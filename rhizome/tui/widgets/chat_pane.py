"""ChatPane — core chat UI: message area, input box, and command palette."""

from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Markdown, Static
from textual.worker import Worker

from rhizome.db import Curriculum, Topic
from rhizome.tui.commands import COMMANDS, parse_input
from rhizome.tui.types import ChatMessageData, Mode, Role
from rhizome.tui.widgets.chat_input import ChatInput
from rhizome.tui.widgets.command_palette import CommandPalette
from rhizome.tui.widgets.message import ChatMessage
from rhizome.tui.widgets.thinking import ThinkingIndicator
from rhizome.tui.widgets.welcome import WelcomeHeader
from rhizome.tui.widgets.topic_tree import TopicTree


class ChatPane(Widget):
    """Reusable chat pane containing the message area, input, and command palette."""

    DEFAULT_CSS = """
    ChatPane {
        layout: grid;
        grid-size: 1;
        grid-rows: 1fr auto auto;
    }
    #message-area {
        background: $surface-darken-1;
        padding: 1;
    }
    #chat-input {
        height: auto;
        min-height: 3;
        max-height: 10;
    }
    #command-palette {
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.messages: list[ChatMessageData] = []
        self._agent_busy: bool = False
        self._agent_worker: Worker[None] | None = None
        self.session_mode: str = Mode.IDLE.value
        self.session_context: str = ""
        self.active_curriculum: Curriculum | None = None
        self.active_topic: Topic | None = None

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="message-area")
        yield ChatInput(placeholder="Type a message or /command ...", id="chat-input")
        yield CommandPalette(id="command-palette")

    def on_mount(self) -> None:
        area = self.query_one("#message-area", VerticalScroll)
        area.mount(WelcomeHeader())
        self.query_one("#chat-input", ChatInput).focus()

    def on_text_area_changed(self, event: ChatInput.Changed) -> None:
        text = event.text_area.text

        palette = self.query_one("#command-palette", CommandPalette)
        chat_input = self.query_one("#chat-input", ChatInput)

        if chat_input._history_index >= 0:
            palette.remove_class("visible")
            chat_input.palette_active = False
            return

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

    def cancel_agent(self) -> None:
        """Cancel the running agent worker, if any."""
        if self._agent_busy and self._agent_worker is not None:
            self._agent_worker.cancel()

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        self._hide_palette()

        if self._agent_busy:
            self.notify("Agent is thinking, you can submit after it completes or interrupt with Ctrl+C")
            return

        text = event.value.strip()
        if not text:
            return

        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.clear()
        chat_input.push_history(text)

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
            await handler(self.app, args)  # pyright: ignore[reportArgumentType]

        self.run_worker(_run())

    def _handle_chat(self, text: str) -> None:
        self.append_message(ChatMessageData(role=Role.USER, content=text))

        self._agent_busy = True

        async def _run_agent() -> None:
            from rhizome.agent import stream_agent

            area = self.query_one("#message-area", VerticalScroll)

            thinking = ThinkingIndicator()
            await area.mount(thinking)
            area.scroll_end(animate=False)

            app = self.app
            widget: ChatMessage | None = None
            stream = None
            body = ""

            try:
                async for chunk in stream_agent(
                    app.agent,  # type: ignore[attr-defined]
                    app.session_factory,  # type: ignore[attr-defined]
                    self.messages,
                    mode=self.session_mode,
                    curriculum_name=(
                        self.active_curriculum.name
                        if self.active_curriculum
                        else ""
                    ),
                    topic_name=(
                        self.active_topic.name
                        if self.active_topic
                        else ""
                    ),
                ):
                    if widget is None:
                        await thinking.remove()
                        widget = ChatMessage(role=Role.AGENT)
                        await area.mount(widget)
                        stream = Markdown.get_stream(widget)
                    body += chunk
                    await stream.write(chunk)
                    area.scroll_end(animate=False)

                if stream is not None:
                    await stream.stop()

                if widget is None:
                    await thinking.remove()
                    widget = ChatMessage(role=Role.AGENT, content="(no response)")
                    await area.mount(widget)
                    body = "(no response)"

                self.messages.append(ChatMessageData(role=Role.AGENT, content=body))

            except asyncio.CancelledError:
                if widget is None:
                    await thinking.remove()

                if body:
                    if stream is not None:
                        await stream.stop()
                    self.messages.append(ChatMessageData(role=Role.AGENT, content=body))
                else:
                    cancelled_msg = ChatMessage(role=Role.AGENT, content="*(cancelled)*")
                    await area.mount(cancelled_msg)

                area.scroll_end(animate=False)

            finally:
                self._agent_busy = False
                self._agent_worker = None

        self._agent_worker = self.run_worker(_run_agent())

    def append_message(self, msg: ChatMessageData) -> None:
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
        self.active_topic = topic
        if self.active_curriculum and topic:
            self.session_context = f"{self.active_curriculum.name} > {topic.name}"
        elif self.active_curriculum:
            self.session_context = self.active_curriculum.name
        elif topic:
            self.session_context = topic.name
        else:
            self.session_context = ""

        self.append_message(ChatMessageData(role=Role.SYSTEM, content=f"Selected topic: {topic.name}"))
        for tree in self.query(TopicTree):
            tree.remove()
        self._restore_chat_input()

    def on_topic_tree_focus_released(self, event: TopicTree.FocusReleased) -> None:
        trees = list(self.query(TopicTree))
        if trees:
            trees[-1].query_one("#topic-tree-help", Static).update(
                "Use Ctrl+Enter to navigate back to the topic explorer (in empty message box)"
            )
        self._restore_chat_input()

    def on_chat_input_focus_tree_requested(self, event: ChatInput.FocusTreeRequested) -> None:
        self._focus_latest_topic_tree()
