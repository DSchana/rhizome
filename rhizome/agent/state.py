"""Custom graph state schema for the root agent."""

from __future__ import annotations

from langchain.agents.middleware.types import AgentState

from typing import TypedDict

from rhizome.agent.flashcard_proposal_tools import FlashcardProposalItem
from rhizome.agent.review_state import ReviewState


class CommitProposalEntry(TypedDict):
    """A single proposed knowledge entry, stored in agent state."""
    title: str
    content: str
    entry_type: str
    topic_id: int


class RhizomeAgentState(AgentState):
    """Extended agent state for checkpoint/replay.

    All fields use default last-write-wins semantics.  Nullable fields
    (``review``, ``flashcard_proposal``, ``commit_payload``,
    ``commit_proposal``) persist in the checkpoint until explicitly
    cleared by a tool via ``Command(update={...})``.  They are NOT
    reset to ``None`` in ``stream()``'s ``next_input``.
    """

    mode: str
    """Active session mode: ``"idle"``, ``"learn"``, or ``"review"``.

    Set via ``next_input`` at the start of each ``stream()`` call from
    ``ChatPane.session_mode`` (the authoritative source of truth).
    Updated mid-stream through two paths:

    - **User-initiated** (shift+tab, slash commands): queued via
      ``AgentModeMiddleware.set_pending_user_mode()`` and applied in
      ``abefore_model``, which updates this field and injects a
      ``[System]`` notification so the agent is aware.
    - **Agent-initiated**: the ``set_mode`` tool returns
      ``Command(update={"mode": ...})`` directly.

    Determines which system prompt and tool allowlist are active, via
    ``AgentModeMiddleware.awrap_model_call``.
    """

    review: ReviewState | None
    """Review session state machine; ``None`` when no review is active."""

    flashcard_proposal: list[FlashcardProposalItem] | None
    """Staged flashcard proposal awaiting user approval."""

    commit_payload: list[dict] | None
    """Selected conversation messages for knowledge commit (``{"index", "content"}``)."""

    commit_proposal: list[CommitProposalEntry] | None
    """Proposed knowledge entries awaiting user approval."""