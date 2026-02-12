"""CRUD operations for Topic objects."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from curriculum_app.db import Topic


async def create_topic(
    session: AsyncSession,
    *,
    curriculum_id: int,
    name: str,
    description: str | None = None,
) -> Topic:
    """Create a new topic under a curriculum."""
    topic = Topic(curriculum_id=curriculum_id, name=name, description=description)
    session.add(topic)
    await session.flush()
    return topic


async def get_topic(
    session: AsyncSession,
    topic_id: int,
) -> Topic | None:
    """Return a topic by id, or None if not found."""
    return await session.get(Topic, topic_id)


async def list_topics(
    session: AsyncSession,
    curriculum_id: int,
) -> list[Topic]:
    """Return all topics for a given curriculum."""
    result = await session.execute(
        select(Topic).where(Topic.curriculum_id == curriculum_id)
    )
    return list(result.scalars().all())


async def update_topic(
    session: AsyncSession,
    topic_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Topic:
    """Update a topic's fields. Only provided (non-None) fields are changed."""
    topic = await session.get(Topic, topic_id)
    if topic is None:
        raise ValueError(f"Topic {topic_id} not found")
    if name is not None:
        topic.name = name
    if description is not None:
        topic.description = description
    await session.flush()
    return topic


async def delete_topic(
    session: AsyncSession,
    topic_id: int,
) -> None:
    """Delete a topic. Cascades to entries via ORM relationship."""
    topic = await session.get(Topic, topic_id)
    if topic is None:
        raise ValueError(f"Topic {topic_id} not found")
    await session.delete(topic)
    await session.flush()
