# curriculum_app/db/

Database layer. Defines the ORM schema and provides async engine/session management.

## Files

- **models.py** — SQLAlchemy ORM models (all use `Mapped`/`mapped_column` typed syntax):
  - `Curriculum` — top-level subject (unique name). Owns topics via cascade delete.
  - `Topic` — sub-area within a curriculum (unique per curriculum). Owns entries via cascade delete.
  - `KnowledgeEntry` — core knowledge unit (fact/concept/definition). Has `title`, `content`, `additional_notes`, `entry_type`, `difficulty` (nullable int), `speed_testable` (bool, default false). Connected to tags (many-to-many) and other entries (directed graph).
  - `Tag` — freeform label (unique, lowercase-normalized).
  - `KnowledgeEntryTag` — junction table for entry-tag many-to-many.
  - `RelatedKnowledgeEntries` — directed edge between two entries with a `relationship_type` (e.g. "depends_on", "example_of"). Has a CHECK constraint preventing self-loops; cycles are prevented at the tool layer.

- **engine.py** — Three functions:
  - `get_engine(db_path)` — creates an `AsyncEngine` using `sqlite+aiosqlite`.
  - `get_session_factory(engine)` — returns an `async_sessionmaker` with `expire_on_commit=False`.
  - `init_db(db_path)` — creates all tables (idempotent) and returns the engine.

## `__init__.py` exports

All 7 model classes, plus `get_engine`, `get_session_factory`, and `init_db`. Import from `curriculum_app.db` directly.
