# `/learn` Mode

Learning mode is the primary workflow. The user sets a curriculum/topic as context, chats with the agent to learn about it, and then commits extracted knowledge to the database.

## 1. Entering learn mode

When the user types `/learn`, they are presented with two paths:

- **Select existing context** — browse and pick a curriculum and topic from the database.
- **Create new context** — create a new curriculum and/or topic inline.

Once a curriculum + topic are set, they appear in the status bar (e.g. `[Git > Branching Strategies]`) and all subsequent knowledge commits target that topic.

The user can change context at any time by running `/learn` again or a sub-command like `/learn context`.

## 2. Chatting

With context set, the user simply chats with the agent. This works like any LLM chat — ask questions, get explanations, explore concepts. The agent is aware of the active curriculum/topic and can tailor its responses accordingly.

Chat messages accumulate in the conversation history but **nothing is written to the database** until the user explicitly commits.

## 3. Committing knowledge

The user decides when to "commit" — converting parts of the conversation into `KnowledgeEntry` records. There are three commit strategies, from most to least manual:

### 3a. Manual commit (`/commit`)

Running `/commit` with no arguments enters manual commit mode:

- Every **agent message** in the current conversation gets a checkbox next to it.
- The user scrolls through the conversation and checks the messages they want to commit.
- For each selected message, the user can optionally edit attributes before confirming:
  - **title** (auto-generated from content, editable)
  - **entry_type** (`fact`, `concept`, `procedure`, `example`, etc.)
  - **additional_notes** (free text the user can append)
  - **tags** (add/remove)
  - **difficulty** (nullable integer)
  - **speed_testable** (boolean, default false — flag for timed-quiz eligibility)
- On confirm, the selected messages are saved as individual `KnowledgeEntry` records under the active topic.

This gives the user full control over exactly what gets stored and how it's categorized.

### 3b. Propose facts (`/commit propose`)

A single agent message might contain multiple distinct facts. `/commit propose` asks the agent to:

1. Analyze the full chat history (or a selected range).
2. Extract individual factoids / knowledge atoms.
3. Present them in a **table** with columns: `[x]`, `title`, `content` (truncated), `entry_type`, `tags`.
4. The user checks rows to include, edits attributes inline, then confirms.

This is the middle ground — the agent does the extraction work, but the user still reviews and approves every entry.

### 3c. Auto commit (`/commit auto`)

The laziest option. The agent analyzes the conversation, extracts facts, categorizes them, and commits them all in one shot. The user gets a summary of what was committed and can undo or edit entries after the fact.

Useful for rapid learning sessions where the user trusts the agent's judgment.

## Commit summary

After any commit strategy completes, the user sees a summary:

```
Committed 5 entries to [Git > Branching Strategies]:
  - "Fast-forward vs. three-way merge"  (fact)
  - "When to use rebase"                (concept)
  - "Creating a feature branch"         (procedure, speed_testable)
  ...
```
