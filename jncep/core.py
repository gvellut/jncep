from collections import defaultdict
from functools import partial
from html.parser import HTMLParser
from itertools import groupby
import json
import logging
from operator import attrgetter
import os
import re
import time

from addict import Dict as Addict
import attr
import trio

from . import epub, jncweb, spec
from .jnclabs import JNCLabsAPI
from .utils import to_safe_filename

logger = logging.getLogger(__package__)


class NoRequestedPartAvailableError(Exception):
    pass


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
    data_index = attr.ib(factory=lambda: defaultdict(list))
    data_fetch = attr.ib(factory=dict)

    # TODO add warnings : missing content, etc

    def normalize_slug(self, slug, did):
        for value in self.data:
            if value.did == slug:
                value.did = did

    def add(self, data: "Data"):
        # TODO replace data_index with data_fetch
        data_key = (data.dtype, data.did)
        if data_key in self.data_index:
            # already fetched ; assumes hasn't changed
            return
        self.data.append(data)
        self.data_index_by_dtype[data.dtype].append(data)
        self.data_index[data_key] = data

    def merge(self, result: "Result"):
        for data in result.data:
            self.add(data)

    # FIXME use
    def check_fetch(self, dtype, did):
        key = (dtype, did)
        if key in self.data_fetch:
            # this data is being fetched or has already been fetched
            event = self.data_fetch[key]
            return event
        else:
            event = trio.Event()
            self.data_fetch[key] = event
            return None

    def set_fetch(self, dtype, did):
        key = (dtype, did)
        if key in self.data_fetch:
            event = self.data_fetch[key]
            event.set()

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
class IdentifierSpec:
    type_ = attr.ib()
    volume_id = attr.ib(default=None)
    part_id = attr.ib(default=None)

    def has_volume(self, _volume_num, volume_id) -> bool:
        if self.type_ == spec.SERIES:
            return True

        return self.volume_id == volume_id

    def has_part(self, _volume_num, _part_num, part_id) -> bool:
        # assumes has_volume already checked with the volume_id
        if self.type_ in (spec.SERIES, spec.VOLUME):
            return True

        return self.part_id == part_id


def process_downloaded(
    result: Result, options: epub.EpubGenerationOptions
) -> epub.BookDetails:
    # TODO split in 2 : separate by volume + other func to handle the details
    # if volumes are merged
    # TODO or handled split by volume
    parts = [d.data for d in result.get_by_dtype(DTYPE_PART)]
    volumes = [d.data for d in result.get_by_dtype(DTYPE_VOLUME)]
    series = result.get_by_dtype(DTYPE_SERIES)[0].data

    contents = {}
    for k, g in groupby(result.get_by_dtype(DTYPE_PART_XHTML), attrgetter("did")):
        # one content for each part
        contents.update({k: next(g).data})

    images_data = result.get_by_dtype(DTYPE_PART_IMAGE)
    images = [d.data for d in images_data]
    images_by_part = {}
    for k, g in groupby(sorted(images_data, key=attrgetter("did")), attrgetter("did")):
        images_by_part.update({k: [d.data for d in g]})

    volumes_in_series = result.get_by_dtype(DTYPE_SERIES_VOLUMES)[0].data
    parts_in_volumes = {d.did: d.data for d in result.get_by_dtype(DTYPE_VOLUME_PARTS)}

    volumes_index = _index_volumes_in_series_by_num(volumes_in_series)

    # order parts according to position in series
    nums_for_parts = _compute_nums_for_parts(volumes_in_series, parts_in_volumes)
    parts_indices = [nums_for_parts[part.legacyId] for part in parts]
    parts_with_indices = sorted(zip(parts_indices, parts), key=lambda x: x[0])
    _, parts = zip(*parts_with_indices)

    for part in parts:
        part_id = part.legacyId

        content_for_part = contents[part_id]
        if not options.is_not_replace_chars:
            content_for_part = _replace_chars(content_for_part)

        # some parts do not have an image
        if part_id in images_by_part:
            imgs = images_by_part[part_id]
            content_for_part = _replace_image_urls(content_for_part, imgs)

        contents[part_id] = content_for_part

    # TODO suffix final complete : not in api but in web page for series
    # data for React contains what is needed in JSON

    # representative volume
    repr_volume = volumes[0]
    author = _extract_author(repr_volume.creators)

    # first part
    repr_part = parts[0]
    volume_num, part_num = nums_for_parts[repr_part.legacyId]
    # TODO in case multiple volumes, do not set volume num? or do
    # something else
    collection = epub.CollectionMetadata(series.legacyId, series.title, volume_num)
    # FIXME placeholder
    # FIXME resolive cover later
    cover_image = images_by_part[repr_part.legacyId][0]

    contents = [contents[part.legacyId] for part in parts]

    if len(parts) == 1:
        # single part
        part = parts[0]
        volume_num, part_num = nums_for_parts[part.legacyId]

        identifier_base = part.slug
        title = f"{part.title}"
        # single part => single volume: part numbers relative to
        # that volume
        toc = [f"Part {part_num}"]
    else:
        volume_index = set()
        volumes = []
        for part in parts:
            volume_num, part_num = nums_for_parts[part.legacyId]
            if volume_num in volume_index:
                continue
            volume_index.add(volume_num)
            volume = volumes_index[volume_num]
            volumes.append(volume)

        if len(volumes) > 1:
            volume_nums = sorted(list(volume_index))
            volume_nums = [str(vn) for vn in volume_nums]
            volume_nums = ", ".join(volume_nums[:-1]) + " & " + volume_nums[-1]
            title_base = f"{series.title}: Volumes {volume_nums}"

            volume_num0, part_num0 = nums_for_parts[parts[0].legacyId]
            volume_num1, part_num1 = nums_for_parts[parts[-1].legacyId]

            part_nums = f"Parts {volume_num0}.{part_num0} to {volume_num1}.{part_num1}"

            toc = [part.title for part in parts]
            title = f"{title_base} [{part_nums}]"
        else:
            volume = volumes[0]
            title_base = volume.title

            toc = [f"Part {nums_for_parts[part.legacyId][1]}" for part in parts]

            _, part_num0 = nums_for_parts[parts[0].legacyId]
            _, part_num1 = nums_for_parts[parts[-1].legacyId]

            title = f"{title_base} [Parts {part_num0} to {part_num1}]"

        identifier_base = series.slug

    identifier = identifier_base + str(int(time.time()))

    book_details = epub.BookDetails(
        identifier, title, author, collection, cover_image, toc, contents, images
    )

    return book_details


