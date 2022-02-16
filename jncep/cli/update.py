import logging

from addict import Dict as Addict
import click

from . import options
from .. import core, jncweb, spec, track, update, utils
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
    is_sync,
    is_whole_volume,
):
    epub_generation_options = core.EpubGenerationOptions(
        output_dirpath,
        is_by_volume,
        is_extract_images,
        is_extract_content,
        is_not_replace_chars,
    )

    # TODO move most of this to update
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

            updated_series, series_meta = await update.update_url_series(
                session,
                jnc_url,
                epub_generation_options,
                tracked_series,
                is_sync,
                new_synced,
                is_whole_volume,
            )

            if len(updated_series) == 0:
                console.info(
                    f"The series '{series_meta.raw_data.title}' is already up to date!",
                    style="success",
                )
                return

        else:
            console.status("Update all series...")

            updated_series, error_series = await update.update_all_series(
                session,
                epub_generation_options,
                tracked_series,
                is_sync,
                new_synced,
                is_whole_volume,
            )

            if error_series:
                console.error("Some series could not be updated!")

        if len(updated_series) == 0:
            # FIXME case all in error ? handle
            console.info(
                "All series are already up to date!",
                style="success",
            )
            return

        if len(updated_series) > 0:
            # update tracking config JSON
            for _, series in updated_series.items():
                parts = core.all_parts_meta(series)
                # if here should exist
                last_part = parts[-1]
                pn = spec.to_relative_spec_from_part(last_part)
                pdate = last_part.raw_data.launch
                series = last_part.volume.series
                tracked_series[
                    jncweb.url_from_series_slug(series.raw_data.slug)
                ] = Addict(
                    {
                        "part_date": pdate,
                        "part": pn,
                        "name": series.raw_data.title,
                    }
                )
            track_manager.write_tracked_series(tracked_series)

            console.info(
                f"{len(updated_series)} series sucessfully updated!",
                style="success",
            )
