# Work Report: Database Schema Implementation

## What was built

The database layer for curriculum-app — four new Python files that define how your data is structured and stored in SQLite.

### New files

| File | Purpose |
|---|---|
| `curriculum_app/__init__.py` | Makes `curriculum_app` a Python package (empty file, but required) |
| `curriculum_app/db/__init__.py` | Makes `curriculum_app.db` a package and re-exports everything so you can write `from curriculum_app.db import Curriculum` |
| `curriculum_app/db/models.py` | Defines the 6 database tables as Python classes |
| `curriculum_app/db/engine.py` | Creates the database connection and can set up the tables on first run |

### Modified files

| File | Change |
|---|---|
| `pyproject.toml` | Added `sqlalchemy[asyncio]` and `aiosqlite` as dependencies |

---

## How SQLAlchemy models work (beginner summary)

SQLAlchemy lets you define database tables as regular Python classes. Each class maps to one table, and each attribute maps to a column. This is called an **ORM** (Object-Relational Mapper) — it translates between Python objects and SQL rows so you rarely need to write raw SQL.

### The modern typed style (SQLAlchemy 2.x)

The models use SQLAlchemy's modern syntax:

```python
class Curriculum(Base):
    __tablename__ = "curriculum"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
```

Here's what each piece means:

- **`Base`** — all models inherit from this. It's what tells SQLAlchemy "this class is a table".
- **`__tablename__`** — the actual SQL table name.
- **`Mapped[int]`** — a type hint that says "this column holds an integer". SQLAlchemy uses these for type checking and editor autocomplete.
- **`mapped_column(...)`** — defines the column's SQL properties (primary key, nullable, unique, etc.).

### Relationships

Relationships let you navigate between related objects in Python without writing JOIN queries:

```python
# On Topic:
entries: Mapped[list["KnowledgeEntry"]] = relationship(back_populates="topic")

# On KnowledgeEntry:
topic: Mapped["Topic"] = relationship(back_populates="entries")
```

With this, you can do `topic.entries` to get all knowledge entries for a topic, or `entry.topic` to get the topic an entry belongs to. SQLAlchemy handles the SQL behind the scenes.

### The 6 tables at a glance

```
Curriculum  1──*  Topic  1──*  KnowledgeEntry  *──*  Tag
                                      │
                                      │ (RelatedKnowledgeEntries)
                                      ▼
                               KnowledgeEntry
```

1. **Curriculum** — a subject area like "vim" or "AWS"
2. **Topic** — a sub-area within a curriculum, like "vim motions"
3. **KnowledgeEntry** — a single piece of knowledge (fact, concept, or definition)
4. **Tag** — a freeform label that can be applied across entries
5. **KnowledgeEntryTag** — the junction table that connects entries to tags (many-to-many)
6. **RelatedKnowledgeEntries** — directed edges between entries (e.g., "A depends on B")

### The engine and sessions

`engine.py` provides three things:

- **`get_engine(db_path)`** — creates a connection to the SQLite database file. Uses `aiosqlite` so everything is async (non-blocking).
- **`get_session_factory(engine)`** — returns a factory that creates sessions. A **session** is like a conversation with the database: you open one, do some reads/writes, then close it.
- **`init_db(db_path)`** — creates all the tables in the database. Safe to call multiple times; it won't touch tables that already exist.

### Async — what does that mean here?

The database uses Python's `async`/`await` syntax. This means database calls don't block the rest of your program while waiting for SQLite to respond. You'll interact with it like:

```python
async with session_factory() as session:
    result = await session.execute(select(Curriculum))
    curricula = result.scalars().all()
```

This matters because the app will eventually run a TUI (Textual) and an LLM agent, both of which benefit from non-blocking I/O.

---

## How to verify it works

```bash
uv sync                          # install the new dependencies
uv run python -c "
import asyncio
from curriculum_app.db import init_db
asyncio.run(init_db('test.db'))
print('Database created successfully')
"
# Then inspect the file:
sqlite3 test.db ".tables"        # should list all 6 tables
rm test.db                       # clean up
```
