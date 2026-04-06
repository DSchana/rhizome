"""NewResourceScreen — modal for creating a new resource."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from rhizome.db.models import LoadingPreference
from rhizome.tui.widgets.file_browser import FileBrowser


_DIM = "rgb(80,80,80)"
_CURSOR_COLOR = "rgb(255,80,80)"

_PREF_NAMES = {
    LoadingPreference.auto: "auto (recommended)",
    LoadingPreference.context_stuff: "context stuff",
    LoadingPreference.vector_store: "vector store",
}
_PREF_DESCS = {
    LoadingPreference.auto: "context-stuff if small, embed otherwise",
    LoadingPreference.context_stuff: "inject full text into conversation",
    LoadingPreference.vector_store: "embed for retrieval",
}
_PREF_LIST = [LoadingPreference.auto, LoadingPreference.context_stuff, LoadingPreference.vector_store]


class _Focus(enum.IntEnum):
    BROWSER = 0
    NAME = 1
    PREFERENCE = 2


@dataclass
class NewResourceResult:
    """Result returned by NewResourceScreen on confirmation."""
    path: Path
    name: str | None  # None means auto-generate via LLM
    loading_preference: LoadingPreference


class NewResourceScreen(ModalScreen[NewResourceResult | None]):
    """Modal for creating a new resource.

    All three sections (file browser, name input, loading preference) are
    visible at all times. Enter advances focus through them; selecting a
    preference confirms and dismisses. Escape moves focus back; ctrl+c
    exits entirely.
    """

    BINDINGS = [
        Binding("escape", "back", show=False),
        Binding("ctrl+c", "force_cancel", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    NewResourceScreen {
        align: center middle;
    }
    NewResourceScreen > Vertical {
        width: 80;
        height: auto;
        max-height: 80%;
        border: solid $surface-lighten-2;
        padding: 1 2;
        background: $surface;
    }
    NewResourceScreen #nr-header {
        height: 1;
        margin-bottom: 1;
    }
    NewResourceScreen #nr-title {
        text-style: bold;
        width: auto;
    }
    NewResourceScreen #nr-cancel-hint {
        color: rgb(80,80,80);
        content-align-horizontal: right;
        width: 1fr;
    }
    NewResourceScreen #nr-browser {
        border: solid $surface-lighten-2;
        padding: 0 1;
        margin-bottom: 1;
    }
    NewResourceScreen #nr-name-input {
        margin-bottom: 0;
    }
    NewResourceScreen #nr-name-hint {
        color: rgb(80,80,80);
        margin: 0 0 1 2;
        height: 1;
    }
    NewResourceScreen #nr-pref-list {
        height: auto;
        padding: 0 1;
    }
    """

    focus_section: reactive[_Focus] = reactive(_Focus.BROWSER)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._selected_path: Path | None = None
        self._pref_cursor: int = 0

    def compose(self):
        with Vertical():
            with Horizontal(id="nr-header"):
                yield Static("New Resource", id="nr-title")
                yield Static("ctrl+c to cancel", id="nr-cancel-hint")
            yield FileBrowser(id="nr-browser")
            yield Input(placeholder="Resource name", id="nr-name-input")
            yield Static("leave blank for auto", id="nr-name-hint")
            yield Static(id="nr-pref-list")

    def on_mount(self) -> None:
        self._render_pref_list()
        self._sync_focus()

    # ------------------------------------------------------------------
    # Focus management
    # ------------------------------------------------------------------

    def watch_focus_section(self) -> None:
        self._sync_focus()

    def _sync_focus(self) -> None:
        section = self.focus_section
        browser = self.query_one("#nr-browser", FileBrowser)

        if section == _Focus.BROWSER:
            browser.focus()
        elif section == _Focus.NAME:
            self.query_one("#nr-name-input", Input).focus()
            # Force browser to re-render without focus styling
            browser.call_after_refresh(browser._render_list)
        elif section == _Focus.PREFERENCE:
            # Focus the screen itself so on_key handles arrow/enter
            self.set_focus(None)

        self._render_pref_list()

    # ------------------------------------------------------------------
    # File browser
    # ------------------------------------------------------------------

    def on_file_browser_file_selected(self, event: FileBrowser.FileSelected) -> None:
        event.stop()
        self._selected_path = event.path
        name_input = self.query_one("#nr-name-input", Input)
        if not name_input.value.strip():
            name_input.value = event.path.stem
            name_input.cursor_position = len(name_input.value)
        self.focus_section = _Focus.NAME

    def on_file_browser_dismissed(self, event: FileBrowser.Dismissed) -> None:
        event.stop()
        self.dismiss(None)

    # ------------------------------------------------------------------
    # Name input
    # ------------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.focus_section = _Focus.PREFERENCE

    # ------------------------------------------------------------------
    # Loading preference
    # ------------------------------------------------------------------

    def _render_pref_list(self) -> None:
        active = self.focus_section == _Focus.PREFERENCE
        text = Text()
        for i, pref in enumerate(_PREF_LIST):
            if i > 0:
                text.append("\n")
            is_cursor = i == self._pref_cursor
            marker = "► " if is_cursor and active else "  "
            name = _PREF_NAMES[pref]
            desc = f" — {_PREF_DESCS[pref]}"
            if is_cursor and active:
                text.append(marker, style=f"bold {_CURSOR_COLOR}")
                text.append(name, style=f"bold {_CURSOR_COLOR}")
                text.append(desc, style=_CURSOR_COLOR)
            else:
                text.append(marker, style=_DIM)
                text.append(name, style=_DIM)
                text.append(desc, style=_DIM)
        self.query_one("#nr-pref-list", Static).update(text)

    # ------------------------------------------------------------------
    # Key handling for preference section
    # ------------------------------------------------------------------

    def on_key(self, event) -> None:
        if self.focus_section != _Focus.PREFERENCE:
            return

        if event.key == "up":
            self._pref_cursor = max(0, self._pref_cursor - 1)
            self._render_pref_list()
            event.stop()
            event.prevent_default()
        elif event.key == "down":
            self._pref_cursor = min(len(_PREF_LIST) - 1, self._pref_cursor + 1)
            self._render_pref_list()
            event.stop()
            event.prevent_default()
        elif event.key == "enter":
            self._confirm()
            event.stop()
            event.prevent_default()

    def _confirm(self) -> None:
        if self._selected_path is None:
            return
        name = self.query_one("#nr-name-input", Input).value.strip() or None
        self.dismiss(NewResourceResult(
            path=self._selected_path,
            name=name,
            loading_preference=_PREF_LIST[self._pref_cursor],
        ))

    # ------------------------------------------------------------------
    # Back / cancel
    # ------------------------------------------------------------------

    def action_back(self) -> None:
        if self.focus_section == _Focus.BROWSER:
            self.dismiss(None)
        elif self.focus_section == _Focus.NAME:
            self.focus_section = _Focus.BROWSER
        elif self.focus_section == _Focus.PREFERENCE:
            self.focus_section = _Focus.NAME

    def action_force_cancel(self) -> None:
        self.dismiss(None)
