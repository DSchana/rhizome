"""CRUD + search operations for KnowledgeEntry objects."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rhizome.db import CurriculumTopic, KnowledgeEntry, Topic
from rhizome.db.models import EntryType


async def create_entry(
    session: AsyncSession,
    *,
    topic_id: int,
    title: str,
    content: str,
    entry_type: EntryType | None = None,
    additional_notes: str = "",
    difficulty: int | None = None,
    speed_testable: bool = False,
) -> KnowledgeEntry:
    """Create a new knowledge entry under a topic."""
    entry = KnowledgeEntry(
        topic_id=topic_id,
        title=title,
        content=content,
        entry_type=entry_type,
        additional_notes=additional_notes,
        difficulty=difficulty,
        speed_testable=speed_testable,
    )
    session.add(entry)
    await session.flush()
    return entry


async def get_entry(
    session: AsyncSession,
    entry_id: int,
) -> KnowledgeEntry | None:
    """Return an entry by id, or None if not found."""
    return await session.get(KnowledgeEntry, entry_id)


async def list_entries(
    session: AsyncSession,
    topic_id: int,
) -> list[KnowledgeEntry]:
    """Return all entries for a topic, ordered by created_at."""
    result = await session.execute(
        select(KnowledgeEntry)
        .where(KnowledgeEntry.topic_id == topic_id)
        .order_by(KnowledgeEntry.created_at)
    )
    return list(result.scalars().all())


async def update_entry(
    session: AsyncSession,
    entry_id: int,
    *,
    title: str | None = None,
    content: str | None = None,
    entry_type: EntryType | None = None,
    additional_notes: str | None = None,
    difficulty: int | None = None,
    speed_testable: bool | None = None,
) -> KnowledgeEntry:
    """Update an entry's fields. Only provided (non-None) fields are changed."""
    entry = await session.get(KnowledgeEntry, entry_id)
    if entry is None:
        raise ValueError(f"KnowledgeEntry {entry_id} not found")
    if title is not None:
        entry.title = title
    if content is not None:
        entry.content = content
    if entry_type is not None:
        entry.entry_type = entry_type
    if additional_notes is not None:
        entry.additional_notes = additional_notes
    if difficulty is not None:
        entry.difficulty = difficulty
    if speed_testable is not None:
        entry.speed_testable = speed_testable
    await session.flush()
    return entry


async def delete_entry(
    session: AsyncSession,
    entry_id: int,
) -> None:
    """Delete a knowledge entry."""
    entry = await session.get(KnowledgeEntry, entry_id)
    if entry is None:
        raise ValueError(f"KnowledgeEntry {entry_id} not found")
    await session.delete(entry)
    await session.flush()


async def search_entries(
    session: AsyncSession,
    query: str,
    *,
    topic_id: int | None = None,
    curriculum_id: int | None = None,
) -> list[KnowledgeEntry]:
    """Search entries by LIKE on title + content.

    Optionally scope to a specific topic or curriculum.
    """
    pattern = f"%{query}%"
    stmt = select(KnowledgeEntry).where(
        (KnowledgeEntry.title.ilike(pattern)) | (KnowledgeEntry.content.ilike(pattern))
    )
    if topic_id is not None:
        stmt = stmt.where(KnowledgeEntry.topic_id == topic_id)
    if curriculum_id is not None:
        stmt = (
            stmt
            .join(Topic, KnowledgeEntry.topic_id == Topic.id)
            .join(CurriculumTopic, Topic.id == CurriculumTopic.topic_id)
            .where(CurriculumTopic.curriculum_id == curriculum_id)
        )
    result = await session.execute(stmt)
    return list(result.scalars().all())
