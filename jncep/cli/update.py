import logging

import click

from . import options
from .. import core, track, update, utils
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
    envvar="JNCEP_WHOLE",
    help=(
        "Flag to indicate whether the whole volume should be regenerated when a "
        "new part is detected during the update"
    ),
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
        if len(tracked_series) == 0:
            console.warning(
                "There are no tracked series! Use the 'jncep track add' command "
                "first."
            )
            return

        new_synced = None
        if is_sync:
            console.status("Fetch followed series from J-Novel Club...")
            follows = await session.api.fetch_follows()
            new_synced, _ = await track.sync_series_forward(
                session, follows, tracked_series, False
            )

        if jnc_url:
            console.status(f"Update '{jnc_url}'...")

            is_tracking_updated = await update.update_url_series(
                session,
                jnc_url,
                epub_generation_options,
                tracked_series,
                is_sync,
                new_synced,
                is_whole_volume,
            )

        else:
            console.status("Update all series...")

            is_tracking_updated = await update.update_all_series(
                session,
                epub_generation_options,
                tracked_series,
                is_sync,
                new_synced,
                is_whole_volume,
            )

        if is_tracking_updated:
            track_manager.write_tracked_series(tracked_series)
            logger.debug("Data for tracked series sucessfully updated!")
