from pathlib import Path
import shutil

import click

from .. import config, namegen, track, utils
from .base import CatchAllExceptionsCommand

console = utils.getConsole()


@click.group(name="config", help="Manage configuration")
def config_manage():
    pass


@config_manage.command(
    name="show", help="List configuration details", cls=CatchAllExceptionsCommand
)
def config_list():
    config_dir = config.config_dir()
    if not config_dir.exists():
        console.warning("No configuration folder found!")
        console.info(f"The recommended location is: [highlight]{config_dir}[/]")
        return

    if not config_dir.is_dir:
        console.warning(f"Not a folder: [highlight]{config_dir}[/]")

    console.info(f"Configuration folder: [highlight]{config_dir}[/]")
    files = list(config_dir.iterdir())
    for f_ in files:
        if f_.is_file():
            if f_.name == track.TRACK_FILE_NAME:
                console.info(f"Found tracking file: [highlight]{f_.name}[/]")
                _track_file_summary(f_)
                continue
            if f_.name == config.CONFIG_FILE_NAME:
                console.info(f"Found config file: [highlight]{f_.name}[/]")
                _config_file_summary(f_)
                continue
            if f_.name == namegen.NAMEGEN_FILE_NAME:
                console.info(f"Found namegen file: [highlight]{f_.name}[/]")
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
    # TOP_SECTION is always there (default section)
    jncep_s = config_options[config.TOP_SECTION]
    if len(jncep_s) == 0:
        console.info("No option set")

    allowed_options = config.list_available_config_options()
    for option in jncep_s:
        # ignore others that are unknown to JNCEP
        if option not in allowed_options:
            continue
        console.info(f"Option: [highlight]{option}[/] => [green]{jncep_s[option]}[/]")


@config_manage.command(
    name="list", help="List configuration options", cls=CatchAllExceptionsCommand
)
def list_options():
    options = config.list_available_config_options()

    rows = [(f"[highlight]{o}[/]", h) for o, h in options.items()]

    # option column: adjust with max margin of 5
    max_len = 0
    for option in options:
        max_len = max(max_len, len(option))
    column_width = max_len + 5

    console.info_table(rows, maxcolwidths=(column_width, 40))


def _wrap(wrapper, text):
    return "\n".join(wrapper.wrap(text))


@config_manage.command(
    name="set", help="Set configuration option", cls=CatchAllExceptionsCommand
)
@click.argument("option", metavar="OPTION", required=True)
@click.argument("value", metavar="VALUE", required=True)
def set_option(option, value):
    config_manager = config.ConfigManager()
    config_options = config_manager.read_config_options()

    option = config.set_config_option(config_options, option, value)
    console.info(
        f"Option '[highlight]{option}[/]' set to '[highlight]{value}[/]'",
        style="success",
    )

    is_needs_created = not config_manager.config_file_path.exists()
    # if config file didn't exist, this will create it
    config_manager.write_config_options(config_options)
    if is_needs_created:
        # mention the creation to user
        console.info(
            f"Config file created at: [highlight]{config_manager.config_file_path}[/]"
        )


@config_manage.command(
    name="unset", help="Delete configuration option", cls=CatchAllExceptionsCommand
)
@click.argument("option", metavar="OPTION", required=True)
def unset_option(option):
    config_manager = config.ConfigManager()

    if not config_manager.config_file_path.exists():
        console.warning(
            f"No config file found at: [highlight]{config_manager.config_file_path}[/]"
        )
        return

    config_options = config_manager.read_config_options()

    option, is_deleted = config.unset_config_option(config_options, option)
    if not is_deleted:
        console.warning(f"Option '[highlight]{option}[/]' not set in config")
        return
    else:
        console.info(f"Option '[highlight]{option}[/]' unset", style="success")

    config_manager.write_config_options(config_options)


