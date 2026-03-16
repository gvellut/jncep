import logging

import click

from .. import core, jncalts, jncweb, namegen, spec, track, utils
from ..trio_utils import coro
from . import options
from .base import CatchAllExceptionsCommand
from .epub import generate_epubs
from .track import _add_track_series_logic

logger = logging.getLogger(__name__)
console = utils.getConsole()


@click.command(
    name="get",
    help="Track and generate EPUB for a new series",
    cls=CatchAllExceptionsCommand,
)
@click.argument("jnc_url", metavar="JNOVEL_CLUB_URL", required=True)
@options.credentials_options
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
@options.subfolder_option
@options.images_option
@options.raw_content_option
@options.no_replace_chars_option
@options.css_option
@options.namegen_option
@coro
async def get_series(
    jnc_url,
    credentials: jncalts.AltCredentials,
    part_spec,
    output_dirpath,
    is_by_volume,
    is_subfolder,
    is_extract_images,
    is_extract_content,
    is_not_replace_chars,
    style_css_path,
    namegen_rules,
):
    origin = jncalts.find_origin(jnc_url)
    config = jncalts.get_alt_config_for_origin(origin)

    async with core.JNCEPSession(config, credentials) as session:
        series = await _add_track_series_logic(session, jnc_url, is_beginning=True, is_first_available_volume=False)

        # This is from epub generate
        name_generator = namegen.NameGenerator(namegen_rules)
        epub_generation_options = core.EpubGenerationOptions(
            output_dirpath,
            is_subfolder,
            is_by_volume,
            is_extract_images,
            is_extract_content,
            is_not_replace_chars,
            style_css_path,
            name_generator,
        )

        jnc_resource = jncweb.resource_from_url(jnc_url)

        if part_spec:
            console.info(f"Use part specification '[highlight]{part_spec}[/]'")
            part_spec_analyzed = spec.analyze_part_specs(part_spec)
            part_spec_analyzed.normalize_and_verify(series)
        else:
            part_spec_analyzed = await core.to_part_spec(series, jnc_resource)

        await generate_epubs(
            session, series, part_spec_analyzed, epub_generation_options
        )
