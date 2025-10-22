import logging

import click

from .. import core, jncalts, jncweb, namegen, spec, track, utils
from ..trio_utils import coro
from ..utils import tryint
from . import options
from .base import CatchAllExceptionsCommand

logger = logging.getLogger(__name__)
console = utils.getConsole()


@click.command(
    name="epub",
    help="Generate EPUB files for J-Novel Club pre-pub novels",
    cls=CatchAllExceptionsCommand,
)
@click.argument("jnc_url_or_index", metavar="JNOVEL_CLUB_URL", required=True)
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
async def generate_epub(
    jnc_url_or_index,
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
    name_generator = namegen.NameGenerator(namegen_rules)
    # created by group
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

    index = tryint(jnc_url_or_index)
    if index is not None:
        track_manager = track.TrackConfigManager()
        tracked_series = track_manager.read_tracked_series()

        index0 = index - 1
        if index0 < 0 or index0 >= len(tracked_series):
            console.warning(f"Index '{index}' is not valid! (Use 'track list')")
            return
        series_url_list = list(tracked_series.keys())
        jnc_url = series_url_list[index0]
        series_name = tracked_series[jnc_url].name
        console.info(f"Resolve to series '[highlight]{series_name}'[/]")
    else:
        jnc_url = jnc_url_or_index

    origin = jncalts.find_origin(jnc_url)
    config = jncalts.get_alt_config_for_origin(origin)

    async with core.JNCEPSession(config, credentials) as session:
        jnc_resource = jncweb.resource_from_url(jnc_url)
        series_id = await core.resolve_series(session, jnc_resource)
        series = await core.fetch_meta(session, series_id)
        core.check_series_is_novel(series)

        if part_spec:
            console.info(f"Use part specification '[highlight]{part_spec}[/]'")
            part_spec_analyzed = spec.analyze_part_specs(part_spec)
            part_spec_analyzed.normalize_and_verify(series)
        else:
            part_spec_analyzed = await core.to_part_spec(series, jnc_resource)

        await generate_epubs(
            session, series, part_spec_analyzed, epub_generation_options
        )


async def generate_epubs(session, series, part_spec_analyzed, epub_generation_options):
    console.status("Get content...")

    has_unavailable_parts = False

    # TODO do not use filter before trying to download : try to download and see if
    # rejected : print warning or error depending on command and if there can be no
    # EPUB file generated (no download)
    # may need to still filter for parts in future
    def part_filter(part):
        if part_spec_analyzed.has_part(part):
            if core.is_part_available(session.now, session.member_status, part):
                return True
            else:
                nonlocal has_unavailable_parts
                has_unavailable_parts = True
        return False

    (
        volumes_to_download,
        parts_to_download,
    ) = core.relevant_volumes_and_parts_for_content(series, part_filter)

    if not parts_to_download:
        console.error(
            "None of the requested parts are available! No EPUB will be generated.",
        )
        return

    if has_unavailable_parts:
        console.warning(
            "Some of the requested parts are not available for reading!",
        )

    volumes_for_cover = core.relevant_volumes_for_cover(
        volumes_to_download, epub_generation_options.is_by_volume
    )

    await core.fill_covers_and_content(session, volumes_for_cover, parts_to_download)

    has_missing, has_available = core.has_missing_part_content(parts_to_download)
    if has_missing:
        if has_available:
            console.warning(
                "Some parts were not downloaded correctly! Do you have a subscription?",
            )
            # continue: can generated an Epub with the downloaded parts
        else:
            console.error(
                "None of the parts were downloaded correctly! "
                "Do you have a subscription?",
            )
            return

    console.status("Create EPUB...")

    await core.create_epub(
        series,
        volumes_to_download,
        parts_to_download,
        epub_generation_options,
    )
