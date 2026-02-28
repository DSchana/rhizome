"""Logging pane widget — displays a rolling window of log messages."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import RichLog


class LoggingPane(Widget):
    """Displays log messages captured by the app's ``TUILogHandler``."""

    DEFAULT_CSS = """
    LoggingPane {
        height: 1fr;
        background: rgb(12, 12, 12);
    }
    LoggingPane #log-output {
        height: 1fr;
        background: rgb(12, 12, 12) !important;
        background-tint: initial !important;
    }
    """

    def compose(self) -> ComposeResult:
        yield RichLog(max_lines=2000, markup=True, wrap=True, auto_scroll=True, id="log-output")

    def on_mount(self) -> None:
        handler = getattr(self.app, "tui_log_handler", None)
        if handler is None:
            return
        rich_log = self.query_one("#log-output", RichLog)
        for line in handler.lines:
            rich_log.write(line)
        handler.register_pane(self)

    def on_unmount(self) -> None:
        handler = getattr(self.app, "tui_log_handler", None)
        if handler is not None:
            handler.unregister_pane(self)

    def write_line(self, line: str) -> None:
        """Called by TUILogHandler to write a new log line."""
        self.query_one("#log-output", RichLog).write(line)
