from collections import namedtuple
from functools import partial
import logging
import sys

import attr
import dateutil
import trio

from . import core, jncweb, spec, utils
from .trio_utils import bag

logger = logging.getLogger(__package__)
console = utils.getConsole()


@attr.s
class UpdateResult:
    series = attr.ib(None)
    is_error = attr.ib(False)
    is_updated = attr.ib(None)
    is_considered = attr.ib(True)
    # to indicate a series with expired parts only
    # will set to latest part or will always have error
    # if stalled
    is_force_set_updated = attr.ib(False)
    is_update_last_checked = attr.ib(True)
    parts_downloaded = attr.ib(None)


UpdateOptions = namedtuple(
    "UpdateOptions",
    [
        "is_sync",
        "is_whole_volume",
        "is_whole_volume_on_final_part",
        "is_use_events",
    ],
)


async def update_url_series(
    session,
    jnc_url,
    epub_generation_options,
    tracked_series,
    new_synced,
    update_options,
):
    # for single url => if error no catch : let it crash and report to the user
    jnc_resource = jncweb.resource_from_url(jnc_url)
    series_id = await core.resolve_series(session, jnc_resource)
    series = await core.fetch_meta(session, series_id)

    series_url = jncweb.url_from_series_slug(series.raw_data.slug)

    if series_url not in tracked_series:
        console.warning(
            f"The series '[highlight]{series.raw_data.title}[/]' is not tracked! "
            f"Use the 'jncep track add' command first."
        )
        return

    if update_options.is_sync:
        # not very useful but make it possible
        # only consider newly synced series if --sync used
        # to mirror case with no URL argument
        if series_url not in new_synced:
            console.warning(
                f"The series '[highlight]{series.raw_data.title}[/]' is not "
                "among the tracked series added from syncing. Use 'jncep update' "
                "without --sync."
            )
            return

    series_details = tracked_series[series_url]

    is_need_check = True
    is_check_events = update_options.is_use_events and _can_use_events_feed(
        series_details
    )
    if is_check_events:
        console.status("Checking J-Novel Club events feed...", clear=False)
        start_date = series_details.last_check_date
        events = await core.fetch_events(session, start_date)
        is_need_check = _verify_series_needs_update_check(events, series_details)
        if not is_need_check:
            update_result = UpdateResult(is_updated=False)
        console.pop_status()

    if is_need_check:
        # the series has just been synced so force EPUB gen from start in this case
        is_force_from_beginning = update_options.is_sync
        update_result = await _create_epub_for_new_parts(
            session,
            series_details,
            series,
            epub_generation_options,
            update_options,
            is_force_from_beginning,
        )

    if update_result.is_updated:
        emoji = ""
        if console.is_advanced():
            emoji = "\u2714 "
        console.info(
            f"{emoji}The series '[highlight]{series.raw_data.title}[/]' has "
            "been updated!",
            style="success",
        )
    else:
        console.info(
            f"The series '[highlight]{series.raw_data.title}[/]' is already up "
            "to date!",
            style="success",
        )
        if is_check_events and is_need_check:
            # events feed said the series was updated but checking the series says
            # there was no update => incoherent : for now, do not update the checl
            # date
            # possible also if tracked.json updated manually : last_checked_date is
            # before the date of the last downloaded part in the file
            update_result.is_update_last_checked = False

    _update_tracking_data(series_details, series, update_result, session.now)


