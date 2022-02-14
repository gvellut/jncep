import logging

import click

from . import options
from .. import core, jncweb, spec
from ..trio_utils import coro
from .base import CatchAllExceptionsCommand

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
    epub_generation_options = core.EpubGenerationOptions(
        output_dirpath,
        is_by_volume,
        is_extract_images,
        is_extract_content,
        is_not_replace_chars,
    )

    async with core.JNCEPSession(email, password) as session:
        jnc_resource = jncweb.resource_from_url(jnc_url)

        if part_spec:
            logger.info(f"Using part specification '{part_spec}' ")
            part_spec_analyzed = spec.analyze_part_specs(part_spec)
        else:
            part_spec_analyzed = await core.to_part_spec(session, jnc_resource)

        series = await core.resolve_series(session, jnc_resource)
        series_meta = await core.fill_meta(
            session, series, volume_callback=part_spec_analyzed.has_volume
        )

        # TODO log that part is unavailable to show user
        def part_filter(part):
            return part_spec_analyzed.has_part(part) and core.is_part_available(
                part, session.now
            )

        (
            volumes_to_download,
            parts_to_download,
        ) = core.relevant_volumes_and_parts_for_content(series_meta, part_filter)
        volumes_for_cover = core.relevant_volumes_for_cover(
            volumes_to_download, epub_generation_options
        )

        await core.fill_covers_and_content(
            session, volumes_for_cover, parts_to_download
        )
        await core.create_epub(
            series_meta, volumes_to_download, parts_to_download, epub_generation_options
        )
