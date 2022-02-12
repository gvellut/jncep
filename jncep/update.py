import logging
import sys

import attr
import trio

from . import core, jncweb, spec
from .core import all_parts, AsyncCollector, dl_parts, FetchOptions, IdentifierSpec
from .track import LastPartSpec
from .utils import green

logger = logging.getLogger(__package__)


@attr.s
class MultiSpec:
    specs = attr.ib()

    def has_volume(self, ref_volume) -> bool:
        for sp in self.specs:
            if sp.has_volume(ref_volume):
                return True
        return False

    def has_part(self, ref_part) -> bool:
        for sp in self.specs:
            if sp.has_part(ref_part):
                return True
        return False


async def update_url_series(
    session,
    jnc_url,
    epub_generation_options,
    tracked_series,
    updated_series,
    is_sync,
    new_synced,
    is_whole_volume,
):
    jnc_resource = jncweb.resource_from_url(jnc_url)

    logger.info(f"Fetching metadata for '{jnc_resource}'...")
    jncapi_legacy.fetch_metadata(token, jnc_resource)

    series = analyze_metadata(jnc_resource)

    series_slug = series.raw_series.titleslug
    series_url = jncweb.url_from_series_slug(series_slug)

    if is_sync:
        # not very useful but make it possible
        # only consider newly synced series if --sync used
        # to mirror case with no URL argument
        if series_url not in new_synced:
            logger.warning(
                f"The series '{series.raw_series.title}' is not among the "
                f"tracked series added from syncing. Use 'jncep update' "
                "without --sync."
            )
            return
        is_updated = _create_epub_from_beginning(token, series, epub_generation_options)

    else:
        if series_url not in tracked_series:
            logger.warning(
                f"The series '{series.raw_series.title}' is not tracked! "
                f"Use the 'jncep track add' command first."
            )
            return

        series_details = tracked_series[series_url]
        is_updated = _create_updated_epub(
            token, series, series_details, epub_generation_options, is_whole_volume
        )

    if is_updated:
        logger.info(green(f"The series '{series.raw_series.title}' has been updated!"))
        updated_series.append(series)


async def update_all_series(
    session,
    epub_generation_options,
    tracked_series,
    is_sync,
    new_synced,
    is_whole_volume,
):
    with AsyncCollector() as c:
        async with trio.open_nursery() as nursery:
            for series_url, series_details in tracked_series.items():
                # TODO channels to indicate which series have been updated

                nursery.start_soon(
                    c.collect(
                        series_url,
                        _handle_series,
                        session,
                        series_url,
                        series_details,
                        epub_generation_options,
                        is_sync,
                        new_synced,
                        is_whole_volume,
                    )
                )

        updated_series = {}
        error_series = set()
        for series_url, (last_part, is_error) in c.results.items():
            if last_part:
                updated_series[series_url] = last_part

            if is_error:
                error_series.add(series_url)

        return updated_series, error_series


async def _handle_series(
    session,
    series_url,
    series_details,
    epub_generation_options,
    is_sync,
    new_synced,
    is_whole_volume,
):
    try:
        if is_sync and series_url not in new_synced:
            # FIXME not implemented
            return

        jnc_resource = jncweb.resource_from_url(series_url)
        series_slug, func_resolve = session.lazy_resolve_series(jnc_resource)
        if not series_slug:
            series_raw_data = await func_resolve()
            series_slug = series_raw_data.slug

        if is_sync:
            raise NotImplementedError("is_sync LABS")
            # is_updated = _create_epub_from_beginning(
            #     token, series, epub_generation_options
            # )
        else:
            is_updated, series = await _create_epub_for_new_parts(
                session,
                series_details,
                series_slug,
                epub_generation_options,
                is_whole_volume,
            )

        last_part = None
        if is_updated:
            logger.info(
                green(f"The series '{series.raw_data.title}' has been updated!")
            )
            last_part = all_parts(series)[-1]

        return last_part, False

    except Exception as ex:
        logger.debug(str(ex), exc_info=sys.exc_info())
        return False, True


