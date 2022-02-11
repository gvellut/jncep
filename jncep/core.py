from collections import defaultdict
from html.parser import HTMLParser
import logging
import os
import re
import time
from typing import List

import attr
import trio

from . import epub, jncweb, spec
from .jnclabs import JNCLabsAPI
from .model import Image, Part, Series, Volume
from .utils import to_safe_filename

logger = logging.getLogger(__name__)


class NoRequestedPartAvailableError(Exception):
    pass


@attr.s
class IdentifierSpec:
    type_ = attr.ib()
    volume_id = attr.ib(None)
    part_id = attr.ib(None)

    def has_volume(self, _volume_num, volume_id) -> bool:
        if self.type_ == spec.SERIES:
            return True

        return self.volume_id == volume_id

    def has_part(self, _volume_num, _part_num, part_id) -> bool:
        # assumes has_volume already checked with the volume_id
        if self.type_ in (spec.SERIES, spec.VOLUME):
            return True

        return self.part_id == part_id


class JNCEPSession:
    def __init__(self, email, password):
        self.api = JNCLabsAPI()
        self.email = email
        self.password = password

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

    def series_slugs(self):
        return list(self.series_content.keys())

    async def to_part_spec(self, jnc_resource):
        if jnc_resource.resource_type == jncweb.RESOURCE_TYPE_SERIES:
            return IdentifierSpec(spec.SERIES)

        elif jnc_resource.resource_type == jncweb.RESOURCE_TYPE_VOLUME:
            if jnc_resource.is_new_website:
                # for volume on new website => where is a tuple (series_slug,
                # volume num)
                series_slug, volume_number = jnc_resource.slug

                volumes = await _fetch_volumes_for_series(self.api, series_slug)

                volume_index = volume_number - 1
                if volume_index not in range(len(volumes)):
                    raise jncweb.BadWebURLError(
                        f"Incorrect volume number in URL: {jnc_resource.url}"
                    )

                volume = volumes[volume_index]
            else:
                volume_slug = jnc_resource.slug
                volume = await self.api.fetch_data("volumes", volume_slug)

            return IdentifierSpec(spec.VOLUME, volume.legacyId)

        elif jnc_resource.resource_type == jncweb.RESOURCE_TYPE_PART:
            with AsyncCollector() as c:
                async with trio.open_nursery() as nursery:
                    nursery.start_soon(
                        c.collect(
                            "part", self.api.fetch_data, "parts", jnc_resource.slug
                        )
                    )
                    nursery.start_soon(
                        c.collect(
                            "volume",
                            self.api.fetch_data,
                            "parts",
                            jnc_resource.slug,
                            "volume",
                        )
                    )

                part = c.results["part"]
                volume = c.results["volume"]
                return IdentifierSpec(spec.PART, volume.legacyId, part.legacyId)

    async def fetch_for_specs(self, jnc_resource, part_spec, epub_generation_options):
        # epub_generation_options for is_by_volume => for the covers to fetch
        with AsyncCollector() as c:
            async with trio.open_nursery() as nursery:
                if jnc_resource.resource_type == jncweb.RESOURCE_TYPE_SERIES:
                    series_slug = jnc_resource.slug
                    nursery.start_soon(
                        c.collect("series", self.api.fetch_data, "series", series_slug)
                    )
                elif jnc_resource.resource_type == jncweb.RESOURCE_TYPE_VOLUME:
                    if jnc_resource.is_new_website:
                        series_slug, _ = jnc_resource.slug
                        nursery.start_soon(
                            c.collect(
                                "series", self.api.fetch_data, "series", series_slug
                            )
                        )
                    else:
                        volume_slug = jnc_resource.slug
                        series_raw_data = await self.api.fetch_data(
                            "volumes", volume_slug, "serie"
                        )
                        series_slug = series_raw_data.slug
                elif jnc_resource.resource_type == jncweb.RESOURCE_TYPE_PART:
                    part_slug = jnc_resource.slug
                    series_raw_data = await self.api.fetch_data(
                        "parts", part_slug, "serie"
                    )
                    series_slug = series_raw_data.slug

                nursery.start_soon(
                    c.collect(
                        "series_deep",
                        _deep_fetch_volumes_for_series,
                        self.api,
                        series_slug,
                        part_spec,
                    )
                )

                is_only_first_volume = not epub_generation_options.is_by_volume
                nursery.start_soon(
                    c.collect_catch(
                        "covers",
                        _fetch_covers,
                        self.api,
                        series_slug,
                        part_spec,
                        is_only_first_volume,
                    )
                )

            if "series" in c.results:
                # some branches fetch the raw data as async
                series_raw_data = c.results["series"]

            volumes = c.results["series_deep"]
            series = Series(series_raw_data, volumes)
            series.raw_data = series_raw_data

            if "covers" in c.results:
                # some branches fetch the raw data as async
                error = c.errors.get("covers")
                if error:
                    logger.warning(f"Issue fetching cover for {series_slug}!")
                else:
                    covers_data = c.results["covers"]
                    for volume in series.volumes:
                        if volume.num in covers_data:
                            volume.cover = covers_data[volume.num]

            return series

    def process_downloaded(
        self, series, options: epub.EpubGenerationOptions
    ) -> epub.BookDetails:

        parts = _dl_parts(series)

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

        volumes = _dl_volumes(series)
        if options.is_by_volume:
            book_details = []
            for volume in volumes:
                volume_parts = _dl_parts_volume(volume)
                volume_details = self._process_single_epub_content(
                    series, [volume], volume_parts
                )
                book_details.append(volume_details)
        else:
            book_details = [self._process_single_epub_content(series, volumes, parts)]

        return book_details

    def _process_single_epub_content(self, series, volumes, parts):
        # TODO suffix final complete : not in api but in web page for series
        # data for React contains what is needed in JSON

        # representative volume
        repr_volume = volumes[0]
        author = _extract_author(repr_volume.raw_data.creators)

        # TODO external func
        # first part
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

                part_nums = (
                    f"Parts {volume_num0}.{part_num0} to {volume_num1}.{part_num1}"
                )

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
        images = _dl_images(parts)

        book_details = epub.BookDetails(
            identifier, title, author, collection, cover_image, toc, contents, images
        )

        return book_details

    async def extract_images(self, series, epub_generation_options):
        async with trio.open_nursery() as nursery:
            for part in _dl_parts(series):
                images = part.images
                _compute_order_of_images(part.content, images)

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
                    nursery.start_soon(_write_bytes, img_filepath, image.content)

    async def extract_content(self, series, epub_generation_options):
        parts = _dl_parts(series)
        async with trio.open_nursery() as nursery:
            for part in parts:
                content = part.content
                content_filename = to_safe_filename(part.raw_data.title) + ".html"
                content_filepath = os.path.join(
                    epub_generation_options.output_dirpath, content_filename
                )
                nursery.start_soon(_write_str, content_filepath, content)


