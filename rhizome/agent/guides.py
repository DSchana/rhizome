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

    "knowledge_entries": Guide(
        name="knowledge_entries",
        description="How to create well-structured knowledge entries: schema, granularity, good/bad examples.",
        content="""\
# Guide: Knowledge Entries

Knowledge Entries are the atomic units of knowledge in the system. They represent individual factoids, or small bits
of exposition of ideas, within a given topic. Each entry belongs to exactly one topic and has the following fields:
- title (required) — A short, descriptive name for the entry.
- content (required) — The main body of the entry.
- additional_notes (optional, defaults to empty) — Supplementary context or caveats.
- entry_type (optional, nullable) — Categorizes the entry's verbosity/style. Must be one of:
  - fact — A concise, unambiguous factoid (e.g. "d is the delete operator").
  - exposition — A longer explanation or definition (e.g. "A motion is a command that moves the cursor").
  - overview — A high-level summary that ties multiple concepts together (e.g. "Operators compose with motions:
    dw deletes a word").
- difficulty (optional, nullable) — An integer representing the entry's difficulty level.
- speed_testable (boolean, defaults to false) — Whether the entry is suitable for timed recall quizzes.

Entries can be tagged with any number of tags and linked to other entries via directed relationships.

It is important to recognize that the purpose of a "knowledge entry" is to be a concise unit of knowledge that can be
reflected upon whenever the user asks to review knowledge on a topic. Knowledge entries can be thought of as a more
generalized notion of an "anki flashcard", with a front matter (the title) and a reverse matter (the content). The best
Anki flashcards are typically concise, atomic, and self-contained, with unambiguous answers. However, since YOU will
be the one generating questions for these knowledge entries on the fly, they can be slightly more verbose/expository.

## Extraction granularity

Always decompose source material into the finest-grained entries that make sense. A single paragraph of conversation can
yield many entries — up to 10 fact-style entries is not unusual. For example, if a message gives an overview of all the
different "git worktree" commands, do NOT create a single exposition entry listing them all; instead create one entry per
command. A paragraph can also produce both fact and exposition entries simultaneously, depending on the content — extract
the discrete factoids as facts and the explanatory material as expositions when appropriate.

## Good Examples of Knowledge Entries

Fact entries — concise, atomic, unambiguous:

- Title: Vim Delete Operator
  Content: `d` is the delete operator. It combines with a motion to delete text (e.g. `dw` deletes a word).

- Title: Race Condition Definition
  Content: A race condition occurs when program behaviour depends on the relative timing of concurrent operations.

- Title: SRTF Scheduling Algorithm
  Content: Shortest Remaining Time First (SRTF) is a preemptive scheduling algorithm that always runs the process
  with the least remaining execution time.

- Title: HTTP 204 Status Code
  Content: 204 No Content indicates the request succeeded but the server has no body to return. Commonly used for
  DELETE responses.

Exposition entries — slightly longer, explaining a concept:

- Title: What Is a Mutex
  Content: A mutex (mutual exclusion lock) is a synchronization primitive that ensures only one thread can access a
  shared resource at a time. A thread acquires the lock before entering a critical section and releases it when done.
  If the lock is already held, other threads block until it becomes available.

- Title: Python GIL
  Content: The Global Interpreter Lock (GIL) is a mutex in CPython that allows only one thread to execute Python
  bytecode at a time. This simplifies memory management but means CPU-bound threads cannot run in parallel.
  I/O-bound threads release the GIL while waiting, so threading still helps for I/O workloads.

Overview entries — tie multiple concepts together:

- Title: Vim Operator-Motion Composition
  Content: Operators (d, c, y, etc.) compose with motions (w, e, $, etc.) to act on text regions. For example, `dw`
  deletes a word and `y$` yanks to end of line. This composability means N operators and M motions give N*M commands.
  Operators can also take text objects (iw, a", ip) for structural selections.

## Bad Examples of Knowledge Entries

Too broad — no single entry should try to cover an entire field:

- Title: How Operating Systems Work
  Content: An operating system manages hardware resources and provides services to applications. It handles
  process scheduling, memory management, file systems, I/O, and security...
  Why bad: This is a textbook chapter, not an entry. Break it into entries per concept (e.g. "Process Scheduling",
  "Virtual Memory", etc.).

Too vague — the title promises insight but the content is a platitude:

- Title: Why Distributed Systems Are Hard
  Content: Distributed systems are hard because many things can go wrong with networks and timing.
  Why bad: Not actionable or reviewable. Better entries would cover specific concepts: "CAP Theorem",
  "Network Partition", "Byzantine Fault", etc.

Too terse — lacks enough detail to be useful during review:

- Title: What Is Caching
  Content: Storing stuff for later.
  Why bad: Technically true but useless for review. A good version: "Caching stores the results of expensive
  computations or remote fetches in a faster-access layer (memory, local disk) to avoid repeating the work on
  subsequent requests."

Question-as-title without a clear answer:

- Title: How does DNS work?
  Content: It translates domain names to IP addresses.
  Why bad: The title is a question (titles should be declarative labels) and the content omits the interesting
  structure (recursive resolvers, root/TLD/authoritative servers, TTL). Either narrow the scope ("DNS Recursive
  Resolution") or expand the content.
""",
    ),
    
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
