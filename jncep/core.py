from __future__ import annotations

from collections import namedtuple
from contextvars import ContextVar
from datetime import datetime, timezone
from enum import Enum, auto
from functools import partial
from html.parser import HTMLParser
import logging
import os
import platform
import re
import sys
import time
from typing import NamedTuple

import dateutil.parser
from dateutil.relativedelta import relativedelta
from exceptiongroup import BaseExceptionGroup
import trio

from . import epub, jncalts, jncapi, jncweb, namegen_utils, spec, utils
from .model import Image, Language, Part, Series, Volume
from .trio_utils import bag
from .utils import is_debug, to_safe_filename

logger = logging.getLogger(__name__)
console = utils.getConsole()

EpubGenerationOptions = namedtuple(
    "EpubGenerationOptions",
    [
        "output_dirpath",
        "is_subfolder",
        "is_by_volume",
        "is_extract_images",
        "is_extract_content",
        "is_not_replace_chars",
        "style_css_path",
        "name_generator",
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


class MemberLevel(Enum):
    USER = auto()  # for accounts with no subscription
    MEMBER = auto()
    PREMIUM_MEMBER = auto()

    @staticmethod
    def from_str(level_str: str) -> MemberLevel:
        try:
            return MemberLevel[level_str.upper()]
        except KeyError:
            console.warning(f"Unknown level : {level_str}")
            # use that as default
            return MemberLevel.USER


class SubscriptionStatus(Enum):
    ACTIVE = auto()
    TRIALING = auto()
    UNKNOWN = auto()  # for non members (just an account: Always with level = USER ?)

    @staticmethod
    def from_str(status_str: str) -> SubscriptionStatus:
        try:
            return SubscriptionStatus[status_str.upper()]
        except KeyError:
            console.warning(f"Unknown subscription status : {status_str}")
            # use that as default
            return SubscriptionStatus.UNKNOWN


class MemberStatus(NamedTuple):
    origin: jncalts.AltOrigin
    name: str
    # level and status are always filled in /me even for non members
    level: MemberLevel
    status: SubscriptionStatus
    premium: bool  # should have no effect for jncep
    club: bool  # prepubs
    reader: bool  # reader's library

    @property
    def is_member(self):
        return (
            self.level != MemberLevel.USER and self.status != SubscriptionStatus.UNKNOWN
        )

    @property
    def is_prepub(self):
        # TODO not sure for nina if second part is necessary (not a subscriber so
        # cannot really check if the details of subscription is returned for Nina)
        return self.club or (
            self.origin == jncalts.AltOrigin.JNC_NINA and self.is_member
        )

    @property
    def is_readers_library(self):
        # not available for Nina
        return self.reader


class FilePathTooLongError(Exception):
    pass


class SeriesNotANovelError(Exception):
    pass


_GLOBAL_SESSION_INSTANCE = ContextVar("session", default=None)


class JNCEPSession:
    # TODO change name : config => alt_config so no confusion with the JNCEP user config
    def __init__(self, config: jncalts.AltConfig, credentials):
        self.config = config

        self.api = jncapi.JNC_API(config)
        self.email, self.password = credentials.get_credentials(config.ORIGIN)

        self.now = datetime.now(tz=timezone.utc)
        # TODO only the member level is sufficient
        self.me = None
        self.member_status = None

    async def __aenter__(self) -> JNCEPSession:
        # to handle nested sessions ie call to a cli commmand from another cli command
        # open only one session for an origin (nested)
        session_dict = _GLOBAL_SESSION_INSTANCE.get()
        if session_dict is None:
            session_dict = {}
        if self.config.ORIGIN not in session_dict:
            await self.login(self.email, self.password)
            session_dict[self.config.ORIGIN] = self
            _GLOBAL_SESSION_INSTANCE.set(session_dict)
        return session_dict[self.config.ORIGIN]

    async def __aexit__(self, exc_type, exc, tb):
        try:
            console.stop_status()
        except Exception:
            pass

        session_dict = _GLOBAL_SESSION_INSTANCE.get()

        if session_dict.get(self.config.ORIGIN) != self:
            # nested ; do not logout => leave it to the top level session
            return False

        # current session is the top level session
        del session_dict[self.config.ORIGIN]
        _GLOBAL_SESSION_INSTANCE.set(session_dict)
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
        msg = (
            f"Login to {self.config.ORIGIN} with email "
            + f"'[highlight]{display_email}[/]'..."
        )
        console.status(msg)
        token = await self.api.login(email, password)

        # to be able to check subscription status
        self.me = await self.api.me()
        self.member_status = member_status(self)

        emoji = ""
        if console.is_advanced():
            emoji = "\u26a1 "
        console.info(
            f"{emoji}Logged in to {self.config.ORIGIN} with email "
            + f"'[highlight]{display_email}[/]'"
        )
        console.status("...")
        return token

    async def logout(self):
        if self.api.is_logged_in:
            try:
                console.info("Logout...")
                self.me = None
                self.member_status = None
                await self.api.logout()
            except (BaseExceptionGroup, Exception) as ex:
                logger.debug(f"Error logout: {ex}", exc_info=sys.exc_info())

    @property
    def origin(self):
        return self.config.ORIGIN


async def create_epub(series, volumes, parts, epub_generation_options):
    book_details = process_series(series, volumes, parts, epub_generation_options)

    utils.ensure_directory_exists(epub_generation_options.output_dirpath)

    if epub_generation_options.is_extract_content:
        await extract_content(parts, epub_generation_options)

    if epub_generation_options.is_extract_images:
        await extract_images(parts, epub_generation_options)

    extension = ".epub"
    for book_details_i in book_details:
        if book_details_i.subfolder:
            output_folderpath = os.path.join(
                epub_generation_options.output_dirpath, book_details_i.subfolder
            )
            utils.ensure_directory_exists(output_folderpath)
        else:
            output_folderpath = epub_generation_options.output_dirpath

        output_filename = book_details_i.filename + extension

        output_filepath = os.path.join(output_folderpath, output_filename)

        # TODO process subfolder in to_max_len
        output_filepath = _to_max_len_filepath(output_filepath, extension)

        # TODO write to memory then async fs write here ? (uses epublib
        # which is sync anyway)
        # or trio.to_thread.run_sync or inside
        epub.output_epub(
            output_filepath, book_details_i, epub_generation_options.style_css_path
        )

        # laughing face
        emoji = ""
        if console.is_advanced():
            emoji = "\U0001f600 "
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
                series, [volume], volume_parts, options
            )
            book_details.append(volume_details)
    else:
        book_details = [_process_single_epub_content(series, volumes, parts, options)]

    return book_details


def _process_single_epub_content(
    series, volumes, parts, options: EpubGenerationOptions
):
    # order of volumes and parts must match

    # representative volume: First
    repr_volume = volumes[0]
    author = _extract_author(repr_volume.raw_data.creators)
    volume_num = repr_volume.num
    description = repr_volume.raw_data.description
    tags = repr_volume.series.raw_data.tags

    # in case of multiple volumes, this will set the number of the first volume
    # in the epub
    # in Calibre, display 1 (I) if not set so a bit better
    collection = epub.CollectionMetadata(
        series.series_id, series.raw_data.title, volume_num
    )

    # cover can be None (handled in epub gen proper)
    cover_image = repr_volume.cover

    contents = [part.epub_content for part in parts]

    if len(parts) == 1:
        # single part
        part = parts[0]
        part_num = part.num_in_volume
        # single part => single volume: part numbers relative to
        # that volume
        toc = [f"Part {part_num}"]
    else:
        volume_index = set([v.num for v in volumes])
        if len(volume_index) > 1:
            toc = [part.raw_data.title for part in parts]
        else:
            toc = [f"Part {part.num_in_volume}" for part in parts]

    name_generator = options.name_generator
    complete = len(volumes) == 1 and is_volume_complete(volumes[0], parts)
    fc = namegen_utils.FC(is_part_final(parts[-1]), complete)
    title, filename, folder = name_generator.generate(series, volumes, parts, fc)

    if options.is_subfolder:
        subfolder = folder
    else:
        subfolder = None

    identifier = series.raw_data.slug + str(int(time.time()))

    images = [img for part in parts for img in part.images]

    book_details = epub.BookDetails(
        identifier,
        series,
        title,
        filename,
        subfolder,
        author,
        collection,
        description,
        tags,
        cover_image,
        toc,
        contents,
        images,
        complete,
    )

    return book_details


def is_part_final(part):
    volume = part.volume
    if volume.raw_data.get("totalParts") is None:
        # assume not final
        return False
    return part.num_in_volume == volume.raw_data.totalParts


def is_volume_complete(volume, parts):
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
                # force JPG extension: recent API update has webp extension for recent
                # parts but always converted to JPG when downloading
                # TODO never PNG ?
                # _, ext = os.path.splitext(image.local_filename)
                ext = ".jpg"
                suffix = f"_Image_{image.order_in_part}"
                img_filename = to_safe_filename(part.raw_data.title) + suffix + ext
                img_filepath = os.path.join(
                    epub_generation_options.output_dirpath, img_filename
                )
                # TODO process subfolder like epub

                img_filepath = _to_max_len_filepath(img_filepath, ext)

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
            # TODO process subfolder like epub

            content_filepath = _to_max_len_filepath(content_filepath, extension)

            n.start_soon(_write_str, content_filepath, content)


def _to_max_len_filepath(
    original_filepath,
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

    # minimum size for keeping recognizable (arbitrary)
    min_title_short_len = 15
    mandatory_len = len(extension)
    # TODO review comment : to_safe_filename is done during namegen
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

    chars_to_remove = len(original_filename) - max_part_title_short_len
    start = (len(original_filename) - chars_to_remove) // 2
    end = start + chars_to_remove
    title_short = original_filename[:start] + original_filename[end:]

    # to_safe_filename must have been done previously
    subs_filename = title_short + extension
    subs_filepath = os.path.join(dirpath, subs_filename)
    return subs_filepath


def _extract_author(creators, default="Unknown Author"):
    for creator in creators:
        if creator.role == "AUTHOR":
            return creator.name
    return default


def _replace_chars(content):
    # https://unicode.scarfboy.com/ for code
    # both the chars to replace and replacement are hardcoded
    # TODO leave the raw unicode character copied from content instead of code?
    # TODO make it automatic ie for all characters not in alphabet + punctuation?
    # TODO add option to set replacement or add characters not processed
    chars_to_replace = [
        "\u2671",
        "\u25c6",
        "\U0001f3f6",
        "\u25c7",
        "\u2605",
        "\u25bc",
        "\u25b3",
        "\u25ef",
        "\u273d",
        "\u2725",
    ]
    replacement_char = "**"
    regex = "|".join(chars_to_replace)
    content = re.sub(regex, replacement_char, content)
    return content


def _replace_image_urls(content, images: list[Image]):
    for image in images:
        # the filename relative to the epub content root
        # the file will be added to the Epub archive
        content = content.replace(image.url, image.local_filename)

    return content


def all_parts_meta(series):
    # return all parts : no need to filter out parts released in the future (v2 API)
    # => always done in fetch_meta before this
    parts = [part for volume in series.volumes if volume.parts for part in volume.parts]
    return parts


def last_part_number_and_date(parts):
    # for the tracking, need the last date: almost always the date of the last part
    # but for some series with volumes released in parallel, can be different
    # see GH #28
    # so do additional work for this

    last_part_number = parts[-1]
    # pn will only be used for display to the user in track list
    pn = spec.to_relative_spec_from_part(last_part_number)

    # the date is what is used to know which series to udpate
    last_part_date = max(parts, key=lambda x: x.raw_data.launch)
    pdate = last_part_date.raw_data.launch

    return pn, pdate


def latest_part_from_non_available_volume(
    session: JNCEPSession, volumes: list[Volume], parts: list[Part]
):
    # used for display output in track_series
    first_available_volume = None
    # part before part 1 of the first volume with all parts still available
    # need the last non available so date compared after its publication date (like
    # what is written in tracked.json)
    latest_non_available_pn = None
    latest_non_available_pdate = None
    is_beginning = False

    if not volumes:
        # series not started
        is_beginning = True

    for i, volume in enumerate(volumes):
        if is_volume_available(session, volume):
            # Note : volumes with no part launched are ignored in resolve_series
            # so if volume before is expired: first_available_volume will not be filled
            # and it will appear in output as tracking from after the last (expired)
            # part instead of current (not started) volume
            # TODO change ? see impact

            # this is the first volume with all released parts also available
            first_available_volume = volume
            if i == 0:
                is_beginning = True
            else:
                # if multiple volumes released in parallel (side stories)
                # volumes[i - 1].parts[-1] may not be the last released so look for it
                # TODO if parallel => maybe a later volume is not available.  but no
                # way to tell to ignore. Almost never happens too
                first_part = volume.parts[0]
                parts_to_consider = [
                    part
                    for part in parts
                    if part.raw_data.launch < first_part.raw_data.launch
                ]
                latest_non_available_pn, latest_non_available_pdate = (
                    last_part_number_and_date(parts_to_consider)
                )
            break

    if not latest_non_available_pdate:
        if is_beginning:
            # first available part is actually the beginning of the series
            return None, None, True

        # all volumes are expired : so no details and will be the same as "last part"
        return None, None, False

    # part details (for tracking), valume detail (for display), beginning, last
    return (
        (latest_non_available_pn, latest_non_available_pdate),
        first_available_volume,
        False,
    )


def is_volume_available(session, volume):
    # check if all parts currently available
    parts_available = (
        is_part_available(session.now, session.member_status, p) for p in volume.parts
    )
    return all(parts_available)


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


async def fetch_meta(session: JNCEPSession, series_id_or_slug):
    series_agg = await session.api.fetch_data("series", series_id_or_slug, "aggregate")
    series_raw_data = series_agg.series
    series_id = series_raw_data.id
    series = Series(series_raw_data, series_id)

    volumes = []
    series.volumes = volumes
    # maybe could happen there is no volumes attr (will need to check when there is a
    # new series)
    if "volumes" in series_agg:
        for i, volume_with_parts in enumerate(series_agg.volumes):
            volume_raw_data = volume_with_parts.volume
            volume_id = volume_raw_data.id
            volume_num = i + 1

            volume = Volume(
                volume_raw_data,
                volume_id,
                volume_num,
                series=series,
            )

            parts = []
            volume.parts = parts
            if "parts" in volume_with_parts:
                parts_raw_data = volume_with_parts.parts
                for i, part_raw_data in enumerate(parts_raw_data):
                    part_id = part_raw_data.id
                    # assume the parts are ordered correctly in API response
                    # FIXME volume 1 (expired) of The Invincible Summoner not ordered.
                    # Others?
                    part_num = i + 1
                    part = Part(
                        part_raw_data, part_id, part_num, volume=volume, series=series
                    )
                    # remove the parts not yet launched => pretend they are not there
                    # change to accommodate API v2 update in october 2024
                    if is_part_in_future(session.now, part):
                        continue
                    parts.append(part)

            # ignore volumes with no part launched
            if len(parts) == 0:
                continue
            volumes.append(volume)

    return series


async def fetch_content(session, parts):
    tasks = []
    for part in parts:
        tasks.append(partial(fetch_content_and_images_for_part, session, part.part_id))
    contents = await bag(tasks)

    parts_content = {}
    for i, content_image in enumerate(contents):
        if not content_image:
            continue
        part = parts[i]
        parts_content[part.part_id] = content_image
    return parts_content


def is_part_available(now, member_status: MemberStatus, part: Part):
    # priority: do not take it into account
    if is_part_in_future(now, part):
        return False

    if part.raw_data.preview:
        return True

    # the prepubs are available if the volume was bought or preordered
    if part.volume.raw_data.owned:
        return True

    # only previews and owned are relevant for non members
    if not member_status.is_member:
        return False

    if member_status.is_readers_library and part.volume.raw_data.readerStreamingEnabled:
        return True
        # user may be both reader's library AND prepub so keep checking after

    if not member_status.is_prepub:
        return False

    # a member with access to prepubs : check expiration date
    exp_dt = expiration_datetime(part)
    if not exp_dt:
        # if no publishing date (thus no expiration) : assume available
        # TODO think about it
        return True

    return exp_dt > now


def is_part_in_future(now, part):
    return dateutil.parser.parse(part.raw_data.launch) > now


def expiration_datetime(part: Part):
    # in the v2 API : the expiration field is not always present:
    # if expired: null
    # if not expired: field present but identical to the publishing date of volume ie
    # different from what is being shown on the website (so probably wrong)
    # On the JNC website: shown expiration always computed from publishing date
    # => here always recompute from the volume publishing date field
    pub_date_s = part.volume.raw_data.publishing
    if not pub_date_s:
        return None

    pub_date = dateutil.parser.parse(pub_date_s)
    return _compute_expiration_datetime(pub_date)


def _compute_expiration_datetime(pub_date):
    # code lifted from JNC website series page:
    # in Debugger : /_next/static/chunks/pages/series/%5Bslug%5D-539be0190514573d.js
    # let n=e.getUTCDate(),r=e.getUTCMonth(),l=e.getUTCFullYear(),
    # a=new Date(l,n>=9?r+1:r,15,10),s=a.getDay();return 0===s&&a.setDate(16),
    # 6===s&&a.setDate(17),a
    # changed function name from _date to _datetime since hours = 10 so time important
    day = pub_date.day
    month = pub_date.month
    year = pub_date.year

    exp_date = datetime(year, month, 15, hour=10, tzinfo=timezone.utc)

    if day >= 9:
        exp_date += relativedelta(months=1)

    weekday = exp_date.weekday()
    if weekday == 6:
        # sunday => set to next monday
        exp_date = exp_date.replace(day=16)
    elif weekday == 5:
        # saturday => set to next monday
        exp_date = exp_date.replace(day=17)

    return exp_date


async def fetch_content_and_images_for_part(session, part_id):
    try:
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
    except Exception as ex:
        # just debug => we will display a more generic message after all the parts
        # have been gathered
        # can be because : user doesn't have the right (not a subscriber)
        # or the part has expired between checking is_available and the actual fetching
        # => we don't care about the difference (result is the same)
        logger.debug(f"Error fetching content for part: {ex}", exc_info=sys.exc_info())
        return None


def webp_to_jpeg(img_url: str):
    # convert from webp to jpeg (webp not readable in some physical epub reader
    # like kobo); scheme documented here : https://forums.j-novel.club/post/374895
    return img_url.replace("/webp/", "/jpg/", 1)


async def fetch_image(session: JNCEPSession, img_url):
    try:
        jpeg_img_url = webp_to_jpeg(img_url)
        img_bytes = await session.api.fetch_url(jpeg_img_url)
        # keep the original img url => will appear in the content
        image = Image(img_url, img_bytes)
        image.local_filename = _local_image_filename(image)
        return image
    except (BaseExceptionGroup, Exception) as ex:
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
    except (BaseExceptionGroup, Exception) as ex:
        logger.debug(
            f"Error fetch_lowres_cover_for_volume: {ex}", exc_info=sys.exc_info()
        )
        return None


async def fetch_cover_image_from_parts(session, parts):
    # need content so only available parts
    parts = [
        part
        for part in parts
        if is_part_available(session.now, session.member_status, part)
    ]
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
            try:
                content = await session.api.fetch_content(part_id, "data.xhtml")
            except Exception as ex:
                # the is_part_available checks only the properties attached to the part
                # data
                # however user may not have the right eg if not a paying subscriber =>
                # only Part 1 of each volume will be available to him
                logger.debug(
                    f"Error fetching hi res cover images: {ex}", exc_info=sys.exc_info()
                )
                return None
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

    except (BaseExceptionGroup, Exception) as ex:
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


def has_missing_part_content(content_parts):
    # if none is available: no Epub will be generated
    has_available = False
    has_missing = False
    for part in content_parts:
        if not part.content:
            has_missing = True
        else:
            has_available = True
    return has_missing, has_available


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
    async for raw_series in jncapi.paginate(session.api.fetch_follows, "series"):
        # ignore manga series
        if not is_novel(raw_series):
            continue

        slug = raw_series.slug
        url = jncweb.url_from_series_slug(session.origin, slug)
        # parse again to fill most fields
        jnc_resource = jncweb.resource_from_url(url)
        # the metadata is not as complete as the usual (with fetch_meta)
        # but it can still be useful to avoid a call later to the API
        # so keep it
        jnc_resource.follow_raw_data = raw_series

        followed_series.append(jnc_resource)

    return followed_series


FR_LANG_re = re.compile(r".* Partie \d+$")
DE_LANG_re = re.compile(r".* Teil \d+$")


# language not set in response from API
# the URL includes the language only in the case of French ; could guess by elimination
# but easier to check by origin + scheme of part names
def guess_language(origin, series: Series):
    if origin == jncalts.AltOrigin.JNC_MAIN:
        return Language.EN

    # Nina
    # count occurences
    lang_count = {}
    for volume in series.volumes:
        for part in volume.parts:
            lang = None
            if re.match(FR_LANG_re, part.raw_data.title):
                lang = Language.FR
            if re.match(DE_LANG_re, part.raw_data.title):
                lang = Language.DE

            if lang:
                lang_count[lang] = lang_count.get(lang, 0) + 1

    # get the most frequent
    if lang_count:
        lang = max(lang_count, key=lang_count.get)
        return lang

    # or English as default (for example, if new Nina language not yet handled here)
    return Language.EN


def member_status(session: JNCEPSession):
    origin = session.origin

    # non paying is USER ; normal member is MEMBER, premium is PREMIUM_MEMBER
    # subscriptionStatus can be ACTIVE or TRIALING or UNKNOWN (for simple USER only?)
    # the me path is not accessible if not logged in : not supported by JNCEP anyway
    # JNC Nina doesn't have premium level membership nor reader list
    # TODO not sure if subscriptionStatus is always null for Nina or just if status is
    # UNKNOWN (in JNC : subscriptionStatus is null if UNKNOWN)
    level_str = session.me.level
    level = MemberLevel.from_str(level_str)
    status_str = session.me.subscriptionStatus
    status = SubscriptionStatus.from_str(status_str)

    name = None
    premium = club = reader = False
    feats = session.me.subscriptionFeatures
    if feats:
        name = feats.name
        premium = bool(feats.premium)
        club = bool(feats.clubStreamingAccess)
        reader = bool(feats.readerStreamingAccess)

    logger.debug(
        f"{origin=} {level_str=} {level=} {status=} {status_str=} {name=} {premium=} "
        f"{club=} {reader=}"
    )

    return MemberStatus(origin, name, level, status, premium, club, reader)
