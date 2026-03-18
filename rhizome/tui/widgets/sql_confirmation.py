"""SqlConfirmation — interrupt widget for confirming SQL modification statements.

Displays the SQL statement, a preview of affected rows in a scrollable
DataTable, and Approve/Deny options. Follows the same pattern as
``WarningChoices``: asyncio.Future for blocking, ``from_interrupt`` classmethod
factory, Up/Down/Enter navigation.
"""

from __future__ import annotations

import asyncio
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import DataTable, Static

from .interrupt import WidgetDeactivated

_NAV_HINT = "ctrl+\u2191/\u2193 to navigate"
_MAX_CELL_WIDTH = 40
_MAX_TABLE_HEIGHT = 14


def _truncate(value: Any, max_len: int = _MAX_CELL_WIDTH) -> str:
    """Stringify and truncate a cell value, collapsing newlines."""
    s = str(value).replace("\n", " ").replace("\r", "")
    if len(s) > max_len:
        return s[: max_len - 1] + "\u2026"
    return s


class SqlConfirmation(Widget, can_focus=True):
    """Displays a SQL modification confirmation with preview table.

    Navigation: Up/Down to move highlight, Enter to select.
    After selection the widget collapses to a single line showing the choice.
    """

    BINDINGS = [
        Binding("up", "cursor_up", "Move up", show=False),
        Binding("down", "cursor_down", "Move down", show=False),
        Binding("enter", "select", "Select", show=False),
    ]

    DEFAULT_CSS = """
    SqlConfirmation {
        height: auto;
        layout: vertical;
        padding: 0 2;
        margin: 1 0;
        border: solid rgb(40,40,40);
    }
    SqlConfirmation:hover {
        border: solid rgb(120,120,120);
    }
    SqlConfirmation:focus-within {
        border: solid rgb(86,126,160);
    }
    SqlConfirmation .sql-warning-header {
        color: rgb(220, 160, 50);
        margin-bottom: 1;
    }
    SqlConfirmation .sql-statement {
        background: rgb(40, 40, 50);
        padding: 1 2;
        margin-bottom: 1;
    }
    SqlConfirmation .sql-no-preview {
        color: rgb(150, 150, 150);
        margin-bottom: 1;
    }
    SqlConfirmation DataTable {
        height: auto;
        max-height: 14;
        margin-bottom: 1;
    }
    SqlConfirmation .sql-truncation-note {
        color: rgb(150, 150, 150);
        margin-bottom: 1;
    }
    """

    cursor: reactive[int] = reactive(0)

    def __init__(
        self,
        sql: str,
        preview_columns: list[str] | None = None,
        preview_rows: list[list] | None = None,
        row_count: int | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._sql = sql
        self._preview_columns = preview_columns or []
        self._preview_rows = preview_rows or []
        self._row_count = row_count
        self._options = ["Approve", "Deny"]
        self._future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        self._has_preview = bool(self._preview_columns)

    @classmethod
    def from_interrupt(cls, value: dict[str, Any]) -> SqlConfirmation:
        """Construct from an interrupt value dict."""
        preview = value.get("preview", {})
        return cls(
            sql=value.get("sql", ""),
            preview_columns=preview.get("columns", []),
            preview_rows=preview.get("rows", []),
            row_count=value.get("row_count"),
        )

    def _build_header(self) -> str:
        if self._row_count is not None:
            return f"SQL Modification \u2014 {self._row_count} row(s) affected"
        return "SQL Modification"

    def _build_truncation_note(self) -> str | None:
        if self._row_count is not None and self._row_count > len(self._preview_rows):
            return f"  \u2026 {self._row_count - len(self._preview_rows)} more row(s) not shown"
        return None

    def compose(self) -> ComposeResult:
        yield Static("\u26a0", classes="sql-warning-icon")
        yield Static(self._build_header(), classes="sql-warning-header")
        yield Static(self._sql, classes="sql-statement")

        if self._has_preview:
            table = DataTable(show_cursor=False, zebra_stripes=True, id="sql-preview-table")
            yield table
            note = self._build_truncation_note()
            if note:
                yield Static(note, classes="sql-truncation-note")
        else:
            yield Static("(no preview available)", classes="sql-no-preview")

        yield Static(id="sql-options")
        yield Static("  (ctrl+c to cancel)", id="sql-hint")

    def on_mount(self) -> None:
        if self._has_preview:
            table = self.query_one("#sql-preview-table", DataTable)
            for col in self._preview_columns:
                table.add_column(str(col))
            for row in self._preview_rows:
                table.add_row(*[_truncate(v) for v in row])

        self._render_options()
        self.query_one("#sql-hint", Static).styles.color = "rgb(100,100,100)"
        self.border_subtitle = _NAV_HINT
        self.focus()
        self.scroll_visible(animate=False)
        self.call_after_refresh(self._render_options)

    def watch_cursor(self) -> None:
        self._render_options()

    def on_focus(self) -> None:
        if not self._future.done():
            self.border_subtitle = None
            self._render_options()

    def on_blur(self) -> None:
        if not self._future.done():
            self.border_subtitle = _NAV_HINT
            self._render_options()

    def _render_options(self) -> None:
        focused = self.has_focus
        text = Text()
        for i, option in enumerate(self._options):
            if i > 0:
                text.append("\n")
            label = f"  {i + 1}. {option}"
            if not focused:
                text.append(label, style="rgb(100,100,100)")
            elif i == self.cursor:
                text.append(label, style="bold white")
            else:
                text.append(label, style="rgb(100,100,100)")
        self.query_one("#sql-options", Static).update(text)

    def action_cursor_up(self) -> None:
        if not self._future.done():
            self.cursor = (self.cursor - 1) % len(self._options)

    def action_cursor_down(self) -> None:
        if not self._future.done():
            self.cursor = (self.cursor + 1) % len(self._options)

    def action_select(self) -> None:
        if self._future.done():
            return
        selected = self._options[self.cursor]
        self._future.set_result(selected)
        self.border_subtitle = None
        self.post_message(WidgetDeactivated(self))
        # Collapse: hide everything except a brief confirmation line
        for cls_name in ("sql-warning-icon", "sql-warning-header", "sql-statement",
                         "sql-no-preview", "sql-truncation-note"):
            for widget in self.query(f".{cls_name}"):
                widget.display = False
        for table in self.query("#sql-preview-table"):
            table.display = False
        display = Text()
        display.append(f"  you selected: {selected}", style="rgb(100,100,100)")
        self.query_one("#sql-options", Static).update(display)
        self.query_one("#sql-hint", Static).update("")

    async def wait_for_selection(self) -> Any:
        """Block until the user selects an option. Returns the selected value."""
        return await self._future

    def cancel(self) -> None:
        """Cancel the pending future if not yet resolved."""
        if not self._future.done():
            self._future.cancel()
            self.border_subtitle = None
            self.post_message(WidgetDeactivated(self))
