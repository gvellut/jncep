from functools import partial
import logging

import click
import trio

from . import options
from .. import core, epub as core_epub, jncapi, jncweb, spec
from ..jnclabs import JNCLabsAPI
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
@options.byvolume_option
@options.images_option
@options.raw_content_option
@options.no_replace_chars_option
def generate_epub(*args, **kwargs):
    trio.run(partial(_main, *args, **kwargs))


async def _main(
    jnc_url,
    email,
    password,
    part_specs,
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

    api = JNCLabsAPI()
    try:
        jnc_resource = jncweb.resource_from_url(jnc_url)

        logger.info(f"Login with email '{email}'...")
        await api.login(email, password)

        if part_specs:
            logger.info(f"Using part specification '{part_specs}' ")
            parts = await fetch_for_specs(api, jnc_resource, part_specs)
        else:
            parts = await fetch_for_resource(api, jnc_resource)

        core.create_epub_with_requested_parts(
            api, parts_to_download, epub_generation_options
        )
    finally:
        if api.is_logged_in:
            try:
                logger.info("Logout...")
                await api.logout()
            except Exception:
                pass


async def fetch_for_specs(api, jnc_resource, part_specs):
    part_spec = spec.analyze_part_specs(part_specs)


async def fetch_for_resource(api, jnc_resource):
    pass
