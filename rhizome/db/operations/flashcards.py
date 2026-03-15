"""CRUD operations for flashcards."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rhizome.db import (
    Flashcard,
    FlashcardEntry,
)
from rhizome.logs import get_logger

_logger = get_logger("tools.flashcards")


async def create_flashcard(
    session: AsyncSession,
    *,
    topic_id: int,
    question_text: str,
    answer_text: str,
    entry_ids: list[int],
    testing_notes: str | None = None,
    session_id: int | None = None,
) -> Flashcard:
    """Create a flashcard with linked entries."""
    flashcard = Flashcard(
        topic_id=topic_id,
        question_text=question_text,
        answer_text=answer_text,
        testing_notes=testing_notes,
        session_id=session_id,
    )
    session.add(flashcard)
    await session.flush()

    for eid in entry_ids:
        session.add(FlashcardEntry(flashcard_id=flashcard.id, entry_id=eid))
    await session.flush()

    _logger.info(
        "Flashcard created: id=%d, topic=%d, entries=%d, session=%s",
        flashcard.id, topic_id, len(entry_ids), session_id,
    )
    return flashcard


async def list_flashcards_by_entries(
    session: AsyncSession,
    entry_ids: list[int],
) -> list[Flashcard]:
    """Return flashcards linked to any of the given entry IDs.

    Excludes flashcards belonging to ephemeral sessions.
    """
    from rhizome.db import ReviewSession

    result = await session.execute(
        select(Flashcard)
        .options(
            selectinload(Flashcard.flashcard_entries),
            selectinload(Flashcard.session),
        )
        .join(FlashcardEntry, Flashcard.id == FlashcardEntry.flashcard_id)
        .outerjoin(ReviewSession, Flashcard.session_id == ReviewSession.id)
        .where(
            FlashcardEntry.entry_id.in_(entry_ids),
            # Exclude flashcards from ephemeral sessions (allow session_id=NULL or non-ephemeral)
            (ReviewSession.id.is_(None)) | (ReviewSession.ephemeral == False),  # noqa: E712
        )
        .distinct()
    )
    return list(result.scalars().unique().all())


async def get_flashcards_by_ids(
    session: AsyncSession,
    flashcard_ids: list[int],
) -> list[Flashcard]:
    """Return flashcards by their IDs, with flashcard_entries eagerly loaded."""
    from sqlalchemy.orm import selectinload

    result = await session.execute(
        select(Flashcard)
        .options(selectinload(Flashcard.flashcard_entries))
        .where(Flashcard.id.in_(flashcard_ids))
    )
    return list(result.scalars().all())


async def list_flashcards_by_topic(
    session: AsyncSession,
    topic_id: int,
) -> list[Flashcard]:
    """Return flashcards for a topic, with entries and session eagerly loaded.

    Includes ephemeral flashcards (caller can check ``flashcard.session.ephemeral``).
    """
    result = await session.execute(
        select(Flashcard)
        .options(
            selectinload(Flashcard.flashcard_entries),
            selectinload(Flashcard.session),
        )
        .where(Flashcard.topic_id == topic_id)
    )
    return list(result.scalars().all())


async def count_flashcards_by_topic(
    session: AsyncSession,
    topic_id: int,
) -> int:
    """Return the number of flashcards for a topic (including ephemeral)."""
    result = await session.execute(
        select(func.count())
        .select_from(Flashcard)
        .where(Flashcard.topic_id == topic_id)
    )
    return result.scalar_one()


async def get_flashcard_entry_ids(
    session: AsyncSession,
    flashcard_id: int,
) -> list[int]:
    """Return the entry IDs linked to a flashcard."""
    result = await session.execute(
        select(FlashcardEntry.entry_id)
        .where(FlashcardEntry.flashcard_id == flashcard_id)
    )
    return list(result.scalars().all())
