import itertools
import logging
import os
import sys
import traceback
from typing import List

import click
import dateutil.parser

from . import core, jncapi
from .utils import green, setup_logging

logger = logging.getLogger(__package__)

login_option = click.option(
    "-l",
    "--email",
    required=True,
    envvar="JNCEP_EMAIL",
    help="Login email for J-Novel Club account",
)

password_option = click.option(
    "-p",
    "--password",
    required=True,
    envvar="JNCEP_PASSWORD",
    help="Login password for J-Novel Club account",
)

output_option = click.option(
    "-o",
    "--output",
    "output_dirpath",
    type=click.Path(exists=True, resolve_path=True, file_okay=False, writable=True),
    default=os.getcwd(),
    envvar="JNCEP_OUTPUT",
    help="Existing folder to write the output [default: The current directory]",
)

byvolume_option = click.option(
    "-v",
    "--byvolume",
    "is_by_volume",
    is_flag=True,
    help=(
        "Flag to indicate that the parts of different volumes shoud be output in "
        "separate EPUBs"
    ),
)

images_option = click.option(
    "-i",
    "--images",
    "is_extract_images",
    is_flag=True,
    help=(
        "Flag to indicate that the images of the novel should be extracted into "
        "the output folder"
    ),
)

raw_content_option = click.option(
    "-c",
    "--content",
    "is_extract_content",
    is_flag=True,
    help=(
        "Flag to indicate that the raw content of the parts should be extracted into "
        "the output folder"
    ),
)

no_replace_chars_option = click.option(
    "-n",
    "--no-replace",
    "is_not_replace_chars",
    is_flag=True,
    help=(
        "Flag to indicate that some unicode characters unlikely to be in an EPUB "
        "reader font should NOT be replaced and instead kept as is"
    ),
)


class CatchAllExceptionsCommand(click.Command):
    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except Exception as ex:
            raise UnrecoverableJNCEPError(str(ex), sys.exc_info())


class UnrecoverableJNCEPError(click.ClickException):
    def __init__(self, message, exc_info):
        super().__init__(message)
        self.exc_info = exc_info

    def show(self):
        logger.error("*** An unrecoverable error occured ***")
        logger.error(self.message)
        logger.debug("".join(traceback.format_exception(*self.exc_info)))


class NoRequestedPartAvailableError(Exception):
    pass


@click.group(
    help="Simple command-line tool to generate EPUB files for J-Novel Club pre-pub "
    "novels"
)
@click.option(
    "-d",
    "--debug",
    "is_debug",
    is_flag=True,
    help=("Flag to activate debug mode"),
    required=False,
)
def main(is_debug):
    setup_logging(is_debug)


