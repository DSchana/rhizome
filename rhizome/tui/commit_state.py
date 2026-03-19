"""Commit-mode state and messages, shared by the TUI and agent layers."""

from __future__ import annotations

from dataclasses import dataclass, field

from textual.message import Message


@dataclass
class CommitState:
    """Encapsulates commit-mode UI state for the ChatPane."""

    active: bool = False
    selectable: list = field(default_factory=list)  # list[ChatMessage] at runtime
    selected: set[int] = field(default_factory=set)
    cursor: int = 0


class CommitApproved(Message):
    """Posted when the commit subagent's proposal is accepted and written to DB."""

    def __init__(self, count: int) -> None:
        super().__init__()
        self.count = count


class CommitCancelled(Message):
    """Posted when the user cancels or rejects a commit proposal."""

    pass
