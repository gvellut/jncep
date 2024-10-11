from collections import namedtuple
from datetime import datetime, timezone
from functools import partial
from html.parser import HTMLParser
import logging
import os
import platform
import re
import sys
import time
from typing import List

from addict import Dict as Addict
import dateutil.parser
import trio

from . import epub, jnclabs, jncweb, spec, utils
from .model import Image, Part, Series, Volume
from .trio_utils import bag
from .utils import is_debug, to_safe_filename

logger = logging.getLogger(__name__)
console = utils.getConsole()


EpubGenerationOptions = namedtuple(
    "EpubGenerationOptions",
    [
        "output_dirpath",
        "is_by_volume",
        "is_extract_images",
        "is_extract_content",
        "is_not_replace_chars",
        "style_css_path",
    ],
)

EventFeed = namedtuple(
    "EventFeed",
    [
        "event_feed",
        "has_reached_limit",
        "first_event_date",
    ],
)


class FilePathTooLongError(Exception):
    pass


class SeriesNotANovelError(Exception):
    pass


class JNCEPSession:
    _GLOBAL_SESSION_INSTANCE = None

    def __init__(self, email, password):
        self.api = jnclabs.JNCLabsAPI()
        self.email = email
        self.password = password
        self.now = datetime.now(tz=timezone.utc)

    async def __aenter__(self) -> "JNCEPSession":
        if JNCEPSession._GLOBAL_SESSION_INSTANCE:
            # nested
            return JNCEPSession._GLOBAL_SESSION_INSTANCE

        await self.login(self.email, self.password)
        # current session is the top level session
        JNCEPSession._GLOBAL_SESSION_INSTANCE = self
        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            console.stop_status()
        except Exception:
            pass

        if JNCEPSession._GLOBAL_SESSION_INSTANCE != self:
            # nested ; do not logout => leave it to the top level session
            return False

        # current session is the top level session
        JNCEPSession._GLOBAL_SESSION_INSTANCE = None
        await self.logout()
        return False

    async def login(self, email, password):
        display_email = email
        if is_debug():
            # hide for privacy in case the trace is copied to GH issue tracker
            display_email = re.sub(
                r"(?<=.)(.*)(?=@)", lambda x: "*" * len(x.group(1)), email
            )
            display_email = re.sub(
                r"(?<=@.)(.*)(?=\.)", lambda x: "*" * len(x.group(1)), display_email
            )
        msg = f"Login with email '[highlight]{display_email}[/]'..."
        console.status(msg)
        token = await self.api.login(email, password)

        emoji = ""
        if console.is_advanced():
            emoji = "\u26A1 "
        console.info(f"{emoji}Logged in with email '[highlight]{display_email}[/]'")
        console.status("...")
        return token

    async def logout(self):
        if self.api.is_logged_in:
            try:
                console.info("Logout...")
                await self.api.logout()
            except (trio.MultiError, Exception) as ex:
                logger.debug(f"Error logout: {ex}", exc_info=sys.exc_info())


