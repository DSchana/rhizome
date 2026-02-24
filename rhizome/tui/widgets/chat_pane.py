"""ChatPane — core chat UI: message area, input box, and command palette."""

from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Markdown
from textual.worker import Worker

from rhizome.agent import stream_agent
from rhizome.db import Curriculum, Topic
from rhizome.tui.commands import COMMANDS, parse_input
from rhizome.tui.options import Options, OptionScope
from rhizome.tui.types import ChatMessageData, Mode, Role
from rhizome.tui.widgets.chat_input import ChatInput
from rhizome.tui.widgets.command_palette import CommandPalette
from rhizome.tui.widgets.message import ChatMessage
from rhizome.tui.widgets.thinking import ThinkingIndicator
from rhizome.tui.widgets.options_editor import OptionsEditor
from rhizome.tui.widgets.welcome import WelcomeHeader
from rhizome.tui.widgets.status_bar import StatusBar
from rhizome.tui.widgets.topic_tree import TopicTree


class ChatPane(Widget):
    """Reusable chat pane containing the message area, input, and command palette."""

    DEFAULT_CSS = """
    ChatPane {
        layout: grid;
        grid-size: 1;
        grid-rows: 1fr auto auto auto;
    }
    #status-bar {
        height: auto;
        background: $surface;
        padding: 0 1;
        border-top: solid rgb(60, 60, 60);
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

    def __init__(self, *, show_welcome: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self._show_welcome = show_welcome
        self.messages: list[ChatMessageData] = []
        self._agent_busy: bool = False
        self._agent_worker: Worker[None] | None = None
        self.session_mode: Mode = Mode.IDLE
        self.session_context: str = ""
        self.active_curriculum: Curriculum | None = None
        self.active_topic: Topic | None = None
        self.options: Options | None = None  # set on mount when app is available

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="message-area")
        yield ChatInput(placeholder="Type a message or /command ...", id="chat-input")
        yield CommandPalette(id="command-palette")
        yield StatusBar(id="status-bar")

    def on_mount(self) -> None:
        self.options = Options(scope=OptionScope.Session, parent=self.app.options)  # type: ignore[attr-defined]
        area = self.query_one("#message-area", VerticalScroll)
        if self._show_welcome:
            area.mount(WelcomeHeader())
        self.query_one("#chat-input", ChatInput).focus()

    def on_unmount(self) -> None:
        if self.options is not None:
            self.options.detach()

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
                    mode=self.session_mode.value,
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
                        widget = ChatMessage(role=Role.AGENT, mode=self.session_mode)
                        await area.mount(widget)
                        stream = Markdown.get_stream(widget.inner_markdown)
                    body += chunk
                    widget._body = body
                    if not widget._collapsed:
                        await stream.write(chunk)
                    area.scroll_end(animate=False)

                if stream is not None:
                    await stream.stop()
                    widget.update_body(body)

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

    def update_status_bar(self) -> None:
        """Sync the status bar with the current mode and context."""
        bar = self.query_one("#status-bar", StatusBar)
        bar.mode = self.session_mode.value
        bar.context = self.session_context

    def append_message(self, msg: ChatMessageData) -> None:
        """Append a message to the history and mount its widget."""
        msg.mode = self.session_mode
        self.messages.append(msg)
        area = self.query_one("#message-area", VerticalScroll)
        area.mount(ChatMessage(role=msg.role, content=msg.content, mode=msg.mode))
        area.scroll_end(animate=False)

    def _restore_chat_input(self) -> None:
        """Restore focus and placeholder to the chat input."""
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.placeholder = "Type a message or /command ..."
        chat_input.focus()

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

        self.update_status_bar()
        self.append_message(ChatMessageData(role=Role.SYSTEM, content=f"Selected topic: {topic.name}"))
        for tree in self.query(TopicTree):
            tree.remove()
        self._restore_chat_input()

    def on_topic_tree_dismissed(self, event: TopicTree.Dismissed) -> None:
        for tree in self.query(TopicTree):
            tree.remove()
        self._restore_chat_input()

    def on_options_editor_dismissed(self, event: OptionsEditor.Dismissed) -> None:
        for ed in self.query(OptionsEditor):
            ed.remove()
        self._restore_chat_input()

    def on_options_editor_done(self, event: OptionsEditor.Done) -> None:
        editors = list(self.query(OptionsEditor))
        for ed in editors:
            ed.remove()
        self._restore_chat_input()
