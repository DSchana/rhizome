"""Main chat screen — message list + input box."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Markdown, Static

from rhizome.tui.commands import COMMANDS, parse_input
from rhizome.tui.state import ChatEntry
from rhizome.tui.widgets.chat_input import ChatInput
from rhizome.tui.widgets.command_palette import CommandPalette
from rhizome.tui.widgets.message import ChatMessage
from rhizome.tui.widgets.status_bar import StatusBar
from rhizome.tui.widgets.thinking import ThinkingIndicator
from rhizome.tui.widgets.welcome import WelcomeHeader
from rhizome.tui.widgets.topic_tree import TopicTree


class ChatScreen(Screen):
    """Primary screen: scrollable message area + input at the bottom."""

    DEFAULT_CSS = """
    ChatScreen {
        layout: grid;
        grid-size: 1;
        grid-rows: 1fr auto auto auto;
    }
    #message-area {
        background: $surface-darken-1;
        padding: 1;
    }
    #status-bar {
        dock: bottom;
        height: auto;
        background: $surface;
        padding: 0 1;
        border-top: solid rgb(60, 60, 60);
    }
    #chat-input {
        height: auto;
        min-height: 3;
        max-height: 10;
    }
    #command-palette {
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[ChatEntry] = []

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="message-area")
        yield ChatInput(placeholder="Type a message or /command ...", id="chat-input")
        yield CommandPalette(id="command-palette")
        yield StatusBar(id="status-bar")

    def on_mount(self) -> None:
        area = self.query_one("#message-area", VerticalScroll)
        area.mount(WelcomeHeader())
        self.query_one("#chat-input", ChatInput).focus()

        # Bind the status bar to the app's reactive properties.
        bar = self.query_one("#status-bar", StatusBar)
        self.watch(self.app, "mode", lambda val: setattr(bar, "mode", val))
        self.watch(self.app, "context", lambda val: setattr(bar, "context", val))

    def on_text_area_changed(self, event: ChatInput.Changed) -> None:
        text = event.text_area.text

        palette = self.query_one("#command-palette", CommandPalette)
        chat_input = self.query_one("#chat-input", ChatInput)
        
        if text.startswith("/") and "\n" not in text:
            palette.filter_text = text
            if palette.has_items:
                palette.add_class("visible")
                chat_input.palette_active = True
            else:
                palette.remove_class("visible")
                chat_input.palette_active = False
        else:
            palette.remove_class("visible")
            chat_input.palette_active = False

    def on_chat_input_palette_navigate(self, event: ChatInput.PaletteNavigate) -> None:
        self.query_one("#command-palette", CommandPalette).move_selection(event.delta)

    def on_chat_input_palette_confirm(self, event: ChatInput.PaletteConfirm) -> None:
        self.query_one("#command-palette", CommandPalette).confirm_selection()

    def on_command_palette_command_selected(self, event: CommandPalette.CommandSelected) -> None:
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.clear()
        chat_input.insert(f"/{event.name} ")
        self._hide_palette()

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        self._hide_palette()

        text = event.value.strip()
        if not text:
            return

        command = parse_input(text)
        if command is not None:
            self._handle_command(command.name, command.args)
        else:
            self._handle_chat(text)

    def _hide_palette(self) -> None:
        """Hide the command palette and restore input margin."""
        palette = self.query_one("#command-palette", CommandPalette)
        chat_input = self.query_one("#chat-input", ChatInput)
        palette.remove_class("visible")
        chat_input.remove_class("palette-open")
        chat_input.palette_active = False

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
        self.append_message(ChatEntry(role="user", content=text))

        async def _run_agent() -> None:
            from rhizome.agent import stream_agent

            area = self.query_one("#message-area", VerticalScroll)

            # Show a "thinking..." indicator while waiting for the first token.
            thinking = ThinkingIndicator()
            await area.mount(thinking)
            area.scroll_end(animate=False)

            app = self.app
            widget: ChatMessage | None = None
            stream = None
            body = ""

            async for chunk in stream_agent(
                app.agent,  # type: ignore[attr-defined]
                app.session_factory,  # type: ignore[attr-defined]
                self.messages,
                mode=app.mode,  # type: ignore[attr-defined]
                curriculum_name=(
                    app.active_curriculum.name  # type: ignore[attr-defined]
                    if getattr(app, "active_curriculum", None)
                    else ""
                ),
                topic_name=(
                    app.active_topic.name  # type: ignore[attr-defined]
                    if getattr(app, "active_topic", None)
                    else ""
                ),
            ):
                if widget is None:
                    # First token: remove spinner and mount the message widget.
                    await thinking.remove()
                    widget = ChatMessage(role="agent")
                    await area.mount(widget)
                    stream = Markdown.get_stream(widget)
                body += chunk
                await stream.write(chunk)
                area.scroll_end(animate=False)

            if stream is not None:
                await stream.stop()

            # If the agent produced no tokens, still clean up the spinner.
            if widget is None:
                await thinking.remove()
                widget = ChatMessage(role="agent", content="(no response)")
                await area.mount(widget)
                body = "(no response)"

            self.messages.append(ChatEntry(role="agent", content=body))

        self.run_worker(_run_agent())

    def append_message(self, msg: ChatEntry) -> None:
        """Append a message to the history and mount its widget."""
        self.messages.append(msg)
        area = self.query_one("#message-area", VerticalScroll)
        area.mount(ChatMessage(role=msg.role, content=msg.content))
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
        self.append_message(ChatEntry(role="system", content=f"Selected topic: {topic.name}"))
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
