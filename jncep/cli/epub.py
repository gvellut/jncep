from functools import partial
import logging

import click

from . import options
from .. import core, jncweb, spec, utils
from ..trio_utils import bag, coro
from .base import CatchAllExceptionsCommand

logger = logging.getLogger(__name__)
console = utils.getConsole()


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
@options.css_option
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
    style_css_path,
):
    # created by group
    epub_generation_options = core.EpubGenerationOptions(
        output_dirpath,
        is_by_volume,
        is_extract_images,
        is_extract_content,
        is_not_replace_chars,
        style_css_path,
    )

    async with core.JNCEPSession(email, password) as session:
        jnc_resource = jncweb.resource_from_url(jnc_url)

        if part_spec:
            console.info(f"Use part specification '[highlight]{part_spec}[/]'")
            part_spec_analyzed = spec.analyze_part_specs(part_spec)
        else:
            part_spec_analyzed = await core.to_part_spec(session, jnc_resource)

        console.status("Get content...")

        series = await core.resolve_series(session, jnc_resource)
        series_meta = await core.fill_meta(
            session, series, volume_callback=part_spec_analyzed.has_volume
        )

        # TODO event ? Think better logging system / notification to the user
        # to support maybe GUI

        has_unavailable_parts = False

        def part_filter(part):
            if part_spec_analyzed.has_part(part):
                if core.is_part_available(session.now, part):
                    return True
                else:
                    nonlocal has_unavailable_parts
                    has_unavailable_parts = True
            return False

        (
            volumes_to_download,
            parts_to_download,
        ) = core.relevant_volumes_and_parts_for_content(series_meta, part_filter)

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

        tasks = [
            partial(
                core.fill_covers_and_content,
                session,
                volumes_for_cover,
                parts_to_download,
            ),
            partial(
                core.fill_num_parts_for_volumes,
                session,
                series_meta,
                volumes_to_download,
            ),
        ]
        await bag(tasks)

        console.status("Create EPUB...")

        await core.create_epub(
            series_meta,
            volumes_to_download,
            parts_to_download,
            epub_generation_options,
        )
