"""Slash command parser and registry."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from curriculum_app.tui.app import CurriculumApp


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
    from curriculum_app.tui.screens.chat import ChatScreen
    from curriculum_app.tui.state import ChatMessage

    chat = app.query_one(ChatScreen)
    chat.append_message(ChatMessage(role="agent", content="/learn — context selection coming soon"))


async def _handle_review(app: CurriculumApp, _args: str) -> None:
    from curriculum_app.tui.screens.chat import ChatScreen
    from curriculum_app.tui.state import ChatMessage

    chat = app.query_one(ChatScreen)
    chat.append_message(ChatMessage(role="agent", content="/review — review mode coming soon"))


async def _handle_options(app: CurriculumApp, _args: str) -> None:
    from curriculum_app.tui.screens.chat import ChatScreen
    from curriculum_app.tui.state import ChatMessage

    chat = app.query_one(ChatScreen)
    chat.append_message(ChatMessage(role="agent", content="/options — settings coming soon"))


async def _handle_help(app: CurriculumApp, args: str) -> None:
    """Show available commands, or details for a specific command."""
    from curriculum_app.tui.screens.chat import ChatScreen
    from curriculum_app.tui.state import ChatMessage

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

    chat = app.query_one(ChatScreen)
    chat.append_message(ChatMessage(role="agent", content=text))


# ---------------------------------------------------------------------------
# Command registry.
# /quit is intentionally absent — it is TUI-only and handled directly
# by the chat screen (the agent should never exit the app).
# ---------------------------------------------------------------------------

COMMANDS: dict[str, Command] = {
    "help": Command("help", "Show available commands and usage", _handle_help),
    "learn": Command("learn", "Enter learning mode: set curriculum and topic context", _handle_learn),
    "review": Command("review", "Enter review mode: quizzes and practice", _handle_review),
    "options": Command("options", "Open settings and configuration", _handle_options),
    "quit": Command("quit", "Quit", None),
}
