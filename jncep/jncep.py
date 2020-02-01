import itertools
import os
import traceback

import click
from termcolor import colored

from . import core, jncapi

DEBUG = False


@click.group()
def cli():
    pass


@cli.command(name="epub", help="Generate EPUB files for J-Novel Club pre-pub novels")
@click.argument("jnc_url", metavar="JNOVEL_CLUB_URL", required=True)
@click.option(
    "-l",
    "--email",
    required=True,
    envvar="JNCEP_EMAIL",
    help="Login email for J-Novel Club account",
)
@click.option(
    "-p",
    "--password",
    required=True,
    envvar="JNCEP_PASSWORD",
    help="Login password for J-Novel Club account",
)
@click.option(
    "-o",
    "--output",
    "output_dirpath",
    type=click.Path(exists=True, resolve_path=True, file_okay=False, writable=True),
    help="Existing folder to write the output [default: The current directory]",
)
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
@click.option(
    "-v",
    "--byvolume",
    "is_by_volume",
    is_flag=True,
    help=(
        "Flag to indicate that the parts of different volumes shoud be output in "
        "separate EPUBs"
    ),
)
@click.option(
    "-i",
    "--images",
    "is_extract_images",
    is_flag=True,
    help=(
        "Flag to indicate that the images of the novel should be extracted into "
        "the output folder"
    ),
)
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
@click.argument("url_or_slug", metavar="JNOVEL_CLUB_URL", required=True)
def track_series(jnc_url):
    pass


@cli.command(name="update", help="Generate EPUB files for new parts of tracked series")
def update_tracked():
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


if __name__ == "__main__":
    main()
