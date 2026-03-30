# Codebase Maturity Review

**Date:** 2026-03-30
**Scope:** Full codebase (88 files, ~18k lines in `rhizome/`)
**Perspective:** Senior-level architectural review assessing design maturity

---

## What's genuinely good

These are not just "good for a solo project" — they'd pass review at a well-run team:

### 1. Layer separation and dependency direction

`db -> agent -> tui` is clean. The DB operations know nothing about the agent. The agent knows nothing about widgets. Dependencies flow one way. This is harder to maintain than it looks, and it's done correctly here.

### 2. The flush-not-commit pattern

Operations call `session.flush()` and leave `commit()` to the caller. This is correct — it allows transaction bundling and makes the operations composable. Many professional codebases get this wrong.

### 3. Tool registration via factory closures

Each tool builder closes over `session_factory`, giving every tool its own session without global state. This makes parallel tool execution inherently safe and is a genuinely good design.

### 4. The options system (`options.py`)

This is the most polished piece of the codebase. Metaclass-driven spec registry, hierarchical scope inheritance with pub/sub, conditional dependent options that auto-reset, JSONC persistence. It would hold up in a production app.

### 5. `AgentModeMiddleware` design

The separation of state-modifying hooks (`abefore_model`) from stateless request-time overrides (`awrap_model_call`) shows real understanding of middleware architecture. The bidirectional mode sync (user-initiated via pending slot, agent-initiated via `Command`) is correctly designed.

### 6. SQL injection safety

All queries are properly parameterized throughout. No string interpolation into SQL anywhere.

### 7. CONTEXT.md convention

Every directory has one. For LLM-assisted development this is excellent practice and shows forward thinking.

---

## Critical shortcomings

### 1. No real test suite — the single biggest risk

`exercise_tools.py` is a hand-rolled smoke test with custom `ok()`/`fail()` helpers. It covers ~30% of the DB operations surface and 0% of:

- Agent tools (31 files, ~2400 lines)
- Middleware behavior (5 files)
- Subagent invocation and structured output parsing
- State transitions (mode changes, review lifecycle, commit workflow)
- TUI widget behavior
- Options validation and pub/sub propagation
- Error paths

**Why this matters:** Complex state machines (review sessions, flashcard proposals, commit workflows) pass through multiple layers — agent state -> tool -> DB operation -> back. A refactor to any of these will break silently. The cost of not having tests grows super-linearly with codebase size, and at 18k lines the project is well past the threshold where "I'll just test manually" becomes untenable.

**Action:** Adopt pytest. Start with the operations layer (pure async functions, easy to test). Then add tests for the tool functions by mocking the session_factory. The middleware is independently testable. Full 100% coverage isn't needed — coverage of the state machines and error paths is.

### 2. N+1 query patterns in core operations

Three operations have textbook N+1 problems:

```python
# topics.py:get_subtree — CTE returns IDs, then fetches each individually
for row in rows:
    topic = await session.get(Topic, row.topic_id)  # 1 query per row

# reviews.py:get_sessions_by_topics — loads sessions, then per-session query
for rs in sessions:
    tid_result = await session.execute(...)  # 1 query per session

# reviews.py:get_interaction_stats — loads interactions, then per-interaction query
for ix in interactions:
    entry_result = await session.execute(...)  # 1 query per interaction
```

With SQLite and small data this is invisible. With 100+ topics or review sessions, it'll feel like the app is frozen. The fix is straightforward: join in the CTE or use `selectinload()`.

### 3. `ChatPane` is a 1391-line god object

This single widget handles: message rendering, agent session lifecycle, mode management, commit mode state machine, command dispatch (18+ commands), topic context tracking, status bar updates, interrupt widget lifecycle, and options subscription.

This isn't "large file that could be split for aesthetics." It's a real maintenance problem — changing the commit workflow requires understanding the agent lifecycle; changing command dispatch requires understanding mode state. These are independent concerns tangled together.

