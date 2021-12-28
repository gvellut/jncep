from collections import OrderedDict
import itertools
import json
import logging
import operator
from pathlib import Path
import traceback

from addict import Dict as Addict
from atomicwrites import atomic_write
import dateutil.parser

from . import epub, jncapi, jncweb, spec
from .utils import green

logger = logging.getLogger(__package__)

CONFIG_DIRPATH = Path.home() / ".jncep"


class NoRequestedPartAvailableError(Exception):
    pass


def analyze_metadata(jnc_resource: jncweb.JNCResource):
    # takes order of parts as returned by API
    # (irrespective of actual partNumber)
    # reorder by volume ordering

    if jnc_resource.resource_type in (
        jncweb.RESOURCE_TYPE_PART,
        jncweb.RESOURCE_TYPE_VOLUME,
    ):
        series = jncapi.Series(jnc_resource.raw_metadata.serie)
    else:
        series = jncapi.Series(jnc_resource.raw_metadata)

    volumes = []
    volume_index = {}
    for raw_volume in series.raw_series.volumes:
        volume_num = len(volumes) + 1
        volume = jncapi.Volume(raw_volume, raw_volume.id, volume_num)
        volume_index[volume.volume_id] = volume
        volumes.append(volume)

    is_warned = False
    for raw_part in series.raw_series.parts:
        volume_id = raw_part.volumeId
        volume: jncapi.Volume = volume_index[volume_id]
        num_in_volume = len(volume.parts) + 1
        part = jncapi.Part(raw_part, volume, num_in_volume)
        volume.parts.append(part)

    parts = []
    for volume in volumes:
        for part in volume.parts:
            # volume number ordering and part number ordering sometimes do not match
            # actually just for Altina volume 8 / 9
            # so set absolute num in sequential order according to volumes
            part.absolute_num = len(parts) + 1
            parts.append(part)

            # some series have a gap in the part number ie index does not correspond
            # to field partNumber e.g. economics of prophecy starting at part 10
            # print warning
            if part.absolute_num != part.raw_part.partNumber and not is_warned:
                # not an issue in practice so leave it in debug mode only
                logger.debug(
                    f"Absolute part number returned by API doesn't correspond to "
                    f"its actual position in series (corrected, starting at part "
                    f"{part.raw_part.partNumber} found in volume {volume.num})"
                )
                is_warned = True

    series.volumes = volumes
    series.parts = parts

    return series


def canonical_series(jnc_url, email, password):
    token = None
    try:
        jnc_resource = jncweb.resource_from_url(jnc_url)

        logger.info(f"Login with email '{email}'...")
        token = jncapi.login(email, password)

        return tracking_series_metadata(token, jnc_resource)
    finally:
        if token:
            try:
                logger.info("Logout...")
                jncapi.logout(token)
            except Exception:
                pass


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
    jncapi.fetch_metadata(token, jnc_resource)

    series = analyze_metadata(jnc_resource)
    series_slug = series.raw_series.titleslug
    series_url = jncweb.url_from_series_slug(series_slug)

    return series, series_url


def process_series_for_tracking(tracked_series, series, series_url):
    # record current last part + name
    if len(series.parts) == 0:
        # no parts yet
        pn = 0
        # 0000-... not a valid date so 1111-...
        pdate = "1111-11-11T11:11:11.111Z"
    else:
        pn = spec.to_relative_spec_from_part(series.parts[-1])
        pdate = series.parts[-1].raw_part.launchDate

    tracked_series[series_url] = {
        "part_date": pdate,
        "part": pn,  # now just for show
        "name": series.raw_series.title,
    }

    if len(series.parts) == 0:
        logger.info(
            green(
                f"The series '{series.raw_series.title}' is now tracked, starting "
                f"from the beginning"
            )
        )
    else:
        relative_part = spec.to_relative_spec_from_part(series.parts[-1])
        part_date = dateutil.parser.parse(series.parts[-1].raw_part.launchDate)
        part_date_formatted = part_date.strftime("%b %d, %Y")
        logger.info(
            green(
                f"The series '{series.raw_series.title}' is now tracked, starting "
                f"after part {relative_part} [{part_date_formatted}]"
            )
        )


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
        jncapi.fetch_metadata(token, jnc_resource)
        series_id = jnc_resource.raw_metadata.id
        title = jnc_resource.raw_metadata.title
        logger.info(f"Follow '{title}'...")
        jncapi.follow_series(token, series_id)

        new_synced.append(series_url)

    if is_delete:
        for jnc_resource in follows:
            if jnc_resource.url not in tracked_series:
                series_id = jnc_resource.raw_metadata.id
                title = jnc_resource.raw_metadata.title
                logger.warning(f"Unfollow '{title}'...")
                jncapi.unfollow_series(token, series_id)

                del_synced.append(jnc_resource.url)

    if new_synced or del_synced:
        logger.info(green("The list of followed series has been sucessfully updated!"))
    else:
        logger.info(green("Everything is already synced!"))

    return new_synced, del_synced


