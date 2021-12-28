import logging

import click

from . import options
from .. import core, epub as core_epub, jncapi, jncweb, spec
from ..utils import to_yn
from .common import CatchAllExceptionsCommand

logger = logging.getLogger(__package__)


@click.command(
    name="epub",
    help="Generate EPUB files for J-Novel Club pre-pub novels",
    cls=CatchAllExceptionsCommand,
)
@click.argument("jnc_url", metavar="JNOVEL_CLUB_URL", required=True)
@options.login_option
@options.password_option
@options.output_option
@click.option(
    "-s",
    "--parts",
    "part_specs",
    help=(
        "Specification of a range of parts to download in the form of "
        "<vol>[.part]:<vol>[.part] [default: All the content linked by "
        "the JNOVEL_CLUB_URL argument, either a single part, a whole volume "
        "or the whole series]"
    ),
)
@click.option(
    "-a",
    "--absolute",
    "is_absolute",
    is_flag=True,
    help=(
        "Flag to indicate that the --parts option specifies part numbers "
        "globally, instead of relative to a volume i.e. <part>:<part>"
    ),
)
@options.byvolume_option
@options.images_option
@options.raw_content_option
@options.no_replace_chars_option
def generate_epub(
    jnc_url,
    email,
    password,
    part_specs,
    is_absolute,
    output_dirpath,
    is_by_volume,
    is_extract_images,
    is_extract_content,
    is_not_replace_chars,
):
    epub_generation_options = core_epub.EpubGenerationOptions(
        output_dirpath,
        is_by_volume,
        is_extract_images,
        is_extract_content,
        is_not_replace_chars,
    )

    token = None
    try:
        jnc_resource = jncweb.resource_from_url(jnc_url)

        logger.info(f"Login with email '{email}'...")
        token = jncapi.login(email, password)

        logger.info(f"Fetching metadata for '{jnc_resource}'...")
        jncapi.fetch_metadata(token, jnc_resource)

        series = core.analyze_metadata(jnc_resource)

        if part_specs:
            logger.info(
                f"Using part specification '{part_specs}' "
                f"(absolute={to_yn(is_absolute)})..."
            )
            parts_to_download = spec.analyze_part_specs(series, part_specs, is_absolute)
        else:
            parts_to_download = spec.analyze_requested(jnc_resource, series)

        core.create_epub_with_requested_parts(
            token, series, parts_to_download, epub_generation_options
        )
    finally:
        if token:
            try:
                logger.info("Logout...")
                jncapi.logout(token)
            except Exception:
                pass
