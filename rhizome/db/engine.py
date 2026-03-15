from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from rhizome.logs import get_logger
from .models import Base

_logger = get_logger("db")


def get_engine(db_path: str | Path = "curriculum.db") -> AsyncEngine:
    """Create an async SQLite engine pointing at *db_path*."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    _logger.info("Engine created for %s", db_path)
    return engine


def get_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    """Return a session factory bound to *engine*."""
    return async_sessionmaker(engine, expire_on_commit=False)


def _migrate_review_tables(connection) -> None:
    """Drop and recreate review/flashcard tables if their schema is outdated.

    These tables were created before several columns were added (e.g.
    ``review_session.ephemeral``, ``flashcard.session_id``).  Since
    ``create_all`` only creates missing tables (not columns), we detect
    stale schemas and recreate them.  This is safe because the review
    system was not yet functional when these tables were first created,
    so they contain no user data.
    """
    inspector = inspect(connection)
    tables_to_check = {
        "review_session": {"ephemeral", "created_at", "additional_args", "user_instructions", "final_summary"},
        "review_interaction": {"flashcard_id"},
        "flashcard": {"session_id"},
    }

    # The full set of review/flashcard tables that should be dropped
    # together (FK dependencies require specific order).
    review_tables = [
        "review_interaction_entry",
        "review_interaction",
        "review_session_entry",
        "review_session_topic",
        "flashcard_entry",
        "flashcard",
        "review_session",
    ]

    needs_recreate = False
    for table_name, required_cols in tables_to_check.items():
        if not inspector.has_table(table_name):
            continue
        existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
        missing = required_cols - existing_cols
        if missing:
            _logger.info(
                "Table %s is missing columns %s — will recreate review tables",
                table_name, missing,
            )
            needs_recreate = True
            break

    if not needs_recreate:
        return

    for table_name in review_tables:
        if inspector.has_table(table_name):
            connection.execute(text(f"DROP TABLE {table_name}"))
            _logger.info("Dropped outdated table: %s", table_name)


async def init_db(db_path: str | Path = "curriculum.db") -> AsyncEngine:
    """Create all tables and return the engine.

    Intended for first-run setup.  Safe to call repeatedly — SQLAlchemy's
    ``create_all`` is a no-op for tables that already exist.

    Also runs lightweight schema migrations for review/flashcard tables
    that may have been created with an older schema.
    """
    engine = get_engine(db_path)
    async with engine.begin() as conn:
        await conn.run_sync(_migrate_review_tables)
        await conn.run_sync(Base.metadata.create_all)
    _logger.info("Database tables initialized")
    return engine
