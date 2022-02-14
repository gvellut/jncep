import logging

import click

from . import options
from .. import core, epub, jncweb, spec, track, update
from ..utils import coro, green
from .base import CatchAllExceptionsCommand

# TODO replace
logger = logging.getLogger(__name__)


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
        tracked_series = track.read_tracked_series()
        if len(tracked_series) == 0:
            logger.warning(
                "There are no tracked series! Use the 'jncep track add' command "
                "first."
            )
            return

        new_synced = None
        if is_sync:
            # logger.info("Fetch followed series from J-Novel Club...")
            # follows = await session.api.fetch_follows()
            # new_synced, _ = core.sync_series_forward(
            #     token, follows, tracked_series, False
            # )
            raise NotImplementedError("is_sync LABS")

        if jnc_url:
            updated_series = await update.update_url_series(
                session,
                jnc_url,
                epub_generation_options,
                tracked_series,
                is_sync,
                new_synced,
                is_whole_volume,
            )

            if len(updated_series) == 0:
                return

        else:
            updated_series, error_series = await update.update_all_series(
                session,
                epub_generation_options,
                tracked_series,
                is_sync,
                new_synced,
                is_whole_volume,
            )

            if error_series:
                logger.error("Some series could not be updated!")

            if len(updated_series) == 0:
                # FIXME case all in error ? handle
                logger.info(green("All series are already up to date!"))
                return

        if len(updated_series) > 0:
            # update tracking config JSON
            for _, last_part in updated_series.items():
                pn = spec.to_relative_spec_from_part(last_part)
                pdate = last_part.raw_data.launch
                series = last_part.volume.series
                tracked_series[jncweb.url_from_series_slug(series.raw_data.slug)] = {
                    "part_date": pdate,
                    "part": pn,
                    "name": series.raw_data.title,
                }
            track.write_tracked_series(tracked_series)

            logger.info(green(f"{len(updated_series)} series sucessfully updated!"))
