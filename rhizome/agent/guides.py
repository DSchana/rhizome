"""Agent guides — on-demand reference material loaded into conversation history.

Guides consolidate detailed instructions (e.g. how to craft good flashcards,
commit proposal workflows) so they're only injected when the agent actually
needs them, keeping the base system prompt lean.

Usage::

    from rhizome.agent.guides import GUIDE_REGISTRY, Guide

    # Register a guide
    GUIDE_REGISTRY["flashcards"] = Guide(
        name="flashcards",
        description="How to craft clear, unambiguous flashcards.",
        content="...",
    )
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Guide:
    """A named block of reference material the agent can load on demand."""

    name: str
    description: str
    content: str


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

GUIDE_REGISTRY: dict[str, Guide] = {
    "flashcards": Guide(
        name="flashcards",
        description="How to craft clear, unambiguous flashcards.",
        content="""
# Guide: Crafting Effective Flashcards

- Predominantly use `fact` knowledge entries for flashcards.
- `exposition` entries can contain a number of flashcards, or can be tested in conversational review.
- `overview` entries are typically best suited for guiding the overall scope/direction of the review, and typically
  should _NOT_ be used as the basis of flashcards.

- Create questions for:
  - Terms and definitions
  - People, places, events
  - Explanations
  - Concepts
  - Key details
  - Key relationships
  - etc.
- Focus on using the 5W/H questions as starting points.
- Example questions include:
  - "What is X?"
  - "What does Y do?"
  - "What command does Z?"
  - "How does W work?"
  - "What is the relationship between X and Y?"
  - "What event caused X?"
  - "Why did Z occur?"
  - "Who is A?"
  - "Why was A relevant to X?"
  - etc.
- Questions MUST be clear, concise, and unambiguous.
- Questions MUST have a _single, atomic, unambiguous answer_.
- Prioritize flashcards with _single word answers_ whenever possible. A one-word answer is easier to recall and
  self-assess. If a concept can be tested with a "What is the name/term for X?" style question that yields a single
  word or short phrase, prefer that formulation over a longer explanation-based question.
- Do NOT give away too much in the question.
- If a question answer could be ambiguous, try to _disambiguate_ in the question itself, _without_ giving away the
  answers.
- Cover breadth and depth among the topics/knowledge entries.
- Vary the cognitive difficulty of the questions.
- _Synthesize_ knowledge entries into new questions. For example, if there are knowledge entries on `git stash` and
  `git pathspec`, then a good question could be "How do you stash everything _but_ a specific file, starting at the
  root of the repository?" This tests both the user's recall of the individual facts, and their synthesis.
- Create flashcards that _link_ knowledge together.
- Use "reversals" strategically — a reversal is when the "content" of the question becomes the question itself, and
  the answer is the question (e.g., if the original question is "What is the capital of Spain", then the reverse is
  "What country is Madrid the capital of?").
  - Not everything benefits from a reversal.
  - Oftentimes it doesn't make sense to include both a question _and_ its reverse in the same review, so choose one
    or the other, prioritizing the "forwards" card.
  - Choose between the forwards/reverse cards based on _which requires more effort to recall_ — always choose the
    higher effort one (e.g. instead of "what does this command do: `X`", choose "what command does Y?").
- Exact numbers and dates (e.g. May 3rd, 1647) are _very difficult to memorize_. Mitigate this as follows:
  - Focus only on the _most important_ dates.
  - Decide what level of specificity is needed for the answer (e.g. only the month and year, or only the year).
  - Create questions with date _ranges_ as answers (e.g., "1950-1955", or the "1820s").
  - Link dates to other pieces of knowledge.
- Lists are _extremely difficult_ to memorize. Do NOT create flashcards prompting the user to recall entire lists or
  tables.
- Do NOT create "true/false" questions as flashcards — emphasize _recall_ over recognition.
- Do NOT create hypothetical questions as flashcards.
- Respect what the notes actually say — the knowledge entries are the source of truth.
"""
    )
}