async def _create_epub_for_new_parts(
    session,
    series_details,
    series_slug,
    epub_generation_options,
    is_whole_volume,
):
    # FIXME all very ugly ; refactor
    # FIXME
    series_url = jncweb.url_from_series_slug(series_slug)
    jnc_resource = jncweb.resource_from_url(series_url)

    # fetch the TOC
    part_spec = LastPartSpec()
    fetch_options = FetchOptions(is_download_content=False, is_download_cover=False)
    series = await session.fetch_for_specs(jnc_resource, part_spec, fetch_options)

    parts = all_parts(series)

    last_part = None
    if parts:
        last_part = parts[-1]

    if series_details.part == 0:
        # special processing : means there was no part available when the
        # series was started tracking

        # TODO in this case no need to fetch the last part
        # fetch all : check that there is a part to distinguish branch below

        # still no part ?
        if not parts:
            series_with_dl_parts = None
            is_updated = False
        else:
            # complete series
            part_spec = spec.analyze_part_specs(":")
            fetch_options = FetchOptions(
                is_by_volume=epub_generation_options.is_by_volume
            )
            series_with_dl_parts = await session.fetch_for_specs(
                jnc_resource, part_spec, fetch_options
            )

            session.create_epub(series_with_dl_parts, epub_generation_options)

            is_updated = True

        return is_updated, series_with_dl_parts
    else:
        if not series_details.part_date:
            # TODO cleanup
            # TODO do this together with fetch toc + fetch last_part
            # if here => old format, first lookup date of last part and use that
            # TODO possible to do that for all ie no need to keep the date around
            # TODO remove ? suppose no old format ? but still maybe for stalled series
            part_spec = spec.analyze_part_specs(series_details.part)
            fetch_options = FetchOptions(
                is_download_content=False, is_download_cover=False
            )
            series = await session.fetch_for_specs(
                jnc_resource, part_spec, fetch_options
            )
            last_update_part = all_parts(series)[-1]
            # in UTC
            last_update_date = last_update_part.raw_data.launch
        else:
            last_update_date = series_details.part_date

        parts_to_download = []
        toc = await session.api.fetch_data("parts", last_part.part_id, "toc")
        # weird struct for the response : toc.parts has pagination struct (but all
        # parts seem to be there anyway) and parts property in turn
        for entry in toc.parts.parts:
            if entry.launch > last_update_date:
                parts_to_download.append(entry.legacyId)

        if not parts_to_download:
            is_updated = False
            return is_updated, None

        # fetch volumes for each parts
        # TODO optimize instead of all this : start from last volume backward
        # until .launch < recorded last update date
        # then we have all the part ids + volume
        with AsyncCollector() as c:
            async with trio.open_nursery() as nursery:
                for part_id in parts_to_download:
                    nursery.start_soon(
                        c.collect(
                            part_id, session.api.fetch_data, "parts", part_id, "volume"
                        )
                    )

            volumes = c.results

        specs = []
        if not is_whole_volume:
            for part_id in parts_to_download:
                volume_id = volumes[part_id].legacyId
                id_spec = IdentifierSpec(spec.PART, volume_id, part_id)
                specs.append(id_spec)
        else:
            volumes_id = set([v.legacyId for v in volumes.values()])
            for volume_id in volumes_id:
                id_spec = IdentifierSpec(spec.VOLUME, volume_id)
                specs.append(id_spec)

        multi_spec = MultiSpec(specs)
        fetch_options = FetchOptions(is_by_volume=epub_generation_options.is_by_volume)
        series = await session.fetch_for_specs(jnc_resource, multi_spec, fetch_options)

        if not dl_parts(series):
            logger.warning(
                f"All updated parts for '{series.raw_data.title}' have expired!"
            )
            raise core.NoRequestedPartAvailableError(series.raw_data.slug)
        await session.create_epub(series, epub_generation_options)

        is_updated = True
        return is_updated, series