class AsyncCollector:
    def __init__(self):
        self.results = {}
        self.errors = {}

    def collect(self, name, afunc, *args):
        async def wrapper():
            res = await afunc(*args)
            self.results[name] = res

        return wrapper

    def collect_catch(self, name, afunc, *args):
        async def wrapper():
            try:
                res = await afunc(*args)
                self.results[name] = res
            except Exception as ex:
                self.errors[name] = ex

        return wrapper

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception_value, exception_traceback):
        return False


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


def _compute_order_of_images(content, images: List[Image]):
    images_with_pos = [(image, content.find(image.url)) for image in images]
    images_with_pos = sorted(images_with_pos, key=lambda x: x[1])

    image_order = 1
    for image, _ in images_with_pos:
        image.order_in_part = image_order
        image_order += 1


def _dl_parts(series):
    parts = [p for v in _dl_volumes(series) for p in v.parts if p.is_dl]
    return parts


def _dl_parts_volume(volume):
    parts = [p for p in volume.parts if p.is_dl]
    return parts


def _dl_volumes(series):
    volumes = [v for v in series.volumes if v.is_dl]
    return volumes


def _dl_images(parts):
    images = [i for part in parts for i in part.images]
    return images


async def _deep_fetch_volumes_for_series(api: JNCLabsAPI, series_id, part_spec):
    volumes_data = await _fetch_volumes_for_series(api, series_id)
    volumes = []

    with AsyncCollector() as c:
        async with trio.open_nursery() as nursery:
            for i, volume_data in enumerate(volumes_data):
                volume_id = volume_data.legacyId
                volume_num = i + 1

                volume = Volume(volume_data, volume_id, volume_num)
                volumes.append(volume)

                if not part_spec.has_volume(volume_num, volume_id):
                    # volume parts will be empty for that one
                    continue
                volume.is_dl = True

                nursery.start_soon(
                    c.collect(
                        volume_id,
                        _deep_fetch_parts_for_volume,
                        api,
                        volume,
                        part_spec,
                    )
                )

        for volume in volumes:
            if not volume.is_dl:
                continue
            volume.parts = c.results[volume.volume_id]

    return volumes


