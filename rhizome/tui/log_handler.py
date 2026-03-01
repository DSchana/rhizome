"""Custom logging handler that bridges Python logging to the Textual UI."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import App

LEVEL_MARKUP = {
    logging.DEBUG: ("dim", "dim"),
    logging.INFO: ("blue", "bold blue"),
    logging.WARNING: ("yellow", "bold yellow"),
    logging.ERROR: ("red", "bold red"),
    logging.CRITICAL: ("red", "bold red reverse"),
}


class TUILogHandler(logging.Handler):
    """A logging handler that stores formatted Rich-markup lines and
    forwards them to any mounted ``LoggingPane`` widgets."""

    def __init__(self, maxlen: int = 2000) -> None:
        super().__init__()
        self.lines: deque[str] = deque(maxlen=maxlen)
        self._app: App | None = None
        self._panes: list = []  # list of LoggingPane references

    def set_app(self, app: App) -> None:
        self._app = app

    def register_pane(self, pane) -> None:
        """Register a LoggingPane so new log lines are written to it."""
        self._panes.append(pane)

    def unregister_pane(self, pane) -> None:
        """Remove a LoggingPane from the active set."""
        try:
            self._panes.remove(pane)
        except ValueError:
            pass

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self._format_rich(record)
            self.lines.append(line)
            if self._app is not None and self._panes:
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    # No event loop on this thread — schedule via Textual
                    self._app.call_from_thread(self._write_to_panes, line)
                else:
                    # Already on the event loop thread — call directly
                    self._write_to_panes(line)
        except Exception:
            self.handleError(record)

    def _write_to_panes(self, line: str) -> None:
        for pane in list(self._panes):
            pane.write_line(line)

    @staticmethod
    def _format_rich(record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")[:-3]
        color, level_style = LEVEL_MARKUP.get(record.levelno, ("white", "bold white"))
        level = record.levelname
        name = record.name
        msg = record.getMessage()
        return f"[dim]{ts}[/dim] [{level_style}]{level:<8}[/{level_style}] [dim]{name}[/dim] {msg}"
