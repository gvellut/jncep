from functools import partial
import logging

import click
import trio

from . import options
from .. import core, track, update, utils
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
@options.login_option
@options.password_option
@options.output_option
@options.byvolume_option
@options.images_option
@options.raw_content_option
@options.no_replace_chars_option
@options.css_option
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
    email,
    password,
    output_dirpath,
    is_by_volume,
    is_extract_images,
    is_extract_content,
    is_not_replace_chars,
    style_css_path,
    is_sync,
    is_whole_volume,
    is_whole_volume_on_final_part,
    is_use_events,
    is_jnc_managed,
):

    async with core.JNCEPSession(email, password) as session:
        if is_jnc_managed:
            # run the equivalent of:
            # track sync --delete --beginning
            # update

            # prune series that are not followed anymore + track from beginning
            console.info("[important]track sync --delete --beginning[/]")
            # run_sync because we are already in a trio context so we wouldn't be able
            # to nest another trio.run (inside the click command) othwerwise
            await trio.to_thread.run_sync(
                partial(
                    ctx.invoke,
                    sync_series,
                    email=email,
                    password=password,
                    is_delete=True,
                    is_beginning=True,
                )
            )

            # after that, let update run normally
            console.info("[important]update[/]")
            # set sync to False because doesn't make sense to sync again
            # TODO log to the user ?
            is_sync = False

        epub_generation_options = core.EpubGenerationOptions(
            output_dirpath,
            is_by_volume,
            is_extract_images,
            is_extract_content,
            is_not_replace_chars,
            style_css_path,
        )

        update_options = update.UpdateOptions(
            is_sync,
            is_whole_volume,
            is_whole_volume_on_final_part,
            is_use_events,
        )

        track_manager = track.TrackConfigManager()
        tracked_series = track_manager.read_tracked_series()

        # process sync first => possibly will add new series to track
        new_synced = None
        if is_sync:
            console.status("Fetch followed series from J-Novel Club...")
            follows = await core.fetch_follows(session)
            # new series will also be added to tracked_series
            new_synced, _ = await track.sync_series_forward(
                session, follows, tracked_series, False
            )

            if len(new_synced) == 0:
                console.warning(
                    "There are no new series to sync. Use the [highlight]Follow[/] "
                    "button on a series page on the J-Novel Club website."
                )
                return

        if len(tracked_series) == 0:
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
                tracked_series,
                new_synced,
                update_options,
            )

        else:
            console.status("Update all series...")

            await update.update_all_series(
                session,
                epub_generation_options,
                tracked_series,
                new_synced,
                update_options,
            )

        # always update and do not notifiy user
        track_manager.write_tracked_series(tracked_series)
