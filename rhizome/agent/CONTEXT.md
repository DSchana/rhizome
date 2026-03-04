# rhizome/agent/

LLM agent integration using LangChain and LangGraph.

## Architecture

Each chat tab creates its own `AgentSession`, which owns the LangChain conversation history (a list of `BaseMessage`) and a compiled agent graph. Tools are built via `build_tools(session_factory, chat_pane)` — a factory that closes over the session factory and optional chat pane. Each tool creates its own DB session, eliminating the need for a shared session lock. `AgentContext` holds only immutable per-invocation data (`user_settings`), satisfying LangGraph's guideline that runtime context should be immutable.

## Modules

- **config.py** — Reads `ANTHROPIC_API_KEY` (required) and `CURRICULUM_AGENT_MODEL` (optional, defaults to `claude-sonnet-4-20250514`) from environment variables.
- **context.py** — `AgentContext` dataclass holding only `user_settings: dict` for the current invocation.
- **tools.py** — `build_tools(session_factory, chat_pane)` factory that returns `@tool`-decorated async functions. Each tool creates its own `AsyncSession` via the closed-over `session_factory`. Tools needing TUI access (`set_mode`, `rename_tab`) capture `chat_pane` from the closure.
- **system_prompt.py** — Contains `SYSTEM_PROMPT`, the system prompt string used by `AgentSession`.
- **agent.py** — `AgentSession` class encapsulating a conversation's agent graph, message history, and token usage tracking. Each session builds its own model and agent graph via `_build_agent(tools, provider, model_name)` with an `InMemorySaver` checkpointer for interrupt/resume support. Each session has a `thread_id` (UUID) for LangGraph checkpointing. Stores `_provider` and `_model_name` and exposes `rebuild_agent(provider, model_name)` for hot-swapping models. `on_options_post_update(options)` is designed as a callback for `Options.post_update()` — it reads provider/model from the passed-in Options instance and rebuilds if changed. Exposes `stream()` as a callback-driven async method (not an iterator) that accepts `on_message`, `on_update`, `on_interrupt`, and `post_chunk_handler` callbacks. The method owns the while/break loop for interrupt handling: when `__interrupt__` appears in an updates payload, it calls `on_interrupt` to get a resume value and re-invokes `astream` with `Command(resume=...)`. Also exposes `add_human_message()`/`add_system_notification()` for appending to history.
- **utils.py** — `TokenUsageData` dataclass for tracking token consumption and context window limits. `compute_chat_model_max_tokens(chat_model)` derives the total context window size from a chat model's `profile` dict.
- **middleware/** — LangChain agent middleware components. See `middleware/CONTEXT.md`.

## Tool List

Curricula: `list_all_curricula`, `list_curriculum_topics`
Topics: `list_root_topics`, `list_topic_children`, `get_topic_subtree`, `create_new_topic`
Entries: `search_knowledge_entries`, `list_topic_entries`, `get_entry_details`, `create_knowledge_entry`
Tags: `list_all_tags`, `get_entries_by_tag_name`, `tag_knowledge_entry`
App Commands: `set_mode`, `rename_tab`
