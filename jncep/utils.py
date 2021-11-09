import logging
import sys

from colorama import Fore

# specify colors for different logging levels
LOG_COLORS = {
    logging.ERROR: Fore.RED,
    logging.WARNING: Fore.YELLOW,
    logging.DEBUG: Fore.CYAN,
}


class ColorFormatter(logging.Formatter):
    def format(self, record, *args, **kwargs):
        if record.levelno in LOG_COLORS:
            record.msg = colored(record.msg, LOG_COLORS[record.levelno])
        return super().format(record, *args, **kwargs)


def setup_logging(is_debug, package=__package__):
    logger = logging.getLogger(package)
    if is_debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = ColorFormatter("%(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def colored(s, color):
    return f"{color}{s}{Fore.RESET}"


def green(msg):
    return colored(msg, Fore.GREEN)


def tryint(val):
    try:
        return int(val)
    except Exception:
        return None
