import itertools
import os
import sys
import traceback

import click
import dateutil.parser
from termcolor import colored

from . import core, DEBUG, jncapi

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


@click.group()
def cli():
    pass


@cli.command(name="epub", help="Generate EPUB files for J-Novel Club pre-pub novels")
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
    is_not_replace_chars,
):
    slug = jncapi.slug_from_url(jnc_url)

    print(f"Login with email '{email}'...")
    token = jncapi.login(email, password)

    print(f"Fetching metadata for '{slug[0]}'...")
    metadata = jncapi.fetch_metadata(token, slug)

    novel = core.analyze_novel_metadata(slug[1], metadata)
    if part_specs:
        print(
            f"Using part specification '{part_specs}' "
            f"(absolute={_to_yn(is_absolute)})..."
        )
        parts_to_download = core.analyze_part_specs(novel, part_specs, is_absolute)
    else:
        parts_to_download = core.analyze_requested(novel)

    _create_epub_with_requested_parts(
        token,
        novel,
        parts_to_download,
        is_by_volume,
        output_dirpath,
        is_extract_images,
        is_not_replace_chars,
    )

    print("Logout...")
    jncapi.logout(token)


@cli.group(name="track", help="Track updates to a series")
def track_series():
    pass


@track_series.command(name="add", help="Add a new series for tracking")
@click.argument("jnc_url", metavar="JNOVEL_CLUB_URL", required=True)
@login_option
@password_option
def add_track_series(jnc_url, email, password):
    novel, series_url = _canonical_series(jnc_url, email, password)
    tracked_series = core.read_tracked_series()

    if series_url in tracked_series:
        print(
            colored(
                f"The series '{novel.raw_serie.title}' is already tracked!", "yellow",
            )
        )
        return

    # record current last part + name
    if len(novel.parts) == 0:
        # no parts yet
        pn = 0
        # 0000-... not a valid date so 1111-...
        pdate = "1111-11-11T11:11:11.111Z"
    else:
        pn = core.to_relative_part_string(novel, novel.parts[-1])
        pdate = novel.parts[-1].raw_part.launchDate

    tracked_series[series_url] = {
        "part_date": pdate,
        "part": pn,  # now just for show
        "name": novel.raw_serie.title,
    }
    core.write_tracked_series(tracked_series)

    if len(novel.parts) == 0:
        print(
            colored(
                f"The series '{novel.raw_serie.title}' is now tracked, starting "
                f"from the beginning",
                "green",
            )
        )
    else:
        relative_part = core.to_relative_part_string(novel, novel.parts[-1])
        part_date = dateutil.parser.parse(novel.parts[-1].raw_part.launchDate)
        part_date_formatted = part_date.strftime("%b %d, %Y")
        print(
            colored(
                f"The series '{novel.raw_serie.title}' is now tracked, starting "
                f"after part {relative_part} [{part_date_formatted}]",
                "green",
            )
        )


@track_series.command(name="rm", help="Remove a series from tracking")
@click.argument("jnc_url", metavar="JNOVEL_CLUB_URL", required=True)
@login_option
@password_option
def remove_track_series(jnc_url, email, password):
    novel, series_url = _canonical_series(jnc_url, email, password)
    tracked_series = core.read_tracked_series()

    if series_url not in tracked_series:
        print(
            colored(f"The series '{novel.raw_serie.title}' is not tracked!", "yellow")
        )
        return

    del tracked_series[series_url]

    core.write_tracked_series(tracked_series)

    print(
        colored(f"The series '{novel.raw_serie.title}' is no longer tracked", "green")
    )


@track_series.command(name="list", help="List tracked series")
def list_track_series():
    tracked_series = core.read_tracked_series()
    if len(tracked_series) > 0:
        print(f"{len(tracked_series)} series are tracked:")
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

            print(f"'{ser_details.name}' ({ser_url}): {details}")
    else:
        print(f"No series is tracked.")


def _canonical_series(jnc_url, email, password):
    slug = jncapi.slug_from_url(jnc_url)

    print(f"Login with email '{email}'...")
    token = jncapi.login(email, password)

    print(f"Fetching metadata for '{slug[0]}'...")
    metadata = jncapi.fetch_metadata(token, slug)

    print("Logout...")
    jncapi.logout(token)

    novel = core.analyze_novel_metadata(slug[1], metadata)
    series_slug = novel.raw_serie.titleslug
    series_url = jncapi.url_from_series_slug(series_slug)

    return novel, series_url


