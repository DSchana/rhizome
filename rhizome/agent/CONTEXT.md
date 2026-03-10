# rhizome/agent/

LLM agent integration using LangChain and LangGraph.

## Architecture

Each chat tab creates its own `AgentSession`, which owns the LangChain conversation history (a list of `BaseMessage`) and a compiled agent graph. Tools are built via `build_tools(session_factory, chat_pane)` — a factory that closes over the session factory and optional chat pane. Each tool creates its own DB session, eliminating the need for a shared session lock. `AgentContext` holds only immutable per-invocation data (`user_settings`), satisfying LangGraph's guideline that runtime context should be immutable.

## Modules

- **config.py** — Reads `ANTHROPIC_API_KEY` (required) and `CURRICULUM_AGENT_MODEL` (optional, defaults to `claude-sonnet-4-20250514`) from environment variables.
- **context.py** — `AgentContext` dataclass holding `user_settings: dict` for the current invocation.
- **tools.py** — `build_tools(session_factory, chat_pane, included=None)` factory that returns `@tool`-decorated async functions. Each tool creates its own `AsyncSession` via the closed-over `session_factory`. Tools needing TUI access (`set_mode`, `rename_tab`) capture `chat_pane` from the closure. The `included` parameter filters to a subset of tool names.
- **system_prompt.py** — Contains `SYSTEM_PROMPT`, the system prompt string used by `AgentSession`.
- **builder.py** — `build_agent(tools, provider, model_name, **agent_kwargs)` constructs a `(model, agent)` tuple. Its primary purpose is to encapsulate provider-specific setup (API keys, middleware selection, model defaults) so callers can build agents without caring which provider is in use. Used by both `AgentSession` and subagent spawning.
- **session.py** — `AgentSession` class encapsulating a conversation's agent graph, message history, and token usage tracking. Delegates graph construction to `build_agent()`. Each session has a `thread_id` (UUID) for LangGraph checkpointing. Stores `_provider` and `_model_name` and exposes `rebuild_agent(provider, model_name)` for hot-swapping models. `on_options_post_update(options)` is designed as a callback for `Options.post_update()` — it reads provider/model from the passed-in Options instance and rebuilds if changed. Exposes `stream()` as a callback-driven async method (not an iterator) that accepts `on_message`, `on_update`, `on_interrupt`, and `post_chunk_handler` callbacks. User settings (answer/planning verbosity) are injected as persistent `[System]`-prefixed `HumanMessage`s in the graph state, queued only when settings change. Also contains `get_agent_kwargs(options)` for building provider-specific kwargs from Options.
- **subagent.py** — `Subagent` dataclass: a lightweight agent with its own isolated conversation history. Supports stateful (multi-turn via `conversation_id`) and stateless modes. Provides `preinvoke_hook`/`postinvoke_hook` for subclass customization. `StructuredSubagent` extends `Subagent` with JSON response parsing into a `response_schema` type. `build_subagent_tools()` creates generic `spawn_subagent`/`invoke_subagent` tools, though specialized subclasses with domain-specific tools are the preferred pattern.
- **commit.py** — Commit workflow for extracting knowledge entries from selected conversation messages. Defines `CommitProposalResponseSchema` (containing `KnowledgeEntryProposalSchema` entries) and `_ProposalRef` (closure-captured mutable container shared across commit tools). `build_commit_subagent()` creates a `StructuredSubagent` with DATABASE tools. `build_commit_subagent_tools()` returns five tools for the root agent, supporting two paths: **subagent path** (`invoke_commit_subagent` delegates to the commit subagent for large/complex selections) and **direct path** (`inspect_commit_payload` retrieves selected messages, `create_commit_proposal` lets the root agent propose entries itself for small selections). Both paths write to the shared `_ProposalRef`, and `present_commit_proposal` (displays proposal via interrupt) and `accept_commit_proposal` (writes to DB) work identically regardless of source.
- **utils.py** — `TokenUsageData` dataclass for tracking token consumption and context window limits. `compute_chat_model_max_tokens(chat_model)` derives the total context window size from a chat model's `profile` dict.
- **middleware/** — LangChain agent middleware components. See `middleware/CONTEXT.md`.

## Tool List

Topics: `list_all_topics`, `show_topics`, `create_new_topic`, `delete_topics`
Entries: `get_entries`, `create_entries`
App Commands: `set_topic`, `set_mode`, `rename_tab`, `ask_user_input`
