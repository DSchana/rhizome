# rhizome/agent/

LLM agent integration using LangChain and LangGraph.

## Architecture

Each chat tab creates its own `AgentSession`, which owns the LangChain conversation history (a list of `BaseMessage`) and a compiled agent graph. The session builds a fresh DB session per `stream()` call via `AgentContext`, passed through LangChain's `context_schema` / `ToolRuntime` mechanism. AIMessages and ToolMessages from the agent are captured into the session's history automatically during streaming, preserving full tool context across turns.

## Modules

- **config.py** — Reads `ANTHROPIC_API_KEY` (required) and `CURRICULUM_AGENT_MODEL` (optional, defaults to `claude-sonnet-4-20250514`) from environment variables.
- **context.py** — `AgentContext` dataclass holding the `AsyncSession`, optional `CurriculumApp` reference, and a `session_lock` (`asyncio.Lock`) for the current invocation. The lock serialises concurrent tool access to the session.
- **tools.py** — `@tool`-decorated async functions wrapping `rhizome.tools`. Each tool receives a `ToolRuntime[AgentContext]` parameter to access the session. `get_all_tools()` returns the full list.
- **agent.py** — `AgentSession` class encapsulating a conversation's agent graph, message history, and token usage tracking. Also contains `SYSTEM_PROMPT`. Each session builds its own model and agent graph via `_build_agent(provider, model_name)` with an `InMemorySaver` checkpointer for interrupt/resume support. Each session has a `thread_id` (UUID) for LangGraph checkpointing. Stores `_provider` and `_model_name` and exposes `rebuild_agent(provider, model_name)` for hot-swapping models. `on_options_post_update(options)` is designed as a callback for `Options.post_update()` — it reads provider/model from the passed-in Options instance and rebuilds if changed. Exposes `stream()` as a callback-driven async method (not an iterator) that accepts `on_message`, `on_update`, `on_interrupt`, and `post_chunk_handler` callbacks. The method owns the while/break loop for interrupt handling: when `__interrupt__` appears in an updates payload, it calls `on_interrupt` to get a resume value and re-invokes `astream` with `Command(resume=...)`. Also exposes `add_human_message()`/`add_system_notification()` for appending to history.
- **utils.py** — `TokenUsageData` dataclass for tracking token consumption and context window limits. `compute_chat_model_max_tokens(chat_model)` derives the total context window size from a chat model's `profile` dict.
- **middleware/** — LangChain agent middleware components. See `middleware/CONTEXT.md`.

## Tool List

Curricula: `list_all_curricula`, `list_curriculum_topics`
Topics: `list_root_topics`, `list_topic_children`, `get_topic_subtree`, `create_new_topic`
Entries: `search_knowledge_entries`, `list_topic_entries`, `get_entry_details`, `create_knowledge_entry`
Tags: `list_all_tags`, `get_entries_by_tag_name`, `tag_knowledge_entry`
App Commands: `switch_to_learn_mode`, `switch_to_review_mode`, `switch_to_idle_mode`, `rename_tab`
