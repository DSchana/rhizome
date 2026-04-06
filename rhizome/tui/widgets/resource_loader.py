"""ResourceLoader — checkbox list for loading resources into the agent session."""

from __future__ import annotations

import enum

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from rhizome.db import Resource


_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class LoadState(enum.Enum):
    """Load state for a resource in the loader widget."""

    UNLOADED = "unloaded"
    DEFAULT = "default"          # loaded per resource's loading_preference
    CONTEXT_STUFFED = "context"  # override: context-stuffed directly
    PENDING = "pending"          # embedding in progress — locked, shows spinner


_DIM = "rgb(100,100,100)"
_FOCUS_GREEN = "rgb(100,200,100)"
_ALT_BG_1 = "rgb(25,25,25)"
_ALT_BG_2 = "rgb(35,35,35)"
_CHECKED_GREEN = "rgb(100,200,100)"
_CHECKED_AMBER = "rgb(220,170,50)"
_UNCHECKED_COLOR = "rgb(80,80,80)"
_PENDING_COLOR = "rgb(100,100,100)"
_META_COLOR = "rgb(80,80,80)"


def _fmt_tokens(n: int | None) -> str:
    """Format a token count as a short human-readable string."""
    if n is None:
        return "?"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}m"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


class ResourceLoader(Widget, can_focus=True):
    """Checkbox list for loading/unloading resources.

    States per resource:
        [ ]  unloaded
        [✓]  green — loaded via default preference (embed/auto)
        [✓]  amber — context-stuffed override
        ⠋ computing embeddings...  — pending (locked)

    Keybindings:
        space/enter     toggle between unloaded ↔ default
        ctrl+enter      promote default → context-stuffed, or unload context-stuffed
    """

    BINDINGS = [
        Binding("up", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("space", "toggle_default", show=False),
        Binding("enter", "toggle_default", show=False),
        Binding("ctrl+j", "toggle_context", show=False, priority=True),
        Binding("escape", "dismiss", show=False),
    ]

    DEFAULT_CSS = """
    ResourceLoader {
        height: auto;
        layout: vertical;
        padding: 0 1;
    }
    ResourceLoader #rld-list-scroll {
        height: auto;
        max-height: 20;
        margin: 1 0 1 0;
    }
    ResourceLoader #rld-list {
        height: auto;
    }
    ResourceLoader #rld-empty {
        color: $text-muted;
        text-style: italic;
        margin: 1 0 0 1;
    }
    ResourceLoader #rld-hint {
        color: rgb(80,80,80);
        margin: 0 0 0 1;
    }
    """

    class Dismissed(Message):
        """Posted when the user presses Escape."""

    class StateChanged(Message):
        """Posted when a resource's load state changes."""

        def __init__(self, resource: Resource, old_state: LoadState, new_state: LoadState) -> None:
            super().__init__()
            self.resource = resource
            self.old_state = old_state
            self.new_state = new_state

    show_ids: reactive[bool] = reactive(False)
    cursor: reactive[int] = reactive(0)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._resources: list[Resource] = []
        self._states: dict[int, LoadState] = {}
        self._spinner_frame: int = 0
        self._spinner_timer = None

    def compose(self) -> ComposeResult:
        yield Static("", id="rld-empty")
        with VerticalScroll(id="rld-list-scroll"):
            yield Static(id="rld-list")
        yield Static("", id="rld-hint")

    def on_mount(self) -> None:
        self._apply_empty_state()
        self._spinner_timer = self.set_interval(0.1, self._tick_spinner, pause=True)

    def _tick_spinner(self) -> None:
        self._spinner_frame = (self._spinner_frame + 1) % len(_SPINNER_FRAMES)
        self._render_list()

    def _update_spinner_timer(self) -> None:
        """Start or pause the spinner timer based on whether any resources are pending."""
        has_pending = any(s == LoadState.PENDING for s in self._states.values())
        if self._spinner_timer is not None:
            if has_pending:
                self._spinner_timer.resume()
            else:
                self._spinner_timer.pause()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_resources(
        self,
        resources: list[Resource],
        states: dict[int, LoadState] | None = None,
    ) -> None:
        """Replace the displayed resources, preserving existing states by default."""
        self._resources = list(resources)
        if states is not None:
            self._states = dict(states)
        # Otherwise keep existing _states — only resource IDs no longer in the
        # list become irrelevant (they'll just be ignored during rendering).
        self.cursor = 0
        self._apply_empty_state()
        if self._resources:
            self._render_list()
            self._update_hint()
            self._scroll_cursor_visible()

    def get_state(self, resource_id: int) -> LoadState:
        """Return the current load state for a resource."""
        return self._states.get(resource_id, LoadState.UNLOADED)

    def set_pending(self, resource_id: int) -> None:
        """Set a resource to PENDING state (embedding in progress)."""
        resource = next((r for r in self._resources if r.id == resource_id), None)
        if resource is not None:
            self._states[resource_id] = LoadState.PENDING
            self._render_list()
            self._update_hint()
            self._update_spinner_timer()

    def resolve_pending(self, resource_id: int, success: bool) -> None:
        """Resolve a pending resource: DEFAULT on success, UNLOADED on failure."""
        if self._states.get(resource_id) != LoadState.PENDING:
            return
        resource = next((r for r in self._resources if r.id == resource_id), None)
        if resource is not None:
            new_state = LoadState.DEFAULT if success else LoadState.UNLOADED
            self._set_state(resource, new_state, quiet=True)

    # ------------------------------------------------------------------
    # Reactive watchers
    # ------------------------------------------------------------------

    def watch_show_ids(self) -> None:
        if self._resources:
            self._render_list()

    def watch_cursor(self) -> None:
        if self._resources:
            self._render_list()
            self._update_hint()
            self._scroll_cursor_visible()

    def _scroll_cursor_visible(self) -> None:
        self.call_after_refresh(self._do_scroll_cursor_visible)

    def _do_scroll_cursor_visible(self) -> None:
        scroll = self.query_one("#rld-list-scroll", VerticalScroll)
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
        self.query_one("#rld-empty", Static).display = empty
        self.query_one("#rld-list-scroll", VerticalScroll).display = not empty
        self.query_one("#rld-hint", Static).display = not empty
        if empty:
            self.query_one("#rld-empty", Static).update("(No resources linked to this topic)")

    def _render_list(self) -> None:
        text = Text()
        for i, resource in enumerate(self._resources):
            if i > 0:
                text.append("\n")

            is_selected = self.cursor == i
            state = self._states.get(resource.id, LoadState.UNLOADED)

            if state == LoadState.PENDING:
                # Pending row: spinner + "computing embeddings..." in dim grey
                marker = "► " if is_selected else "  "
                spinner = _SPINNER_FRAMES[self._spinner_frame]
                text.append(marker, style=_PENDING_COLOR)
                text.append(f"{spinner} ", style=_PENDING_COLOR)
                text.append(resource.name, style=_PENDING_COLOR)
                text.append("  computing embeddings...", style=_PENDING_COLOR)
                continue

            # Checkbox appearance
            if state == LoadState.UNLOADED:
                checkbox = "[ ] "
                checkbox_color = _UNCHECKED_COLOR
            elif state == LoadState.DEFAULT:
                checkbox = "[✓] "
                checkbox_color = _CHECKED_GREEN
            else:  # CONTEXT_STUFFED
                checkbox = "[✓] "
                checkbox_color = _CHECKED_AMBER

            # Row styling
            if is_selected and self.has_focus:
                name_style = f"bold {_FOCUS_GREEN}"
                marker = "► "
            elif is_selected:
                name_style = "bold"
                marker = "► "
            else:
                name_style = "" if i % 2 == 0 else _DIM
                marker = "  "

            text.append(marker, style=name_style)
            text.append(checkbox, style=checkbox_color)
            text.append(resource.name, style=name_style)

            # Metadata: id (togglable) │ tokens │ chunks │ preference
            meta_parts: list[str] = []
            if self.show_ids:
                meta_parts.append(f"[{resource.id}]")
            meta_parts.append(f"~{_fmt_tokens(resource.estimated_tokens)} tok")
            try:
                chunk_count = len(resource.chunks) if resource.chunks is not None else 0
            except Exception:
                chunk_count = 0
            meta_parts.append(f"{chunk_count} chunks")
            pref = resource.loading_preference.value if resource.loading_preference else "—"
            meta_parts.append(pref)
            text.append("  " + " │ ".join(meta_parts), style=_META_COLOR)

            # Show loading preference hint for context-stuffed items
            if state == LoadState.CONTEXT_STUFFED:
                text.append("  ctx", style=_CHECKED_AMBER)

        self.query_one("#rld-list", Static).update(text)

    def _update_hint(self) -> None:
        default_count = sum(
            1 for r in self._resources
            if self._states.get(r.id) == LoadState.DEFAULT
        )
        context_count = sum(
            1 for r in self._resources
            if self._states.get(r.id) == LoadState.CONTEXT_STUFFED
        )
        total = len(self._resources)
        self.query_one("#rld-hint", Static).update(
            f"{default_count + context_count}/{total} loaded "
            f"({context_count} ctx)  |  "
            f"space: toggle  ctrl+enter: context stuff"
        )

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
    # State transitions
    # ------------------------------------------------------------------

    def _set_state(self, resource: Resource, new_state: LoadState, *, quiet: bool = False) -> None:
        old_state = self._states.get(resource.id, LoadState.UNLOADED)
        if new_state == LoadState.UNLOADED:
            self._states.pop(resource.id, None)
        else:
            self._states[resource.id] = new_state
        self._render_list()
        self._update_hint()
        self._update_spinner_timer()
        if not quiet:
            self.post_message(self.StateChanged(resource, old_state, new_state))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_cursor_up(self) -> None:
        if self._resources and self.cursor > 0:
            self.cursor -= 1

    def action_cursor_down(self) -> None:
        if self._resources and self.cursor < len(self._resources) - 1:
            self.cursor += 1

    def action_toggle_default(self) -> None:
        """space/enter: unloaded ↔ default, or context-stuffed → default."""
        if not self._resources:
            return
        resource = self._resources[min(self.cursor, len(self._resources) - 1)]
        state = self._states.get(resource.id, LoadState.UNLOADED)
        if state == LoadState.PENDING:
            return  # locked — embedding in progress
        if state == LoadState.UNLOADED:
            self._set_state(resource, LoadState.DEFAULT)
        elif state == LoadState.DEFAULT:
            self._set_state(resource, LoadState.UNLOADED)
        else:  # CONTEXT_STUFFED → DEFAULT
            self._set_state(resource, LoadState.DEFAULT)

    def action_toggle_context(self) -> None:
        """ctrl+enter: default → context-stuffed, or context-stuffed → unloaded."""
        if not self._resources:
            return
        resource = self._resources[min(self.cursor, len(self._resources) - 1)]
        state = self._states.get(resource.id, LoadState.UNLOADED)
        if state == LoadState.PENDING:
            return  # locked — embedding in progress
        if state == LoadState.UNLOADED:
            self._set_state(resource, LoadState.CONTEXT_STUFFED)
        elif state == LoadState.DEFAULT:
            self._set_state(resource, LoadState.CONTEXT_STUFFED)
        elif state == LoadState.CONTEXT_STUFFED:
            self._set_state(resource, LoadState.UNLOADED)

    def action_dismiss(self) -> None:
        self.post_message(self.Dismissed())
