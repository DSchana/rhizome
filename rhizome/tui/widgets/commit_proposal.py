"""CommitProposal — interrupt widget for reviewing and editing commit proposals."""

from __future__ import annotations

import asyncio
import copy
from enum import Enum, auto
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.message import Message
from textual.widgets import Input, Static, TextArea


_ENTRY_TYPES = ["fact", "exposition", "overview"]
_CHOICES = ["Approve", "Edit", "Reset", "Cancel"]
_CHOICE_HINTS = ["ctrl+a", "ctrl+e", "ctrl+r", "ctrl+c"]
_CHOICE_DESCRIPTIONS = [
    "accept the proposal (including any changes made above)",
    "describe the changes you'd like to make",
    "discard all changes and restore the original proposal",
    "cancel the proposal",
]

# Colors
_RED = "rgb(255,80,80)"
_DIM = "rgb(100,100,100)"
_EXCLUDED_DIM = "rgb(60,60,60)"
_HINT = "rgb(80,80,80)"


class _State(Enum):
    BROWSE = auto()
    EDIT_DETAIL = auto()
    EDIT_INSTRUCTIONS = auto()


class _EditInstructions(TextArea):
    """Multiline input for edit instructions. Enter submits, Ctrl+J inserts a newline."""

    class Submitted(Message):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def _on_key(self, event) -> None:
        if event.key == "enter":
            text = self.text.strip()
            if text:
                self.post_message(self.Submitted(value=text))
            event.stop()
            event.prevent_default()
        elif event.key == "ctrl+j":
            self.insert("\n")
            event.stop()
            event.prevent_default()
        else:
            super()._on_key(event)


