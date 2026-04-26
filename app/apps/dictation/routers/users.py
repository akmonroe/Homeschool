from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.apps.dictation import database
from app.apps.dictation import dictation_lexemes as lex
from app.core.deps import get_core_pg_session

router = APIRouter(tags=["Users"])

SessionDep = Annotated[AsyncSession, Depends(get_core_pg_session)]


class UserCreate(BaseModel):
    name: str
    difficulty_level: int = 1
    core_student_id: str | None = None


@router.post("/users")
def create_user(user: UserCreate):
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (name, difficulty_level, core_student_id) VALUES (?, ?, ?)",
            (user.name, str(user.difficulty_level), user.core_student_id),
        )
        conn.commit()
        conn.close()
        return {"status": "success", "message": f"Profile created for {user.name}!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/users")
def get_all_users():
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, difficulty_level, core_student_id FROM users")
        users = cursor.fetchall()
        conn.close()
        return {"status": "success", "users": [dict(row) for row in users]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/users/{user_id}/progress")
async def get_progress_report(user_id: int, session: SessionDep):
    try:
        report = await lex.progress_report(session, user_id)
        return {"status": "success", "report": report}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
