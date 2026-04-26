"""SQLite-backed spelling word session helpers (used by core admin API)."""

from __future__ import annotations

import os
import sqlite3
from datetime import date

import requests

from app.apps.dictation import database

OLLAMA_GENERATE_URL = os.getenv(
    "OLLAMA_GENERATE_URL",
    f"{os.getenv('OLLAMA_BASE_URL', 'http://host.docker.internal:11434').rstrip('/')}/api/generate",
)
DICTATION_OLLAMA_MODEL = os.getenv("DICTATION_OLLAMA_MODEL", "gemma4:e4b")


def ensure_dictation_user(core_student_id: str, display_name: str, difficulty_level: int) -> int:
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE core_student_id = ?", (core_student_id,))
    row = cursor.fetchone()
    if row:
        uid = int(row["id"])
        cursor.execute(
            "UPDATE users SET name = ?, difficulty_level = ? WHERE id = ?",
            (display_name, str(difficulty_level), uid),
        )
        conn.commit()
        conn.close()
        return uid
    try:
        cursor.execute(
            "INSERT INTO users (name, difficulty_level, core_student_id) VALUES (?, ?, ?)",
            (display_name, str(difficulty_level), core_student_id),
        )
        conn.commit()
        uid = int(cursor.lastrowid)
        conn.close()
        return uid
    except sqlite3.IntegrityError:
        conn.rollback()
        cursor.execute("SELECT id FROM users WHERE name = ?", (display_name,))
        r2 = cursor.fetchone()
        if not r2:
            conn.close()
            raise
        uid = int(r2["id"])
        cursor.execute(
            "UPDATE users SET difficulty_level = ?, core_student_id = ? WHERE id = ?",
            (str(difficulty_level), core_student_id, uid),
        )
        conn.commit()
        conn.close()
        return uid


def draft_daily_session_dictation(user_id: int, target_daily_words: int) -> dict:
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT difficulty_level FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError("Dictation user not found")
    difficulty = int(row["difficulty_level"])

    cursor.execute(
        "SELECT w.word FROM user_words uw JOIN words w ON uw.word_id = w.id WHERE uw.user_id = ?",
        (user_id,),
    )
    known_words = [r["word"] for r in cursor.fetchall()]

    cursor.execute(
        "SELECT count(*) as count FROM user_words WHERE user_id = ? AND next_review_date <= ?",
        (user_id, date.today().isoformat()),
    )
    due_count = cursor.fetchone()["count"]

    shortfall = target_daily_words - due_count
    new_words: list[str] = []

    if shortfall > 0:
        known_str = ", ".join(known_words) if known_words else "none"
        prompt = (
            f"You are an elementary spelling teacher. Generate a comma-separated list of EXACTLY {shortfall} "
            f"new spelling words appropriate for a student at skill level {difficulty} out of 10 "
            "(where 1 means basic 3-letter words and 10 means advanced middle-school words). "
            f"DO NOT use any of these words: {known_str}. Output ONLY the comma-separated words, nothing else."
        )
        response = requests.post(
            OLLAMA_GENERATE_URL,
            json={"model": DICTATION_OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120,
        )
        response.raise_for_status()
        new_words = [w.strip().lower() for w in response.json()["response"].split(",") if w.strip()]

    conn.close()
    return {"due_count": due_count, "suggested_words": new_words, "difficulty": difficulty}


def commit_daily_session_dictation(user_id: int, words: list[str]) -> dict:
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT difficulty_level FROM users WHERE id = ?", (user_id,))
    difficulty = int(cursor.fetchone()["difficulty_level"])

    assigned_count = 0
    for raw in words:
        clean_word = raw.lower().strip()
        if not clean_word:
            continue
        cursor.execute(
            "INSERT OR IGNORE INTO words (word, difficulty_level) VALUES (?, ?)",
            (clean_word, difficulty),
        )
        cursor.execute("SELECT id FROM words WHERE word = ?", (clean_word,))
        word_id = int(cursor.fetchone()["id"])
        try:
            cursor.execute("INSERT INTO user_words (user_id, word_id) VALUES (?, ?)", (user_id, word_id))
            assigned_count += 1
        except sqlite3.IntegrityError:
            pass

    conn.commit()
    conn.close()
    return {"assigned_count": assigned_count}
