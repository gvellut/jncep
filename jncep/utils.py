import inspect
import logging
import re
import sys
import unicodedata

import rich.console
import rich.theme

logger = logging.getLogger(__name__)


def setup_logging(is_debug, package=__package__):
    if not logging.getLogger().handlers:
        # not needed if coloredlogs is used
        format = "%(asctime)s %(name)-12s %(levelname)-8s %(message)s"
        logging.basicConfig(stream=sys.stdout, level=logging.INFO, format=format)

    # coloredlogs changes the level of the handler
    logging.getLogger().handlers[0].setLevel(logging.NOTSET)

    logger = logging.getLogger(package)
    if is_debug:
        logger.setLevel(logging.DEBUG)
        # keep debug console (ie logging)
        # or issues mixing the print and the logs with Rich
    else:
        logger.setLevel(logging.INFO)
        getConsole().console = RichConsole()


def tryint(val):
    try:
        return int(val)
    except Exception:
        return None


def to_yn(b):
    return "yes" if b else "no"


def to_safe_filename(name):
    name = "".join(
        c for c in unicodedata.normalize("NFD", name) if unicodedata.category(c) != "Mn"
    )
    safe = re.sub(r"[^0-9a-zA-Z_]+", "_", name)
    safe = safe.strip("_")
    return safe


def module_info():
    # for main module : its __name__ is __main__
    # so find out its real name
    frm = inspect.stack()[1]
    mod = inspect.getmodule(frm[0])
    return mod.__spec__.name


rich_theme = rich.theme.Theme(
    {
        "success": "bright_green",
        "warning": "bright_yellow",
        "error": "bright_red",
        "highlight": "white on red",
    }
)

# TODO use events instead ?


class RichConsole:
    def __init__(self):
        self.console = rich.console.Console(highlight=False, theme=rich_theme)
        self._status = None

    def info(self, *args, **kwargs):
        self.console.print(*args, **kwargs)

    def warning(self, *args, **kwargs):
        self.console.print(*args, **{"style": "warning", **kwargs})

    def error(self, *args, **kwargs):
        self.console.print(*args, **{"style": "error", **kwargs})

    def status(self, message, **kwargs_spinner_style):
        if not self._status:
            self._status = self.console.status(message, **kwargs_spinner_style)
            self._status.start()
        else:
            self._status.update(message, **kwargs_spinner_style)

    def stop_status(self):
        if self._status:
            self._status.stop()

    def log(self, *args, **kwargs):
        self.console.log(*args, **kwargs)


class DebugConsole:
    def __init__(self):
        pass

    def info(self, message, *args, **kwargs):
        logger.info(message)

    def warning(self, message, *args, **kwargs):
        logger.warning(message)

    def error(self, message, *args, **kwargs):
        logger.error(message)

    def status(self, message, **kwargs_spinner_style):
        logger.warning(message)

    def stop_status(self):
        pass

    def log(self, message, *args, **kwargs):
        logger.info(message)


class RootConsole:
    def __init__(self):
        # default
        self.console = DebugConsole()

    def info(self, message, *args, **kwargs):
        self.console.info(message, *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        self.console.warning(message, *args, **kwargs)

    def error(self, message, *args, **kwargs):
        self.console.error(message, *args, **kwargs)

    def status(self, message, **kwargs_spinner_style):
        self.console.status(message, **kwargs_spinner_style)

    def stop_status(self):
        self.console.stop_status()

    def log(self, message, *args, **kwargs):
        self.console.log(message, *args, **kwargs)


ROOT_CONSOLE = RootConsole()


def getConsole():
    return ROOT_CONSOLE
