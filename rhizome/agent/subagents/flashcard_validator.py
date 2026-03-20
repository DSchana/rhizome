"""Flashcard validation subagents: test proposed flashcards for clarity and unambiguity.

Two subagents work in sequence:

1. **Answerer** — receives each flashcard question (with NO additional context) and
   attempts to answer it in a single short paragraph or single term.
2. **Comparator** — receives the expected answers, the answerer's answers, and
   any testing notes, then evaluates whether each flashcard is clear and unambiguous.

The root agent receives per-card feedback and an overall pass/fail verdict.
"""

from __future__ import annotations

import json
from typing import Any

from langchain.agents.structured_output import ProviderStrategy
from langchain_core.messages import ToolMessage
from langchain.tools import tool
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.types import Command
from pydantic import BaseModel, Field

from rhizome.agent.builder import build_agent
from rhizome.agent.subagents.base import StructuredSubagent
from rhizome.agent.tools.flashcard import FlashcardProposalState
from rhizome.agent.tools.visibility import ToolVisibility, tool_visibility
from rhizome.logs import get_logger

_logger = get_logger("agent.flashcard_validator")

DEFAULT_MAX_VALIDATION_ATTEMPTS = 2

# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class AnswererCardResponse(BaseModel):
    question_index: int = Field(description="Zero-based index of the flashcard in the proposal")
    answer: str = Field(description="Your best answer to the question — a single term or one short paragraph")


class AnswererResponse(BaseModel):
    answers: list[AnswererCardResponse]


class ComparatorCardResult(BaseModel):
    question_index: int = Field(description="Zero-based index of the flashcard in the proposal")
    passed: bool = Field(description="True if the answerer's response demonstrates the flashcard is clear and unambiguous")
    feedback: str = Field(description="Explanation of the verdict — if failed, concrete suggestions for improvement")


class ComparatorResponse(BaseModel):
    results: list[ComparatorCardResult]


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

ANSWERER_SYSTEM_PROMPT = """\
You are a flashcard answering agent. You will be given a set of flashcard questions.
For each question, provide your best answer using ONLY your own general knowledge.
You have NO additional context — no notes, no database, no prior conversation.

Answer each question with either:
- A single term or short phrase (preferred when the question asks for a name, command, definition, etc.)
- One short paragraph (when the question requires a brief explanation)

Do NOT hedge or say "I don't know" — always give your best attempt.

Respond ONLY with a JSON object in this exact format — no additional text:
{
    "answers": [
        {"question_index": 0, "answer": "your answer here"},
        {"question_index": 1, "answer": "your answer here"}
    ]
}"""

COMPARATOR_SYSTEM_PROMPT = """\
You are a flashcard quality evaluator. You will receive a set of flashcard questions, each with:
- The expected answer (from the flashcard author)
- An answer produced by a test-taker who had NO additional context
- Optional testing notes describing how to assess responses

Your job is to evaluate whether each flashcard is **clear and unambiguous** by comparing the \
test-taker's answer against the expected answer.

A flashcard **passes** if the test-taker's answer demonstrates that the question is clear enough \
to elicit the correct answer (or a reasonably close equivalent) without additional context. Minor \
wording differences are acceptable — focus on whether the core concept was correctly identified.

A flashcard **fails** if:
- The test-taker's answer is substantially different from the expected answer, suggesting the \
question is ambiguous or misleading
- The question could reasonably be interpreted in multiple ways, leading to a valid but different answer
- The question is too vague to elicit a specific response
- The question gives away too much of the answer, making it trivially easy (not truly testing recall)

When a flashcard fails, provide concrete, actionable suggestions for how to improve the question \
to make it unambiguous. Draw from strategies like these (use whichever are relevant):

- **Be more specific**: add qualifying context to the question to narrow the answer space \
(e.g. "In the context of X, what is Y?" instead of just "What is Y?").
- **Split into multiple cards**: if the question conflates two concepts, suggest breaking it into \
separate, focused questions that each have a single atomic answer.
- **Try a reversal**: if the forward question is ambiguous, suggest reversing it \
(e.g. instead of "What does X do?" try "What command/term does Y?").
- **Narrow the scope**: if the expected answer is one of several valid responses, suggest \
constraining the question to eliminate alternatives (e.g. "In Linux, ..." or "Using Git, ...").

Respond ONLY with a JSON object in this exact format — no additional text:
{
    "results": [
        {"question_index": 0, "passed": true, "feedback": "Clear and unambiguous."},
        {"question_index": 1, "passed": false, "feedback": "The question could refer to X or Y. Suggest: ..."}
    ]
}"""


