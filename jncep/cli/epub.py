from collections import defaultdict
from functools import partial
from html.parser import HTMLParser
import json
import logging
import os
import re
import time

from addict import Dict as Addict
import attr
import click
from ebooklib import epub
import trio

from . import options
from .. import core, epub as core_epub, jncweb, spec
from ..jnclabs import JNCLabsAPI
from .common import CatchAllExceptionsCommand

logger = logging.getLogger(__package__)


@click.command(
    name="epub",
    help="Generate EPUB files for J-Novel Club pre-pub novels",
    cls=CatchAllExceptionsCommand,
)
@click.argument("jnc_url", metavar="JNOVEL_CLUB_URL", required=True)
@options.login_option
@options.password_option
@options.output_option
@click.option(
    "-s",
    "--parts",
    "part_specs",
    help=(
        "Specification of a range of parts to download in the form of "
        "<vol>[.part]:<vol>[.part] [default: All the content linked by "
        "the JNOVEL_CLUB_URL argument, either a single part, a whole volume "
        "or the whole series]"
    ),
)
@options.byvolume_option
@options.images_option
@options.raw_content_option
@options.no_replace_chars_option
def generate_epub(*args, **kwargs):
    trio.run(partial(_main, *args, **kwargs))


async def _main(
    jnc_url,
    email,
    password,
    part_specs,
    output_dirpath,
    is_by_volume,
    is_extract_images,
    is_extract_content,
    is_not_replace_chars,
):
    epub_generation_options = core_epub.EpubGenerationOptions(
        output_dirpath,
        is_by_volume,
        is_extract_images,
        is_extract_content,
        is_not_replace_chars,
    )

    api = JNCLabsAPI()
    try:
        jnc_resource = jncweb.resource_from_url(jnc_url)

        logger.info(f"Login with email '{email}'...")
        await api.login(email, password)

        if part_specs:
            logger.info(f"Using part specification '{part_specs}' ")
            epub_data = await fetch_for_specs(api, jnc_resource, part_specs)
        else:
            # TODO cache + download cover
            # TODO handle exceptions
            # TODO extract images
            # TODO extract content
            # TODO split by volume
            result = Result()
            if jnc_resource.resource_type == jncweb.RESOURCE_TYPE_SERIES:
                await fetch_series_toplevel(api, jnc_resource, result)
                book_details = process_series(result, epub_generation_options)
            elif jnc_resource.resource_type == jncweb.RESOURCE_TYPE_VOLUME:
                await fetch_volume_toplevel(api, jnc_resource, result)
                book_details = process_single_volume(result, epub_generation_options)
            elif jnc_resource.resource_type == jncweb.RESOURCE_TYPE_PART:
                await fetch_part_toplevel(api, jnc_resource, result)
                book_details = process_single_part(result, epub_generation_options)

        output_filename = _to_safe_filename(book_details.title) + ".epub"
        output_filepath = os.path.join(
            epub_generation_options.output_dirpath, output_filename
        )
        create_epub(output_filepath, book_details, epub_generation_options)

    finally:
        if api.is_logged_in:
            try:
                logger.info("Logout...")
                await api.logout()
            except Exception:
                pass


async def fetch_for_specs(api, jnc_resource, part_specs):
    part_spec = spec.analyze_part_specs(part_specs)


# TODO core_epub.EpubGenerationOptions not needed


def create_epub(output_filepath, book_details: "BookDetails", epub_generation_options):
    lang = "en"
    book = epub.EpubBook()
    book.set_identifier(book_details.identifier)
    book.set_title(book_details.title)
    book.set_language(lang)
    book.add_author(book_details.author)

    # metadata for series GH issue #9
    # TODO struct
    collection_id, collection_title, volume_position = book_details.collection
    book.add_metadata(
        "OPF",
        "belongs-to-collection",
        collection_title,
        {"property": "belongs-to-collection", "id": collection_id},
    )
    book.add_metadata(
        "OPF",
        "collection-type",
        "series",
        {"property": "collection-type", "refines": f"#{collection_id}"},
    )
    # as position, set the volume number of the first part in the epub
    # in Calibre, display 1 (I) if not set so a bit better
    # TODO issue on KOBO: if 1, series is not displayed on device
    # really matters?
    book.add_metadata(
        "OPF",
        "group-position",
        str(volume_position),
        {"property": "group-position", "refines": f"#{collection_id}"},
    )

    book.set_cover("cover.jpg", book_details.cover_image.content, False)

    # TODO externalize CSS
    style = """body {color: black;}
h1 {page-break-before: always;}
img {width: 100%; page-break-after: always; page-break-before: always; object-fit: contain;}
p {text-indent: 1.3em;}
.centerp {text-align: center; text-indent: 0em;}
.noindent {text-indent: 0em;}"""
    css = epub.EpubItem(
        uid="style", file_name="book.css", media_type="text/css", content=style
    )
    book.add_item(css)

    cover_page = epub.EpubHtml(title="Cover", file_name="cover.xhtml", lang=lang)
    cover_page.content = '<img src="cover.jpg" alt="cover" />'
    cover_page.add_item(css)
    book.add_item(cover_page)

    image: "Image"
    for image in book_details.images:
        img = epub.EpubImage()
        img.file_name = image.local_filename
        # TODO always ? check ?
        img.media_type = "image/jpeg"
        img.content = image.content
        book.add_item(img)

    # TODO extract inside body html like with previous API ?
    chapters = []
    for i, content in enumerate(book_details.contents):
        c = epub.EpubHtml(
            title=book_details.toc[i], file_name=f"chap_{i}.xhtml", lang=lang
        )
        # explicit encoding to bytes or some issue with lxml on some platforms (PyDroid)
        # some message about USC4 little endian not supported
        c.content = content.encode("utf-8")
        c.add_item(css)
        book.add_item(c)
        chapters.append(c)

    book.toc = chapters

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    book.spine = [cover_page, "nav", *chapters]

    epub.write_epub(output_filepath, book, {})