async def create_epub(series, volumes, parts, epub_generation_options):
    book_details = process_series(series, volumes, parts, epub_generation_options)

    utils.ensure_directory_exists(epub_generation_options.output_dirpath)

    if epub_generation_options.is_extract_content:
        await extract_content(parts, epub_generation_options)

    if epub_generation_options.is_extract_images:
        await extract_images(parts, epub_generation_options)

    extension = ".epub"
    for book_details_i in book_details:
        output_filename = to_safe_filename(book_details_i.title) + extension
        output_filepath = os.path.join(
            epub_generation_options.output_dirpath, output_filename
        )

        seg_volume = book_details_i.title_segments.volume
        seg_part = book_details_i.title_segments.part
        output_filepath = _to_max_len_filepath(
            output_filepath,
            book_details_i.title_segments.series_title,
            book_details_i.title_segments.series_slug,
            f" {seg_volume} {seg_part}",
            extension,
        )

        # TODO write to memory then async fs write here ? (uses epublib
        # which is sync anyway)
        # or trio.to_thread.run_sync or inside
        epub.output_epub(
            output_filepath, book_details_i, epub_generation_options.style_css_path
        )

        # laughing face
        emoji = ""
        if console.is_advanced():
            emoji = "\U0001F600 "
        console.info(
            f"{emoji}Success! EPUB generated in '{output_filepath}'!",
            style="success",
        )


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

    # representative volume: First
    repr_volume = volumes[0]
    author = _extract_author(repr_volume.raw_data.creators)
    volume_num = repr_volume.num

    # in case of multiple volumes, this will set the number of the first volume
    # in the epub
    # in Calibre, display 1 (I) if not set so a bit better
    collection = epub.CollectionMetadata(
        series.raw_data.id, series.raw_data.title, volume_num
    )

    # cover can be None (handled in epub gen proper)
    cover_image = repr_volume.cover

    contents = [part.epub_content for part in parts]

    if len(parts) == 1:
        # single part
        part = parts[0]
        volume_num = part.volume.num
        part_num = part.num_in_volume

        suffix = ""
        if _is_part_final(part):
            suffix = " [Final]"

        title = f"{part.raw_data.title}{suffix}"
        # single part => single volume: part numbers relative to
        # that volume
        toc = [f"Part {part_num}"]
        title_segments = Addict(
            {
                "series_title": series.raw_data.title,
                "series_slug": series.raw_data.slug,
                "volume": f"Volume {volume_num}",
                "part": f"Part {part_num}",
            }
        )
    else:
        volume_index = set([v.num for v in volumes])
        if len(volume_index) > 1:
            volume_nums = sorted(list(volume_index))
            volume_nums = [str(vn) for vn in volume_nums]
            volume_nums = ", ".join(volume_nums[:-1]) + " & " + volume_nums[-1]
            volume_segment = f"Volumes {volume_nums}"
            title_base = f"{series.raw_data.title}: {volume_segment}"

            volume_num0 = parts[0].volume.num
            part_num0 = parts[0].num_in_volume
            volume_num1 = parts[-1].volume.num
            part_num1 = parts[-1].num_in_volume

            # check only last part in the epub
            suffix = ""
            if _is_part_final(parts[-1]):
                suffix = " - Final"

            part_segment = (
                f"Parts {volume_num0}.{part_num0} to "
                f"{volume_num1}.{part_num1}{suffix}"
            )

            toc = [part.raw_data.title for part in parts]
            title = f"{title_base} [{part_segment}]"
            title_segments = Addict(
                {
                    "series_title": series.raw_data.title,
                    "series_slug": series.raw_data.slug,
                    "volume": volume_segment,
                    "part": part_segment,
                }
            )
        else:
            volume = volumes[0]
            title_base = volume.raw_data.title

            toc = [f"Part {part.num_in_volume}" for part in parts]

            part_num0 = parts[0].num_in_volume
            part_num1 = parts[-1].num_in_volume

            is_complete = _is_volume_complete(volume, parts)
            if is_complete:
                part_segment = "Complete"
            else:
                # check the last part in the epub
                suffix = ""
                if _is_part_final(parts[-1]):
                    suffix = " - Final"
                part_segment = f"Parts {part_num0} to {part_num1}{suffix}"

            title = f"{title_base} [{part_segment}]"
            title_segments = Addict(
                {
                    "series_title": series.raw_data.title,
                    "series_slug": series.raw_data.slug,
                    "volume": f"Volume {volume.num}",
                    "part": part_segment,
                }
            )

    identifier = series.raw_data.slug + str(int(time.time()))

    images = [img for part in parts for img in part.images]

    book_details = epub.BookDetails(
        identifier,
        title,
        title_segments,
        author,
        collection,
        cover_image,
        toc,
        contents,
        images,
    )

    return book_details


def _is_part_final(part):
    volume = part.volume
    if volume.raw_data.get("totalParts") is None:
        # assume not final
        return False
    return part.num_in_volume == volume.raw_data.totalParts


def _is_volume_complete(volume, parts):
    # need parts as args : the requested parts that will be included in the final
    # epub
    if volume.raw_data.get("totalParts") is None:
        # assume not complete
        return False
    return volume.raw_data.totalParts == len(parts)


