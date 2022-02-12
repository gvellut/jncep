import logging
import os

import click

from . import options
from .. import core, epub, jncweb, spec
from ..utils import coro, green
from .common import CatchAllExceptionsCommand

logger = logging.getLogger(__name__)


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
    "part_spec",
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
@coro
async def generate_epub(
    jnc_url,
    email,
    password,
    part_spec,
    output_dirpath,
    is_by_volume,
    is_extract_images,
    is_extract_content,
    is_not_replace_chars,
):
    epub_generation_options = epub.EpubGenerationOptions(
        output_dirpath,
        is_by_volume,
        is_extract_images,
        is_extract_content,
        is_not_replace_chars,
    )

    async with core.JNCEPSession(email, password) as session:
        jnc_resource = jncweb.resource_from_url(jnc_url)

        # TODO handle exceptions
        # TODO split by volume

        if part_spec:
            logger.info(f"Using part specification '{part_spec}' ")
            part_spec_analyzed = spec.analyze_part_specs(part_spec)
        else:
            part_spec_analyzed = await session.to_part_spec(jnc_resource)

        fetch_otions = core.FetchOptions(
            is_by_volume=epub_generation_options.is_by_volume, is_download_content=True
        )
        series = await session.fetch_for_specs(
            jnc_resource, part_spec_analyzed, fetch_otions
        )

        await session.create_epub(series, epub_generation_options)
