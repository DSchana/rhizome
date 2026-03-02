"""Logging pane widget — displays a rolling window of log messages."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import RichLog, Static


class LogsStatusBar(Static):
    """Static hint bar displayed at the bottom of the logs pane."""

    DEFAULT_CSS = """
    LogsStatusBar {
        height: 3;
        dock: bottom;
        background: rgb(12, 12, 12);
        color: rgb(100, 100, 100);
        padding: 0 1;
        border-top: solid rgb(60, 60, 60);
    }
    """

    def render(self):
        return "ctrl+g to open in editor"


class LoggingPane(Widget):
    """Displays log messages captured by the app's ``TUILogHandler``."""

    BINDINGS = [
        Binding("ctrl+g", "open_logs_in_editor", "Open logs in editor", show=False, priority=True),
    ]

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
        yield LogsStatusBar()

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

    def action_open_logs_in_editor(self) -> None:
        """Dump current log buffer to a temp file and open it in $EDITOR."""
        handler = getattr(self.app, "tui_log_handler", None)
        if handler is None or not handler.lines:
            return

        _markup_re = re.compile(r"\[/?[^\]]*\]")
        plain_lines = [_markup_re.sub("", line) for line in handler.lines]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", prefix="rhizome-logs-", delete=False
        ) as tmp:
            tmp.write("\n".join(plain_lines) + "\n")
            tmp_path = tmp.name

        editor = os.environ.get("EDITOR", "nano")
        try:
            with self.app.suspend():
                subprocess.run([editor, tmp_path])
        finally:
            os.unlink(tmp_path)
