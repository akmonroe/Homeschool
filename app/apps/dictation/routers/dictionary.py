import csv
import io
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.apps.dictation import dictation_lexemes as lex
from app.core.deps import get_core_pg_session

router = APIRouter(tags=["Dictionary"])

SessionDep = Annotated[AsyncSession, Depends(get_core_pg_session)]


class WordEdit(BaseModel):
    difficulty_level: int
    definition: str


@router.get("/words/review", tags=["Dictionary"])
async def review_dictionary_words(
    session: SessionDep,
    q: str | None = Query(None, description="Filter by substring of word (case-insensitive)"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """Paginated browse of all dictionary words with definitions and extensions (pronunciation, etymology, tricks)."""
    try:
        items, total = await lex.list_lexemes_review_page(session, q=q, offset=offset, limit=limit)
        return {
            "status": "success",
            "total": total,
            "offset": offset,
            "limit": limit,
            "words": items,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/words/{word}/definition")
async def get_word_definition(word: str, session: SessionDep):
    """Definition from Postgres `core.lexemes`."""
    clean_word = word.lower().strip()
    try:
        definition = await lex.get_definition_for_word(session, clean_word)
        if definition is None:
            raise HTTPException(status_code=404, detail="Word not found in dictionary.")
        if not definition.strip():
            definition = "No definition provided. Ask your teacher!"
        return {"status": "success", "word": clean_word, "definition": definition}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/words/{word}/study-hints")
async def get_word_study_hints(word: str, session: SessionDep):
    """Definition, etymology, and spelling tricks for use while practicing (from `extensions`)."""
    clean_word = word.lower().strip()
    try:
        hints = await lex.get_study_hints_for_word(session, clean_word)
        if hints is None:
            raise HTTPException(status_code=404, detail="Word not found in dictionary.")
        if not hints["definition"]:
            hints["definition"] = "No definition provided. Ask your teacher!"
        return {"status": "success", **hints}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/words/bulk-upload")
async def bulk_upload_words(session: SessionDep, file: UploadFile = File(...)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")
    try:
        contents = await file.read()
        csv_reader = csv.DictReader(io.StringIO(contents.decode("utf-8")))
        rows = list(csv_reader)
        n = await lex.bulk_upsert_lexemes_from_rows(session, rows)
        return {"status": "success", "message": f"Processed {n} words."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/words", tags=["Dictionary"])
async def get_all_words(session: SessionDep):
    """Master dictionary from Postgres."""
    try:
        words = await lex.list_lexemes_for_admin(session)
        return {"status": "success", "words": words}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put("/words/{word_id}", tags=["Dictionary"])
async def edit_word(word_id: str, word_data: WordEdit, session: SessionDep):
    try:
        lid = uuid.UUID(word_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid word id") from exc
    try:
        await lex.update_lexeme_fields(
            session,
            lid,
            difficulty_level=word_data.difficulty_level,
            definition=word_data.definition,
        )
        return {"status": "success", "message": "Word updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
