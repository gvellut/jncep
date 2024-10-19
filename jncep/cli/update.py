from functools import partial
import logging

import click
import trio

from . import options
from .. import core, jncalts, track, update, jncweb, utils
from ..config import ENVVAR_PREFIX
from ..trio_utils import coro
from .base import CatchAllExceptionsCommand
from .track import sync_series

logger = logging.getLogger(__name__)
console = utils.getConsole()


@click.command(
    name="update",
    help="Generate EPUB files for new parts of all tracked series (or specific "
    "series if a URL argument is passed)",
    cls=CatchAllExceptionsCommand,
)
@click.argument("jnc_url", metavar="(JNOVEL_CLUB_URL?)", required=False)
@options.credentials_options
# TODO group the EPUB gen options like the credentials
@options.output_option
@options.byvolume_option
@options.subfolder_option
@options.images_option
@options.raw_content_option
@options.no_replace_chars_option
@options.css_option
@options.namegen_option
# TODO group the update options
@click.option(
    "-s",
    "--sync",
    "is_sync",
    is_flag=True,
    help=(
        "Flag to sync tracked series based on series followed on J-Novel Club and "
        "update the new ones from the beginning of the series"
    ),
)
@click.option(
    "-j",
    "--jnc-managed",
    "is_jnc_managed",
    is_flag=True,
    envvar=f"{ENVVAR_PREFIX}JNC_MANAGED",
    help=(
        "Flag to indicate whether to use the series followed on the J-Novel Club "
        "website as the tracking reference for updating (equivalent to "
        "running 'track sync --delete --beginning' followed by 'update')"
    ),
)
@click.option(
    "-w",
    "--whole",
    "is_whole_volume",
    is_flag=True,
    envvar=f"{ENVVAR_PREFIX}WHOLE",
    help=(
        "Flag to indicate whether the whole volume should be regenerated when a "
        "new part is detected during the update"
    ),
)
@click.option(
    "-f",
    "--whole-final",
    "is_whole_volume_on_final_part",
    is_flag=True,
    default=False,
    envvar=f"{ENVVAR_PREFIX}WHOLE_FINAL",
    help=(
        "Flag to indicate whether an EPUB with a complete volume should also be "
        "generated when the final part of the volume is included in the update"
    ),
)
@click.option(
    "-g",
    "--whole-only",
    "is_whole_volume_only",
    is_flag=True,
    default=False,
    envvar=f"{ENVVAR_PREFIX}WHOLE_ONLY",
    help=(
        "Flag to indicate whether an EPUB should be generated ONLY when the final "
        "part of the volume is included in the update. This EPUB will contain the "
        "whole volume."
    ),
)
@click.option(
    "-e",
    "--use-events",
    "is_use_events",
    is_flag=True,
    default=False,
    envvar=f"{ENVVAR_PREFIX}USE_EVENTS",
    help="Flag to use the events feed to check for updates",
)
@click.pass_context
@coro
async def update_tracked(
    ctx,
    jnc_url,
    credentials,
    output_dirpath,
    is_by_volume,
    is_subfolder,
    is_extract_images,
    is_extract_content,
    is_not_replace_chars,
    style_css_path,
    namegen_rules,
    is_sync,
    is_whole_volume,
    is_whole_volume_on_final_part,
    is_whole_volume_only,
    is_use_events,
    is_jnc_managed,
):
    track_manager = track.TrackConfigManager()
    tracked_series = track_manager.read_tracked_series()

    async def update_tracked_for_origin(config, tracked_series_origin):
        # TODO catch exc for an origin ; or error in one => global error
        async with core.JNCEPSession(config, credentials) as session:
            ids_updated = False
            # Check if series_id is legacyId, update if so
            for series_url, value in tracked_series.items():
                if (len(value.series_id) == 24 and
                    all(c in "abcdef1234567890" for c in value.series_id)):
                    # LegacyId needs update to new id
                    console.info(f"Updating legacy id for {series_url}!")
                    jnc_resource = jncweb.resource_from_url(series_url)
                    series_id = await core.resolve_series(session, jnc_resource)
                    series = await core.fetch_meta(session, series_id)
                    value['series_id'] = series.series_id
                    tracked_series[series_url] = value
                    ids_updated = True

            if ids_updated:
                track_manager.write_tracked_series(tracked_series)

            if is_jnc_managed:
                # run the equivalent of:
                # track sync --delete --beginning
                # update

                # do the sync_series inside an existing origin session so only one login
                # for the origin
                origin_credentials = credentials.extract_for_origin(config.ORIGIN)

                # prune series that are not followed anymore + track from beginning
                console.info("[important]track sync --delete --beginning[/]")

                # TODO instead of passing through click use internal function
                # no need for the rereading of the tracked series

                # run_sync because we are already in a trio context so we wouldn't be
                # able to nest another trio.run (inside the click command) othwerwise
                # TODO check if newer Trio versions have lifted that limitation?
                await trio.to_thread.run_sync(
                    partial(
                        ctx.invoke,
                        sync_series,
                        credentials=origin_credentials,
                        is_delete=True,
                        is_beginning=True,
                    )
                )

                # need to reread since the tracked_series_origin is not updated by
                # the invocation above: updates the file itself
                tracked_series_updated = track_manager.read_tracked_series()
                tracked_series_origin_updated = jncalts.split_by_origin(
                    tracked_series_updated
                )[config.ORIGIN]
                # keep the reference to the tracked_series_origin but replace content
                # with the newly synced tracking content
                # the reference needs to be kept since used for the merge in
                # call_for_each_origin
                tracked_series_origin.clear()
                tracked_series_origin.update(tracked_series_origin_updated)

                # after that, let update run normally
                console.info("[important]update[/]")
                # set sync to False because doesn't make sense to sync again
                # TODO log to the user ?
                nonlocal is_sync
                is_sync = False

            epub_generation_options = core.EpubGenerationOptions(
                output_dirpath,
                is_subfolder,
                is_by_volume,
                is_extract_images,
                is_extract_content,
                is_not_replace_chars,
                style_css_path,
                namegen_rules,
            )

            update_options = update.UpdateOptions(
                is_sync,
                is_whole_volume,
                is_whole_volume_on_final_part,
                is_whole_volume_only,
                is_use_events,
            )

            # process sync first => possibly will add new series to track
            new_synced = None
            if is_sync:
                console.status("Fetch followed series from J-Novel Club...")
                follows = await core.fetch_follows(session)
                # new series will also be added to tracked_series
                new_synced, _ = await track.sync_series_forward(
                    session, follows, tracked_series_origin, False
                )

                if len(new_synced) == 0:
                    console.warning(
                        "There are no new series to sync. Use the [highlight]Follow[/] "
                        "button on a series page on the J-Novel Club website."
                    )
                    return

            if len(tracked_series_origin) == 0:
                console.warning(
                    "There are no tracked series! Use the 'jncep track add' command "
                    "first."
                )
                return

            if jnc_url:
                console.status(f"Update '{jnc_url}'...")

                await update.update_url_series(
                    session,
                    jnc_url,
                    epub_generation_options,
                    tracked_series_origin,
                    new_synced,
                    update_options,
                )

            else:
                console.status("Update all series...")

                await update.update_all_series(
                    session,
                    epub_generation_options,
                    tracked_series_origin,
                    new_synced,
                    update_options,
                )

    if jnc_url:
        origin = jncalts.find_origin(jnc_url)
        config = jncalts.get_alt_config_for_origin(origin)

        await update_tracked_for_origin(config, tracked_series)
    else:
        _, tracked_series = await jncalts.call_for_each_origin(
            credentials, update_tracked_for_origin, tracked_series
        )

    # always update and do not notifiy user
    track_manager.write_tracked_series(tracked_series)
