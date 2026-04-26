import os
import sqlite3

_DATA = os.getenv("DICTATION_DATA_DIR", "/app/data")
DB_PATH = os.path.join(_DATA, "dictation.db")


def _ensure_data_dir() -> None:
    os.makedirs(_DATA, exist_ok=True)


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _ensure_users_core_student_id_column(conn.cursor())
    conn.commit()
    return conn


def init_db():
    """SQLite holds dictation login profiles only; dictionary and word queue live in Postgres."""
    print("Checking SQLite dictation profile table...")
    _ensure_data_dir()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            difficulty_level TEXT DEFAULT 'beginner',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.commit()
    _ensure_users_core_student_id_column(cursor)
    conn.commit()
    conn.close()
    print("Dictation profile database initialized successfully.")


def _ensure_users_core_student_id_column(cursor: sqlite3.Cursor) -> None:
    cursor.execute("PRAGMA table_info(users)")
    columns = {row[1] for row in cursor.fetchall()}
    if "core_student_id" in columns:
        return
    cursor.execute("ALTER TABLE users ADD COLUMN core_student_id TEXT")
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_core_student_id "
        "ON users(core_student_id) WHERE core_student_id IS NOT NULL"
    )
