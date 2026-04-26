import os
import re
import sqlite3
from datetime import date, timedelta

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.apps.dictation import database

OLLAMA_GENERATE_URL = os.getenv(
    "OLLAMA_GENERATE_URL",
    f"{os.getenv('OLLAMA_BASE_URL', 'http://host.docker.internal:11434').rstrip('/')}/api/generate",
)
DICTATION_OLLAMA_MODEL = os.getenv("DICTATION_OLLAMA_MODEL", "gemma4:e4b")

router = APIRouter(tags=["Study & Curriculum"])

class WordAdd(BaseModel):
    word: str
    difficulty_level: int = 1 #changed to int
    definition: str = ""

class GradeRequest(BaseModel):
    target_word: str
    user_input: str

@router.post("/users/{user_id}/words")
def assign_word_to_user(user_id: int, word_data: WordAdd):
    clean_word = word_data.word.lower().strip()
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO words (word, difficulty_level, definition) VALUES (?, ?, ?)", 
                       (clean_word, word_data.difficulty_level, word_data.definition))
        cursor.execute("SELECT id FROM words WHERE word = ?", (clean_word,))
        word_id = cursor.fetchone()['id']
        cursor.execute("INSERT INTO user_words (user_id, word_id) VALUES (?, ?)", (user_id, word_id))
        conn.commit()
        conn.close()
        return {"status": "success", "message": f"Assigned '{clean_word}'."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users/{user_id}/words/due")
def get_due_words(user_id: int):
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT uw.id as assignment_id, w.word, w.definition, uw.interval, uw.correct_streak 
            FROM user_words uw JOIN words w ON uw.word_id = w.id
            WHERE uw.user_id = ? AND uw.next_review_date <= ?
        ''', (user_id, date.today().isoformat()))
        due_words = cursor.fetchall()
        conn.close()
        return {"status": "success", "count": len(due_words), "due_words": [dict(row) for row in due_words]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/users/{user_id}/grade")
def grade_dictation(user_id: int, request: GradeRequest):
    clean_target = request.target_word.lower().strip()
    words_in_input = re.findall(r'\b\w+\b', request.user_input.lower())
    is_correct = clean_target in words_in_input
    
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT uw.id, uw.interval, uw.correct_streak, uw.word_id 
            FROM user_words uw JOIN words w ON uw.word_id = w.id
            WHERE uw.user_id = ? AND w.word = ?
        ''', (user_id, clean_target))
        assignment = cursor.fetchone()
        
        new_streak = assignment['correct_streak'] + 1 if is_correct else 0
        new_interval = 1 if new_streak <= 1 else assignment['interval'] * 2 if is_correct else 1
        
        if is_correct:
            ai_feedback = "Great job! You spelled it perfectly."
        else:
            prompt = f"A student was doing a spelling dictation. They were supposed to spell '{clean_target}'. They typed this sentence: '{request.user_input}'. Write a very short, friendly, and encouraging 1-sentence response telling them the correct spelling of '{clean_target}'. Do not use quotes in your response."
            response = requests.post(
                OLLAMA_GENERATE_URL,
                json={"model": DICTATION_OLLAMA_MODEL, "prompt": prompt, "stream": False},
                timeout=120,
            )
            ai_feedback = response.json()["response"].strip()
            
        next_review = date.today() + timedelta(days=new_interval)
        
        cursor.execute("UPDATE user_words SET interval = ?, correct_streak = ?, next_review_date = ? WHERE id = ?", (new_interval, new_streak, next_review.isoformat(), assignment['id']))
        cursor.execute("INSERT INTO history (user_id, word_id, is_correct, attempt_date) VALUES (?, ?, ?, ?)", (user_id, assignment['word_id'], is_correct, date.today().isoformat()))
        conn.commit()
        conn.close()
        
        return {"status": "success", "is_correct": is_correct, "feedback": ai_feedback}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

