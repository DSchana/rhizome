"""ResourceLoader — tree-based widget for loading resources into the agent session.

Resources are root nodes; sections (if extracted) appear as expandable
children.  Both resources and sections have independent load states
governed by the same state machine:

    unloaded  →(space)→  default  →(space)→  unloaded
    unloaded  →(ctrl+enter)→  context-stuffed  →(ctrl+enter)→  unloaded
    default   →(ctrl+enter)→  context-stuffed
    context-stuffed  →(space)→  default
"""

from __future__ import annotations

import enum
from typing import Any

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static, Tree
from textual.widgets._tree import TreeNode, TOGGLE_STYLE

from rhizome.db import Resource
from rhizome.db.models import ResourceSection

from rhizome.tui.types import Arrangement
from .resource_view_model import LoadState, ResourceLoaderViewModel


_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


# -- Colors ------------------------------------------------------------

_DIM = Style(color="rgb(100,100,100)")
_FOCUS_GREEN = Style(color="rgb(100,200,100)", bold=True)
_UNFOCUSED_BOLD = Style(bold=True)
_CHECKED_GREEN = Style(color="rgb(100,200,100)")
_CHECKED_AMBER = Style(color="rgb(220,170,50)")
_UNCHECKED = Style(color="rgb(80,80,80)")
_PENDING = Style(color="rgb(100,100,100)")
_META = Style(color="rgb(80,80,80)")
_CTX_TAG = Style(color="rgb(220,170,50)")
_ID_STYLE = Style(color="rgb(80,80,80)")
_HINT_COLOR = "rgb(80,80,80)"

# Section depth colors: depth 1 is lighter, depth 2+ is dimmer.
_SECTION_DEPTH_1 = Style(color="rgb(140,140,140)")
_SECTION_DEPTH_2_PLUS = Style(color="rgb(100,100,100)")


def _fmt_tokens(n: int | None) -> str:
    """Format a token count as a short human-readable string."""
    if n is None:
        return "?"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}m"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


# -- Node data ---------------------------------------------------------

NodeData = Resource | ResourceSection


def _state_key(data: NodeData) -> tuple[str, int]:
    if isinstance(data, Resource):
        return ("resource", data.id)
    return ("section", data.id)


def _owning_resource(node: TreeNode[NodeData]) -> Resource:
    """Walk up to find the Resource that owns this node."""
    current = node
    while current is not None:
        if isinstance(current.data, Resource):
            return current.data
        current = current.parent
    raise RuntimeError("Section node has no Resource ancestor")


class _LoaderHint(Static):
    """Self-rendering hint bar that reacts to load counts and arrangement."""

    loaded: reactive[int] = reactive(0)
    total: reactive[int] = reactive(0)
    sections: reactive[int] = reactive(0)
    vertical: reactive[bool] = reactive(False)

    _BINDINGS = [
        ("space", "toggle"),
        ("ctrl+enter", "context stuff"),
        ("\u2190/\u2192", "expand/collapse"),
    ]

    def render(self) -> str:
        summary = f"{self.loaded}/{self.total} loaded, {self.sections} sections"
        if self.vertical:
            key_width = max(len(k) for k, _ in self._BINDINGS)
            lines = [summary]
            for key, action in self._BINDINGS:
                lines.append(f"  {key:<{key_width}}  {action}")
            return "\n".join(lines)
        else:
            parts = [f"{k}: {a}" for k, a in self._BINDINGS]
            return f"{summary}  |  {'  '.join(parts)}"


# ======================================================================
# Inner tree widget
# ======================================================================

