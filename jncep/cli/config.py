import click

from .. import config, track, utils
from .base import CatchAllExceptionsCommand

console = utils.getConsole()


@click.group(name="config", help="Manage configuration")
def config_manage():
    pass


@config_manage.command(
    name="show", help="List configuration details", cls=CatchAllExceptionsCommand
)
# TODO option to hide / show option values ?
def config_list():
    config_dir = config.config_dir()
    if not config_dir.exists():
        console.warning("No suitable configuration directory found!")
        console.info(f"The recommanded location is: [highlight]{config_dir}[/]")
        return

    if not config_dir.is_dir:
        console.warning(f"not a directory: [highlight]{config_dir}[/]")

    console.info(f"Config directory: [highlight]{config_dir}[/]")
    files = list(config_dir.iterdir())
    for f_ in files:
        # no subdirectory
        if f_.is_file():
            if f_.name == track.TRACK_FILE_NAME:
                console.info(f"Found tracking file: [highlight]{f_.name}[/]")
                _track_file_summary(f_)
                continue
            if f_.name == config.CONFIG_FILE_NAME:
                console.info(f"Found config file: [highlight]{f_.name}[/]")
                _config_file_summary(f_)
                continue
        # ignore everything else


def _track_file_summary(file_path):
    track_config_manager = track.TrackConfigManager(file_path)
    tracked_series = track_config_manager.read_tracked_series()
    len_ts = len(tracked_series)
    console.info(f"{len_ts} series tracked")


def _config_file_summary(file_path):
    config_manager = config.ConfigManager(file_path)
    config_options = config_manager.read_config_options()
    if config.TOP_SECTION not in config_options:
        console.warning("No [JNCEP] section")
        return
    jncep_s = config_options[config.TOP_SECTION]
    # ignorer other non listed in OPTIONS
    for option in config.OPTIONS.values():
        if option not in jncep_s:
            continue
        console.info(f"Option '[highlight]{option}[/]': {jncep_s[option]}")


@config_manage.command(
    name="migrate",
    help="Migrate to standard configuration folder",
    cls=CatchAllExceptionsCommand,
)
def config_migrate():
    console.info(f"Configuration will be migrated to {config.APPDATA_CONFIG_DIR}")
