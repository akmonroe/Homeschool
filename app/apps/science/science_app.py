"""Science experiments sub-app (mounted at /apps/science)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.apps.science import storage
from app.apps.science.science_routes import router as science_router

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="Science lab",
    description="Document science experiments, observations, photos, and video.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url=None,
    openapi_url="/openapi.json",
)


def setup_science() -> None:
    storage.ensure_data_dir()


@app.on_event("startup")
def _on_start() -> None:
    setup_science()


app.include_router(science_router)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/apps/science/ui/", status_code=307)


@app.get("/ui", include_in_schema=False)
def ui_no_slash() -> RedirectResponse:
    return RedirectResponse(url="/apps/science/ui/", status_code=307)


@app.get("/ui/", include_in_schema=False)
def science_ui() -> FileResponse:
    p = STATIC_DIR / "index.html"
    if not p.is_file():
        raise HTTPException(404, "Science UI not found")
    return FileResponse(p)


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="science_static")