@main.command(
    name="epub",
    help="Generate EPUB files for J-Novel Club pre-pub novels",
    cls=CatchAllExceptionsCommand,
)
@click.argument("jnc_url", metavar="JNOVEL_CLUB_URL", required=True)
@login_option
@password_option
@output_option
@click.option(
    "-s",
    "--parts",
    "part_specs",
    help=(
        "Specification of a range of parts to download in the form of "
        "<vol>[.part]:<vol>[.part] [default: All the content linked by "
        "the JNOVEL_CLUB_URL argument, either a single part, a whole volume "
        "or the whole series]"
    ),
)
@click.option(
    "-a",
    "--absolute",
    "is_absolute",
    is_flag=True,
    help=(
        "Flag to indicate that the --parts option specifies part numbers "
        "globally, instead of relative to a volume i.e. <part>:<part>"
    ),
)
@byvolume_option
@images_option
@raw_content_option
@no_replace_chars_option
def generate_epub(
    jnc_url,
    email,
    password,
    part_specs,
    is_absolute,
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

    token = None
    try:
        jnc_resource = jncapi.resource_from_url(jnc_url)

        logger.info(f"Login with email '{email}'...")
        token = jncapi.login(email, password)

        logger.info(f"Fetching metadata for '{jnc_resource}'...")
        jncapi.fetch_metadata(token, jnc_resource)

        series = core.analyze_metadata(jnc_resource)

        if part_specs:
            logger.info(
                f"Using part specification '{part_specs}' "
                f"(absolute={_to_yn(is_absolute)})..."
            )
            parts_to_download = core.analyze_part_specs(series, part_specs, is_absolute)
        else:
            parts_to_download = core.analyze_requested(jnc_resource, series)

        _create_epub_with_requested_parts(
            token, series, parts_to_download, epub_generation_options
        )
    finally:
        if token:
            try:
                logger.info("Logout...")
                jncapi.logout(token)
            except Exception:
                pass


# TODO separate command groups into different files
@main.group(name="track", help="Track updates to a series")
def track_series():
    pass


@track_series.command(
    name="add", help="Add a new series for tracking", cls=CatchAllExceptionsCommand
)
@click.argument("jnc_url", metavar="JNOVEL_CLUB_URL", required=True)
@login_option
@password_option
def add_track_series(jnc_url, email, password):
    series, series_url = _canonical_series(jnc_url, email, password)
    tracked_series = core.read_tracked_series()

    if series_url in tracked_series:
        logger.warning(f"The series '{series.raw_series.title}' is already tracked!")
        return

    _process_series_for_tracking(tracked_series, series, series_url)

    core.write_tracked_series(tracked_series)


def _process_series_for_tracking(tracked_series, series, series_url):
    # record current last part + name
    if len(series.parts) == 0:
        # no parts yet
        pn = 0
        # 0000-... not a valid date so 1111-...
        pdate = "1111-11-11T11:11:11.111Z"
    else:
        pn = core.to_relative_part_string(series, series.parts[-1])
        pdate = series.parts[-1].raw_part.launchDate

    tracked_series[series_url] = {
        "part_date": pdate,
        "part": pn,  # now just for show
        "name": series.raw_series.title,
    }

    if len(series.parts) == 0:
        logger.info(
            green(
                f"The series '{series.raw_series.title}' is now tracked, starting "
                f"from the beginning"
            )
        )
    else:
        relative_part = core.to_relative_part_string(series, series.parts[-1])
        part_date = dateutil.parser.parse(series.parts[-1].raw_part.launchDate)
        part_date_formatted = part_date.strftime("%b %d, %Y")
        logger.info(
            green(
                f"The series '{series.raw_series.title}' is now tracked, starting "
                f"after part {relative_part} [{part_date_formatted}]"
            )
        )


@track_series.command(
    name="sync",
    help="Sync list of series to track based on series followed on J-Novel Club "
    "website",
    cls=CatchAllExceptionsCommand,
)
@login_option
@password_option
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
def sync_series(email, password, is_reverse, is_delete):
    tracked_series = core.read_tracked_series()

    token = None
    try:
        logger.info(f"Login with email '{email}'...")
        token = jncapi.login(email, password)

        logger.info("Fetch followed series from J-Novel Club...")
        follows: List[jncapi.JNCResource] = jncapi.fetch_follows(token)

        if is_reverse:
            _sync_series_backward(token, follows, tracked_series, is_delete)
        else:
            _sync_series_forward(token, follows, tracked_series, is_delete)
    finally:
        if token:
            try:
                logger.info("Logout...")
                jncapi.logout(token)
            except Exception:
                pass


def _sync_series_forward(token, follows, tracked_series, is_delete):
    # sync local tracked series based on remote follows
    new_synced = []
    del_synced = []
    for jnc_resource in follows:
        if jnc_resource.url in tracked_series:
            continue
        series, series_url = _tracking_series_metadata(token, jnc_resource)
        _process_series_for_tracking(tracked_series, series, series_url)

        new_synced.append(series_url)

    if is_delete:
        followed_index = {f.url: f for f in follows}
        # to avoid dictionary changed size during iteration
        for series_url, series_data in list(tracked_series.items()):
            if series_url not in followed_index:
                del tracked_series[series_url]

                logger.warning(f"The series '{series_data.name}' is no longer tracked")

                del_synced.append(series_url)

    core.write_tracked_series(tracked_series)

    if new_synced or del_synced:
        logger.info(green("The list of tracked series has been sucessfully updated!"))
    else:
        logger.info(green("Everything is already synced!"))

    return new_synced, del_synced


def _sync_series_backward(token, follows, tracked_series, is_delete):
    # sync remote follows based on locally tracked series
    new_synced = []
    del_synced = []

    followed_index = {f.url: f for f in follows}
    for series_url in tracked_series:
        # series_url is the latest URL format (same as the follows)
        if series_url in followed_index:
            continue

        jnc_resource = jncapi.resource_from_url(series_url)
        logger.info(f"Fetching metadata for '{jnc_resource}'...")
        jncapi.fetch_metadata(token, jnc_resource)
        series_id = jnc_resource.raw_metadata.id
        title = jnc_resource.raw_metadata.title
        logger.info(f"Follow '{title}'...")
        jncapi.follow_series(token, series_id)

        new_synced.append(series_url)

    if is_delete:
        for jnc_resource in follows:
            if jnc_resource.url not in tracked_series:
                series_id = jnc_resource.raw_metadata.id
                title = jnc_resource.raw_metadata.title
                logger.warning(f"Unfollow '{title}'...")
                jncapi.unfollow_series(token, series_id)

                del_synced.append(jnc_resource.url)

    if new_synced or del_synced:
        logger.info(green("The list of followed series has been sucessfully updated!"))
    else:
        logger.info(green("Everything is already synced!"))

    return new_synced, del_synced


@track_series.command(
    name="rm", help="Remove a series from tracking", cls=CatchAllExceptionsCommand
)
@click.argument("jnc_url", metavar="JNOVEL_CLUB_URL", required=True)
@login_option
@password_option
def remove_track_series(jnc_url, email, password):
    series, series_url = _canonical_series(jnc_url, email, password)
    tracked_series = core.read_tracked_series()

    if series_url not in tracked_series:
        logger.warning(f"The series '{series.raw_series.title}' is not tracked!")
        return

    del tracked_series[series_url]

    core.write_tracked_series(tracked_series)

    logger.info(green(f"The series '{series.raw_series.title}' is no longer tracked"))


@track_series.command(
    name="list", help="List tracked series", cls=CatchAllExceptionsCommand
)
def list_track_series():
    tracked_series = core.read_tracked_series()
    if len(tracked_series) > 0:
        logger.info(f"{len(tracked_series)} series are tracked:")
        for ser_url, ser_details in tracked_series.items():
            details = None
            if ser_details.part_date:
                part_date = dateutil.parser.parse(ser_details.part_date)
                part_date_formatted = part_date.strftime("%b %d, %Y")
                details = f"{ser_details.part} [{part_date_formatted}]"
            elif ser_details.part == 0:
                details = "No part released"
            else:
                details = f"{ser_details.part}"

            logger.info(f"'{green(ser_details.name)}' ({ser_url}): {details}")
    else:
        logger.info(f"No series is tracked.")


def _canonical_series(jnc_url, email, password):
    token = None
    try:
        jnc_resource = jncapi.resource_from_url(jnc_url)

        logger.info(f"Login with email '{email}'...")
        token = jncapi.login(email, password)

        return _tracking_series_metadata(token, jnc_resource)
    finally:
        if token:
            try:
                logger.info("Logout...")
                jncapi.logout(token)
            except Exception:
                pass


def _tracking_series_metadata(token, jnc_resource):
    logger.info(f"Fetching metadata for '{jnc_resource}'...")
    jncapi.fetch_metadata(token, jnc_resource)

    series = core.analyze_metadata(jnc_resource)
    series_slug = series.raw_series.titleslug
    series_url = jncapi.url_from_series_slug(series_slug)

    return series, series_url


@main.command(
    name="update",
    help="Generate EPUB files for new parts of all tracked series (or specific "
    "series if a URL argument is passed)",
    cls=CatchAllExceptionsCommand,
)
@click.argument("jnc_url", metavar="(JNOVEL_CLUB_URL?)", required=False)
@login_option
@password_option
@output_option
@byvolume_option
@images_option
@raw_content_option
@no_replace_chars_option
@click.option(
    "-s",
    "--sync",
    "is_sync",
    is_flag=True,
    help=(
        "Flag to sync tracked series based on series followed on J-Novel Club and "
        "update the new ones from the beginning of the series"
    ),
)
def update_tracked(
    jnc_url,
    email,
    password,
    output_dirpath,
    is_by_volume,
    is_extract_images,
    is_extract_content,
    is_not_replace_chars,
    is_sync,
):
    epub_generation_options = core.EpubGenerationOptions(
        output_dirpath,
        is_by_volume,
        is_extract_images,
        is_extract_content,
        is_not_replace_chars,
    )

    token = None
    updated_series = []
    try:
        tracked_series = core.read_tracked_series()
        if len(tracked_series) == 0:
            logger.warning(
                "There are no tracked series! Use the 'jncep track add' command "
                "first."
            )
            return

        logger.info(f"Login with email '{email}'...")
        token = jncapi.login(email, password)

        new_synced = None
        if is_sync:
            logger.info("Fetch followed series from J-Novel Club...")
            follows = jncapi.fetch_follows(token)
            new_synced, _ = _sync_series_forward(token, follows, tracked_series, False)

        if jnc_url:
            _update_url_series(
                token,
                jnc_url,
                epub_generation_options,
                tracked_series,
                updated_series,
                is_sync,
                new_synced,
            )
            if len(updated_series) == 0:
                return
        else:
            has_error = _update_all_series(
                token,
                epub_generation_options,
                tracked_series,
                updated_series,
                is_sync,
                new_synced,
            )

            if has_error:
                logger.error("Some series could not be updated!")

            if len(updated_series) == 0:
                # TODO case all in error ?
                logger.info(green(f"All series are already up to date!"))
                return
    finally:
        if token:
            try:
                logger.info("Logout...")
                jncapi.logout(token)
            except Exception:
                pass

    if len(updated_series) > 0:
        # update tracking config JSON
        for series in updated_series:
            pn = core.to_relative_part_string(series, series.parts[-1])
            pdate = series.parts[-1].raw_part.launchDate
            tracked_series[jncapi.url_from_series_slug(series.raw_series.titleslug)] = {
                "part_date": pdate,
                "part": pn,
                "name": series.raw_series.title,
            }
        core.write_tracked_series(tracked_series)

        logger.info(green(f"{len(updated_series)} series sucessfully updated!"))


def _update_url_series(
    token,
    jnc_url,
    epub_generation_options,
    tracked_series,
    updated_series,
    is_sync,
    new_synced,
):
    jnc_resource = jncapi.resource_from_url(jnc_url)

    logger.info(f"Fetching metadata for '{jnc_resource}'...")
    jncapi.fetch_metadata(token, jnc_resource)

    series = core.analyze_metadata(jnc_resource)

    series_slug = series.raw_series.titleslug
    series_url = jncapi.url_from_series_slug(series_slug)

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
            token, series, series_details, epub_generation_options
        )

    if is_updated:
        logger.info(green(f"The series '{series.raw_series.title}' has been updated!"))
        updated_series.append(series)


