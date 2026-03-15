"""CRUD operations for review sessions and interactions."""

from datetime import datetime, timezone

from sqlalchemy import func, select
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
    flashcard_id: int | None = None,
) -> ReviewInteraction:
    """Add an interaction to a review session."""
    interaction = ReviewInteraction(
        session_id=session_id,
        question_text=question_text,
        user_response=user_response,
        feedback=feedback,
        score=score,
        position=position,
        flashcard_id=flashcard_id,
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


async def get_sessions_by_topics(
    session: AsyncSession,
    topic_ids: list[int],
    limit: int = 5,
) -> list[ReviewSession]:
    """Return recent non-ephemeral sessions overlapping the given topic IDs.

    Results are ranked by IoU (intersection-over-union) of topic_ids,
    then by recency. Limited to ``limit`` results.
    """
    if not topic_ids:
        return []

    # Get all non-ephemeral sessions that share at least one topic
    topic_set = set(topic_ids)
    result = await session.execute(
        select(ReviewSession)
        .join(ReviewSessionTopic, ReviewSession.id == ReviewSessionTopic.session_id)
        .where(
            ReviewSessionTopic.topic_id.in_(topic_ids),
            ReviewSession.ephemeral == False,  # noqa: E712
        )
        .distinct()
        .order_by(ReviewSession.created_at.desc())
    )
    sessions = list(result.scalars().all())

    # Compute IoU for ranking
    ranked: list[tuple[float, ReviewSession]] = []
    for rs in sessions:
        # Load session's topic IDs
        tid_result = await session.execute(
            select(ReviewSessionTopic.topic_id)
            .where(ReviewSessionTopic.session_id == rs.id)
        )
        session_topic_ids = set(tid_result.scalars().all())
        intersection = len(topic_set & session_topic_ids)
        union = len(topic_set | session_topic_ids)
        iou = intersection / union if union > 0 else 0.0
        ranked.append((iou, rs))

    # Sort by IoU descending, then recency (already ordered by created_at desc)
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [rs for _, rs in ranked[:limit]]


async def update_session_ephemeral(
    session: AsyncSession,
    review_session_id: int,
    ephemeral: bool,
) -> None:
    """Set the ephemeral flag on a review session."""
    review = await session.get(ReviewSession, review_session_id)
    if review is None:
        raise ValueError(f"ReviewSession {review_session_id} not found")
    review.ephemeral = ephemeral
    await session.flush()


async def update_session_instructions(
    session: AsyncSession,
    review_session_id: int,
    instructions: str | None,
) -> None:
    """Write user_instructions to a review session."""
    review = await session.get(ReviewSession, review_session_id)
    if review is None:
        raise ValueError(f"ReviewSession {review_session_id} not found")
    review.user_instructions = instructions
    await session.flush()


async def update_session_summary(
    session: AsyncSession,
    review_session_id: int,
    summary: str,
) -> None:
    """Write final_summary to a review session."""
    review = await session.get(ReviewSession, review_session_id)
    if review is None:
        raise ValueError(f"ReviewSession {review_session_id} not found")
    review.final_summary = summary
    await session.flush()


async def get_interaction_stats(
    session: AsyncSession,
    review_session_id: int,
) -> dict:
    """Compute aggregate stats from a session's review interactions.

    Returns a dict with:
    - ``total``: total interaction count
    - ``scored``: number with a score
    - ``average_score``: mean score (or None if no scored interactions)
    - ``per_entry``: dict[entry_id, {"count": int, "total_score": int, "scored": int}]
    """
    interactions = await list_review_interactions(session, review_session_id)

    total = len(interactions)
    scored = 0
    score_sum = 0
    per_entry: dict[int, dict] = {}

    for ix in interactions:
        has_score = ix.score is not None
        if has_score:
            scored += 1
            score_sum += ix.score

        # Load entry IDs for this interaction
        entry_result = await session.execute(
            select(ReviewInteractionEntry.entry_id)
            .where(ReviewInteractionEntry.interaction_id == ix.id)
        )
        entry_ids = list(entry_result.scalars().all())

        for eid in entry_ids:
            if eid not in per_entry:
                per_entry[eid] = {"count": 0, "total_score": 0, "scored": 0}
            per_entry[eid]["count"] += 1
            if has_score:
                per_entry[eid]["scored"] += 1
                per_entry[eid]["total_score"] += ix.score

    return {
        "total": total,
        "scored": scored,
        "average_score": round(score_sum / scored, 2) if scored > 0 else None,
        "per_entry": per_entry,
    }
