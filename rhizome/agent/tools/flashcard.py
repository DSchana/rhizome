"""Flashcard proposal tools — stage, present, and accept flashcard proposals.

These tools are mode-independent: they can be used during learn mode
(to create flashcards from a learning conversation) or during review mode
(to propose flashcards as part of a review session).  Proposal state is
stored in ``RhizomeAgentState.flashcard_proposal``, separate from
``ReviewState``.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langchain.tools import tool
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from rhizome.agent.tools.visibility import ToolVisibility, tool_visibility
from rhizome.db.operations import create_flashcard
from rhizome.logs import get_logger

_logger = get_logger("agent.flashcard_proposal_tools")


# ---------------------------------------------------------------------------
# State types
# ---------------------------------------------------------------------------

class FlashcardProposalItem(TypedDict):
    topic_id: int
    question_text: str
    answer_text: str
    entry_ids: list[int]
    testing_notes: str | None


class FlashcardInput(BaseModel):
    """Input schema for creating a single flashcard."""

    topic_id: int = Field(description="Topic ID the flashcard belongs to")
    question_text: str = Field(description="The question text")
    answer_text: str = Field(description="The expected answer text")
    entry_ids: list[int] = Field(description="Knowledge entry IDs this flashcard tests")
    testing_notes: str | None = Field(default=None, description="Notes on how to assess responses")


# ---------------------------------------------------------------------------
# Tool builder
# ---------------------------------------------------------------------------

def build_flashcard_proposal_tools(session_factory) -> dict[str, Any]:
    """Build flashcard proposal tools with session_factory closed over."""

    @tool("create_flashcard_proposal", description=(
        "Stage flashcards for user review without writing to the database. "
        "Stores the proposal in agent state. Call present_flashcard_proposal "
        "next to show it to the user. Each flashcard needs: topic_id, "
        "question_text, answer_text, entry_ids, and optionally testing_notes."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def create_flashcard_proposal_tool(
        flashcards: list[FlashcardInput],
        runtime: ToolRuntime,
    ) -> Command:
        proposal: list[FlashcardProposalItem] = [
            FlashcardProposalItem(
                topic_id=fc.topic_id,
                question_text=fc.question_text,
                answer_text=fc.answer_text,
                entry_ids=list(fc.entry_ids),
                testing_notes=fc.testing_notes,
            )
            for fc in flashcards
        ]

        msg = f"Flashcard proposal staged: {len(proposal)} card(s). Call present_flashcard_proposal to show it to the user."
        return Command(update={
            "flashcard_proposal": proposal,
            "messages": [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)],
        })

    @tool("present_flashcard_proposal", description=(
        "Display the staged flashcard proposal to the user for review. "
        "The user can approve, request edits, reset, or cancel. "
        "Returns the user's choice. If approved, call accept_flashcard_proposal "
        "to write them to the database. If edits requested, revise and re-stage."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def present_flashcard_proposal_tool(
        runtime: ToolRuntime,
    ) -> Command:
        proposal = runtime.state.get("flashcard_proposal")

        if not proposal:
            return Command(update={
                "messages": [ToolMessage(
                    content="Error: no flashcard proposal staged. Call create_flashcard_proposal first.",
                    tool_call_id=runtime.tool_call_id,
                )],
            })

        # Build the interrupt payload matching FlashcardProposal.from_interrupt
        interrupt_flashcards = [
            {
                "question": fc["question_text"],
                "answer": fc["answer_text"],
                "testing_notes": fc.get("testing_notes"),
                "entry_ids": fc.get("entry_ids", []),
            }
            for fc in proposal
        ]

        result = interrupt({
            "type": "flashcard_proposal",
            "flashcards": interrupt_flashcards,
        })

        choice = result["choice"]

        if choice == "Approve":
            # The widget returns included cards with an `_index` field
            # indicating their position in the original proposal. Each
            # card may have user-edited question/answer text. Update
            # the proposal in state to reflect edits and exclusions.
            approved = result.get("flashcards", [])

            accepted_items: list[FlashcardProposalItem] = []
            for returned in approved:
                idx = returned["_index"]
                original = proposal[idx]
                accepted_items.append(FlashcardProposalItem(
                    topic_id=original["topic_id"],
                    question_text=returned["question"],
                    answer_text=returned["answer"],
                    entry_ids=original["entry_ids"],
                    testing_notes=returned.get("testing_notes"),
                ))

            msg = f"User approved {len(accepted_items)} flashcard(s). Call accept_flashcard_proposal to write them to the database."
            return Command(update={
                "flashcard_proposal": accepted_items,
                "messages": [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)],
            })

        elif choice == "Edit":
            instructions = result.get("instructions", "")
            msg = f"User requested edits: {instructions}"
            return Command(update={
                "messages": [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)],
            })

        else:  # Cancel
            msg = "User cancelled the flashcard proposal."
            return Command(update={
                "flashcard_proposal": None,
                "messages": [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)],
            })

    @tool("accept_flashcard_proposal", description=(
        "Write the approved flashcard proposal to the database. "
        "Call this after the user has approved via present_flashcard_proposal. "
        "Returns the created flashcard IDs."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def accept_flashcard_proposal_tool(
        runtime: ToolRuntime,
    ) -> Command:
        proposal = runtime.state.get("flashcard_proposal")

        if not proposal:
            return Command(update={
                "messages": [ToolMessage(
                    content="Error: no flashcard proposal to accept. Stage and present a proposal first.",
                    tool_call_id=runtime.tool_call_id,
                )],
            })

        # Use review session ID if one is active, otherwise None
        review_state = runtime.state.get("review")
        session_id = review_state["session_id"] if review_state else None

        new_ids: list[int] = []
        async with session_factory() as session:
            for fc_item in proposal:
                fc = await create_flashcard(
                    session,
                    topic_id=fc_item["topic_id"],
                    question_text=fc_item["question_text"],
                    answer_text=fc_item["answer_text"],
                    entry_ids=fc_item["entry_ids"],
                    testing_notes=fc_item.get("testing_notes"),
                    session_id=session_id,
                )
                new_ids.append(fc.id)
            await session.commit()

        msg = f"Created {len(new_ids)} flashcard(s) (IDs: {new_ids})."
        return Command(update={
            "flashcard_proposal": None,
            "messages": [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)],
        })

    return {
        "create_flashcard_proposal": create_flashcard_proposal_tool,
        "present_flashcard_proposal": present_flashcard_proposal_tool,
        "accept_flashcard_proposal": accept_flashcard_proposal_tool,
    }
