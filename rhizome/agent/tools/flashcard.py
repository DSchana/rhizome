"""Flashcard proposal tools — stage, present, and accept flashcard proposals.

These tools are mode-independent: they can be used during learn mode
(to create flashcards from a learning conversation) or during review mode
(to propose flashcards as part of a review session).  Proposal state is
stored in ``RhizomeAgentState.flashcard_proposal_state``, separate from
``ReviewState``.
"""

from __future__ import annotations

import json
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


class FlashcardProposalState(TypedDict):
    """Consolidated state for the flashcard proposal workflow.

    Stored in ``RhizomeAgentState.flashcard_proposal_state``.
    """
    items: list[FlashcardProposalItem]
    """The staged flashcard items."""

    validation_attempts: int
    """Number of validation attempts consumed.  Persists across re-stages
    so that the attempt budget is enforced across the full proposal
    lifecycle."""


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

def build_flashcard_proposal_tools(
    session_factory,
    answerer=None,
    comparator=None,
    *,
    max_validation_attempts: int = 2,
) -> dict[str, Any]:
    """Build flashcard proposal tools with session_factory closed over.

    Parameters
    ----------
    answerer, comparator:
        Optional ``StructuredSubagent`` instances for flashcard validation.
        Required if the ``validate`` flag on ``create_flashcard_proposal``
        is to be used.
    max_validation_attempts:
        Maximum number of validation attempts per proposal before failing
        cards are dropped.
    """

    @tool("create_flashcard_proposal", description=(
        "Stage flashcards for user review without writing to the database. "
        "Stores the proposal in agent state. Call present_flashcard_proposal "
        "next to show it to the user. Each flashcard needs: topic_id, "
        "question_text, answer_text, entry_ids, and optionally testing_notes. "
        "Set validate=True to run an automated clarity check before presenting "
        "to the user (required on first call; optional on subsequent re-stages)."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def create_flashcard_proposal_tool(
        flashcards: list[FlashcardInput],
        runtime: ToolRuntime,
        validate: bool = False,
    ) -> Command:
        items: list[FlashcardProposalItem] = [
            FlashcardProposalItem(
                topic_id=fc.topic_id,
                question_text=fc.question_text,
                answer_text=fc.answer_text,
                entry_ids=list(fc.entry_ids),
                testing_notes=fc.testing_notes,
            )
            for fc in flashcards
        ]

        # Read prior attempt count from existing state (persists across re-stages).
        fp_state: FlashcardProposalState | None = runtime.state.get("flashcard_proposal_state")
        prior_attempts = (fp_state.get("validation_attempts") or 0) if fp_state else 0

        proposal_state = FlashcardProposalState(
            items=items,
            validation_attempts=prior_attempts,
        )

        if not validate:
            msg = (
                f"Flashcard proposal staged: {len(items)} card(s). "
                f"Call present_flashcard_proposal to show it to the user."
            )
            return Command(update={
                "flashcard_proposal_state": proposal_state,
                "messages": [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)],
            })

        # --- Inline validation ---
        if answerer is None or comparator is None:
            return Command(update={
                "flashcard_proposal_state": proposal_state,
                "messages": [ToolMessage(
                    content="Error: validation subagents not configured. Stage without validate=True.",
                    tool_call_id=runtime.tool_call_id,
                )],
            })

        attempts = prior_attempts + 1
        is_final_attempt = attempts >= max_validation_attempts

        # Step 1: Build question list for the answerer
        questions_payload = [
            {"index": i, "question": fc["question_text"]}
            for i, fc in enumerate(items)
        ]

        answerer_input = (
            "Answer each of the following flashcard questions:\n\n"
            + "\n".join(f"{q['index']}. {q['question']}" for q in questions_payload)
        )

        _logger.debug("Invoking answerer subagent with %d question(s)", len(questions_payload))
        _, answerer_response = await answerer.ainvoke(answerer_input)

        if answerer.structured_response is None:
            return Command(update={
                "flashcard_proposal_state": {**proposal_state, "validation_attempts": attempts},
                "messages": [ToolMessage(
                    content=json.dumps({
                        "error": "Answerer subagent failed to produce structured output.",
                        "raw_response": answerer_response.content,
                    }, indent=2, default=str),
                    tool_call_id=runtime.tool_call_id,
                )],
            })

        answerer_answers: dict[int, str] = {
            a.question_index: a.answer
            for a in answerer.structured_response.answers
        }

        # Step 2: Build comparison payload
        comparison_items = [
            {
                "index": i,
                "question": fc["question_text"],
                "expected_answer": fc["answer_text"],
                "test_taker_answer": answerer_answers.get(i, "(no answer provided)"),
                "testing_notes": fc.get("testing_notes"),
            }
            for i, fc in enumerate(items)
        ]

        comparator_input = (
            "Evaluate the following flashcards for clarity and unambiguity:\n\n"
            + "\n---\n".join(
                f"Card {item['index']}:\n"
                f"  Question: {item['question']}\n"
                f"  Expected answer: {item['expected_answer']}\n"
                f"  Test-taker answer: {item['test_taker_answer']}\n"
                + (f"  Testing notes: {item['testing_notes']}\n" if item["testing_notes"] else "")
                for item in comparison_items
            )
        )

        _logger.debug("Invoking comparator subagent with %d card(s)", len(comparison_items))
        _, comparator_response = await comparator.ainvoke(comparator_input)

        if comparator.structured_response is None:
            return Command(update={
                "flashcard_proposal_state": {**proposal_state, "validation_attempts": attempts},
                "messages": [ToolMessage(
                    content=json.dumps({
                        "error": "Comparator subagent failed to produce structured output.",
                        "raw_response": comparator_response.content,
                    }, indent=2, default=str),
                    tool_call_id=runtime.tool_call_id,
                )],
            })

        # Step 3: Build result summary
        results = []
        all_passed = True
        for card_result in comparator.structured_response.results:
            idx = card_result.question_index
            fc = items[idx] if idx < len(items) else None
            result_entry: dict[str, Any] = {
                "question_index": idx,
                "question": fc["question_text"] if fc else "(unknown)",
                "expected_answer": fc["answer_text"] if fc else "(unknown)",
                "test_taker_answer": answerer_answers.get(idx, "(no answer)"),
                "passed": card_result.passed,
                "feedback": card_result.feedback,
            }
            results.append(result_entry)
            if not card_result.passed:
                all_passed = False

        passed_count = sum(1 for r in results if r["passed"])
        failed_count = len(results) - passed_count
        remaining_attempts = max_validation_attempts - attempts

        summary: dict[str, Any] = {
            "all_passed": all_passed,
            "passed": passed_count,
            "failed": failed_count,
            "total": len(results),
            "attempt": attempts,
            "max_attempts": max_validation_attempts,
            "remaining_attempts": remaining_attempts,
            "results": results,
        }

        if all_passed:
            msg = (
                f"Flashcard proposal staged and validated (attempt {attempts}/{max_validation_attempts}): "
                f"all {len(results)} card(s) are clear and unambiguous. "
                f"Proceed with present_flashcard_proposal."
            )
        elif is_final_attempt:
            failed_indices = [r["question_index"] for r in results if not r["passed"]]
            msg = (
                f"Flashcard proposal staged. Final validation attempt ({attempts}/{max_validation_attempts}): "
                f"{passed_count}/{len(results)} passed, {failed_count} still failing. "
                f"Maximum revision attempts exhausted. Drop the failing card(s) "
                f"(indices: {failed_indices}) from the proposal by re-staging with "
                f"create_flashcard_proposal (validate=False) containing only the passing cards, "
                f"then proceed directly to present_flashcard_proposal."
            )
        else:
            msg = (
                f"Flashcard proposal staged. Validation attempt {attempts}/{max_validation_attempts}: "
                f"{passed_count}/{len(results)} passed, {failed_count} failed. "
                f"{remaining_attempts} attempt(s) remaining. "
                f"Review the feedback, revise failed cards, and re-stage with "
                f"create_flashcard_proposal(validate=True)."
            )

        _logger.info(
            "Flashcard validation attempt %d/%d: %d/%d passed",
            attempts, max_validation_attempts, passed_count, len(results),
        )

        return Command(update={
            "flashcard_proposal_state": {**proposal_state, "validation_attempts": attempts},
            "messages": [ToolMessage(
                content=json.dumps({"summary": msg, **summary}, indent=2),
                tool_call_id=runtime.tool_call_id,
            )],
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
        fp_state: FlashcardProposalState | None = runtime.state.get("flashcard_proposal_state")

        if not fp_state or not fp_state.get("items"):
            return Command(update={
                "messages": [ToolMessage(
                    content="Error: no flashcard proposal staged. Call create_flashcard_proposal first.",
                    tool_call_id=runtime.tool_call_id,
                )],
            })

        proposal = fp_state["items"]

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
                "flashcard_proposal_state": {**fp_state, "items": accepted_items},
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
                "flashcard_proposal_state": None,
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
        fp_state: FlashcardProposalState | None = runtime.state.get("flashcard_proposal_state")

        if not fp_state or not fp_state.get("items"):
            return Command(update={
                "messages": [ToolMessage(
                    content="Error: no flashcard proposal to accept. Stage and present a proposal first.",
                    tool_call_id=runtime.tool_call_id,
                )],
            })

        proposal = fp_state["items"]

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
            "flashcard_proposal_state": None,
            "messages": [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)],
        })

    return {
        "create_flashcard_proposal": create_flashcard_proposal_tool,
        "present_flashcard_proposal": present_flashcard_proposal_tool,
        "accept_flashcard_proposal": accept_flashcard_proposal_tool,
    }