async def extract_images(parts, epub_generation_options):
    async with trio.open_nursery() as n:
        for part in parts:
            images = part.images

            for image in images:
                # change filename to something more readable since visible to
                # user
                _, ext = os.path.splitext(image.local_filename)
                suffix = f"_Image_{image.order_in_part}"
                img_filename = to_safe_filename(part.raw_data.title) + suffix + ext
                img_filepath = os.path.join(
                    epub_generation_options.output_dirpath, img_filename
                )

                img_filepath = _to_max_len_filepath(
                    img_filepath,
                    part.series.raw_data.title,
                    part.series.raw_data.slug,
                    f" Volume {part.volume.num} Part {part.num_in_volume}{suffix}",
                    ext,
                )

                n.start_soon(_write_bytes, img_filepath, image.content)


async def extract_content(parts, epub_generation_options):
    async with trio.open_nursery() as n:
        for part in parts:
            content = part.content
            extension = ".html"
            content_filename = to_safe_filename(part.raw_data.title) + extension
            content_filepath = os.path.join(
                epub_generation_options.output_dirpath, content_filename
            )

            content_filepath = _to_max_len_filepath(
                content_filepath,
                part.series.raw_data.title,
                part.series.raw_data.slug,
                f" Volume {part.volume.num} Part {part.num_in_volume}",
                extension,
            )

            n.start_soon(_write_str, content_filepath, content)


def _to_max_len_filepath(
    original_filepath,
    _series_title,
    series_slug,
    suffix,
    extension,
):
    # do some processing or error when writing (for example, see Backstabbed ....)
    system = platform.system()
    if system == "Windows":
        max_name_len = 255
        max_path_len = 255
    elif system == "Darwin":
        # mac OS
        max_name_len = 255
        max_path_len = 1024
    elif system == "Linux":
        max_name_len = 255
        max_path_len = 4096
    else:
        # do nothing for the others
        return original_filepath

    dirpath, original_filename = os.path.split(original_filepath)

    if len(original_filepath) < max_path_len and len(original_filename) < max_name_len:
        return original_filepath

    # basic substitution : replace title by slug (usually shorter)
    # TODO do not do this ? can be inconsistent depending on suffix length (but should
    # be rare) + use series_title for shorten instead of slug
    subs_filename = to_safe_filename(series_slug + suffix) + extension
    subs_filepath = os.path.join(dirpath, subs_filename)
    if len(subs_filepath) < max_path_len and len(subs_filename) < max_name_len:
        return subs_filepath

    # will need to shorten slug part

    # minimum size for keeping recognizable (arbitrary)
    min_title_short_len = 10
    mandatory_len = len(suffix) + len(extension)
    # to_safe_filename below will not lenghten the title+suffix part
    # (will reduce actually: so final name will possibly be shorter than max_name)
    # -1 for the / between dirpath and filename (not already in dirpath)
    max_part_title_short_len = min(
        max_name_len - mandatory_len, max_path_len - len(dirpath) - 1 - mandatory_len
    )
    if max_part_title_short_len < min_title_short_len:
        # will not manage to create a substition path
        raise FilePathTooLongError(
            f"'{original_filepath}' too long for {system} and cannot shorten! "
            f"PATH_MAX={max_path_len}, NAME_MAX={max_name_len}"
        )

    # TODO use series instead ?
    title_short = series_slug[:max_part_title_short_len]
    subs_filename = to_safe_filename(title_short + suffix) + extension
    subs_filepath = os.path.join(dirpath, subs_filename)
    return subs_filepath


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
        # the file will be added to the Epub archive
        content = content.replace(image.url, image.local_filename)

    return content


def all_parts_meta(series):
    return [part for volume in series.volumes if volume.parts for part in volume.parts]


