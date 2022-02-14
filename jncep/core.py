from collections import namedtuple
from datetime import datetime, timezone
from functools import partial
from html.parser import HTMLParser
import logging
import os
import re
import sys
import time
from typing import List

import attr
import dateutil.parser
import trio

from . import epub, jncweb, spec
from .jnclabs import JNCLabsAPI
from .model import Image, Part, Series, Volume
from .trio_utils import background, gather
from .utils import green, to_safe_filename

logger = logging.getLogger(__name__)


class NoRequestedPartAvailableError(Exception):
    pass


EpubGenerationOptions = namedtuple(
    "EpubGenerationOptions",
    [
        "output_dirpath",
        "is_by_volume",
        "is_extract_images",
        "is_extract_content",
        "is_not_replace_chars",
    ],
)


@attr.s
class IdentifierSpec:
    type_ = attr.ib()
    volume_id = attr.ib(None)
    part_id = attr.ib(None)

    def has_volume(self, volume) -> bool:
        if self.type_ == spec.SERIES:
            return True

        return self.volume_id == volume.volume_id

    def has_part(self, ref_part) -> bool:
        # assumes has_volume already checked with the volume_id
        if self.type_ in (spec.SERIES, spec.VOLUME):
            return True

        return self.part_id == ref_part.part_id


class JNCEPSession:
    def __init__(self, email, password):
        self.api = JNCLabsAPI()
        self.email = email
        self.password = password
        self.now = datetime.now(tz=timezone.utc)

    async def __aenter__(self) -> "JNCEPSession":
        await self.login(self.email, self.password)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.logout()
        return False

    async def login(self, email, password):
        logger.info(f"Login with email '{email}'...")
        return await self.api.login(email, password)

    async def logout(self):
        if self.api.is_logged_in:
            try:
                logger.info("Logout...")
                await self.apiapi.logout()
            except Exception:
                pass


async def create_epub(series, volumes, parts, epub_generation_options):
    book_details = process_series(series, volumes, parts, epub_generation_options)

    if epub_generation_options.is_extract_content:
        await extract_content(parts, epub_generation_options)

    if epub_generation_options.is_extract_images:
        await extract_images(parts, epub_generation_options)

    for book_details_i in book_details:
        output_filename = to_safe_filename(book_details_i.title) + ".epub"
        output_filepath = os.path.join(
            epub_generation_options.output_dirpath, output_filename
        )
        # TODO write to memory then async fs write here ? (uses epublib
        # which is sync anyway)
        epub.create_epub(output_filepath, book_details_i)

        logger.info(green(f"Success! EPUB generated in '{output_filepath}'!"))


def process_series(
    series, volumes, parts, options: EpubGenerationOptions
) -> epub.BookDetails:

    # prepare content
    for part in parts:
        content_for_part = part.content
        if not options.is_not_replace_chars:
            content_for_part = _replace_chars(content_for_part)

        # some parts do not have an image
        if part.images:
            imgs = part.images
            content_for_part = _replace_image_urls(content_for_part, imgs)

        part.epub_content = content_for_part

    if options.is_by_volume:
        book_details = []
        for volume in volumes:
            volume_parts = [part for part in parts if part.volume is volume]
            volume_details = _process_single_epub_content(
                series, [volume], volume_parts
            )
            book_details.append(volume_details)
    else:
        book_details = [_process_single_epub_content(series, volumes, parts)]

    return book_details


