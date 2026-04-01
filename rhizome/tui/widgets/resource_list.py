"""ResourceList — read-only widget for browsing resources."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from rhizome.db import Resource

_DIM = "rgb(100,100,100)"
_HINT = "rgb(80,80,80)"
_ACCENT = "rgb(255,80,80)"
_FOCUS_GREEN = "rgb(100,200,100)"
_ALT_GREY = "rgb(180,180,180)"


class ResourceList(Widget, can_focus=True):
    """Read-only resource list with detail panel for browsing Resource objects."""

    BINDINGS = [
        Binding("up", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("enter", "dismiss", show=False),
        Binding("escape", "dismiss", show=False),
    ]

    DEFAULT_CSS = """
    ResourceList {
        height: auto;
        layout: vertical;
        padding: 0 1;
    }
    ResourceList #rl-list-scroll {
        height: auto;
        max-height: 10;
        margin: 1 0 1 0;
    }
    ResourceList #rl-list {
        height: auto;
    }
    ResourceList #rl-detail-panel {
        border: solid $surface-lighten-2;
        padding: 1 2;
        height: auto;
    }
    ResourceList #rl-name {
        text-style: bold;
        margin-bottom: 0;
    }
    ResourceList #rl-meta {
        color: rgb(100,100,100);
        margin: 0 0 1 0;
    }
    ResourceList #rl-summary-scroll {
        height: auto;
        max-height: 10;
    }
    ResourceList #rl-summary {
        height: auto;
    }
    ResourceList #rl-empty {
        color: $text-muted;
        text-style: italic;
        margin: 1 0 0 1;
    }
    """

    class Dismissed(Message):
        """Posted when the user presses Escape to leave the resource list."""

    class CursorChanged(Message):
        """Posted when the cursor moves to a different resource."""

        def __init__(self, resource: Resource | None) -> None:
            super().__init__()
            self.resource = resource

    cursor: reactive[int] = reactive(0)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._resources: list[Resource] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="rl-empty")
        with VerticalScroll(id="rl-list-scroll"):
            yield Static(id="rl-list")
        with Vertical(id="rl-detail-panel"):
            yield Static(id="rl-name")
            yield Static(id="rl-meta")
            with VerticalScroll(id="rl-summary-scroll"):
                yield Static(id="rl-summary")

    def on_mount(self) -> None:
        self._apply_empty_state()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_resources(self, resources: list[Resource]) -> None:
        """Replace the displayed resources and reset the cursor."""
        self._resources = list(resources)
        self.cursor = 0
        self._apply_empty_state()
        if self._resources:
            self._render_list()
            self._render_detail()
            self._scroll_cursor_visible()
            self.post_message(self.CursorChanged(self._resources[0]))
        else:
            self.post_message(self.CursorChanged(None))

    # ------------------------------------------------------------------
    # Reactive watchers
    # ------------------------------------------------------------------

    def watch_cursor(self) -> None:
        if self._resources:
            self._render_list()
            self._render_detail()
            self._scroll_cursor_visible()
            resource = self._resources[min(self.cursor, len(self._resources) - 1)]
            self.post_message(self.CursorChanged(resource))
        else:
            self.post_message(self.CursorChanged(None))

    def _scroll_cursor_visible(self) -> None:
        self.call_after_refresh(self._do_scroll_cursor_visible)

    def _do_scroll_cursor_visible(self) -> None:
        scroll = self.query_one("#rl-list-scroll", VerticalScroll)
        if scroll.size.height == 0:
            return
        line_height = 1
        cursor_top = self.cursor * line_height
        cursor_bottom = cursor_top + line_height
        if cursor_top < scroll.scroll_y:
            scroll.scroll_y = cursor_top
        elif cursor_bottom > scroll.scroll_y + scroll.size.height:
            scroll.scroll_y = cursor_bottom - scroll.size.height

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _apply_empty_state(self) -> None:
        empty = not self._resources
        self.query_one("#rl-empty", Static).display = empty
        self.query_one("#rl-list-scroll", VerticalScroll).display = not empty
        self.query_one("#rl-detail-panel", Vertical).display = not empty
        if empty:
            self.query_one("#rl-empty", Static).update("(No resources)")

    def _render_list(self) -> None:
        num_width = len(str(len(self._resources))) + 2
        name_widths = [len(r.name) for r in self._resources]
        max_name = max(name_widths, default=0)

        right_parts = [
            r.loading_preference.value if r.loading_preference else "—"
            for r in self._resources
        ]
        max_right = max((len(r) for r in right_parts), default=0)

        text = Text()
        for i, resource in enumerate(self._resources):
            if i > 0:
                text.append("\n")

            is_selected = self.cursor == i
            marker = "► " if is_selected else "  "
            num = f"{i + 1}. ".rjust(num_width + 1)

            if is_selected and self.has_focus:
                style = f"bold {_FOCUS_GREEN}"
                marker_style = f"bold {_FOCUS_GREEN}"
                right_style = _DIM
            elif is_selected:
                style = "bold"
                marker_style = "bold"
                right_style = _DIM
            else:
                style = "" if i % 2 == 0 else _ALT_GREY
                marker_style = ""
                right_style = _DIM

            text.append(marker, style=marker_style)
            text.append(num, style=style)
            text.append(resource.name, style=style)

            right = right_parts[i].rjust(max_right)
            padding = max_name - len(resource.name) + 2
            gap = " " * padding
            text.append(gap)
            text.append(right, style=right_style)

        self.query_one("#rl-list", Static).update(text)

    def _render_detail(self) -> None:
        if not self._resources:
            return
        idx = min(self.cursor, len(self._resources) - 1)
        resource = self._resources[idx]

        panel = self.query_one("#rl-detail-panel", Vertical)
        panel.border_title = f"Resource {idx + 1}"

        self.query_one("#rl-name", Static).update(resource.name)

        parts = [f"Preference: {resource.loading_preference.value}"]
        if resource.estimated_tokens is not None:
            parts.append(f"Tokens: ~{resource.estimated_tokens:,}")
        if resource.created_at is not None:
            parts.append(f"Created: {resource.created_at:%Y-%m-%d}")
        self.query_one("#rl-meta", Static).update("  ".join(parts))

        summary = resource.summary or "(no summary)"
        self.query_one("#rl-summary", Static).update(summary)

    # ------------------------------------------------------------------
    # Focus changes
    # ------------------------------------------------------------------

    def on_focus(self) -> None:
        if self._resources:
            self.call_after_refresh(self._render_list)

    def on_blur(self) -> None:
        if self._resources:
            self.call_after_refresh(self._render_list)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_cursor_up(self) -> None:
        if self._resources and self.cursor > 0:
            self.cursor -= 1

    def action_cursor_down(self) -> None:
        if self._resources and self.cursor < len(self._resources) - 1:
            self.cursor += 1

    def action_dismiss(self) -> None:
        self.post_message(self.Dismissed())