async def update_all_series(
    session,
    epub_generation_options,
    tracked_series,
    new_synced,
    update_options,
):
    # is_sync: all parts from beginning so no need for the events
    if (
        not update_options.is_sync
        and update_options.is_use_events
        and _can_any_use_events_feed(tracked_series)
    ):
        console.status("Checking J-Novel Club events feed...", clear=False)
        start_date = _min_last_check_date(tracked_series)
        events = await core.fetch_events(session, start_date)
        console.pop_status()
    else:
        events = None

    series_details_a = []
    tasks = []
    for series_url, series_details in tracked_series.items():
        tasks.append(
            partial(
                _handle_series,
                session,
                series_url,
                series_details,
                epub_generation_options,
                update_options.is_sync,
                new_synced,
                update_options,
                events,
            )
        )
        series_details_a.append(series_details)

    results = await bag(tasks)

    num_updated = 0
    num_errors = 0
    update_result: UpdateResult
    for i, update_result in enumerate(results):
        series_details = series_details_a[i]

        # --sync has bee used and series is not part of the synced series so
        # has not been checked
        if not update_result.is_considered:
            continue

        if update_result.is_updated:
            num_updated += 1

        if update_result.is_error:
            num_errors += 1
        else:
            # the update of tracking has some conditions besides
            # just the series updated
            _update_tracking_data(
                series_details, update_result.series, update_result, session.now
            )

    if num_errors > 0:
        console.error("Some series could not be updated!")

    emoji = ""
    if console.is_advanced():
        emoji = "\u2728 "

    if num_updated == 0 and num_errors == 0:
        # second clause => all in error
        console.info(
            f"{emoji}All series are already up to date!",
            style="success",
        )

    if num_updated > 0:
        console.info(
            f"{emoji}{num_updated} series sucessfully updated!",
            style="success",
        )


def _update_tracking_data(series_details, series_meta, update_result, check_date):
    # alway update this : in case --use-events is used
    if update_result.is_update_last_checked:
        series_details.last_check_date = utils.isoformat_with_z(check_date)

    # not always available (if series not checked for example)
    if series_meta:
        # should stay always the same
        series_details.series_id = series_meta.series_id

    if not (update_result.is_updated or update_result.is_force_set_updated):
        return

    parts = core.all_parts_meta(series_meta)
    assert bool(parts)

    # this is only used for display to the user in track list
    last_part_number = parts[-1]
    pn = spec.to_relative_spec_from_part(last_part_number)
    series_details.part = pn

    # if series has more than one volume in parallel, it can happen that the last
    # part (in number) is released before (in date) a part that comes before (in number)
    # we use the part_date for the update process => last part (in date) for this
    # instead of using the date of the last part (in number)
    last_part_date = max(parts, key=lambda x: x.raw_data.launch)
    pdate = last_part_date.raw_data.launch

    series_details.part_date = pdate


async def _handle_series(
    session,
    series_url,
    series_details,
    epub_generation_options,
    is_sync,
    new_synced,
    update_options,
    events,
):
    series = None
    try:
        if is_sync and series_url not in new_synced:
            return UpdateResult(is_considered=False)

        is_need_check = False
        is_check_events = events and _can_use_events_feed(series_details)
        if is_check_events:
            is_need_check = _verify_series_needs_update_check(events, series_details)
            if not is_need_check:
                return UpdateResult(is_updated=False)
            # else the standard check continues

        jnc_resource = jncweb.resource_from_url(series_url)
        series_id = await core.resolve_series(session, jnc_resource)
        series = await core.fetch_meta(session, series_id)

        # generate from the start if the series is newly sync
        is_force_from_beginning = is_sync
        update_result = await _create_epub_for_new_parts(
            session,
            series_details,
            series,
            epub_generation_options,
            update_options,
            is_force_from_beginning,
        )

        if update_result.is_updated:
            emoji = ""
            if console.is_advanced():
                emoji = "\u2714 "
            console.info(
                f"{emoji}The series '[highlight]{series.raw_data.title}[/]' has "
                "been updated!",
                style="success",
            )
        else:
            if is_check_events and is_need_check:
                # incoherence between feed and series data
                # assumes maybe advertised part has not been released yet (but will be)
                # so do not advance check_date (so next check, if the part is released
                # it will be picked up)
                update_result.is_update_last_checked = False

        return update_result

    except (trio.MultiError, Exception) as ex:
        if series and series.raw_data:
            title = series.raw_data.title
        else:
            title = series_url

        emoji = ""
        if console.is_advanced():
            emoji = "\u274C "
        # FIXME show the user some feedback as to the nature of the error
        console.error(
            f"{emoji}Error updating '{title}'! "
            "(run 'jncep -d update' for more details)",
        )
        logger.debug(f"Error _handle_series: {ex}", exc_info=sys.exc_info())
        # series_meta may be None if error during retrieval
        return UpdateResult(is_error=True)