def _update_all_series(
    token, epub_generation_options, tracked_series, updated_series, is_sync, new_synced,
):
    has_error = False
    for series_url, series_details in tracked_series.items():
        try:
            if is_sync and series_url not in new_synced:
                continue

            jnc_resource = jncapi.resource_from_url(series_url)

            logger.info(f"Fetching metadata for '{jnc_resource}'...")
            jncapi.fetch_metadata(token, jnc_resource)

            series = core.analyze_metadata(jnc_resource)

            if is_sync:
                is_updated = _create_epub_from_beginning(
                    token, series, epub_generation_options
                )
            else:
                is_updated = _create_updated_epub(
                    token, series, series_details, epub_generation_options
                )

            if is_updated:
                logger.info(
                    green(f"The series '{series.raw_series.title}' has been updated!")
                )
                updated_series.append(series)

        except Exception as ex:
            has_error = True
            logger.error("An error occured while updating the series:")
            logger.error(str(ex))
            logger.debug(traceback.format_exc())

    return has_error


def _to_yn(b):
    return "yes" if b else "no"


def _create_epub_from_beginning(token, series, epub_generation_options):
    if len(series.parts) == 0:
        new_parts = None
    else:
        # complete series
        new_parts = core.analyze_part_specs(series, ":", True)

    if not new_parts:
        # no new part
        logger.warning(
            f"The series '{series.raw_series.title}' has no parts available!",
        )
        return False

    return _create_epub_with_updated_parts(
        token, series, new_parts, epub_generation_options
    )