def _process_single_epub_content(series, volumes, parts):
    # order of volumes and parts must match

    # TODO suffix final complete : not in api but in web page for series
    # data for React contains what is needed in JSON

    # representative volume
    repr_volume = volumes[0]
    author = _extract_author(repr_volume.raw_data.creators)

    # representative part
    repr_part = parts[0]
    volume_num = repr_part.volume.num
    part_num = repr_part.num_in_volume

    # TODO in case multiple volumes, do not set volume num? or do
    # something else
    collection = epub.CollectionMetadata(
        series.raw_data.legacyId, series.raw_data.title, volume_num
    )

    # cover should always be there : error if problem with downloading
    # TODO handle problem with missing cover => use dummy jpeg
    cover_image = repr_volume.cover

    contents = [part.epub_content for part in parts]

    if len(parts) == 1:
        # single part
        part = parts[0]
        volume_num = part.volume.num
        part_num = part.num_in_volume

        title = f"{part.raw_data.title}"
        # single part => single volume: part numbers relative to
        # that volume
        toc = [f"Part {part_num}"]
    else:
        volume_index = set([v.num for v in volumes])
        if len(volume_index) > 1:
            volume_nums = sorted(list(volume_index))
            volume_nums = [str(vn) for vn in volume_nums]
            volume_nums = ", ".join(volume_nums[:-1]) + " & " + volume_nums[-1]
            title_base = f"{series.raw_data.title}: Volumes {volume_nums}"

            volume_num0 = parts[0].volume.num
            part_num0 = parts[0].num_in_volume
            volume_num1 = parts[-1].volume.num
            part_num1 = parts[-1].num_in_volume

            part_nums = f"Parts {volume_num0}.{part_num0} to {volume_num1}.{part_num1}"

            toc = [part.raw_data.title for part in parts]
            title = f"{title_base} [{part_nums}]"
        else:
            volume = volumes[0]
            title_base = volume.raw_data.title

            toc = [f"Part {part.num_in_volume}" for part in parts]

            part_num0 = parts[0].num_in_volume
            part_num1 = parts[-1].num_in_volume

            title = f"{title_base} [Parts {part_num0} to {part_num1}]"

    identifier = series.raw_data.slug + str(int(time.time()))

    images = [img for part in parts for img in part.images]

    book_details = epub.BookDetails(
        identifier, title, author, collection, cover_image, toc, contents, images
    )

    return book_details


async def extract_images(parts, epub_generation_options):
    async with trio.open_nursery() as n:
        for part in parts:
            images = part.images

            for image in images:
                # change filename to something more readable since visible to
                # user
                _, ext = os.path.splitext(image.local_filename)
                img_filename = (
                    to_safe_filename(part.raw_data.title)
                    # extension at the end
                    + f"_Image_{image.order_in_part}{ext}"
                )
                img_filepath = os.path.join(
                    epub_generation_options.output_dirpath, img_filename
                )
                n.start_soon(_write_bytes, img_filepath, image.content)


async def extract_content(parts, epub_generation_options):
    async with trio.open_nursery() as n:
        for part in parts:
            content = part.content
            content_filename = to_safe_filename(part.raw_data.title) + ".html"
            content_filepath = os.path.join(
                epub_generation_options.output_dirpath, content_filename
            )
            n.start_soon(_write_str, content_filepath, content)


def _extract_author(creators, default="Unknown Author"):
    for creator in creators:
        if creator.role == "AUTHOR":
            return creator.name
    return default


def _replace_chars(content):
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


def _replace_image_urls(content, images: List[Image]):
    for image in images:
        # the filename relative to the epub content root
        # file will be added to the Epub archive
        # ext is almost always .jpg but sometimes it is .jpeg
        # splitext  works fine with a url
        root, ext = os.path.splitext(image.url)
        new_local_filename = to_safe_filename(root) + ext
        image.local_filename = new_local_filename
        content = content.replace(image.url, new_local_filename)

    return content


def all_parts_meta(series):
    return [part for volume in series.volumes if volume.parts for part in volume.parts]


async def to_part_spec(session, jnc_resource):
    if jnc_resource.resource_type == jncweb.RESOURCE_TYPE_SERIES:
        return IdentifierSpec(spec.SERIES)

    elif jnc_resource.resource_type == jncweb.RESOURCE_TYPE_VOLUME:
        if jnc_resource.is_new_website:
            # for volume on new website => where is a tuple (series_slug,
            # volume num)
            series_slug, volume_number = jnc_resource.slug

            volumes = await fetch_volumes_for_series(session.api, series_slug)

            volume_index = volume_number - 1
            if volume_index not in range(len(volumes)):
                raise jncweb.BadWebURLError(
                    f"Incorrect volume number in URL: {jnc_resource.url}"
                )

            volume = volumes[volume_index]
        else:
            volume_slug = jnc_resource.slug
            volume = await session.api.fetch_data("volumes", volume_slug)

        return IdentifierSpec(spec.VOLUME, volume.legacyId)

    elif jnc_resource.resource_type == jncweb.RESOURCE_TYPE_PART:
        async with trio.open_nursery() as n:
            f_part = background(
                n, partial(session.api.fetch_data, "parts", jnc_resource.slug)
            )
            f_volume = background(
                n, partial(session.api.fetch_data, "parts", jnc_resource.slug, "volume")
            )
            part, volume = await gather(n, [f_part, f_volume]).get()

        return IdentifierSpec(spec.PART, volume.legacyId, part.legacyId)


