"""Postgres-backed dictation dictionary (lexemes) and per-user word queue."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import and_, case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import DictationAssignment, DictationAttempt, Lexeme

DEFAULT_LOCALE = "en"


async def get_or_create_lexeme(
    session: AsyncSession,
    canonical_word: str,
    *,
    locale_code: str = DEFAULT_LOCALE,
    difficulty_level: int | None = None,
    definition: str | None = None,
    extensions: dict[str, Any] | None = None,
) -> Lexeme:
    cw = canonical_word.lower().strip()
    if not cw:
        raise ValueError("canonical_word is empty")
    stmt = select(Lexeme).where(
        Lexeme.locale_code == locale_code,
        func.lower(Lexeme.canonical_word) == cw,
    )
    row = await session.scalar(stmt)
    if row:
        if difficulty_level is not None:
            row.difficulty_level = difficulty_level
        if definition is not None:
            row.definition = definition
        if extensions is not None:
            merged = dict(row.extensions or {})
            merged.update(extensions)
            row.extensions = merged
        await session.flush()
        return row

    ext = dict(extensions or {})
    lex = Lexeme(
        locale_code=locale_code,
        canonical_word=cw,
        display_word=canonical_word.strip(),
        difficulty_level=difficulty_level,
        definition=definition,
        extensions=ext,
    )
    session.add(lex)
    await session.flush()
    return lex


async def list_lexemes_review_page(
    session: AsyncSession,
    *,
    locale_code: str = DEFAULT_LOCALE,
    q: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """Paginated dictionary browse; optional case-insensitive substring match on canonical_word."""
    filt: list[Any] = [Lexeme.locale_code == locale_code]
    if q and q.strip():
        filt.append(func.lower(Lexeme.canonical_word).like(f"%{q.strip().lower()}%"))
    where_expr = and_(*filt)

    total = int(
        await session.scalar(select(func.count()).select_from(Lexeme).where(where_expr)) or 0
    )

    result = await session.scalars(
        select(Lexeme)
        .where(where_expr)
        .order_by(Lexeme.canonical_word.asc())
        .offset(max(0, offset))
        .limit(min(500, max(1, limit)))
    )
    rows = list(result)
    items = [
        {
            "id": str(r.id),
            "word": r.canonical_word,
            "display_word": r.display_word,
            "difficulty_level": r.difficulty_level,
            "definition": r.definition or "",
            "extensions": r.extensions or {},
        }
        for r in rows
    ]
    return items, total


async def list_lexemes_for_admin(session: AsyncSession, locale_code: str = DEFAULT_LOCALE) -> list[dict[str, Any]]:
    result = await session.scalars(
        select(Lexeme)
        .where(Lexeme.locale_code == locale_code)
        .order_by(Lexeme.canonical_word.asc())
    )
    rows = list(result)
    return [
        {
            "id": str(r.id),
            "word": r.canonical_word,
            "difficulty_level": r.difficulty_level,
            "definition": r.definition or "",
            "extensions": r.extensions or {},
        }
        for r in rows
    ]


async def update_lexeme_fields(
    session: AsyncSession,
    lexeme_id: uuid.UUID,
    *,
    difficulty_level: int | None = None,
    definition: str | None = None,
    extensions: dict[str, Any] | None = None,
) -> None:
    lex = await session.get(Lexeme, lexeme_id)
    if not lex:
        return
    if difficulty_level is not None:
        lex.difficulty_level = difficulty_level
    if definition is not None:
        lex.definition = definition
    if extensions is not None:
        merged = dict(lex.extensions or {})
        merged.update(extensions)
        lex.extensions = merged
    await session.flush()


async def get_definition_for_word(session: AsyncSession, word: str, locale_code: str = DEFAULT_LOCALE) -> str | None:
    cw = word.lower().strip()
    stmt = select(Lexeme.definition).where(
        Lexeme.locale_code == locale_code,
        func.lower(Lexeme.canonical_word) == cw,
    )
    return await session.scalar(stmt)


async def bulk_upsert_lexemes_from_rows(
    session: AsyncSession,
    rows: list[dict[str, Any]],
    locale_code: str = DEFAULT_LOCALE,
) -> int:
    """rows: dicts with word, difficulty_level, definition (CSV-style). Returns rows processed."""
    n = 0
    for row in rows:
        w = (row.get("word") or "").lower().strip()
        if not w:
            continue
        try:
            lvl = int(row.get("difficulty_level", 1))
        except (TypeError, ValueError):
            lvl = 1
        defn = (row.get("definition") or "").strip() or None
        await get_or_create_lexeme(
            session,
            w,
            locale_code=locale_code,
            difficulty_level=lvl,
            definition=defn,
        )
        n += 1
    return n


async def assign_word_to_user(
    session: AsyncSession,
    dictation_user_id: int,
    word: str,
    *,
    difficulty_level: int = 1,
    definition: str = "",
    locale_code: str = DEFAULT_LOCALE,
) -> None:
    clean = word.lower().strip()
    lex = await get_or_create_lexeme(
        session,
        clean,
        locale_code=locale_code,
        difficulty_level=difficulty_level,
        definition=definition.strip() or None,
    )
    exists = await session.scalar(
        select(DictationAssignment.id).where(
            DictationAssignment.dictation_user_id == dictation_user_id,
            DictationAssignment.lexeme_id == lex.id,
        )
    )
    if exists:
        return
    session.add(
        DictationAssignment(
            dictation_user_id=dictation_user_id,
            lexeme_id=lex.id,
            interval=0,
            correct_streak=0,
            next_review_date=date.today(),
        )
    )
    await session.flush()


async def list_due_words(
    session: AsyncSession, dictation_user_id: int, today: date | None = None
) -> list[dict[str, Any]]:
    today = today or date.today()
    stmt = (
        select(DictationAssignment, Lexeme)
        .join(Lexeme, DictationAssignment.lexeme_id == Lexeme.id)
        .where(
            DictationAssignment.dictation_user_id == dictation_user_id,
            DictationAssignment.next_review_date <= today,
        )
    )
    result = await session.execute(stmt)
    out: list[dict[str, Any]] = []
    for da, lex in result.all():
        out.append(
            {
                "assignment_id": str(da.id),
                "word": lex.canonical_word,
                "definition": lex.definition or "",
                "interval": da.interval,
                "correct_streak": da.correct_streak,
            }
        )
    return out


async def get_assignment_for_word(
    session: AsyncSession, dictation_user_id: int, canonical_word: str
) -> tuple[DictationAssignment, uuid.UUID] | None:
    cw = canonical_word.lower().strip()
    stmt = (
        select(DictationAssignment, Lexeme.id)
        .join(Lexeme, DictationAssignment.lexeme_id == Lexeme.id)
        .where(
            DictationAssignment.dictation_user_id == dictation_user_id,
            func.lower(Lexeme.canonical_word) == cw,
        )
    )
    row = (await session.execute(stmt)).first()
    if not row:
        return None
    return row[0], row[1]


async def update_assignment_after_grade(
    session: AsyncSession,
    assignment_id: uuid.UUID,
    *,
    interval: int,
    correct_streak: int,
    next_review_date: date,
) -> None:
    await session.execute(
        update(DictationAssignment)
        .where(DictationAssignment.id == assignment_id)
        .values(interval=interval, correct_streak=correct_streak, next_review_date=next_review_date)
    )


async def insert_attempt(
    session: AsyncSession,
    dictation_user_id: int,
    lexeme_id: uuid.UUID,
    is_correct: bool,
    attempt_date: date | None = None,
) -> None:
    session.add(
        DictationAttempt(
            dictation_user_id=dictation_user_id,
            lexeme_id=lexeme_id,
            is_correct=is_correct,
            attempt_date=attempt_date or date.today(),
        )
    )


async def known_words_for_user(session: AsyncSession, dictation_user_id: int) -> list[str]:
    stmt = select(Lexeme.canonical_word).join(
        DictationAssignment, DictationAssignment.lexeme_id == Lexeme.id
    ).where(DictationAssignment.dictation_user_id == dictation_user_id)
    rows = await session.scalars(stmt)
    return list(rows)


async def count_due_for_user(session: AsyncSession, dictation_user_id: int, today: date | None = None) -> int:
    today = today or date.today()
    stmt = select(func.count()).select_from(DictationAssignment).where(
        DictationAssignment.dictation_user_id == dictation_user_id,
        DictationAssignment.next_review_date <= today,
    )
    return int(await session.scalar(stmt) or 0)


async def commit_words_for_user(
    session: AsyncSession,
    dictation_user_id: int,
    words: list[str],
    difficulty_level: int,
    locale_code: str = DEFAULT_LOCALE,
) -> int:
    return await _count_assignments_added(
        session, dictation_user_id, words, difficulty_level, locale_code
    )


async def _count_assignments_added(
    session: AsyncSession,
    dictation_user_id: int,
    words: list[str],
    difficulty_level: int,
    locale_code: str,
) -> int:
    """Insert words and return how many new assignment rows were created."""
    assigned = 0
    for raw in words:
        clean = raw.lower().strip()
        if not clean:
            continue
        lex = await get_or_create_lexeme(
            session, clean, locale_code=locale_code, difficulty_level=difficulty_level
        )
        chk = await session.scalar(
            select(DictationAssignment.id).where(
                DictationAssignment.dictation_user_id == dictation_user_id,
                DictationAssignment.lexeme_id == lex.id,
            )
        )
        if chk:
            continue
        session.add(
            DictationAssignment(
                dictation_user_id=dictation_user_id,
                lexeme_id=lex.id,
                interval=0,
                correct_streak=0,
                next_review_date=date.today(),
            )
        )
        assigned += 1
    await session.flush()
    return assigned


async def progress_report(session: AsyncSession, dictation_user_id: int) -> list[dict[str, Any]]:
    stmt = (
        select(
            DictationAttempt.attempt_date,
            func.count().label("total_attempts"),
            func.sum(case((DictationAttempt.is_correct.is_(True), 1), else_=0)).label("correct_attempts"),
        )
        .where(DictationAttempt.dictation_user_id == dictation_user_id)
        .group_by(DictationAttempt.attempt_date)
        .order_by(DictationAttempt.attempt_date.desc())
    )
    rows = (await session.execute(stmt)).all()
    report = []
    for attempt_date, total, correct in rows:
        total = int(total or 0)
        correct = int(correct or 0)
        pct = round((correct / total) * 100) if total else 0
        report.append(
            {
                "date": attempt_date.isoformat() if hasattr(attempt_date, "isoformat") else str(attempt_date),
                "score": f"{correct}/{total}",
                "accuracy_percent": pct,
            }
        )
    return report
