"""ResourceViewer — docked bottom panel for browsing and linking resources."""

from __future__ import annotations

import enum

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static, Tree

from rhizome.db import Resource, Topic
from rhizome.db.models import LoadingPreference
from rhizome.db.operations import (
    link_resource_to_topic,
    list_resources,
    list_resources_for_topic,
    unlink_resource_from_topic,
)
from rhizome.resources import ResourceManager

from rhizome.tui.types import DatabaseCommitted

from .messages import ActiveTopicChanged
from .resource_linker import ResourceLinker
from .resource_list import ResourceList
from .resource_loader import LoadState, ResourceLoader
from .topic_tree import TopicTree


class ResourceViewMode(enum.IntEnum):
    TOPIC_RESOURCES = 0
    LINK_RESOURCES = 1
    LOAD_RESOURCES = 2


_MODE_LABELS = {
    ResourceViewMode.TOPIC_RESOURCES: "topic resources",
    ResourceViewMode.LINK_RESOURCES: "link resources",
    ResourceViewMode.LOAD_RESOURCES: "load resources",
}

# Pane IDs visible in each mode (for ctrl+left/right focus cycling).
_MODE_PANES: dict[ResourceViewMode, list[str]] = {
    ResourceViewMode.TOPIC_RESOURCES: ["rv-tree-pane", "rv-resource-pane"],
    ResourceViewMode.LINK_RESOURCES: ["rv-tree-pane", "rv-linker-pane"],
    ResourceViewMode.LOAD_RESOURCES: ["rv-loader-pane"],
}