def _create_updated_epub(token, series, series_details, epub_generation_options):
    if series_details.part == 0:
        # special processing : means there was no part available when the
        # series was started tracking

        # still no part ?
        if len(series.parts) == 0:
            is_updated = False
            # just to bind or pylint complains
            new_parts = None
        else:
            is_updated = True
            # complete series
            new_parts = core.analyze_part_specs(series, ":", True)
    else:
        # for others, look at the date if there
        if not series_details.part_date:
            # if not => old format, first lookup date of last part and use that
            # TODO possible to do that for all ie no need to keep the date around
            last_part = core.to_part(series, series_details.part)
            last_update_date = last_part.raw_part.launchDate
        else:
            last_update_date = series_details.part_date

        new_parts = _parts_released_after_date(series, last_update_date)
        is_updated = len(new_parts) > 0

    if not is_updated:
        # no new part
        logger.warning(f"The series '{series.raw_series.title}' has not been updated!",)
        return False

    return _create_epub_with_updated_parts(
        token, series, new_parts, epub_generation_options
    )


def _parts_released_after_date(series, date):
    parts = []
    comparison_date = dateutil.parser.parse(date)
    for part in series.parts:
        # all date strings are in ISO format
        # so no need to parse really
        # parsing just to be safe
        launch_date = dateutil.parser.parse(part.raw_part.launchDate)
        if launch_date > comparison_date:
            parts.append(part)
    return parts


