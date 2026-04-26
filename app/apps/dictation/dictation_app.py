"""Dictation FastAPI sub-application (mounted under /apps/dictation)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from TTS.api import TTS

from app.apps.dictation import database
from app.apps.dictation.routers import dictionary, study, users

OLLAMA_GENERATE_URL = os.getenv(
    "OLLAMA_GENERATE_URL",
    f"{os.getenv('OLLAMA_BASE_URL', 'http://host.docker.internal:11434').rstrip('/')}/api/generate",
)
DICTATION_OLLAMA_MODEL = os.getenv("DICTATION_OLLAMA_MODEL", "gemma4:e4b")

STATIC_DIR = Path(__file__).resolve().parent / "static"
DATA_DIR = Path(os.getenv("DICTATION_DATA_DIR", "/app/data"))
CURRENT_AUDIO = DATA_DIR / "current_dictation.wav"

app = FastAPI(title="Dictation")

app.include_router(users.router)
app.include_router(dictionary.router)
app.include_router(study.router)

os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/ui", StaticFiles(directory=str(STATIC_DIR), html=True), name="dictation_static")

tts_model: TTS | None = None


class DictationRequest(BaseModel):
    word: str


def setup_dictation() -> None:
    """Initialize SQLite and load VITS. Call from the root app lifespan: mounted
    sub-applications do not receive FastAPI startup events when the parent boots.
    """
    global tts_model
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    database.init_db()
    print("Initializing Fast VITS Model...")

    try:
        tts_model = TTS("tts_models/en/vctk/vits").to("cpu")
        print("Model loaded and ready!")
    except ValueError as e:
        if "Model file not found" in str(e):
            print("Corrupted partial download detected. Deleting and retrying...")
            bad_cache_path = os.path.expanduser("~/.local/share/tts/tts_models--en--vctk--vits")
            shutil.rmtree(bad_cache_path, ignore_errors=True)
            print("Downloading fresh VITS model...")
            tts_model = TTS("tts_models/en/vctk/vits").to("cpu")
            print("Model loaded and ready!")
        else:
            raise


@app.post("/generate", tags=["AI Engine"])
def generate_dictation(request: DictationRequest) -> dict[str, str]:
    """Generates the sentence via Ollama and the audio via VITS."""
    prompt = (
        f"Write a simple, 8-word sentence in English for a spelling test. "
        f"Include the word '{request.word}'. Output ONLY the sentence, with no quotes or extra text."
    )

    try:
        response = requests.post(
            OLLAMA_GENERATE_URL,
            json={"model": DICTATION_OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120,
        )
        response.raise_for_status()
        sentence = response.json()["response"].strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ollama Error: {e!s}") from e

    if tts_model is None:
        raise HTTPException(status_code=503, detail="TTS model is not loaded yet.")

    print(f"Generating audio for: {sentence}")
    tts_model.tts_to_file(
        text=sentence,
        speaker="p226",
        file_path=str(CURRENT_AUDIO),
        speed=0.25,
    )

    return {
        "status": "success",
        "sentence": sentence,
        "audio_url": "/apps/dictation/audio",
    }


@app.get("/audio", tags=["AI Engine"])
def get_audio() -> FileResponse:
    """Serves the generated audio file to the browser."""
    if not CURRENT_AUDIO.is_file():
        raise HTTPException(status_code=404, detail="No dictation audio generated yet.")
    return FileResponse(str(CURRENT_AUDIO), media_type="audio/wav")
