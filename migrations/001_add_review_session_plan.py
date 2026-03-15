"""Add `plan` column to `review_session` table.

Usage:
    uv run python -m migrations.001_add_review_session_plan [db_path]

Defaults to the app's configured DB path (via ``get_default_db_path``).
An explicit path can be passed as a CLI argument.  Safe to run multiple
times — the migration checks whether the column already exists.
"""

import sqlite3
import sys

from rhizome.config import get_default_db_path


def migrate(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if table exists
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='review_session'"
    )
    if not cursor.fetchone():
        print(f"Table 'review_session' does not exist in {db_path}. Nothing to do.")
        conn.close()
        return

    # Check if column already exists
    cursor.execute("PRAGMA table_info(review_session)")
    columns = {row[1] for row in cursor.fetchall()}

    if "plan" in columns:
        print(f"Column 'plan' already exists in review_session ({db_path}). Nothing to do.")
        conn.close()
        return

    cursor.execute("ALTER TABLE review_session ADD COLUMN plan TEXT")
    conn.commit()
    print(f"Added 'plan' column to review_session ({db_path}).")
    conn.close()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else str(get_default_db_path())
    migrate(path)
