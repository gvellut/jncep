import logging

import click

from . import options
from .. import core, epub, jncapi, jncweb, spec
from ..utils import green
from .common import CatchAllExceptionsCommand

logger = logging.getLogger(__package__)


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
def update_tracked(
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
    epub_generation_options = epub.EpubGenerationOptions(
        output_dirpath,
        is_by_volume,
        is_extract_images,
        is_extract_content,
        is_not_replace_chars,
    )

    token = None
    updated_series = []
    try:
        tracked_series = core.read_tracked_series()
        if len(tracked_series) == 0:
            logger.warning(
                "There are no tracked series! Use the 'jncep track add' command "
                "first."
            )
            return

        logger.info(f"Login with email '{email}'...")
        token = jncapi.login(email, password)

        new_synced = None
        if is_sync:
            logger.info("Fetch followed series from J-Novel Club...")
            follows = jncapi.fetch_follows(token)
            new_synced, _ = core.sync_series_forward(
                token, follows, tracked_series, False
            )

        if jnc_url:
            core.update_url_series(
                token,
                jnc_url,
                epub_generation_options,
                tracked_series,
                updated_series,
                is_sync,
                new_synced,
            )
            if len(updated_series) == 0:
                return
        else:
            has_error = core.update_all_series(
                token,
                epub_generation_options,
                tracked_series,
                updated_series,
                is_sync,
                new_synced,
                is_whole_volume,
            )

            if has_error:
                logger.error("Some series could not be updated!")

            if len(updated_series) == 0:
                # TODO case all in error ?
                logger.info(green("All series are already up to date!"))
                return
    finally:
        if token:
            try:
                logger.info("Logout...")
                jncapi.logout(token)
            except Exception:
                pass

    if len(updated_series) > 0:
        # update tracking config JSON
        for series in updated_series:
            pn = spec.to_relative_spec_from_part(series.parts[-1])
            pdate = series.parts[-1].raw_part.launchDate
            tracked_series[jncweb.url_from_series_slug(series.raw_series.titleslug)] = {
                "part_date": pdate,
                "part": pn,
                "name": series.raw_series.title,
            }
        core.write_tracked_series(tracked_series)

        logger.info(green(f"{len(updated_series)} series sucessfully updated!"))
