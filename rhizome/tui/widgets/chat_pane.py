"""ChatPane — core chat UI: message area, input box, and command palette."""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import time
import traceback
from functools import partial
from pathlib import Path
from typing import Literal

from langchain_core.messages import HumanMessage
from langchain_core.messages.utils import count_tokens_approximately

import rich_click as click

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static, TabbedContent
from textual.worker import Worker

from rhizome.agent import AgentSession
from rhizome.agent.session import get_agent_kwargs
from rhizome.db import Topic
from rhizome.logs import get_logger
from rhizome.tui.commit_state import CommitApproved, CommitState
from rhizome.tui.commands import CommandRegistry, parse_input
from rhizome.tui.options import Options, OptionScope, build_jsonc_snapshot, parse_jsonc
from rhizome.tui.types import ChatMessageData, Mode, Role

from .chat_input import ChatInput
from .command_palette import CommandPalette
from .agent_message_harness import AgentMessageHarness
from .message import ChatMessage, MarkdownChatMessage, RichChatMessage
from .options_editor import OptionsEditor
from .welcome import WelcomeHeader
from .status_bar import StatusBar
from .explorer_viewer import ExplorerViewer
from .commit_proposal import CommitProposal
from .flashcard_proposal import FlashcardProposal
from .flashcard_viewer import FlashcardViewer
from .navigable import WidgetDeactivated


class HintHigherVerbosity(Message):
    """Posted by the hint_higher_verbosity tool to suggest the user raise verbosity."""