def _create_epub_with_updated_parts(token, series, new_parts, epub_generation_options):
    # just wrap _create_epub_with_requested_parts but handle case where parts
    # have expired
    try:
        _create_epub_with_requested_parts(
            token, series, new_parts, epub_generation_options
        )
        return True
    except NoRequestedPartAvailableError:
        logger.error("The parts that need to be updated have all expired!")
        return False


def _create_epub_with_requested_parts(
    token, series, parts_to_download, epub_generation_options
):
    # preview => parts 1 of each volume, always available
    # not expired => prepub
    available_parts_to_download = list(
        filter(
            lambda p: p.raw_part.preview or not p.raw_part.expired, parts_to_download
        )
    )

    if len(available_parts_to_download) == 0:
        raise NoRequestedPartAvailableError(
            "None of the requested parts are available for reading"
        )

    if len(available_parts_to_download) != len(parts_to_download):
        logger.warning("Some of the requested parts are not available for reading !")

    if epub_generation_options.is_by_volume:
        for _, g in itertools.groupby(
            available_parts_to_download, lambda p: p.volume.volume_id
        ):
            parts = list(g)
            core.create_epub(token, series, parts, epub_generation_options)
    else:
        core.create_epub(
            token, series, available_parts_to_download, epub_generation_options
        )


if __name__ == "__main__":
    main()
