"""ResourceViewer — docked bottom panel for browsing and linking resources."""

from __future__ import annotations

import enum

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static, Tree

from rhizome.db import Resource, Topic
from rhizome.db.operations import (
    link_resource_to_topic,
    list_resources,
    list_resources_for_topic,
    unlink_resource_from_topic,
)

from rhizome.tui.types import DatabaseCommitted

from .resource_linker import ResourceLinker
from .resource_list import ResourceList
from .topic_tree import TopicTree


class ResourceViewMode(enum.IntEnum):
    TOPIC_RESOURCES = 0
    LINK_RESOURCES = 1
    EXPANDED = 2


_MODE_LABELS = {
    ResourceViewMode.TOPIC_RESOURCES: "topic resources",
    ResourceViewMode.LINK_RESOURCES: "link resources",
    ResourceViewMode.EXPANDED: "expanded (coming soon)",
}

# Pane IDs visible in each mode (for ctrl+left/right focus cycling).
_MODE_PANES: dict[ResourceViewMode, list[str]] = {
    ResourceViewMode.TOPIC_RESOURCES: ["rv-tree-pane", "rv-resource-pane"],
    ResourceViewMode.LINK_RESOURCES: ["rv-tree-pane", "rv-linker-pane"],
    ResourceViewMode.EXPANDED: ["rv-tree-pane"],
}


