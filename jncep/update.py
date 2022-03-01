from functools import partial
import logging
import sys

import attr
import dateutil
import trio

from . import core, jncweb, model, spec, track, utils
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


async def update_url_series(
    session,
    jnc_url,
    epub_generation_options,
    tracked_series,
    is_sync,
    new_synced,
    is_whole_volume,
):
    # for single url => if error no catch : let it crash and report to the user
    jnc_resource = jncweb.resource_from_url(jnc_url)
    series_meta = await core.resolve_series(session, jnc_resource)

    series_url = jncweb.url_from_series_slug(series_meta.raw_data.slug)

    if series_url not in tracked_series:
        console.warning(
            f"The series '[highlight]{series_meta.raw_data.title}[/]' is not tracked! "
            f"Use the 'jncep track add' command first."
        )
        return

    if is_sync:
        # not very useful but make it possible
        # only consider newly synced series if --sync used
        # to mirror case with no URL argument
        if series_url not in new_synced:
            console.warning(
                f"The series '[highlight]{series_meta.raw_data.title}[/]' is not "
                "among the tracked series added from syncing. Use 'jncep update' "
                "without --sync."
            )
            return

    series_details = tracked_series[series_url]

    # the series has just been synced so force EPUB gen from start
    is_force_from_beginning = is_sync
    update_result = await _create_epub_for_new_parts(
        session,
        series_details,
        series_meta,
        epub_generation_options,
        is_whole_volume,
        is_force_from_beginning,
    )

    if update_result.is_updated:
        emoji = ""
        if console.is_advanced():
            emoji = "\u2714 "
        console.info(
            f"{emoji}The series '[highlight]{series_meta.raw_data.title}[/]' has "
            "been updated!",
            style="success",
        )
    else:
        console.info(
            f"The series '[highlight]{series_meta.raw_data.title}[/]' is already up "
            "to date!",
            style="success",
        )

    is_tracking_updated = _update_tracking_data(
        series_details, series_meta, update_result
    )

    return is_tracking_updated


async def update_all_series(
    session,
    epub_generation_options,
    tracked_series,
    is_sync,
    new_synced,
    is_whole_volume,
):
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
                is_sync,
                new_synced,
                is_whole_volume,
            )
        )
        series_details_a.append(series_details)

    results = await bag(tasks)

    num_updated = 0
    num_errors = 0
    is_tracking_updated = False
    update_result: UpdateResult
    for i, update_result in enumerate(results):
        if not update_result.is_considered:
            continue

        series_details = series_details_a[i]

        if update_result.is_updated:
            num_updated += 1

        if update_result.is_error:
            num_errors += 1
        else:
            # the update of tracking has some conditions besides
            # just the series udpated
            is_tracking_updated_for_series = _update_tracking_data(
                series_details, update_result.series, update_result
            )
            if is_tracking_updated_for_series:
                is_tracking_updated = True

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

    return is_tracking_updated


def _update_tracking_data(series_details, series_meta, update_result):
    if not (update_result.is_updated or update_result.is_force_set_updated):
        return False

    parts = core.all_parts_meta(series_meta)
    assert bool(parts)

    last_part = parts[-1]
    pn = spec.to_relative_spec_from_part(last_part)
    pdate = last_part.raw_data.launch

    series_details.part_date = pdate
    series_details.part = pn

    return True


async def _handle_series(
    session,
    series_url,
    series_details,
    epub_generation_options,
    is_sync,
    new_synced,
    is_whole_volume,
):
    series_meta = None
    try:
        if is_sync and series_url not in new_synced:
            return UpdateResult(is_considered=False)

        jnc_resource = jncweb.resource_from_url(series_url)
        series_meta = await core.resolve_series(session, jnc_resource)

        # generate from the start if the series is newly sync
        is_force_from_beginning = is_sync
        update_result = await _create_epub_for_new_parts(
            session,
            series_details,
            series_meta,
            epub_generation_options,
            is_whole_volume,
            is_force_from_beginning,
        )

        if update_result.is_updated:
            emoji = ""
            if console.is_advanced():
                emoji = "\u2714 "
            console.info(
                f"{emoji}The series '[highlight]{series_meta.raw_data.title}[/]' has "
                "been updated!",
                style="success",
            )

        return update_result

    except (trio.MultiError, Exception) as ex:
        if series_meta and series_meta.raw_data:
            title = series_meta.raw_data.title
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


