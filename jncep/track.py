from collections import OrderedDict
from functools import partial
import json
import logging
from pathlib import Path

from addict import Dict as Addict
from atomicwrites import atomic_write
import dateutil.parser

from . import config, core, jncweb, spec, utils
from .trio_utils import bag

logger = logging.getLogger(__package__)
console = utils.getConsole()

TRACK_FILE_NAME = "tracked.json"

DEFAULT_CONFIG_FILEPATH = config.config_dir() / TRACK_FILE_NAME

FROM_BEGINNING_CHECK_DATE = "1000-10-10T10:10:10Z"


class TrackConfigManager:
    def __init__(self, config_file_path=None):
        if not config_file_path:
            self.config_file_path = DEFAULT_CONFIG_FILEPATH
        else:
            if config_file_path is Path:
                self.config_file_path = config_file_path
            else:
                self.config_file_path = Path(config_file_path)
            # TODO check read write permission / is file etc...

    # TODO async
    def read_tracked_series(self):
        try:
            with self.config_file_path.open() as json_file:
                # Explicit ordereddict (although should be fine without
                # since Python >= 3.6 dicts are ordered ; spec since 3.7)
                data = json.load(json_file, object_pairs_hook=OrderedDict)
                data = Addict(data)
                return self._convert_to_latest_format(data)
        except FileNotFoundError:
            # first run ?
            return Addict({})

    def write_tracked_series(self, tracked):
        utils.ensure_directory_exists(self.config_file_path.parent)
        with atomic_write(str(self.config_file_path.resolve()), overwrite=True) as f:
            f.write(json.dumps(tracked, sort_keys=True, indent=2))

    def _convert_to_latest_format(self, data):
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


async def track_series(session, tracked_series, series, is_beginning=False):
    parts = core.all_parts_meta(series)

    # record current last part + name
    if not parts or is_beginning:
        # no parts yet, special value 0: processed in update with special case
        pn = 0
        # 0000-... not a valid date so 1111-...
        pdate = "1111-11-11T11:11:11.111Z"

        console.info(
            f"The series '[highlight]{series.raw_data.title}[/]' is now tracked, "
            "starting [highlight]from the beginning[/]",
            style="success",
        )
    else:
        # for the tracking, need the last date: almost always the date of the last part
        # but for some series with volumes released in parallel, can be different
        # see GH #28, also update._update_tracking_data
        # so do additional work for this

        parts = core.all_parts_meta(series)
        last_part_date = max(parts, key=lambda x: x.raw_data.launch)

        last_part_number = parts[-1]
        pn = spec.to_relative_spec_from_part(last_part_number)
        pdate = last_part_date.raw_data.launch

        part_date = dateutil.parser.parse(pdate)
        part_date_formatted = part_date.strftime("%b %d, %Y")
        # TODO display something in case last_part_number and last_part_date_raw do not
        # correspond to the same part?
        console.info(
            f"The series '[highlight]{series.raw_data.title}[/]' is now tracked, "
            f"starting after part [highlight]{pn} [{part_date_formatted}]"
            f"[/]",
            style="success",
        )

    if is_beginning:
        # TODO add a flag to indicate --beginning ; keep track of the last part
        # anyway instead of the special part=0 and last_check_date in that case
        # see also cli.track list_track_series
        # date far in the past: used in case of --use-events => will always end up
        # checking the full metadata of the series (as if --use-events was not used)
        last_check_date = FROM_BEGINNING_CHECK_DATE
    else:
        last_check_date = utils.isoformat_with_z(session.now)

    series_url = jncweb.url_from_series_slug(series.raw_data.slug)
    # TODO class for trackData
    tracked_series[series_url] = Addict(
        {
            "part_date": pdate,
            "part": pn,  # now just for showing to the user in track list
            "name": series.raw_data.title,
            "series_id": series.series_id,
            "last_check_date": last_check_date,
        }
    )


async def sync_series_forward(
    session, follows, tracked_series, is_delete, is_beginning=False
):
    # sync local tracked series based on remote follows
    new_synced = []
    del_synced = []

    async def do_track(jnc_resource):
        series_id = await core.resolve_series(session, jnc_resource)
        series = await core.fetch_meta(session, series_id)
        await track_series(session, tracked_series, series, is_beginning)
        # manga already excluded from follows so no need to check

        series_url = jncweb.url_from_series_slug(series.raw_data.slug)
        new_synced.append(series_url)

    tasks = []
    for jnc_resource in follows:
        if jnc_resource.url in tracked_series:
            continue
        tasks.append(partial(do_track, jnc_resource))

    # result doesn't matter ; just for the exceptions
    await bag(tasks)

    if is_delete:
        followed_index = {f.url: f for f in follows}
        # list() to avoid dictionary changed size during iteration
        for series_url, series_data in list(tracked_series.items()):
            if series_url not in followed_index:
                del tracked_series[series_url]

                console.warning(
                    f"The series '[highlight]{series_data.name}[/]' is no longer "
                    "tracked"
                )

                del_synced.append(series_url)

    return new_synced, del_synced


async def sync_series_backward(session, follows, tracked_series, is_delete):
    # sync remote follows based on locally tracked series
    new_synced = []
    del_synced = []

    async def do_follow(jnc_resource):
        console.info(f"Fetch metadata for '{jnc_resource}'...")
        series_id = await core.resolve_series(session, jnc_resource)
        series = await core.fetch_meta(session, series_id)
        title = series.raw_data.title

        console.info(f"Follow '{title}'...")
        await session.api.follow_series(series.series_id)

        new_synced.append(series_url)

    followed_index = {f.url: f for f in follows}
    tasks = []
    for series_url in tracked_series:
        # series_url is the latest URL format (same as the follows)
        if series_url in followed_index:
            continue
        jnc_resource = jncweb.resource_from_url(series_url)
        tasks.append(partial(do_follow, jnc_resource))

    if is_delete:

        async def do_undollow(jnc_resource):
            # use the follow_raw_data: to avoid another call to the API
            series_id = jnc_resource.follow_raw_data.id
            title = jnc_resource.follow_raw_data.title
            console.warning(f"Unfollow '{title}'...")
            await session.api.unfollow_series(series_id)

            del_synced.append(jnc_resource.url)

        for jnc_resource in follows:
            if jnc_resource.url not in tracked_series:
                tasks.append(partial(do_undollow, jnc_resource))

    # no result needed ; just for the exceptions
    await bag(tasks)

    return new_synced, del_synced
