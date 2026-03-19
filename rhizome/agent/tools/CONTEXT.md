# rhizome/agent/tools/

Tool definitions and infrastructure for the rhizome agent.

## Architecture

Tools are built via factory functions that close over `session_factory` and an optional `chat_pane`. Each tool creates its own `AsyncSession`, eliminating the need for a shared session lock. Tool visibility (`ToolVisibility`) controls which tools appear in the TUI status bar at different verbosity levels.

Each tool group has its own builder function (e.g. `build_database_tools`, `build_app_tools`). `AgentSession.__init__` assembles the full tool list by calling each builder directly.

## Modules

- **\_\_init\_\_.py** — Re-exports `ToolVisibility`, `TOOL_VISIBILITY`, and `tool_visibility` from the visibility module.
- **visibility.py** — `ToolVisibility` enum (LOW, DEFAULT, HIGH), `TOOL_VISIBILITY` registry dict, and `@tool_visibility` decorator for registering a tool's visibility level. Anthropic server-side tools (`web_search`, `web_fetch`) are pre-registered here.
- **database.py** — `build_database_tools(session_factory)` — topic and entry CRUD tools: `list_all_topics`, `show_topics`, `create_new_topic`, `delete_topics`, `get_entries`, `create_entries`.
- **app.py** — `build_app_tools(session_factory, chat_pane)` — app control tools: `set_topic`, `set_mode` (returns `Command` to update graph state), `rename_tab`, `ask_user_input` (interrupt-based multiple choice), `hint_higher_verbosity`. Also defines the `Question` Pydantic model for `ask_user_input`.
- **sql.py** — `build_sql_tools(session_factory)` — last-resort SQL tools: `describe_database` (schema introspection via PRAGMA), `run_sql_query` (read-only, capped at 200 rows), `run_sql_modification` (INSERT/UPDATE/DELETE with preview and user confirmation via `sql_confirmation` interrupt).
- **flashcard.py** — `build_flashcard_proposal_tools(session_factory)` — mode-independent flashcard proposal workflow: `create_flashcard_proposal` (stages in state), `present_flashcard_proposal` (shows via interrupt), `accept_flashcard_proposal` (writes to DB). Defines `FlashcardProposalItem` TypedDict and `FlashcardInput` Pydantic schema. Available in both learn and review modes.
- **review.py** — `build_review_tools(session_factory)` — 13 tools for the review session state machine covering SCOPING, CONFIGURING, PLANNING, REVIEWING, and SUMMARIZING phases. Tools that mutate `ReviewState` return `Command(update={"review": ...})`.
