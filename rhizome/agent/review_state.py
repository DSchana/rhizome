"""ReviewState — typed state for the review session state machine.

This state is stored in ``RhizomeAgentState.review`` and tracks the
active review session's phase, scope, configuration, flashcard queue,
and entry coverage.  It is ``None`` when no review session is active.
"""

from __future__ import annotations

from typing import TypedDict


class ReviewScope(TypedDict):
    topic_ids: list[int]
    entry_ids: list[int]


class ReviewConfig(TypedDict):
    style: str                      # "flashcard" | "conversation" | "mixed"
    critique_timing: str            # "during" | "after"
    question_source: str            # "existing" | "generated" | "both"
    ephemeral: bool
    user_instructions: str | None


class ReviewState(TypedDict):
    phase: str                      # "scoping" | "configuring" | "planning" | "reviewing" | "summarizing"
    session_id: int                 # Always set — ephemeral sessions still get a DB record
    scope: ReviewScope | None
    config: ReviewConfig | None
    flashcard_queue: list[int]      # Flashcard DB IDs to present, popped as used
    entry_coverage: dict[int, int]  # entry_id → touch count, incremented by record_review_interaction
    interaction_count: int
    discussion_plan: str | None
