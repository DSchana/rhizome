"""Runtime context passed to every tool invocation."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class AgentContext:
    session: AsyncSession
