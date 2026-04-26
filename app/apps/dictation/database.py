import os
import sqlite3
from datetime import date

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
    print("Checking SQLite database tables...")
    _ensure_data_dir()
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. The Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            difficulty_level TEXT DEFAULT 'beginner',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 2. The Master Dictionary Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT UNIQUE NOT NULL,
            difficulty_level TEXT DEFAULT 'beginner',
            definition TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 3. The Progress Tracker (Assigned Words)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            word_id INTEGER NOT NULL,
            interval INTEGER DEFAULT 0,
            correct_streak INTEGER DEFAULT 0,
            next_review_date DATE DEFAULT CURRENT_DATE,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(word_id) REFERENCES words(id),
            UNIQUE(user_id, word_id) 
        )
    ''')

    # 4. The Gradebook (History Tracker)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            word_id INTEGER NOT NULL,
            is_correct BOOLEAN NOT NULL,
            attempt_date DATE DEFAULT CURRENT_DATE,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(word_id) REFERENCES words(id)
        )
    ''')

    
    conn.commit()

    _ensure_users_core_student_id_column(cursor)
    conn.commit()
    conn.close()
    print("Database initialized successfully.")


def _ensure_users_core_student_id_column(cursor: sqlite3.Cursor) -> None:
    """SQLite cannot always add UNIQUE in one ALTER; migrate explicitly for existing DBs."""
    cursor.execute("PRAGMA table_info(users)")
    columns = {row[1] for row in cursor.fetchall()}
    if "core_student_id" in columns:
        return
    # Avoid UNIQUE on ALTER — it fails on some SQLite builds; enforce with a partial index instead.
    cursor.execute("ALTER TABLE users ADD COLUMN core_student_id TEXT")
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_core_student_id "
        "ON users(core_student_id) WHERE core_student_id IS NOT NULL"
    )
