import logging

from rich.console import Console
from rich.highlighter import JSONHighlighter
from rich.logging import RichHandler
from rich.theme import Theme

class RichLogger:

    SUBPROC = 25  # Between INFO (20) and WARNING (30)

    def __init__(self, name):
        self.logger = logging.getLogger(name)        
        console = Console(
            stderr=True, theme=Theme({"logging.level.subproc": "bold blue"})
        )

        logging.basicConfig(
            level=logging.NOTSET,
            format="%(name)s: %(message)s",  # Include logger name in messages
            datefmt="[%X]",
            handlers=[RichHandler(console=console)],
        )
        self.logger = logging.getLogger(name)
        logging.addLevelName(self.SUBPROC, "SUBPROC")

    def info(self, message):
        # message = self.format_numbers(message)
        self.logger.info(message)
        
    def debug(self, message):
        # message = self.format_numbers(message)
        self.logger.debug(message)
        

    def warn(self, message):
        # message = self.format_numbers(message)
        self.logger.warning(message)

    def subproc(self, message, *args, **kwargs):
        # message = self.format_numbers(message)
        if not message:  # Check if the message is empty
            message = "No errors reported"
        if self.logger.isEnabledFor(self.SUBPROC):
            self.logger._log(self.SUBPROC, message, args, **kwargs)