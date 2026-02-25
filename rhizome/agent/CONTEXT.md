# rhizome/agent/

LLM agent integration using LangChain and LangGraph.

## Architecture

The agent graph is built **once** at app startup (`build_agent`) and reused for every chat message. Each invocation gets a fresh DB session via `AgentContext`, passed through LangChain's `context_schema` / `ToolRuntime` mechanism.

## Modules

- **config.py** — Reads `ANTHROPIC_API_KEY` (required) and `CURRICULUM_AGENT_MODEL` (optional, defaults to `claude-sonnet-4-20250514`) from environment variables.
- **context.py** — `AgentContext` dataclass holding the `AsyncSession` and optional `CurriculumApp` reference for the current invocation.
- **tools.py** — `@tool`-decorated async functions wrapping `rhizome.tools`. Each tool receives a `ToolRuntime[AgentContext]` parameter to access the session. `get_all_tools()` returns the full list.
- **agent.py** — `build_agent()` returns a `(model, agent)` tuple: the chat model instance (for inspecting its `profile` dict with context window limits) and the compiled agent graph.
- **utils.py** — `compute_chat_model_max_tokens(chat_model)` attempts to derive the total context window size (`max_input_tokens + max_output_tokens`) from a chat model's `profile` dict. Returns `None` if the profile is unavailable or incomplete (profiles are a beta LangChain feature).
- **runner.py** — `stream_agent()` opens a session, prepends a system prompt with mode/context info, and streams agent output using dual `stream_mode=["updates", "messages"]`. Yields `("message", text_str)` for filtered model text tokens and `("update", chunk_dict)` for raw graph state updates. Commits on completion.

## Tool List

Curricula: `list_all_curricula`, `list_curriculum_topics`
Topics: `list_root_topics`, `list_topic_children`, `get_topic_subtree`, `create_new_topic`
Entries: `search_knowledge_entries`, `list_topic_entries`, `get_entry_details`, `create_knowledge_entry`
Tags: `list_all_tags`, `get_entries_by_tag_name`, `tag_knowledge_entry`
App Commands: `switch_to_learn_mode`, `switch_to_review_mode`, `switch_to_idle_mode`, `rename_tab`
