import logging
import sys
import traceback

import click

from .. import utils

console = utils.getConsole()

logger = logging.getLogger(__package__)


class CatchAllExceptionsCommand(click.Command):
    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except Exception as ex:
            raise UnrecoverableJNCEPError(str(ex), sys.exc_info())


class UnrecoverableJNCEPError(click.ClickException):
    def __init__(self, message, exc_info):
        super().__init__(message)
        self.exc_info = exc_info

    def show(self):
        console.stop_status()

        emoji = ""
        if console.is_advanced():
            emoji = "\u274C "
        console.error(f"*** {emoji}An unrecoverable error occured ***")
        console.error(self.message)

        logger.debug(" ".join(traceback.format_exception(*self.exc_info)))
