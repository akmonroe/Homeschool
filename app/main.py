import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pyttsx3
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from app.apps.dictation.dictation_app import app as dictation_subapp
from app.apps.dictation.dictation_app import setup_dictation
from app.core.database import core_db_enabled, dispose_engine
from app.core.router import router as core_router


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
DEFAULT_OLLAMA_MODEL = os.getenv("DEFAULT_OLLAMA_MODEL", "llama3.2")
MAX_TTS_CHARS = int(os.getenv("MAX_TTS_CHARS", "5000"))

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    setup_dictation()
    yield
    if core_db_enabled():
        await dispose_engine()


app = FastAPI(
    title="Homeschool",
    description=(
        "Homeschooling app suite: web portal, shared AI (Ollama), and TTS. "
        "Individual apps are linked from the landing page."
    ),
    version="0.1.0",
    lifespan=_lifespan,
)

app.include_router(core_router)


@app.get("/", include_in_schema=False)
async def landing_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/apps/dictation", include_in_schema=False)
async def dictation_entry() -> RedirectResponse:
    return RedirectResponse(url="/apps/dictation/ui/", status_code=307)


_admin_dir = STATIC_DIR / "admin"
_admin_index = _admin_dir / "index.html"


@app.get("/admin", include_in_schema=False)
async def admin_no_slash() -> RedirectResponse:
    """Always use trailing slash so relative paths and caches behave consistently."""
    return RedirectResponse(url="/admin/", status_code=307)


@app.get("/admin/", include_in_schema=False)
async def admin_index() -> FileResponse:
    """Platform admin UI (explicit route so this never depends on mount-only behavior)."""
    if not _admin_index.is_file():
        raise HTTPException(status_code=404, detail="Admin UI not found (missing app/static/admin/index.html).")
    return FileResponse(_admin_index)


@app.get("/admin/index.html", include_in_schema=False)
async def admin_index_explicit() -> FileResponse:
    return FileResponse(_admin_index)


app.mount("/admin/static", StaticFiles(directory=str(_admin_dir)), name="admin_static")
app.mount("/apps/dictation", dictation_subapp, name="dictation")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Prompt to send to Ollama.")
    model: str | None = Field(None, description="Ollama model name. Defaults to DEFAULT_OLLAMA_MODEL.")
    system: str | None = Field(None, description="Optional system prompt for the AI tutor.")


class GenerateResponse(BaseModel):
    model: str
    response: str


class TextToSpeechRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Text to synthesize into speech.")
    rate: int = Field(175, ge=80, le=320, description="Speech rate in words per minute.")
    voice: str | None = Field(None, description="Optional pyttsx3 voice id.")


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "ollama_base_url": OLLAMA_BASE_URL,
        "default_ollama_model": DEFAULT_OLLAMA_MODEL,
        "tts_engine": "pyttsx3",
        "core_db_configured": core_db_enabled(),
    }


@app.post("/ai/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest) -> GenerateResponse:
    model = request.model or DEFAULT_OLLAMA_MODEL
    payload = {
        "model": model,
        "prompt": request.prompt,
        "stream": False,
    }
    if request.system:
        payload["system"] = request.system

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Ollama service is unavailable.") from exc

    data = response.json()
    return GenerateResponse(model=model, response=data.get("response", ""))


@app.post("/tts")
def text_to_speech(request: TextToSpeechRequest) -> FileResponse:
    if len(request.text) > MAX_TTS_CHARS:
        raise HTTPException(status_code=413, detail=f"Text is limited to {MAX_TTS_CHARS} characters.")

    output = Path(tempfile.NamedTemporaryFile(delete=False, suffix=".wav").name)
    try:
        engine = pyttsx3.init()
        engine.setProperty("rate", request.rate)
        if request.voice:
            engine.setProperty("voice", request.voice)
        engine.save_to_file(request.text, str(output))
        engine.runAndWait()
    except Exception as exc:
        output.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Text-to-speech synthesis failed.") from exc

    return FileResponse(
        output,
        media_type="audio/wav",
        filename="speech.wav",
        background=BackgroundTask(lambda: output.unlink(missing_ok=True)),
    )
