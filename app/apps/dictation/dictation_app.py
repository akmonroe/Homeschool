"""Dictation FastAPI sub-application (mounted under /apps/dictation)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from TTS.api import TTS

from app.apps.dictation import database
from app.apps.dictation.dictation_tts import (
    playback_tempo_from_env,
    tts_speaker_from_env,
    wav_through_tempo,
    word_playback_tempo_from_env,
)
from app.apps.dictation.ollama_settings import DICTATION_OLLAMA_MODEL, OLLAMA_GENERATE_URL
from app.apps.dictation.routers import dictionary, study, users

STATIC_DIR = Path(__file__).resolve().parent / "static"
DATA_DIR = Path(os.getenv("DICTATION_DATA_DIR", "/app/data"))
CURRENT_SENTENCE_AUDIO = DATA_DIR / "current_dictation_sentence.wav"
CURRENT_WORD_AUDIO = DATA_DIR / "current_dictation_word.wav"
# Legacy single-file path (unused); kept name for any external references
CURRENT_AUDIO = CURRENT_SENTENCE_AUDIO

_GEN_LOCK = threading.Lock()
# Cached practice line for the current target word (replay uses same sentence + WAV without Ollama).
_GEN_CACHE: dict[str, str | int | None] = {
    "word_key": None,
    "display_word": None,
    "sentence": None,
    "revision": 0,
}

app = FastAPI(title="Dictation")

app.include_router(users.router)
app.include_router(dictionary.router)
app.include_router(study.router)

os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/ui", StaticFiles(directory=str(STATIC_DIR), html=True), name="dictation_static")

tts_model: TTS | None = None


class DictationRequest(BaseModel):
    word: str
    regenerate: bool = Field(
        False,
        description="If true, ask Ollama for a new sentence. Default false reuses the last sentence for this word.",
    )


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


def _synthesize_dictation_wavs(sentence: str, word_for_tts: str) -> None:
    """Write sentence + word WAVs with clearer pacing (VITS + ffmpeg tempo)."""
    if tts_model is None:
        raise HTTPException(status_code=503, detail="TTS model is not loaded yet.")
    speaker = tts_speaker_from_env()
    tempo_sent = playback_tempo_from_env()
    tempo_word = word_playback_tempo_from_env()

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as raw_s:
        raw_sentence = Path(raw_s.name)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as raw_w:
        raw_word = Path(raw_w.name)
    try:
        print(f"Generating sentence audio for: {sentence}")
        tts_model.tts_to_file(
            text=sentence,
            speaker=speaker,
            file_path=str(raw_sentence),
            split_sentences=False,
        )
        try:
            wav_through_tempo(raw_sentence, CURRENT_SENTENCE_AUDIO, tempo_sent)
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"ffmpeg tempo (sentence) failed, using raw VITS wav: {exc}")
            shutil.copyfile(raw_sentence, CURRENT_SENTENCE_AUDIO)

        print(f"Generating word-only audio for: {word_for_tts}")
        tts_model.tts_to_file(
            text=word_for_tts,
            speaker=speaker,
            file_path=str(raw_word),
            split_sentences=False,
        )
        try:
            wav_through_tempo(raw_word, CURRENT_WORD_AUDIO, tempo_word)
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"ffmpeg tempo (word) failed, using raw VITS wav: {exc}")
            shutil.copyfile(raw_word, CURRENT_WORD_AUDIO)
    finally:
        raw_sentence.unlink(missing_ok=True)
        raw_word.unlink(missing_ok=True)


@app.post("/generate", tags=["AI Engine"])
def generate_dictation(request: DictationRequest) -> dict[str, str | int | bool]:
    """Builds (or reuses) a practice sentence and TTS. Re-listen uses cache unless regenerate=true."""
    word_for_tts = request.word.strip()
    if not word_for_tts:
        raise HTTPException(status_code=400, detail="word is empty")
    word_key = word_for_tts.lower()

    sentence: str
    from_cache = False

    with _GEN_LOCK:
        cache_ok = (
            not request.regenerate
            and _GEN_CACHE.get("word_key") == word_key
            and isinstance(_GEN_CACHE.get("sentence"), str)
            and str(_GEN_CACHE["sentence"]).strip()
            and CURRENT_SENTENCE_AUDIO.is_file()
            and CURRENT_WORD_AUDIO.is_file()
        )
        if cache_ok:
            sentence = str(_GEN_CACHE["sentence"]).strip()
            from_cache = True
        else:
            prompt = (
                f"Write a simple, 8-word sentence in English for a spelling test. "
                f"Include the word '{word_for_tts}'. Output ONLY the sentence, with no quotes or extra text."
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
            if not sentence:
                raise HTTPException(status_code=500, detail="Ollama returned an empty sentence.")

            _GEN_CACHE["word_key"] = word_key
            _GEN_CACHE["display_word"] = word_for_tts
            _GEN_CACHE["sentence"] = sentence
            _GEN_CACHE["revision"] = int(_GEN_CACHE.get("revision") or 0) + 1

    if not from_cache:
        _synthesize_dictation_wavs(sentence, word_for_tts)

    revision = int(_GEN_CACHE.get("revision") or 0)
    return {
        "status": "success",
        "sentence": sentence,
        "audio_url": "/apps/dictation/audio",
        "word_audio_url": "/apps/dictation/audio/word",
        "revision": revision,
        "from_cache": from_cache,
    }


@app.get("/audio/word", tags=["AI Engine"])
def get_word_audio() -> FileResponse:
    """Serves TTS for the target word alone (last generated session)."""
    if not CURRENT_WORD_AUDIO.is_file():
        raise HTTPException(status_code=404, detail="No word audio generated yet.")
    return FileResponse(str(CURRENT_WORD_AUDIO), media_type="audio/wav")


@app.get("/audio", tags=["AI Engine"])
def get_audio() -> FileResponse:
    """Serves the generated sentence audio to the browser."""
    if not CURRENT_SENTENCE_AUDIO.is_file():
        raise HTTPException(status_code=404, detail="No dictation audio generated yet.")
    return FileResponse(str(CURRENT_SENTENCE_AUDIO), media_type="audio/wav")