async def resolve_series(session, jnc_resource):
    if jnc_resource.resource_type == jncweb.RESOURCE_TYPE_SERIES:
        series_slug = jnc_resource.slug
        series_raw_data = await session.api.fetch_data("series", series_slug)
    elif jnc_resource.resource_type == jncweb.RESOURCE_TYPE_VOLUME:
        if jnc_resource.is_new_website:
            series_slug, _ = jnc_resource.slug
            series_raw_data = await session.api.fetch_data("series", series_slug)
        else:
            volume_slug = jnc_resource.slug
            series_raw_data = await session.api.fetch_data(
                "volumes", volume_slug, "serie"
            )
    elif jnc_resource.resource_type == jncweb.RESOURCE_TYPE_PART:
        part_slug = jnc_resource.slug
        series_raw_data = await session.api.fetch_data("parts", part_slug, "serie")

    series = Series(series_raw_data, series_raw_data.legacyId)
    return series


async def fill_meta(session, series, volume_callback=None):
    volumes = await fetch_volumes_meta(session, series.series_id)
    series.volumes = volumes
    for volume in volumes:
        volume.series = series

    await fill_all_parts_meta_background(session, volumes, volume_callback)

    # similar to what we got from the original JNC API
    return series


async def fetch_volumes_meta(session, series_id):
    volumes_raw_data = await fetch_volumes_for_series(session, series_id)

    volumes = []
    for i, volume_raw_data in enumerate(volumes_raw_data):
        volume_id = volume_raw_data.legacyId
        volume_num = i + 1

        volume = Volume(volume_raw_data, volume_id, volume_num)
        volumes.append(volume)

    return volumes


async def fill_all_parts_meta_background(session, volumes, volume_callback=None):
    async with trio.open_nursery() as n:
        volumes_meta = []
        futures = []
        for volume in volumes:
            if volume_callback and not volume_callback(volume):
                continue

            f_parts = background(
                n, partial(fetch_parts_meta, session, volume.volume_id)
            )
            futures.append(f_parts)
            volumes_meta.append(volume)

        all_parts = await gather(n, futures).get()
        for i, parts in enumerate(all_parts):
            volume = volumes_meta[i]

            volume.parts = parts
            for part in parts:
                part.volume = volume


async def fetch_parts_meta(session, volume_id):
    parts_raw_data = await fetch_parts_for_volume(session, volume_id)
    parts = []

    for i, part_raw_data in enumerate(parts_raw_data):
        part_id = part_raw_data.legacyId
        part_num = i + 1
        part = Part(part_raw_data, part_id, part_num)
        parts.append(part)

    return parts


async def fetch_volumes_for_series(session, series_id):
    volumes = [
        volume
        async for volume in session.api.paginate(
            partial(session.api.fetch_data, "series", series_id, "volumes")
        )
    ]
    return volumes


async def fetch_parts_for_volume(session, volume_id):
    parts = [
        part
        async for part in session.api.paginate(
            partial(session.api.fetch_data, "volumes", volume_id, "parts")
        )
    ]
    return parts


async def fetch_content(session, parts):
    async with trio.open_nursery() as n:
        f_contents = []
        for part in parts:
            f_content = background(
                n, partial(fetch_content_and_images_for_part, session, part.part_id)
            )
            f_contents.append(f_content)

        contents = await gather(n, f_contents).get()

    parts_content = {}
    for i, content_image in enumerate(contents):
        part = parts[i]
        parts_content[part.part_id] = content_image
    return parts_content


def is_part_available(now, part):
    if part.raw_data.preview:
        return True

    expiration_data = dateutil.parser.parse(part.raw_data.expiration)
    return expiration_data > now


