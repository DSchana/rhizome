# TUI Implementation Plan

Phased plan for building the Textual-based TUI on top of the existing `db/` and `tools/` layers.

## Proposed Directory Structure

```
rhizome/
├── db/                # existing — no changes expected
├── tools/             # existing — no changes expected
├── tui/
│   ├── __init__.py
│   ├── app.py         # Main Textual App subclass, entry point
│   ├── state.py       # App-level state: active context, chat history, mode
│   ├── commands.py    # Slash command parser and registry
│   ├── screens/
│   │   ├── __init__.py
│   │   ├── chat.py        # Main chat screen (message list + input)
│   │   ├── context.py     # Curriculum/topic selection (/learn entry)
│   │   ├── commit.py      # Commit workflow screens
│   │   ├── review.py      # Review mode scope selection + quiz flow
│   │   └── options.py     # Settings screen
│   └── widgets/
│       ├── __init__.py
│       ├── message.py     # Chat message bubble (user vs. agent styling)
│       ├── status_bar.py  # Persistent bar showing [Curriculum > Topic] + mode
│       └── entry_table.py # Tabular display for entries (commit review, browse)
├── agent/
│   ├── __init__.py
│   ├── client.py      # LLM API client wrapper (streaming support)
│   ├── prompts.py     # System prompts per mode (learn, review, extract)
│   └── extract.py     # Knowledge extraction logic for /commit propose & auto
└── config/
    ├── __init__.py
    └── settings.py    # Persistent user settings (TOML/JSON on disk)
```

### Rationale

- **`tui/`** is the main new package. `screens/` maps 1:1 to major UI states; `widgets/` holds reusable Textual components. `state.py` centralizes mutable app state (active curriculum/topic, chat history, current mode) so screens can read and mutate it without passing data through widget trees. `commands.py` owns the slash-command registry — parsing input, resolving commands, and dispatching to the right screen or action.
- **`agent/`** is a separate package rather than living inside `tui/` because the LLM interaction logic is conceptually independent of the display layer. `client.py` wraps the API (model selection, streaming). `prompts.py` holds system prompts. `extract.py` houses the extraction logic that `/commit propose` and `/commit auto` rely on. Keeping this separate also makes it testable without spinning up a TUI.
- **`config/`** owns persistent user settings (the `/options` backing store). A simple file-based approach (TOML or JSON in a known path like `~/.config/rhizome/settings.toml`) keeps it decoupled from the database.

---

## Phases

### Phase 1 — App Shell

Running Textual app with basic layout, navigation skeleton, and command infrastructure.

**What was built:**
- `tui/app.py` — `CurriculumApp(App)` creates shared `AppState`, pushes `ChatScreen` on mount.
- `tui/state.py` — `AppState` dataclass (`mode`, `active_curriculum`, `active_topic`, `chat_history`), `ChatMessage`, `Mode` enum.
- `tui/commands.py` — `parse_input()` for slash-command detection; `Command(name, description, handler)` dataclass with `COMMANDS` dict registry. Stub handlers for `learn`, `review`, `options`.
- `tui/screens/chat.py` — Main chat screen: scrollable message area, input box, status bar. Routes `/quit` directly (TUI-only), delegates other commands to their registry handlers via `run_worker`.
- `tui/widgets/status_bar.py` — Reactive `mode` and `context` display.
- `tui/widgets/message.py` — `MessageWidget` with role-based styling.
- `tui/__main__.py` — Entry point: `uv run python -m rhizome.tui`.

**Key design decision — commands as agent tools:** Command handlers are standalone `async (AppState, str) -> str` functions, decoupled from the TUI. This allows the agent layer (Phase 3+) to invoke the same commands programmatically — e.g., the agent can call the `/learn` handler when the user says "I want to learn about X" in natural language. `/quit` is the exception: it has no handler and is handled inline by the chat screen, since the agent should never exit the app. State validation (e.g., "is this command valid in the current mode?") will live inside individual handler implementations rather than in a category system.

### Phase 2 — `/learn` Context Selection

Build the first real workflow: picking (or creating) a curriculum and topic. No LLM needed.

**Deliverables:**
- `tui/screens/context.py` — A Textual Screen (or modal) with two paths:
  - **Select existing**: list curricula (from `list_curricula`), pick one, then list its topics (from `list_topics`), pick one. A simple vertical list or `OptionList` widget.
  - **Create new**: inline input fields for curriculum name/description and topic name/description. Calls `create_curriculum` / `create_topic`.
- On selection, update `state.active_curriculum` and `state.active_topic`. The status bar reflects the change.
- `/learn` command dispatches to this screen. After context is set, return to the chat screen.

**Why second:** This is the gateway to the primary workflow. It exercises the full stack (TUI → tools → db) end-to-end without requiring LLM integration, so it proves the architecture early.

### Phase 3 — Chat + Agent Layer

Wire up LLM conversation so the user can actually chat within a learning context.

