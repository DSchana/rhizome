"""Custom graph state schema for the root agent."""

from __future__ import annotations

from langchain.agents.middleware.types import AgentState

from typing import TypedDict

from rhizome.agent.tools.flashcard import FlashcardProposalState
from rhizome.agent.review_state import ReviewState


class CommitProposalEntry(TypedDict):
    """A single proposed knowledge entry, stored in agent state."""
    id: int
    title: str
    content: str
    entry_type: str
    topic_id: int


class CommitProposalState(TypedDict):
    """Consolidated state for the commit proposal workflow.

    Stored in ``RhizomeAgentState.commit_proposal_state``.
    """
    payload: list[dict]
    """Selected conversation messages for knowledge commit (``{"index", "content"}``)."""

    proposal: list[CommitProposalEntry]
    """Proposed knowledge entries awaiting user approval."""

    proposal_diff: str | None
    """Human-readable diff summary from the most recent user edit session.
    Written by ``present_commit_proposal`` on Edit; read by
    ``invoke_commit_subagent`` to inform the subagent of user changes."""


class RhizomeAgentState(AgentState):
    """Extended agent state for checkpoint/replay.

    All fields use default last-write-wins semantics.  Nullable fields
    (``review``, ``flashcard_proposal_state``, ``commit_proposal_state``)
    persist in the checkpoint until explicitly cleared by a tool via
    ``Command(update={...})``.  They are NOT reset to ``None`` in
    ``stream()``'s ``next_input``.
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

    flashcard_proposal_state: FlashcardProposalState | None
    """Consolidated flashcard proposal state: staged items.
    ``None`` when no proposal is active."""

    commit_proposal_state: CommitProposalState | None
    """Consolidated commit proposal state: payload, proposal entries, and
    diff summary.  ``None`` when no commit workflow is active."""