# TODO too complex ; refactor
async def _create_epub_for_new_parts(
    session,
    series_details,
    series_meta,
    epub_generation_options,
    is_whole_volume=False,
    is_force_from_beginning=False,
):
    # sufficient for here
    # quick to check
    await track.fill_meta_last_part(session, series_meta)
    parts = core.all_parts_meta(series_meta)

    if series_details.part == 0 or is_force_from_beginning:
        # Firt clause: special processing : means there was no part available when the
        # series was started tracking

        # still no part ?
        if not parts:
            return UpdateResult(is_updated=False)
        else:
            console.info(
                f"The series '[highlight]{series_meta.raw_data.title}[/]' "
                "will be updated..."
            )

            # complete series from beginning
            await core.fill_meta(session, series_meta)

            part_filter = partial(core.is_part_available, session.now)

            (
                volumes_to_download,
                parts_to_download,
            ) = core.relevant_volumes_and_parts_for_content(series_meta, part_filter)
            volumes_for_cover = core.relevant_volumes_for_cover(
                volumes_to_download, epub_generation_options.is_by_volume
            )

            await core.fill_covers_and_content(
                session, volumes_for_cover, parts_to_download
            )
            await core.create_epub(
                series_meta,
                volumes_to_download,
                parts_to_download,
                epub_generation_options,
            )

            return UpdateResult(series_meta, is_updated=True)
    else:

        if not series_details.part_date:
            # if here => old format, first lookup date of last part and use that
            # still useful for stalled series so keep it
            part_spec = spec.analyze_part_specs(series_details.part)
            await core.fill_meta(session, series_meta, part_spec.has_volume)
            parts = core.all_parts_meta(series_meta)
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

        # TOC is below a part in the Labs API
        last_part = parts[-1]
        toc = await session.api.fetch_data("parts", last_part.part_id, "toc")
        # weird struct for the response : toc.parts has pagination struct (but all
        # parts seem to be there anyway) and parts property in turn
        # parts_release_after_date is a list of Parts but has reduced data (no num,
        # no series, no volume)
        parts_release_after_date = _filter_parts_released_after_date(
            last_update_date, toc.parts.parts
        )

        if not parts_release_after_date:
            # not updated
            return UpdateResult(series_meta, is_updated=False)

        # filling in the series ; necessary to check availability
        for part in parts_release_after_date:
            part.series = series_meta

        available_parts_to_download = [
            part
            for part in parts_release_after_date
            if core.is_part_available(session.now, part)
        ]

        if not available_parts_to_download:
            console.warning(
                f"All updated parts for '[highlight]{series_meta.raw_data.title}[/]' "
                "have expired!"
            )
            # not updated but the series will still have its tracking data changed
            # in tracking config ; if not, the message above will always be displayed
            # should be rare (if updating often) ; also first part is preview
            # so even rarer
            return UpdateResult(
                series=series_meta, is_updated=False, is_force_set_updated=True
            )

        console.info(
            f"The series '[highlight]{series_meta.raw_data.title}[/]' will "
            "be updated..."
        )

        # after the to update notification
        if len(available_parts_to_download) != len(parts_release_after_date):
            console.warning(
                f"Some parts for '[highlight]{series_meta.raw_data.title}[/]' have "
                "expired!"
            )

        # we need the volumes for titles and covers
        # so fetch the meta to prepare
        await fill_meta_for_update(session, series_meta, available_parts_to_download)
        # normally if in this branch parts should not be empty
        parts = core.all_parts_meta(series_meta)

        parts_id_to_download = set(
            (part.part_id for part in available_parts_to_download)
        )

        # availability alread tested
        def simple_part_filter(part):
            return part.part_id in parts_id_to_download

        (
            volumes_to_download,
            parts_to_download,
        ) = core.relevant_volumes_and_parts_for_content(series_meta, simple_part_filter)

        if is_whole_volume:
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
                series_meta, whole_volume_part_filter
            )

        volumes_for_cover = core.relevant_volumes_for_cover(
            volumes_to_download, epub_generation_options.is_by_volume
        )

        tasks = [
            partial(
                core.fill_covers_and_content,
                session,
                volumes_for_cover,
                parts_to_download,
            ),
            partial(
                core.fill_num_parts_for_volumes,
                session,
                series_meta,
                volumes_to_download,
            ),
        ]
        await bag(tasks)

        await core.create_epub(
            series_meta,
            volumes_to_download,
            parts_to_download,
            epub_generation_options,
        )

        return UpdateResult(series_meta, is_updated=True)


async def fill_meta_for_update(session, series, parts_to_download):
    await core.fill_volumes_meta(session, series)
    volumes = series.volumes

    parts_id_to_download = set((part.part_id for part in parts_to_download))

    # in order not to do too many requests:
    # first try last 2 volumes => in most update scenarios (if updated frequently),
    # this should be enough
    # then do the rest if not sufficient
    last_2_volumes = volumes[-2:]
    rest_volumes = volumes[:-2]
    await core.fill_parts_meta_for_volumes(session, last_2_volumes)
    for volume in last_2_volumes:
        for part in volume.parts:
            # check if has part before the reference date
            # => means the parts relased after are all there
            # (except possibly when multiple volumes > 2 published at the same time)
            if part.part_id in parts_id_to_download:
                parts_id_to_download.remove(part.part_id)
        if len(parts_id_to_download) == 0:
            # found them all
            break
    else:
        # some parts to download have not been found in the last 2 volumes
        # just give up and request everything
        await core.fill_parts_meta_for_volumes(session, rest_volumes)


def _is_released_after_date(date, part_date_s):
    launch_date = dateutil.parser.parse(part_date_s)
    return launch_date > date


def _filter_parts_released_after_date(date, parts_raw):
    # parts is the raw Part struct from JNC Labs API
    parts_to_download = []
    for part_raw in parts_raw:
        # all date strings are in ISO format
        # so no need to parse really
        # parsing just to be safe
        # in case different shape like ms part or not (which throws str comp off)
        if _is_released_after_date(date, part_raw.launch):
            # num in volume is unknown at this point
            parts_to_download.append(model.Part(part_raw, part_raw.legacyId, -1))

    return parts_to_download
