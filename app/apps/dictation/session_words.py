"""Dictation profile sync (SQLite users) + word session (Postgres lexemes)."""

from __future__ import annotations

import re
import sqlite3
from datetime import date

import requests

from app.apps.dictation import database
from app.apps.dictation import dictation_lexemes as lex
from app.apps.dictation.ollama_settings import DICTATION_OLLAMA_MODEL, OLLAMA_GENERATE_URL
from app.core.database import session_scope

_MAX_PROMPT_CANDIDATES = 500


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


def _parse_ollama_word_list(response_text: str) -> list[str]:
    """Extract comma- or line-separated words from model output."""
    t = (response_text or "").strip()
    t = t.replace("\n", " ").replace(";", ",")
    parts: list[str] = []
    for p in t.split(","):
        w = p.strip()
        w = re.sub(r"^[\W\d]+", "", w)
        w = re.sub(r"[\W]+$", "", w)
        w = w.strip()
        if w and w.isalpha():
            parts.append(w.lower())
    return parts


def _ai_pick_from_candidates(
    candidates: set[str], known: set[str], n_new: int, difficulty: int, pool_for_prompt: list[str]
) -> list[str]:
    if not pool_for_prompt or n_new <= 0:
        return []
    pool_text = "\n".join(f"- {w}" for w in pool_for_prompt)
    if len(pool_for_prompt) > _MAX_PROMPT_CANDIDATES:
        # session_words is sync; use deterministic slice for sub-pool (stratify elsewhere).
        pool_text = "\n".join(f"- {w}" for w in pool_for_prompt[:_MAX_PROMPT_CANDIDATES])
    prompt = (
        f"Student spelling skill level: {difficulty} (1=easiest, 10=hardest).\n"
        f"Choose EXACTLY {n_new} different words that appear in the list below. "
        f"Do not invent words. Do not use: {', '.join(sorted(known)) if known else 'none'}.\n"
        f"Output only a comma-separated list, lowercase, nothing else.\n"
        f"---\n{pool_text}\n"
    )
    system = (
        "You are a strict assistant. You only copy words that appear in the user list. "
        "If you output a word that is not in the list, the assignment will fail. "
        "Never add commentary."
    )
    try:
        response = requests.post(
            OLLAMA_GENERATE_URL,
            json={
                "model": DICTATION_OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "system": system,
                "options": {"num_predict": 200, "temperature": 0.2},
            },
            timeout=120,
        )
        response.raise_for_status()
        raw = (response.json().get("response") or "").strip()
    except Exception:
        return []
    picked: list[str] = []
    for w in _parse_ollama_word_list(raw):
        if w in candidates and w not in known and w not in picked:
            picked.append(w)
        if len(picked) >= n_new:
            break
    return picked


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
        known_list = await lex.known_words_for_user(session, user_id)
        due_count = await lex.count_due_for_user(session, user_id)
        unassigned_rows = await lex.list_unassigned_lexeme_rows(session, user_id)

    known_set = {k.lower() for k in known_list if k and str(k).strip()}
    n_new = max(1, min(int(target_daily_words), 50))
    if not unassigned_rows:
        return {
            "due_count": due_count,
            "suggested_words": [],
            "difficulty": difficulty,
            "pool_size": 0,
        }

    by_word: dict[str, int | None] = {}
    for w, d in unassigned_rows:
        if w and w not in by_word:
            by_word[w.lower()] = d

    candidates: set[str] = set(by_word)
    new_words: list[str] = []

    if len(candidates) <= n_new:
        new_words = list(dict.fromkeys(w for w, _d in unassigned_rows if w))
    else:
        if len(candidates) <= 80:
            pool = sorted(candidates)
        else:
            pool = lex.pick_lexemes_stratified(
                [(w, by_word[w]) for w in by_word], min(500, len(candidates)), center_level=difficulty
            )
            for w in sorted(candidates - set(pool)):
                if len(pool) >= 500:
                    break
                pool.append(w)
            pool.sort()
        new_words = _ai_pick_from_candidates(
            candidates,
            known_set,
            n_new,
            difficulty,
            pool[:_MAX_PROMPT_CANDIDATES] if len(pool) > _MAX_PROMPT_CANDIDATES else pool,
        )
        if len(new_words) < n_new:
            need = n_new - len(new_words)
            used = set(new_words) | known_set
            rem_rows = [(w, by_word.get(w)) for w, _d in unassigned_rows if w not in used and w in candidates]
            if rem_rows:
                for w in lex.pick_lexemes_stratified(rem_rows, need, center_level=difficulty):
                    if w not in new_words:
                        new_words.append(w)
                    if len(new_words) >= n_new:
                        break
    return {
        "due_count": due_count,
        "suggested_words": new_words,
        "difficulty": difficulty,
        "pool_size": len(candidates),
    }


async def commit_daily_session_dictation(user_id: int, words: list[str]) -> dict:
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT difficulty_level FROM users WHERE id = ?", (user_id,))
    difficulty = int(cursor.fetchone()["difficulty_level"])
    conn.close()

    async with session_scope() as session:
        assigned = await lex.commit_words_for_user_existing_only(session, user_id, words)
    return {"assigned_count": assigned}