class ResourceViewer(Vertical):
    """Docked bottom panel for browsing and linking resources to topics."""

    DEFAULT_CSS = """
    ResourceViewer {
        height: auto;
        padding: 0 0 0 1;
        margin-top: 1;
        background: $surface-darken-1;
        border-top: solid rgb(60, 60, 60);
        border-title-color: rgb(180, 180, 180);
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
        padding-left: 3;
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
    ResourceViewer #rv-loader-pane {
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

    /* -- Mode: load resources (no tree, loader takes full width) -- */
    ResourceViewer.--mode-load #rv-tree-pane {
        display: none;
    }
    ResourceViewer.--mode-load #rv-resource-pane {
        display: none;
    }
    ResourceViewer.--mode-load #rv-loader-pane {
        display: block;
        width: 100%;
    }
    """

    BINDINGS = [
        Binding("tab", "cycle_mode", show=False),
        Binding("ctrl+left", "focus_prev_pane", show=False),
        Binding("ctrl+right", "focus_next_pane", show=False),
        Binding("ctrl+j", "select_active_topic", show=False, priority=True),
        Binding("i", "toggle_ids", show=False),
        Binding("escape", "dismiss_viewer", show=False),
    ]

    class Dismissed(Message):
        """Posted when the user dismisses the resource viewer."""

    view_mode: reactive[ResourceViewMode] = reactive(ResourceViewMode.TOPIC_RESOURCES)
    show_ids: reactive[bool] = reactive(False)

    def __init__(self, session_factory=None, resource_manager: ResourceManager | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._session_factory = session_factory
        self._resource_manager = resource_manager
        self._resource_cache: dict[int, list[Resource]] = {}
        self._loader_resource_cache: dict[int, list[Resource]] = {}
        self._resource_cursor_cache: dict[int, int] = {}
        self._all_resources: list[Resource] | None = None
        self._linked_ids_cache: dict[int, set[int]] = {}
        self._current_topic_id: int | None = None
        self._active_topic: Topic | None = None
        self._active_topic_path: list[str] = []
        self._linker_toggle_in_progress: bool = False
        self._loader_toggle_in_progress: bool = False

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
            with Vertical(id="rv-loader-pane"):
                yield Static("Load Resources", id="rv-loader-title", classes="pane-title")
                yield ResourceLoader(id="rv-resource-loader")
        yield Static(" ", id="rv-bottom-spacer")

    def on_mount(self) -> None:
        self.border_title = "Resources [dim]ctrl+r to focus[/dim]"
        self._update_help_text()

    # ------------------------------------------------------------------
    # Help text
    # ------------------------------------------------------------------

    def _update_help_text(self) -> None:
        mode_label = _MODE_LABELS[self.view_mode]
        parts = [f"\\[{mode_label}]", "tab: cycle view"]
        if len(_MODE_PANES[self.view_mode]) > 1:
            parts.append("ctrl+\u2190/\u2192: switch pane")
        if self.view_mode != ResourceViewMode.LOAD_RESOURCES:
            parts.append("ctrl+enter: set topic")
        parts.append("i: toggle ids")
        parts.append("esc: close")
        self.query_one("#rv-help", Static).update("  ".join(parts))

    # ------------------------------------------------------------------
    # View mode cycling
    # ------------------------------------------------------------------

    _MODE_CSS_CLASSES = {
        ResourceViewMode.TOPIC_RESOURCES: None,
        ResourceViewMode.LINK_RESOURCES: "--mode-link",
        ResourceViewMode.LOAD_RESOURCES: "--mode-load",
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
        if new_value == ResourceViewMode.LOAD_RESOURCES:
            self.query_one("#rv-resource-loader", ResourceLoader).focus()
            self.call_after_refresh(self._load_loader_for_active_topic)
        else:
            self.query_one(TopicTree).focus()
            self.call_after_refresh(self._load_data_for_current_topic)

    def action_cycle_mode(self) -> None:
        next_val = (self.view_mode + 1) % len(ResourceViewMode)
        self.view_mode = ResourceViewMode(next_val)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    async def _load_data_for_current_topic(self) -> None:
        if self.view_mode == ResourceViewMode.LOAD_RESOURCES:
            await self._load_loader_for_active_topic()
            return
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
            if self._linker_toggle_in_progress:
                self._linker_toggle_in_progress = False
                linker.update_linked_ids(self._linked_ids_cache[topic.id])
            else:
                linker.set_resources(self._all_resources, self._linked_ids_cache[topic.id])

    def set_active_topic(self, topic: Topic | None, path: list[str] | None = None) -> None:
        """Called by ChatPane when the active topic changes."""
        self._active_topic = topic
        self._active_topic_path = path or []
        self.query_one(TopicTree).active_topic_id = topic.id if topic else None
        if self.view_mode == ResourceViewMode.LOAD_RESOURCES:
            self.call_after_refresh(self._load_loader_for_active_topic)

    async def _load_loader_for_active_topic(self) -> None:
        """Load the resource loader using the stored active topic."""
        topic = self._active_topic
        loader = self.query_one("#rv-resource-loader", ResourceLoader)
        title_static = self.query_one("#rv-loader-title", Static)
        if topic is None:
            title_static.update("Load Resources [dim](no active topic)[/dim]")
            loader.set_resources([])
            return
        path_str = " > ".join(self._active_topic_path) if self._active_topic_path else topic.name
        title_static.update(f"Load Resources [dim]— {path_str}[/dim]")
        # The loader needs chunks eagerly loaded (for chunk count display).
        # The shared _resource_cache may hold chunk-less resources from the
        # other view modes, so use a separate cache for the loader.
        if topic.id not in self._loader_resource_cache:
            async with self._session_factory() as session:
                resources = await list_resources_for_topic(session, topic.id, load_chunks=True)
                self._loader_resource_cache[topic.id] = resources
        if self._loader_toggle_in_progress:
            self._loader_toggle_in_progress = False
            saved_cursor = loader.cursor
            loader.set_resources(self._loader_resource_cache[topic.id])
            loader.cursor = min(saved_cursor, max(len(self._loader_resource_cache[topic.id]) - 1, 0))
        else:
            loader.set_resources(self._loader_resource_cache[topic.id])

    # ------------------------------------------------------------------
    # Topic highlight — load data when cursor moves in the tree
    # ------------------------------------------------------------------

    async def on_tree_node_highlighted(self, event: Tree.NodeHighlighted[Topic]) -> None:
        if self.view_mode == ResourceViewMode.LOAD_RESOURCES:
            return
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

        self._linker_toggle_in_progress = True
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
        self._loader_resource_cache.pop(self._current_topic_id, None)
        # Update linked IDs cache in place
        if event.linked:
            self._linked_ids_cache.setdefault(self._current_topic_id, set()).add(event.resource.id)
        else:
            self._linked_ids_cache.get(self._current_topic_id, set()).discard(event.resource.id)

    # ------------------------------------------------------------------
    # Load state changes (from ResourceLoader)
    # ------------------------------------------------------------------

    # Token threshold for the "auto" loading preference: resources below
    # this estimate are context-stuffed, above are vector-embedded.
    AUTO_CONTEXT_STUFF_TOKEN_LIMIT = 10_000

    def on_resource_loader_state_changed(self, event: ResourceLoader.StateChanged) -> None:
        event.stop()
        if self._resource_manager is None:
            return

        resource = event.resource
        rid = resource.id
        new = event.new_state

        if new == LoadState.UNLOADED:
            self._resource_manager.full_unload(rid)
        elif new == LoadState.CONTEXT_STUFFED:
            self._resource_manager.set_context_stuffed(rid, True)
        elif new == LoadState.DEFAULT:
            self._apply_loading_preference(resource)

    def _apply_loading_preference(self, resource: Resource) -> None:
        """Route a DEFAULT (auto) load through the resource's loading preference."""
        rid = resource.id
        pref = resource.loading_preference
        tokens = resource.estimated_tokens or 0

        if pref == LoadingPreference.context_stuff:
            self._resource_manager.set_context_stuffed(rid, True)
        elif pref == LoadingPreference.vector_store:
            self._load_with_embeddings(resource)
        else:
            # auto: context-stuff if small enough, otherwise vector-embed
            tokens = resource.estimated_tokens or 0
            if tokens <= self.AUTO_CONTEXT_STUFF_TOKEN_LIMIT:
                self._resource_manager.set_context_stuffed(rid, True)
            else:
                self._load_with_embeddings(resource)

    def _load_with_embeddings(self, resource: Resource) -> None:
        """Ensure embeddings exist, then mark the resource as vector-loaded.

        Sets the ResourceLoader to PENDING while embeddings are computed.
        On success, flips to DEFAULT and sets vector_loaded. On failure,
        reverts to UNLOADED.
        """
        self._loader_toggle_in_progress = True
        loader = self.query_one("#rv-resource-loader", ResourceLoader)
        loader.set_pending(resource.id)
        self.run_worker(self._ensure_embeddings(resource), exclusive=False)

    async def _ensure_embeddings(self, resource: Resource) -> None:
        rid = resource.id
        success = await self._resource_manager.ensure_embedded(rid)

        # Invalidate loader cache so chunk counts refresh from DB.
        if self._active_topic is not None:
            self._loader_resource_cache.pop(self._active_topic.id, None)
            await self._load_loader_for_active_topic()

        loader = self.query_one("#rv-resource-loader", ResourceLoader)
        loader.resolve_pending(rid, success)

        if success:
            self._resource_manager.set_vector_loaded(rid, True)

    # ------------------------------------------------------------------
    # Pane focus navigation (ctrl+left / ctrl+right)
    # ------------------------------------------------------------------

    def _get_right_pane_widget(self):
        """Return the focusable widget in the currently visible right pane, or None if empty."""
        mode = self.view_mode
        if mode == ResourceViewMode.TOPIC_RESOURCES:
            rl = self.query_one("#rv-resource-list", ResourceList)
            return rl if rl._resources else None
        elif mode == ResourceViewMode.LINK_RESOURCES:
            lk = self.query_one("#rv-resource-linker", ResourceLinker)
            return lk if lk._resources else None
        elif mode == ResourceViewMode.LOAD_RESOURCES:
            ld = self.query_one("#rv-resource-loader", ResourceLoader)
            return ld if ld._resources else None
        return None

    def action_focus_next_pane(self) -> None:
        pane_ids = _MODE_PANES[self.view_mode]
        if len(pane_ids) < 2:
            return  # single-pane mode (e.g. LOAD_RESOURCES), nothing to cycle
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

    def on_resource_loader_dismissed(self, event: ResourceLoader.Dismissed) -> None:
        event.stop()
        self.action_dismiss_viewer()

    # ------------------------------------------------------------------
    # Data refresh (called on DB changes)
    # ------------------------------------------------------------------

    async def notify_database_committed(self, event: DatabaseCommitted) -> None:
        if not self.has_class("--visible"):
            return
        tables = event.changed_tables

        if not tables:
            # Unknown change — full refresh
            self._resource_cache.clear()
            self._loader_resource_cache.clear()
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
            self._loader_resource_cache.clear()

        if tables & {"topic_resource"}:
            self._resource_cache.clear()
            self._loader_resource_cache.clear()
            self._linked_ids_cache.clear()

        if tables & {"topic", "resource", "topic_resource"}:
            if not refreshed_tree:
                await self._load_data_for_current_topic()

    # ------------------------------------------------------------------
    # Active topic selection (ctrl+enter from topic tree)
    # ------------------------------------------------------------------

    def action_select_active_topic(self) -> None:
        """Toggle the active topic: select if different, clear if same."""
        if self.view_mode == ResourceViewMode.LOAD_RESOURCES:
            # Tree not visible — forward to the loader's context-stuff toggle.
            self.query_one("#rv-resource-loader", ResourceLoader).action_toggle_context()
            return
        tree = self.query_one(TopicTree)
        node = tree.cursor_node
        if node is None or node.data is None:
            return

        topic = node.data
        if tree.active_topic_id == topic.id:
            # Clear: re-selecting the same topic deactivates it
            tree.active_topic_id = None
            self.post_message(ActiveTopicChanged(None, []))
        else:
            # Select
            path: list[str] = []
            current = node
            while current.parent is not None:
                if current.data is not None:
                    path.append(current.data.name)
                current = current.parent
            path.reverse()
            tree.active_topic_id = topic.id
            self.post_message(ActiveTopicChanged(topic, path))

    # ------------------------------------------------------------------
    # Toggle topic IDs
    # ------------------------------------------------------------------

    def action_toggle_ids(self) -> None:
        self.show_ids = not self.show_ids

    def watch_show_ids(self, value: bool) -> None:
        self.query_one(TopicTree).show_ids = value
        self.query_one("#rv-resource-list", ResourceList).show_ids = value
        self.query_one("#rv-resource-linker", ResourceLinker).show_ids = value
        self.query_one("#rv-resource-loader", ResourceLoader).show_ids = value

    # ------------------------------------------------------------------
    # Dismiss / focus
    # ------------------------------------------------------------------

    def action_dismiss_viewer(self) -> None:
        self.post_message(self.Dismissed())

    def focus(self, scroll_visible: bool = True) -> None:
        if self.view_mode == ResourceViewMode.LOAD_RESOURCES:
            self.query_one("#rv-resource-loader", ResourceLoader).focus(scroll_visible)
        else:
            self.query_one(TopicTree).focus(scroll_visible)
