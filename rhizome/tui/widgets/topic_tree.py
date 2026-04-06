"""Interactive topic tree viewer built on Textual's Tree widget."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text

from textual.reactive import reactive
from textual.widgets import Tree
from textual.widgets._tree import TreeNode, TOGGLE_STYLE

from rhizome.db import Topic
from rhizome.db.operations import list_children, list_root_topics

_ACTIVE_TOPIC_COLOR = Style(color="rgb(0,191,255)")
_ACTIVE_TOPIC_SELECTED = Style(color="rgb(100,210,255)", bold=True)


class TopicTree(Tree[Topic]):
    """The actual Tree widget — used inside TopicTree container."""

    active_topic_id: reactive[int | None] = reactive(None)

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

    # ------------------------------------------------------------------
    # Active topic indicator
    # ------------------------------------------------------------------

    def watch_active_topic_id(self) -> None:
        # Textual's Tree widget caches rendered lines in self._line_cache,
        # keyed partly on self._updates (an internal counter). Calling
        # self.refresh() schedules a repaint, but if _updates hasn't
        # changed, Tree.render_line will return the cached (stale) strip
        # instead of calling render_label again. Bumping _updates
        # invalidates those cache entries so our render_label override
        # (which reads active_topic_id to color the active topic and its
        # ancestors) actually runs on the next paint.
        self._updates += 1
        self.refresh()

    def _is_ancestor_of_active(self, node: TreeNode[Topic]) -> bool:
        """Check if node is a strict ancestor of the active topic node."""
        if self.active_topic_id is None:
            return False
        # Walk all descendants of this node looking for the active topic.
        # Since the tree is lazy-loaded, we only check expanded children.
        stack = list(node.children)
        while stack:
            child = stack.pop()
            if child.data is not None and child.data.id == self.active_topic_id:
                return True
            if child.is_expanded:
                stack.extend(child.children)
        return False

    def render_label(
        self, node: TreeNode[Topic], base_style: Style, style: Style,
    ) -> Text:
        if node.data is not None and self.active_topic_id is not None:
            is_active = node.data.id == self.active_topic_id
            is_ancestor = not is_active and self._is_ancestor_of_active(node)
        else:
            is_active = False
            is_ancestor = False

        # Build the expand/collapse icon prefix.
        if node._allow_expand:
            icon = self.ICON_NODE_EXPANDED if node.is_expanded else self.ICON_NODE
            if is_active or is_ancestor:
                icon_style = base_style + TOGGLE_STYLE + _ACTIVE_TOPIC_COLOR
            else:
                icon_style = base_style + TOGGLE_STYLE
        else:
            icon = ""
            icon_style = base_style

        node_label = node._label.copy()
        if is_active:
            is_cursor = node is self.cursor_node
            node_label.stylize(_ACTIVE_TOPIC_SELECTED if is_cursor else _ACTIVE_TOPIC_COLOR)
        else:
            node_label.stylize(style)

        return Text.assemble((icon, icon_style), node_label)