def _extract_author(creators, default="Unknown Author"):
    for creator in creators:
        if creator.role == "AUTHOR":
            return creator.name
    return default


def _index_volumes_in_series_by_num(volumes_in_series):
    volumes_index = {}
    for index_volume, volume in enumerate(volumes_in_series):
        volumes_index[index_volume + 1] = volume

    return volumes_index


def _compute_nums_for_parts(volumes_in_series, parts_in_volumes):
    parts_index = {}
    for index_volume, volume in enumerate(volumes_in_series):
        for volume_id, volume_parts in parts_in_volumes.items():
            if volume.legacyId == volume_id:
                for index_part, part in enumerate(volume_parts):
                    vol_part_key = (index_volume + 1, index_part + 1)
                    parts_index[part.legacyId] = vol_part_key

    return parts_index


# TODO way to indicate failure of some kind
# TODO timeout for the API requests


async def _fetch_toc_for_part(api: JNCLabsAPI, part_id, result):
    content = await api.fetch_xhtml(part_id)
    toc = Addict(json.loads(content))
    result.add(Data(DTYPE_PART_TOC, part_id, toc))


async def _download_image(api: JNCLabsAPI, part_id, img_url, result):
    img_bytes = await api.fetch_image_from_cdn(img_url)
    result.add(Data(DTYPE_PART_IMAGE, part_id, epub.Image(img_url, img_bytes)))


def _overwrite(array1, array2):
    array1.splice(0, len(array1), array2)


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


def _replace_image_urls(content, images):
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


async def fetch_for_specs(api, jnc_resource, part_spec, result):
    async with trio.open_nursery() as nursery:
        if jnc_resource.resource_type == jncweb.RESOURCE_TYPE_SERIES:
            series_slug = jnc_resource.slug
            nursery.start_soon(partial(_fetch_series, api, series_slug, result))
        elif jnc_resource.resource_type == jncweb.RESOURCE_TYPE_VOLUME:
            if jnc_resource.is_new_website:
                series_slug, _ = jnc_resource.slug
                nursery.start_soon(partial(_fetch_series, api, series_slug, result))
            else:
                volume_slug = jnc_resource.slug
                series = await _fetch_series_for_volume(api, volume_slug, result)
                series_slug = series.slug
        elif jnc_resource.resource_type == jncweb.RESOURCE_TYPE_PART:
            part_slug = jnc_resource.slug
            # slightly inefficient
            series = await _fetch_series_for_part(api, part_slug, result)
            series_slug = series.slug

        nursery.start_soon(
            partial(
                _deep_fetch_volumes_for_series,
                api,
                nursery,
                series_slug,
                part_spec,
                result,
            )
        )