class _LoaderTree(Tree[NodeData]):
    """The actual Tree — managed by the outer ResourceLoader container."""

    DEFAULT_CSS = """
    _LoaderTree {
        height: auto;
        max-height: 20;
        margin: 1 1 1 1;
        background: transparent;
        overflow-y: auto;
    }
    _LoaderTree:focus {
        background-tint: transparent;
    }
    _LoaderTree > .tree--cursor {
        background: transparent;
    }
    _LoaderTree:focus > .tree--cursor {
        background: transparent;
    }
    _LoaderTree > .tree--highlight {
        background: transparent;
    }
    _LoaderTree > .tree--highlight-line {
        background: transparent;
    }
    """

    def __init__(self, loader: ResourceLoader, **kwargs) -> None:
        super().__init__("Resources", **kwargs)
        self.show_root = False
        self._loader = loader

    def _refresh_height(self) -> None:
        # In vertical arrangement, height is 1fr (CSS) — skip manual sizing.
        line_count = len(self._tree_lines) + 2  # +2 for padding/margin
        self.styles.height = max(line_count, 1)

    def _invalidate_label_cache(self) -> None:
        self._updates += 1
        self.refresh()

    # -- Expansion -----------------------------------------------------

    def on_tree_node_expanded(self, event: Tree.NodeExpanded[NodeData]) -> None:
        node = event.node
        data = node.data
        if data is None or node.children:
            self._refresh_height()
            return

        if isinstance(data, Resource):
            sections = getattr(data, "sections", None) or []
            root_sections = sorted(
                [s for s in sections if s.parent_id is None],
                key=lambda s: s.position,
            )
            for section in root_sections:
                child_sections = [s for s in sections if s.parent_id == section.id]
                if child_sections:
                    node.add(section.title, data=section, allow_expand=True)
                else:
                    node.add_leaf(section.title, data=section)

        elif isinstance(data, ResourceSection):
            resource = _owning_resource(node)
            all_sections = getattr(resource, "sections", None) or []
            children = sorted(
                [s for s in all_sections if s.parent_id == data.id],
                key=lambda s: s.position,
            )
            for child in children:
                grandchildren = [s for s in all_sections if s.parent_id == child.id]
                if grandchildren:
                    node.add(child.title, data=child, allow_expand=True)
                else:
                    node.add_leaf(child.title, data=child)

        self._refresh_height()

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed[NodeData]) -> None:
        self._refresh_height()

    # -- Key handling --------------------------------------------------

    def _on_key(self, event) -> None:
        if event.key == "right":
            node = self.cursor_node
            if node is not None and node.allow_expand:
                if not node.is_expanded:
                    node.expand()
                elif node.children:
                    self.move_cursor(node.children[0])
            event.stop()
            event.prevent_default()
        elif event.key == "left":
            node = self.cursor_node
            if node is not None:
                if node.is_expanded:
                    node.collapse()
                elif node.parent and node.parent is not self.root:
                    self.move_cursor(node.parent)
            event.stop()
            event.prevent_default()
        elif event.key in ("enter", "space"):
            # Suppress default Tree toggle — these are handled by the
            # outer ResourceLoader's bindings for state transitions.
            event.stop()
            event.prevent_default()
            if event.key == "space":
                self._loader.action_toggle_default()
        else:
            super()._on_key(event)

    # -- Label rendering -----------------------------------------------

    def render_label(
        self, node: TreeNode[NodeData], base_style: Style, style: Style,
    ) -> Text:
        data = node.data
        if data is None:
            return Text(str(node._label))

        loader = self._loader
        key = _state_key(data)
        state = loader._states.get(key, LoadState.UNLOADED)
        is_cursor = node is self.cursor_node

        # -- Pending state: spinner, no checkbox -----------------------
        if state == LoadState.PENDING:
            spinner = _SPINNER_FRAMES[loader._spinner_frame]
            return Text.assemble(
                (f"{spinner} ", _PENDING),
                (str(node._label), _PENDING),
                ("  computing embeddings...", _PENDING),
            )

        # -- Expand/collapse icon --------------------------------------
        if node._allow_expand:
            icon = self.ICON_NODE_EXPANDED if node.is_expanded else self.ICON_NODE
            icon_style = base_style + TOGGLE_STYLE
        else:
            icon = ""
            icon_style = base_style

        # -- Checkbox --------------------------------------------------
        partial = state in (LoadState.DEFAULT, LoadState.CONTEXT_STUFFED) and loader._is_partially_loaded(data)
        if state == LoadState.UNLOADED:
            checkbox, cb_style = "[ ] ", _UNCHECKED
        elif state == LoadState.DEFAULT:
            checkbox = "[/] " if partial else "[✓] "
            cb_style = _CHECKED_GREEN
        else:  # CONTEXT_STUFFED
            checkbox = "[/] " if partial else "[✓] "
            cb_style = _CHECKED_AMBER

        # -- Name styling ----------------------------------------------
        if is_cursor and self.has_focus:
            name_style = _FOCUS_GREEN
        elif is_cursor:
            name_style = _UNFOCUSED_BOLD
        elif isinstance(data, ResourceSection):
            name_style = _SECTION_DEPTH_1 if data.depth <= 1 else _SECTION_DEPTH_2_PLUS
        else:
            name_style = style

        # -- Build suffix (metadata + ctx tag) so we know its width -----
        vertical = loader._vm.arrangement == Arrangement.VERTICAL
        suffix = ""
        if not vertical:
            if isinstance(data, Resource):
                meta_parts: list[str] = []
                if loader.show_ids:
                    meta_parts.append(f"[{data.id}]")
                meta_parts.append(f"~{_fmt_tokens(data.estimated_tokens)} tok")
                try:
                    chunk_count = len(data.chunks) if data.chunks is not None else 0
                except Exception:
                    chunk_count = 0
                meta_parts.append(f"{chunk_count} chunks")
                pref = data.loading_preference.value if data.loading_preference else "—"
                meta_parts.append(pref)
                suffix = "  " + " │ ".join(meta_parts)
            elif isinstance(data, ResourceSection):
                meta_parts: list[str] = []
                if loader.show_ids:
                    meta_parts.append(f"[{data.id}]")
                try:
                    chunk_count = len(data.chunks) if data.chunks is not None else 0
                except Exception:
                    chunk_count = 0
                if chunk_count:
                    meta_parts.append(f"{chunk_count} chunks")
                if meta_parts:
                    suffix = "  " + " │ ".join(meta_parts)

        if state == LoadState.CONTEXT_STUFFED:
            suffix += "  ctx"

        # -- Truncate name to fit within available width ---------------
        name = str(node._label)
        if not vertical:
            tree_depth = 0
            p = node.parent
            while p is not None:
                tree_depth += 1
                p = p.parent
            guide_width = self.guide_depth * tree_depth
            prefix_width = len(icon) + len(checkbox)
            available = self.size.width - guide_width - prefix_width - len(suffix) - 1
            available = max(available, 10)
            if len(name) > available:
                name = name[: available - 1] + "…"

        label = Text(name)
        label.stylize(name_style)

        text = Text.assemble(
            (icon, icon_style),
            (checkbox, base_style + cb_style),
            label,
        )

        # -- Append suffix with styling --------------------------------
        if not vertical:
            if isinstance(data, Resource):
                meta_end = suffix
                if state == LoadState.CONTEXT_STUFFED:
                    meta_end = suffix[: -len("  ctx")]
                    text.append(meta_end, style=_META)
                    text.append("  ctx", style=_CTX_TAG)
                else:
                    text.append(suffix, style=_META)
            else:
                if suffix:
                    meta_end = suffix
                    if state == LoadState.CONTEXT_STUFFED:
                        meta_end = suffix[: -len("  ctx")]
                        text.append(meta_end, style=_META)
                        text.append("  ctx", style=_CTX_TAG)
                    else:
                        text.append(suffix, style=_META)
                elif state == LoadState.CONTEXT_STUFFED:
                    text.append("  ctx", style=_CTX_TAG)
        elif suffix:
            # Vertical: only the ctx tag if present
            text.append(suffix, style=_CTX_TAG)

        return text


