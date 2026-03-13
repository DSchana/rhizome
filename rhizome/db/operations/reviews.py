"""CRUD operations for review sessions and interactions."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rhizome.db import (
    ReviewInteraction,
    ReviewInteractionEntry,
    ReviewSession,
    ReviewSessionEntry,
    ReviewSessionTopic,
)
from rhizome.logs import get_logger

_logger = get_logger("tools.reviews")


async def create_review_session(
    session: AsyncSession,
    *,
    topic_ids: list[int],
    entry_ids: list[int],
) -> ReviewSession:
    """Create a review session with the given topics and entries."""
    review = ReviewSession()
    session.add(review)
    await session.flush()

    for tid in topic_ids:
        session.add(ReviewSessionTopic(session_id=review.id, topic_id=tid))
    for eid in entry_ids:
        session.add(ReviewSessionEntry(session_id=review.id, entry_id=eid))
    await session.flush()

    _logger.info(
        "ReviewSession created: id=%d, topics=%d, entries=%d",
        review.id, len(topic_ids), len(entry_ids),
    )
    return review


async def get_review_session(
    session: AsyncSession,
    review_session_id: int,
) -> ReviewSession | None:
    """Return a review session by id, or None if not found."""
    return await session.get(ReviewSession, review_session_id)


async def complete_review_session(
    session: AsyncSession,
    review_session_id: int,
) -> ReviewSession:
    """Mark a review session as completed."""
    review = await session.get(ReviewSession, review_session_id)
    if review is None:
        raise ValueError(f"ReviewSession {review_session_id} not found")
    review.completed_at = datetime.now(timezone.utc)
    await session.flush()
    _logger.info("ReviewSession completed: id=%d", review.id)
    return review


async def add_review_interaction(
    session: AsyncSession,
    *,
    session_id: int,
    question_text: str,
    user_response: str,
    entry_ids: list[int],
    feedback: str | None = None,
    score: int | None = None,
    position: int,
) -> ReviewInteraction:
    """Add an interaction to a review session."""
    interaction = ReviewInteraction(
        session_id=session_id,
        question_text=question_text,
        user_response=user_response,
        feedback=feedback,
        score=score,
        position=position,
    )
    session.add(interaction)
    await session.flush()

    for eid in entry_ids:
        session.add(ReviewInteractionEntry(interaction_id=interaction.id, entry_id=eid))
    await session.flush()

    _logger.info(
        "ReviewInteraction created: id=%d, session=%d, pos=%d, entries=%d",
        interaction.id, session_id, position, len(entry_ids),
    )
    return interaction


async def list_review_interactions(
    session: AsyncSession,
    review_session_id: int,
) -> list[ReviewInteraction]:
    """Return all interactions for a review session, ordered by position."""
    result = await session.execute(
        select(ReviewInteraction)
        .where(ReviewInteraction.session_id == review_session_id)
        .order_by(ReviewInteraction.position)
    )
    return list(result.scalars().all())


async def get_review_session_entries(
    session: AsyncSession,
    review_session_id: int,
) -> list[int]:
    """Return the entry IDs in a review session's pool."""
    result = await session.execute(
        select(ReviewSessionEntry.entry_id)
        .where(ReviewSessionEntry.session_id == review_session_id)
    )
    return list(result.scalars().all())
