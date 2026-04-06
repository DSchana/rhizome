"""Name-based resolution for topics and resources.

Accepts numeric IDs, plain names (partial match), or slash-separated
ancestor paths for disambiguation (e.g. ``"Linux/Filesystem/Types"``).

Resolution outcomes:
- Exactly one match → returns a single model instance.
- Zero matches → raises ``ValueError``.
- Multiple matches → returns a non-empty list of ambiguous candidates.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rhizome.db.models import Resource, Topic


# ------------------------------------------------------------------
# Result types
# ------------------------------------------------------------------

@dataclass
class AmbiguousTopic:
    """A candidate topic with its full human-readable path."""
    topic: Topic
    path: str  # e.g. "Linux > Filesystem > Core Concepts > Types"


@dataclass
class AmbiguousResource:
    """A candidate resource surfaced during ambiguous resolution."""
    resource: Resource


# ------------------------------------------------------------------
# Path helpers
# ------------------------------------------------------------------

async def get_topic_path(session: AsyncSession, topic: Topic) -> str:
    """Build the full ``>``-separated path from root to *topic*."""
    segments: list[str] = [topic.name]
    current = topic
    while current.parent_id is not None:
        current = await session.get(Topic, current.parent_id)
        if current is None:
            break
        segments.append(current.name)
    segments.reverse()
    return " > ".join(segments)


# ------------------------------------------------------------------
# Topic resolution
# ------------------------------------------------------------------

async def _matches_ancestor_segments(
    session: AsyncSession,
    topic: Topic,
    ancestor_segments: list[str],
) -> bool:
    """Walk up from *topic*.parent checking ancestor names match *ancestor_segments* right-to-left."""
    current = topic
    for seg in reversed(ancestor_segments):
        if current.parent_id is None:
            return False
        parent = await session.get(Topic, current.parent_id)
        if parent is None or seg.lower() not in parent.name.lower():
            return False
        current = parent
    return True


async def resolve_topic(
    session: AsyncSession,
    identifier: str,
) -> Topic | list[AmbiguousTopic]:
    """Resolve a topic by numeric ID, name, or slash-separated path.

    Returns
    -------
    Topic
        On an unambiguous match (including numeric ID).
    list[AmbiguousTopic]
        Non-empty list (length ≥ 2) if ambiguous.

    Raises
    ------
    ValueError
        If no matches are found.
    """
    identifier = identifier.strip()

    # Fast path: numeric ID
    if identifier.isdigit():
        topic = await session.get(Topic, int(identifier))
        if topic is None:
            raise ValueError(f"Topic {identifier} not found.")
        return topic

    # Split on "/" for path-based resolution
    segments = [s.strip() for s in identifier.split("/") if s.strip()]
    if not segments:
        raise ValueError("Empty topic identifier.")

    leaf_name = segments[-1]
    ancestor_segments = segments[:-1]

    # Find all topics whose name partially matches the leaf segment
    result = await session.execute(
        select(Topic).where(Topic.name.ilike(f"%{leaf_name}%"))
    )
    candidates = list(result.scalars().all())

    # Filter by ancestor path if segments were provided
    if ancestor_segments:
        surviving: list[Topic] = []
        for topic in candidates:
            if await _matches_ancestor_segments(session, topic, ancestor_segments):
                surviving.append(topic)
        candidates = surviving

    if len(candidates) == 0:
        raise ValueError(f"No topic matching '{identifier}' found.")
    if len(candidates) == 1:
        return candidates[0]

    # Build full paths for disambiguation display
    return [
        AmbiguousTopic(topic=t, path=await get_topic_path(session, t))
        for t in candidates
    ]


# ------------------------------------------------------------------
# Resource resolution
# ------------------------------------------------------------------

async def resolve_resource(
    session: AsyncSession,
    identifier: str,
) -> Resource | list[AmbiguousResource]:
    """Resolve a resource by numeric ID or partial name match.

    Returns
    -------
    Resource
        On an unambiguous match.
    list[AmbiguousResource]
        Non-empty list (length ≥ 2) if ambiguous.

    Raises
    ------
    ValueError
        If no matches are found.
    """
    identifier = identifier.strip()

    # Fast path: numeric ID
    if identifier.isdigit():
        resource = await session.get(Resource, int(identifier))
        if resource is None:
            raise ValueError(f"Resource {identifier} not found.")
        return resource

    if not identifier:
        raise ValueError("Empty resource identifier.")

    # Partial name match
    result = await session.execute(
        select(Resource).where(Resource.name.ilike(f"%{identifier}%"))
    )
    candidates = list(result.scalars().all())

    if len(candidates) == 0:
        raise ValueError(f"No resource matching '{identifier}' found.")
    if len(candidates) == 1:
        return candidates[0]

    return [AmbiguousResource(resource=r) for r in candidates]
