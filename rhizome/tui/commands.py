"""Slash command parser and registry."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from textual.widgets import TabbedContent

from rhizome.tui.options import OptionNamespaceNode, Options, parse_jsonc
from rhizome.tui.types import ChatMessageData, Mode, Role
from rhizome.tui.widgets.options_editor import OptionsEditor
from rhizome.tui.widgets.topic_tree import TopicTree

if TYPE_CHECKING:
    from rhizome.tui.app import CurriculumApp


@dataclass
class ParsedCommand:
    """Result of parsing a slash command from user input."""

    name: str
    args: str


@dataclass(frozen=True)
class Command:
    """A registered slash command.

    Handlers are standalone async functions so they can be invoked by both
    the TUI (via slash input) and the agent layer (as tools).
    """

    name: str
    description: str
    handler: Callable[[CurriculumApp, str], Awaitable[None]] | None


def parse_input(text: str) -> ParsedCommand | None:
    """Parse user input into a command if it starts with ``/``.

    Returns ``None`` if the input is not a slash command (i.e. regular
    chat text).
    """
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None

    parts = stripped.split(maxsplit=1)
    name = parts[0][1:]  # drop the leading '/'
    args = parts[1] if len(parts) > 1 else ""
    return ParsedCommand(name=name, args=args)


# ---------------------------------------------------------------------------
# Stub handlers — return a message string for display.
# These will be replaced with real implementations in later phases.
# ---------------------------------------------------------------------------


async def set_mode(app: CurriculumApp, mode: Mode, *, silent: bool = False) -> None:
    """Set the session mode. This is the shared implementation used by all
    mode-switching commands and agent tools.

    When *silent* is ``True`` the system message is suppressed (useful when
    the agent switches modes programmatically).
    """
    pane = app.active_chat_pane
    if pane.session_mode == mode:
        if not silent:
            pane.append_message(
                ChatMessageData(role=Role.SYSTEM, content=f"Already in {mode.value} mode.")
            )
        return
    pane.session_mode = mode
    if not silent:
        label = "Returned to idle mode." if mode == Mode.IDLE else f"Entered {mode.value} mode."
        pane.append_message(ChatMessageData(role=Role.SYSTEM, content=label))
    pane.update_status_bar()


async def _handle_idle(app: CurriculumApp, _args: str) -> None:
    await set_mode(app, Mode.IDLE)


async def _handle_learn(app: CurriculumApp, _args: str) -> None:
    await set_mode(app, Mode.LEARN)


async def _handle_review(app: CurriculumApp, _args: str) -> None:
    await set_mode(app, Mode.REVIEW)


def _build_jsonc_snapshot(target: Options) -> str:
    """Build a JSONC string from the spec tree for external editor use."""
    all_specs = Options.spec()
    last_resolved = all_specs[-1].resolved_name if all_specs else ""
    top_level, nodes = Options.spec_tree()

    lines = ["{"]

    def _emit_specs(specs: list, indent: str = "    ") -> None:
        for s in specs:
            for comment_line in s.jsonc_comment().splitlines():
                if comment_line.startswith("//"):
                    lines.append(f"{indent}{comment_line}")
                else:
                    lines.append(f"{indent}// {comment_line}")
            value = target.get(s)
            json_val = json.dumps(value)
            comma = "," if s.resolved_name != last_resolved else ""
            lines.append(f"{indent}{json.dumps(s.resolved_name)}: {json_val}{comma}")
            if s.resolved_name != last_resolved:
                lines.append("")

    def _emit_node(node: OptionNamespaceNode, indent: str = "    ") -> None:
        ns = node.namespace
        if ns.description:
            lines.append(f"{indent}// {ns.description}")
        _emit_specs(node.options, indent)
        for child in node.children:
            _emit_node(child, indent)

    _emit_specs(top_level)
    for node in nodes:
        _emit_node(node)

    lines.append("}")
    return "\n".join(lines) + "\n"


async def _handle_options(app: CurriculumApp, args: str) -> None:
    pane = app.active_chat_pane
    parts = args.strip().split()
    use_editor = "-e" in parts
    is_global = "global" in parts

    target = app.options if is_global else pane.options

    if use_editor:
        # Editor mode: suspend TUI and open $EDITOR
        # Build a JSONC snapshot of current values
        jsonc_text = _build_jsonc_snapshot(target)

        editor = os.environ.get("EDITOR", "nano")

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonc", prefix="rhizome-options-", delete=False
        ) as tmp:
            tmp.write(jsonc_text)
            tmp_path = tmp.name

        try:
            with app.suspend():
                subprocess.run([editor, tmp_path])

            new_text = Path(tmp_path).read_text(encoding="utf-8")
            new_opts = parse_jsonc(new_text)

            spec_map = {s.resolved_name: s for s in Options.spec()}
            for key, val in new_opts.items():
                s = spec_map.get(key)
                if s is not None:
                    await target.set(s, val)

            await target.post_update()
            pane.append_message(
                ChatMessageData(role=Role.SYSTEM, content="Options updated.")
            )
        except Exception as exc:
            pane.append_message(
                ChatMessageData(role=Role.SYSTEM, content=f"Error applying options: {exc}")
            )
        finally:
            os.unlink(tmp_path)
        return

    # Inline widget mode
    area = pane.query_one("#message-area")
    editor_widget = OptionsEditor(target, id="options-editor")
    await area.mount(editor_widget)
    area.scroll_end(animate=False)
    editor_widget.focus()


async def _handle_explore(app: CurriculumApp, _args: str) -> None:
    pane = app.active_chat_pane
    # If a topic tree already exists, just focus it instead of creating a new one.
    existing = list(pane.query(TopicTree))
    if existing:
        tree = existing[-1]
        tree.query_one("#topic-tree-help").update(
            "Use arrow keys to navigate, enter to select a topic."
        )
        tree.focus()
    else:
        area = pane.query_one("#message-area")
        tree = TopicTree(id="topic-tree")
        await area.mount(tree)
        area.scroll_end(animate=False)
        tree.focus()
    pane.query_one("#chat-input").placeholder = (
        "Use Tab/Shift+Tab to navigate between widgets"
    )


async def _handle_help(app: CurriculumApp, args: str) -> None:
    """Show available commands, or details for a specific command."""
    if args:
        name = args.strip().lstrip("/")
        cmd = COMMANDS.get(name)
        if cmd is None:
            text = f"Unknown command: /{name}\nType /help to see available commands."
        else:
            text = f"/{cmd.name} — {cmd.description}"
    else:
        lines = ["**Available commands:**", ""]
        for name in sorted(COMMANDS):
            cmd = COMMANDS[name]
            lines.append(f"  /{cmd.name} — {cmd.description}")
        lines.append("")
        lines.append("Type /help <command> for details.")
        text = "\n".join(lines)

    app.active_chat_pane.append_message(ChatMessageData(role=Role.AGENT, content=text))


async def _handle_clear(app: CurriculumApp, _args: str) -> None:
    """Clear all visible chat messages from the message area."""
    pane = app.active_chat_pane
    area = pane.query_one("#message-area")
    await area.remove_children()
    pane.messages.clear()


async def _handle_rename(app: CurriculumApp, args: str) -> None:
    """Rename the active chat session tab."""
    from rhizome.tui.screens.chat import ChatTabPane # Avoid circular import

    new_name = args.strip()
    if not new_name:
        app.active_chat_pane.append_message(
            ChatMessageData(role=Role.SYSTEM, content="Usage: /rename <name>")
        )
        return

    tabs = app.screen.query_one("#tabs", TabbedContent)
    active_pane = tabs.active_pane
    if active_pane is not None and isinstance(active_pane, ChatTabPane):
        active_pane.full_name = new_name
        active_pane._update_tab_label()


async def _handle_new(app: CurriculumApp, _args: str) -> None:
    """Create a new chat session tab."""
    from rhizome.tui.screens.chat import ChatScreen # Avoid circular import

    screen = app.screen
    if isinstance(screen, ChatScreen):
        await screen._add_tab()


async def _handle_commit(app: CurriculumApp, _args: str) -> None:
    """Select learn-mode messages to commit as knowledge."""
    pane = app.active_chat_pane
    pane.enter_commit_mode()


async def _handle_logs(app: CurriculumApp, _args: str) -> None:
    """Open the logs tab."""
    from rhizome.tui.screens.chat import ChatScreen  # Avoid circular import

    screen = app.screen
    if isinstance(screen, ChatScreen):
        await screen._add_log_tab()


async def _handle_close(app: CurriculumApp, _args: str) -> None:
    """Close the current chat session tab."""
    from rhizome.tui.screens.chat import ChatScreen # Avoid circular import

    screen = app.screen
    if isinstance(screen, ChatScreen):
        await screen._close_active_tab()


# ---------------------------------------------------------------------------
# Command registry.
# /quit is intentionally absent — it is TUI-only and handled directly
# by the chat screen (the agent should never exit the app).
# ---------------------------------------------------------------------------

COMMANDS: dict[str, Command] = {
    "clear": Command("clear", "Clear chat messages", _handle_clear),
    "close": Command("close", "Close the current chat session tab", _handle_close),
    "commit": Command("commit", "Select learn-mode messages to commit as knowledge", _handle_commit),
    "explore": Command("explore", "Browse and select topics from the topic tree", _handle_explore),
    "help": Command("help", "Show available commands and usage", _handle_help),
    "idle": Command("idle", "Return to idle mode", _handle_idle),
    "learn": Command("learn", "Enter learning mode: set curriculum and topic context", _handle_learn),
    "logs": Command("logs", "Open the logs viewer tab", _handle_logs),
    "new": Command("new", "Open a new chat session tab", _handle_new),
    "rename": Command("rename", "Rename the current tab", _handle_rename),
    "review": Command("review", "Enter review mode: quizzes and practice", _handle_review),
    "options": Command("options", "Open settings and configuration", _handle_options),
    "quit": Command("quit", "Quit", None),
}
