"""Change flashcard.session_id ON DELETE from CASCADE to SET NULL.

Usage:
    uv run python -m migrations.002_flashcard_session_set_null [db_path]

Defaults to the app's configured DB path (via ``get_default_db_path``).
An explicit path can be passed as a CLI argument.  Safe to run multiple
times — the migration checks the current FK action before proceeding.

Since SQLite does not support ALTER TABLE to change FK constraints, the
flashcard table is recreated via a rename-create-copy-drop cycle.
"""

import sqlite3
import sys

from rhizome.config import get_default_db_path


def migrate(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if flashcard table exists
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='flashcard'"
    )
    if not cursor.fetchone():
        print(f"Table 'flashcard' does not exist in {db_path}. Nothing to do.")
        conn.close()
        return

    # Check current FK action on session_id
    cursor.execute("PRAGMA foreign_key_list(flashcard)")
    for row in cursor.fetchall():
        # (id, seq, table, from, to, on_update, on_delete, match)
        if row[2] == "review_session" and row[6] == "SET NULL":
            print(f"flashcard.session_id already uses SET NULL ({db_path}). Nothing to do.")
            conn.close()
            return

    # Disable FK enforcement during migration
    cursor.execute("PRAGMA foreign_keys = OFF")

    # Collect existing column info for the copy
    cursor.execute("PRAGMA table_info(flashcard)")
    columns = [row[1] for row in cursor.fetchall()]
    col_list = ", ".join(columns)

    cursor.execute("BEGIN")
    cursor.execute("ALTER TABLE flashcard RENAME TO _old_flashcard")

    # Drop indexes that followed the rename (they'd conflict with new table)
    cursor.execute("PRAGMA index_list(_old_flashcard)")
    for row in cursor.fetchall():
        idx_name = row[1]
        if not idx_name.startswith("sqlite_autoindex"):
            cursor.execute(f'DROP INDEX IF EXISTS "{idx_name}"')

    cursor.execute("""
        CREATE TABLE flashcard (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER REFERENCES review_session(id) ON DELETE SET NULL,
            topic_id INTEGER NOT NULL REFERENCES topic(id) ON DELETE CASCADE,
            question_text TEXT NOT NULL,
            answer_text TEXT NOT NULL,
            testing_notes TEXT
        )
    """)
    cursor.execute("CREATE INDEX ix_flashcard_session_id ON flashcard (session_id)")
    cursor.execute("CREATE INDEX ix_flashcard_topic_id ON flashcard (topic_id)")
    cursor.execute(f"INSERT INTO flashcard ({col_list}) SELECT {col_list} FROM _old_flashcard")
    cursor.execute("DROP TABLE _old_flashcard")

    conn.commit()
    cursor.execute("PRAGMA foreign_keys = ON")
    print(f"Changed flashcard.session_id to ON DELETE SET NULL ({db_path}).")
    conn.close()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else str(get_default_db_path())
    migrate(path)
