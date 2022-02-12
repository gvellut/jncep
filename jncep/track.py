from collections import OrderedDict
import json
import logging
from pathlib import Path

from addict import Dict as Addict
from atomicwrites import atomic_write
import attr
import dateutil.parser

from . import jncweb, spec
from .core import all_parts, FetchOptions
from .jncweb import resource_from_url
from .utils import green

logger = logging.getLogger(__package__)


# TODO change => in App folder for windows + config file there too
CONFIG_DIRPATH = Path.home() / ".jncep"


@attr.s
class LastPartSpec:
    def has_volume(self, ref_volume) -> bool:
        index_volume = ref_volume.volume_num
        return index_volume == ref_volume.num_volumes

    def has_part(self, ref_part) -> bool:
        # assumes has_volume already checked
        index_part = ref_part.part_num
        return index_part == ref_part.num_parts_in_volume


def read_tracked_series():
    try:
        with _tracked_series_filepath().open() as json_file:
            # Explicit ordereddict (although should be fine without
            # since Python >= 3.6 dicts are ordered ; spec since 3.7)
            data = json.load(json_file, object_pairs_hook=OrderedDict)
            return _convert_to_latest_format(Addict(data))
    except FileNotFoundError:
        # first run ?
        return Addict({})


def _convert_to_latest_format(data):
    converted = {}
    # while at it convert from old format
    # legacy format for tracked parts : just the part instead of object
    # with keys part, name
    # key is slug
    # TODO rename "name" field into "title"
    for series_url_or_slug, value in data.items():
        if not isinstance(value, dict):
            series_slug = series_url_or_slug
            series_url = jncweb.url_from_series_slug(series_slug)
            # low effort way to get some title
            name = series_slug.replace("-", " ").title()
            value = Addict({"name": name, "part": value})
            converted[series_url] = value
        else:
            converted[series_url_or_slug] = value

    converted_b = {}
    for legacy_series_url, value in converted.items():
        new_series_url = jncweb.to_new_website_series_url(legacy_series_url)
        converted_b[new_series_url] = value

    return converted_b


def write_tracked_series(tracked):
    _ensure_config_dirpath_exists()
    with atomic_write(str(_tracked_series_filepath().resolve()), overwrite=True) as f:
        f.write(json.dumps(tracked, sort_keys=True, indent=2))


def _tracked_series_filepath():
    return CONFIG_DIRPATH / "tracked.json"


def _ensure_config_dirpath_exists():
    CONFIG_DIRPATH.mkdir(parents=False, exist_ok=True)


def tracking_series_metadata(token, jnc_resource):
    logger.info(f"Fetching metadata for '{jnc_resource}'...")
    jncapi_legacy.fetch_metadata(token, jnc_resource)

    series = analyze_metadata(jnc_resource)
    series_slug = series.raw_series.titleslug
    series_url = jncweb.url_from_series_slug(series_slug)

    return series, series_url


async def process_series_for_tracking(session, tracked_series, series_url):
    jnc_resource = resource_from_url(series_url)
    # TODO change ; combine LastpartSpec+ fetch_options
    part_spec = LastPartSpec()
    fetch_options = FetchOptions(is_download_content=False, is_download_cover=False)
    series = await session.fetch_for_specs(jnc_resource, part_spec, fetch_options)

    parts = all_parts(series)
    last_part = None
    if parts:
        last_part = parts[-1]

    # record current last part + name
    if not last_part:
        # no parts yet
        pn = 0
        # 0000-... not a valid date so 1111-...
        pdate = "1111-11-11T11:11:11.111Z"

        logger.info(
            green(
                f"The series '{series.raw_data.title}' is now tracked, starting "
                f"from the beginning"
            )
        )
    else:
        pn = spec.to_relative_spec_from_part(last_part)
        pdate = last_part.raw_data.launch

        relative_part = spec.to_relative_spec_from_part(last_part)
        part_date = dateutil.parser.parse(last_part.raw_data.launch)
        part_date_formatted = part_date.strftime("%b %d, %Y")
        logger.info(
            green(
                f"The series '{series.raw_data.title}' is now tracked, starting "
                f"after part {relative_part} [{part_date_formatted}]"
            )
        )

    tracked_series[series_url] = {
        "part_date": pdate,
        "part": pn,  # now just for show
        "name": series.raw_data.title,
    }


def sync_series_forward(token, follows, tracked_series, is_delete):
    # sync local tracked series based on remote follows
    new_synced = []
    del_synced = []
    for jnc_resource in follows:
        if jnc_resource.url in tracked_series:
            continue
        series, series_url = tracking_series_metadata(token, jnc_resource)
        process_series_for_tracking(tracked_series, series, series_url)

        new_synced.append(series_url)

    if is_delete:
        followed_index = {f.url: f for f in follows}
        # to avoid dictionary changed size during iteration
        for series_url, series_data in list(tracked_series.items()):
            if series_url not in followed_index:
                del tracked_series[series_url]

                logger.warning(f"The series '{series_data.name}' is no longer tracked")

                del_synced.append(series_url)

    write_tracked_series(tracked_series)

    if new_synced or del_synced:
        logger.info(green("The list of tracked series has been sucessfully updated!"))
    else:
        logger.info(green("Everything is already synced!"))

    return new_synced, del_synced


def sync_series_backward(token, follows, tracked_series, is_delete):
    # sync remote follows based on locally tracked series
    new_synced = []
    del_synced = []

    followed_index = {f.url: f for f in follows}
    for series_url in tracked_series:
        # series_url is the latest URL format (same as the follows)
        if series_url in followed_index:
            continue

        jnc_resource = jncweb.resource_from_url(series_url)
        logger.info(f"Fetching metadata for '{jnc_resource}'...")
        jncapi_legacy.fetch_metadata(token, jnc_resource)
        series_id = jnc_resource.raw_metadata.id
        title = jnc_resource.raw_metadata.title
        logger.info(f"Follow '{title}'...")
        jncapi_legacy.follow_series(token, series_id)

        new_synced.append(series_url)

    if is_delete:
        for jnc_resource in follows:
            if jnc_resource.url not in tracked_series:
                series_id = jnc_resource.raw_metadata.id
                title = jnc_resource.raw_metadata.title
                logger.warning(f"Unfollow '{title}'...")
                jncapi_legacy.unfollow_series(token, series_id)

                del_synced.append(jnc_resource.url)

    if new_synced or del_synced:
        logger.info(green("The list of followed series has been sucessfully updated!"))
    else:
        logger.info(green("Everything is already synced!"))

    return new_synced, del_synced
