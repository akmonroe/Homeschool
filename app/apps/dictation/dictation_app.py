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
from app.apps.dictation.dictation_tts import wav_through_tempo
from app.apps.dictation.dictation_tts_settings import (
    VCTK_FALLBACK_SPEAKERS,
    clean_dictation_ollama_sentence,
    get_effective_config,
    get_env_defaults,
    get_overrides_snapshot,
    set_overrides,
    clear_overrides,
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


class TtsSettingsPut(BaseModel):
    """Override dictation TTS for this app process. Omit a field to leave the current value."""

    speaker: str | None = None
    sentence_tempo: float | None = Field(
        None,
        ge=0.25,
        le=1.0,
        description="Sentence playback: lower = slower (0.5 is half speed). 1.0 = full speed.",
    )
    word_tempo: float | None = Field(
        None, ge=0.25, le=1.0, description="Word-only playback speed (same scale as sentence_tempo)."
    )
    use_env_defaults: bool = Field(
        False,
        description="If true, clear overrides; env vars apply. Other fields are ignored for overrides.",
    )


def _list_speaker_ids() -> list[str]:
    if tts_model is None:
        return list(VCTK_FALLBACK_SPEAKERS)
    for attr in ("speakers", "speakers_id"):
        s = getattr(tts_model, attr, None)
        if s:
            return list(s)
    return list(VCTK_FALLBACK_SPEAKERS)


def _ollama_dictation_user_prompt(word: str) -> str:
    return (
        f"Write one natural English sentence for a child's spelling test. The sentence must be between 6 and 14 words. "
        f"Use the spelling word exactly: {word}\n"
        f"Output only the sentence, nothing else. No title, no quotes, no explanations."
    )


def _ollama_dictation_options() -> dict:
    return {
        "num_predict": 80,
        "num_ctx": 256,
        "stop": ["\n\n", "\n#", "\n##"],
        "temperature": 0.55,
    }


def _ollama_dictation_system() -> str:
    return (
        "You are a language teacher writing short dictation sentences. "
        "You write exactly one clear English sentence, grammatically correct, for elementary or middle school. "
        "You never add commentary, prefaces, or a second sentence."
    )


def _ollama_dictation_request_body(word: str) -> dict:
    return {
        "model": DICTATION_OLLAMA_MODEL,
        "prompt": _ollama_dictation_user_prompt(word),
        "stream": False,
        "options": _ollama_dictation_options(),
        "system": _ollama_dictation_system(),
    }


@app.get("/tts-settings", tags=["AI Engine"])
def get_tts_settings() -> dict:
    """Current dictation TTS: env defaults, in-memory overrides, and effective values for playback."""
    env = get_env_defaults()
    ovr = get_overrides_snapshot()
    eff = get_effective_config()
    return {
        "env": env,
        "overrides": ovr,
        "effective": {"speaker": eff.speaker, "sentence_tempo": eff.sentence_tempo, "word_tempo": eff.word_tempo},
    }


@app.put("/tts-settings", tags=["AI Engine"])
def put_tts_settings(body: TtsSettingsPut) -> dict:
    """Set or clear dictation TTS overrides (in-memory, until container restart for env-only)."""
    if body.use_env_defaults:
        clear_overrides()
    else:
        set_overrides(
            speaker=body.speaker,
            sentence_tempo=body.sentence_tempo,
            word_tempo=body.word_tempo,
        )
    eff = get_effective_config()
    return {
        "ok": True,
        "overrides": get_overrides_snapshot(),
        "effective": {"speaker": eff.speaker, "sentence_tempo": eff.sentence_tempo, "word_tempo": eff.word_tempo},
    }


@app.get("/tts-voices", tags=["AI Engine"])
def get_tts_voices() -> dict[str, list[str]]:
    """Speaker IDs for the loaded VCTK VITS model (e.g. p225)."""
    return {"speakers": _list_speaker_ids()}


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
    cfg = get_effective_config()
    speaker = cfg.speaker
    tempo_sent = cfg.sentence_tempo
    tempo_word = cfg.word_tempo

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
            last_err: str | None = None
            sentence = ""
            for attempt in range(2):
                try:
                    body = _ollama_dictation_request_body(word_for_tts)
                    if attempt == 1:
                        opts = dict(body.get("options") or {})
                        opts["temperature"] = 0.25
                        body["options"] = opts
                    response = requests.post(
                        OLLAMA_GENERATE_URL,
                        json=body,
                        timeout=120,
                    )
                    response.raise_for_status()
                    raw = (response.json().get("response") or "").strip()
                except Exception as e:
                    last_err = str(e)
                    break
                sentence = clean_dictation_ollama_sentence(raw, word_for_tts)
                if sentence:
                    break
                last_err = "Model output did not contain the target word or was empty after cleanup."
            if not sentence:
                msg = f"Ollama Error: {last_err}" if last_err else "Ollama returned an empty or unusable sentence."
                raise HTTPException(status_code=500, detail=msg)

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
