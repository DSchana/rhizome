"""CRUD operations for Curriculum objects."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from curriculum_app.db import Curriculum


async def create_curriculum(
    session: AsyncSession,
    *,
    name: str,
    description: str | None = None,
) -> Curriculum:
    """Create a new curriculum and flush it to obtain its id."""
    curriculum = Curriculum(name=name, description=description)
    session.add(curriculum)
    await session.flush()
    return curriculum


async def get_curriculum(
    session: AsyncSession,
    curriculum_id: int,
) -> Curriculum | None:
    """Return a curriculum by id, or None if not found."""
    return await session.get(Curriculum, curriculum_id)


async def list_curricula(session: AsyncSession) -> list[Curriculum]:
    """Return all curricula."""
    result = await session.execute(select(Curriculum))
    return list(result.scalars().all())


async def update_curriculum(
    session: AsyncSession,
    curriculum_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Curriculum:
    """Update a curriculum's fields. Only provided (non-None) fields are changed."""
    curriculum = await session.get(Curriculum, curriculum_id)
    if curriculum is None:
        raise ValueError(f"Curriculum {curriculum_id} not found")
    if name is not None:
        curriculum.name = name
    if description is not None:
        curriculum.description = description
    await session.flush()
    return curriculum


async def delete_curriculum(
    session: AsyncSession,
    curriculum_id: int,
) -> None:
    """Delete a curriculum. Cascades to topics and entries via ORM relationships."""
    curriculum = await session.get(Curriculum, curriculum_id)
    if curriculum is None:
        raise ValueError(f"Curriculum {curriculum_id} not found")
    await session.delete(curriculum)
    await session.flush()
