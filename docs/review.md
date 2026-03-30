# Review Mode

Review mode is for practicing and testing knowledge that's been committed to the database. It follows a multi-phase state machine managed by `ReviewState` in the agent's graph state.

## Entering Review Mode

- **Slash command:** `/review`
- **Keybinding:** `Shift+Tab` cycles through modes (idle → learn → review → idle)
- **Agent tool:** The `set_mode` tool can switch modes programmatically

## Session Lifecycle

A review session progresses through phases:

```
SCOPING → CONFIGURING → PLANNING → REVIEWING → SUMMARIZING
```

State is tracked in two places: `ReviewState` (in-memory graph state, cleared on session end) and `ReviewSession` (database record, persists for historical continuity).

### Scoping

The agent helps the user decide what to review:
1. Browse the knowledge base using `list_topics`, `list_knowledge_entries`, `read_knowledge_entries`
2. Check prior review history via `get_review_sessions` (retrieves up to 5 sessions overlapping the selected topics, ranked by IoU, with `final_summary` for continuity)
3. Lock in scope by calling `set_review_scope(entry_ids)` — this creates a `ReviewSession` DB record and initializes `ReviewState`

### Configuring

The agent sets session parameters via `configure_review`:

| Parameter | Options | Default behavior |
|-----------|---------|-----------------|
| **Review style** | `flashcard`, `conversation`, `mixed` | Flashcard: structured Q&A. Conversation: open-ended discussion. Mixed: flashcards then conversation. |
| **Critique timing** | `during`, `after` | During: immediate feedback. After: batched at end. |
| **Question source** | `existing`, `generated`, `both` | Existing: reuse saved flashcards. Generated: create new ones. Both: mix. |
| **Ephemeral** | bool | If true, session won't appear in future `get_review_sessions` calls |
| **User instructions** | text | Stored on the session for agent reference |

The agent infers what it can from context and only asks about ambiguous options.

### Planning

The agent prepares the question sequence before starting:

**For flashcard-based reviews:**
1. `list_flashcards(entry_ids)` — check which entries already have flashcards
2. `read_flashcards(flashcard_ids)` — inspect existing card content
3. `add_flashcards_to_review(flashcard_ids)` — queue existing flashcard IDs
4. For entries that need new flashcards, follow the proposal workflow:
   - `flashcard_proposal_create(flashcards)` — stage cards for user review
   - `flashcard_proposal_present()` — show proposal to user (approve / edit / cancel)
   - `flashcard_proposal_accept()` — write approved cards to DB
   - `add_flashcards_to_review(flashcard_ids)` — add created IDs to the queue
5. `set_review_flashcards(flashcard_ids)` — replace the full queue order if needed

**For conversational reviews:**
- Load entry content and organize a discussion flow
- No flashcards created — questions are generated naturally during the review

Call `start_review(plan)` to begin, optionally storing a discussion plan outline.

### Reviewing

The core loop. The agent presents questions, evaluates responses, and records interactions.

**Flashcard flow:** Pop from queue → present question → receive answer → score → record → repeat until queue empty.

**Conversational flow:** Follow the discussion plan → ask natural questions → evaluate understanding → record at checkpoints.

**Scoring:** 0–5 scale (0 = no answer/wrong, 3 = correct but incomplete, 5 = excellent). The agent judges overall understanding rather than expecting verbatim recall.

**Recording:** `record_review_interaction` takes message IDs for the question and answer, extracts text from history, accepts either a `flashcard_id` or explicit `entry_ids`, and creates `ReviewInteraction` + `ReviewInteractionEntry` DB records. It also updates in-memory entry coverage tracking and pops the flashcard from the queue if applicable.

### Summarizing

After `complete_review_session` (computes aggregate stats, sets `completed_at`), the agent writes a structured summary covering:
- Scope, style, question count
- Overall score and per-entry breakdown
- Strengths, areas for improvement, recommendations

`save_review_summary(final_summary)` persists this to the DB and clears `ReviewState`, ending the session.

## Flashcard Model

Flashcards are reusable question templates stored in the database:
- Tied to a **topic** (required) and optionally to the **session** that created them
- Linked to one or more **knowledge entries** via `FlashcardEntry` junction (enables synthesis questions)
- Have `question_text`, `answer_text`, and optional `testing_notes` (instructions for evaluating responses)
- When a parent session is deleted, its flashcards cascade-delete

The flashcard queue supports both **append** (`add_flashcards_to_review`) and **replace** (`set_review_flashcards`) semantics. Use append for adding new cards; use replace for reordering or clearing the queue.

## Review Tools

| Tool | Phase(s) | Purpose |
|------|----------|---------|
| `get_review_sessions` | Scoping | Retrieve prior sessions for continuity |
| `set_review_scope` | Scoping → Configuring | Lock scope, create DB session, init state |
| `configure_review` | Configuring → Planning | Set style, timing, source, ephemeral, instructions |
| `list_flashcards` | Planning | Check existing flashcard coverage |
| `read_flashcards` | Planning | Get flashcard content by ID |
| `set_review_flashcards` | Planning / Reviewing | Set queue (replace semantics) |
| `flashcard_proposal_create` | Any (learn or review) | Stage flashcards for user review |
| `flashcard_proposal_present` | Any (learn or review) | Show proposal interrupt, return user's decision |
| `flashcard_proposal_accept` | Any (learn or review) | Write approved flashcards to DB |
| `add_flashcards_to_review` | Planning / Reviewing | Append flashcard IDs to queue |
| `start_review` | Planning → Reviewing | Store discussion plan, begin review |
| `record_review_interaction` | Reviewing | Record Q&A, update coverage and queue |
| `complete_review_session` | Reviewing → Summarizing | Compute stats, mark complete |
| `save_review_summary` | Summarizing | Persist summary, clear state, end session |
| `inspect_review_state` | Any | Dump current state for debugging |
| `clear_review_state` | Any | Abandon session, clear state (DB records remain) |

## Other Available Tools

**Database (read-only):** `list_topics`, `list_knowledge_entries`, `read_knowledge_entries`, `list_flashcards`, `read_flashcards`
**App:** `set_topic`, `set_mode`, `rename_tab`, `ask_user_input`, `hint_higher_verbosity`
**Web:** `web_search`, `web_fetch`
