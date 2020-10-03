import itertools
import os
import sys
import traceback

import click
from termcolor import colored

from . import core, jncapi

DEBUG = False


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

    _create_epub_with_parts(
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
    novel, series_url, series_slug = _canonical_series(jnc_url, email, password)
    tracked_series = core.read_tracked_series()

    # keep compatibility for now
    # TODO remove compat for 1.0
    if series_slug in tracked_series or series_url in tracked_series:
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
    else:
        pn = core.to_relative_part_string(novel, novel.parts[-1])
    tracked_series[series_url] = {"part": pn, "name": novel.raw_serie.title}
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
        print(
            colored(
                f"The series '{novel.raw_serie.title}' is now tracked, starting "
                f"after part {relative_part}",
                "green",
            )
        )


@track_series.command(name="rm", help="Remove a series from tracking")
@click.argument("jnc_url", metavar="JNOVEL_CLUB_URL", required=True)
@login_option
@password_option
def remove_track_series(jnc_url, email, password):
    novel, series_url, series_slug = _canonical_series(jnc_url, email, password)
    tracked_series = core.read_tracked_series()

    if series_slug not in tracked_series and series_url not in tracked_series:
        print(
            colored(f"The series '{novel.raw_serie.title}' is not tracked!", "yellow")
        )
        return

    # try both old and new form
    try:
        del tracked_series[series_slug]
    except Exception:
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
            if isinstance(ser_details, dict):
                print(f"'{ser_details.name}' ({ser_url}): {ser_details.part}")
            else:
                # keep compat with old version for now
                print(f"'{ser_url}': {ser_details}")
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
    # series slug for the compat with old format
    series_slug = novel.raw_serie.titleslug
    series_url = jncapi.url_from_slug(series_slug)

    return novel, series_url, series_slug


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
    if jnc_url:
        slug = jncapi.slug_from_url(jnc_url)

        print(f"Fetching metadata for '{slug[0]}'...")
        metadata = jncapi.fetch_metadata(token, slug)

        novel = core.analyze_novel_metadata(slug[1], metadata)
        series_slug = novel.raw_serie.titleslug
        series_url = jncapi.url_from_slug(series_slug)

        if series_slug not in tracked_series and series_url not in tracked_series:
            print(
                colored(
                    f"The series '{novel.raw_serie.title}' is not tracked! "
                    f"Use the 'jncep track' command first.",
                    "yellow",
                )
            )
            return

        # TODO merge with case no URL
        if series_slug in tracked_series:
            series_details = tracked_series[series_slug]
        else:
            series_details = tracked_series[series_url]
        # keep compatibility for now
        if isinstance(series_details, dict):
            # special processing : cond means there was no part available when the
            # series was started tracking
            if series_details.part == 0:
                last_pn = 0
            else:
                last_pn = core.to_part(novel, series_details.part).absolute_num
        else:
            last_pn = series_details

        is_updated = _create_updated_epub(
            token,
            novel,
            last_pn,
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
        # keep compatibility
        has_error = False
        for series_slug_or_url, series_details in tracked_series.items():
            try:
                # see track command: always record the Novel URL
                try:
                    slug = jncapi.slug_from_url(series_slug_or_url)
                except Exception:
                    # not a URL. It is probably a slug from an older version
                    slug = (series_slug_or_url, "NOVEL")
                print(f"Fetching metadata for '{slug[0]}'...")
                metadata = jncapi.fetch_metadata(token, slug)
                novel = core.analyze_novel_metadata(slug[1], metadata)

                # keep compatibility for now
                if isinstance(series_details, dict):
                    if series_details.part == 0:
                        last_pn = 0
                    else:
                        last_pn = core.to_part(novel, series_details.part).absolute_num
                else:
                    last_pn = series_details

                is_updated = _create_updated_epub(
                    token,
                    novel,
                    last_pn,
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
        print(colored("Some series could not be updated!", "red"))

    if len(updated_series) > 0:
        # update tracking config JSON => to last part in series
        # TODO do that in the loop instead of the end ?
        for novel in updated_series:
            pn = core.to_relative_part_string(novel, novel.parts[-1])
            # write part + name in case old version with just the part number
            tracked_series[jncapi.url_from_slug(novel.raw_serie.titleslug)] = {
                "part": pn,
                "name": novel.raw_serie.title,
            }
            # wipeout old format if exists
            # TODO do that for all ?
            try:
                del tracked_series[novel.raw_serie.titleslug]
            except Exception:
                pass
        core.write_tracked_series(tracked_series)

        print(colored(f"{len(updated_series)} series sucessfully updated!", "green"))
    else:
        print(colored(f"All series are already up to date!", "green"))


def _to_yn(b):
    return "yes" if b else "no"


def _create_updated_epub(
    token,
    novel,
    last_pn,
    is_by_volume,
    output_dirpath,
    is_extract_images,
    is_not_replace_chars,
):
    if len(novel.parts) == 0 or novel.parts[-1].absolute_num <= last_pn:
        # no new part
        print(
            colored(
                f"The series '{novel.raw_serie.title}' has not been updated!", "yellow",
            )
        )
        return False

    # create string part specs based on the next abs part number
    part_specs = f"{last_pn + 1}:"
    is_absolute = True
    parts_to_download = core.analyze_part_specs(novel, part_specs, is_absolute)

    # TODO create options object
    _create_epub_with_parts(
        token,
        novel,
        parts_to_download,
        is_by_volume,
        output_dirpath,
        is_extract_images,
        is_not_replace_chars,
    )

    return True


def _create_epub_with_parts(
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
