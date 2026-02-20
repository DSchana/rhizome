# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Rhizome is a knowledge management system designed for LLM agent integration. It supports structured learning (storing knowledge entries) and practice (quizzes). The database layer and tool functions are complete; TUI (Textual) and agent layers are planned.

**Tech stack:** Python 3.14+, SQLAlchemy 2.x (async), aiosqlite, SQLite

## Commands

```bash
# Install dependencies
uv sync

# Run the comprehensive tool function test suite
uv run python examples/exercise_tools.py

# Seed a sample database (creates explore.db)
uv run python examples/seed_sample_db.py

# Run any Python script
uv run python <script.py>
```

There is no formal test framework (pytest, etc.) yet. `examples/exercise_tools.py` serves as the end-to-end test suite.

## CONTEXT.md Files

Each directory under `rhizome/` contains a `CONTEXT.md` describing its contents, purpose, and how it fits into the larger system. These files are essential context for working in this codebase:

- **Always read** the relevant `CONTEXT.md` files before planning changes or writing new code in a directory.
- **Always update** the affected `CONTEXT.md` files after any major code change (adding/removing modules, changing public API, altering architectural patterns).
- **Always create** a `CONTEXT.md` when adding a new directory under `rhizome/`.

## Architecture

### Database Layer (`rhizome/db/`)
- **models.py** — 8 SQLAlchemy ORM models using modern `Mapped`/`mapped_column` syntax:
  - `Curriculum` — subject area, linked to topics via `CurriculumTopic` junction (many-to-many with ordering)
  - `CurriculumTopic` — junction table with `position` for ordered curriculum-topic membership
  - `Topic` — tree structure via adjacency list (`parent_id` self-FK). Entries attach at any depth.
  - `KnowledgeEntry`, `Tag`, `KnowledgeEntryTag` — knowledge units with tagging
  - `RelatedKnowledgeEntries` — directed graph edges between entries (acyclic, enforced via recursive CTE)
- **engine.py** — Async engine factory (`get_engine`), session factory (`get_session_factory`), and `init_db()` for table creation

### Tool Functions (`rhizome/tools/`)
Pure async functions that accept `AsyncSession` as their first argument. Each module maps to a domain:
- **curricula.py** — CRUD for Curriculum + curriculum-topic membership (`add_topic_to_curriculum`, `remove_topic_from_curriculum`, `reorder_topic_in_curriculum`, `list_topics_in_curriculum`)
- **topics.py** — CRUD for Topic tree (`create_topic` with optional `parent_id`, `list_root_topics`, `list_children`, `get_subtree`)
- **entries.py** — CRUD + `search_entries()` (LIKE-based search on title/content)
- **tags.py** — Tag CRUD, `tag_entry`/`untag_entry` (idempotent), `get_entries_by_tag`
- **relations.py** — Graph edge management with cycle detection (`CycleError`), `get_dependency_chain` (recursive, depth-limited to 10)

Both `__init__.py` files re-export all public symbols.

## Key Patterns

- **Async-first**: All DB operations are async coroutines. Sessions come from `async_sessionmaker` with `expire_on_commit=False`.
- **Tool functions don't commit**: They call `session.flush()` but leave `commit()` to the caller, allowing transaction bundling.
- **Partial updates**: Update functions only modify fields where the argument is not `None`.
- **Cycle detection**: `add_relation()` runs a recursive CTE to check reachability before inserting a graph edge.
- **Tag normalization**: Tag names are lowercased on creation to prevent duplicates.

## Documentation

- `docs/schema-proposal.md` — Detailed schema design with rationale and example SQL
- `docs/work-report-schema-implementation.md` — SQLAlchemy ORM patterns and async implementation guide
- `docs/braindump.md` — Product vision (learning phases, Anki/Obsidian integration plans)