async def to_part_spec(api, jnc_resource, result: Result):
    if jnc_resource.resource_type == jncweb.RESOURCE_TYPE_SERIES:
        return IdentifierSpec(spec.SERIES)

    elif jnc_resource.resource_type == jncweb.RESOURCE_TYPE_VOLUME:
        if jnc_resource.is_new_website:
            # for volume on new website => where is a tuple (series_slug, volume num)
            series_slug, volume_number = jnc_resource.slug

            volumes = await _fetch_volumes_for_series(api, series_slug, result)

            volume_index = volume_number - 1
            if volume_index not in range(len(volumes)):
                raise jncweb.BadWebURLError(
                    f"Incorrect volume number in URL: {jnc_resource.url}"
                )

            volume = volumes[volume_index]
        else:
            volume_slug = jnc_resource.slug
            volume = await _fetch_volume(api, volume_slug)

        return IdentifierSpec(spec.VOLUME, volume.legacyId)

    elif jnc_resource.resource_type == jncweb.RESOURCE_TYPE_PART:
        local_result = Result()
        async with trio.open_nursery() as nursery:
            nursery.start_soon(
                partial(_fetch_part, api, jnc_resource.slug, local_result)
            )
            nursery.start_soon(
                partial(_fetch_volume_for_part, api, jnc_resource.slug, local_result)
            )
        part = local_result.get_by_dtype(DTYPE_PART)[0].data
        volume = local_result.get_by_dtype(DTYPE_VOLUME)[0].data

        result.merge(local_result)

        return IdentifierSpec(spec.PART, volume.legacyId, part.legacyId)


async def _fetch_series(api, series_id, result):
    series = await api.fetch_data("series", series_id)
    result.add(Data(DTYPE_SERIES, series.legacyId, series))
    return series


async def _deep_fetch_volumes_for_series(
    api: JNCLabsAPI, nursery, series_id, part_spec, result
):
    volumes = await _fetch_volumes_for_series(api, series_id, result)

    for i, volume_data in enumerate(volumes):
        volume_id = volume_data.legacyId
        volume_num = i + 1
        if not part_spec.has_volume(volume_num, volume_id):
            continue

        volume_id = volume_data.legacyId
        result.add(Data(DTYPE_VOLUME, volume_id, volume_data))

        nursery.start_soon(
            partial(
                _deep_fetch_parts_for_volume,
                api,
                nursery,
                volume_id,
                volume_num,
                part_spec,
                result,
            )
        )


async def _fetch_volumes_for_series(api: JNCLabsAPI, series_id, result):
    volumes = [
        volume
        async for volume in api.paginate(
            partial(api.fetch_data, "series", series_id, "volumes")
        )
    ]
    result.add(Data(DTYPE_SERIES_VOLUMES, series_id, volumes))
    return volumes


async def _fetch_volume(api: JNCLabsAPI, volume_id, result):
    volume = await api.fetch_data("volumes", volume_id)
    result.add(Data(DTYPE_VOLUME, volume.legacyId, volume))
    return volume


async def _deep_fetch_parts_for_volume(
    api: JNCLabsAPI, nursery, volume_id, volume_num, part_spec, result
):
    parts = await _fetch_parts_for_volume(api, volume_id, result)
    for i, part_data in enumerate(parts):
        part_id = part_data.legacyId
        part_num = i + 1
        if not part_spec.has_part(volume_num, part_num, part_id):
            continue

        part_id = part_data.legacyId
        result.add(Data(DTYPE_PART, part_id, part_data))

        nursery.start_soon(
            partial(_deep_fetch_content_for_part, api, nursery, part_id, result)
        )


async def _fetch_series_for_volume(api: JNCLabsAPI, volume_id, result):
    series = await api.fetch_data("volumes", volume_id, "serie")
    result.add(Data(DTYPE_SERIES, series.legacyId, series))
    return series


async def _fetch_parts_for_volume(api: JNCLabsAPI, volume_id, result: Result):
    parts = [
        part
        async for part in api.paginate(
            partial(api.fetch_data, "volumes", volume_id, "parts")
        )
    ]
    result.add(Data(DTYPE_VOLUME_PARTS, volume_id, parts))
    return parts


async def _fetch_part(api: JNCLabsAPI, part_id, result):
    part = await api.fetch_data("parts", part_id)
    result.add(Data(DTYPE_PART, part.legacyId, part))
    return part


async def _deep_fetch_content_for_part(api: JNCLabsAPI, nursery, part_id, result):
    # TODO handle unavailable content (not preview + not catchup)
    # TODO handle errors
    content = await api.fetch_content(part_id, "data.xhtml")

    result.add(Data(DTYPE_PART_XHTML, part_id, content))
    img_urls = _img_urls(content)
    if len(img_urls) > 0:
        # TODO handle failures
        for img_url in img_urls:
            nursery.start_soon(partial(_download_image, api, part_id, img_url, result))


async def _fetch_series_for_part(api: JNCLabsAPI, part_id, result):
    series = await api.fetch_data("parts", part_id, "serie")
    result.add(Data(DTYPE_SERIES, series.legacyId, series))
    return series


async def _fetch_volume_for_part(api: JNCLabsAPI, part_id, result):
    volume = await api.fetch_data("parts", part_id, "volume")
    result.add(Data(DTYPE_VOLUME, volume.legacyId, volume))
    return volume