class ResourceViewer(Vertical):
    """Docked bottom panel for browsing and linking resources to topics."""

    DEFAULT_CSS = """
    ResourceViewer {
        height: auto;
        padding: 0 0 0 1;
        border-top: solid rgb(60, 60, 60);
    }
    ResourceViewer #rv-help {
        color: $text-muted;
        margin: 1 0 0 1;
    }
    ResourceViewer #rv-split {
        height: auto;
    }
    ResourceViewer #rv-tree-pane {
        width: 30%;
        height: auto;
    }
    ResourceViewer #rv-resource-pane {
        width: 70%;
        height: auto;
    }
    ResourceViewer #rv-linker-pane {
        display: none;
        width: 70%;
        height: auto;
    }
    ResourceViewer #rv-expanded-pane {
        display: none;
        width: 70%;
        height: auto;
    }
    ResourceViewer .pane-title {
        text-style: bold;
        color: $text-muted;
        margin: 1 0 0 1;
    }
    ResourceViewer TopicTree {
        height: auto;
        width: auto;
        scrollbar-size: 0 0;
        padding-left: 2;
        margin-bottom: 1;
        background: transparent;
    }
    ResourceViewer TopicTree:focus > .tree--cursor {
        background: transparent;
        color: rgb(255,80,80);
        text-style: bold;
    }
    ResourceViewer TopicTree > .tree--cursor {
        background: transparent;
        color: rgb(180,60,60);
        text-style: bold;
    }

    /* -- Mode: link resources -- */
    ResourceViewer.--mode-link #rv-resource-pane {
        display: none;
    }
    ResourceViewer.--mode-link #rv-linker-pane {
        display: block;
    }

    /* -- Mode: expanded -- */
    ResourceViewer.--mode-expanded #rv-resource-pane {
        display: none;
    }
    ResourceViewer.--mode-expanded #rv-expanded-pane {
        display: block;
    }
    """

    BINDINGS = [
        Binding("tab", "cycle_mode", show=False),
        Binding("ctrl+left", "focus_prev_pane", show=False),
        Binding("ctrl+right", "focus_next_pane", show=False),
        Binding("escape", "dismiss_viewer", show=False),
    ]

    class Dismissed(Message):
        """Posted when the user dismisses the resource viewer."""

    view_mode: reactive[ResourceViewMode] = reactive(ResourceViewMode.TOPIC_RESOURCES)

    def __init__(self, session_factory=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._session_factory = session_factory
        self._resource_cache: dict[int, list[Resource]] = {}
        self._resource_cursor_cache: dict[int, int] = {}
        self._all_resources: list[Resource] | None = None
        self._linked_ids_cache: dict[int, set[int]] = {}
        self._current_topic_id: int | None = None

    def compose(self):
        yield Static("", id="rv-help")
        with Horizontal(id="rv-split"):
            with Vertical(id="rv-tree-pane"):
                yield Static("Topics", classes="pane-title")
                yield TopicTree(self._session_factory)
            with Vertical(id="rv-resource-pane"):
                yield Static("Resources", classes="pane-title")
                yield ResourceList(id="rv-resource-list")
            with Vertical(id="rv-linker-pane"):
                yield Static("Link Resources", classes="pane-title")
                yield ResourceLinker(id="rv-resource-linker")
            with Vertical(id="rv-expanded-pane"):
                yield Static("(Coming soon)", classes="pane-title")

    def on_mount(self) -> None:
        self.border_title = "Resources"
        self._update_help_text()

    # ------------------------------------------------------------------
    # Help text
    # ------------------------------------------------------------------

    def _update_help_text(self) -> None:
        mode_label = _MODE_LABELS[self.view_mode]
        parts = [f"\\[{mode_label}]", "tab: cycle view"]
        if len(_MODE_PANES[self.view_mode]) > 1:
            parts.append("ctrl+\u2190/\u2192: switch pane")
        parts.append("esc: close")
        self.query_one("#rv-help", Static).update("  ".join(parts))

    # ------------------------------------------------------------------
    # View mode cycling
    # ------------------------------------------------------------------

    _MODE_CSS_CLASSES = {
        ResourceViewMode.TOPIC_RESOURCES: None,
        ResourceViewMode.LINK_RESOURCES: "--mode-link",
        ResourceViewMode.EXPANDED: "--mode-expanded",
    }

    def watch_view_mode(self, old_value: ResourceViewMode, new_value: ResourceViewMode) -> None:
        # Save cursor from old mode
        if self._current_topic_id is not None and old_value == ResourceViewMode.TOPIC_RESOURCES:
            resource_list = self.query_one("#rv-resource-list", ResourceList)
            self._resource_cursor_cache[self._current_topic_id] = resource_list.cursor

        # Swap CSS classes
        old_cls = self._MODE_CSS_CLASSES.get(old_value)
        if old_cls:
            self.remove_class(old_cls)
        new_cls = self._MODE_CSS_CLASSES.get(new_value)
        if new_cls:
            self.add_class(new_cls)

        self._update_help_text()
        self.query_one(TopicTree).focus()
        self.call_after_refresh(self._load_data_for_current_topic)

    def action_cycle_mode(self) -> None:
        next_val = (self.view_mode + 1) % len(ResourceViewMode)
        self.view_mode = ResourceViewMode(next_val)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    async def _load_data_for_current_topic(self) -> None:
        tree = self.query_one(TopicTree)
        node = tree.cursor_node
        if node is None or node.data is None:
            return
        await self._load_for_topic(node.data)

    async def _load_for_topic(self, topic: Topic) -> None:
        session_factory = self._session_factory
        mode = self.view_mode

        if mode == ResourceViewMode.TOPIC_RESOURCES:
            if topic.id not in self._resource_cache:
                async with session_factory() as session:
                    resources = await list_resources_for_topic(session, topic.id)
                    self._resource_cache[topic.id] = resources
            resource_list = self.query_one("#rv-resource-list", ResourceList)
            resource_list.set_resources(self._resource_cache[topic.id])
            if topic.id in self._resource_cursor_cache:
                resource_list.cursor = min(
                    self._resource_cursor_cache[topic.id],
                    max(len(self._resource_cache[topic.id]) - 1, 0),
                )
                resource_list._scroll_cursor_visible()

        elif mode == ResourceViewMode.LINK_RESOURCES:
            if self._all_resources is None:
                async with session_factory() as session:
                    self._all_resources = await list_resources(session)
                self._all_resources.sort(key=lambda r: r.name.lower())

            if topic.id not in self._linked_ids_cache:
                async with session_factory() as session:
                    linked = await list_resources_for_topic(session, topic.id)
                    self._linked_ids_cache[topic.id] = {r.id for r in linked}

            linker = self.query_one("#rv-resource-linker", ResourceLinker)
            linker.set_resources(self._all_resources, self._linked_ids_cache[topic.id])

    # ------------------------------------------------------------------
    # Topic highlight — load data when cursor moves in the tree
    # ------------------------------------------------------------------

    async def on_tree_node_highlighted(self, event: Tree.NodeHighlighted[Topic]) -> None:
        topic = event.node.data
        if topic is None:
            return

        # Save cursor for previous topic
        if self._current_topic_id is not None and self.view_mode == ResourceViewMode.TOPIC_RESOURCES:
            resource_list = self.query_one("#rv-resource-list", ResourceList)
            self._resource_cursor_cache[self._current_topic_id] = resource_list.cursor
        self._current_topic_id = topic.id

        await self._load_for_topic(topic)

    # ------------------------------------------------------------------
    # Link toggling (from ResourceLinker)
    # ------------------------------------------------------------------

    async def on_resource_linker_link_toggled(self, event: ResourceLinker.LinkToggled) -> None:
        event.stop()
        if self._current_topic_id is None:
            return

        session_factory = self._session_factory
        async with session_factory() as session:
            if event.linked:
                await link_resource_to_topic(
                    session, resource_id=event.resource.id, topic_id=self._current_topic_id
                )
            else:
                await unlink_resource_from_topic(
                    session, resource_id=event.resource.id, topic_id=self._current_topic_id
                )
            await session.commit()

        # Invalidate the topic-resource cache so view 1 picks up changes
        self._resource_cache.pop(self._current_topic_id, None)
        # Update linked IDs cache in place
        if event.linked:
            self._linked_ids_cache.setdefault(self._current_topic_id, set()).add(event.resource.id)
        else:
            self._linked_ids_cache.get(self._current_topic_id, set()).discard(event.resource.id)

    # ------------------------------------------------------------------
    # Pane focus navigation (ctrl+left / ctrl+right)
    # ------------------------------------------------------------------

    def _get_right_pane_widget(self):
        """Return the focusable widget in the currently visible right pane."""
        mode = self.view_mode
        if mode == ResourceViewMode.TOPIC_RESOURCES:
            return self.query_one("#rv-resource-list", ResourceList)
        elif mode == ResourceViewMode.LINK_RESOURCES:
            return self.query_one("#rv-resource-linker", ResourceLinker)
        return None

    def action_focus_next_pane(self) -> None:
        focused = self.screen.focused
        tree = self.query_one(TopicTree)
        right = self._get_right_pane_widget()
        if focused is tree and right is not None:
            right.focus()
        else:
            tree.focus()

    def action_focus_prev_pane(self) -> None:
        self.action_focus_next_pane()

    # ------------------------------------------------------------------
    # Child dismissals — return focus to tree
    # ------------------------------------------------------------------

    def on_resource_list_dismissed(self, event: ResourceList.Dismissed) -> None:
        event.stop()
        self.query_one(TopicTree).focus()

    def on_resource_linker_dismissed(self, event: ResourceLinker.Dismissed) -> None:
        event.stop()
        self.query_one(TopicTree).focus()

    # ------------------------------------------------------------------
    # Data refresh (called on DB changes)
    # ------------------------------------------------------------------

    async def on_database_committed(self, event: DatabaseCommitted) -> None:
        if not self.has_class("--visible"):
            return
        tables = event.changed_tables

        if not tables:
            # Unknown change — full refresh
            self._resource_cache.clear()
            self._all_resources = None
            self._linked_ids_cache.clear()
            tree = self.query_one(TopicTree)
            await tree.invalidate_and_refresh()
            await self._load_data_for_current_topic()
            return

        refreshed_tree = False
        if tables & {"topic"}:
            tree = self.query_one(TopicTree)
            await tree.invalidate_and_refresh()
            refreshed_tree = True

        if tables & {"resource"}:
            self._all_resources = None
            self._resource_cache.clear()

        if tables & {"topic_resource"}:
            self._resource_cache.clear()
            self._linked_ids_cache.clear()

        if tables & {"topic", "resource", "topic_resource"}:
            if not refreshed_tree:
                await self._load_data_for_current_topic()

    # ------------------------------------------------------------------
    # Dismiss / focus
    # ------------------------------------------------------------------

    def action_dismiss_viewer(self) -> None:
        self.post_message(self.Dismissed())

    def focus(self, scroll_visible: bool = True) -> None:
        self.query_one(TopicTree).focus(scroll_visible)
