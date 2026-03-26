from pathlib import Path

from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from rhizome.logs import get_logger
from .models import Base

_logger = get_logger("db")


def get_engine(db_path: str | Path = "rhizome.db") -> AsyncEngine:
    """Create an async SQLite engine pointing at *db_path*.

    Registers a ``connect`` event listener that enables SQLite foreign key
    enforcement (``PRAGMA foreign_keys = ON``) on every new DBAPI connection.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    _logger.info("Engine created for %s (foreign_keys=ON)", db_path)
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


# -- Cascade migration -------------------------------------------------------

# Tables with FK columns, listed in dependency order (parents before children).
# Only these tables need to be recreated to add ON DELETE CASCADE/SET NULL.
_FK_TABLES_ORDERED = [
    "topic",
    "knowledge_entry",
    "knowledge_entry_tag",
    "related_knowledge_entries",
    "review_session_topic",
    "review_session_entry",
    "flashcard",
    "flashcard_entry",
    "review_interaction",
    "review_interaction_entry",
]


def _needs_cascade_migration(connection) -> bool:
    """Check if any FK constraint has incorrect ON DELETE action.

    Returns True when any FK lacks an ON DELETE rule (NO ACTION) or when
    the flashcard.session_id FK uses CASCADE instead of SET NULL.
    """
    result = connection.execute(text(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ))
    tables = [r[0] for r in result]
    for table in tables:
        fk_result = connection.execute(text(f"PRAGMA foreign_key_list(\"{table}\")"))
        for row in fk_result:
            # (id, seq, table, from, to, on_update, on_delete, match)
            on_delete = row[6]
            if on_delete in ("NO ACTION", "", None):
                return True
            # flashcard.session_id should be SET NULL, not CASCADE
            if table == "flashcard" and row[2] == "review_session" and on_delete != "SET NULL":
                return True
    return False


def _migrate_add_cascades(connection) -> None:
    """Recreate tables to add ON DELETE CASCADE/SET NULL constraints.

    SQLite does not support ALTER TABLE to change FK constraints, so we
    must recreate affected tables with a rename-create-copy-drop cycle.
    Data is fully preserved.  This runs with FK enforcement OFF (the
    SQLite default) to avoid constraint violations during the swap.
    """
    if not _needs_cascade_migration(connection):
        return

    _logger.info("Migrating tables to add ON DELETE CASCADE/SET NULL constraints")

    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())
    tables_to_migrate = [t for t in _FK_TABLES_ORDERED if t in existing_tables]

    if not tables_to_migrate:
        return

    # Step 1a: Collect indexes that will conflict after rename
    indexes_to_drop: list[str] = []
    for table in tables_to_migrate:
        result = connection.execute(text(f'PRAGMA index_list("{table}")'))
        for row in result:
            idx_name = row[1]
            if not idx_name.startswith("sqlite_autoindex"):
                indexes_to_drop.append(idx_name)

    # Step 1b: Rename existing tables
    for table in reversed(tables_to_migrate):
        connection.execute(text(f'ALTER TABLE "{table}" RENAME TO "_old_{table}"'))
        _logger.info("Renamed %s -> _old_%s", table, table)

    # Step 1c: Drop old indexes (they followed the rename but names conflict)
    for idx_name in indexes_to_drop:
        connection.execute(text(f'DROP INDEX IF EXISTS "{idx_name}"'))

    # Step 2: Create new tables from current model definitions (with ondelete=)
    Base.metadata.create_all(connection, tables=[
        Base.metadata.tables[t] for t in tables_to_migrate
    ])

    # Step 3: Copy data from old tables to new tables
    for table in tables_to_migrate:
        new_cols = [c.name for c in Base.metadata.tables[table].columns]
        # Only copy columns that exist in both old and new tables
        old_inspector = inspect(connection)
        old_cols = {c["name"] for c in old_inspector.get_columns(f"_old_{table}")}
        common = [c for c in new_cols if c in old_cols]
        col_list = ", ".join(f'"{c}"' for c in common)
        connection.execute(text(
            f'INSERT INTO "{table}" ({col_list}) SELECT {col_list} FROM "_old_{table}"'
        ))
        _logger.info("Copied data for %s (%d columns)", table, len(common))

    # Step 4: Drop old tables
    for table in reversed(tables_to_migrate):
        connection.execute(text(f'DROP TABLE "_old_{table}"'))
        _logger.info("Dropped _old_%s", table)

    _logger.info("Cascade migration complete")


async def init_db(db_path: str | Path = "rhizome.db") -> AsyncEngine:
    """Create all tables and return the engine.

    Intended for first-run setup.  Safe to call repeatedly — SQLAlchemy's
    ``create_all`` is a no-op for tables that already exist.

    Runs three migration phases:
    1. ``_migrate_review_tables`` — drop/recreate review tables with missing columns
    2. ``create_all`` — create any missing tables
    3. ``_migrate_add_cascades`` — recreate FK tables to add ON DELETE CASCADE/SET NULL

    The cascade migration requires FK enforcement OFF (so renamed tables
    don't trigger constraint errors), so it runs on a temporary engine
    without the PRAGMA listener.  The returned engine has FK enforcement ON.
    """
    # Phase 1-3: migrations run with FK enforcement OFF (no PRAGMA listener)
    migration_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", echo=False
    )
    async with migration_engine.begin() as conn:
        await conn.run_sync(_migrate_review_tables)
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_add_cascades)
    await migration_engine.dispose()

    # Production engine with FK enforcement ON
    engine = get_engine(db_path)
    _logger.info("Database tables initialized")
    return engine