**Recommended extraction (in priority order):**
1. Command handlers -> separate module (they're already methods named `_cmd_*`)
2. Agent session controller (create, stream, cancel, rebuild, interrupt handling)
3. Commit mode manager (enter/exit, selection state, cursor)

### 4. `execute_sql` keyword filtering is fragile

```python
_READ_KEYWORDS = frozenset({"SELECT", "PRAGMA", "EXPLAIN", "WITH"})
```

`WITH` is classified as read-only, but `WITH ... AS (...) DELETE FROM ...` is valid SQL. A CTE can wrap any DML statement. The `_first_keyword` function checks only the first token, so this is bypassable by the LLM (or by a prompt injection in user data that influences the LLM's SQL generation).

In read-only mode, there's also no query timeout or statement-level resource limit, so an expensive `SELECT` could lock the database.

**Action:** Use SQLite's `SQLITE_LIMIT_VDBE_OP` or at minimum wrap reads in a read-only transaction (`BEGIN DEFERRED` + `ROLLBACK`). For the keyword check, consider `sqlparse` or at minimum check for DML keywords anywhere in the statement, not just position 0.

### 5. Only Anthropic actually works, but OpenAI is offered in the UI

```python
# builder.py
def _init_model(provider: str, model_name: str, temperature: float = 0.3):
    if provider == "anthropic":
        return init_chat_model(model_name, api_key=get_api_key(), temperature=temperature)
    raise ValueError(f"Unsupported provider: {provider}")
```

`Options.Agent.Provider` offers `["anthropic", "openai"]`, and `Options.Agent.Model` has OpenAI models listed. Selecting OpenAI will crash at agent build time. Either implement it or remove it from the options.

---

## Significant concerns

### 6. Tight coupling to LangChain internals

Dependencies on non-stable APIs:
- `langchain.agents.middleware.types.AgentMiddleware` (middleware hook interface)
- `langchain.agents.create_agent`
- `langchain.chat_models.init_chat_model`
- `langgraph.prebuilt.tool_node.ToolRuntime`
- `langgraph.types.Command`, `interrupt`

LangChain has a history of breaking changes across minor versions, and version constraints are loose (`langchain>=0.3`).

**Action:** Pin to specific minor versions (e.g., `langchain>=0.3.0,<0.4`). Consider wrapping the most volatile APIs behind thin adapters.

### 7. Dependency bloat

`langchain-voyageai`, `langchain-community`, `faiss-cpu`, and `pypdf` are not imported anywhere in the `rhizome/` package (they're for planned Resource/embedding features). `langchain-community` is a massive meta-package.

Every unused dependency is install time, CI build time, and attack surface. Move these to an `[optional]` dependency group or a `[resources]` extra until the features they support actually exist.

### 8. No error boundaries between layers

When a tool function fails, it typically raises an unhandled exception that propagates up through the agent stream. There's no structured error handling at the tool-agent boundary. Some tools catch exceptions (the SQL tool), but most don't. A database connection failure in any tool will crash the entire stream.

**Action:** Each tool should catch its own operational errors and return a `ToolMessage` with the error, rather than letting exceptions propagate.

### 9. `InMemorySaver` + no context window management

The `InMemorySaver` checkpointer stores the full conversation history in memory. There's no summarization, no pruning, no sliding window. `_compute_overhead_tokens` calls `_get_graph_messages()` (full history read) on every token chunk. In a long session, this will degrade.

`total_tokens` and `max_tokens` are tracked in `TokenUsageData`, but nothing happens when the window is approaching capacity. A production system needs context summarization, message pruning, or at minimum a warning to the user.

### 10. Logger name inconsistency

```python
# In db/operations/reviews.py:
_logger = get_logger("tools.reviews")  # "tools" prefix, but this is db/operations

# In agent/tools/review.py:
_logger = get_logger("agent.review_tools")  # "agent" prefix, correct

# In db/operations/topics.py:
_logger = get_logger("tools.topics")  # Same misleading "tools" prefix
```

All DB operations use the `tools.` namespace, which makes log filtering confusing. These should be `db.operations.reviews`, etc.

### 11. Documented TOCTOU races are real bugs

The `add_relation()` cycle check and `tag_entry()` get-or-create races are documented with TODOs. For single-user SQLite this is low risk (SQLite's write lock serializes concurrent writers). But if the DB ever moves to Postgres, or if the TUI starts using concurrent tasks that share a session, these become data corruption bugs. The fixes are known (CAS pattern, `INSERT ... ON CONFLICT`).

---

## Maturity summary

| Dimension | Rating | Notes |
|---|---|---|
| **Architecture / separation** | Senior | Clean layers, good dependency direction, no cycles |
| **Database modeling** | Mid-senior | Correct cascades, constraints, CTEs. N+1 patterns drag it down |
| **State management** | Senior | Graph state design, mode synchronization, options hierarchy |
| **Testing** | Junior | Hand-rolled smoke test, no framework, no coverage of agent/TUI |
| **Error handling** | Junior-mid | Inconsistent, no error boundaries, no retry/resilience |
| **Security** | Mid | SQL params are safe, but execute_sql is exploitable |
| **Operability** | Junior | No CI, no linting config, no container, no health checks |
| **Dependency management** | Junior-mid | Loose pins, unused deps in core, placeholder pyproject metadata |
| **Code organization** | Mid | ChatPane god object, but most other files are well-scoped |
| **Documentation** | Mid-senior | CONTEXT.md is great. Inline docs are good. No user-facing docs |

**Overall:** The architecture is built like a mid-level engineer who reads like a senior. The architectural decisions are sound — the knowledge is there. What's missing is the discipline infrastructure that comes from shipping to production and maintaining under pressure: tests, error boundaries, CI, dependency hygiene, and the willingness to split a beloved god object before it becomes load-bearing.

---

## Highest-leverage next steps (in order)

1. Adopt pytest and cover the operations + tools layers
2. Split `ChatPane`
3. Fix N+1 queries
4. Pin LangChain versions and move unused deps to optional
5. Add structured error handling at the tool-agent boundary
