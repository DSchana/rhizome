"""Flashcard validation subagents: test proposed flashcards for clarity and unambiguity.

Two subagents work in sequence:

1. **Answerer** — receives each flashcard question (with NO additional context) and
   attempts to answer it in a single short paragraph or single term.
2. **Comparator** — receives the expected answers, the answerer's answers, and
   any testing notes, then evaluates whether each flashcard is clear and unambiguous.

The validation logic itself lives in ``create_flashcard_proposal`` (in
``rhizome.agent.tools.flashcard``) — this module only defines the subagent
builders and their response schemas.
"""

from __future__ import annotations

from langchain.agents.structured_output import ProviderStrategy
from pydantic import BaseModel, Field

from rhizome.agent.builder import build_agent
from rhizome.agent.subagents.base import StructuredSubagent
from rhizome.logs import get_logger

_logger = get_logger("agent.flashcard_validator")

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
