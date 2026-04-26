import csv
import io

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.apps.dictation import database

router = APIRouter(tags=["Dictionary"])

class WordEdit(BaseModel):
    difficulty_level: int
    definition: str

@router.get("/words/{word}/definition")
def get_word_definition(word: str):
    """Fetches the definition directly from the SQL database."""
    clean_word = word.lower().strip()
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT definition FROM words WHERE word = ?", (clean_word,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            raise HTTPException(status_code=404, detail="Word not found in dictionary.")
            
        definition = row['definition']
        
        # If the word is in the database but you haven't typed a definition yet
        if not definition or definition.strip() == "":
            definition = "No definition provided. Ask your teacher!"
            
        return {"status": "success", "word": clean_word, "definition": definition}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/words/bulk-upload")
async def bulk_upload_words(file: UploadFile = File(...)):
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")
    try:
        contents = await file.read()
        csv_reader = csv.DictReader(io.StringIO(contents.decode('utf-8')))
        conn = database.get_db_connection()
        cursor = conn.cursor()
        
        added_count = 0
        for row in csv_reader:
            word = row.get('word', '').lower().strip()
            
            if word:
                # 1. Safely extract the number, defaulting to 1 if it fails
                try:
                    level = int(row.get('difficulty_level', 1))
                except ValueError:
                    level = 1 # Fallback if the cell is blank or contains text
                
                # 2. Insert the word using the new 'level' integer
                cursor.execute(
                    "INSERT OR IGNORE INTO words (word, difficulty_level, definition) VALUES (?, ?, ?)", 
                    (word, level, row.get('definition', '').strip())
                )
                added_count += 1        

        conn.commit()
        conn.close()
        return {"status": "success", "message": f"Processed {added_count} words."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/words", tags=["Dictionary"])
def get_all_words():
    """Fetches the entire master dictionary for the dashboard."""
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, word, difficulty_level, definition FROM words ORDER BY word ASC")
        words = cursor.fetchall()
        conn.close()
        return {"status": "success", "words": [dict(row) for row in words]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/words/{word_id}", tags=["Dictionary"])
def edit_word(word_id: int, word_data: WordEdit):
    """Allows the dashboard to save edits to a word's difficulty or definition."""
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE words SET difficulty_level = ?, definition = ? WHERE id = ?", 
            (word_data.difficulty_level, word_data.definition, word_id)
        )
        conn.commit()
        conn.close()
        return {"status": "success", "message": "Word updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
