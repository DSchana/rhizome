"""Autocomplete dropdown for slash commands."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from rhizome.tui.commands import COMMANDS


# Build the full command list (including quit which isn't in COMMANDS registry
# but is a valid TUI command).
_ALL_COMMANDS: list[tuple[str, str]] = sorted(
    [(cmd.name, cmd.description) for cmd in COMMANDS.values()],
    key=lambda c: c[0],
)


class CommandPalette(Widget):
    """Filtered dropdown list of slash commands."""

    DEFAULT_CSS = """
    CommandPalette {
        display: none;
        height: auto;
        max-height: 10;
        width: 100%;
        background: $surface;
        border-top: solid rgb(60, 60, 60);
    }
    CommandPalette.visible {
        display: block;
    }
    CommandPalette .cmd-row {
        height: 1;
        padding: 0 1;
    }
    CommandPalette .cmd-row.highlighted {
        background: $accent;
        color: $text;
    }
    """

    filter_text: reactive[str] = reactive("", layout=True)
    selected_index: reactive[int] = reactive(0)

    class CommandSelected(Message):
        """Posted when the user picks a command from the palette."""

        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name

    def _get_filtered(self) -> list[tuple[str, str]]:
        prefix = self.filter_text.lstrip("/")
        return [(n, d) for n, d in _ALL_COMMANDS if n.startswith(prefix)]

    def watch_filter_text(self) -> None:
        self.selected_index = 0
        self._rebuild()

    def watch_selected_index(self) -> None:
        self._update_highlight()

    def _rebuild(self) -> None:
        """Rebuild the list of command rows."""
        filtered = self._get_filtered()
        # Remove old rows
        for child in list(self.children):
            child.remove()
        if not filtered:
            return
        for i, (name, desc) in enumerate(filtered):
            row = Static(f"/{name}  — {desc}", classes="cmd-row")
            row.set_class(i == self.selected_index, "highlighted")
            self.mount(row)

    def _update_highlight(self) -> None:
        rows = list(self.query(".cmd-row"))
        for i, row in enumerate(rows):
            row.set_class(i == self.selected_index, "highlighted")

    def move_selection(self, delta: int) -> None:
        """Move the selection up or down by *delta* items."""
        filtered = self._get_filtered()
        if not filtered:
            return
        self.selected_index = (self.selected_index + delta) % len(filtered)

    def confirm_selection(self) -> str | None:
        """Post a CommandSelected message for the current selection. Returns the name or None."""
        filtered = self._get_filtered()
        if not filtered:
            return None
        idx = min(self.selected_index, len(filtered) - 1)
        name = filtered[idx][0]
        self.post_message(self.CommandSelected(name))
        return name

    @property
    def has_items(self) -> bool:
        return len(self._get_filtered()) > 0
