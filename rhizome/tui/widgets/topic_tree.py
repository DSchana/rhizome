"""Interactive topic tree viewer built on Textual's Tree widget."""

from __future__ import annotations

from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Button, Static, Tree
from textual.widgets._tree import TreeNode

from rhizome.db import Topic
from rhizome.tools import list_children, list_root_topics


class _InnerTree(Tree[Topic]):
    """The actual Tree widget — used inside TopicTree container."""

    def __init__(self) -> None:
        super().__init__("Topics")
        self.show_root = False

    def _refresh_height(self) -> None:
        """Set height to match the number of visible lines."""
        line_count = len(self._tree_lines)
        self.styles.height = max(line_count, 1)

    async def on_mount(self) -> None:
        session_factory = self.app.session_factory  # type: ignore[attr-defined]
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

    async def on_tree_node_expanded(self, event: Tree.NodeExpanded[Topic]) -> None:
        node: TreeNode[Topic] = event.node
        if node.data is None:
            return
        if node.children:
            self._refresh_height()
            return
        session_factory = self.app.session_factory  # type: ignore[attr-defined]
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
        else:
            super()._on_key(event) # pyright: ignore[reportUnusedCoroutine]


class TopicTree(Vertical):
    """A bordered container with a tree viewer for browsing topics."""

    DEFAULT_CSS = """
    TopicTree {
        height: auto;
        margin-top: 1;
        border: round rgb(86, 126, 160);
        padding: 0 0 1 1;
    }
    TopicTree #topic-tree-help {
        color: $text-muted;
        margin: 1 0 0 1;
    }
    TopicTree _InnerTree {
        height: auto;
        scrollbar-size: 0 0;
    }
    TopicTree #topic-tree-dismiss {
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
    TopicTree #topic-tree-dismiss:hover {
        color: $error;
    }
    """

    class TopicSelected(Message):
        """Posted when the user selects a topic with Enter."""

        def __init__(self, topic: Topic) -> None:
            super().__init__()
            self.topic = topic

    class Dismissed(Message):
        """Posted when the user clicks the dismiss button."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    def compose(self):
        yield Button("x", id="topic-tree-dismiss")
        yield Static("Use arrow keys to navigate, enter to select a topic.", id="topic-tree-help")
        yield _InnerTree()

    def on_mount(self) -> None:
        self.border_title = "Topics"

    def on_tree_node_selected(self, event: Tree.NodeSelected[Topic]) -> None:
        if event.node.data is not None:
            event.stop()
            self.post_message(self.TopicSelected(event.node.data))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "topic-tree-dismiss":
            self.post_message(self.Dismissed())

    def focus(self, scroll_visible: bool = True) -> None:
        """Delegate focus to the inner tree."""
        self.query_one(_InnerTree).focus(scroll_visible)