class CommitProposal(Widget, can_focus=True):
    """Displays a commit proposal for review with inline editing.

    The entry list and choice list share a single cursor. Position 0 is
    the "Topic (all)" row; positions ``1 .. N`` are entries; positions
    ``N+1 .. N+3`` are choices.
    """

    BINDINGS = [
        Binding("up", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("enter", "select", show=False),
        Binding("escape", "escape", show=False),
        Binding("d", "toggle_exclude", show=False),
        Binding("f", "cycle_type", show=False),
        Binding("t", "select_topic", show=False),
        Binding("T", "select_topic_all", show=False),
        Binding("ctrl+a", "approve", show=False),
        Binding("ctrl+e", "edit_instructions", show=False),
        Binding("ctrl+r", "reset_proposal", show=False),
        Binding("ctrl+c", "cancel_proposal", show=False),
    ]

    DEFAULT_CSS = """
    CommitProposal {
        height: auto;
        layout: vertical;
        padding: 1 2;
        margin: 1 0;
    }
    CommitProposal #proposal-header {
        margin-bottom: 0;
    }
    CommitProposal #proposal-hints {
        color: rgb(80,80,80);
        margin-bottom: 1;
    }
    CommitProposal #detail-panel {
        border: solid $surface-lighten-2;
        margin: 1 0;
        padding: 1 2 1 2;
        height: auto;
    }
    CommitProposal #detail-title {
        background: transparent;
        border: none;
        height: 1;
        padding: 0;
        margin: 0;
    }
    CommitProposal #detail-title:focus {
        border: solid $accent;
        height: 3;
    }
    CommitProposal #detail-meta {
        color: rgb(100,100,100);
        margin: 0 0 1 0;
        padding: 0;
    }
    CommitProposal #detail-content {
        background: transparent;
        border: none;
        height: auto;
        max-height: 12;
        min-height: 3;
        margin: 0;
        padding: 0 1;
    }
    CommitProposal #detail-content:focus {
        border: solid $accent;
    }
    CommitProposal #proposal-choices {
        margin-top: 1;
    }
    CommitProposal #edit-instructions {
        background: transparent;
        border: solid $surface-lighten-2;
        margin: 1 0 0 0;
        height: auto;
        min-height: 3;
        max-height: 8;
        padding: 0 1;
    }
    """

    cursor: reactive[int] = reactive(1)

    def __init__(
        self,
        entries: list[dict[str, Any]],
        topic_map: dict[int, str],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._entries = [dict(e) for e in entries]
        self._topic_map = dict(topic_map)
        self._original_entries = copy.deepcopy(self._entries)
        self._original_topic_map = copy.deepcopy(self._topic_map)
        self._excluded: set[int] = set()
        self._state = _State.BROWSE
        self._max_content_lines: int = 0
        self._future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()

    @classmethod
    def from_interrupt(cls, value: dict[str, Any]) -> CommitProposal:
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
        # 1 (topic-all) + entries + choices
        return 1 + self._entry_count + len(_CHOICES)

    @property
    def _cursor_entry_index(self) -> int | None:
        """Return the 0-based entry index if the cursor is on an entry, else None."""
        if 1 <= self.cursor <= self._entry_count:
            return self.cursor - 1
        return None

    @property
    def _viewed_entry_index(self) -> int:
        """Entry index to show in the detail panel (clamps to valid range)."""
        return min(max(self.cursor - 1, 0), self._entry_count - 1)

    @property
    def _common_topic_id(self) -> int | None:
        """Return the shared topic_id if all entries have the same one, else None."""
        ids = {e["topic_id"] for e in self._entries}
        return ids.pop() if len(ids) == 1 else None

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
        yield _EditInstructions(
            id="edit-instructions",
            show_line_numbers=False,
        )

    def on_mount(self) -> None:
        edit_inst = self.query_one("#edit-instructions", _EditInstructions)
        edit_inst.display = False
        edit_inst.placeholder = "Describe what changes you'd like..."
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
            self.call_after_refresh(self._scroll_choices_visible)

    # ------------------------------------------------------------------
    # Action gating — disable browse-only bindings during editing
    # ------------------------------------------------------------------

    def check_action(self, action: str, parameters: tuple) -> bool:
        browse_only = {
            "cursor_up", "cursor_down", "select",
            "toggle_exclude", "cycle_type", "select_topic",
            "select_topic_all",
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
            "  d: exclude/include  f: cycle type  t: change topic  T: change all topics  enter: edit  esc: back",
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
        title_widths = [len(e["title"]) for e in self._entries]
        max_title = max(title_widths, default=0)

        text = Text()

        # Topic (all) row — cursor position 0
        common = self._common_topic_id
        if common is not None:
            topic_label = f"{self._topic_map.get(common, f'#{common}')} [{common}]"
        else:
            topic_label = "(mixed)"
        topic_all_selected = self.cursor == 0
        marker = "► " if topic_all_selected else "  "
        text.append(marker, style="bold" if topic_all_selected else "")
        # Pad to align with numbered entries: use same num_width but with spaces
        text.append(" " * (num_width + 1), style=_DIM)
        text.append(f"Topic (all): {topic_label}", style="bold" if topic_all_selected else _DIM)

        # Entry rows — cursor positions 1..N
        text.append("\n")
        for i, entry in enumerate(self._entries):
            text.append("\n")

            is_selected = self.cursor == i + 1
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
            # Ratchet min-height so the panel never shrinks
            line_count = content_area.document.line_count
            if line_count > self._max_content_lines:
                self._max_content_lines = line_count
                content_area.styles.min_height = min(line_count, 12)

        etype = entry["entry_type"]
        topic_id = entry["topic_id"]
        topic_name = self._topic_map.get(topic_id, f"#{topic_id}")
        excluded_note = "  [dim](excluded)[/dim]" if idx in self._excluded else ""
        self.query_one("#detail-meta", Static).update(
            f"  Type: {etype}   Topic: {topic_name} [{topic_id}]{excluded_note}"
        )

    def _render_choices(self) -> None:
        # Compute column width so descriptions align
        prefix_lengths = [
            2 + len(c) + 1 + len(f"({h})")  # "► " or "  " + choice + " " + "(hint)"
            for c, h in zip(_CHOICES, _CHOICE_HINTS)
        ]
        max_prefix = max(prefix_lengths)

        text = Text()
        for i, choice in enumerate(_CHOICES):
            if i > 0:
                text.append("\n")
            choice_idx = 1 + self._entry_count + i
            is_selected = choice_idx == self.cursor
            hint = _CHOICE_HINTS[i]
            desc = _CHOICE_DESCRIPTIONS[i]
            if is_selected:
                text.append(f"► {choice}", style=f"bold {_RED}")
            else:
                text.append(f"  {choice}", style=_DIM)
            hint_str = f" ({hint})"
            text.append(hint_str, style=_HINT)
            padding = max_prefix - prefix_lengths[i] + 2
            text.append(" " * padding + desc, style=_HINT)
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
        if self.cursor == 0:
            # Topic (all) row — open topic selector for all entries
            self._open_topic_selector_all()
        elif self.cursor <= self._entry_count:
            self._enter_detail_edit()
        else:
            choice = _CHOICES[self.cursor - self._entry_count - 1]
            self._handle_choice(choice)

    def action_toggle_exclude(self) -> None:
        entry_idx = self._cursor_entry_index
        if entry_idx is not None:
            self._excluded.symmetric_difference_update({entry_idx})
            self._render_entry_list()
            self._render_detail()

    def action_cycle_type(self) -> None:
        entry_idx = self._cursor_entry_index
        if entry_idx is not None:
            entry = self._entries[entry_idx]
            try:
                idx = _ENTRY_TYPES.index(entry["entry_type"])
            except ValueError:
                idx = -1
            entry["entry_type"] = _ENTRY_TYPES[(idx + 1) % len(_ENTRY_TYPES)]
            self._render_entry_list()
            self._render_detail()

    def action_select_topic(self) -> None:
        entry_idx = self._cursor_entry_index
        if entry_idx is not None:
            from rhizome.tui.screens.topic_selector import TopicSelectorScreen
            self.app.push_screen(TopicSelectorScreen(), callback=self._on_topic_selected)

    def _on_topic_selected(self, result: tuple[int, str] | None) -> None:
        entry_idx = self._cursor_entry_index
        if result is not None and entry_idx is not None:
            topic_id, topic_name = result
            self._entries[entry_idx]["topic_id"] = topic_id
            self._topic_map[topic_id] = topic_name
            self._render_entry_list()
            self._render_detail()
        self.focus()

    def action_select_topic_all(self) -> None:
        self._open_topic_selector_all()

    def _open_topic_selector_all(self) -> None:
        from rhizome.tui.screens.topic_selector import TopicSelectorScreen
        self.app.push_screen(TopicSelectorScreen(), callback=self._on_topic_all_selected)

    def _on_topic_all_selected(self, result: tuple[int, str] | None) -> None:
        if result is not None:
            topic_id, topic_name = result
            self._topic_map[topic_id] = topic_name
            for entry in self._entries:
                entry["topic_id"] = topic_id
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
            instructions_input = self.query_one("#edit-instructions", _EditInstructions)
            instructions_input.display = False
            instructions_input.clear()
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

    def on__edit_instructions_submitted(self, event: _EditInstructions.Submitted) -> None:
        self._resolve_edit(event.value)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "edit-instructions":
            self.call_after_refresh(
                lambda: event.text_area.scroll_visible(animate=False)
            )

    # ------------------------------------------------------------------
    # Choice handling
    # ------------------------------------------------------------------

    def action_approve(self) -> None:
        self._handle_choice("Approve")

    def action_edit_instructions(self) -> None:
        self._handle_choice("Edit")

    def action_reset_proposal(self) -> None:
        self._handle_choice("Reset")

    def action_cancel_proposal(self) -> None:
        self._handle_choice("Cancel")

    def _handle_choice(self, choice: str) -> None:
        if choice == "Approve":
            self._resolve(choice)
        elif choice == "Edit":
            self._state = _State.EDIT_INSTRUCTIONS
            instructions_input = self.query_one("#edit-instructions", _EditInstructions)
            instructions_input.display = True
            instructions_input.focus()
            self.call_after_refresh(
                lambda: instructions_input.scroll_visible(animate=False)
            )
        elif choice == "Reset":
            self._entries = copy.deepcopy(self._original_entries)
            self._topic_map = copy.deepcopy(self._original_topic_map)
            self._excluded.clear()
            self._max_content_lines = 0
            self.cursor = 1
            self._render_all()
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
        self.query_one("#edit-instructions", _EditInstructions).display = False

    # ------------------------------------------------------------------
    # InterruptWidget protocol
    # ------------------------------------------------------------------

    async def wait_for_selection(self) -> Any:
        return await self._future

    def cancel(self) -> None:
        if not self._future.done():
            self._future.cancel()