DTYPE_SERIES = "SERIES"
DTYPE_SERIES_VOLUMES = "SERIES_VOLUMES"
DTYPE_VOLUME = "VOLUME"
DTYPE_VOLUME_PARTS = "VOLUME_PARTS"
DTYPE_PART = "PART"
DTYPE_PART_XHTML = "XHTML"
DTYPE_PART_IMAGE = "IMAGE"
DTYPE_PART_TOC = "TOC"


@attr.s
class Result:
    data = attr.ib(factory=list)
    data_index_by_dtype = attr.ib(factory=lambda: defaultdict(list))
    # TODO add warnings : missing content, etc

    def normalize_slug(self, slug, did):
        for value in self.data:
            if value.did == slug:
                value.did = did

    def add(self, data: "Data"):
        self.data.append(data)
        self.data_index_by_dtype[data.dtype].append(data)

    def get_by_dtype(self, dtype):
        if dtype in self.data_index_by_dtype:
            return self.data_index_by_dtype[dtype]
        else:
            return []


@attr.s
class Data:
    dtype = attr.ib()
    did = attr.ib()
    data = attr.ib()


@attr.s
class Image:
    url = attr.ib()
    content = attr.ib()
    local_filename = attr.ib(None)
    # TODO for the cover
    dimensions = attr.ib(None)


@attr.s
class BookDetails:
    identifier = attr.ib()
    title = attr.ib()
    author = attr.ib()
    collection = attr.ib()
    cover_image = attr.ib()
    toc = attr.ib()
    contents = attr.ib()
    images = attr.ib()


def process_series(
    result: Result, options: core_epub.EpubGenerationOptions
) -> BookDetails:
    pass


def process_single_volume(
    result: Result, options: core_epub.EpubGenerationOptions
) -> BookDetails:
    pass


def process_single_part(
    result: Result, options: core_epub.EpubGenerationOptions
) -> BookDetails:

    part_data = result.get_by_dtype(DTYPE_PART)[0]
    part_id = part_data.did
    part = part_data.data

    volume = result.get_by_dtype(DTYPE_VOLUME)[0].data
    series = result.get_by_dtype(DTYPE_SERIES)[0].data
    content = result.get_by_dtype(DTYPE_PART_XHTML)[0].data
    images = [d.data for d in result.get_by_dtype(DTYPE_PART_IMAGE)]
    parts_in_volume = result.get_by_dtype(DTYPE_VOLUME_PARTS)[0].data
    volumes_in_series = result.get_by_dtype(DTYPE_SERIES_VOLUMES)[0].data

    if not options.is_not_replace_chars:
        # replace chars...
        content = replace_chars(content)
    content = replace_image_urls(content, images)

    identifier = part.slug + str(int(time.time()))
    title = part.title
    author = extract_author(volume.creators)
    index_in_series = extract_volume_index_in_series(volume.legacyId, volumes_in_series)
    # TODO struct
    collection = (series.legacyId, series.title, index_in_series + 1)
    # FIXME placeholder
    # make sure it has one
    cover_image = images[0]
    index_in_volume = extract_part_index_in_volume(part_id, parts_in_volume)
    toc = [f"Part {index_in_volume + 1}"]
    contents = [content]

    book_details = BookDetails(
        identifier, title, author, collection, cover_image, toc, contents, images
    )

    return book_details


def extract_author(creators, default="Unknown Author"):
    for creator in creators:
        if creator.role == "AUTHOR":
            return creator.name
    return default


