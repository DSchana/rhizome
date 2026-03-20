# rhizome/

Top-level application package. The `__init__.py` is empty — all public API is accessed through the subpackages:

- **`db/`** — ORM models and async engine/session management. Import models and `init_db`/`get_engine`/`get_session_factory` from here.
- **`db/operations/`** — Async functions that operate on the database. Each function takes an `AsyncSession` as its first argument. Import any CRUD/search/graph operation from here.
- **`agent/`** — LLM agent integration (LangChain/LangGraph). Built once at startup, invoked per chat message with a fresh DB session via `ToolRuntime` context injection.
- **`tui/`** — Textual-based terminal UI. Launch via `uv run python -m rhizome.tui`. Contains the main app, screens, widgets, state management, and slash command routing.

- **`credentials.py`** — Credential resolution module. Checks env vars first (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`), then falls back to `~/.config/rhizome/credentials.json` (mode `0600`). Used by both `agent/config.py` and the TUI setup screen.

Typical usage (programmatic):

```python
from rhizome.db import init_db, get_session_factory
from rhizome.db.operations import create_topic, create_entry

engine = await init_db("my.db")
factory = get_session_factory(engine)
async with factory() as session:
    t = await create_topic(session, name="motions")
    await create_entry(session, topic_id=t.id, title="Word motion", content="w moves forward one word")
    await session.commit()
```
