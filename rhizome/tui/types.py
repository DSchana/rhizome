"""Shared types used across the TUI."""

from dataclasses import dataclass
from enum import Enum


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


@dataclass
class ChatMessageData:
    """A single message in the conversation history."""

    role: Role
    content: str
    mode: Mode = Mode.IDLE