def extract_part_index_in_volume(did, volume_parts):
    for i, part in enumerate(volume_parts):
        if part.legacyId == did:
            return i

    # TODO custom exception
    raise ValueError(f"Part {did} not found in volume parts !")


def extract_volume_index_in_series(did, series_volumes):
    for i, volume in enumerate(series_volumes):
        if volume.legacyId == did:
            return i

    raise ValueError(f"Volume {did} not found in series volumes !")


def find_with_did(result, did, only_one=False):
    # did can be a slug for top level resource
    values = []
    for d in result.data:
        if d.did == did:
            values.append(d)
            if only_one:
                break
    return values


# TODO simplify. Really needs those funcs ???

# TODO way to indicate failure of some kind
# TODO timeout for the API requests


async def fetch_series(api, series_id, result):
    series_data = await api.fetch_data("series", series_id)
    result.add(Data(DTYPE_SERIES, series_data.legacyId, series_data))
    return series_data


async def fetch_volume(api: JNCLabsAPI, volume_id, result):
    volume_data = await api.fetch_data("volumes", volume_id)
    result.add(Data(DTYPE_VOLUME, volume_data.legacyId, volume_data))
    return volume_data


async def fetch_part(api: JNCLabsAPI, part_id, result):
    part_data = await api.fetch_data("parts", part_id)
    result.add(Data(DTYPE_PART, part_data.legacyId, part_data))
    return part_data


async def fetch_series_for_volume(api: JNCLabsAPI, volume_id, result):
    series_data = await api.fetch_data("volumes", volume_id, "serie")
    result.add(Data(DTYPE_SERIES, series_data.legacyId, series_data))
    return series_data


async def fetch_series_for_part(api: JNCLabsAPI, part_id, result):
    series_data = await api.fetch_data("parts", part_id, "serie")
    result.add(Data(DTYPE_SERIES, series_data.legacyId, series_data))
    return series_data


async def fetch_volume_for_part(api: JNCLabsAPI, part_id, result):
    volume_data = await api.fetch_data("parts", part_id, "volume")
    result.add(Data(DTYPE_VOLUME, volume_data.legacyId, volume_data))
    return volume_data


async def fetch_volume_parts_for_part(api: JNCLabsAPI, part_id, result):
    volume_data = await fetch_volume_for_part(api, part_id, result)
    volume_id = volume_data.legacyId
    parts = await api.fetch_data("volumes", volume_id, "parts")
    result.add(Data(DTYPE_VOLUME_PARTS, volume_id, parts.parts))
    return parts.parts


async def fetch_series_volumes_for_part(api: JNCLabsAPI, part_id, result):
    # TODO paginate
    series_data = await fetch_series_for_part(api, part_id, result)
    series_id = series_data.legacyId
    volumes = await api.fetch_data("series", series_id, "volumes")
    result.add(Data(DTYPE_SERIES_VOLUMES, series_id, volumes.volumes))
    return volumes.volumes


# TODO have a params struct that includes only_volumes
# TODO have params struct that indicate to go deep (instead of the name)
async def deep_fetch_volumes_for_series(
    api: JNCLabsAPI, nursery, series_id, result, only_volumes=None
):
    # TODO paginate
    # TODO same content as /volumes/volumeId ? verif
    volumes = await api.fetch_data("series", series_id, "volumes")
    result.add(Data(DTYPE_SERIES_VOLUMES, series_id, volumes.volumes))
    for i, volume_data in enumerate(volumes.volumes):
        volume_id = volume_data.legacyId
        result.add(Data(DTYPE_VOLUME, volume_id, volume_data))

        # TODO transform into spec for volume + part in volume
        volume_num = i + 1
        if not only_volumes or volume_num in only_volumes:
            nursery.start_soon(partial(deep_fetch_parts_for_volume, volume_id))


async def deep_fetch_parts_for_volume(api: JNCLabsAPI, nursery, volume_id, result):
    # TODO paginate
    parts = await api.fetch_data("volumes", volume_id, "parts")
    result.add(Data(DTYPE_VOLUME_PARTS, volume_id, parts.parts))
    for part_data in parts.parts:
        part_id = part_data.legacyId
        result.add(Data(DTYPE_PART, part_id, part_data))
        nursery.start_soon(partial(deep_fetch_content_for_part, part_id))


async def deep_fetch_part(api: JNCLabsAPI, nursery, part_id, result):
    # TODO make obvious the fact that part_id is acutally the slug
    # and why we do the following first
    part_data = await fetch_part(api, part_id, result)
    part_id = part_data.legacyId
    await deep_fetch_content_for_part(api, nursery, part_id, result)


