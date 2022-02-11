from functools import partial
import logging
import os

import click
import trio

from . import options
from .. import core, epub, jncweb, spec
from ..utils import green
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
def generate_epub(*args, **kwargs):
    trio.run(partial(_main, *args, **kwargs))


async def _main(
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

        # TODO download cover
        # TODO handle exceptions
        # TODO extract images
        # TODO extract content
        # TODO split by volume

        if part_spec:
            logger.info(f"Using part specification '{part_spec}' ")
            part_spec_analyzed = spec.analyze_part_specs(part_spec)
        else:
            part_spec_analyzed = await session.to_part_spec(jnc_resource)

        series = await session.fetch_for_specs(
            jnc_resource, part_spec_analyzed, epub_generation_options
        )

        # TODO process split in volume
        book_details = session.process_downloaded(series, epub_generation_options)

        if is_extract_content:
            await session.extract_content(series, epub_generation_options)

        if is_extract_images:
            await session.extract_images(series, epub_generation_options)

        output_filename = core.to_safe_filename(book_details.title) + ".epub"
        output_filepath = os.path.join(
            epub_generation_options.output_dirpath, output_filename
        )
        # TODO write to memory then async fs write here ? (use epublib which is sync)
        epub.create_epub(output_filepath, book_details)

        logger.info(green(f"Success! EPUB generated in '{output_filepath}'!"))
