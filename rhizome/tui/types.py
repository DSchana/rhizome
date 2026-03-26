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


class DataChanged(Message):
    """Posted when a DB commit occurs, signalling widgets to refresh stale data."""


@dataclass
class ChatMessageData:
    """A single message in the conversation history."""

    role: Role
    content: str
    mode: Mode = Mode.IDLE
    rich: bool = False
