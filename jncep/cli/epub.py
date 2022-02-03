from functools import partial
import logging
import os

import click
import trio

from . import options
from .. import core, epub, jncweb, spec
from ..jnclabs import JNCLabsAPI
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

    # TODO put the api + cache state in container class (with Result)
    api = JNCLabsAPI()
    try:
        jnc_resource = jncweb.resource_from_url(jnc_url)

        logger.info(f"Login with email '{email}'...")
        await api.login(email, password)

        # TODO download cover
        # TODO handle exceptions
        # TODO extract images
        # TODO extract content
        # TODO split by volume

        # TODO make the to_part_spec + fetch part of the Result class
        # TODO rename Result class
        result = core.Result()
        if part_spec:
            logger.info(f"Using part specification '{part_spec}' ")
            part_spec_analyzed = spec.analyze_part_specs(part_spec)
        else:
            part_spec_analyzed = await core.to_part_spec(api, jnc_resource, result)

        await core.fetch_for_specs(api, jnc_resource, part_spec_analyzed, result)
        # TODO process split in volume  + extract image + content
        book_details = core.process_downloaded(result, epub_generation_options)
        output_filename = core.to_safe_filename(book_details.title) + ".epub"
        output_filepath = os.path.join(
            epub_generation_options.output_dirpath, output_filename
        )
        epub.create_epub(output_filepath, book_details)

    finally:
        if api.is_logged_in:
            try:
                logger.info("Logout...")
                await api.logout()
            except Exception:
                pass
