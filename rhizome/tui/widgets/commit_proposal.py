"""CommitProposalInterrupt — interrupt widget for reviewing and editing commit proposals."""

from __future__ import annotations

import asyncio
from enum import Enum, auto
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Static, TextArea


_ENTRY_TYPES = ["fact", "exposition", "overview"]
_CHOICES = ["Approve", "Edit", "Cancel"]
_CHOICE_HINTS = ["ctrl+a", "ctrl+e", "ctrl+c"]

# Colors
_RED = "rgb(255,80,80)"
_DIM = "rgb(100,100,100)"
_EXCLUDED_DIM = "rgb(60,60,60)"
_HINT = "rgb(80,80,80)"


class _State(Enum):
    BROWSE = auto()
    EDIT_DETAIL = auto()
    EDIT_INSTRUCTIONS = auto()


class CommitProposalInterrupt(Widget, can_focus=True):
    """Displays a commit proposal for review with inline editing.

    The entry list and choice list share a single cursor. Positions
    ``0 .. N-1`` are entries; positions ``N .. N+2`` are choices.
    """

    BINDINGS = [
        Binding("up", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("enter", "select", show=False),
        Binding("escape", "escape", show=False),
        Binding("d", "toggle_exclude", show=False),
        Binding("f", "cycle_type", show=False),
        Binding("t", "select_topic", show=False),
        Binding("ctrl+a", "approve", show=False),
        Binding("ctrl+e", "edit_instructions", show=False),
        Binding("ctrl+c", "cancel_proposal", show=False),
    ]

    DEFAULT_CSS = """
    CommitProposalInterrupt {
        height: auto;
        layout: vertical;
        padding: 1 2;
        margin: 1 0;
    }
    CommitProposalInterrupt #proposal-header {
        margin-bottom: 0;
    }
    CommitProposalInterrupt #proposal-hints {
        color: rgb(80,80,80);
        margin-bottom: 1;
    }
    CommitProposalInterrupt #detail-panel {
        border: solid $surface-lighten-2;
        margin: 1 0;
        padding: 1 2 1 2;
        height: auto;
    }
    CommitProposalInterrupt #detail-title {
        background: transparent;
        border: none;
        height: 1;
        padding: 0;
        margin: 0;
    }
    CommitProposalInterrupt #detail-title:focus {
        border: solid $accent;
        height: 3;
    }
    CommitProposalInterrupt #detail-meta {
        color: rgb(100,100,100);
        margin: 0 0 1 0;
        padding: 0;
    }
    CommitProposalInterrupt #detail-content {
        background: transparent;
        border: none;
        height: auto;
        max-height: 12;
        min-height: 3;
        margin: 0;
        padding: 0 1;
    }
    CommitProposalInterrupt #detail-content:focus {
        border: solid $accent;
    }
    CommitProposalInterrupt #proposal-choices {
        margin-top: 1;
    }
    CommitProposalInterrupt #edit-instructions {
        background: transparent;
        border: solid $surface-lighten-2;
        margin: 1 0 0 0;
        height: 3;
        padding: 0 1;
    }
    """

    cursor: reactive[int] = reactive(0)

    def __init__(
        self,
        entries: list[dict[str, Any]],
        topic_map: dict[int, str],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._entries = [dict(e) for e in entries]
        self._topic_map = dict(topic_map)
        self._excluded: set[int] = set()
        self._state = _State.BROWSE
        self._future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()

    @classmethod
    def from_interrupt(cls, value: dict[str, Any]) -> CommitProposalInterrupt:
        return cls(
            entries=value["entries"],
            topic_map=value.get("topic_map", {}),
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def _entry_count(self) -> int:
        return len(self._entries)

    @property
    def _total_items(self) -> int:
        return self._entry_count + len(_CHOICES)

    @property
    def _viewed_entry_index(self) -> int:
        """Entry index to show in the detail panel (clamps to last entry)."""
        return min(self.cursor, self._entry_count - 1)

    # ------------------------------------------------------------------
    # Compose & mount
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(id="proposal-header")
        yield Static(id="proposal-hints")
        yield Static(id="entry-list")
        with Vertical(id="detail-panel"):
            yield Input(id="detail-title")
            yield Static(id="detail-meta")
            yield TextArea(id="detail-content", show_line_numbers=False)
        yield Static(id="proposal-choices")
        yield Input(
            id="edit-instructions",
            placeholder="Describe what changes you'd like...",
        )

    def on_mount(self) -> None:
        self.query_one("#edit-instructions", Input).display = False
        # Disable cursor blink on the TextArea until it's focused
        self.query_one("#detail-content", TextArea).cursor_blink = False
        self._render_all()
        self.focus()

    # ------------------------------------------------------------------
    # Reactive watchers
    # ------------------------------------------------------------------

    def watch_cursor(self) -> None:
        if self._state == _State.BROWSE:
            self._render_entry_list()
            self._render_detail()
            self._render_choices()
            self._scroll_choices_visible()

    # ------------------------------------------------------------------
    # Action gating — disable browse-only bindings during editing
    # ------------------------------------------------------------------

    def check_action(self, action: str, parameters: tuple) -> bool:
        browse_only = {
            "cursor_up", "cursor_down", "select",
            "toggle_exclude", "cycle_type", "select_topic",
        }
        if action in browse_only:
            return self._state == _State.BROWSE
        return True

    # ------------------------------------------------------------------
    # Scrolling
    # ------------------------------------------------------------------

    def _scroll_choices_visible(self) -> None:
        """Ensure the choices area is always visible by scrolling it into view."""
        choices = self.query_one("#proposal-choices", Static)
        choices.scroll_visible(animate=False)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_all(self) -> None:
        self._render_header()
        self._render_hints()
        self._render_entry_list()
        self._render_detail()
        self._render_choices()

    def _render_header(self) -> None:
        n = self._entry_count
        s = "y" if n == 1 else "ies"
        text = Text()
        text.append("  Commit Proposal", style=f"bold {_RED}")
        text.append(f"  ({n} entr{s})", style=_DIM)
        self.query_one("#proposal-header", Static).update(text)

    def _render_hints(self) -> None:
        self.query_one("#proposal-hints", Static).update(Text(
            "  d: exclude/include  f: cycle type  t: change topic  enter: edit  esc: back",
            style=_HINT,
        ))

    def _render_entry_list(self) -> None:
        # Compute the right-side column width for alignment
        right_parts: list[str] = []
        for entry in self._entries:
            etype = entry["entry_type"]
            topic_id = entry["topic_id"]
            topic_name = self._topic_map.get(topic_id, f"#{topic_id}")
            right_parts.append(f"{etype} │ {topic_name} [{topic_id}]")
        max_right = max((len(r) for r in right_parts), default=0)

        # Compute the max title width for padding
        num_width = len(str(self._entry_count)) + 2  # "N. "
        marker_width = 2  # "► " or "  "
        title_widths = [len(e["title"]) for e in self._entries]
        max_title = max(title_widths, default=0)

        text = Text()
        for i, entry in enumerate(self._entries):
            if i > 0:
                text.append("\n")

            is_selected = i == self.cursor
            is_excluded = i in self._excluded

            marker = "► " if is_selected else "  "
            num = f"{i + 1}. ".rjust(num_width + 1)
            title = entry["title"]
            right = right_parts[i].rjust(max_right)
            # Pad between title and right column
            padding = max_title - len(title) + 2
            gap = " " * padding

            if is_excluded:
                style = f"{_EXCLUDED_DIM} strike"
                right_style = f"{_EXCLUDED_DIM} strike"
            elif is_selected:
                style = "bold"
                right_style = _DIM
            else:
                style = ""
                right_style = _DIM

            text.append(marker, style="bold" if is_selected else "")
            text.append(num, style=style)
            text.append(title, style=style)
            text.append(gap)
            text.append(right, style=right_style)

        self.query_one("#entry-list", Static).update(text)

    def _render_detail(self) -> None:
        idx = self._viewed_entry_index
        entry = self._entries[idx]

        panel = self.query_one("#detail-panel", Vertical)
        panel.border_title = f"Entry {idx + 1}"

        # Only update widget values in browse mode to avoid clobbering edits.
        if self._state == _State.BROWSE:
            self.query_one("#detail-title", Input).value = entry["title"]
            content_area = self.query_one("#detail-content", TextArea)
            content_area.clear()
            content_area.insert(entry["content"])

        etype = entry["entry_type"]
        topic_id = entry["topic_id"]
        topic_name = self._topic_map.get(topic_id, f"#{topic_id}")
        excluded_note = "  [dim](excluded)[/dim]" if idx in self._excluded else ""
        self.query_one("#detail-meta", Static).update(
            f"  Type: {etype}   Topic: {topic_name} [{topic_id}]{excluded_note}"
        )

    def _render_choices(self) -> None:
        text = Text()
        for i, choice in enumerate(_CHOICES):
            if i > 0:
                text.append("    ")
            choice_idx = self._entry_count + i
            is_selected = choice_idx == self.cursor
            hint = _CHOICE_HINTS[i]
            if is_selected:
                text.append(f"► {choice}", style=f"bold {_RED}")
            else:
                text.append(f"  {choice}", style=_DIM)
            text.append(f" ({hint})", style=_HINT)
        self.query_one("#proposal-choices", Static).update(text)

    # ------------------------------------------------------------------
    # Browse actions
    # ------------------------------------------------------------------

    def action_cursor_up(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1

    def action_cursor_down(self) -> None:
        if self.cursor < self._total_items - 1:
            self.cursor += 1

    def action_select(self) -> None:
        if self.cursor < self._entry_count:
            self._enter_detail_edit()
        else:
            choice = _CHOICES[self.cursor - self._entry_count]
            self._handle_choice(choice)

    def action_toggle_exclude(self) -> None:
        if self.cursor < self._entry_count:
            self._excluded.symmetric_difference_update({self.cursor})
            self._render_entry_list()
            self._render_detail()

    def action_cycle_type(self) -> None:
        if self.cursor < self._entry_count:
            entry = self._entries[self.cursor]
            try:
                idx = _ENTRY_TYPES.index(entry["entry_type"])
            except ValueError:
                idx = -1
            entry["entry_type"] = _ENTRY_TYPES[(idx + 1) % len(_ENTRY_TYPES)]
            self._render_entry_list()
            self._render_detail()

    def action_select_topic(self) -> None:
        if self.cursor < self._entry_count:
            from rhizome.tui.screens.topic_selector import TopicSelectorScreen
            self.app.push_screen(TopicSelectorScreen(), callback=self._on_topic_selected)

    def _on_topic_selected(self, result: tuple[int, str] | None) -> None:
        if result is not None and self.cursor < self._entry_count:
            topic_id, topic_name = result
            self._entries[self.cursor]["topic_id"] = topic_id
            self._topic_map[topic_id] = topic_name
            self._render_entry_list()
            self._render_detail()
        self.focus()

    # ------------------------------------------------------------------
    # Escape — context-dependent
    # ------------------------------------------------------------------

    def action_escape(self) -> None:
        if self._state == _State.EDIT_DETAIL:
            self._save_detail_edits()
            self._state = _State.BROWSE
            # Disable cursor blink now that we've left edit mode
            self.query_one("#detail-content", TextArea).cursor_blink = False
            self._render_entry_list()
            self._render_detail()
            self.focus()
        elif self._state == _State.EDIT_INSTRUCTIONS:
            instructions_input = self.query_one("#edit-instructions", Input)
            instructions_input.display = False
            instructions_input.value = ""
            self._state = _State.BROWSE
            self.focus()

    # ------------------------------------------------------------------
    # Detail editing
    # ------------------------------------------------------------------

    def _enter_detail_edit(self) -> None:
        self._state = _State.EDIT_DETAIL
        self.query_one("#detail-content", TextArea).cursor_blink = True
        self.query_one("#detail-title", Input).focus()

    def _save_detail_edits(self) -> None:
        idx = self._viewed_entry_index
        entry = self._entries[idx]
        entry["title"] = self.query_one("#detail-title", Input).value
        entry["content"] = self.query_one("#detail-content", TextArea).text

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "detail-title":
            # Enter in title → move to content
            self.query_one("#detail-content", TextArea).focus()
        elif event.input.id == "edit-instructions":
            self._resolve_edit(event.value)

    # ------------------------------------------------------------------
    # Choice handling
    # ------------------------------------------------------------------

    def action_approve(self) -> None:
        self._handle_choice("Approve")

    def action_edit_instructions(self) -> None:
        self._handle_choice("Edit")

    def action_cancel_proposal(self) -> None:
        self._handle_choice("Cancel")

    def _handle_choice(self, choice: str) -> None:
        if choice == "Approve":
            self._resolve(choice)
        elif choice == "Edit":
            self._state = _State.EDIT_INSTRUCTIONS
            instructions_input = self.query_one("#edit-instructions", Input)
            instructions_input.display = True
            instructions_input.focus()
            instructions_input.scroll_visible(animate=False)
        elif choice == "Cancel":
            self._resolve(choice)

    def _resolve(self, choice: str, instructions: str | None = None) -> None:
        if self._future.done():
            return
        included = [
            self._entries[i]
            for i in range(self._entry_count)
            if i not in self._excluded
        ]
        result: dict[str, Any] = {"choice": choice, "entries": included}
        if instructions:
            result["instructions"] = instructions
        self._future.set_result(result)
        self._render_resolved(choice, instructions)

    def _resolve_edit(self, instructions: str) -> None:
        self._resolve("Edit", instructions=instructions)

    def _render_resolved(self, choice: str, instructions: str | None = None) -> None:
        """Dim the widget after resolution."""
        # Disable cursor blink on resolution
        self.query_one("#detail-content", TextArea).cursor_blink = False
        resolved = Text()
        resolved.append(f"  you selected: {choice}", style=_DIM)
        if instructions:
            resolved.append(f"\n  instructions: {instructions}", style=_DIM)
        self.query_one("#proposal-choices", Static).update(resolved)
        self.query_one("#proposal-hints", Static).update("")
        self.query_one("#edit-instructions", Input).display = False

    # ------------------------------------------------------------------
    # InterruptWidget protocol
    # ------------------------------------------------------------------

    async def wait_for_selection(self) -> Any:
        return await self._future

    def cancel(self) -> None:
        if not self._future.done():
            self._future.cancel()