@config_manage.command(
    name="init", help="Create configuration file", cls=CatchAllExceptionsCommand
)
def init_config():
    config_filepath = config.DEFAULT_CONFIG_FILEPATH
    if config_filepath.exists():
        console.warning(f"Config file already exists: [highlight]{config_filepath}[/]")
        return

    config_manager = config.ConfigManager(config_filepath)
    # will create empty config file
    config_options = config_manager.read_config_options()
    config_manager.write_config_options(config_options)

    console.info(
        f"New empty config file created: [highlight]{config_filepath}[/]",
        style="success",
    )


NAMEGEN_PY_TEMPLATE = """\
from jncep import namegen_utils as ng


def to_title(series: ng.Series, volumes: list[ng.Volume], parts: list[ng.Part], fc: ng.FC) -> str:
    # Replace with your logic
    return ng.default_title(series, volumes, parts, fc)


def to_filename(
    title: str, series: ng.Series, volumes: list[ng.Volume], parts: list[ng.Part], fc: ng.FC
) -> str:
    # Replace with your logic
    return ng.default_filename(series, volumes, parts, fc)


def to_folder(series: ng.Series, volumes: list[ng.Volume], parts: list[ng.Part], fc: ng.FC) -> str:
    # Replace with your logic
    return ng.default_folder(series, volumes, parts, fc)

"""  # noqa: E501

DEFAULT_NAMEGEN_PY_FILENAME = "namegen.py"


@config_manage.command(
    name="namegen-py",
    help="Generate a template namegen.py file for custom EPUB naming.",
    cls=CatchAllExceptionsCommand,
)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(resolve_path=True),
    help="Path to generate the file. Can be a directory.",
)
@click.option(
    "-f",
    "--overwrite",
    "is_overwrite",
    is_flag=True,
    help="Overwrite the file if it already exists.",
)
def generate_namegen_py(output_path, is_overwrite):
    if output_path:
        path = Path(output_path)
        if path.is_dir():
            filepath = path / DEFAULT_NAMEGEN_PY_FILENAME
        else:
            if not path.parent.exists():
                raise Exception(f"Directory not found: {path.parent}")
                return
            filepath = path
    else:
        config_dir = config.config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        filepath = config_dir / DEFAULT_NAMEGEN_PY_FILENAME

    if filepath.exists() and not is_overwrite:
        raise Exception(
            f"File already exists: '[highlight]{filepath}[/]'. Use --overwrite to "
            "replace it."
        )
        return

    if filepath.exists() and is_overwrite:
        click.confirm(
            f"File '{filepath}' already exists. Do you want to overwrite it?",
            abort=True,
        )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(NAMEGEN_PY_TEMPLATE)

    console.info(f"Successfully generated '[highlight]{filepath}[/]'", style="success")


# FIXME remove ? stopped being useful in 2023
@config_manage.command(
    name="migrate",
    help=f"Migrate to standard configuration folder [{config.APPDATA_CONFIG_DIR}]",
    cls=CatchAllExceptionsCommand,
)
def config_migrate():
    if not config.has_config_dir():
        console.warning("No configuration folder found!")
        console.info(
            f"The recommended location is: [highlight]{config.APPDATA_CONFIG_DIR}[/]"
        )
        return

    current_config_dir = config.config_dir()
    if current_config_dir == config.APPDATA_CONFIG_DIR:
        console.warning(
            f"Configuration is already in: [highlight]{config.APPDATA_CONFIG_DIR}[/]"
        )
        return

    migrate_config_dir = config.APPDATA_CONFIG_DIR

    # configuration is in legacy_config_dir => migrate to appdir

    migrate_config_dir.mkdir(parents=True)

    files = [
        track.TRACK_FILE_NAME,
        config.CONFIG_FILE_NAME,
        namegen.NAMEGEN_FILE_NAME,
    ]
    for f_ in files:
        from_filepath = current_config_dir / f_
        if from_filepath.exists():
            to_filepath = migrate_config_dir / f_
            shutil.copy2(from_filepath, to_filepath)

    console.info(
        "[success]"
        f"The configuration is now in: [highlight]{migrate_config_dir}[/]"
        "[/]\n"
        f"You may delete: [highlight]{current_config_dir}[/]"
    )
