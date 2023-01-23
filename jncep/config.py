from collections import defaultdict
from configparser import ConfigParser
from pathlib import Path

from addict import Dict as Addict
from appdirs import user_config_dir

LEGACY_CONFIG_DIR = Path.home() / ".jncep"
# appdata on Windows but will be somthing relevant to the platform for other OS's
APPDATA_CONFIG_DIR = Path(user_config_dir("jncep", roaming=True))

CONFIG_FILE_NAME = "config.ini"


TOP_SECTION = "JNCEP"
# TODO Get options automatically from click
# or define them here and reuse in CLI options
OPTIONS = Addict(
    {
        "LOGIN_OPTION": "LOGIN",
        "PASSWORD_OPTION": "PASSWORD",
        "OUTPUT_DIR_OPTION": "OUTPUT",
    }
)


def config_dir():
    if APPDATA_CONFIG_DIR.exists():
        # default if exists
        return APPDATA_CONFIG_DIR
    elif LEGACY_CONFIG_DIR.exists():
        return LEGACY_CONFIG_DIR
    # none exists => will be created
    return APPDATA_CONFIG_DIR


DEFAULT_CONFIG_FILEPATH = config_dir() / CONFIG_FILE_NAME


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
        parser = JNCEPConfigParser()
        try:
            parser.read(self.config_file_path, encoding="utf-8")
            return parser.as_dict()
        except FileNotFoundError:
            # TODO verif error class
            # first run ?
            return parser

    def write_config_options(self, options):
        pass


class JNCEPConfigParser(ConfigParser):
    def __init__(self):
        super().__init__()
        self.optionxform = lambda x: x.upper()

    # TODO suppr ?
    def as_dict(self):
        dictionary = defaultdict(dict)
        for section in self.sections():
            for option in self.options(section):
                dictionary[section][option] = self.get(section, option)

        return Addict(dictionary)
