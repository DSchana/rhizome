"""Application-wide configuration and path resolution."""

import os
from pathlib import Path

import platformdirs

APP_NAME = "curriculum-app"


def get_data_dir() -> Path:
    """Return the OS-appropriate data directory, creating it if needed."""
    path = Path(platformdirs.user_data_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_default_db_path() -> Path:
    """Return the default database path.

    Checks ``CURRICULUM_APP_DB`` env var first, otherwise falls back to
    the platform data directory.
    """
    if env := os.environ.get("CURRICULUM_APP_DB"):
        return Path(env)
    return get_data_dir() / "curriculum.db"