# ---------------------------------------------------------------------------
# Subagent builders
# ---------------------------------------------------------------------------

def build_answerer_subagent(**agent_kwargs) -> StructuredSubagent:
    provider = agent_kwargs.pop("provider", "anthropic")
    model_name = agent_kwargs.pop("model_name", "claude-haiku-4-5-20251001")

    model, agent, _mw = build_agent(
        tools=[],
        provider=provider,
        model_name=model_name,
        response_format=ProviderStrategy(AnswererResponse),
        **{**agent_kwargs, "temperature": 0.0},
    )
    return StructuredSubagent(
        model=model,
        agent=agent,
        system_prompt=ANSWERER_SYSTEM_PROMPT,
        stateful=False,
        response_schema=AnswererResponse,
    )


def build_comparator_subagent(**agent_kwargs) -> StructuredSubagent:
    provider = agent_kwargs.pop("provider", "anthropic")
    model_name = agent_kwargs.pop("model_name", "claude-sonnet-4-6")

    model, agent, _mw = build_agent(
        tools=[],
        provider=provider,
        model_name=model_name,
        response_format=ProviderStrategy(ComparatorResponse),
        **{**agent_kwargs, "temperature": 0.0},
    )
    return StructuredSubagent(
        model=model,
        agent=agent,
        system_prompt=COMPARATOR_SYSTEM_PROMPT,
        stateful=False,
        response_schema=ComparatorResponse,
    )


# ---------------------------------------------------------------------------
# Tool builder
# ---------------------------------------------------------------------------

