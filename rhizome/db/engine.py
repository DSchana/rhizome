from pathlib import Path

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


async def init_db(db_path: str | Path = "curriculum.db") -> AsyncEngine:
    """Create all tables and return the engine.

    Intended for first-run setup.  Safe to call repeatedly — SQLAlchemy's
    ``create_all`` is a no-op for tables that already exist.
    """
    engine = get_engine(db_path)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    _logger.info("Database tables initialized")
    return engine
