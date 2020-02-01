import itertools
import os
import sys
import traceback

import click
from termcolor import colored

from . import core, jncapi

DEBUG = True


def login_option(f):
    return click.option(
        "-l",
        "--email",
        required=True,
        envvar="JNCEP_EMAIL",
        help="Login email for J-Novel Club account",
    )(f)


def password_option(f):
    return click.option(
        "-p",
        "--password",
        required=True,
        envvar="JNCEP_PASSWORD",
        help="Login password for J-Novel Club account",
    )(f)


def output_option(f):
    return click.option(
        "-o",
        "--output",
        "output_dirpath",
        type=click.Path(exists=True, resolve_path=True, file_okay=False, writable=True),
        help="Existing folder to write the output [default: The current directory]",
    )(f)


def byvolume_option(f):
    return click.option(
        "-v",
        "--byvolume",
        "is_by_volume",
        is_flag=True,
        help=(
            "Flag to indicate that the parts of different volumes shoud be output in "
            "separate EPUBs"
        ),
    )(f)


def images_option(f):
    return click.option(
        "-i",
        "--images",
        "is_extract_images",
        is_flag=True,
        help=(
            "Flag to indicate that the images of the novel should be extracted into "
            "the output folder"
        ),
    )(f)


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
def generate_epub(
    jnc_url,
    email,
    password,
    part_specs=None,
    is_absolute=False,
    output_dirpath=None,
    is_by_volume=False,
    is_extract_images=False,
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

    if not output_dirpath:
        output_dirpath = os.getcwd()

    if is_by_volume:
        for _, g in itertools.groupby(
            available_parts_to_download, lambda p: p.volume.volume_id
        ):
            parts = list(g)
            core.create_epub(token, novel, parts, output_dirpath, is_extract_images)
    else:
        core.create_epub(
            token, novel, available_parts_to_download, output_dirpath, is_extract_images
        )


@cli.command(name="track", help="Track updates to a series")
@click.argument("jnc_url", metavar="JNOVEL_CLUB_URL", required=True)
@login_option
@password_option
@click.option(
    "--rm",
    "is_rm",
    is_flag=True,
    help="Flag to indicate that the argument URL should be untracked",
)
def track_series(jnc_url, email, password, is_rm):
    slug = jncapi.slug_from_url(jnc_url)

    print(f"Login with email '{email}'...")
    token = jncapi.login(email, password)

    print(f"Fetching metadata for '{slug[0]}'...")
    metadata = jncapi.fetch_metadata(token, slug)

    novel = core.analyze_novel_metadata(slug[1], metadata)
    # standardize on the series slug for the config (even though URLs
    # for volumes or parts are accepted)
    titleslug = novel.raw_serie.titleslug

    tracked_series = core.read_tracked_series()

    if not is_rm:
        if titleslug in tracked_series:
            print(
                colored(
                    f"The series '{novel.raw_serie.title}'' is already tracked!",
                    "yellow",
                )
            )
            return

        # record current last part
        pn = novel.parts[-1].raw_part.partNumber
        tracked_series[titleslug] = pn
        core.write_tracked_series(tracked_series)

        relative_part = core.to_relative_part_string(novel, novel.parts[-1])
        print(
            colored(
                f"The series '{novel.raw_serie.title}' is now tracked, starting after "
                f"part {relative_part}",
                "green",
            )
        )
    else:
        if titleslug not in tracked_series:
            print(
                colored(
                    f"The series '{novel.raw_serie.title}' is not tracked!", "yellow"
                )
            )
            return

        del tracked_series[titleslug]
        core.write_tracked_series(tracked_series)

        print(
            colored(
                f"The series '{novel.raw_serie.title}' is no longer tracked", "green"
            )
        )


@cli.command(name="update", help="Generate EPUB files for new parts of tracked series")
@click.argument("jnc_url", metavar="JNOVEL_CLUB_URL")
def update_tracked(jnc_url):
    pass


def _to_yn(b):
    return "yes" if b else "no"


class NoRequestedPartAvailableError(Exception):
    def __init__(self, msg):
        super().__init__(self, msg)


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