async def to_part_spec(series, jnc_resource):
    if jnc_resource.resource_type == jncweb.RESOURCE_TYPE_SERIES:
        # if here, the URL in resource must have been correct (since series is filled)
        return spec.IdentifierSpec(spec.SERIES)

    elif jnc_resource.resource_type == jncweb.RESOURCE_TYPE_VOLUME:
        if jnc_resource.is_new_website:
            # for volume on new website => where is a tuple (series_slug,
            # volume num)
            _, volume_number = jnc_resource.slug
            volumes = series.volumes
            volume_index = volume_number - 1
            if volume_index not in range(len(volumes)):
                raise jncweb.BadWebURLError(
                    f"Incorrect volume number in URL: {jnc_resource.url}"
                )

            volume = volumes[volume_index]
        else:
            volume_slug = jnc_resource.slug
            for volume in series.volumes:
                if volume.raw_data.slug == volume_slug:
                    break
            else:
                raise jncweb.BadWebURLError(
                    f"Incorrect URL for volume: {jnc_resource.url}"
                )

        return spec.IdentifierSpec(spec.VOLUME, volume.volume_id)

    elif jnc_resource.resource_type == jncweb.RESOURCE_TYPE_PART:
        part_slug = jnc_resource.slug
        for volume in series.volumes:
            for part in volume.parts:
                if part.raw_data.slug == part_slug:
                    break
            else:
                continue
            break
        else:
            raise jncweb.BadWebURLError(f"Incorrect URL for part: {jnc_resource.url}")

        return spec.IdentifierSpec(spec.PART, volume.volume_id, part.part_id)


async def resolve_series(session: JNCEPSession, jnc_resource):
    # id or slug to identify the series
    if jnc_resource.resource_type == jncweb.RESOURCE_TYPE_SERIES:
        series_slug = jnc_resource.slug
        return series_slug
    elif jnc_resource.resource_type == jncweb.RESOURCE_TYPE_VOLUME:
        if jnc_resource.is_new_website:
            series_slug, _ = jnc_resource.slug
            return series_slug
        else:
            volume_slug = jnc_resource.slug
            series_raw_data = await session.api.fetch_data(
                "volumes", volume_slug, "serie"
            )
            return series_raw_data.id
    elif jnc_resource.resource_type == jncweb.RESOURCE_TYPE_PART:
        part_slug = jnc_resource.slug
        series_raw_data = await session.api.fetch_data("parts", part_slug, "serie")
        return series_raw_data.id


async def fetch_meta(session, series_id_or_slug):
    series_agg = await session.api.fetch_data("series", series_id_or_slug, "aggregate")
    series_raw_data = series_agg.series
    series = Series(series_raw_data, series_raw_data.id)

    volumes = []
    series.volumes = volumes
    # maybe could happen there is no volumes attr (will need to check when there is a
    # new series)
    if "volumes" in series_agg:
        for i, volume_with_parts in enumerate(series_agg.volumes):
            volume_raw_data = volume_with_parts.volume
            volume_id = volume_raw_data.id
            volume_num = i + 1

            volume = Volume(volume_raw_data, volume_id, volume_num, series=series)
            volumes.append(volume)

            parts = []
            volume.parts = parts
            if "parts" in volume_with_parts:
                parts_raw_data = volume_with_parts.parts
                for i, part_raw_data in enumerate(parts_raw_data):
                    part_id = part_raw_data.id
                    part_num = i + 1
                    part = Part(
                        part_raw_data, part_id, part_num, volume=volume, series=series
                    )
                    parts.append(part)

    return series


async def fetch_content(session, parts):
    tasks = []
    for part in parts:
        tasks.append(partial(fetch_content_and_images_for_part, session, part.part_id))
    contents = await bag(tasks)

    parts_content = {}
    for i, content_image in enumerate(contents):
        part = parts[i]
        parts_content[part.part_id] = content_image
    return parts_content


def is_part_available(now, part):
    if part.raw_data.preview:
        return True

    if part.series.raw_data.catchup:
        return True

    if not part.raw_data.expiration:
        # not filled yet on JNC's end (happened for the first parts of a new series)
        # cf GH #22
        # assume it has not expired
        return True

    if dateutil.parser.parse(part.raw_data.launch) > now:
        return False

    expiration_data = dateutil.parser.parse(part.raw_data.expiration)
    return expiration_data > now