async def _fetch_volumes_for_series(api: JNCLabsAPI, series_id):
    volumes = [
        volume
        async for volume in api.paginate(
            api.fetch_data,
            "series",
            series_id,
            "volumes",
        )
    ]
    return volumes


async def _deep_fetch_parts_for_volume(api: JNCLabsAPI, volume, part_spec):
    parts_data = await _fetch_parts_for_volume(api, volume)
    parts = []
    with AsyncCollector() as c:
        async with trio.open_nursery() as nursery:
            for i, part_data in enumerate(parts_data):
                part_id = part_data.legacyId
                part_num = i + 1
                part = Part(part_data, volume, part_id, part_num)
                parts.append(part)

                if not part_spec.has_part(volume.num, part_num, part_id):
                    continue
                part.is_dl = True

                # TODO handle unavailable content (not preview + not catchup)

                nursery.start_soon(
                    c.collect(part_id, _deep_fetch_content_for_part, api, part)
                )

        for part in parts:
            if not part.is_dl:
                continue
            content, images = c.results[part.part_id]
            part.content = content
            part.images = images

    return parts


async def _fetch_parts_for_volume(api: JNCLabsAPI, volume):
    parts = [
        part
        async for part in api.paginate(
            api.fetch_data,
            "volumes",
            volume.volume_id,
            "parts",
        )
    ]
    return parts


async def _deep_fetch_content_for_part(api: JNCLabsAPI, part):
    # TODO handle errors
    content = await api.fetch_content(part.part_id, "data.xhtml")
    img_urls = _img_urls(content)
    if len(img_urls) > 0:
        # TODO handle image dl failures
        with AsyncCollector() as c:
            async with trio.open_nursery() as nursery:
                for img_url in img_urls:
                    nursery.start_soon(
                        c.collect(img_url, _fetch_image, api, part, img_url)
                    )

            return content, list(c.results.values())

    return content, []


async def _fetch_image(api: JNCLabsAPI, part, img_url):
    img_bytes = await api.fetch_url(img_url)
    image = Image(img_url, part, img_bytes)
    return image


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


async def _fetch_covers(api: JNCLabsAPI, series_id, part_spec, is_only_first_volume):
    # should be cached
    volumes_data = await _fetch_volumes_for_series(api, series_id)

    covers = defaultdict(list)

    with AsyncCollector() as c:
        async with trio.open_nursery() as nursery:
            for i, volume_data in enumerate(volumes_data):
                volume_id = volume_data.legacyId
                volume_num = i + 1

                if not part_spec.has_volume(volume_num, volume_id):
                    continue

                cover_url = volume_data.cover.coverUrl
                nursery.start_soon(
                    c.collect(
                        ("volume", volume_num), _fetch_image, api, None, cover_url
                    )
                )
                # also process large covers (foud in part content)

                if is_only_first_volume:
                    # just the first found volume
                    break

        for key, value in c.results.items():
            _, volume_num = key
            covers[volume_num] = value

    return covers


async def _write_bytes(filepath, content):
    async with await trio.open_file(filepath, "wb") as img_f:
        await img_f.write(content)


async def _write_str(filepath, content):
    async with await trio.open_file(filepath, "w", encoding="utf-8") as img_f:
        await img_f.write(content)
