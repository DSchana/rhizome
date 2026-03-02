"""ChatPane — core chat UI: message area, input box, and command palette."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import rich_click as click

from rhizome.logs import get_logger

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static, TabbedContent
from textual.worker import Worker

from rhizome.agent import AgentSession
from rhizome.agent.agent import get_agent_kwargs
from rhizome.config import get_log_dir
from rhizome.db import Topic
from rhizome.tui.commands import CommandRegistry, parse_input
from rhizome.tui.options import Options, OptionScope, build_jsonc_snapshot, parse_jsonc
from rhizome.tui.types import ChatMessageData, Mode, Role
from rhizome.tui.widgets.chat_input import ChatInput
from rhizome.tui.widgets.command_palette import CommandPalette
from rhizome.tui.widgets.agent_message_harness import AgentMessageHarness
from rhizome.tui.widgets.message import ChatMessage, MarkdownChatMessage, RichChatMessage
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
        # TODO: move logging into the AgentSession.
        self._agent_log: logging.Logger | None = None
        self._agent_log_handler: logging.FileHandler | None = None

        # Commit mode state
        # - _commit_mode is True when the user has entered commit mode for selecting learn-mode messages to commit.
        # - _commit_selectable is the list of ChatMessage widgets that are selectable in commit mode.
        # - _commit_cursor is the index of the currently highlighted message in _commit_selectable.
        # - _commit_selected is the set of indices in _commit_selectable that the user has selected for commit.
        self._commit_mode: bool = False
        self._commit_selectable: list[ChatMessage] = []
        self._commit_cursor: int = 0
        self._commit_selected: set[int] = set()

        # Command registry
        self._command_registry = CommandRegistry()
        self._register_commands(self._command_registry)

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
            app=self.app,
            chat_pane=self,
            provider=provider,
            model_name=model_name,
            agent_kwargs=agent_kwargs,
            on_token_usage_changed=self.update_status_bar,
            on_rebuild_agent=self._on_agent_rebuilt,
        )

        # Subscribe to post-update so agent rebuilds when options change
        self.options.subscribe_post_update(self._agent_session.on_options_post_update)

        # Add the welcome header, assuming _show_welcome is True.
        area = self.query_one("#message-area", VerticalScroll)
        if self._show_welcome:
            area.mount(WelcomeHeader())

        # Focus the chat input
        self.query_one("#chat-input", ChatInput).focus()

        # TODO: move this logging setup into the AgentSession.
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

    def on_resize(self) -> None:
        self._sync_registry_width()

    def _sync_registry_width(self) -> None:
        """Update the command registry's max_content_width from the pane's current width."""
        self._command_registry.max_content_width = max(self.size.width - 15, 40)

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

    _log = get_logger("tui.chat_pane")

    def _handle_command(self, name: str, args: str) -> None:
        if name == "quit":
            self.app.exit()
            return

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
                self._log.exception("Error executing command: /%s %s", name, args)
                self.notify(str(e), severity="error")

        self.run_worker(_run())

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def _set_mode(self, mode: Mode, *, silent: bool = False) -> None:
        """Set the session mode.

        When *silent* is ``True`` the system message is suppressed (useful
        when the agent switches modes programmatically).
        """
        if self.session_mode == mode:
            if not silent:
                self.append_message(
                    ChatMessageData(role=Role.SYSTEM, content=f"Already in {mode.value} mode.")
                )
            return
        self.session_mode = mode
        if not silent:
            label = "Returned to idle mode." if mode == Mode.IDLE else f"Entered {mode.value} mode."
            self.append_message(ChatMessageData(role=Role.SYSTEM, content=label))
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

    async def _cmd_explore(self) -> None:
        """Browse and select topics from the topic tree."""
        existing = list(self.query(TopicTree))
        if existing:
            tree = existing[-1]
            tree.query_one("#topic-tree-help").update(
                "Use arrow keys to navigate, enter to select a topic."
            )
            tree.focus()
        else:
            area = self.query_one("#message-area")
            tree = TopicTree(id="topic-tree")
            await area.mount(tree)
            area.scroll_end(animate=False)
            tree.focus()
        self.query_one("#chat-input").placeholder = (
            "Use Tab/Shift+Tab to navigate between widgets"
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
                for key, val in new_opts.items():
                    s = spec_map.get(key)
                    if s is not None:
                        await target.set(s, val)

                await target.post_update()
                self.append_message(
                    ChatMessageData(role=Role.SYSTEM, content="Options updated.")
                )
            except Exception as exc:
                self.append_message(
                    ChatMessageData(role=Role.SYSTEM, content=f"Error applying options: {exc}")
                )
            finally:
                os.unlink(tmp_path)
            return

        # Inline widget mode
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
            lines.append("Type /help <command> for details, or /<command> --help.")
            text = "\n".join(lines)

        self.append_message(ChatMessageData(role=Role.SYSTEM, content=text, rich=True))

    async def _cmd_rename(self, name: str) -> None:
        """Rename the active chat session tab."""
        from rhizome.tui.screens.chat import ChatTabPane

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
        from rhizome.tui.screens.chat import ChatScreen

        screen = self.app.screen
        if isinstance(screen, ChatScreen):
            await screen._add_tab()

    async def _cmd_commit(self) -> None:
        """Select learn-mode messages to commit as knowledge."""
        self.enter_commit_mode()

    async def _cmd_logs(self) -> None:
        """Open the logs tab."""
        from rhizome.tui.screens.chat import ChatScreen

        screen = self.app.screen
        if isinstance(screen, ChatScreen):
            await screen._add_log_tab()

    async def _cmd_close(self) -> None:
        """Close the current chat session tab."""
        from rhizome.tui.screens.chat import ChatScreen

        screen = self.app.screen
        if isinstance(screen, ChatScreen):
            await screen._close_active_tab()

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

        @registry.command(name="clear", help="Clear chat messages")
        async def clear():
            await self._cmd_clear()

        @registry.command(name="topics", help="Browse and select topics from the topic tree")
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

    def _handle_chat(self, text: str) -> None:
        self._log.debug("Chat submitted (%d chars)", len(text))
        # Post the user's message to the message history
        self.append_message(ChatMessageData(role=Role.USER, content=text))

        # Construct an AgentMessageHarness for capturing the View aspects of the agent stream.
        message_area = self.query_one("#message-area", VerticalScroll)
        harness = AgentMessageHarness()
        message_area.mount(harness)

        agent_session = self._agent_session
        assert agent_session is not None

        async def _run_agent() -> None:
            await harness.start_thinking()
            message_area.scroll_end(animate=False)

            try:
                await agent_session.stream(
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

        # Start the agent, setting _agent_busy to True until the worker completes.
        self._agent_busy = True
        self._agent_worker = self.run_worker(_run_agent())

    def _on_agent_rebuilt(self, old_model: str, new_model: str) -> None:
        """Called when the agent is rebuilt due to a model option change."""
        self._log.info("Agent rebuilt: %s → %s", old_model, new_model)
        self.append_message(ChatMessageData(
            role=Role.SYSTEM,
            content=(
                f"Model changed to {self._agent_session._model_name}.  \n"
                f"Profile: `{self._agent_session.model.profile}`"
            ),
        ))

    def on_agent_message_harness_interrupt_pending(
        self, event: AgentMessageHarness.InterruptPending
    ) -> None:
        """Disable chat input while an interrupt widget awaits user input."""
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.disabled = True
        chat_input.placeholder = "Respond to the agent's prompt above..."
        event.widget.focus()

    def on_agent_message_harness_interrupt_resolved(
        self, event: AgentMessageHarness.InterruptResolved
    ) -> None:
        """Re-enable chat input after the user resolves an interrupt."""
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.disabled = False
        self._restore_chat_input()

    def update_status_bar(self) -> None:
        """Sync the status bar with the current mode and context."""
        bar = self.query_one("#status-bar", StatusBar)
        bar.mode = self.session_mode.value
        bar.topic_path = list(self._topic_path)
        if self._agent_session is not None:
            bar.token_usage = self._agent_session.token_usage
        bar.mutate_reactive(StatusBar.token_usage)

    def append_message(self, msg: ChatMessageData) -> None:
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
        if self._agent_session is not None:
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

    def _restore_chat_input(self) -> None:
        """Restore focus and placeholder to the chat input."""
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.placeholder = "Type a message or /command ..."
        chat_input.focus()

    def on_topic_tree_topic_selected(self, event: TopicTree.TopicSelected) -> None:
        self.active_topic = event.topic
        self._topic_path = event.path
        self.update_status_bar()
        self.append_message(ChatMessageData(role=Role.SYSTEM, content=f"Selected topic: {self.active_topic.name}"))
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

        async def _notify() -> None:
            if self.options is not None:
                await self.options.post_update()

        self.run_worker(_notify())

    # ------------------------------------------------------------------
    # Commit mode
    # ------------------------------------------------------------------

    def enter_commit_mode(self) -> None:
        """Activate commit mode: decorate learn-mode agent messages for selection."""

        # First, find all the learn-mode agent messages in the current message area.
        selectable = list(self.query("ChatMessage.agent-message.learn-mode"))
        if not selectable:
            self.append_message(ChatMessageData(role=Role.SYSTEM, content="No learn-mode messages to commit."))
            return

        self._commit_mode = True
        self._commit_selectable = selectable
        self._commit_cursor = 0
        self._commit_selected = set()

        # Decorate each message with a checkbox and the --commit-selectable class, mount a checkbox
        # to the message, and set the first message as the initial cursor position.
        for msg in self._commit_selectable:
            msg.add_class("--commit-selectable")
            checkbox = Static("☐", classes="commit-checkbox")
            msg.mount(checkbox, before=0)

        self._commit_selectable[0].add_class("--commit-cursor")
        self._commit_selectable[0].scroll_visible()

        # Disable the chat input and show commit mode instructions in the placeholder.
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.disabled = True
        chat_input.placeholder = "↑↓ navigate  Space select  Ctrl+Enter confirm  Esc cancel"

    def exit_commit_mode(self, selected: list[ChatMessageData] | None) -> None:
        """Deactivate commit mode, clean up decorations, and optionally post results."""

        # Clean up all commit-mode decorations and state.
        for msg in self._commit_selectable:
            msg.remove_class("--commit-selectable")
            msg.remove_class("--commit-cursor")
            msg.remove_class("--commit-selected")
            for cb in msg.query(".commit-checkbox"):
                cb.remove()

        # Reset commit mode state.
        self._commit_mode = False
        self._commit_selectable = []
        self._commit_cursor = 0
        self._commit_selected = set()

        # Restore the chat input.
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.disabled = False
        self._restore_chat_input()

        # TODO: for now this is just a placeholder for the actual commit logic.
        if selected is not None and selected:
            count = len(selected)
            self.append_message(ChatMessageData(role=Role.SYSTEM, content=f"Selected {count} message(s) for commit."))

    def _commit_move_cursor(self, delta: int) -> None:
        """Move the commit-mode cursor highlight."""
        if not self._commit_selectable:
            return
        
        new_index = self._commit_cursor + delta
        if new_index < 0 or new_index >= len(self._commit_selectable):
            return

        # Remove cursor highlight from the old message, update the index, and add it to the new message.
        if 0 <= self._commit_cursor < len(self._commit_selectable):
            self._commit_selectable[self._commit_cursor].remove_class("--commit-cursor")
        self._commit_cursor = new_index

        target = self._commit_selectable[self._commit_cursor]
        target.add_class("--commit-cursor")
        target.scroll_visible()

    def on_key(self, event) -> None:
        # Remark: we only capture key events for commit mode, so we don't interfere with normal input,
        # command palette navigation, etc.
        if not self._commit_mode:
            return

        # Stop propagation and prevent default behavior for all keys in commit mode, 
        # since we're using them for navigation and selection.
        event.stop()
        event.prevent_default()

        key = event.key
        if key == "up":
            if self._commit_cursor > 0:
                self._commit_move_cursor(-1)

        elif key == "down":
            if self._commit_cursor < len(self._commit_selectable) - 1:
                self._commit_move_cursor(1)

        elif key == "space":
            msg = self._commit_selectable[self._commit_cursor]
            checkbox = msg.query_one(".commit-checkbox")

            if self._commit_cursor in self._commit_selected:
                # Deselect the current message.
                self._commit_selected.discard(self._commit_cursor)
                msg.remove_class("--commit-selected")

                if checkbox:
                    checkbox.update("☐")
            else:
                # Select, and move the cursor to the next message if possible.
                self._commit_selected.add(self._commit_cursor)
                msg.add_class("--commit-selected")

                if checkbox:
                    checkbox.update("☑")

                if self._commit_cursor < len(self._commit_selectable) - 1:
                    self._commit_move_cursor(1)

        elif key == "ctrl+j":
            # Confirm selection and exit commit mode.
            selected_messages = []
            for idx in sorted(self._commit_selected):
                m = self._commit_selectable[idx]
                selected_messages.append(
                    ChatMessageData(role=Role.AGENT, content=m.content_text)
                )
            self.exit_commit_mode(selected_messages)

        elif key == "escape":
            # Cancel selection and exit commit mode.
            self.exit_commit_mode(None)
