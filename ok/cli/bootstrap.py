"""Runtime setup shared by ok-cli entry points."""

import logging
import os
import sys


class _StreamFilter:
    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        value = str(text)
        if any(token in value for token in ("QFluentWidgets Pro", "qfluentwidgets.com", "Tips:")):
            return
        self._stream.write(text)

    def flush(self):
        self._stream.flush()

    def isatty(self):
        return self._stream.isatty()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def prepare_cli_environment():
    """Apply CLI-specific logging and output noise filters once."""
    if os.environ.get("OK_CLI_BOOTSTRAPPED") == "1":
        return

    os.environ["OK_CLI_BOOTSTRAPPED"] = "1"
    os.environ["DISABLE_QFluentWidgets_TIPS"] = "1"

    sys.stdout = _StreamFilter(sys.__stdout__)
    sys.stderr = _StreamFilter(sys.__stderr__)

    logging.disable(logging.CRITICAL)

    import logging.handlers as logging_handlers

    original_emit = logging_handlers.TimedRotatingFileHandler.emit

    def safe_emit(self, record):
        try:
            if self.stream and not self.stream.closed:
                original_emit(self, record)
        except (IOError, OSError, PermissionError):
            pass

    logging_handlers.TimedRotatingFileHandler.emit = safe_emit
