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
    ERROR = "error"


@dataclass
class TokenUsageData:
    """Tracks token consumption and context window limits."""

    total_tokens: int = 0
    max_tokens: int | None = None  # None means we couldn't determine the limit
    overhead_tokens: int | None = None  # None = unknown, skip (+N) display

    @property
    def usage_percent(self) -> float | None:
        if self.max_tokens is None or self.max_tokens == 0:
            return None
        return (self.total_tokens / self.max_tokens) * 100


@dataclass
class ChatMessageData:
    """A single message in the conversation history."""

    role: Role
    content: str
    mode: Mode = Mode.IDLE
