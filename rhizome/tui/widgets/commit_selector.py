"""CommitSelector — overlay widget for selecting learn-mode agent messages to commit."""

from __future__ import annotations

from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from rhizome.tui.types import ChatMessageData, Role
from rhizome.tui.widgets.message import ChatMessage


class CommitSelector(Widget, can_focus=True):
    """Manages keyboard-driven selection of learn-mode agent messages.

    On mount, scans the message area for agent ChatMessage widgets with the
    ``learn-mode`` CSS class, decorates them with checkboxes and visual
    indicators, and handles Up/Down/Space/Ctrl+Enter/Escape navigation.
    """

    DEFAULT_CSS = """
    CommitSelector {
        height: 0;
        overflow: hidden;
    }
    """

    class Dismissed(Message):
        """User cancelled the selection."""

    class Done(Message):
        """User confirmed the selection."""

        def __init__(self, selected_messages: list[ChatMessageData]) -> None:
            super().__init__()
            self.selected_messages = selected_messages

    BINDINGS = [
        ("up", "cursor_up", "Move cursor up"),
        ("down", "cursor_down", "Move cursor down"),
        ("space", "toggle_select", "Toggle selection"),
        ("ctrl+j", "confirm", "Confirm selection"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._selectable: list[ChatMessage] = []
        self._cursor: int = 0
        self._selected: set[int] = set()

    def on_mount(self) -> None:
        """Scan for selectable messages and decorate them."""
        pane = self.ancestors_with_self[-1]  # walk up to find messages
        try:
            from rhizome.tui.widgets.chat_pane import ChatPane
            for ancestor in self.ancestors_with_self:
                if isinstance(ancestor, ChatPane):
                    pane = ancestor
                    break
        except ImportError:
            pass

        # Query for learn-mode agent messages
        self._selectable = list(pane.query("ChatMessage.agent-message.learn-mode"))

        if not self._selectable:
            self.post_message(self.Dismissed())
            return

        # Decorate each selectable message
        for msg in self._selectable:
            msg.add_class("--commit-selectable")
            checkbox = Static("☐", classes="commit-checkbox")
            msg.mount(checkbox, before=0)

        # Set initial cursor
        self._update_cursor(0)
        self.focus()

    def on_unmount(self) -> None:
        """Clean up all decorations from messages."""
        for msg in self._selectable:
            msg.remove_class("--commit-selectable")
            msg.remove_class("--commit-cursor")
            msg.remove_class("--commit-selected")
            for cb in msg.query(".commit-checkbox"):
                cb.remove()

    def _update_cursor(self, new_index: int) -> None:
        """Move the cursor highlight to the given index."""
        if not self._selectable:
            return
        # Remove old cursor
        if 0 <= self._cursor < len(self._selectable):
            self._selectable[self._cursor].remove_class("--commit-cursor")
        # Set new cursor
        self._cursor = new_index
        target = self._selectable[self._cursor]
        target.add_class("--commit-cursor")
        target.scroll_visible()

    def action_cursor_up(self) -> None:
        if self._selectable and self._cursor > 0:
            self._update_cursor(self._cursor - 1)

    def action_cursor_down(self) -> None:
        if self._selectable and self._cursor < len(self._selectable) - 1:
            self._update_cursor(self._cursor + 1)

    def action_toggle_select(self) -> None:
        if not self._selectable:
            return
        msg = self._selectable[self._cursor]
        checkboxes = list(msg.query(".commit-checkbox"))
        if self._cursor in self._selected:
            self._selected.discard(self._cursor)
            msg.remove_class("--commit-selected")
            if checkboxes:
                checkboxes[0].update("☐")
        else:
            self._selected.add(self._cursor)
            msg.add_class("--commit-selected")
            if checkboxes:
                checkboxes[0].update("☑")

    def action_confirm(self) -> None:
        selected_messages = []
        for idx in sorted(self._selected):
            msg = self._selectable[idx]
            selected_messages.append(
                ChatMessageData(role=Role.AGENT, content=msg.content_text)
            )
        self.post_message(self.Done(selected_messages))

    def action_cancel(self) -> None:
        self.post_message(self.Dismissed())
