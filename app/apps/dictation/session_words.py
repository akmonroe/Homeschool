"""Dictation profile sync (SQLite users) + word session (Postgres lexemes)."""

from __future__ import annotations

import sqlite3
from datetime import date

import requests

from app.apps.dictation import database
from app.apps.dictation import dictation_lexemes as lex
from app.apps.dictation.ollama_settings import DICTATION_OLLAMA_MODEL, OLLAMA_GENERATE_URL
from app.core.database import session_scope


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


async def draft_daily_session_dictation(user_id: int, target_daily_words: int) -> dict:
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT difficulty_level FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise ValueError("Dictation user not found")
    difficulty = int(row["difficulty_level"])

    async with session_scope() as session:
        known = await lex.known_words_for_user(session, user_id)
        due_count = await lex.count_due_for_user(session, user_id)

    # How many brand-new words to ask the model for (same as admin "target" count).
    # NOTE: We intentionally do NOT subtract due_count. Legacy logic used
    # shortfall = target - due_count which blocked all suggestions whenever the student
    # already had more due words than the target (e.g. 19 due vs 10 target → 0 new words).
    n_new = max(1, min(int(target_daily_words), 50))
    new_words: list[str] = []

    if n_new > 0:
        known_str = ", ".join(known) if known else "none"
        prompt = (
            f"You are an elementary spelling teacher. Generate a comma-separated list of EXACTLY {n_new} "
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

    return {"due_count": due_count, "suggested_words": new_words, "difficulty": difficulty}


async def commit_daily_session_dictation(user_id: int, words: list[str]) -> dict:
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT difficulty_level FROM users WHERE id = ?", (user_id,))
    difficulty = int(cursor.fetchone()["difficulty_level"])
    conn.close()

    async with session_scope() as session:
        assigned = await lex.commit_words_for_user(session, user_id, words, difficulty)
    return {"assigned_count": assigned}
