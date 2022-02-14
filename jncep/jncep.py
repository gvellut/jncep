import logging

import click

from .cli.epub import generate_epub
from .cli.track import track_series
from .cli.update import update_tracked
from .utils import module_info, setup_logging

logger = logging.getLogger(module_info())


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
