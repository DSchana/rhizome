# rhizome/

Top-level application package. The `__init__.py` is empty — all public API is accessed through the subpackages:

- **`db/`** — ORM models and async engine/session management. Import models and `init_db`/`get_engine`/`get_session_factory` from here.
- **`tools/`** — Async tool functions that operate on the database. Each function takes an `AsyncSession` as its first argument. Import any CRUD/search/graph operation from here.
- **`agent/`** — LLM agent integration (LangChain/LangGraph). Built once at startup, invoked per chat message with a fresh DB session via `ToolRuntime` context injection.
- **`tui/`** — Textual-based terminal UI. Launch via `uv run python -m rhizome.tui`. Contains the main app, screens, widgets, state management, and slash command routing.

Typical usage (programmatic):

```python
from rhizome.db import init_db, get_session_factory
from rhizome.tools import create_curriculum, create_topic, add_topic_to_curriculum

engine = await init_db("my.db")
factory = get_session_factory(engine)
async with factory() as session:
    c = await create_curriculum(session, name="vim")
    t = await create_topic(session, name="motions")
    await add_topic_to_curriculum(session, curriculum_id=c.id, topic_id=t.id, position=0)
    await session.commit()
```
