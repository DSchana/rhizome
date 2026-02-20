"""Shared types used across the TUI."""

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class Mode(Enum):
    """Top-level application mode."""

    IDLE = "idle"
    LEARN = "learn"
    REVIEW = "review"


@dataclass
class ChatEntry:
    """A single message in the conversation history."""

    role: Literal["user", "agent", "system"]
    content: str
