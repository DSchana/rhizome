# curriculum_app/agent/

LLM agent integration using LangChain and LangGraph.

## Architecture

The agent graph is built **once** at app startup (`build_agent`) and reused for every chat message. Each invocation gets a fresh DB session via `AgentContext`, passed through LangChain's `context_schema` / `ToolRuntime` mechanism.

## Modules

- **config.py** — Reads `ANTHROPIC_API_KEY` (required) and `CURRICULUM_AGENT_MODEL` (optional, defaults to `claude-sonnet-4-20250514`) from environment variables.
- **context.py** — `AgentContext` dataclass holding the `AsyncSession` for the current invocation.
- **tools.py** — `@tool`-decorated async functions wrapping `curriculum_app.tools`. Each tool receives a `ToolRuntime[AgentContext]` parameter to access the session. `get_all_tools()` returns the full list.
- **agent.py** — `build_agent()` constructs the compiled agent graph with `create_agent`.
- **runner.py** — `invoke_agent()` opens a session, prepends a system prompt with mode/context info, runs the agent, commits, and returns the assistant's reply text.

## Tool List

Curricula: `list_all_curricula`, `list_curriculum_topics`
Topics: `list_root_topics`, `list_topic_children`, `get_topic_subtree`, `create_new_topic`
Entries: `search_knowledge_entries`, `list_topic_entries`, `get_entry_details`, `create_knowledge_entry`
Tags: `list_all_tags`, `get_entries_by_tag_name`, `tag_knowledge_entry`
