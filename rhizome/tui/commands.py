"""Slash command parser and registry."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

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


async def _handle_learn(app: CurriculumApp, _args: str) -> None:
    from rhizome.tui.state import ChatEntry

    app.active_chat_pane.append_message(ChatEntry(role="system", content="/learn — context selection coming soon"))


async def _handle_review(app: CurriculumApp, _args: str) -> None:
    from rhizome.tui.state import ChatEntry

    app.active_chat_pane.append_message(ChatEntry(role="system", content="/review — review mode coming soon"))


async def _handle_options(app: CurriculumApp, _args: str) -> None:
    from rhizome.tui.state import ChatEntry

    app.active_chat_pane.append_message(ChatEntry(role="system", content="/options — settings coming soon"))


async def _handle_explore(app: CurriculumApp, _args: str) -> None:
    from rhizome.tui.widgets.chat_input import ChatInput
    from rhizome.tui.widgets.topic_tree import TopicTree

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
    pane.query_one("#chat-input", ChatInput).placeholder = (
        "Use Ctrl+Enter to exit the topic viewer"
    )


async def _handle_help(app: CurriculumApp, args: str) -> None:
    """Show available commands, or details for a specific command."""
    from rhizome.tui.state import ChatEntry

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

    app.active_chat_pane.append_message(ChatEntry(role="agent", content=text))


async def _handle_new(app: CurriculumApp, _args: str) -> None:
    """Create a new chat session tab."""
    from rhizome.tui.screens.chat import ChatScreen

    screen = app.screen
    if isinstance(screen, ChatScreen):
        await screen._add_tab()


async def _handle_close(app: CurriculumApp, _args: str) -> None:
    """Close the current chat session tab."""
    from rhizome.tui.screens.chat import ChatScreen

    screen = app.screen
    if isinstance(screen, ChatScreen):
        await screen._close_active_tab()


# ---------------------------------------------------------------------------
# Command registry.
# /quit is intentionally absent — it is TUI-only and handled directly
# by the chat screen (the agent should never exit the app).
# ---------------------------------------------------------------------------

COMMANDS: dict[str, Command] = {
    "close": Command("close", "Close the current chat session tab", _handle_close),
    "explore": Command("explore", "Browse and select topics from the topic tree", _handle_explore),
    "help": Command("help", "Show available commands and usage", _handle_help),
    "learn": Command("learn", "Enter learning mode: set curriculum and topic context", _handle_learn),
    "new": Command("new", "Open a new chat session tab", _handle_new),
    "review": Command("review", "Enter review mode: quizzes and practice", _handle_review),
    "options": Command("options", "Open settings and configuration", _handle_options),
    "quit": Command("quit", "Quit", None),
}