def build_flashcard_validator_tools(
    answerer: StructuredSubagent,
    comparator: StructuredSubagent,
    *,
    max_attempts: int = DEFAULT_MAX_VALIDATION_ATTEMPTS,
) -> list:
    """Build the validate_flashcard_proposal tool for the root agent."""

    @tool("validate_flashcard_proposal", description=(
        "Validate the staged flashcard proposal by testing whether an independent "
        "agent can answer each question correctly without additional context. "
        "Returns per-card pass/fail verdicts with feedback. Requires the "
        "validation_id returned by create_flashcard_proposal. Call this after "
        "create_flashcard_proposal and before present_flashcard_proposal."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def validate_flashcard_proposal_tool(
        validation_id: str,
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

        # Verify the validation_id matches the current proposal
        current_id = fp_state.get("validation_id")
        if current_id != validation_id:
            return Command(update={
                "messages": [ToolMessage(
                    content=(
                        f"Error: validation_id mismatch. Expected '{current_id}', "
                        f"got '{validation_id}'. The proposal may have been re-staged — "
                        f"use the validation_id from the most recent create_flashcard_proposal call."
                    ),
                    tool_call_id=runtime.tool_call_id,
                )],
            })

        # Track attempts
        attempts = (fp_state.get("validation_attempts") or 0) + 1
        is_final_attempt = attempts >= max_attempts

        # Step 1: Build the question list for the answerer
        questions_payload = []
        for i, fc in enumerate(proposal):
            questions_payload.append({
                "index": i,
                "question": fc["question_text"],
            })

        answerer_input = (
            "Answer each of the following flashcard questions:\n\n"
            + "\n".join(
                f"{q['index']}. {q['question']}"
                for q in questions_payload
            )
        )

        _logger.debug("Invoking answerer subagent with %d question(s)", len(questions_payload))
        _, answerer_response = await answerer.ainvoke(answerer_input)

        if answerer.structured_response is None:
            return Command(update={
                "messages": [ToolMessage(
                    content=json.dumps({
                        "error": "Answerer subagent failed to produce structured output.",
                        "raw_response": answerer_response.content,
                    }, indent=2, default=str),
                    tool_call_id=runtime.tool_call_id,
                )],
            })

        # Build an index map of answerer responses
        answerer_answers: dict[int, str] = {
            a.question_index: a.answer
            for a in answerer.structured_response.answers
        }

        # Step 2: Build the comparison payload
        comparison_items = []
        for i, fc in enumerate(proposal):
            comparison_items.append({
                "index": i,
                "question": fc["question_text"],
                "expected_answer": fc["answer_text"],
                "test_taker_answer": answerer_answers.get(i, "(no answer provided)"),
                "testing_notes": fc.get("testing_notes"),
            })

        comparator_input = (
            "Evaluate the following flashcards for clarity and unambiguity:\n\n"
            + "\n---\n".join(
                f"Card {item['index']}:\n"
                f"  Question: {item['question']}\n"
                f"  Expected answer: {item['expected_answer']}\n"
                f"  Test-taker answer: {item['test_taker_answer']}\n"
                + (f"  Testing notes: {item['testing_notes']}\n" if item['testing_notes'] else "")
                for item in comparison_items
            )
        )

        _logger.debug("Invoking comparator subagent with %d card(s)", len(comparison_items))
        _, comparator_response = await comparator.ainvoke(comparator_input)

        if comparator.structured_response is None:
            return Command(update={
                "messages": [ToolMessage(
                    content=json.dumps({
                        "error": "Comparator subagent failed to produce structured output.",
                        "raw_response": comparator_response.content,
                    }, indent=2, default=str),
                    tool_call_id=runtime.tool_call_id,
                )],
            })

        # Step 3: Build the result summary
        results = []
        all_passed = True
        for card_result in comparator.structured_response.results:
            idx = card_result.question_index
            fc = proposal[idx] if idx < len(proposal) else None
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
        remaining_attempts = max_attempts - attempts

        summary: dict[str, Any] = {
            "all_passed": all_passed,
            "passed": passed_count,
            "failed": failed_count,
            "total": len(results),
            "attempt": attempts,
            "max_attempts": max_attempts,
            "remaining_attempts": remaining_attempts,
            "results": results,
        }

        if all_passed:
            msg = (
                f"Validation passed (attempt {attempts}/{max_attempts}): "
                f"all {len(results)} flashcard(s) are clear and unambiguous. "
                f"Proceed with present_flashcard_proposal."
            )
        elif is_final_attempt:
            failed_indices = [r["question_index"] for r in results if not r["passed"]]
            msg = (
                f"Final validation attempt ({attempts}/{max_attempts}): "
                f"{passed_count}/{len(results)} passed, {failed_count} still failing. "
                f"Maximum revision attempts exhausted. Drop the failing card(s) "
                f"(indices: {failed_indices}) from the proposal by re-staging with "
                f"create_flashcard_proposal containing only the passing cards, "
                f"then proceed directly to present_flashcard_proposal."
            )
        else:
            msg = (
                f"Validation attempt {attempts}/{max_attempts}: "
                f"{passed_count}/{len(results)} passed, {failed_count} failed. "
                f"{remaining_attempts} attempt(s) remaining. "
                f"Review the feedback and revise failed cards, then re-stage with "
                f"create_flashcard_proposal and validate again."
            )

        _logger.info(
            "Flashcard validation attempt %d/%d: %d/%d passed",
            attempts, max_attempts, passed_count, len(results),
        )

        return Command(update={
            "flashcard_proposal_state": {**fp_state, "validation_attempts": attempts},
            "messages": [ToolMessage(
                content=json.dumps({"summary": msg, **summary}, indent=2),
                tool_call_id=runtime.tool_call_id,
            )],
        })

    return [validate_flashcard_proposal_tool]