def update_url_series(
    token,
    jnc_url,
    epub_generation_options,
    tracked_series,
    updated_series,
    is_sync,
    new_synced,
    is_whole_volume,
):
    jnc_resource = jncweb.resource_from_url(jnc_url)

    logger.info(f"Fetching metadata for '{jnc_resource}'...")
    jncapi.fetch_metadata(token, jnc_resource)

    series = analyze_metadata(jnc_resource)

    series_slug = series.raw_series.titleslug
    series_url = jncweb.url_from_series_slug(series_slug)

    if is_sync:
        # not very useful but make it possible
        # only consider newly synced series if --sync used
        # to mirror case with no URL argument
        if series_url not in new_synced:
            logger.warning(
                f"The series '{series.raw_series.title}' is not among the "
                f"tracked series added from syncing. Use 'jncep update' "
                "without --sync."
            )
            return
        is_updated = _create_epub_from_beginning(token, series, epub_generation_options)

    else:
        if series_url not in tracked_series:
            logger.warning(
                f"The series '{series.raw_series.title}' is not tracked! "
                f"Use the 'jncep track add' command first."
            )
            return

        series_details = tracked_series[series_url]
        is_updated = _create_updated_epub(
            token, series, series_details, epub_generation_options, is_whole_volume
        )

    if is_updated:
        logger.info(green(f"The series '{series.raw_series.title}' has been updated!"))
        updated_series.append(series)


def update_all_series(
    token,
    epub_generation_options,
    tracked_series,
    updated_series,
    is_sync,
    new_synced,
    is_whole_volume,
):
    has_error = False
    for series_url, series_details in tracked_series.items():
        try:
            if is_sync and series_url not in new_synced:
                continue

            jnc_resource = jncweb.resource_from_url(series_url)

            logger.info(f"Fetching metadata for '{jnc_resource}'...")
            jncapi.fetch_metadata(token, jnc_resource)

            series = analyze_metadata(jnc_resource)

            if is_sync:
                is_updated = _create_epub_from_beginning(
                    token, series, epub_generation_options
                )
            else:
                is_updated = _create_updated_epub(
                    token,
                    series,
                    series_details,
                    epub_generation_options,
                    is_whole_volume,
                )

            if is_updated:
                logger.info(
                    green(f"The series '{series.raw_series.title}' has been updated!")
                )
                updated_series.append(series)

        except Exception as ex:
            has_error = True
            logger.error("An error occured while updating the series:")
            logger.error(str(ex))
            logger.debug(traceback.format_exc())

    return has_error


def _create_epub_from_beginning(token, series, epub_generation_options):
    if len(series.parts) == 0:
        new_parts = None
    else:
        # complete series
        new_parts = spec.analyze_part_specs(series, ":", True)

    if not new_parts:
        # no new part
        logger.warning(
            f"The series '{series.raw_series.title}' has no parts available!",
        )
        return False

    return _create_epub_with_updated_parts(
        token, series, new_parts, epub_generation_options
    )


def _create_updated_epub(
    token, series, series_details, epub_generation_options, is_whole_volume
):
    if series_details.part == 0:
        # special processing : means there was no part available when the
        # series was started tracking

        # still no part ?
        if len(series.parts) == 0:
            is_updated = False
            # just to bind or pylint complains
            new_parts = None
        else:
            is_updated = True
            # complete series
            new_parts = spec.analyze_part_specs(series, ":", True)
    else:
        # for others, look at the date if there
        if not series_details.part_date:
            # if not => old format, first lookup date of last part and use that
            # TODO possible to do that for all ie no need to keep the date around
            last_part = spec.to_part_from_relative_spec(series, series_details.part)
            last_update_date = last_part.raw_part.launchDate
        else:
            last_update_date = series_details.part_date

        new_parts = _parts_released_after_date(series, last_update_date)
        is_updated = len(new_parts) > 0

    if not is_updated:
        # no new part
        logger.warning(f"The series '{series.raw_series.title}' has not been updated!")
        return False

    parts_to_download = list(new_parts)
    if is_whole_volume:
        for part in new_parts:
            for volpart in part.volume.parts:
                if volpart not in parts_to_download:
                    parts_to_download.append(volpart)
        parts_to_download.sort(key=operator.attrgetter("absolute_num"))

    return _create_epub_with_updated_parts(
        token, series, parts_to_download, epub_generation_options
    )


def _parts_released_after_date(series, date):
    parts = []
    comparison_date = dateutil.parser.parse(date)
    for part in series.parts:
        # all date strings are in ISO format
        # so no need to parse really
        # parsing just to be safe
        launch_date = dateutil.parser.parse(part.raw_part.launchDate)
        if launch_date > comparison_date:
            parts.append(part)
    return parts


def _create_epub_with_updated_parts(token, series, new_parts, epub_generation_options):
    # just wrap _create_epub_with_requested_parts but handle case where parts
    # have expired
    try:
        create_epub_with_requested_parts(
            token, series, new_parts, epub_generation_options
        )
        return True
    except NoRequestedPartAvailableError:
        logger.error("The parts that need to be updated have all expired!")
        return False


def create_epub_with_requested_parts(
    token, series, parts_to_download, epub_generation_options
):
    # preview => parts 1 of each volume, always available
    # not expired => prepub
    available_parts_to_download = list(
        filter(
            lambda p: p.raw_part.preview or not p.raw_part.expired, parts_to_download
        )
    )

    if len(available_parts_to_download) == 0:
        raise NoRequestedPartAvailableError(
            "None of the requested parts are available for reading"
        )

    if len(available_parts_to_download) != len(parts_to_download):
        logger.warning("Some of the requested parts are not available for reading !")

    if epub_generation_options.is_by_volume:
        for _, g in itertools.groupby(
            available_parts_to_download, lambda p: p.volume.volume_id
        ):
            parts = list(g)
            epub.create_epub(token, series, parts, epub_generation_options)
    else:
        epub.create_epub(
            token, series, available_parts_to_download, epub_generation_options
        )
