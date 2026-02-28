"""Tag CRUD and entry tagging/untagging operations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rhizome.db import CurriculumTopic, KnowledgeEntry, KnowledgeEntryTag, Tag, Topic
from rhizome.logs import get_logger

_logger = get_logger("tools.tags")


async def create_tag(
    session: AsyncSession,
    *,
    name: str,
) -> Tag:
    """Create a tag. The name is normalized to lowercase."""
    tag = Tag(name=name.lower())
    session.add(tag)
    await session.flush()
    _logger.debug("Tag created: id=%d, name=%r", tag.id, tag.name)
    return tag


async def list_tags(session: AsyncSession) -> list[Tag]:
    """Return all tags."""
    result = await session.execute(select(Tag))
    return list(result.scalars().all())


async def tag_entry(
    session: AsyncSession,
    *,
    entry_id: int,
    tag_name: str,
) -> None:
    """Tag an entry. Creates the tag if it doesn't already exist."""
    tag_name = tag_name.lower()

    # Get or create the tag.
    result = await session.execute(select(Tag).where(Tag.name == tag_name))
    tag = result.scalar_one_or_none()
    if tag is None:
        tag = Tag(name=tag_name)
        session.add(tag)
        await session.flush()

    # Check if the association already exists.
    existing = await session.get(KnowledgeEntryTag, (entry_id, tag.id))
    if existing is None:
        session.add(KnowledgeEntryTag(knowledge_entry_id=entry_id, tag_id=tag.id))
        await session.flush()
        _logger.debug("Entry %d tagged with %r", entry_id, tag_name)


async def untag_entry(
    session: AsyncSession,
    *,
    entry_id: int,
    tag_name: str,
) -> None:
    """Remove a tag from an entry. No-op if the tag or association doesn't exist."""
    tag_name = tag_name.lower()

    result = await session.execute(select(Tag).where(Tag.name == tag_name))
    tag = result.scalar_one_or_none()
    if tag is None:
        return

    assoc = await session.get(KnowledgeEntryTag, (entry_id, tag.id))
    if assoc is not None:
        await session.delete(assoc)
        await session.flush()


async def get_entries_by_tag(
    session: AsyncSession,
    tag_name: str,
    *,
    curriculum_id: int | None = None,
) -> list[KnowledgeEntry]:
    """Return all entries with a given tag. Optionally scoped to a curriculum."""
    tag_name = tag_name.lower()

    stmt = (
        select(KnowledgeEntry)
        .join(KnowledgeEntryTag, KnowledgeEntry.id == KnowledgeEntryTag.knowledge_entry_id)
        .join(Tag, KnowledgeEntryTag.tag_id == Tag.id)
        .where(Tag.name == tag_name)
    )
    if curriculum_id is not None:
        stmt = (
            stmt
            .join(Topic, KnowledgeEntry.topic_id == Topic.id)
            .join(CurriculumTopic, Topic.id == CurriculumTopic.topic_id)
            .where(CurriculumTopic.curriculum_id == curriculum_id)
        )
    result = await session.execute(stmt)
    return list(result.scalars().all())
