from __future__ import annotations

from enum import Enum, auto
import importlib.util
import logging
from pathlib import Path

from . import config, namegen_minilang as ngml
from .namegen_utils import _default_filename_from_title, default_folder, default_title
from .utils import getConsole

logger = logging.getLogger(__name__)
console = getConsole()

NAMEGEN_FILE_NAME = "namegen.py"


class InvalidNamegenPyError(Exception):
    pass


class NamegenMode(Enum):
    PY = auto()
    MINI_LANG = auto()


def _load_py(namegen_py_path):
    py_funcs = {}
    spec = importlib.util.spec_from_file_location("namegen_custom", namegen_py_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for func_name in ["to_title", "to_filename", "to_folder"]:
        if hasattr(module, func_name):
            py_funcs[func_name] = getattr(module, func_name)
            logger.debug(f"Found '{func_name}' function in namegen file.")
        else:
            logger.debug(f"'{func_name}' function not found, will use default.")
    return py_funcs


# special value : for testing (so force default : not taken from config)
# FIXME instead be able to define a path to alternate config (and make it empty for
# tests)
DEFAULT_NAMEGEN_SPECIAL_VALUE = "default"


class NameGenerator:
    def __init__(self, namegen_option: str | None):
        self._mode = None
        self._py_funcs = {}
        self._parsed_rules = None
        self._process_option(namegen_option)

    def _process_option(self, namegen_option: str | None):
        if namegen_option:
            if namegen_option.endswith(".py"):
                # use that simple criteria to distinguish between modes
                path = Path(namegen_option)
                if not path.exists():
                    raise InvalidNamegenPyError(f"File not found: {namegen_option}")
                namegen_py_path = path
                self._mode = NamegenMode.PY
                logger.debug(f"Using namegen file from option: {namegen_py_path}")
                self._py_funcs = _load_py(namegen_py_path)
            elif namegen_option.lower() != DEFAULT_NAMEGEN_SPECIAL_VALUE:
                self._mode = NamegenMode.MINI_LANG
                logger.debug("Using namegen rule string from option.")
                self._parsed_rules = ngml.parse_namegen_rules(namegen_option)
        else:
            config_namegen_py = config.config_dir() / NAMEGEN_FILE_NAME
            if config_namegen_py.exists():
                namegen_py_path = config_namegen_py
                self._mode = NamegenMode.PY
                logger.debug(
                    f"Using namegen file from config directory: {namegen_py_path}"
                )
                self._py_funcs = _load_py(namegen_py_path)

        if not self._mode:
            # nothing passed
            logger.debug("Using default rules.")
            self._mode = NamegenMode.PY
            self._py_funcs = {}

    def generate(self, series, volumes, parts, fc):
        if self._mode == NamegenMode.PY:
            args = (series, volumes, parts, fc)

            title_func = self._py_funcs.get("to_title", default_title)
            title = title_func(*args)

            if "to_filename" in self._py_funcs:
                filename = self._py_funcs["to_filename"](title, *args)
            else:
                # so we don't regenerate the title again
                filename = _default_filename_from_title(title)

            folder_func = self._py_funcs.get("to_folder", default_folder)
            folder = folder_func(*args)

            return title, filename, folder
        else:
            return ngml.generate_names(series, volumes, parts, fc, self._parsed_rules)
