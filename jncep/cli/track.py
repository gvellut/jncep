import logging
from typing import List

import click
import dateutil.parser

from . import options
from .. import core, jncweb, track, utils
from ..trio_utils import coro
from ..utils import tryint
from .base import CatchAllExceptionsCommand

logger = logging.getLogger(__name__)
console = utils.getConsole()


@click.group(name="track", help="Track updates to a series")
def track_series():
    pass


@track_series.command(
    name="add", help="Add a new series for tracking", cls=CatchAllExceptionsCommand
)
@click.argument("jnc_url", metavar="JNOVEL_CLUB_URL", required=True)
@options.login_option
@options.password_option
@coro
async def add_track_series(jnc_url, email, password):
    async with core.JNCEPSession(email, password) as session:
        # TODO async read
        track_manager = track.TrackConfigManager()
        tracked_series = track_manager.read_tracked_series()

        console.status("Check tracking status...")

        jnc_resource = jncweb.resource_from_url(jnc_url)
        series_id = await core.resolve_series(session, jnc_resource)
        series = await core.fetch_meta(session, series_id)
        core.check_series_is_novel(series)

        series_url = jncweb.url_from_series_slug(series.raw_data.slug)
        if series_url in tracked_series:
            console.warning(
                f"The series '[highlight]{series.raw_data.title}[/]' is "
                "already tracked!"
            )
            return

        await track.track_series(session, tracked_series, series)

        # TOO async write
        track_manager.write_tracked_series(tracked_series)


@track_series.command(
    name="sync",
    help="Sync list of series to track based on series followed on J-Novel Club "
    "website",
    cls=CatchAllExceptionsCommand,
)
@options.login_option
@options.password_option
@click.option(
    "-r",
    "--reverse",
    "is_reverse",
    is_flag=True,
    help=(
        "Flag to sync followed series on JNC website based on the series tracked with "
        "jncep"
    ),
)
@click.option(
    "-d",
    "--delete",
    "is_delete",
    is_flag=True,
    help="Flag to delete series not found on the sync source",
)
# from the beginning: so that when update is run after => update from the beginning
@click.option(
    "-b",
    "--beginning",
    "is_beginning",
    is_flag=True,
    help="Flag to add new series from the beginning",
)
@coro
async def sync_series(email, password, is_reverse, is_delete, is_beginning):
    track_manager = track.TrackConfigManager()
    tracked_series = track_manager.read_tracked_series()

    async with core.JNCEPSession(email, password) as session:
        console.status("Fetch followed series from J-Novel Club...")
        follows: List[jncweb.JNCResource] = await core.fetch_follows(session)

        if is_reverse:
            console.status("Sync to J-Novel Club...")

            new_synced, del_synced = await track.sync_series_backward(
                session, follows, tracked_series, is_delete
            )

            if new_synced or del_synced:
                console.info(
                    "The list of followed series has been sucessfully updated!",
                    style="success",
                )
            else:
                console.info(
                    "Everything is already synced!",
                    style="success",
                )

        else:
            console.status("Sync tracked series from J-Novel Club...")

            new_synced, del_synced = await track.sync_series_forward(
                session, follows, tracked_series, is_delete, is_beginning
            )

            track_manager.write_tracked_series(tracked_series)

            if new_synced or del_synced:
                console.info(
                    "The list of tracked series has been sucessfully updated!",
                    style="success",
                )
            else:
                console.info(
                    "Everything is already synced!",
                    style="success",
                )


@track_series.command(
    name="rm", help="Remove a series from tracking", cls=CatchAllExceptionsCommand
)
@click.argument("jnc_url_or_index", metavar="JNOVEL_CLUB_URL_OR_INDEX", required=True)
@options.login_option
@options.password_option
@coro
async def rm_track_series(jnc_url_or_index, email, password):
    track_manager = track.TrackConfigManager()
    tracked_series = track_manager.read_tracked_series()

    index = tryint(jnc_url_or_index)
    if index is not None:
        index0 = index - 1
        if index0 < 0 or index0 >= len(tracked_series):
            console.warning(f"Index '{index}' is not valid! (Use 'track list')")
            return
        series_url_list = list(tracked_series.keys())
        series_url = series_url_list[index0]
    else:
        async with core.JNCEPSession(email, password) as session:
            console.status("Check tracking status...")
            jnc_resource = jncweb.resource_from_url(jnc_url_or_index)
            series_id = await core.resolve_series(session, jnc_resource)
            series = await core.fetch_meta(session, series_id)
            series_url = jncweb.url_from_series_slug(series.raw_data.slug)

            if series_url not in tracked_series:
                console.warning(
                    f"The series '[highlight]{series.raw_data.title}[/]' is not "
                    "tracked! (Use 'track list --details')"
                )
                return

    series_name = tracked_series[series_url].name

    del tracked_series[series_url]

    track_manager.write_tracked_series(tracked_series)

    console.info(
        f"The series '[highlight]{series_name}[/]' is no longer tracked",
        style="success",
    )


@track_series.command(
    name="list", help="List tracked series", cls=CatchAllExceptionsCommand
)
@click.option(
    "-t",
    "--details",
    "is_detail",
    is_flag=True,
    help="Flag to list the details of the tracked series (URL, date of last release)",
)
def list_track_series(is_detail):
    # TODO async ? zero utility
    track_manager = track.TrackConfigManager()
    tracked_series = track_manager.read_tracked_series()

    if len(tracked_series) > 0:
        console.info(f"{len(tracked_series)} series are tracked:")
        for index, (ser_url, ser_details) in enumerate(tracked_series.items()):
            details = None
            if ser_details.part == 0:
                if ser_details.last_check_date == track.FROM_BEGINNING_CHECK_DATE:
                    # added with --beginning
                    details = "Not yet updated"
                else:
                    details = "No part released"
            elif ser_details.part_date:
                part_date = dateutil.parser.parse(ser_details.part_date)
                part_date_formatted = part_date.strftime("%b %d, %Y")
                details = f"{ser_details.part} [{part_date_formatted}]"
            else:
                details = f"{ser_details.part}"

            msg = f"[[yellow]{index + 1}[/]] [green]{ser_details.name}[/]"
            if is_detail:
                msg += f" {ser_url} [red]{details}[/]"

            console.info(msg)
    else:
        console.warning("No series is tracked.")
