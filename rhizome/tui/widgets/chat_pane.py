"""ChatPane — core chat UI: message area, input box, and command palette."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.worker import Worker

from langchain_core.messages.utils import count_tokens_approximately
from langchain.messages import ToolMessage

from rhizome.agent import build_lc_messages, compute_chat_model_max_tokens, stream_agent
from rhizome.config import get_log_dir
from rhizome.db import Curriculum, Topic
from rhizome.tui.commands import COMMANDS, parse_input
from rhizome.tui.options import Options, OptionScope
from rhizome.tui.types import ChatMessageData, Mode, Role, TokenUsageData
from rhizome.tui.widgets.chat_input import ChatInput
from rhizome.tui.widgets.command_palette import CommandPalette
from rhizome.tui.widgets.agent_message_harness import AgentMessageHarness
from rhizome.tui.widgets.commit_selector import CommitSelector
from rhizome.tui.widgets.message import ChatMessage
from rhizome.tui.widgets.options_editor import OptionsEditor
from rhizome.tui.widgets.welcome import WelcomeHeader
from rhizome.tui.utils import serialize_stream_payload
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
        background: rgb(12, 12, 12);
        padding: 0 1 1 1;
        border-top: solid rgb(60, 60, 60);
    }
    #message-area {
        background: $surface-darken-1;
        padding: 1;
        scrollbar-color: rgb(60, 60, 60);
        scrollbar-color-hover: rgb(80, 80, 80);
        scrollbar-color-active: rgb(100, 100, 100);
    }
    #chat-input {
        height: auto;
        min-height: 3;
        max-height: 10;
        padding: 0 1;
        background: rgb(12, 12, 12);
    }
    #command-palette {
        background: rgb(12, 12, 12);
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
        self._token_usage = TokenUsageData()
        self._agent_log: logging.Logger | None = None
        self._agent_log_handler: logging.FileHandler | None = None

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="message-area")
        yield ChatInput(placeholder="Type a message or /command ...", id="chat-input")
        yield CommandPalette(id="command-palette")
        yield StatusBar(id="status-bar")

    def on_mount(self) -> None:
        # Construct the per-session options object
        self.options = Options(scope=OptionScope.Session, parent=self.app.options)  # type: ignore[attr-defined]

        # Compute max context window tokens from the model profile.
        self._token_usage.max_tokens = compute_chat_model_max_tokens(self.app.chat_model)

        area = self.query_one("#message-area", VerticalScroll)
        if self._show_welcome:
            area.mount(WelcomeHeader())
        self.query_one("#chat-input", ChatInput).focus()

        if self.app.debug_logging:  # type: ignore[attr-defined]
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")
            logger_name = f"rhizome.agent_stream.{ts}"
            self._agent_log = logging.getLogger(logger_name)
            self._agent_log.setLevel(logging.DEBUG)
            self._agent_log.propagate = False
            log_path = get_log_dir() / f"agent_stream_{ts}.log"
            self._agent_log_handler = logging.FileHandler(str(log_path), mode="w")
            self._agent_log_handler.setFormatter(logging.Formatter("%(message)s"))
            self._agent_log.addHandler(self._agent_log_handler)

    def _close_agent_log(self) -> None:
        """Close and detach the agent stream file handler."""
        if self._agent_log_handler is not None:
            self._agent_log_handler.close()
            if self._agent_log is not None:
                self._agent_log.removeHandler(self._agent_log_handler)
            self._agent_log_handler = None
            self._agent_log = None

    def on_unmount(self) -> None:
        self._close_agent_log()
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
        # Post the user's message to the message history
        self.append_message(ChatMessageData(role=Role.USER, content=text))

        # Construct an AgentMessageHarness for capturing the View aspects of the agent stream.
        message_area = self.query_one("#message-area", VerticalScroll)
        harness = AgentMessageHarness()
        message_area.mount(harness)

        async def _run_agent() -> None:
            # Before we receive anything from the stream, add a thinking indicator.
            await harness.start_thinking()
            message_area.scroll_end(animate=False)

            try:
                async for mode, payload in stream_agent(
                    self.app.agent,  # type: ignore[attr-defined]
                    self.app.session_factory,  # type: ignore[attr-defined]
                    self.messages,
                    app=self.app,
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
                    if self._agent_log is not None:
                        self._agent_log.debug(
                            "[%s] [%s] %s",
                            datetime.now(timezone.utc).isoformat(),
                            mode,
                            serialize_stream_payload(payload),
                        )
                    if mode == "messages":
                        chunk, metadata = payload
                        if isinstance(chunk, ToolMessage):
                            continue
                        await harness.append(chunk)

                        # If we have usage metadata, update the status bar to display the total
                        # number of tokens.
                        if (
                            hasattr(chunk, "usage_metadata") and
                            chunk.usage_metadata and
                            chunk.usage_metadata.get("total_tokens")
                        ):
                            self._token_usage.total_tokens = chunk.usage_metadata["total_tokens"]
                            self.update_status_bar()

                    elif mode == "updates":
                        await harness.post_update(payload)
                    message_area.scroll_end(animate=False)

                # Finalize the message, retrieve the final agent message body, and
                # add it to our own list of message data.
                body = await harness.finalize()
                if body:
                    self.messages.append(ChatMessageData(role=Role.AGENT, content=body))

                # Compute overhead tokens (system prompt + app-generated system messages)
                non_conversation = [m for m in self.messages if m.role == Role.SYSTEM]
                lc_messages = build_lc_messages(
                    non_conversation,
                    mode=self.session_mode.value,
                    curriculum_name=(
                        self.active_curriculum.name if self.active_curriculum else ""
                    ),
                    topic_name=(
                        self.active_topic.name if self.active_topic else ""
                    ),
                )
                overhead = count_tokens_approximately(lc_messages)
                if overhead <= self._token_usage.total_tokens:
                    self._token_usage.overhead_tokens = overhead
                self.update_status_bar()

            except asyncio.CancelledError:
                # Post a "cancelled" message, retrieve this final message body,
                # and add it to our own list of message data.
                body = await harness.cancel()
                if body:
                    self.messages.append(ChatMessageData(role=Role.AGENT, content=body))

            finally:
                self._agent_busy = False
                self._agent_worker = None

        # Start the agent, setting _agent_busy to True until the worker completes.
        self._agent_busy = True
        self._agent_worker = self.run_worker(_run_agent())

    def update_status_bar(self) -> None:
        """Sync the status bar with the current mode and context."""
        bar = self.query_one("#status-bar", StatusBar)
        bar.mode = self.session_mode.value
        bar.context = self.session_context
        bar.token_usage = self._token_usage
        bar.mutate_reactive(StatusBar.token_usage)

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

    def on_commit_selector_dismissed(self, event: CommitSelector.Dismissed) -> None:
        for sel in self.query(CommitSelector):
            sel.remove()
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.disabled = False
        self._restore_chat_input()

    def on_commit_selector_done(self, event: CommitSelector.Done) -> None:
        for sel in self.query(CommitSelector):
            sel.remove()
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.disabled = False
        self._restore_chat_input()
        count = len(event.selected_messages)
        self.append_message(ChatMessageData(role=Role.SYSTEM, content=f"Selected {count} message(s) for commit."))
