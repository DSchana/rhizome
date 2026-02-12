# curriculum_app/

Top-level application package. The `__init__.py` is empty — all public API is accessed through the two subpackages:

- **`db/`** — ORM models and async engine/session management. Import models and `init_db`/`get_engine`/`get_session_factory` from here.
- **`tools/`** — Async tool functions that operate on the database. Each function takes an `AsyncSession` as its first argument. Import any CRUD/search/graph operation from here.

Typical usage:

```python
from curriculum_app.db import init_db, get_session_factory
from curriculum_app.tools import create_curriculum, create_topic, search_entries

engine = await init_db("my.db")
factory = get_session_factory(engine)
async with factory() as session:
    c = await create_curriculum(session, name="vim")
    await session.commit()
```

No application entry point exists yet. The planned layers (TUI via Textual, agent via Claude API) will sit above this package and call into `tools/`.
