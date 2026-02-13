# curriculum_app/

Top-level application package. The `__init__.py` is empty — all public API is accessed through the subpackages:

- **`db/`** — ORM models and async engine/session management. Import models and `init_db`/`get_engine`/`get_session_factory` from here.
- **`tools/`** — Async tool functions that operate on the database. Each function takes an `AsyncSession` as its first argument. Import any CRUD/search/graph operation from here.
- **`tui/`** — Textual-based terminal UI. Launch via `uv run python -m curriculum_app.tui`. Contains the main app, screens, widgets, state management, and slash command routing.

Typical usage (programmatic):

```python
from curriculum_app.db import init_db, get_session_factory
from curriculum_app.tools import create_curriculum, create_topic, search_entries

engine = await init_db("my.db")
factory = get_session_factory(engine)
async with factory() as session:
    c = await create_curriculum(session, name="vim")
    await session.commit()
```
