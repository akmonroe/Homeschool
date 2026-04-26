from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from datetime import date, timedelta
import sqlite3
import requests
import csv
import io
import re
import database

# This acts like a mini-FastAPI app that we will plug into main.py
router = APIRouter()

# --- Data Models ---
class UserCreate(BaseModel):
    name: str
    difficulty_level: str = "beginner"

class WordAdd(BaseModel):
    word: str
    difficulty_level: str = "beginner"
    definition: str = ""

class GradeRequest(BaseModel):
    target_word: str
    user_input: str

# --- Users API ---
@router.post("/users", tags=["Users"])
def create_user(user: UserCreate):
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (name, difficulty_level) VALUES (?, ?)", 
            (user.name, user.difficulty_level)
        )
        conn.commit()
        conn.close()
        return {"status": "success", "message": f"Profile created for {user.name}!"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="A user with this name already exists.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users", tags=["Users"])
def get_all_users():
    """Fetches all kids currently in the database."""
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, difficulty_level FROM users")
        users = cursor.fetchall()
        conn.close()
        
        return {"status": "success", "users": [dict(row) for row in users]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Vocabulary API ---
@router.post("/users/{user_id}/words", tags=["Vocabulary"])
def assign_word_to_user(user_id: int, word_data: WordAdd):
    clean_word = word_data.word.lower().strip()
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR IGNORE INTO words (word, difficulty_level, definition) 
            VALUES (?, ?, ?)
        ''', (clean_word, word_data.difficulty_level, word_data.definition))
        
        cursor.execute("SELECT id FROM words WHERE word = ?", (clean_word,))
        word_id = cursor.fetchone()['id']
        
        cursor.execute('''
            INSERT INTO user_words (user_id, word_id) 
            VALUES (?, ?)
        ''', (user_id, word_id))
        
        conn.commit()
        conn.close()
        return {"status": "success", "message": f"Assigned '{clean_word}' to user {user_id}."}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="This word is already assigned to this user.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users/{user_id}/words/due", tags=["Vocabulary"])
def get_due_words(user_id: int):
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT uw.id as assignment_id, w.word, w.definition, uw.interval, uw.correct_streak 
            FROM user_words uw
            JOIN words w ON uw.word_id = w.id
            WHERE uw.user_id = ? AND uw.next_review_date <= ?
        ''', (user_id, date.today().isoformat()))
        due_words = cursor.fetchall()
        conn.close()
        return {"status": "success", "count": len(due_words), "due_words": [dict(row) for row in due_words]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/words/{word}/definition", tags=["Dictionary"])
def get_word_definition(word: str):
    clean_word = word.lower().strip()
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, definition FROM words WHERE word = ?", (clean_word,))
        row = cursor.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Word not found in master dictionary.")
            
        word_id = row['id']
        definition = row['definition']
        
        if not definition:
            print(f"Generating definition for '{clean_word}'...")
            ollama_url = "http://localhost:11434/api/generate"
            prompt = f"Write a simple, 1-sentence dictionary definition for the word '{clean_word}' suitable for an elementary school student. Output ONLY the definition."
            
            response = requests.post(ollama_url, json={"model": "gemma4:4b", "prompt": prompt, "stream": False})
            response.raise_for_status()
            definition = response.json()["response"].strip()
            
            cursor.execute("UPDATE words SET definition = ? WHERE id = ?", (definition, word_id))
            conn.commit()
            
        conn.close()
        return {"status": "success", "word": clean_word, "definition": definition}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/words/bulk-upload", tags=["Dictionary"])
async def bulk_upload_words(file: UploadFile = File(...)):
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")
    try:
        contents = await file.read()
        decoded = contents.decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(decoded))
        
        conn = database.get_db_connection()
        cursor = conn.cursor()
        
        added_count = 0
        for row in csv_reader:
            word = row.get('word', '').lower().strip()
            level = row.get('difficulty_level', 'beginner').lower().strip()
            definition = row.get('definition', '').strip()
            
            if word:
                cursor.execute('''
                    INSERT OR IGNORE INTO words (word, difficulty_level, definition) 
                    VALUES (?, ?, ?)
                ''', (word, level, definition))
                added_count += 1
                
        conn.commit()
        conn.close()
        return {"status": "success", "message": f"Processed {added_count} words from CSV."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users/{user_id}/grade", tags=["Vocabulary"])
def grade_dictation(user_id: int, request: GradeRequest):
    """Evaluates the spelling, updates Spaced Repetition, and generates AI feedback."""
    clean_target = request.target_word.lower().strip()
    
    # 1. Clean the user's input (strip punctuation and lowercase)
    # This splits the sentence into a clean list of just words: ["the", "quick", "astronaut"]
    words_in_input = re.findall(r'\b\w+\b', request.user_input.lower())
    
    # 2. Check if the exact target word is in their cleaned list
    is_correct = clean_target in words_in_input
    
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        
        # Find this specific student's assignment for this word
        cursor.execute('''
            SELECT uw.id, uw.interval, uw.correct_streak 
            FROM user_words uw
            JOIN words w ON uw.word_id = w.id
            WHERE uw.user_id = ? AND w.word = ?
        ''', (user_id, clean_target))
        
        assignment = cursor.fetchone()
        
        if not assignment:
            raise HTTPException(status_code=404, detail="Word not assigned to this user.")
            
        current_interval = assignment['interval']
        streak = assignment['correct_streak']
        
        # 3. Spaced Repetition Algorithm & Feedback
        if is_correct:
            new_streak = streak + 1
            # Interval math: 1 day, then 2, 4, 8, 16 days...
            new_interval = 1 if new_streak == 1 else current_interval * 2
            ai_feedback = "Great job! You spelled it perfectly."
        else:
            new_streak = 0
            new_interval = 1 # Try again tomorrow
            
            # Ask Gemma 4 for gentle correction
            print(f"Generating correction for '{clean_target}'...")
            ollama_url = "http://localhost:11434/api/generate"
            prompt = f"A student was doing a spelling dictation. They were supposed to spell '{clean_target}'. They typed this sentence: '{request.user_input}'. Write a very short, friendly, and encouraging 1-sentence response telling them the correct spelling of '{clean_target}'. Do not use quotes in your response."
            
            try:
                response = requests.post(ollama_url, json={
                    "model": "gemma4:4b", 
                    "prompt": prompt, 
                    "stream": False
                })
                response.raise_for_status()
                ai_feedback = response.json()["response"].strip()
            except Exception as e:
                print(f"AI Feedback Error: {e}")
                ai_feedback = f"Oops! The correct spelling is '{clean_target}'. We will practice this one again!"
        
        # 4. Save progress to database
        next_review = date.today() + timedelta(days=new_interval)
        
        cursor.execute('''
            UPDATE user_words 
            SET interval = ?, correct_streak = ?, next_review_date = ?
            WHERE id = ?
        ''', (new_interval, new_streak, next_review.isoformat(), assignment['id']))

        # ... (existing spaced repetition math) ...
        
        cursor.execute('''
            UPDATE user_words 
            SET interval = ?, correct_streak = ?, next_review_date = ?
            WHERE id = ?
        ''', (new_interval, new_streak, next_review.isoformat(), assignment['id']))
        
        # --- ADD THIS BLOCK TO LOG THE ATTEMPT ---
        cursor.execute('''
            INSERT INTO history (user_id, word_id, is_correct, attempt_date)
            VALUES (?, ?, ?, ?)
        ''', (user_id, assignment['word_id'], is_correct, date.today().isoformat()))
        # -----------------------------------------
        
        conn.commit()
        
        conn.commit()
        conn.close()
        
        return {
            "status": "success",
            "is_correct": is_correct,
            "feedback": ai_feedback,
            "new_streak": new_streak,
            "next_review": next_review.isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
