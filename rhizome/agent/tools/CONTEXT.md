# rhizome/agent/tools/

Tool definitions and infrastructure for the rhizome agent.

## Architecture

Tools are built via factory functions that close over `session_factory` and an optional `chat_pane`. Each tool creates its own `AsyncSession`, eliminating the need for a shared session lock. Tool visibility (`ToolVisibility`) controls which tools appear in the TUI status bar at different verbosity levels.

Each tool group has its own builder function (e.g. `build_core_tools`, `build_app_tools`). `AgentSession.__init__` assembles the full tool list by calling each builder directly.

## Modules

- **\_\_init\_\_.py** — Re-exports `ToolVisibility`, `TOOL_VISIBILITY`, and `tool_visibility` from the visibility module.
- **visibility.py** — `ToolVisibility` enum (LOW, DEFAULT, HIGH), `TOOL_VISIBILITY` registry dict, and `@tool_visibility` decorator for registering a tool's visibility level. Anthropic server-side tools (`web_search`, `web_fetch`) are pre-registered here.
- **core.py** — `build_core_tools(session_factory)` — core knowledge-base tools: `list_topics`, `list_knowledge_entries`, `create_topics` (recursive subtree creation via `TopicNode` schema), `delete_topics`, `read_knowledge_entries`, `list_flashcards` (by topic_ids or knowledge_entry_ids), `read_flashcards`. Defines `TopicNode` Pydantic model for recursive topic creation.
- **app.py** — `build_app_tools(session_factory, chat_pane)` — app control tools: `set_topic`, `set_mode` (returns `Command` to update graph state), `rename_tab`, `ask_user_input` (interrupt-based multiple choice), `hint_higher_verbosity`. Also defines the `Question` Pydantic model for `ask_user_input`.
- **sql.py** — `build_sql_tools(session_factory)` — last-resort SQL tools: `describe_database` (schema introspection via PRAGMA), `execute_sql` (unified query/modification tool; defaults to read-only, set `read_only=False` for INSERT/UPDATE/DELETE with preview and user confirmation via `sql_confirmation` interrupt; read queries capped at 200 rows).
- **flashcard_proposal.py** — `build_flashcard_proposal_tools(session_factory, answerer, comparator)` — mode-independent flashcard proposal workflow: `flashcard_proposal_create` (stages in state, with optional `validate=True` for inline clarity testing via answerer/comparator subagents), `flashcard_proposal_present` (shows via interrupt, builds diff summary of user edits), `flashcard_proposal_edit` (targeted edits/additions/deletions by stable ID), `flashcard_proposal_accept` (writes to DB). Defines `FlashcardProposalItem` TypedDict, `FlashcardInput` and `FlashcardEdit` Pydantic schemas. Available in both learn and review modes.
- **review.py** — `build_review_tools(session_factory, scorer)` — tools for the review session state machine covering SCOPING, CONFIGURING, PLANNING, REVIEWING, and SUMMARIZING phases. Tools that mutate `ReviewState` return `Command(update={"review": ...})`. Includes `present_flashcards` (interrupt-based flashcard presentation for both critique-during and critique-after modes; auto-scored cards are scored inline by the scorer subagent). `record_review_interaction` is for conversational review only (no flashcard support). Defines `AUTO_SCORE` constant.