async def fetch_content_and_images_for_part(session, part_id):
    # FIXME catch error => in case expires between checking before and
    # running this (case to check)
    # FIXME or the assumption of is_part_available (if expiration is null)
    # is incorrect
    content = await session.api.fetch_content(part_id, "data.xhtml")
    img_urls = extract_image_urls(content)
    if len(img_urls) > 0:
        tasks = [partial(fetch_image, session, img_url) for img_url in img_urls]
        images = await bag(tasks)

        # filter images with download error
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
        image.local_filename = _local_image_filename(image)
        return image
    except (trio.MultiError, Exception) as ex:
        console.error(f"Error downloading image with URL: '{img_url}'")
        logger.debug(f"Error downloading image: {ex}", exc_info=sys.exc_info())
        # TODO still create the Image object with empty content ?
        # the original link to the image will stay in the EPUB
        # some EPUB reader may be able to donwload them
        return None


def _local_image_filename(image):
    # unique name to use for the image inside the EPUB
    # ext is almost always .jpg but sometimes it is .jpeg
    # splitext  works fine with a url
    root, ext = os.path.splitext(image.url)
    root = root.replace("https://", "")
    # i is alphabetically greater than c (for cover.jpg)
    # so cover will always be first in zip ; useful for File Explorer cf GH #20
    new_local_filename = "i_" + to_safe_filename(root) + ext
    return new_local_filename


class ImgUrlParser(HTMLParser):
    def __init__(self):
        super().__init__()

        self.img_urls = []

    def handle_starttag(self, tag, tag_attrs):
        if tag == "img":
            for tag_attr in tag_attrs:
                if tag_attr[0] == "src":
                    self.img_urls.append(tag_attr[1])
                    break


def extract_image_urls(content):
    parser = ImgUrlParser()
    parser.feed(content)
    return parser.img_urls


async def fetch_covers(session, volumes):
    tasks = []
    for volume in volumes:
        # fetch the cover url low res image as indicated in the metadata
        # used as a fallback in case the high res is not found
        tasks.append(partial(fetch_lowres_cover_for_volume, session, volume))
        tasks.append(partial(fetch_cover_image_from_parts, session, volume.parts))

    covers = await bag(tasks)
    # even index are lowres
    lowres_covers = covers[::2]
    # odd
    hires_covers = covers[1::2]

    candidate_covers = zip(hires_covers, lowres_covers)
    volumes_cover = {}
    for i, candidate_cover in enumerate(candidate_covers):
        volume = volumes[i]
        hires, lowres = candidate_cover
        # priority to hires
        # note : lowres can also be none if failure => handled in epub gen
        volumes_cover[volume.volume_id] = hires if hires else lowres

    return volumes_cover


async def fetch_lowres_cover_for_volume(session, volume):
    try:
        cover_url = volume.raw_data.cover.coverUrl
        cover = await fetch_image(session, cover_url)
        return cover
    except (trio.MultiError, Exception) as ex:
        logger.debug(
            f"Error fetch_lowres_cover_for_volume: {ex}", exc_info=sys.exc_info()
        )
        return None


async def fetch_cover_image_from_parts(session, parts):
    # need content so only available parts
    parts = [part for part in parts if is_part_available(session.now, part)]
    if not parts:
        return None

    try:
        # the cover image is almost always on the 1st part
        # very rarely on the second
        # so check those 2 first in parallel (need the content); then if
        # doesn't succeed, check the rest
        first_2_parts = parts[:2]
        rest_parts = parts[2:]

        async def fetch_highres_image_maybe(session, part_id):
            content = await session.api.fetch_content(part_id, "data.xhtml")
            return _candidate_cover_image(content)

        for batch_parts in [first_2_parts, rest_parts]:
            tasks = []
            for part in batch_parts:
                tasks.append(partial(fetch_highres_image_maybe, session, part.part_id))
            candidate_urls = await bag(tasks)
            cover = await _fetch_one_candidate_image(session, candidate_urls)
            if cover:
                return cover
        return None

    except (trio.MultiError, Exception) as ex:
        logger.debug(
            f"Error fetching hi res cover images: {ex}", exc_info=sys.exc_info()
        )
        # lowres cover will be used (unless it fails too)
        return None


async def _fetch_one_candidate_image(session, candidate_urls):
    for candidate_url in candidate_urls:
        if candidate_url:

            if "cover" not in candidate_url and "cvr" not in candidate_url:
                # TODO check the cover format on old series
                logger.debug(
                    "The hires cover candidate url doesn't look like a cover URL"
                )

            cover = await fetch_image(session, candidate_url)
            # TODO check dimension ? but all the images in the interior have
            # hi res
            # TODO check the presence of colors => images in the interior except the
            # cover are B&W
            return cover
    return None


