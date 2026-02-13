"""Mutable application state shared across screens and widgets."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from curriculum_app.db import Curriculum, Topic


class Mode(Enum):
    """Top-level application mode."""

    IDLE = "idle"
    LEARN = "learn"
    REVIEW = "review"


@dataclass
class ChatMessage:
    """A single message in the conversation history."""

    role: Literal["user", "agent"]
    content: str


@dataclass
class AppState:
    """Central mutable state for the TUI.

    Screens and widgets read and mutate this object to coordinate
    context, mode, and conversation history.
    """

    mode: Mode = Mode.IDLE
    active_curriculum: Curriculum | None = None
    active_topic: Topic | None = None
    chat_history: list[ChatMessage] = field(default_factory=list)

    @property
    def context_label(self) -> str:
        """Human-readable label for the active curriculum > topic, or empty."""
        if self.active_curriculum and self.active_topic:
            return f"{self.active_curriculum.name} > {self.active_topic.name}"
        if self.active_curriculum:
            return self.active_curriculum.name
        return ""
