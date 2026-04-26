import re
from datetime import date, timedelta
from typing import Annotated

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.apps.dictation import dictation_lexemes as lex
from app.core.deps import get_core_pg_session

OLLAMA_GENERATE_URL = __import__("os").getenv(
    "OLLAMA_GENERATE_URL",
    f"{__import__('os').getenv('OLLAMA_BASE_URL', 'http://host.docker.internal:11434').rstrip('/')}/api/generate",
)
DICTATION_OLLAMA_MODEL = __import__("os").getenv("DICTATION_OLLAMA_MODEL", "gemma4:e4b")

router = APIRouter(tags=["Study & Curriculum"])

SessionDep = Annotated[AsyncSession, Depends(get_core_pg_session)]


class WordAdd(BaseModel):
    word: str
    difficulty_level: int = 1
    definition: str = ""


class GradeRequest(BaseModel):
    target_word: str
    user_input: str


@router.post("/users/{user_id}/words")
async def assign_word_to_user(user_id: int, word_data: WordAdd, session: SessionDep):
    clean_word = word_data.word.lower().strip()
    try:
        await lex.assign_word_to_user(
            session,
            user_id,
            clean_word,
            difficulty_level=word_data.difficulty_level,
            definition=word_data.definition,
        )
        return {"status": "success", "message": f"Assigned '{clean_word}'."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/users/{user_id}/words/due")
async def get_due_words(user_id: int, session: SessionDep):
    try:
        due = await lex.list_due_words(session, user_id)
        return {"status": "success", "count": len(due), "due_words": due}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/users/{user_id}/grade")
async def grade_dictation(user_id: int, request: GradeRequest, session: SessionDep):
    clean_target = request.target_word.lower().strip()
    words_in_input = re.findall(r"\b\w+\b", request.user_input.lower())
    is_correct = clean_target in words_in_input

    try:
        row = await lex.get_assignment_for_word(session, user_id, clean_target)
        if not row:
            raise HTTPException(status_code=404, detail="Word not assigned or not found.")
        assignment, lexeme_id = row

        new_streak = assignment.correct_streak + 1 if is_correct else 0
        new_interval = 1 if new_streak <= 1 else assignment.interval * 2 if is_correct else 1

        if is_correct:
            ai_feedback = "Great job! You spelled it perfectly."
        else:
            prompt = (
                f"A student was doing a spelling dictation. They were supposed to spell '{clean_target}'. "
                f"They typed this sentence: '{request.user_input}'. Write a very short, friendly, and encouraging "
                f"1-sentence response telling them the correct spelling of '{clean_target}'. Do not use quotes in your response."
            )
            response = requests.post(
                OLLAMA_GENERATE_URL,
                json={"model": DICTATION_OLLAMA_MODEL, "prompt": prompt, "stream": False},
                timeout=120,
            )
            response.raise_for_status()
            ai_feedback = response.json()["response"].strip()

        next_review = date.today() + timedelta(days=new_interval)

        await lex.update_assignment_after_grade(
            session,
            assignment.id,
            interval=new_interval,
            correct_streak=new_streak,
            next_review_date=next_review,
        )
        await lex.insert_attempt(session, user_id, lexeme_id, is_correct, date.today())

        return {"status": "success", "is_correct": is_correct, "feedback": ai_feedback}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