class StopHTMLParsing(Exception):
    pass


class CoverImgUrlParser(HTMLParser):
    def __init__(self):
        super().__init__()

        self.candidate_cover_url = None

        # this is to handle covers : special significance for
        # first image before any text
        self.is_after_body = False
        self.is_after_first_text_in_body = False

    def handle_starttag(self, tag, tag_attrs):
        if tag == "img":
            self._handle_img(tag_attrs)
            raise StopHTMLParsing()

        if tag == "body":
            self.is_after_body = True

    def _handle_img(self, tag_attrs):
        for tag_attr in tag_attrs:
            if tag_attr[0] == "src":
                self.candidate_cover_url = tag_attr[1]
                break

    def handle_data(self, text):
        if self.is_after_body:
            # to avoid new line and spaces
            text = text.strip()
            if text:
                raise StopHTMLParsing()


def _candidate_cover_image(content):
    try:
        parser = CoverImgUrlParser()
        parser.feed(content)
    except StopHTMLParsing:
        pass
    url = parser.candidate_cover_url
    if not url:
        return None
    return url


def relevant_volumes_for_cover(volumes, is_by_volume):
    if not is_by_volume:
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
    tasks = [
        partial(fetch_content, session, content_parts),
        partial(fetch_covers, session, cover_volumes),
    ]
    contents, covers = await bag(tasks)

    for part in content_parts:
        content, images = contents[part.part_id]
        part.content = content
        part.images = images

    for volume in cover_volumes:
        volume.cover = covers[volume.volume_id]

    _rename_cover_images(cover_volumes)


def _rename_cover_images(volumes):
    # replace cover local filename from the default to cover.jpg
    # both in part images + volume.cover
    cover_filename = "cover.jpg"
    for volume in volumes:
        if not volume.cover:
            continue

        cover_image = volume.cover
        cover_image.local_filename = cover_filename

        for part in volume.parts:
            if not part.images:
                continue

            for image in part.images:
                if image.url == cover_image.url:
                    image.local_filename = cover_filename
                    break


async def _write_bytes(filepath, content):
    async with await trio.open_file(filepath, "wb") as img_f:
        await img_f.write(content)


async def _write_str(filepath, content):
    async with await trio.open_file(filepath, "w", encoding="utf-8") as img_f:
        await img_f.write(content)


async def fetch_events(session: JNCEPSession, start_date_s):
    session_now = utils.isoformat_with_z(session.now)

    # max 200 previous events : 2-3 weeks, so if updating more often, will be less
    limit = 200
    # already ordered by launch desc
    params = {"limit": limit, "end_date": session_now, "start_date": start_date_s}

    events_with_pagination = await session.api.fetch_events(**params)

    events = events_with_pagination.events
    pagination = events_with_pagination.pagination
    has_reached_limit = not pagination.lastPage
    if events:
        first_event_date = dateutil.parser.parse(events[-1].launch)
    else:
        # too short delay between checks => no events
        # actual value should not matter
        first_event_date = session.now
    return EventFeed(events, has_reached_limit, first_event_date)


def check_series_is_novel(series: Series):
    if not is_novel(series.raw_data):
        raise SeriesNotANovelError(
            f"Series '[highlight]{series.raw_data.title}[/]' is not a novel "
            f"(type is '{series.raw_data.type}')"
        )


def is_novel(raw_series):
    return raw_series.type.upper() == "NOVEL"


async def fetch_follows(session: JNCEPSession):
    followed_series = []
    async for raw_series in jnclabs.paginate(session.api.fetch_follows, "series"):
        # ignore manga series
        if not is_novel(raw_series):
            continue

        slug = raw_series.slug
        # the metadata is not as complete as the usual (with fetch_meta)
        # but it can still be useful to avoid a call later to the API
        jnc_resource = jncweb.JNCResource(
            jncweb.url_from_series_slug(slug),
            slug,
            True,
            jncweb.RESOURCE_TYPE_SERIES,
            raw_series,
        )
        followed_series.append(jnc_resource)

    return followed_series
