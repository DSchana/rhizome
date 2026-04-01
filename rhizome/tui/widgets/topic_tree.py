"""Interactive topic tree viewer built on Textual's Tree widget."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button, Static, Tree
from textual.widgets._tree import TreeNode

from rhizome.db import KnowledgeEntry, Topic
from rhizome.db.operations import count_entries, list_children, list_entries, list_root_topics

from .entry_list import EntryList


class TopicTree(Tree[Topic]):
    """The actual Tree widget — used inside TopicTree container."""

    def __init__(self, session_factory=None) -> None:
        super().__init__("Topics")
        self.show_root = False
        self._session_factory = session_factory

    def _refresh_height(self) -> None:
        """Set height to match the number of visible lines."""
        line_count = len(self._tree_lines)
        self.styles.height = max(line_count, 1)

    async def on_mount(self) -> None:
        session_factory = self._session_factory
        async with session_factory() as session:
            roots = await list_root_topics(session)
            has_children = {
                topic.id: bool(await list_children(session, topic.id))
                for topic in roots
            }
        for topic in roots:
            if has_children[topic.id]:
                self.root.add(topic.name, data=topic, allow_expand=True)
            else:
                self.root.add_leaf(topic.name, data=topic)
        self._refresh_height()
        if self.root.children:
            self.move_cursor(self.root.children[0])

    async def invalidate_and_refresh(self) -> None:
        """Clear the tree and reload from DB, preserving the cursor topic."""
        prev_topic_id = None
        if self.cursor_node is not None and self.cursor_node.data is not None:
            prev_topic_id = self.cursor_node.data.id
        self.root.remove_children()
        self._refresh_height()
        session_factory = self._session_factory
        async with session_factory() as session:
            roots = await list_root_topics(session)
            has_children = {
                topic.id: bool(await list_children(session, topic.id))
                for topic in roots
            }
        restore_node = None
        for topic in roots:
            if has_children[topic.id]:
                node = self.root.add(topic.name, data=topic, allow_expand=True)
            else:
                node = self.root.add_leaf(topic.name, data=topic)
            if topic.id == prev_topic_id:
                restore_node = node
        self._refresh_height()
        if restore_node is not None:
            self.move_cursor(restore_node)
        elif self.root.children:
            self.move_cursor(self.root.children[0])

    async def on_tree_node_expanded(self, event: Tree.NodeExpanded[Topic]) -> None:
        node: TreeNode[Topic] = event.node
        if node.data is None:
            return
        if node.children:
            self._refresh_height()
            return
        session_factory = self._session_factory
        async with session_factory() as session:
            children = await list_children(session, node.data.id)
            has_grandchildren = {
                child.id: bool(await list_children(session, child.id))
                for child in children
            }
        for child in children:
            if has_grandchildren[child.id]:
                node.add(child.name, data=child, allow_expand=True)
            else:
                node.add_leaf(child.name, data=child)
        self._refresh_height()

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed[Topic]) -> None:
        self._refresh_height()

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
        elif event.key == "enter":
            # Suppress default Tree Enter (which fires NodeSelected).
            # Topic selection is handled by ctrl+j in the parent container.
            event.stop()
            event.prevent_default()
        else:
            super()._on_key(event) # pyright: ignore[reportUnusedCoroutine]


class TopicTreeViewer(Vertical):
    """A bordered container with a tree viewer for browsing topics."""

    DEFAULT_CSS = """
    TopicTreeViewer {
        height: auto;
        margin-top: 1;
        border: round rgb(86, 126, 160);
        padding: 0 0 1 1;
    }
    TopicTreeViewer #topic-tree-split {
        height: auto;
    }
    TopicTreeViewer #topic-tree-left {
        width: 1fr;
        height: auto;
    }
    TopicTreeViewer #topic-tree-help {
        color: $text-muted;
        margin: 1 0 0 1;
    }
    TopicTreeViewer #topic-tree-scroll {
        height: auto;
        overflow-x: auto;
        overflow-y: hidden;
        margin-top: 1;
    }
    TopicTreeViewer TopicTree {
        height: auto;
        width: auto;
        scrollbar-size: 0 0;
        padding-left: 2;
        margin-bottom: 1;
        background: transparent;
    }
    TopicTreeViewer TopicTree:focus > .tree--cursor {
        background: transparent;
        color: rgb(255,80,80);
        text-style: bold;
    }
    TopicTreeViewer TopicTree > .tree--cursor {
        background: transparent;
        color: rgb(180,60,60);
        text-style: bold;
    }
    TopicTreeViewer #entry-count-hint {
        color: $text-muted;
        margin: 0 0 0 3;
    }
    TopicTreeViewer #topic-entry-viewer {
        display: none;
    }
    TopicTreeViewer #topic-tree-dismiss {
        dock: right;
        width: 3;
        min-width: 3;
        height: 1;
        background: transparent;
        border: none;
        color: $text-muted;
        margin: 0;
        padding: 0;
    }
    TopicTreeViewer #topic-tree-dismiss:hover {
        color: $error;
    }
    TopicTreeViewer.--show-entries {
        height: auto;
    }
    TopicTreeViewer.--show-entries #topic-tree-split {
        height: auto;
    }
    TopicTreeViewer.--show-entries #topic-tree-left {
        width: 30%;
    }
    TopicTreeViewer.--show-entries #topic-entry-viewer {
        display: block;
        width: 70%;
        height: auto;
    }
    TopicTreeViewer.--show-entries #entry-count-hint {
        display: none;
    }
    """

    BINDINGS = [
        Binding("ctrl+a", "toggle_entries", show=False),
        Binding("ctrl+j", "select_topic", show=False),
        Binding("escape", "dismiss_viewer", show=False),
    ]

    class TopicSelected(Message):
        """Posted when the user selects a topic with Enter."""

        def __init__(self, topic: Topic, path: list[str]) -> None:
            super().__init__()
            self.topic = topic
            self.path = path

    class Dismissed(Message):
        """Posted when the user clicks the dismiss button."""

    show_entries: reactive[bool] = reactive(False)

    def __init__(self, session_factory=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._session_factory = session_factory
        self._entry_cache: dict[int, list[KnowledgeEntry]] = {}
        self._entry_count_cache: dict[int, int] = {}
        self._entry_cursor_cache: dict[int, int] = {}
        self._current_topic_id: int | None = None

    def compose(self):
        yield Button("x", id="topic-tree-dismiss")
        yield Static(
            "arrows: navigate  ctrl+a: show entries  enter: select topic  esc: dismiss",
            id="topic-tree-help",
        )
        with Horizontal(id="topic-tree-split"):
            with Vertical(id="topic-tree-left"):
                with ScrollableContainer(id="topic-tree-scroll"):
                    yield TopicTree(self._session_factory)
                yield Static("", id="entry-count-hint")
            yield EntryList(id="topic-entry-viewer")

    def on_mount(self) -> None:
        self.border_title = "Topics"

    # ------------------------------------------------------------------
    # Help text
    # ------------------------------------------------------------------

    def _update_help_text(self) -> None:
        if self.show_entries:
            text = "arrows: navigate  enter: view entries  ctrl+j: select topic  ctrl+a: hide entries  esc: dismiss"
        else:
            text = "arrows: navigate  ctrl+a: show entries  enter: select topic  esc: dismiss"
        self.query_one("#topic-tree-help", Static).update(text)

    # ------------------------------------------------------------------
    # Toggle entry viewer
    # ------------------------------------------------------------------

    async def watch_show_entries(self, value: bool) -> None:
        if value:
            self.add_class("--show-entries")
            await self._load_entries_for_current_topic()
        else:
            self.remove_class("--show-entries")
        self._update_help_text()

    def action_toggle_entries(self) -> None:
        self.show_entries = not self.show_entries

    async def _load_entries_for_current_topic(self) -> None:
        tree = self.query_one(TopicTree)
        node = tree.cursor_node
        if node is None or node.data is None:
            return
        topic = node.data
        if topic.id not in self._entry_cache:
            session_factory = self._session_factory
            async with session_factory() as session:
                entries = await list_entries(session, topic.id)
                self._entry_cache[topic.id] = entries
                self._entry_count_cache[topic.id] = len(entries)
        viewer = self.query_one("#topic-entry-viewer", EntryList)
        viewer.set_entries(self._entry_cache[topic.id])
        if topic.id in self._entry_cursor_cache:
            viewer.cursor = min(
                self._entry_cursor_cache[topic.id],
                max(len(self._entry_cache[topic.id]) - 1, 0),
            )
        viewer._scroll_cursor_visible()

    # ------------------------------------------------------------------
    # Horizontal scroll to keep highlighted node visible
    # ------------------------------------------------------------------

    def _scroll_to_node(self, node: TreeNode[Topic]) -> None:
        """Scroll the tree container so the highlighted node is visible."""
        scroll = self.query_one("#topic-tree-scroll", ScrollableContainer)
        # Compute the node's depth (number of ancestors before root)
        depth = 0
        current = node
        tree = self.query_one(TopicTree)
        while current.parent is not None and current is not tree.root:
            depth += 1
            current = current.parent
        # guide_depth (default 4) chars per level, plus padding
        indent = depth * tree.guide_depth
        label_len = len(str(node.label))
        # Scroll so the node's label is visible with some margin
        container_width = scroll.size.width
        node_left = max(indent - 4, 0)  # small left padding to show siblings
        node_right = indent + label_len + 4
        # Only scroll if the label isn't fully visible
        if node_left >= scroll.scroll_x and node_right <= scroll.scroll_x + container_width:
            return  # fully visible, nothing to do
        # Anchor to the beginning of the name
        scroll.scroll_x = node_left

    # ------------------------------------------------------------------
    # Entry count hint + entry loading on cursor move
    # ------------------------------------------------------------------

    async def on_tree_node_highlighted(self, event: Tree.NodeHighlighted[Topic]) -> None:
        topic = event.node.data
        if topic is None:
            return
        # Scroll the container so the highlighted node's label is visible
        self._scroll_to_node(event.node)
        # Save cursor position for the previous topic
        viewer = self.query_one("#topic-entry-viewer", EntryList)
        if self._current_topic_id is not None:
            self._entry_cursor_cache[self._current_topic_id] = viewer.cursor
        self._current_topic_id = topic.id
        session_factory = self._session_factory
        if self.show_entries:
            # Panel is open — fetch full entries (needed for display)
            if topic.id not in self._entry_cache:
                async with session_factory() as session:
                    entries = await list_entries(session, topic.id)
                    self._entry_cache[topic.id] = entries
                    self._entry_count_cache[topic.id] = len(entries)
            viewer.set_entries(self._entry_cache[topic.id])
            # Restore saved cursor position
            if topic.id in self._entry_cursor_cache:
                viewer.cursor = min(
                    self._entry_cursor_cache[topic.id],
                    max(len(self._entry_cache[topic.id]) - 1, 0),
                )
            viewer._scroll_cursor_visible()
        else:
            # Panel is closed — only fetch count (lightweight)
            if topic.id not in self._entry_count_cache:
                async with session_factory() as session:
                    count = await count_entries(session, topic.id)
                    self._entry_count_cache[topic.id] = count
        # Update the count hint
        count = self._entry_count_cache[topic.id]
        if count == 0:
            hint_text = "(no entries in this topic)"
        elif count == 1:
            hint_text = "(1 entry in this topic)"
        else:
            hint_text = f"({count} entries in this topic)"
        self.query_one("#entry-count-hint", Static).update(hint_text)

    # ------------------------------------------------------------------
    # Topic selection (Enter / Ctrl+J)
    # ------------------------------------------------------------------

    def on_tree_node_selected(self, event: Tree.NodeSelected[Topic]) -> None:
        if event.node.data is None:
            return
        event.stop()
        if self.show_entries:
            # Enter with panel open → focus the entry viewer
            self.query_one("#topic-entry-viewer", EntryList).focus()
        else:
            # Enter with panel closed → select topic and exit
            self._post_topic_selected(event.node)

    def action_select_topic(self) -> None:
        """Ctrl+J — select the currently highlighted topic and exit."""
        tree = self.query_one(TopicTree)
        node = tree.cursor_node
        if node is not None and node.data is not None:
            self._post_topic_selected(node)

    def _post_topic_selected(self, node: TreeNode[Topic]) -> None:
        """Build the path and post TopicSelected."""
        path: list[str] = []
        current = node
        while current.parent is not None:
            if current.data is not None:
                path.append(current.data.name)
            current = current.parent
        path.reverse()
        self.post_message(self.TopicSelected(node.data, path))

    # ------------------------------------------------------------------
    # Entry viewer dismissed → return focus to tree
    # ------------------------------------------------------------------

    def on_entry_list_dismissed(self, event: EntryList.Dismissed) -> None:
        event.stop()
        self.query_one(TopicTree).focus()

    # ------------------------------------------------------------------
    # Dismiss viewer (Escape from tree)
    # ------------------------------------------------------------------

    def action_dismiss_viewer(self) -> None:
        self.post_message(self.Dismissed())

    # ------------------------------------------------------------------
    # Dismiss button
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "topic-tree-dismiss":
            self.post_message(self.Dismissed())

    # ------------------------------------------------------------------
    # Focus delegation
    # ------------------------------------------------------------------

    def focus(self, scroll_visible: bool = True) -> None:
        """Delegate focus to the inner tree."""
        self.query_one(TopicTree).focus(scroll_visible)