def _verify_series_needs_update_check(event_feed, series_details):
    last_check_date = dateutil.parser.parse(series_details.last_check_date)

    events, has_reached_limit, first_event_date = event_feed

    # shortcuts for some special cases

    if len(events) == 0:
        # events only contain the necessary events for dates between last_check and now:
        # no events => no update
        return False

    # last_check_date is specific to the series; but event feed is checked taking into
    # account all series so event if has_reached_limit is True, series may not need to
    # be checked
    if has_reached_limit and last_check_date <= first_event_date:
        # events doesn't go far enough in the past: Not possible to know for sure
        # if there are no updates
        # assumes need check
        return True

    series_id = series_details.series_id

    for event in events:
        if "details" in event and event.details.startswith("Release of Part"):
            # no s in JNC attr
            series = event.serie
            if series.id != series_id:
                continue

            launch_date = dateutil.parser.parse(event.launch)
            # <= : last_check_date is the session.now of the previous check so if
            # equal to last_check_date, already included in previous check
            # see core.fetch_events request parameters
            if launch_date <= last_check_date:
                # the events are ordered by launch desc so can never be false after
                break

            # return only that there has been updates
            # the standard check for the series will be done after
            # TODO return specific parts ?
            return True

    return False


def _can_any_use_events_feed(tracking_data):
    return any(
        (
            _can_use_events_feed(series_details)
            for series_details in tracking_data.values()
        )
    )


def _min_last_check_date(tracking_data):
    # all dates are encoded in the same ISO format
    check_dates = (
        d.last_check_date for d in tracking_data.values() if _can_use_events_feed(d)
    )
    return min(check_dates)


def _can_use_events_feed(series_details):
    # the 2 attributes have been added later so may not always be there
    return "series_id" in series_details and "last_check_date" in series_details


async def _create_epub_for_new_parts(
    session,
    series_details,
    series,
    epub_generation_options,
    update_options,
    is_force_from_beginning=False,
):
    parts = core.all_parts_meta(series)

    if series_details.part == 0 or is_force_from_beginning:
        # Firt clause: special processing : means there was no part available when the
        # series was started tracking

        update_result = await _update_from_beginning(
            session, series, parts, epub_generation_options
        )
        # no need for _generate_whole_volume_on_final_part: if from the beginning +
        # final included => the whole volume is already generated
        return update_result
    else:
        update_result = await _update_new_parts(
            session,
            series_details,
            series,
            parts,
            epub_generation_options,
            update_options,
        )

        if (
            update_result.is_updated
            and update_options.is_whole_volume_on_final_part
            and not update_options.is_whole_volume
        ):
            # TODO do that as soon as we know which parts to download before
            # fill_covers_and_content
            parts_downloaded = update_result.parts_downloaded
            await _generate_whole_volume_on_final_part(
                session, series, parts_downloaded, epub_generation_options
            )

        return update_result


async def _update_from_beginning(session, series, parts, epub_generation_options):
    # still no part ?
    if not parts:
        return UpdateResult(is_updated=False)
    else:
        console.info(
            f"The series '[highlight]{series.raw_data.title}[/]' " "will be updated..."
        )

        part_filter = partial(core.is_part_available, session.now)

        (
            volumes_to_download,
            parts_to_download,
        ) = core.relevant_volumes_and_parts_for_content(series, part_filter)
        volumes_for_cover = core.relevant_volumes_for_cover(
            volumes_to_download, epub_generation_options.is_by_volume
        )

        await core.fill_covers_and_content(
            session, volumes_for_cover, parts_to_download
        )
        await core.create_epub(
            series,
            volumes_to_download,
            parts_to_download,
            epub_generation_options,
        )

        return UpdateResult(series, is_updated=True, parts_downloaded=parts_to_download)


