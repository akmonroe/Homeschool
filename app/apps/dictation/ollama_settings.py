"""Single source for dictation Ollama URL and model (env-driven)."""

from __future__ import annotations

import os

_ollama_base = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")

OLLAMA_GENERATE_URL = os.getenv(
    "OLLAMA_GENERATE_URL",
    f"{_ollama_base}/api/generate",
)
DICTATION_OLLAMA_MODEL = os.getenv("DICTATION_OLLAMA_MODEL", "gemma4:e4b")
