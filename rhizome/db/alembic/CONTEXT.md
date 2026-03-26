# rhizome/db/alembic/

Alembic migration environment for the rhizome database.

## Files

- **env.py** — Migration runner configuration. Uses async SQLAlchemy with `render_as_batch=True` (required for SQLite, which doesn't support most `ALTER TABLE` operations). Points `target_metadata` at `Base.metadata` for autogenerate support.
- **script.py.mako** — Template for generating new migration files.
- **versions/** — Ordered migration scripts. Each has a `revision` ID and `down_revision` pointer forming a chain. `alembic_version` table in the DB tracks the current position.

## Usage

```bash
# Apply all pending migrations
uv run alembic upgrade head

# Generate a new migration from model changes
uv run alembic revision --autogenerate -m "description"

# Check current revision
uv run alembic current
```

Programmatically, `init_db()` in `engine.py` calls `run_migrations()` which runs `alembic upgrade head` against the specified DB path.

## Config

`alembic.ini` lives at the repo root. The `sqlalchemy.url` there is a fallback for CLI use; `run_migrations()` overrides it programmatically with the actual DB path.