async def _update_new_parts(
    session,
    series_details,
    series,
    parts,
    epub_generation_options,
    update_options,
):
    if not series_details.part_date:
        # if here => old format, first lookup date of last part and use that
        # still useful for stalled series so keep it
        part_spec = spec.analyze_part_specs(series_details.part)
        for part in parts:
            if part_spec.has_part(part):
                # will be filled if the part still exists (it should)
                # TODO case it doesn't ? eg tracked.json filled by hand
                last_update_part = part
                break
        # in UTC
        last_update_date = last_update_part.raw_data.launch
    else:
        # new format : date is recorded
        last_update_date = series_details.part_date

    last_update_date = dateutil.parser.parse(last_update_date)

    parts_release_after_date = _filter_parts_released_after_date(
        last_update_date, parts
    )

    if not parts_release_after_date:
        # not updated
        return UpdateResult(series, is_updated=False)

    available_parts_to_download = [
        part
        for part in parts_release_after_date
        if core.is_part_available(session.now, part)
    ]

    if not available_parts_to_download:
        console.warning(
            f"All updated parts for '[highlight]{series.raw_data.title}[/]' "
            "have expired!"
        )
        # not updated but the series will still have its tracking data changed
        # in tracking config ; if not, the message above will always be displayed
        # should be rare (if updating often) ; also first part is preview
        # so even rarer
        return UpdateResult(series=series, is_updated=False, is_force_set_updated=True)

    console.info(
        f"The series '[highlight]{series.raw_data.title}[/]' will be updated..."
    )

    # after the to update notification
    if len(available_parts_to_download) != len(parts_release_after_date):
        console.warning(
            f"Some parts for '[highlight]{series.raw_data.title}[/]' have " "expired!"
        )

    parts_id_to_download = set((part.part_id for part in available_parts_to_download))

    # availability alread tested
    def simple_part_filter(part):
        return part.part_id in parts_id_to_download

    (
        volumes_to_download,
        parts_to_download,
    ) = core.relevant_volumes_and_parts_for_content(series, simple_part_filter)

    if update_options.is_whole_volume:
        # second pass : filter on the volumes_to_download
        # all the parts of those volumes must be downloaded
        volumes_id_to_download = set((v.volume_id for v in volumes_to_download))

        def whole_volume_part_filter(part):
            return (
                part.volume.volume_id in volumes_id_to_download
                and core.is_part_available(session.now, part)
            )

        (
            volumes_to_download,
            parts_to_download,
        ) = core.relevant_volumes_and_parts_for_content(
            series, whole_volume_part_filter
        )

    volumes_for_cover = core.relevant_volumes_for_cover(
        volumes_to_download, epub_generation_options.is_by_volume
    )

    await core.fill_covers_and_content(session, volumes_for_cover, parts_to_download)

    await core.create_epub(
        series,
        volumes_to_download,
        parts_to_download,
        epub_generation_options,
    )

    return UpdateResult(series, is_updated=True, parts_downloaded=parts_to_download)


def _is_released_after_date(date, part_date_s):
    # all date strings are in ISO format
    # so no need to parse really
    # parsing just to be safe
    # in case different shape like ms part or not (which throws str comp off)
    launch_date = dateutil.parser.parse(part_date_s)
    return launch_date > date


def _filter_parts_released_after_date(date, parts):
    parts_to_download = []
    for part in parts:
        if _is_released_after_date(date, part.raw_data.launch):
            parts_to_download.append(part)

    return parts_to_download


async def _generate_whole_volume_on_final_part(
    session, series, parts_downloaded, epub_generation_options
):
    # check if any part included in the update is the final part of its volume
    for part in parts_downloaded:
        # only max one part can be final in a volume
        if not core._is_part_final(part):
            continue

        # check if possibly all parts have already been downloaded as part of the
        # update
        for volpart in part.volume.parts:
            if volpart not in parts_downloaded:
                break
        else:
            # all the parts have been downloaded in the normal course
            # of things, so we skip regenerating the whole volume
            continue

        console.info(
            "The complete volume "
            f"'[highlight]{part.volume.raw_data.title}[/]' will be "
            "downloaded..."
        )

        # With JNC if the final part can be downloaded, the rest of the
        # volume is also available for download so no need to check

        await core.fill_covers_and_content(session, [part.volume], part.volume.parts)
        await core.create_epub(
            series,
            [part.volume],
            part.volume.parts,
            epub_generation_options,
        )
