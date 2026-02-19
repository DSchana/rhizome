"""Main chat screen — message list + input box."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Static

from curriculum_app.tui.commands import COMMANDS, parse_input
from curriculum_app.tui.state import ChatMessage
from curriculum_app.tui.widgets.chat_input import ChatInput
from curriculum_app.tui.widgets.message import MessageWidget
from curriculum_app.tui.widgets.status_bar import StatusBar
from curriculum_app.tui.widgets.topic_tree import TopicTree


class ChatScreen(Screen):
    """Primary screen: scrollable message area + input at the bottom."""

    DEFAULT_CSS = """
    ChatScreen {
        layout: grid;
        grid-size: 1;
        grid-rows: 1fr auto auto;
    }
    #message-area {
        background: $surface-darken-1;
        padding: 1;
    }
    #status-bar {
        dock: bottom;
        height: 1;
        background: $surface;
        padding: 0 1;
    }
    #chat-input {
        dock: bottom;
        margin: 0 0 1 0;
        height: auto;
        min-height: 3;
        max-height: 10;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[ChatMessage] = []

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="message-area")
        yield ChatInput(placeholder="Type a message or /command ...", id="chat-input")
        yield StatusBar(id="status-bar")

    def on_mount(self) -> None:
        self.query_one("#chat-input", ChatInput).focus()
        # Bind the status bar to the app's reactive properties.
        bar = self.query_one("#status-bar", StatusBar)
        self.watch(self.app, "mode", lambda val: setattr(bar, "mode", val))
        self.watch(self.app, "context", lambda val: setattr(bar, "context", val))

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return

        command = parse_input(text)
        if command is not None:
            self._handle_command(command.name, command.args)
        else:
            self._handle_chat(text)

    def _handle_command(self, name: str, args: str) -> None:
        # /quit is TUI-only — not in the registry and not agent-callable.
        if name == "quit":
            self.app.exit()
            return

        command = COMMANDS.get(name)
        if command is None:
            self.notify(f"Unknown command: /{name}", severity="error")
            return
        handler = command.handler
        if handler is None:
            self.notify(f"Error: command /{name} doesn't have an associated handler", severity="error")
            return

        async def _run() -> None:
            await handler(self.app, args) # pyright: ignore[reportArgumentType]

        self.run_worker(_run())

    def _handle_chat(self, text: str) -> None:
        self.append_message(ChatMessage(role="user", content=text))

    def append_message(self, msg: ChatMessage) -> None:
        """Append a message to the history and mount its widget."""
        self.messages.append(msg)
        area = self.query_one("#message-area", VerticalScroll)
        area.mount(MessageWidget(role=msg.role, content=msg.content))
        area.scroll_end(animate=False)

    def _restore_chat_input(self) -> None:
        """Restore focus and placeholder to the chat input."""
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.placeholder = "Type a message or /command ..."
        chat_input.focus()

    def _focus_latest_topic_tree(self) -> bool:
        """Focus the last TopicTree in the message area. Returns True if found."""
        trees = list(self.query(TopicTree))
        if not trees:
            return False
        tree = trees[-1]
        tree.query_one("#topic-tree-help", Static).update(
            "Use arrow keys to navigate, enter to select a topic."
        )
        tree.focus()
        self.query_one("#chat-input", ChatInput).placeholder = (
            "Use Ctrl+Enter to exit the topic viewer"
        )
        return True

    def on_topic_tree_topic_selected(self, event: TopicTree.TopicSelected) -> None:
        topic = event.topic
        self.app.update_context(None, topic)  # type: ignore[attr-defined]
        self.append_message(ChatMessage(role="agent", content=f"Selected topic: {topic.name}"))
        for tree in self.query(TopicTree):
            tree.remove()
        self._restore_chat_input()

    def on_topic_tree_focus_released(self, event: TopicTree.FocusReleased) -> None:
        # Update the tree's help text to hint how to return.
        trees = list(self.query(TopicTree))
        if trees:
            trees[-1].query_one("#topic-tree-help", Static).update(
                "Use Ctrl+Enter to navigate back to the topic explorer (in empty message box)"
            )
        self._restore_chat_input()

    def on_chat_input_focus_tree_requested(self, event: ChatInput.FocusTreeRequested) -> None:
        self._focus_latest_topic_tree()
