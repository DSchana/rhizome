"""Runtime context passed to every tool invocation."""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class AgentContext:
    session: AsyncSession
    app: Any = field(default=None)
    """Optional ``CurriculumApp`` instance, available when invoked from the TUI."""
    chat_pane: Any = field(default=None)
    """Optional ``ChatPane`` instance that owns the agent session."""