async def fetch_content_and_images_for_part(session, part_id):
    # TODO catch error + event => in case expires between checking before and
    # running this (case to check)
    content = await session.api.fetch_content(part_id, "data.xhtml")
    img_urls = extract_image_urls(content)
    if len(img_urls) > 0:
        f_images = []
        async with trio.open_nursery() as n:
            for img_url in img_urls:
                f_image = background(n, partial(fetch_image, session, img_url))
                f_images.append(f_image)

            images = await gather(n, f_images).get()

        images = list(filter(None, images))
        for i, image in enumerate(images):
            image.order_in_part = i + 1

    else:
        images = []

    return content, images


async def fetch_image(session, img_url):
    try:
        img_bytes = await session.api.fetch_url(img_url)
        image = Image(img_url, img_bytes)
        return image
    except Exception as ex:
        # TODO event error downloading image isntead
        logger.info("Error download image with URL: {img_url}")
        logger.debug(f"Error downloading image : {ex}", exc_info=sys.exc_inf())
        return None


class StopHTMLParsing(Exception):
    pass


class ImgUrlParser(HTMLParser):
    def __init__(self, is_stop_after_text=False):
        super().__init__()

        self.img_urls = []
        # this is to handle covers : special significance for
        # first image before any text
        # TODO separte parser ?
        self.is_stop_after_text = is_stop_after_text
        self.is_after_body = False
        self.is_after_first_text_in_body = False

    def handle_starttag(self, tag, tag_attrs):
        if tag == "img":
            self._handle_img(tag_attrs)

        if tag == "body":
            self.is_after_body = True

    def _handle_img(self, tag_attrs):
        for tag_attr in tag_attrs:
            if tag_attr[0] == "src":
                self.img_urls.append(tag_attr[1])
                break

    def handle_data(self, data):
        if self.is_after_body:
            self.is_after_first_text_in_body = True

            if self.is_stop_after_text:
                raise StopHTMLParsing()


def extract_image_urls(content):
    parser = ImgUrlParser()
    parser.feed(content)
    return parser.img_urls


def _top_image(content):
    # TODO implement
    pass


async def fetch_covers(session, volumes):
    async with trio.open_nursery() as n:
        f_covers = []
        for volume in volumes:
            f_cover = background(n, partial(fetch_cover_for_volume, session, volume))
            f_covers.append(f_cover)

        covers = await gather(n, f_covers).get()

    volumes_cover = {}
    for i, cover in enumerate(covers):
        volume = volumes[i]
        volumes_cover[volume.volume_id] = cover
    return volumes_cover


async def fetch_cover_for_volume(session, volume):
    cover_url = volume.raw_data.cover.coverUrl
    cover = await fetch_image(session, cover_url)
    # TODO also check the content of each part for image at the top of the part
    # for high resolution

    return cover


def relevant_volumes_for_cover(volumes, is_by_volume):
    if is_by_volume:
        volumes_cover = [volumes[0]]
    else:
        volumes_cover = volumes
    return volumes_cover


def relevant_volumes_and_parts_for_content(series, part_filter):
    # some volumes may be empty after checking the parts => so getting
    # the volumes from the parts
    volumes_to_download = {}
    parts_to_download = []
    for volume in series.volumes:
        if not volume.parts:
            continue
        for part in volume.parts:
            if part_filter(part):
                parts_to_download.append(part)
                volumes_to_download[part.volume.volume_id] = volume

    # dict is ordered from py 3.6 so no need to sort
    volumes_to_download = list(volumes_to_download.values())

    return volumes_to_download, parts_to_download


async def fill_covers_and_content(session, cover_volumes, content_parts):
    async with trio.open_nursery() as n:
        f_content = background(n, partial(fetch_content, session, content_parts))
        f_covers = background(n, partial(fetch_covers, session, cover_volumes))

        contents, covers = await gather(n, [f_content, f_covers]).get()

    for part in content_parts:
        if part.part_id in contents:
            content, images = contents[part.part_id]
            part.content = content
            part.images = images

    for volume in cover_volumes:
        if volume.volume_id in covers:
            volume.cover = covers[volume.volume_id]


async def _write_bytes(filepath, content):
    async with await trio.open_file(filepath, "wb") as img_f:
        await img_f.write(content)


async def _write_str(filepath, content):
    async with await trio.open_file(filepath, "w", encoding="utf-8") as img_f:
        await img_f.write(content)
