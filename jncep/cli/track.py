import logging

import click
from colorama import Fore
import dateutil.parser

from . import options
from .. import core, jncweb, track
from ..utils import colored, coro, green, tryint
from .base import CatchAllExceptionsCommand

logger = logging.getLogger(__name__)


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
        jnc_resource = jncweb.resource_from_url(jnc_url)
        series_slug, func_resolve = session.lazy_resolve_series(jnc_resource)
        if not series_slug:
            series_raw_data = await func_resolve()
            series_slug = series_raw_data.slug

        # TODO async read
        tracked_series = track.read_tracked_series()
        series_url = jncweb.url_from_series_slug(series_slug)

        if series_url in tracked_series:
            series_raw_data = await resolve_func()
            logger.warning(
                f"The series '{series_raw_data.raw_series.title}' is already tracked!"
            )
            return

        await track.process_series_for_tracking(session, tracked_series, series_url)

        # TOO async write
        track.write_tracked_series(tracked_series)


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
@coro
async def sync_series(email, password, is_reverse, is_delete):
    raise NotImplementedError("sync_series LABS")

    # tracked_series = core.read_tracked_series()

    # token = None
    # try:
    #     logger.info(f"Login with email '{email}'...")
    #     token = jncapi_legacy.login(email, password)

    #     logger.info("Fetch followed series from J-Novel Club...")
    #     follows: List[jncweb.JNCResource] = jncapi_legacy.fetch_follows(token)

    #     if is_reverse:
    #         track.sync_series_backward(token, follows, tracked_series, is_delete)
    #     else:
    #         track.sync_series_forward(token, follows, tracked_series, is_delete)
    # finally:
    #     if token:
    #         try:
    #             logger.info("Logout...")
    #             jncapi_legacy.logout(token)
    #         except Exception:
    #             pass


@track_series.command(
    name="rm", help="Remove a series from tracking", cls=CatchAllExceptionsCommand
)
@click.argument("jnc_url_or_index", metavar="JNOVEL_CLUB_URL_OR_INDEX", required=True)
@options.login_option
@options.password_option
@coro
async def rm_track_series(jnc_url_or_index, email, password):
    tracked_series = track.read_tracked_series()
    index = tryint(jnc_url_or_index)
    if index is not None:
        index0 = index - 1
        if index0 < 0 or index0 >= len(tracked_series):
            logger.warning(f"Index '{index}' is not valid! (Use 'track list')")
            return
        series_url_list = list(tracked_series.keys())
        series_url = series_url_list[index0]
    else:
        async with core.JNCEPSession(email, password) as session:
            jnc_resource = jncweb.resource_from_url(jnc_url_or_index)
            series_slug, func_resolve = session.lazy_resolve_series(jnc_resource)
            if not series_slug:
                series_raw_data = await func_resolve()
                series_slug = series_raw_data.slug
            series_url = jncweb.url_from_series_slug(series_slug)

            if series_url not in tracked_series:
                series_raw_data = await resolve_func()
                logger.warning(
                    f"The series '{series_raw_data.title}' is not tracked! "
                    "(Use 'track list --details')"
                )
                return

    series_name = tracked_series[series_url].name

    del tracked_series[series_url]

    track.write_tracked_series(tracked_series)

    logger.info(green(f"The series '{series_name}' is no longer tracked"))


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
    tracked_series = track.read_tracked_series()
    if len(tracked_series) > 0:
        logger.info(f"{len(tracked_series)} series are tracked:")
        for index, (ser_url, ser_details) in enumerate(tracked_series.items()):
            details = None
            if ser_details.part_date:
                part_date = dateutil.parser.parse(ser_details.part_date)
                part_date_formatted = part_date.strftime("%b %d, %Y")
                details = f"{ser_details.part} [{part_date_formatted}]"
            elif ser_details.part == 0:
                details = "No part released"
            else:
                details = f"{ser_details.part}"

            msg = f"[{colored(index + 1, Fore.YELLOW)}] {green(ser_details.name)}"
            if is_detail:
                msg += f" {ser_url} {colored(details, Fore.RED)}"

            logger.info(msg)
    else:
        logger.info("No series is tracked.")
