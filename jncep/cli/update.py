import logging

import click

from . import options
from .. import core, track, update, utils
from ..config import ENVVAR_PREFIX
from ..trio_utils import coro
from .base import CatchAllExceptionsCommand

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
    "-e",
    "--use-events",
    "is_use_events",
    is_flag=True,
    default=False,
    envvar=f"{ENVVAR_PREFIX}USE_EVENTS",
    help="Flag to use the events feed to check for updates",
)
@coro
async def update_tracked(
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
    is_use_events,
):
    epub_generation_options = core.EpubGenerationOptions(
        output_dirpath,
        is_by_volume,
        is_extract_images,
        is_extract_content,
        is_not_replace_chars,
        style_css_path,
    )

    async with core.JNCEPSession(email, password) as session:
        track_manager = track.TrackConfigManager()
        tracked_series = track_manager.read_tracked_series()

        # process sync first => possibly will add new series to track
        new_synced = None
        if is_sync:
            console.status("Fetch followed series from J-Novel Club...")
            follows = await session.api.fetch_follows()
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
                is_sync,
                new_synced,
                is_whole_volume,
                is_use_events,
            )

        else:
            console.status("Update all series...")

            await update.update_all_series(
                session,
                epub_generation_options,
                tracked_series,
                is_sync,
                new_synced,
                is_whole_volume,
                is_use_events,
            )

        # always update and do not notifiy user
        track_manager.write_tracked_series(tracked_series)
