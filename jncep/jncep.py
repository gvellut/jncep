import logging

import click

from . import __version__ as JNCEP_VERSION
from .cli.config import config_manage
from .cli.epub import generate_epub
from .cli.track import track_series
from .cli.update import update_tracked
from .config import apply_options_from_config, DEFAULT_CONFIG_FILEPATH
from .utils import getConsole, module_info, setup_logging

logger = logging.getLogger(module_info())

console = getConsole()


@click.group(
    help="Command-line tool to generate EPUB files for J-Novel Club pre-pub novels"
)
@click.version_option(JNCEP_VERSION, message="v%(version)s")
@click.option(
    "-d",
    "--debug",
    "is_debug",
    is_flag=True,
    help="Flag to activate debug mode",
    required=False,
)
def main(is_debug):
    setup_logging(is_debug)
    try:
        apply_options_from_config()
    except Exception:
        console.warning(
            "There was an error reading the configuration at: "
            f"{DEFAULT_CONFIG_FILEPATH}. Continuing..."
        )


main.add_command(generate_epub)
main.add_command(track_series)
main.add_command(update_tracked)
main.add_command(config_manage)

if __name__ == "__main__":
    main()
