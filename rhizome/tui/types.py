"""Shared types used across the TUI."""

from dataclasses import dataclass
from enum import Enum

from textual.message import Message


class Mode(Enum):
    """Top-level application mode."""

    IDLE = "idle"
    LEARN = "learn"
    REVIEW = "review"


class Role(Enum):
    """Chat message role."""

    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"
    ERROR = "error"


class UserFeedback(Message):
    """Screen-level message requesting that a tab pane display feedback to the user."""

    def __init__(self, text: str, severity: str = "information") -> None:
        super().__init__()
        self.text = text
        self.severity = severity


class DatabaseCommitted(Message):
    """Posted when a DB commit occurs, signalling widgets to refresh stale data.

    ``changed_tables`` contains the set of table names that had inserts,
    updates, or deletes in the committed transaction.  Consumers can inspect
    this to skip unnecessary refreshes (e.g. the explorer viewer doesn't
    need to reload when only ``topic_resource`` rows changed).
    """

    def __init__(self, changed_tables: frozenset[str] | None = None) -> None:
        super().__init__()
        self.changed_tables: frozenset[str] = changed_tables or frozenset()


@dataclass
class ChatMessageData:
    """A single message in the conversation history."""

    role: Role
    content: str
    mode: Mode = Mode.IDLE
    rich: bool = False
