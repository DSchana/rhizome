"""Slash command parser and registry."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from curriculum_app.tui.state import AppState


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
    handler: Callable[[AppState, str], Awaitable[str]] | None


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

async def _handle_learn(_state: AppState, _args: str) -> str:
    return "/learn — context selection coming soon"


async def _handle_review(_state: AppState, _args: str) -> str:
    return "/review — review mode coming soon"


async def _handle_options(_state: AppState, _args: str) -> str:
    return "/options — settings coming soon"


# ---------------------------------------------------------------------------
# Command registry.
# /quit is intentionally absent — it is TUI-only and handled directly
# by the chat screen (the agent should never exit the app).
# ---------------------------------------------------------------------------

COMMANDS: dict[str, Command] = {
    "learn": Command("learn", "Enter learning mode: set curriculum and topic context", _handle_learn),
    "review": Command("review", "Enter review mode: quizzes and practice", _handle_review),
    "options": Command("options", "Open settings and configuration", _handle_options),
    "quit": Command("quit", "Quit", None),
}
