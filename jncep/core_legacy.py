import itertools
import logging
import operator
import traceback

import dateutil.parser

from . import epub, jncapi_legacy, jncweb, spec
from .utils import green

logger = logging.getLogger(__package__)


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
        series = jncapi_legacy.Series(jnc_resource.raw_metadata.serie)
    else:
        series = jncapi_legacy.Series(jnc_resource.raw_metadata)

    volumes = []
    volume_index = {}
    for raw_volume in series.raw_series.volumes:
        volume_num = len(volumes) + 1
        volume = jncapi_legacy.Volume(raw_volume, raw_volume.id, volume_num)
        volume_index[volume.volume_id] = volume
        volumes.append(volume)

    is_warned = False
    for raw_part in series.raw_series.parts:
        volume_id = raw_part.volumeId
        volume: jncapi_legacy.Volume = volume_index[volume_id]
        num_in_volume = len(volume.parts) + 1
        part = jncapi_legacy.Part(raw_part, volume, num_in_volume)
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
    jncapi_legacy.fetch_metadata(token, jnc_resource)

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
            jncapi_legacy.fetch_metadata(token, jnc_resource)

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
        new_parts = spec.analyze_part_specs(series, ":")

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
            new_parts = spec.analyze_part_specs(series, ":")
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