async def deep_fetch_content_for_part(api: JNCLabsAPI, nursery, part_id, result):
    # TODO handle unavailable content (not preview + not catchup)
    # TODO handle errors
    content = await api.fetch_content(part_id, "data.xhtml")

    result.add(Data(DTYPE_PART_XHTML, part_id, content))
    img_urls = _img_urls(content)
    if len(img_urls) > 0:
        # TODO handle failures
        for img_url in img_urls:
            nursery.start_soon(partial(download_image, api, part_id, img_url, result))


async def fetch_toc_for_part(api: JNCLabsAPI, part_id, result):
    # TODO paginate ?
    content = await api.fetch_xhtml(part_id)
    toc = Addict(json.loads(content))
    result.add(Data(DTYPE_PART_TOC, part_id, toc))


async def download_image(api: JNCLabsAPI, part_id, img_url, result):
    img_bytes = await api.fetch_image_from_cdn(img_url)
    result.add(Data(DTYPE_PART_IMAGE, part_id, Image(img_url, img_bytes)))


class ImgUrlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.img_urls = []

    def handle_starttag(self, tag, tag_attrs):
        if tag != "img":
            return

        for tag_attr in tag_attrs:
            if tag_attr[0] == "src":
                self.img_urls.append(tag_attr[1])
                break


def _img_urls(content):
    parser = ImgUrlParser()
    parser.feed(content)
    return parser.img_urls


def replace_chars(content):
    # both the chars to replace and replacement are hardcoded
    # U+2671 => East Syriac Cross
    # U+25C6 => Black Diamond
    # U+1F3F6 => Black Rosette
    # U+25C7 => White Diamond
    # U+2605 => Black star
    chars_to_replace = ["\u2671", "\u25C6", "\U0001F3F6", "\u25C7", "\u2605"]
    replacement_char = "**"
    regex = "|".join(chars_to_replace)
    content = re.sub(regex, replacement_char, content)
    return content


def _to_safe_filename(name):
    s = re.sub("[^0-9a-zA-Z]+", "_", name).strip("_")
    return s


def replace_image_urls(content, images):
    for image in images:
        # the filename relative to the epub content root
        # file will be added to the Epub archive
        # ext is almost always .jpg but sometimes it is .jpeg
        # splitext  works fine with a url
        root, ext = os.path.splitext(image.url)
        new_local_filename = _to_safe_filename(root) + ext
        image.local_filename = new_local_filename
        content = content.replace(image.url, new_local_filename)

    return content


async def fetch_series_toplevel(api, jnc_resource, result):
    series_slug = jnc_resource.slug
    async with trio.open_nursery() as nursery:
        nursery.start_soon(partial(fetch_series, api, series_slug, result))
        nursery.start_soon(
            partial(deep_fetch_volumes_for_series, api, nursery, series_slug, result)
        )

    # norm to use only the id
    series = result.get_by_dtype(DTYPE_SERIES)[0]
    series_id = series.did
    result.normalize_slug(series_slug, series_id)


async def fetch_volume_toplevel(api, jnc_resource, result):
    if jnc_resource.is_new_website:
        # for volume on new website => where is a tuple (series_slug, volume num)
        series_slug, volume_number = jnc_resource.slug

        # first fetch series since we have the slug for it
        # will fetch metadata of all volumes + parts for this volume
        only_volumes = [volume_number]
        async with trio.open_nursery() as nursery:
            nursery.start_soon(partial(fetch_series, api, series_slug, result))
            nursery.start_soon(
                partial(
                    deep_fetch_volumes_for_series,
                    api,
                    nursery,
                    series_slug,
                    result,
                    only_volumes,
                )
            )

        series = result.get(DTYPE_SERIES)[0]
        series_id = series.did
        # not needed I think but done anyway in case I change something and forget
        result.normalize_slug(series_slug, series_id)
    else:
        volume_slug = jnc_resource.slug
        async with trio.open_nursery() as nursery:
            nursery.start_soon(
                partial(fetch_series_for_volume, api, volume_slug, result)
            )
            nursery.start_soon(partial(fetch_volume, api, volume_slug, result))
            nursery.start_soon(
                partial(deep_fetch_parts_for_volume, api, nursery, volume_slug, result)
            )

        volume = result.get_by_dtype(DTYPE_VOLUME)[0]
        volume_id = volume.did
        result.normalize_slug(volume_slug, volume_id)

        # FIXME finish.
        # TODO still needed ? not a lot of work anyway


async def fetch_part_toplevel(api, jnc_resource, result):
    part_slug = jnc_resource.slug
    async with trio.open_nursery() as nursery:
        nursery.start_soon(partial(fetch_volume_parts_for_part, api, part_slug, result))
        nursery.start_soon(
            partial(fetch_series_volumes_for_part, api, part_slug, result)
        )
        nursery.start_soon(partial(deep_fetch_part, api, nursery, part_slug, result))

    part = result.get_by_dtype(DTYPE_PART)[0]
    part_id = part.did
    result.normalize_slug(part_slug, part_id)
