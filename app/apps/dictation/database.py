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
    conn.close()
    print("Database initialized successfully.")