# ======================================================================
# Outer container widget
# ======================================================================

class ResourceLoader(Widget, can_focus=True):
    """Container widget with an inner tree and a status hint.

    Delegates focus to the inner ``_LoaderTree`` and exposes the same
    public API that ``ResourceViewer`` expects.
    """

    BINDINGS = [
        Binding("space", "toggle_default", show=False),
        Binding("ctrl+j", "toggle_context", show=False, priority=True),
        Binding("escape", "dismiss", show=False),
    ]

    DEFAULT_CSS = """
    ResourceLoader {
        height: auto;
        layout: vertical;
    }
    ResourceLoader #rld-hint {
        color: rgb(80,80,80);
        margin: 0 0 0 2;
    }
    ResourceLoader #rld-detail {
        display: none;
        height: auto;
        color: rgb(100,100,100);
        margin: 0 1 0 2;
    }
    ResourceLoader #rld-empty {
        color: $text-muted;
        text-style: italic;
        margin: 1 0 0 2;
    }
    """

    # -- Messages (bubbled up from this widget) ------------------------

    class Dismissed(Message):
        """Posted when the user presses Escape."""

    class StateChanged(Message):
        """Posted when a load state changes."""

        def __init__(self, resource: Resource, old_state: LoadState, new_state: LoadState) -> None:
            super().__init__()
            self.resource = resource
            self.old_state = old_state
            self.new_state = new_state

    # -- Reactives -----------------------------------------------------

    show_ids: reactive[bool] = reactive(False)

    # -- Init / compose ------------------------------------------------

    def __init__(self, view_model: ResourceLoaderViewModel | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._vm = view_model or ResourceLoaderViewModel()
        self._spinner_timer = None

    # -- Properties that read/write through to the view model -------------

    @property
    def _resources(self) -> list[Resource]:
        return self._vm.resources

    @_resources.setter
    def _resources(self, value: list[Resource]) -> None:
        self._vm.resources = value

    @property
    def _states(self) -> dict[tuple[str, int], LoadState]:
        return self._vm.states

    @_states.setter
    def _states(self, value: dict[tuple[str, int], LoadState]) -> None:
        self._vm.states = value

    @property
    def _spinner_frame(self) -> int:
        return self._vm.spinner_frame

    @_spinner_frame.setter
    def _spinner_frame(self, value: int) -> None:
        self._vm.spinner_frame = value

    def compose(self) -> ComposeResult:
        yield Static("", id="rld-empty")
        yield Static("", id="rld-detail")
        yield _LoaderTree(self, id="rld-tree")
        yield _LoaderHint(id="rld-hint")

    def on_mount(self) -> None:
        self.show_ids = self._vm.show_ids
        self.query_one("#rld-hint", _LoaderHint).vertical = (
            self._vm.arrangement == Arrangement.VERTICAL
        )
        self._spinner_timer = self.set_interval(0.1, self._tick_spinner, pause=True)
        self._apply_empty_state()
        self._update_spinner_timer()
        if self._resources:
            self._update_hint()
        if self._vm.arrangement == Arrangement.VERTICAL:
            self.call_after_refresh(self._constrain_tree)

    def on_resize(self) -> None:
        if self._vm.arrangement == Arrangement.VERTICAL:
            self._constrain_tree()

    def _constrain_tree(self) -> None:
        # Textual's CSS layout resolves `max-height: N%` against the *full*
        # parent height, ignoring sibling widgets.  This means there is no
        # pure-CSS way to express "fill remaining space after siblings, then
        # scroll."  A `height: auto` tree shrinks to content (good) but has
        # no upper bound (no scrollbar ever).  A `height: 1fr` tree fills
        # all remaining space (scrollbar works) but expands even when content
        # is small, pushing the hint to the very bottom of the dock area.
        #
        # The workaround is to keep the tree at `height: auto` and set its
        # `max_height` programmatically to the space that actually remains
        # after the other children (detail, hint, empty label) are measured.
        # The extra margin of 6 accounts for the tree's own margin (1 on
        # each side) plus spacing from surrounding widgets.
        tree = self._tree
        siblings_height = sum(
            child.size.height for child in self.children if child is not tree
        )
        available = self.size.height - siblings_height - 6
        if available > 0:
            tree.styles.max_height = available

    def _tick_spinner(self) -> None:
        self._spinner_frame = (self._spinner_frame + 1) % len(_SPINNER_FRAMES)
        self._tree._invalidate_label_cache()

    def _update_spinner_timer(self) -> None:
        has_pending = any(s == LoadState.PENDING for s in self._states.values())
        if self._spinner_timer is not None:
            if has_pending:
                self._spinner_timer.resume()
            else:
                self._spinner_timer.pause()

    @property
    def _tree(self) -> _LoaderTree:
        return self.query_one("#rld-tree", _LoaderTree)

    # -- Focus delegation ----------------------------------------------

    def focus(self, scroll_visible: bool = True) -> Widget:
        """Delegate focus to the inner tree."""
        return self._tree.focus(scroll_visible)

    # -- Helpers -------------------------------------------------------

    def _is_partially_loaded(self, data: NodeData) -> bool:
        """True if the node has children and not all share the same load state."""
        if isinstance(data, Resource):
            sections = getattr(data, "sections", None) or []
            if not sections:
                return False
            parent_state = self._states.get(("resource", data.id), LoadState.UNLOADED)
            return any(
                self._states.get(("section", s.id), LoadState.UNLOADED) != parent_state
                for s in sections
            )
        elif isinstance(data, ResourceSection):
            resource = next((r for r in self._resources if r.id == data.resource_id), None)
            if resource is None:
                return False
            all_sections = getattr(resource, "sections", None) or []
            children = [s for s in all_sections if s.parent_id == data.id]
            if not children:
                return False
            parent_state = self._states.get(("section", data.id), LoadState.UNLOADED)
            return any(
                self._states.get(("section", c.id), LoadState.UNLOADED) != parent_state
                for c in children
            )
        return False

    # -- Public API ----------------------------------------------------

    def set_resources(self, resources: list[Resource]) -> None:
        """Replace the tree contents with a new list of resources."""
        self._resources = list(resources)
        tree = self._tree
        tree.root.remove_children()
        for resource in resources:
            has_sections = bool(getattr(resource, "sections", None))
            if has_sections:
                tree.root.add(resource.name, data=resource, allow_expand=True)
            else:
                tree.root.add_leaf(resource.name, data=resource)
        tree._refresh_height()
        if tree.root.children:
            tree.move_cursor(tree.root.children[0])
        self._apply_empty_state()
        self._update_hint()

    def get_state(self, resource_id: int) -> LoadState:
        """Return the current load state for a resource."""
        return self._states.get(("resource", resource_id), LoadState.UNLOADED)

    def set_pending(self, resource_id: int) -> None:
        """Set a resource to PENDING state (embedding in progress)."""
        self._states[("resource", resource_id)] = LoadState.PENDING
        self._tree._invalidate_label_cache()
        self._update_spinner_timer()
        self._update_hint()

    def resolve_pending(self, resource_id: int, success: bool) -> None:
        """Resolve a pending resource: DEFAULT on success, UNLOADED on failure."""
        key = ("resource", resource_id)
        if self._states.get(key) != LoadState.PENDING:
            return
        new_state = LoadState.DEFAULT if success else LoadState.UNLOADED
        if new_state == LoadState.UNLOADED:
            self._states.pop(key, None)
        else:
            self._states[key] = new_state
        self._tree._invalidate_label_cache()
        self._update_spinner_timer()
        self._update_hint()

    # -- Reactive watchers ---------------------------------------------

    def watch_show_ids(self) -> None:
        self._vm.show_ids = self.show_ids
        tree = self._tree
        tree._invalidate_label_cache()
        # Padding to accommodate ID text beyond measured label width.
        tree.styles.padding = (0, 2, 0, 0) if self.show_ids else (0, 0, 0, 0)
        # Refresh the detail panel (IDs shown there in vertical arrangement).
        cursor_node = tree.cursor_node
        if cursor_node is not None:
            self._update_detail(cursor_node.data)

    # -- Rendering -----------------------------------------------------

    def _apply_empty_state(self) -> None:
        empty = not self._resources
        self.query_one("#rld-empty", Static).display = empty
        self._tree.display = not empty
        self.query_one("#rld-hint", _LoaderHint).display = not empty
        if empty:
            self.query_one("#rld-empty", Static).update("(No resources linked to this topic)")
            detail = self.query_one("#rld-detail", Static)
            detail.update("")
            detail.display = False

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted[NodeData]) -> None:
        self._update_detail(event.node.data)

    def _update_detail(self, data: NodeData | None) -> None:
        """Update the detail panel with metadata for the highlighted node."""
        detail = self.query_one("#rld-detail", Static)
        if data is None:
            detail.update("")
            detail.display = False
            return

        if isinstance(data, Resource):
            parts: list[str] = []
            parts.append(f"~{_fmt_tokens(data.estimated_tokens)} tokens")
            try:
                chunk_count = len(data.chunks) if data.chunks is not None else 0
            except Exception:
                chunk_count = 0
            parts.append(f"{chunk_count} chunks")
            pref = data.loading_preference.value if data.loading_preference else "—"
            parts.append(pref)
            if self.show_ids:
                parts.append(f"id: {data.id}")
            detail.update(" │ ".join(parts))
            detail.display = True
        elif isinstance(data, ResourceSection):
            parts: list[str] = []
            try:
                chunk_count = len(data.chunks) if data.chunks is not None else 0
            except Exception:
                chunk_count = 0
            parts.append(f"{chunk_count} chunks")
            if self.show_ids:
                parts.append(f"id: {data.id}")
            detail.update(" │ ".join(parts))
            detail.display = True
        else:
            detail.update("")
            detail.display = False

    def _update_hint(self) -> None:
        loaded_count = 0
        total_sections = 0
        for resource in self._resources:
            res_state = self._states.get(("resource", resource.id), LoadState.UNLOADED)
            if res_state in (LoadState.DEFAULT, LoadState.CONTEXT_STUFFED, LoadState.PENDING):
                loaded_count += 1
            sections = getattr(resource, "sections", None) or []
            for section in sections:
                sec_state = self._states.get(("section", section.id), LoadState.UNLOADED)
                if sec_state in (LoadState.DEFAULT, LoadState.CONTEXT_STUFFED):
                    total_sections += 1
        hint = self.query_one("#rld-hint", _LoaderHint)
        hint.loaded = loaded_count
        hint.total = len(self._resources)
        hint.sections = total_sections

    # -- State transitions ---------------------------------------------

    def _set_state(self, node: TreeNode[NodeData], new_state: LoadState) -> None:
        data = node.data
        if data is None:
            return
        key = _state_key(data)
        old_state = self._states.get(key, LoadState.UNLOADED)
        if new_state == LoadState.UNLOADED:
            self._states.pop(key, None)
        else:
            self._states[key] = new_state

        # Propagate to all descendant sections.
        self._propagate_to_descendants(data, new_state)

        # Propagate upward: if all siblings are now unloaded, unload the parent.
        if new_state == LoadState.UNLOADED:
            self._propagate_unload_to_ancestors(data)

        self._tree._invalidate_label_cache()
        self._update_spinner_timer()
        self._update_hint()
        resource = data if isinstance(data, Resource) else _owning_resource(node)
        self.post_message(self.StateChanged(resource, old_state, new_state))

    def _propagate_to_descendants(self, data: NodeData, new_state: LoadState) -> None:
        """Apply *new_state* to all descendant sections of *data*, skipping PENDING."""
        if isinstance(data, Resource):
            sections = getattr(data, "sections", None) or []
        elif isinstance(data, ResourceSection):
            resource = next((r for r in self._resources if r.id == data.resource_id), None)
            if resource is None:
                return
            all_sections = getattr(resource, "sections", None) or []
            sections = []
            queue = [s for s in all_sections if s.parent_id == data.id]
            while queue:
                s = queue.pop(0)
                sections.append(s)
                queue.extend(c for c in all_sections if c.parent_id == s.id)
        else:
            return

        for section in sections:
            key = ("section", section.id)
            if self._states.get(key) == LoadState.PENDING:
                continue
            if new_state == LoadState.UNLOADED:
                self._states.pop(key, None)
            else:
                self._states[key] = new_state

    def _propagate_unload_to_ancestors(self, data: NodeData) -> None:
        """Walk up from *data*: if all children of a parent are UNLOADED, unload the parent too."""
        if isinstance(data, ResourceSection):
            resource = next((r for r in self._resources if r.id == data.resource_id), None)
            if resource is None:
                return
            all_sections = getattr(resource, "sections", None) or []

            # Walk from this section's parent up to the resource.
            current_parent_id = data.parent_id
            while current_parent_id is not None:
                siblings = [s for s in all_sections if s.parent_id == current_parent_id]
                if all(self._states.get(("section", s.id), LoadState.UNLOADED) == LoadState.UNLOADED for s in siblings):
                    parent_key = ("section", current_parent_id)
                    if self._states.get(parent_key) != LoadState.PENDING:
                        self._states.pop(parent_key, None)
                    parent_section = next((s for s in all_sections if s.id == current_parent_id), None)
                    current_parent_id = parent_section.parent_id if parent_section else None
                else:
                    break

            # Check if all top-level sections are unloaded → unload the resource.
            top_sections = [s for s in all_sections if s.parent_id is None]
            if all(self._states.get(("section", s.id), LoadState.UNLOADED) == LoadState.UNLOADED for s in top_sections):
                res_key = ("resource", resource.id)
                if self._states.get(res_key) != LoadState.PENDING:
                    self._states.pop(res_key, None)

    # -- Actions -------------------------------------------------------

    def action_toggle_default(self) -> None:
        """space: unloaded ↔ default, or context-stuffed → default."""
        node = self._tree.cursor_node
        if node is None or node.data is None:
            return
        state = self._states.get(_state_key(node.data), LoadState.UNLOADED)
        if state == LoadState.PENDING:
            return
        if state == LoadState.UNLOADED:
            self._set_state(node, LoadState.DEFAULT)
        elif state == LoadState.DEFAULT:
            self._set_state(node, LoadState.UNLOADED)
        else:  # CONTEXT_STUFFED → DEFAULT
            self._set_state(node, LoadState.DEFAULT)

    def action_toggle_context(self) -> None:
        """ctrl+enter: cycle context-stuffed."""
        node = self._tree.cursor_node
        if node is None or node.data is None:
            return
        state = self._states.get(_state_key(node.data), LoadState.UNLOADED)
        if state == LoadState.PENDING:
            return
        if state == LoadState.UNLOADED:
            self._set_state(node, LoadState.CONTEXT_STUFFED)
        elif state == LoadState.DEFAULT:
            self._set_state(node, LoadState.CONTEXT_STUFFED)
        elif state == LoadState.CONTEXT_STUFFED:
            self._set_state(node, LoadState.UNLOADED)

    def action_dismiss(self) -> None:
        self.post_message(self.Dismissed())
