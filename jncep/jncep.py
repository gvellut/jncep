import itertools
import logging
import operator
import traceback

import dateutil.parser

from . import core, jncapi
from .utils import green

logger = logging.getLogger(__package__)


class NoRequestedPartAvailableError(Exception):
    pass


def canonical_series(jnc_url, email, password):
    token = None
    try:
        jnc_resource = jncapi.resource_from_url(jnc_url)

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


def tracking_series_metadata(token, jnc_resource):
    logger.info(f"Fetching metadata for '{jnc_resource}'...")
    jncapi.fetch_metadata(token, jnc_resource)

    series = core.analyze_metadata(jnc_resource)
    series_slug = series.raw_series.titleslug
    series_url = jncapi.url_from_series_slug(series_slug)

    return series, series_url


def process_series_for_tracking(tracked_series, series, series_url):
    # record current last part + name
    if len(series.parts) == 0:
        # no parts yet
        pn = 0
        # 0000-... not a valid date so 1111-...
        pdate = "1111-11-11T11:11:11.111Z"
    else:
        pn = core.to_relative_part_string(series, series.parts[-1])
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
        relative_part = core.to_relative_part_string(series, series.parts[-1])
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

    core.write_tracked_series(tracked_series)

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

        jnc_resource = jncapi.resource_from_url(series_url)
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
    jnc_resource = jncapi.resource_from_url(jnc_url)

    logger.info(f"Fetching metadata for '{jnc_resource}'...")
    jncapi.fetch_metadata(token, jnc_resource)

    series = core.analyze_metadata(jnc_resource)

    series_slug = series.raw_series.titleslug
    series_url = jncapi.url_from_series_slug(series_slug)

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

            jnc_resource = jncapi.resource_from_url(series_url)

            logger.info(f"Fetching metadata for '{jnc_resource}'...")
            jncapi.fetch_metadata(token, jnc_resource)

            series = core.analyze_metadata(jnc_resource)

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
        new_parts = core.analyze_part_specs(series, ":", True)

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
            new_parts = core.analyze_part_specs(series, ":", True)
    else:
        # for others, look at the date if there
        if not series_details.part_date:
            # if not => old format, first lookup date of last part and use that
            # TODO possible to do that for all ie no need to keep the date around
            last_part = core.to_part(series, series_details.part)
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
            core.create_epub(token, series, parts, epub_generation_options)
    else:
        core.create_epub(
            token, series, available_parts_to_download, epub_generation_options
        )
