import logging

import click

from ..utils import setup_logging
from .epub import generate_epub
from .track import track_series
from .update import update_tracked

logger = logging.getLogger(__package__)


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


main.add_command(generate_epub)
main.add_command(track_series)
main.add_command(update_tracked)

if __name__ == "__main__":
    main()
