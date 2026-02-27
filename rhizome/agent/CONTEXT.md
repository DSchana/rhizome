# rhizome/agent/

LLM agent integration using LangChain and LangGraph.

## Architecture

Each chat tab creates its own `AgentSession`, which owns the LangChain conversation history (a list of `BaseMessage`) and a compiled agent graph. The session builds a fresh DB session per `stream()` call via `AgentContext`, passed through LangChain's `context_schema` / `ToolRuntime` mechanism. AIMessages and ToolMessages from the agent are captured into the session's history automatically during streaming, preserving full tool context across turns.

## Modules

- **config.py** — Reads `ANTHROPIC_API_KEY` (required) and `CURRICULUM_AGENT_MODEL` (optional, defaults to `claude-sonnet-4-20250514`) from environment variables.
- **context.py** — `AgentContext` dataclass holding the `AsyncSession` and optional `CurriculumApp` reference for the current invocation.
- **tools.py** — `@tool`-decorated async functions wrapping `rhizome.tools`. Each tool receives a `ToolRuntime[AgentContext]` parameter to access the session. `get_all_tools()` returns the full list.
- **agent.py** — `AgentSession` class encapsulating a conversation's agent graph, message history, and token usage tracking. Also contains `SYSTEM_PROMPT`. Each session builds its own model and agent graph via `_build_agent()`, enabling per-tab model configuration in the future. Exposes `stream()` as an async iterator of `(kind, payload)` tuples, and `add_human_message()`/`add_system_notification()` for appending to history.
- **utils.py** — `TokenUsageData` dataclass for tracking token consumption and context window limits. `compute_chat_model_max_tokens(chat_model)` derives the total context window size from a chat model's `profile` dict.

## Tool List

Curricula: `list_all_curricula`, `list_curriculum_topics`
Topics: `list_root_topics`, `list_topic_children`, `get_topic_subtree`, `create_new_topic`
Entries: `search_knowledge_entries`, `list_topic_entries`, `get_entry_details`, `create_knowledge_entry`
Tags: `list_all_tags`, `get_entries_by_tag_name`, `tag_knowledge_entry`
App Commands: `switch_to_learn_mode`, `switch_to_review_mode`, `switch_to_idle_mode`, `rename_tab`
