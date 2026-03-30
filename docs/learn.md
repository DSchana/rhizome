# Learn Mode

Learn mode is the primary workflow. The user sets a topic as context, chats with the agent to explore it, and commits extracted knowledge entries to the database.

## Entering Learn Mode

- **Slash command:** `/learn`
- **Keybinding:** `Shift+Tab` cycles through modes (idle → learn → review → idle)
- **Agent tool:** The `set_mode` tool can switch modes programmatically

On entry, the system prompt switches to `LEARN_MODE_SECTION` and the tool set is filtered to learn-relevant tools via `AgentModeMiddleware`.

## Topic Selection

The active topic determines where committed entries are stored. It's shown in the status bar (e.g. `[Git > Branching Strategies]`).

**Setting a topic:**
- `/topics` opens an interactive `TopicTreeViewer` — navigate with arrow keys, select with `Ctrl+J`
- The agent can call `set_topic` to set it programmatically
- The agent receives the active topic name in its context on every invocation

## Chatting

With a topic set, the user chats freely. The agent is instructed to:
- Ground answers in the knowledge database (browsing existing entries via `show_topics` / `get_entries`)
- Build on what's already stored rather than repeating it
- Use web search when needed

Nothing is written to the database until the user explicitly commits.

## Commit Workflow

`/commit` enters commit mode — a multi-step process for extracting knowledge entries from the conversation.

### 1. Message Selection

Entering `/commit` overlays checkboxes on selectable messages. Which messages are selectable is controlled by the `CommitSelectable` option:
- `"learn_only"` (default) — only agent messages sent in learn mode
- `"all_agent"` — all agent messages regardless of mode
- `"all"` — all messages including user messages

**Controls:**
- `↑`/`↓` — navigate between messages
- `Space` — toggle selection (auto-advances to next)
- `Ctrl+Enter` — confirm selection
- `Escape` — cancel

### 2. Routing

After confirmation, the selected messages become the **commit payload**. The system routes to one of two paths based on `Options.Subagents.Commit`:

- **Direct path** — for small/simple selections. The root agent examines the payload and proposes entries itself.
- **Subagent path** — for larger selections. A specialized `StructuredSubagent` with database read tools processes the payload and returns structured proposals.

Routing is automatic based on token count or message count thresholds.

### 3. Proposal

Both paths produce a `CommitProposalResponseSchema` — a list of proposed knowledge entries, each with title, content, entry type (`fact` / `exposition` / `overview`), and topic assignment.

The proposal is presented to the user via an interrupt widget. The user can:
- **Approve** — accept as-is
- **Edit** — modify entries and optionally provide instructions for revision
- **Cancel** — discard the proposal

### 4. Commit

On approval, `commit_proposal_accept` writes the entries to the database as `KnowledgeEntry` records and posts a summary of what was committed.

### Commit Tools

| Tool | Path | Purpose |
|------|------|---------|
| `commit_show_selected_messages` | Direct | Retrieve the selected messages as JSON |
| `commit_proposal_create` | Direct | Root agent proposes entries |
| `commit_invoke_subagent` | Subagent | Delegate to commit subagent (supports multi-turn refinement) |
| `commit_proposal_present` | Both | Show proposal to user via interrupt |
| `commit_proposal_accept` | Both | Write approved entries to database |

## Available Tools

**Database:** `list_all_topics`, `show_topics`, `get_entries`, `list_flashcards`, `get_flashcards`, `create_new_topic`, `delete_topics`
**App:** `set_topic`, `set_mode`, `rename_tab`, `ask_user_input`, `hint_higher_verbosity`
**Commit:** `commit_show_selected_messages`, `commit_proposal_create`, `commit_invoke_subagent`, `commit_proposal_present`, `commit_proposal_accept`
**Web:** `web_search`, `web_fetch`
