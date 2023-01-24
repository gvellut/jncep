from collections import defaultdict
from configparser import ConfigParser
from pathlib import Path

from addict import Dict as Addict
from appdirs import user_config_dir
from click import Context

LEGACY_CONFIG_DIR = Path.home() / ".jncep"
# appdata on Windows but will be somthing relevant to the platform for other OS's
APPDATA_CONFIG_DIR = Path(user_config_dir("jncep", roaming=True))


def config_dir():
    if APPDATA_CONFIG_DIR.exists():
        # default if exists
        return APPDATA_CONFIG_DIR
    elif LEGACY_CONFIG_DIR.exists():
        return LEGACY_CONFIG_DIR
    # none exists => will be created
    return APPDATA_CONFIG_DIR


CONFIG_FILE_NAME = "config.ini"

DEFAULT_CONFIG_FILEPATH = config_dir() / CONFIG_FILE_NAME

TOP_SECTION = "JNCEP"


# TODO error hierarchy with JNCEPError at the top
class InvalidOptionError(Exception):
    pass


def list_config_options():
    # to prevent import loops
    from .jncep import main

    with Context(main) as ctx:
        info = ctx.to_info_dict()
        envvars = []
        _extract_envvars(info, envvars)
        envvars = list(set(envvars))
        prefix = "JNCEP_"
        no_prefix_envvars = sorted(
            [ev[len(prefix) :] for ev in envvars if ev.startswith(prefix)]
        )
        return no_prefix_envvars


def _extract_envvars(info, acc):
    for k, v in info.items():
        if k == "envvar" and v is not None:
            acc.append(v)
        else:
            if isinstance(v, dict):
                _extract_envvars(v, acc)
            elif isinstance(v, list):
                for i in v:
                    if isinstance(i, dict):
                        _extract_envvars(i, acc)


def set_config_option(option, value):
    allowed_options = list_config_options()
    if option not in allowed_options:
        raise InvalidOptionError(
            f"Option '{option}' is not valid. Valid options are: "
            f"{', '.joint(allowed_options)}"
        )

    config_manager = ConfigManager(DEFAULT_CONFIG_FILEPATH)
    config = config_manager.read_config_options()
    config[TOP_SECTION][option] = value
    config_manager.write_config_options(config)


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
        try:
            config.read(self.config_file_path, encoding="utf-8")
        except FileNotFoundError:
            # TODO verif error class
            # first run ? just return the parser (which will be empty)
            pass
        return config

    def write_config_options(self, config):
        with open(self.config_file_path, "w", encoding="utf-8") as f:
            config.write(f)


class JNCEPConfigParser(ConfigParser):
    def __init__(self):
        # TOP_SECTION will be automatically created
        super().__init__(default_section=TOP_SECTION)
        self.optionxform = lambda x: x.upper()

    # TODO suppr ?
    def as_dict(self):
        dictionary = defaultdict(dict)
        for section in self.sections():
            for option in self.options(section):
                dictionary[section][option] = self.get(section, option)

        return Addict(dictionary)
