from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.apps.dictation import database

router = APIRouter(tags=["Users"])

class UserCreate(BaseModel):
    name: str
    difficulty_level: int = 1 # changed to numeric ranking

@router.post("/users")
def create_user(user: UserCreate):
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (name, difficulty_level) VALUES (?, ?)", (user.name, user.difficulty_level))
        conn.commit()
        conn.close()
        return {"status": "success", "message": f"Profile created for {user.name}!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users")
def get_all_users():
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, difficulty_level FROM users")
        users = cursor.fetchall()
        conn.close()
        return {"status": "success", "users": [dict(row) for row in users]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users/{user_id}/progress")
def get_progress_report(user_id: int):
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT attempt_date, COUNT(*) as total_attempts, SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct_attempts
            FROM history WHERE user_id = ? GROUP BY attempt_date ORDER BY attempt_date DESC
        ''', (user_id,))
        daily_stats = cursor.fetchall()
        conn.close()
        
        report = [{"date": day['attempt_date'], "score": f"{day['correct_attempts']}/{day['total_attempts']}", "accuracy_percent": round((day['correct_attempts'] / day['total_attempts']) * 100)} for day in daily_stats]
        return {"status": "success", "report": report}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
