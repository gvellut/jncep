from configparser import ConfigParser
from io import StringIO
import os
from pathlib import Path

from click import Context, get_app_dir

LEGACY_CONFIG_DIR = Path.home() / ".jncep"
# appdata on Windows but will be something relevant to the platform for other OS's
APPDATA_CONFIG_DIR = Path(get_app_dir("jncep", roaming=True))


def config_dir():
    if APPDATA_CONFIG_DIR.exists():
        # default if exists (if LEGACY_CONFIG_DIR is still there => will be ignored)
        return APPDATA_CONFIG_DIR
    elif LEGACY_CONFIG_DIR.exists():
        return LEGACY_CONFIG_DIR
    # none exists => will need to be created
    return APPDATA_CONFIG_DIR


def has_config_dir():
    return config_dir().exists()


CONFIG_FILE_NAME = "config.ini"

DEFAULT_CONFIG_FILEPATH = config_dir() / CONFIG_FILE_NAME

TOP_SECTION = "JNCEP"

# also used in the declarations for env var names to use for options
ENVVAR_PREFIX = "JNCEP_"


# TODO error hierarchy with JNCEPError at the top
class InvalidOptionError(Exception):
    pass


def list_available_config_options():
    # to prevent import loops
    from .jncep import main

    with Context(main) as ctx:
        info = ctx.to_info_dict()
        envvars = {}
        _extract_envvars(info, envvars)
        no_prefix_envvars = sorted(
            [
                (ev[len(ENVVAR_PREFIX) :], help_)
                for ev, help_ in envvars.items()
                if ev.startswith(ENVVAR_PREFIX)
            ],
            key=lambda x: x[0],
        )
        no_prefix_envvars = dict(no_prefix_envvars)
        return no_prefix_envvars


def _extract_envvars(info, acc):
    if "envvar" in info and info["envvar"]:
        acc[info["envvar"]] = info.get("help", "")
    else:
        for v in info.values():
            if isinstance(v, dict):
                _extract_envvars(v, acc)
            elif isinstance(v, list):
                for i in v:
                    if isinstance(i, dict):
                        _extract_envvars(i, acc)


def set_config_option(config, option, value):
    option = _validate_option(option)
    config[TOP_SECTION][option] = value
    # returns options since its case may have been modified
    return option


def unset_config_option(config, option):
    option = _validate_option(option)
    is_deleted = config.remove_option(None, option)
    return option, is_deleted


def _validate_option(option):
    # keys in upper case when writing
    option = option.upper()
    allowed_options = list_available_config_options().keys()
    if option not in allowed_options:
        raise InvalidOptionError(
            f"Option '{option}' is not valid. Valid options are: "
            f"{', '.join(allowed_options)}"
        )
    return option


def apply_options_from_config():
    # sets the envvar corresponding to the options in config file
    # needs to be launched before the main click command is launched
    # click will pick up the envvars, in the same way as if they were set outside
    config_manager = ConfigManager()
    config_options = config_manager.read_config_options()
    for option, value in config_options[TOP_SECTION].items():
        option_envvar = f"{ENVVAR_PREFIX}{option}"
        # priority to envvars set outside the config file
        # in that case, ignore the value in the config file
        if os.environ.get(option_envvar) is not None:
            continue
        os.environ[option_envvar] = value


class ConfigManager:
    def __init__(self, config_file_path=None):
        if not config_file_path:
            self.config_file_path = DEFAULT_CONFIG_FILEPATH
        else:
            if config_file_path is Path:
                self.config_file_path = config_file_path
            else:
                self.config_file_path = Path(config_file_path)

    def read_config_options(self):
        config = JNCEPConfigParser()
        if not self.config_file_path.exists():
            # first run ? just return the parser (which will be empty except for the
            # default section)
            return config

        with open(self.config_file_path, "r", encoding="utf-8") as f:
            # add a section transparently to conform to a .ini file
            # it is also the default section in the parser so will be
            # there even if
            config_string = f"[{TOP_SECTION}]\n" + f.read()
            config.read_string(config_string)
            return config

    def write_config_options(self, config):
        # make sure the folder exists
        self._ensure_config_dirpath_exists()

        buffer = StringIO()
        config.write(buffer)
        buffer.seek(0)
        config_str = buffer.read()
        # remove section
        config_str = config_str.replace(f"[{TOP_SECTION}]", "").lstrip()
        with open(self.config_file_path, "w", encoding="utf-8") as f:
            f.write(config_str)

    def _ensure_config_dirpath_exists(self):
        self.config_file_path.parent.mkdir(parents=True, exist_ok=True)


class JNCEPConfigParser(ConfigParser):
    def __init__(self):
        # TOP_SECTION will be automatically created if new file
        super().__init__(default_section=TOP_SECTION, interpolation=None)
        # keys in upper case when reading (instead of default lower)
        self.optionxform = lambda x: x.upper()