@cli.command(
    name="update",
    help="Generate EPUB files for new parts of all tracked series (or specific "
    "series if a URL argument is passed)",
)
@click.argument("jnc_url", metavar="(JNOVEL_CLUB_URL?)", required=False)
@login_option
@password_option
@output_option
@byvolume_option
@images_option
@no_replace_chars_option
def update_tracked(  # noqa: C901
    jnc_url,
    email,
    password,
    output_dirpath,
    is_by_volume,
    is_extract_images,
    is_not_replace_chars,
):

    tracked_series = core.read_tracked_series()
    if len(tracked_series) == 0:
        print(
            colored(
                "There are no tracked series! Use the 'jncep track add' command first.",
                "yellow",
            )
        )
        return

    print(f"Login with email '{email}'...")
    token = jncapi.login(email, password)

    updated_series = []
    has_error = False
    if jnc_url:
        slug = jncapi.slug_from_url(jnc_url)

        print(f"Fetching metadata for '{slug[0]}'...")
        metadata = jncapi.fetch_metadata(token, slug)

        novel = core.analyze_novel_metadata(slug[1], metadata)
        series_slug = novel.raw_serie.titleslug
        series_url = jncapi.url_from_series_slug(series_slug)

        if series_url not in tracked_series:
            print(
                colored(
                    f"The series '{novel.raw_serie.title}' is not tracked! "
                    f"Use the 'jncep track' command first.",
                    "yellow",
                )
            )
            return

        series_details = tracked_series[series_url]
        is_updated = _create_updated_epub(
            token,
            novel,
            series_details,
            is_by_volume,
            output_dirpath,
            is_extract_images,
            is_not_replace_chars,
        )

        if is_updated:
            print(
                colored(
                    f"The series '{novel.raw_serie.title}' has been updated!", "green"
                )
            )
            updated_series.append(novel)
    else:
        for series_url, series_details in tracked_series.items():
            try:
                slug = jncapi.slug_from_url(series_url)

                print(f"Fetching metadata for '{slug[0]}'...")
                metadata = jncapi.fetch_metadata(token, slug)
                novel = core.analyze_novel_metadata(slug[1], metadata)

                is_updated = _create_updated_epub(
                    token,
                    novel,
                    series_details,
                    is_by_volume,
                    output_dirpath,
                    is_extract_images,
                    is_not_replace_chars,
                )
                if is_updated:
                    print(
                        colored(
                            f"The series '{novel.raw_serie.title}' has been updated!",
                            f"green",
                        )
                    )
                    updated_series.append(novel)
            except Exception as ex:
                has_error = True
                print(colored("An error occured while updating the series:", "red"))
                print(colored(str(ex), "red"))
                if DEBUG:
                    traceback.print_exc()

    print("Logout...")
    jncapi.logout(token)

    if has_error:
        # only for multiple updates ; when url passed and error => goes directly
        # to fatal error
        print(colored("Some series could not be updated!", "red"))

    if len(updated_series) > 0:
        # update tracking config JSON => to last part in series
        # TODO do that in the loop instead of the end ?
        for novel in updated_series:
            pn = core.to_relative_part_string(novel, novel.parts[-1])
            pdate = novel.parts[-1].raw_part.launchDate
            # write part + name in case old version with just the part number
            tracked_series[jncapi.url_from_series_slug(novel.raw_serie.titleslug)] = {
                "part_date": pdate,
                "part": pn,
                "name": novel.raw_serie.title,
            }
        core.write_tracked_series(tracked_series)

        print(colored(f"{len(updated_series)} series sucessfully updated!", "green"))
    else:
        print(colored(f"All series are already up to date!", "green"))


def _to_yn(b):
    return "yes" if b else "no"


def _create_updated_epub(
    token,
    novel,
    series_details,
    is_by_volume,
    output_dirpath,
    is_extract_images,
    is_not_replace_chars,
):
    if series_details.part == 0:
        # special processing : means there was no part available when the
        # series was started tracking

        # still no part ?
        if len(novel.parts) == 0:
            is_updated = False
            # just to bind or pylint complains
            first_new_part = 0
        else:
            is_updated = True
            # starting from the first part
            first_new_part = 1
    else:
        # for others, look at the date if there
        if not series_details.part_date:
            # if not => old format, first lookup date of last part and use that
            # TODO possible to do that for all ie no need to keep the date around
            last_part = core.to_part(novel, series_details.part)
            last_update_date = last_part.raw_part.launchDate
        else:
            last_update_date = series_details.part_date

        first_new_part = _first_part_released_after_date(novel, last_update_date)
        is_updated = first_new_part is not None

    if not is_updated:
        # no new part
        print(
            colored(
                f"The series '{novel.raw_serie.title}' has not been updated!", "yellow",
            )
        )
        return False

    # create string part specs starting from the part number of the first new part
    part_specs = f"{first_new_part}:"
    is_absolute = True
    parts_to_download = core.analyze_part_specs(novel, part_specs, is_absolute)

    # TODO create options object
    _create_epub_with_requested_parts(
        token,
        novel,
        parts_to_download,
        is_by_volume,
        output_dirpath,
        is_extract_images,
        is_not_replace_chars,
    )

    return True


def _first_part_released_after_date(novel, date):
    comparison_date = dateutil.parser.parse(date)
    for part in novel.parts:
        # all date strings are in ISO format
        # so no need to parse really
        # parsing just to be safe
        launch_date = dateutil.parser.parse(part.raw_part.launchDate)
        if launch_date > comparison_date:
            return part.absolute_num
    return None


def _create_epub_with_requested_parts(
    token,
    novel,
    parts_to_download,
    is_by_volume,
    output_dirpath,
    is_extract_images,
    is_not_replace_chars,
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
        print(
            colored(
                "Some of the requested parts are not available for reading !", "yellow"
            )
        )

    if is_by_volume:
        for _, g in itertools.groupby(
            available_parts_to_download, lambda p: p.volume.volume_id
        ):
            parts = list(g)
            core.create_epub(
                token,
                novel,
                parts,
                output_dirpath,
                is_extract_images,
                is_not_replace_chars,
            )
    else:
        core.create_epub(
            token,
            novel,
            available_parts_to_download,
            output_dirpath,
            is_extract_images,
            is_not_replace_chars,
        )


class NoRequestedPartAvailableError(Exception):
    def __init__(self, msg):
        super().__init__(msg)


def main():
    try:
        cli()
    except Exception as ex:
        print(colored("*** An unrecoverable error occured ***", "red"))
        print(colored(str(ex), "red"))
        if DEBUG:
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
