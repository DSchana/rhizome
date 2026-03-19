# rhizome/agent/subagents/

Subagent base classes and specialized subagents.

## Architecture

Subagents are lightweight agent instances that run in isolated context windows, separate from the root agent's conversation history. They support stateful (multi-turn via `conversation_id`) and stateless modes. The preferred pattern is specialized subclasses with domain-specific invocation tools, rather than the generic `spawn_subagent`/`invoke_subagent` tools.

## Modules

- **base.py** — `Subagent` dataclass: a lightweight agent with its own isolated conversation history. Provides `preinvoke_hook`/`postinvoke_hook` for subclass customization. `StructuredSubagent` extends `Subagent` with JSON response parsing into a `response_schema` type (dataclass or Pydantic model), storing the result in `structured_response`. `build_subagent_tools()` creates generic `spawn_subagent`/`invoke_subagent` tools for dynamic subagent management.
- **commit.py** — Commit workflow for extracting knowledge entries from selected conversation messages. `build_commit_subagent()` creates a `StructuredSubagent` with DATABASE tools and a `CommitProposalResponseSchema`. `build_commit_subagent_tools()` returns five tools for the root agent: `inspect_commit_payload`, `invoke_commit_subagent` (delegates to the subagent for large selections), `create_commit_proposal` (direct path for small selections), `present_commit_proposal` (shows proposal via interrupt), `accept_commit_proposal` (writes to DB). All tools use `ToolRuntime` to read/write `commit_payload` and `commit_proposal` in `RhizomeAgentState` via `Command(update={...})`.
