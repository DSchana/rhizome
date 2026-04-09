"""Custom logging handler that bridges Python logging to the Textual UI."""

from __future__ import annotations

import logging
import traceback
from collections import deque
from datetime import datetime

from rich.markup import escape

LEVEL_MARKUP = {
    logging.DEBUG: ("dim", "dim"),
    logging.INFO: ("blue", "bold blue"),
    logging.WARNING: ("yellow", "bold yellow"),
    logging.ERROR: ("red", "bold red"),
    logging.CRITICAL: ("red", "bold red reverse"),
}


class TUILogHandler(logging.Handler):
    """A logging handler that stores formatted Rich-markup lines in a deque.

    This handler is storage-only — it does not write to any widgets directly.
    ``LoggingPane`` widgets pull new lines by polling ``total_count`` and
    reading from the ``lines`` deque.
    """

    def __init__(self, maxlen: int = 2000) -> None:
        super().__init__()
        self.lines: deque[str] = deque(maxlen=maxlen)
        self.total_count: int = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self._format_rich(record)
            self.lines.append(line)
            self.total_count += 1
        except Exception:
            self.handleError(record)

    @staticmethod
    def _format_rich(record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")[:-3]
        color, level_style = LEVEL_MARKUP.get(record.levelno, ("white", "bold white"))
        level = record.levelname
        name = record.name
        msg = escape(record.getMessage())
        if record.exc_info and record.exc_info[1] is not None:
            msg = f"{msg}\n{escape(''.join(traceback.format_exception(*record.exc_info)))}"
        if record.stack_info:
            msg = f"{msg}\n{escape(record.stack_info)}"
        return f"[dim]{ts}[/dim] [{level_style}]{level:<8}[/{level_style}] [dim]{name}[/dim] {msg}"
