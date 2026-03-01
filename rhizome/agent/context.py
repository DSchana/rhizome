"""Runtime context passed to every tool invocation."""

import asyncio
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
    session_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    """Mutex guarding ``session`` against concurrent tool execution.

    LangGraph's ``ToolNode`` may dispatch multiple tool calls via
    ``asyncio.gather``.  SQLAlchemy's ``AsyncSession`` is not safe for
    concurrent use, so every tool should ``async with ctx.session_lock:``
    around its session operations.
    """