**Deliverables:**
- `agent/client.py` — Async wrapper around the LLM API. Must support streaming so tokens appear incrementally in the TUI. Expose a simple interface like `async def send(messages, system_prompt) -> AsyncIterator[str]`.
- `agent/prompts.py` — System prompt for learn mode. Should include the active curriculum/topic name and description so the agent tailors responses.
- `tui/widgets/message.py` — Chat message widget with distinct styling for user vs. agent. Agent messages stream in (appending content as chunks arrive). Support markdown rendering (Textual has `Markdown` / `RichLog` widgets).
- `tui/screens/chat.py` — The main screen. On submit: append user message to `state.chat_history`, call `agent.client.send()`, stream the response into a new agent message widget, append the complete response to history.
- Non-slash input goes to the agent; slash input goes to the command router.

**Why third:** Chat is the core interaction. Once this works, the user can actually learn things — even before commit is built, the app is usable as a context-aware LLM chat.

### Phase 4 — `/commit` (Manual)

The simplest commit strategy: user selects agent messages and saves them as entries.

**Deliverables:**
- `tui/screens/commit.py` — Triggered by `/commit`. Overlays the chat with checkboxes on each agent message. After selection, presents an editable form per selected message: title (auto-generated, editable), entry_type (dropdown), additional_notes (text area), tags (comma-separated input), difficulty (optional int input), speed_testable (checkbox).
- On confirm, calls `create_entry` and `tag_entry` for each, then `session.commit()`. Displays the commit summary.
- `tui/widgets/entry_table.py` — Tabular view used in the commit summary (and later in browse/review).

**Why fourth:** This closes the core value loop: set context → chat → commit knowledge. The three most important features are now working.

### Phase 5 — `/review` Browse

View stored entries without LLM involvement. Simplest review type.

**Deliverables:**
- `tui/screens/review.py` — Scope selection: pick a curriculum, topic, or tag. Uses the same selection pattern as the context screen.
- "Browse entries" option: fetches entries via `list_entries` / `get_entries_by_tag` and displays them in `entry_table.py` with full detail (title, content, type, tags, difficulty, speed_testable).
- Basic navigation: scroll through entries, maybe expand/collapse content.

**Why fifth:** Lets users verify what they've committed and builds the review screen infrastructure that quizzes will plug into.

### Phase 6 — Agent-Powered Features

Features that require the agent to analyze or generate content.

**Deliverables (can be parallelized):**
- **`/commit propose`** — `agent/extract.py` takes chat history, returns structured list of proposed entries (title, content, entry_type, tags). The TUI presents them in an editable table with checkboxes. User reviews, edits, confirms.
- **`/commit auto`** — Same extraction, but skips the review step. Commits immediately, shows summary.
- **Free-form quiz** — Agent generates questions from entries in the selected scope. `agent/prompts.py` gets a review/quiz system prompt. The chat screen runs in "quiz mode": question → user answer → agent evaluation → next question.
- **Timed quiz** — Like free-form but filters to `speed_testable` entries. Adds a timer widget to the screen. Tracks response times (display only for now — no persistence).

**Why sixth:** These are the most complex features and all depend on a working agent layer + chat + commit infrastructure. Deferring them avoids blocking the core loop on LLM prompt engineering.

### Phase 7 — `/options` + Config

**Deliverables:**
- `config/settings.py` — Load/save settings from a config file. Fields: default curriculum ID, LLM model/provider, default entry_type, quiz length, timer duration.
- `tui/screens/options.py` — Form-based screen for editing settings. Writes to the config file on save.
- Wire settings into the app: `agent/client.py` reads model config, `/learn` respects the default curriculum, `/review` respects quiz length/timer defaults.

**Why last:** The app is fully functional without this. Settings are polish that make the experience smoother but don't unlock new capabilities.

---

## Cross-Cutting Concerns

Things that don't belong to a single phase but should be addressed as they come up:

- **Session lifecycle**: The TUI needs a long-lived session factory. Initialize the engine + factory at app startup (in `app.py`). Individual operations should open short-lived sessions, commit, and close — don't hold a session open for the app's entire lifetime.
- **Error handling in the TUI**: Tool functions raise `ValueError` for missing entities. The TUI should catch these and display user-friendly notifications (Textual's `notify()`) rather than crashing.
- **Testing**: The project currently uses `examples/exercise_tools.py` as its test suite. As we build the agent and TUI layers, we should consider whether to continue this pattern or adopt pytest. At minimum, `agent/extract.py` and `tui/commands.py` are good candidates for unit tests since they're pure logic without UI dependencies.
- **Keyboard shortcuts**: Textual supports keybindings natively. We should define sensible defaults early (e.g. `Ctrl+Enter` to submit, `Escape` to back out of a screen/mode) and keep them consistent across screens.

---

## What This Plan Defers

These items from the design docs are intentionally left for later:

- Performance tracking / spaced repetition (noted as "future" in the review mode doc).
- Chat history persistence to the database (open question — currently chat is ephemeral).
- Multi-topic commits and conversation scoping (open questions).
- Undo granularity (open question).
- Anki/Obsidian export integrations (noted as "future" in options doc).
