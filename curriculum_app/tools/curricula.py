"""CRUD operations for Curriculum objects and curriculum-topic membership."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from curriculum_app.db import Curriculum, CurriculumTopic, Topic


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
    """Delete a curriculum. Removes junction rows but not the topics themselves."""
    curriculum = await session.get(Curriculum, curriculum_id)
    if curriculum is None:
        raise ValueError(f"Curriculum {curriculum_id} not found")
    await session.delete(curriculum)
    await session.flush()


async def add_topic_to_curriculum(
    session: AsyncSession,
    *,
    curriculum_id: int,
    topic_id: int,
    position: int,
) -> CurriculumTopic:
    """Add a topic to a curriculum at the given position."""
    curriculum = await session.get(Curriculum, curriculum_id)
    if curriculum is None:
        raise ValueError(f"Curriculum {curriculum_id} not found")
    topic = await session.get(Topic, topic_id)
    if topic is None:
        raise ValueError(f"Topic {topic_id} not found")
    ct = CurriculumTopic(
        curriculum_id=curriculum_id, topic_id=topic_id, position=position
    )
    session.add(ct)
    await session.flush()
    return ct


async def remove_topic_from_curriculum(
    session: AsyncSession,
    *,
    curriculum_id: int,
    topic_id: int,
) -> None:
    """Remove a topic from a curriculum. Raises ValueError if not found."""
    ct = await session.get(CurriculumTopic, (curriculum_id, topic_id))
    if ct is None:
        raise ValueError(
            f"Topic {topic_id} is not in curriculum {curriculum_id}"
        )
    await session.delete(ct)
    await session.flush()


async def reorder_topic_in_curriculum(
    session: AsyncSession,
    *,
    curriculum_id: int,
    topic_id: int,
    new_position: int,
) -> CurriculumTopic:
    """Update the position of a topic within a curriculum."""
    ct = await session.get(CurriculumTopic, (curriculum_id, topic_id))
    if ct is None:
        raise ValueError(
            f"Topic {topic_id} is not in curriculum {curriculum_id}"
        )
    ct.position = new_position
    await session.flush()
    return ct


async def list_topics_in_curriculum(
    session: AsyncSession,
    curriculum_id: int,
) -> list[Topic]:
    """Return all topics for a curriculum, ordered by position."""
    result = await session.execute(
        select(Topic)
        .join(CurriculumTopic, Topic.id == CurriculumTopic.topic_id)
        .where(CurriculumTopic.curriculum_id == curriculum_id)
        .order_by(CurriculumTopic.position)
    )
    return list(result.scalars().all())