class ChatPane(Widget):
    """Reusable chat pane containing the message area, input, and command palette."""

    # ------------------------------------------------------------------
    # Class-level constants
    # ------------------------------------------------------------------

    BINDINGS = [
        ("ctrl+c", "cancel_or_copy", "Cancel/Copy"),
        Binding("ctrl+l", "refocus_input", "Refocus input", show=False, priority=True),
        Binding("ctrl+t", "toggle_last_agent_message", "Toggle agent msg", show=False, priority=True),
        Binding("ctrl+o", "toggle_last_tool_call", "Toggle tool call", show=False, priority=True),
        Binding("shift+tab", "cycle_mode", "Cycle mode", show=False, priority=True),
        Binding("ctrl+b", "cycle_verbosity", "Cycle verbosity", show=False, priority=True),
        Binding("ctrl+up", "focus_prev_widget", "Prev widget", show=False, priority=True),
        Binding("ctrl+down", "focus_next_widget", "Next widget", show=False, priority=True),
    ]

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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(self, *, show_welcome: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)

        # Whether to show the welcome header on mount, or start with an empty message area.
        self._show_welcome = show_welcome

        # The list of all messages in this chat pane, including those from the agent stream and user/system messages.
        # This is the "view" level representation of the messages, separate from the conversation history managed by
        # the agent session.
        #
        # TODO: do we even really need this?
        self.messages: list[ChatMessageData] = []

        self.session_mode: Mode = Mode.IDLE
        self.options: Options | None = None  # set on mount when app is available

        # Active topic and path, if any. _topic_path is the list of topic names from the root to the active topic,
        # used for display in the status bar.
        self.active_topic: Topic | None = None
        self._topic_path: list[str] = []

        # Agent session and worker state.
        # - _agent_session is the AgentSession instance for this chat pane, which manages the conversation history and agent stream.
        # - _agent_busy is True from the moment an agent turn is initiated until its worker completes.
        # - _agent_worker holds the current agent worker, if any, so it can be cancelled if the user interrupts.
        self._agent_session: AgentSession | None = None
        self._agent_busy: bool = False
        self._agent_worker: Worker[None] | None = None
        # Commit mode state — see CommitState dataclass.
        self._commit = CommitState()

        self._log = get_logger("tui.chat_pane")

        # Active widget stack — interactive widgets in mount order.
        # Ctrl+Up/Down navigates between them.
        self._active_widgets: list[Widget] = []

        # Command registry
        self._command_registry = CommandRegistry()
        self._register_commands(self._command_registry)

        # Verbosity-hint throttling: show the toast only on the first hint
        # since the last answer-verbosity change, or if 10+ minutes have passed.
        self._verbosity_hint_allowed = True
        self._verbosity_hint_last_shown: float = 0.0

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="message-area")
        yield ChatInput(placeholder="Type a message or /command ...", id="chat-input")
        yield CommandPalette(id="command-palette")
        yield StatusBar(id="status-bar")

    def on_mount(self) -> None:
        self._sync_registry_width()

        # Construct the per-session options object
        self.options = Options(
            scope=OptionScope.Session,
            parent=self.app.options # type: ignore[attr-defined]
        )

        # Create the agent with initial provider/model from options
        provider = self.options.get(Options.Agent.Provider)
        model_name = self.options.get(Options.Agent.Model)
        agent_kwargs = get_agent_kwargs(self.options)
        self._agent_session = AgentSession(
            self.app.session_factory,  # type: ignore[attr-defined]
            chat_pane=self,
            provider=provider,
            model_name=model_name,
            agent_kwargs=agent_kwargs,
            on_token_usage_changed=self.update_status_bar,
            on_rebuild_agent=self._on_agent_rebuilt,
            debug=getattr(self.app, "debug_logging", False),
        )
        self.update_status_bar() # Call to trigger model name display

        # Subscribe to post-update so agent rebuilds when options change
        self.options.subscribe_post_update(self._agent_session.on_options_post_update)
        self.options.subscribe_post_update(self._on_options_post_update)

        # Add the welcome header, assuming _show_welcome is True.
        area = self.query_one("#message-area", VerticalScroll)
        if self._show_welcome:
            area.mount(WelcomeHeader())

        # Focus the chat input
        self.query_one("#chat-input", ChatInput).focus()

    def on_unmount(self) -> None:
        if self.options is not None:
            self.options.detach()

    def on_resize(self) -> None:
        self._sync_registry_width()

    def _sync_registry_width(self) -> None:
        """Update the command registry's max_content_width from the pane's current width."""
        self._command_registry.max_content_width = max(self.size.width - 15, 40)

    # ------------------------------------------------------------------
    # Agent session
    # ------------------------------------------------------------------

    def _start_agent(self):
        # Create a harness, and run the agent. This sets _agent_busy = True internally
        # as well, until the worker finishes or is cancelled.
        harness = AgentMessageHarness(
            tool_use_visibility=self.options.get(Options.ToolUseVisibility),
        )
        self._agent_worker = self.run_worker(partial(self._run_agent, harness))

    async def _run_agent(self, harness: AgentMessageHarness) -> None:
        message_area = self.query_one("#message-area", VerticalScroll)
        message_area.mount(harness)
        message_area.scroll_end(animate=False)

        try:
            assert self._agent_session is not None
            assert not self._agent_busy

            self._agent_busy = True
            await harness.start_thinking()
            message_area.scroll_end(animate=False)

            await self._agent_session.stream(
                mode=self.session_mode.value,
                topic_name=self.active_topic.name if self.active_topic else "",
                on_message=harness.on_message,
                on_update=harness.on_update,
                on_interrupt=harness.on_interrupt,
                post_chunk_handler=lambda: message_area.scroll_end(animate=False),
            )
            
            body = await harness.finalize()
            if body:
                self.messages.append(ChatMessageData(role=Role.AGENT, content=body))

        except asyncio.CancelledError:
            self._log.info("User cancelled agent stream.")
            body = await harness.cancel()
            if body:
                self.messages.append(ChatMessageData(role=Role.AGENT, content=body))

                # Remark: here we re-inject whatever the agent was able to produce before it was interrupted back into the message
                # queue as a fake AI message. When asyncio.CancelledError is triggered it seems like the half-finished message doesn't
                # actually make it into the graph's messages state - manually queueing the partial message provides it as additional 
                # context for the agent.
                self._agent_session.add_ai_message(body)

            self.append_message(
                ChatMessageData(role=Role.SYSTEM, content="(user cancelled)")
            )

        except Exception as exc:
            self._log.error("Agent error: %s", exc)
            await harness.cancel()
            self.append_message(ChatMessageData(role=Role.ERROR, content=str(exc)))
            # raise

        finally:
            self._agent_busy = False
            self._agent_worker = None

    def _on_agent_rebuilt(self, old_model: str, new_model: str) -> None:
        """Called when the agent is rebuilt due to a model option change."""
        if new_model == old_model:
            return

        self._log.info("Agent rebuilt: %s → %s", old_model, new_model)
        self.append_message(ChatMessageData(
            role=Role.SYSTEM,
            content=(
                f"Model changed to {self._agent_session._model_name}.  \n"
                f"Profile: `{self._agent_session.model.profile}`"
            ),
        ))
        self.update_status_bar() # Model name changed.

    def on_agent_message_harness_interrupt_pending(
        self, event: AgentMessageHarness.InterruptPending
    ) -> None:
        """Disable chat input while an interrupt widget awaits user input."""
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.disabled = True
        chat_input.placeholder = "Respond to the agent's prompt above..."
        self._active_widgets.append(event.widget)
        event.widget.focus()

    def on_agent_message_harness_interrupt_resolved(
        self, event: AgentMessageHarness.InterruptResolved
    ) -> None:
        """Re-enable chat input after the user resolves an interrupt."""
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.disabled = False
        self._restore_chat_input()

    def on_widget_deactivated(self, event: WidgetDeactivated) -> None:
        """Remove a widget from the active stack when it is no longer interactable."""
        sender = event.sender_widget
        if sender in self._active_widgets:
            self._active_widgets.remove(sender)

    # ------------------------------------------------------------------
    # Message area & status bar
    # ------------------------------------------------------------------

    def append_message(self, msg: ChatMessageData, ui_only=False) -> None:
        """Append a message to the history and mount its widget."""
        # Deduplicate consecutive identical system messages by pinging the existing one.
        if msg.role == Role.SYSTEM:
            area = self.query_one("#message-area", VerticalScroll)
            children = area.children
            if children and isinstance(children[-1], ChatMessage) and children[-1]._role == Role.SYSTEM and children[-1]._body == msg.content:
                children[-1].ping()
                return

        msg.mode = self.session_mode
        self.messages.append(msg)

        # Add message to agent message history.
        if not ui_only and self._agent_session is not None:
            if msg.role == Role.USER:
                self._agent_session.add_human_message(msg.content)
            elif msg.role == Role.SYSTEM:
                self._agent_session.add_system_notification(msg.content)

        area = self.query_one("#message-area", VerticalScroll)
        if msg.rich:
            widget = RichChatMessage(role=msg.role, content=msg.content, mode=msg.mode)
        else:
            widget = MarkdownChatMessage(role=msg.role, content=msg.content, mode=msg.mode)

        # Remark: this part identifies if the current message and the previous message are both system/error messages, and if so
        # adds the --after-system class to the current message. This allows us to style consecutive system/error messages differently
        if msg.role in (Role.SYSTEM, Role.ERROR):
            children = area.children
            if children and isinstance(children[-1], ChatMessage) and children[-1]._role in (Role.SYSTEM, Role.ERROR):
                widget.add_class("--after-system")

        area.mount(widget)
        area.scroll_end(animate=False)

    def update_status_bar(self) -> None:
        """Sync the status bar with the current mode and context."""
        bar = self.query_one("#status-bar", StatusBar)
        bar.mode = self.session_mode.value
        bar.topic_path = list(self._topic_path)
        if self._agent_session is not None:
            bar.token_usage = self._agent_session.token_usage
            bar.model_name = self._agent_session._model_name or ""
        if self.options is not None:
            bar.verbosity = self.options.get(Options.Agent.AnswerVerbosity)
        bar.mutate_reactive(StatusBar.token_usage)

    def _restore_chat_input(self) -> None:
        """Restore focus and placeholder to the chat input."""
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.placeholder = "Type a message or /command ..."
        chat_input.focus()

    # ------------------------------------------------------------------
    # Input handling & command palette
    # ------------------------------------------------------------------

    # Commands that require the agent to be idle before executing.
    _AGENT_GATED_COMMANDS = {"commit", "options"}

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        self._hide_palette()

        text = event.value.strip()
        if not text:
            return

        command = parse_input(text)
        needs_idle = command is None or command.name in self._AGENT_GATED_COMMANDS

        if needs_idle and self._agent_busy:
            self.notify("Agent is thinking, you can submit after it completes or interrupt with Ctrl+C")
            return

        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.clear()
        chat_input.push_history(text)

        if command is not None:
            self._handle_command(command.name, command.args)
        else:
            self._handle_chat(text)

    def _handle_command(self, name: str, args: str) -> None:
        self._log.debug("command dispatched: /%s %s", name, args)

        async def _run() -> None:
            try:
                line = f"{name} {args}".strip()
                result = await self._command_registry.execute(line)
                if result:
                    self.append_message(
                        ChatMessageData(role=Role.SYSTEM, content=result, rich=True)
                    )
            except KeyError:
                self.notify(f"Unknown command: /{name}", severity="error")
            except Exception as e:
                self._log.exception("Error executing command: /%s %s", name, args, exc_info=e, stack_info=True)
                self.append_message(
                    ChatMessageData(
                        role=Role.ERROR,
                        content=(
                            f"Error executing command /{name} {args}: {traceback.format_exc()}"
                        )
                    )
                )

        self.run_worker(_run())

    def _handle_chat(self, text: str) -> None:
        self._log.debug("Chat submitted (%d chars)", len(text))

        # Post the user's message to the message history
        self.append_message(ChatMessageData(role=Role.USER, content=text))

        # Start the agent to have it respond
        self._start_agent()

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

    def _hide_palette(self) -> None:
        """Hide the command palette and restore input margin."""
        palette = self.query_one("#command-palette", CommandPalette)
        chat_input = self.query_one("#chat-input", ChatInput)
        palette.remove_class("visible")
        chat_input.remove_class("palette-open")
        chat_input.palette_active = False

    # ------------------------------------------------------------------
    # Keybinding actions
    # ------------------------------------------------------------------

    def cancel_agent(self) -> None:
        """Cancel the running agent worker, if any."""
        if self._agent_busy and self._agent_worker is not None:
            self._agent_worker.cancel()

    def action_cancel_or_copy(self) -> None:
        selected = self.screen.get_selected_text()
        if selected:
            self.app.copy_to_clipboard(selected)
        else:
            self.cancel_agent()

    def action_refocus_input(self) -> None:
        self.query_one("#chat-input").focus()

    def action_focus_prev_widget(self) -> None:
        self._navigate_active_widgets(-1)

    def action_focus_next_widget(self) -> None:
        self._navigate_active_widgets(1)

    def _navigate_active_widgets(self, direction: int) -> None:
        """Navigate the active widget stack by *direction* (-1 or +1)."""
        if not self._active_widgets:
            return

        # Find which widget currently has focus (or contains focus).
        focused = self.screen.focused
        current_idx: int | None = None
        if focused is not None:
            for i, w in enumerate(self._active_widgets):
                if focused is w or w in focused.ancestors_with_self:
                    current_idx = i
                    break

        if current_idx is not None:
            new_idx = current_idx + direction
            # Clamp — don't wrap, just stop at the ends.
            new_idx = max(0, min(new_idx, len(self._active_widgets) - 1))
        else:
            # Focus is not on any active widget — jump to nearest end.
            new_idx = len(self._active_widgets) - 1 if direction < 0 else 0

        target = self._active_widgets[new_idx]
        target.focus()
        target.scroll_visible(animate=False)

    def action_toggle_last_agent_message(self) -> None:
        harnesses = self.query(AgentMessageHarness)
        for harness in reversed(harnesses):
            msgs = harness.query(ChatMessage)
            if msgs:
                last_msg = list(msgs)[-1]
                last_msg.toggle_collapse()
                return

    def action_toggle_last_tool_call(self) -> None:
        harnesses = self.query(AgentMessageHarness)
        for harness in reversed(harnesses):
            tool_list = harness._last_tool_list
            if tool_list is not None:
                tool_list.action_toggle_collapse()
                return

    async def action_cycle_mode(self) -> None:
        cycle = {Mode.IDLE: Mode.LEARN, Mode.LEARN: Mode.REVIEW, Mode.REVIEW: Mode.IDLE}
        await self._set_mode(cycle[self.session_mode], silent=True)

    async def action_cycle_verbosity(self) -> None:
        choices = Options.Agent.AnswerVerbosity.choices
        current = self.options.get(Options.Agent.AnswerVerbosity)
        idx = choices.index(current) if current in choices else 0
        new_value = choices[(idx + 1) % len(choices)]
        await self.options.set(Options.Agent.AnswerVerbosity, new_value)
        await self.options.post_update()
        self.update_status_bar()

    async def _on_options_post_update(self, options: Options) -> None:
        """React to option changes: reset verbosity hint, clear stale cache display."""
        self._verbosity_hint_allowed = True

        if (
            options.get(Options.Agent.Provider) == "anthropic"
            and options.get(Options.Agent.Anthropic.PromptCache) != "enabled"
        ):
            if self._agent_session is not None:
                self._agent_session.token_usage.cache_read_tokens = None
                self._agent_session.token_usage.cache_creation_tokens = None
                self.update_status_bar()

    # ------------------------------------------------------------------
    # Command registration & handlers
    # ------------------------------------------------------------------

    def _register_commands(self, registry: CommandRegistry) -> None:
        """Register all slash commands with the click-based registry."""

        @registry.group(name="options", help="Open settings and configuration",
                        invoke_without_command=True)
        @click.option("-e", "--edit", is_flag=True, help="Open in $EDITOR")
        @click.option("-g", "--global", "scope", flag_value="global",
                      help="Target global options")
        @click.option("-s", "--session", "scope", flag_value="session",
                      default=True, help="Target session options (default)")
        @click.pass_context
        async def options_group(ctx, edit, scope):
            if ctx.invoked_subcommand is None:
                await self._cmd_options(edit=edit, scope=scope)

        @options_group.command(name="get", help="Get an option value")
        @click.option("-g", "--global", "scope", flag_value="global",
                      help="Target global options")
        @click.option("-s", "--session", "scope", flag_value="session",
                      default=True, help="Target session options (default)")
        @click.argument("name")
        async def options_get(scope, name):
            await self._cmd_options_get(scope=scope, name=name)

        @options_group.command(name="set", help="Set an option value")
        @click.option("-g", "--global", "scope", flag_value="global",
                      help="Target global options")
        @click.option("-s", "--session", "scope", flag_value="session",
                      default=True, help="Target session options (default)")
        @click.argument("name")
        @click.argument("value")
        async def options_set(scope, name, value):
            await self._cmd_options_set(scope=scope, name=name, value=value)

        @registry.command(name="rename", help="Rename the current tab")
        @click.argument("name", nargs=-1, required=True)
        async def rename(name: tuple[str, ...]):
            await self._cmd_rename(" ".join(name))

        @registry.command(name="help", help="Show available commands and usage")
        @click.argument("command_name", default="", required=False)
        async def help_cmd(command_name: str):
            await self._cmd_help(command_name)

        @registry.command(name="quit", help="Quit the application")
        async def quit_cmd():
            self.app.exit()

        @registry.command(name="clear", help="Clear chat messages")
        async def clear():
            await self._cmd_clear()

        @registry.command(name="explore", help="Browse topics, entries, and flashcards")
        async def explore():
            await self._cmd_explore()

        @registry.command(name="idle", help="Return to idle mode")
        async def idle():
            await self._cmd_idle()

        @registry.command(name="learn", help="Enter learning mode: set curriculum and topic context")
        async def learn():
            await self._cmd_learn()

        @registry.command(name="review", help="Enter review mode: quizzes and practice")
        async def review():
            await self._cmd_review()

        @registry.command(name="new", help="Open a new chat session tab")
        async def new():
            await self._cmd_new()

        @registry.command(name="commit", help="Select learn-mode messages to commit as knowledge")
        async def commit():
            await self._cmd_commit()

        @registry.command(name="logs", help="Open the logs viewer tab")
        async def logs():
            await self._cmd_logs()

        @registry.command(name="close", help="Close the current chat session tab")
        async def close():
            await self._cmd_close()

        if getattr(self.app, "debug_logging", False):
            @registry.command(name="test-flashcards", help="Open flashcard study widget with sample data")
            async def test_flashcards():
                await self._cmd_test_flashcards()

            @registry.command(name="test-flashcard-proposal", help="Open flashcard proposal widget with sample data")
            async def test_flashcard_proposal():
                await self._cmd_test_flashcard_proposal()

            @registry.command(name="test-commit-proposal", help="Open commit proposal widget with sample data")
            async def test_commit_proposal():
                await self._cmd_test_commit_proposal()

    async def _set_mode(
        self,
        mode: Mode,
        *,
        silent: bool = False,
        source: Literal["user", "agent"] = "user",
    ) -> None:
        """Set the session mode.

        Updates the TUI-level ``session_mode`` and (for user-initiated
        changes) queues a pending mode change on the agent middleware so
        graph state is updated on the next model call.

        Args:
            mode: The target mode.
            silent: Suppress the chat system message (e.g. for shift+tab
                cycling or agent-initiated changes).
            source: ``"user"`` for UI-initiated changes (shift+tab, slash
                commands) — these queue a pending change on the middleware.
                ``"agent"`` for tool-initiated changes — graph state is
                updated directly via ``Command``, so no pending change is
                needed.
        """

        # Branch variables:
        #   - silent
        #   - source
        #   - agent_busy

        # source is "agent"
        #   - Under this condition, these assertions must pass
        #       - agent_busy is True
        #       - silent is True
        if source == "agent":
            assert self._agent_busy
            silent = True # Just override
        
        # In all cases, if the new mode is no different from the current, just return early.
        if self.session_mode == mode:
            # Since "silent" is always true when source is "agent", this should never fire while the agent is busy.
            if not silent:
                self.append_message(
                    ChatMessageData(role=Role.SYSTEM, content=f"Already in {mode.value} mode.")
                )
            return
        
        # In this case:
        #   - Mutate self.session_mode and propagate to UI
        #   - Graph state is updated by the agent tool call
        #   - Clear pending user-initated mode changes - agent tool calls take priority.
        if source == "agent":
            self.session_mode = mode
            self.update_status_bar()

            # Clearing the pending user-initiated mode change addresses this edge case:
            #   - User sets mode to A while agent is running, then agent runs set_tool to change mode to B
            #
            # The agent's tool call wins in this case, and we discard the user-initiated change.
            await self._agent_session._mode_middleware.clear_pending_user_mode()
            return

        # From hereron-in, source is "user"
        message = "Returned to idle mode." if mode == Mode.IDLE else f"Entered {mode.value} mode."
        if self._agent_busy:
            # Mutate self.session_mode
            self.session_mode = mode
            
            # Post a pending user mode change to the agent. This gets intercepted before the next model call and is used
            # to automatically update the mode in the agnet state graph.
            if self._agent_session is not None:
                await self._agent_session.set_pending_user_mode(mode.value)

            if not silent:
                # append message to _UI only_.
                # set_pending_user_mode submits a message directly to the agent _when_ the queue is drained, which is
                # directly before the next model invocation (within)
                self.append_message(
                    ChatMessageData(role=Role.SYSTEM, content=message),
                    ui_only=True
                )
        
        else:
            self.session_mode = mode
            if silent:
                # Just post a notification to the agent
                if self._agent_session is not None:
                    self._agent_session.add_system_notification(message)
            else:
                # Post a notification to both the UI, and the agent.
                self.append_message(ChatMessageData(role=Role.SYSTEM, content=message))

        # Propagate to UI
        self.update_status_bar()

    async def _cmd_idle(self) -> None:
        await self._set_mode(Mode.IDLE)

    async def _cmd_learn(self) -> None:
        await self._set_mode(Mode.LEARN)

    async def _cmd_review(self) -> None:
        await self._set_mode(Mode.REVIEW)

    async def _cmd_clear(self) -> None:
        """Clear all visible chat messages from the message area."""
        area = self.query_one("#message-area")
        await area.remove_children()
        self.messages.clear()
        self._active_widgets.clear()

    async def _cmd_explore(self) -> None:
        """Browse topics, entries, and flashcards."""
        existing = list(self.query(ExplorerViewer))
        if existing:
            tree = existing[-1]
            tree.focus()
        else:
            area = self.query_one("#message-area")
            tree = ExplorerViewer(id="explorer")
            await area.mount(tree)
            area.scroll_end(animate=False)
            self._active_widgets.append(tree)
            tree.focus()
        self.query_one("#chat-input").placeholder = (
            "Ctrl+l to refocus chat input"
        )

    async def _cmd_test_flashcards(self) -> None:
        """Open the flashcard study widget with sample data."""
        sample_cards = [
            {"question": "What is the time complexity of binary search?", "answer": "O(log n) — each comparison halves the remaining search space."},
            {"question": "Explain the difference between a stack and a queue.", "answer": "A stack is LIFO (Last In, First Out): the most recently added element is removed first.\n\nA queue is FIFO (First In, First Out): the earliest added element is removed first."},
            {"question": "What is a hash collision and how is it typically resolved?", "answer": "A hash collision occurs when two different keys produce the same hash value.\n\nCommon resolution strategies:\n• Chaining — each bucket holds a linked list of entries\n• Open addressing — probe for the next available slot (linear, quadratic, or double hashing)"},
            {"question": "What does the CAP theorem state?", "answer": "A distributed system can provide at most two of the following three guarantees simultaneously:\n\n• Consistency — every read returns the most recent write\n• Availability — every request receives a response\n• Partition tolerance — the system operates despite network partitions"},
            {"question": "What is the difference between concurrency and parallelism?", "answer": "Concurrency is about dealing with multiple tasks at once (structure).\nParallelism is about doing multiple tasks at once (execution).\n\nConcurrency is possible on a single core via interleaving; parallelism requires multiple cores."},
        ]

        area = self.query_one("#message-area")
        study = FlashcardViewer()
        await area.mount(study)
        study.set_flashcards(sample_cards)
        area.scroll_end(animate=False)
        self._active_widgets.append(study)
        study.focus()
        self.query_one("#chat-input").placeholder = (
            "Ctrl+l to refocus chat input"
        )

    async def _cmd_test_flashcard_proposal(self) -> None:
        """Open the flashcard proposal widget with sample data."""
        sample_cards = [
            {
                "question": "What is the time complexity of binary search?",
                "answer": "O(log n) — each comparison halves the remaining search space.",
                "testing_notes": "Ask for best/worst case separately.",
                "entry_ids": [1, 3],
            },
            {
                "question": "Explain the difference between a stack and a queue.",
                "answer": "A stack is LIFO (Last In, First Out): the most recently added element is removed first.\n\nA queue is FIFO (First In, First Out): the earliest added element is removed first.",
                "testing_notes": None,
                "entry_ids": [2],
            },
            {
                "question": "What is a hash collision and how is it typically resolved?",
                "answer": "A hash collision occurs when two different keys produce the same hash value.\n\nCommon resolution strategies:\n• Chaining — each bucket holds a linked list of entries\n• Open addressing — probe for the next available slot (linear, quadratic, or double hashing)",
                "testing_notes": "Can ask about chaining vs open addressing trade-offs as a follow-up.",
                "entry_ids": [],
            },
        ]

        area = self.query_one("#message-area")
        proposal = FlashcardProposal(flashcards=sample_cards)
        await area.mount(proposal)
        area.scroll_end(animate=False)
        self._active_widgets.append(proposal)
        proposal.focus()
        self.query_one("#chat-input").placeholder = (
            "Ctrl+l to refocus chat input"
        )

    async def _cmd_test_commit_proposal(self) -> None:
        """Open the commit proposal widget with sample data."""
        sample_entries = [
            {
                "title": "Binary Search",
                "content": "Binary search is a divide-and-conquer algorithm that finds a target value in a sorted array by repeatedly halving the search space.\n\nTime complexity: O(log n)\nSpace complexity: O(1) iterative, O(log n) recursive",
                "entry_type": "fact",
                "topic_id": 1,
            },
            {
                "title": "Hash Table Collision Resolution",
                "content": "When two keys hash to the same bucket, a collision occurs. Common strategies:\n\n• Chaining — each bucket holds a linked list\n• Open addressing — probe for the next available slot\n• Robin Hood hashing — minimize probe distance variance",
                "entry_type": "exposition",
                "topic_id": 1,
            },
            {
                "title": "CAP Theorem Overview",
                "content": "The CAP theorem states that a distributed system can provide at most two of three guarantees: Consistency, Availability, and Partition tolerance.\n\nIn practice, partition tolerance is non-negotiable, so the real trade-off is between consistency and availability.",
                "entry_type": "overview",
                "topic_id": 2,
            },
        ]
        sample_topic_map = {
            1: "Data Structures",
            2: "Distributed Systems",
        }

        area = self.query_one("#message-area")
        proposal = CommitProposal(entries=sample_entries, topic_map=sample_topic_map)
        await area.mount(proposal)
        area.scroll_end(animate=False)
        self._active_widgets.append(proposal)
        proposal.focus()
        self.query_one("#chat-input").placeholder = (
            "Ctrl+l to refocus chat input"
        )

    async def _cmd_options(self, *, edit: bool = False, scope: str = "session") -> None:
        """Open settings and configuration."""
        is_global = scope == "global"
        target = self.app.options if is_global else self.options  # type: ignore[attr-defined]

        if edit:
            jsonc_text = build_jsonc_snapshot(target)
            editor = os.environ.get("EDITOR", "nano")

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".jsonc", prefix="rhizome-options-", delete=False
            ) as tmp:
                tmp.write(jsonc_text)
                tmp_path = tmp.name

            try:
                with self.app.suspend():
                    subprocess.run([editor, tmp_path])

                new_text = Path(tmp_path).read_text(encoding="utf-8")
                new_opts = parse_jsonc(new_text)

                spec_map = {s.resolved_name: s for s in Options.spec()}
                changed: list[str] = []
                for key, val in new_opts.items():
                    s = spec_map.get(key)
                    if s is not None and target.get(s) != val:
                        await target.set(s, val)
                        changed.append(key)

                await target.post_update()
                if changed:
                    names = ", ".join(f"`{n}`" for n in changed)
                    msg = f"Options updated: {names}"
                else:
                    msg = "No changes made."
                self.append_message(
                    ChatMessageData(role=Role.SYSTEM, content=msg)
                )
            except Exception as exc:
                self.append_message(
                    ChatMessageData(role=Role.SYSTEM, content=f"Error applying options: {exc}")
                )
            finally:
                os.unlink(tmp_path)
            return

        # Inline widget mode — dismiss any existing editor first
        for ed in self.query(OptionsEditor):
            await ed.remove()

        area = self.query_one("#message-area")
        editor_widget = OptionsEditor(target, id="options-editor")
        await area.mount(editor_widget)
        area.scroll_end(animate=False)
        editor_widget.focus()

    async def _cmd_options_get(self, *, scope: str = "session", name: str) -> None:
        """Print the current value of a single option."""
        spec_map = {s.resolved_name: s for s in Options.spec()}
        spec = spec_map.get(name)
        if spec is None:
            self.append_message(
                ChatMessageData(role=Role.SYSTEM, content=f"Unknown option: {name}")
            )
            return
        is_global = scope == "global"
        target = self.app.options if is_global else self.options  # type: ignore[attr-defined]
        value = target.get(spec)
        self.append_message(
            ChatMessageData(role=Role.SYSTEM, content=f"{name} = {value!r}")
        )

    async def _cmd_options_set(self, *, scope: str = "session", name: str, value: str) -> None:
        """Set an option value."""
        spec_map = {s.resolved_name: s for s in Options.spec()}
        spec = spec_map.get(name)
        if spec is None:
            self.append_message(
                ChatMessageData(role=Role.SYSTEM, content=f"Unknown option: {name}")
            )
            return
        is_global = scope == "global"
        target = self.app.options if is_global else self.options  # type: ignore[attr-defined]
        try:
            coerced = spec.from_string(value)
            await target.set(spec, coerced)
            await target.post_update()
            self.append_message(
                ChatMessageData(role=Role.SYSTEM, content=f"{name} set to {coerced!r}")
            )
        except (ValueError, TypeError) as exc:
            self.append_message(
                ChatMessageData(role=Role.SYSTEM, content=f"Error setting {name}: {exc}")
            )

    async def _cmd_help(self, command_name: str = "") -> None:
        """Show available commands, or details for a specific command."""
        if command_name:
            name = command_name.strip().lstrip("/")
            cmd = self._command_registry.commands.get(name)
            if cmd is None:
                text = f"Unknown command: /{name}\nType /help to see available commands."
            else:
                # Get help text from click command
                with cmd.make_context(name, [], max_content_width=self._command_registry.max_content_width) as ctx:
                    text = ctx.get_help()
        else:
            lines = ["**Available commands:**", ""]
            for name in sorted(self._command_registry.commands):
                cmd = self._command_registry.commands[name]
                # Use the callback's docstring or the click help string
                desc = cmd.help or (cmd.callback.__doc__ if cmd.callback else "") or ""
                # Take only the first line of the description
                desc = desc.strip().split("\n")[0] if desc else ""
                lines.append(f"  /{name} — {desc}")
            lines.append("")
            lines.append("Commands support standard CLI syntax (options, flags, --help).")
            lines.append("e.g. /options --edit --global, /options set agent.temperature 0.5")
            text = "\n".join(lines)

        self.append_message(ChatMessageData(role=Role.SYSTEM, content=text, rich=True))

    async def _cmd_rename(self, name: str) -> None:
        """Rename the active chat session tab."""
        from rhizome.tui.screens.main import ChatTabPane

        new_name = name.strip()
        if not new_name:
            self.append_message(
                ChatMessageData(role=Role.SYSTEM, content="Usage: /rename <name>")
            )
            return

        tabs = self.app.screen.query_one("#tabs", TabbedContent)
        active_pane = tabs.active_pane
        if active_pane is not None and isinstance(active_pane, ChatTabPane):
            active_pane.full_name = new_name
            active_pane._update_tab_label()

    async def _cmd_new(self) -> None:
        """Create a new chat session tab."""
        from rhizome.tui.screens.main import MainScreen

        screen = self.app.screen
        if isinstance(screen, MainScreen):
            await screen._add_tab()

    async def _cmd_commit(self) -> None:
        """Select learn-mode messages to commit as knowledge."""
        self.enter_commit_mode()

    async def _cmd_logs(self) -> None:
        """Open the logs tab."""
        from rhizome.tui.screens.main import MainScreen

        screen = self.app.screen
        if isinstance(screen, MainScreen):
            await screen._add_log_tab()

    async def _cmd_close(self) -> None:
        """Close the current chat session tab."""
        from rhizome.tui.screens.main import MainScreen

        screen = self.app.screen
        if isinstance(screen, MainScreen):
            await screen._close_active_tab()

    # ------------------------------------------------------------------
    # Child widget events (topic tree, options editor)
    # ------------------------------------------------------------------

    def on_explorer_viewer_topic_selected(self, event: ExplorerViewer.TopicSelected) -> None:
        self.active_topic = event.topic
        self._topic_path = event.path
        self.update_status_bar()
        self.append_message(ChatMessageData(role=Role.SYSTEM, content=f"Selected topic: {self.active_topic.name}"))
        for viewer in self.query(ExplorerViewer):
            viewer.remove()
        self._restore_chat_input()

    def on_explorer_viewer_dismissed(self, event: ExplorerViewer.Dismissed) -> None:
        for viewer in self.query(ExplorerViewer):
            viewer.remove()
        self._restore_chat_input()

    def on_flashcard_viewer_dismissed(self, event: FlashcardViewer.Dismissed) -> None:
        for w in self.query(FlashcardViewer):
            w.remove()
        self._restore_chat_input()

    def on_flashcard_viewer_session_complete(self, event: FlashcardViewer.SessionComplete) -> None:
        self.append_message(ChatMessageData(role=Role.SYSTEM, content="Flashcard session complete."))
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

        if event.changes:
            lines = [f"  {name}: {old} → {new}" for name, (old, new) in event.changes.items()]
            self.append_message(ChatMessageData(
                role=Role.SYSTEM, content="Options changed:\n" + "\n".join(lines), rich=True
            ))

        async def _notify() -> None:
            if self.options is not None:
                await self.options.post_update()

        self.run_worker(_notify())

    def on_hint_higher_verbosity(self, event: HintHigherVerbosity) -> None:
        now = time.monotonic()
        elapsed = now - self._verbosity_hint_last_shown
        if self._verbosity_hint_allowed or elapsed >= 600:
            self.notify(
                "Hint: the agent has indicated that a higher verbosity "
                "may be required to properly answer your query.",
                timeout=8
            )
            self._verbosity_hint_allowed = False
            self._verbosity_hint_last_shown = now

    def on_commit_approved(self, event: CommitApproved) -> None:
        self.append_message(ChatMessageData(
            role=Role.SYSTEM,
            content=f"Committed {event.count} knowledge entry/entries to the database.",
        ))

    # ------------------------------------------------------------------
    # Commit mode
    # ------------------------------------------------------------------

    def enter_commit_mode(self) -> None:
        """Activate commit mode: decorate selectable messages for selection."""

        # Determine which messages are selectable based on the commit_selectable option.
        level = self.options.get(Options.CommitSelectable) if self.options else "learn_only"
        if level == "all_agent":
            selector = "ChatMessage.agent-message"
        elif level == "all":
            selector = "ChatMessage.user-message, ChatMessage.agent-message"
        else:
            selector = "ChatMessage.agent-message.learn-mode"

        selectable = list(self.query(selector))
        if not selectable:
            self.append_message(ChatMessageData(role=Role.SYSTEM, content="No selectable messages to commit."))
            return

        self._commit.active = True
        self._commit.selectable = selectable
        self._commit.cursor = 0
        self._commit.selected = set()

        # Decorate each message with a checkbox and the --commit-selectable class, mount a checkbox
        # to the message, and set the first message as the initial cursor position.
        for msg in self._commit.selectable:
            msg.add_class("--commit-selectable")
            checkbox = Static("☐", classes="commit-checkbox")
            msg.mount(checkbox, before=0)

        self._commit.selectable[0].add_class("--commit-cursor")
        self._commit.selectable[0].scroll_visible()

        # Disable the chat input and show commit mode instructions in the placeholder.
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.disabled = True
        chat_input.placeholder = "↑↓ navigate  Space select  Ctrl+Enter confirm  Esc cancel"

    def confirm_commit_selection(self) -> None:
        """Deactivate commit mode, clean up decorations, and optionally post results."""

        # Clean up all commit-mode decorations and state.
        for msg in self._commit.selectable:
            msg.remove_class("--commit-selectable")
            msg.remove_class("--commit-cursor")
            msg.remove_class("--commit-selected")
            for cb in msg.query(".commit-checkbox"):
                cb.remove()

        # Restore the chat input.
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.disabled = False
        self._restore_chat_input()

        # Remark: we do NOT clear the commit state until either a CommitApproved or a CommitCanceled
        # event is received. This is because the commit subagent access the commit state directly, and
        # moreover can modify the commit selection (e.g. to deselect messages at user request) before 
        # posting the final approval event.
        #
        # We merely deactivate the commit mode here to exit the selection UI and prevent further changes.
        self._commit.active = False

        if not self._commit.selected:
            self.append_message(ChatMessageData(role=Role.SYSTEM, content="No messages selected for commit."))
            return

        # Build the commit payload and inject it into agent state for the
        # commit tools to read via ToolRuntime.
        commit_payload = [
            {"index": idx, "content": self._commit.selectable[idx].content_text}
            for idx in sorted(self._commit.selected)
        ]
        self._agent_session.set_commit_payload(commit_payload)

        # Compute the approximate token count for the selected messages, and determine routing based on subagent commit options.
        combined = "\n".join(entry["content"] for entry in commit_payload)
        approx_tokens = count_tokens_approximately([HumanMessage(content=combined)])
        num_messages = len(self._commit.selected)

        use_subagent = False
        if self.options and self.options.get(Options.Subagents.Commit.Enabled) == "enabled":
            criterion = self.options.get(Options.Subagents.Commit.RoutingCriterion)
            threshold = self.options.get(Options.Subagents.Commit.RoutingThreshold)
            if criterion == "tokens":
                use_subagent = approx_tokens >= threshold
            else:
                use_subagent = num_messages >= threshold

        if use_subagent:
            self._agent_session.add_system_notification(
                f"User selected {num_messages} message(s) for commit "
                f"(~{approx_tokens} tokens). Use invoke_commit_subagent to delegate "
                "knowledge entry extraction, then present the proposal to the user."
            )
        else:
            self._agent_session.add_system_notification(
                f"User selected {num_messages} message(s) for commit "
                f"(~{approx_tokens} tokens). Use inspect_commit_payload and "
                "create_commit_proposal to draft entries directly, then present "
                "the proposal to the user."
            )
        self._start_agent()
            

    def _commit_move_cursor(self, delta: int) -> None:
        """Move the commit-mode cursor highlight."""
        if not self._commit.selectable:
            return

        new_index = self._commit.cursor + delta
        if new_index < 0 or new_index >= len(self._commit.selectable):
            return

        # Remove cursor highlight from the old message, update the index, and add it to the new message.
        if 0 <= self._commit.cursor < len(self._commit.selectable):
            self._commit.selectable[self._commit.cursor].remove_class("--commit-cursor")
        self._commit.cursor = new_index

        target = self._commit.selectable[self._commit.cursor]
        target.add_class("--commit-cursor")
        target.scroll_visible()

    def on_key(self, event) -> None:
        # Remark: we only capture key events for commit mode, so we don't interfere with normal input,
        # command palette navigation, etc.
        if not self._commit.active:
            return

        # Stop propagation and prevent default behavior for all keys in commit mode,
        # since we're using them for navigation and selection.
        event.stop()
        event.prevent_default()

        key = event.key
        if key == "up":
            if self._commit.cursor > 0:
                self._commit_move_cursor(-1)

        elif key == "down":
            if self._commit.cursor < len(self._commit.selectable) - 1:
                self._commit_move_cursor(1)

        elif key == "space":
            msg = self._commit.selectable[self._commit.cursor]
            checkbox = msg.query_one(".commit-checkbox")

            if self._commit.cursor in self._commit.selected:
                # Deselect the current message.
                self._commit.selected.discard(self._commit.cursor)
                msg.remove_class("--commit-selected")

                if checkbox:
                    checkbox.update("☐")
            else:
                # Select, and move the cursor to the next message if possible.
                self._commit.selected.add(self._commit.cursor)
                msg.add_class("--commit-selected")

                if checkbox:
                    checkbox.update("☑")

                if self._commit.cursor < len(self._commit.selectable) - 1:
                    self._commit_move_cursor(1)

        elif key == "ctrl+j":
            # Confirm selection and exit commit mode.
            self.confirm_commit_selection()

        elif key == "escape":
            # Cancel selection and exit commit mode.
            self.confirm_commit_selection(None)
