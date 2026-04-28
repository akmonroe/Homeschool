"""Runtime TTS settings for dictation: optional overrides, otherwise env defaults.

Overrides apply process-wide; restarting the app restores env-only behavior.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

from app.apps.dictation.dictation_tts import (
    playback_tempo_from_env,
    tts_speaker_from_env,
    word_playback_tempo_from_env,
)

_lock = threading.Lock()
_override_speaker: str | None = None
_override_sentence_tempo: float | None = None
_override_word_tempo: float | None = None

# VCTK multi-speaker VITS — common test IDs; used if the model is not yet loaded to list names.
VCTK_FALLBACK_SPEAKERS = tuple(f"p{n}" for n in range(225, 256))


@dataclass(frozen=True, slots=True)
class DictationTtsConfig:
    """Effective values used for the next TTS render."""

    speaker: str
    sentence_tempo: float
    word_tempo: float


def get_env_defaults() -> dict[str, str | float]:
    return {
        "speaker": tts_speaker_from_env(),
        "sentence_tempo": playback_tempo_from_env(),
        "word_tempo": word_playback_tempo_from_env(),
    }


def get_effective_config() -> DictationTtsConfig:
    d = get_env_defaults()
    with _lock:
        return DictationTtsConfig(
            speaker=(str(_override_speaker) if _override_speaker is not None else d["speaker"]).strip() or "p225",
            sentence_tempo=(float(_override_sentence_tempo) if _override_sentence_tempo is not None else d["sentence_tempo"]),
            word_tempo=(float(_override_word_tempo) if _override_word_tempo is not None else d["word_tempo"]),
        )


def get_overrides_snapshot() -> dict:
    with _lock:
        return {
            "speaker": _override_speaker,
            "sentence_tempo": _override_sentence_tempo,
            "word_tempo": _override_word_tempo,
        }


def set_overrides(
    speaker: str | None = None,
    sentence_tempo: float | None = None,
    word_tempo: float | None = None,
) -> None:
    """Set override fields. Pass None to leave that field unchanged."""
    with _lock:
        global _override_speaker, _override_sentence_tempo, _override_word_tempo
        if speaker is not None:
            s = str(speaker).strip()
            _override_speaker = s if s else None
        if sentence_tempo is not None:
            st = _clamp_tempo(sentence_tempo)
            _override_sentence_tempo = st
        if word_tempo is not None:
            wt = _clamp_tempo(word_tempo)
            _override_word_tempo = wt


def clear_overrides() -> None:
    with _lock:
        global _override_speaker, _override_sentence_tempo, _override_word_tempo
        _override_speaker = None
        _override_sentence_tempo = None
        _override_word_tempo = None


def _clamp_tempo(v: float) -> float:
    try:
        t = float(v)
    except (TypeError, ValueError):
        return 0.58
    return max(0.25, min(1.0, t))


# --- Sentence Ollama output: normalize model quirks ---

def clean_dictation_ollama_sentence(raw: str, target_spelling: str) -> str:
    """One plain English line for a spelling test; first line, strip chatter, one sentence.

    Ollama often prefaces with 'Sure! Here is...' or returns multiple lines; this keeps dictation stable.
    """
    if not (raw or "").strip():
        return ""
    s = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    # Prefer a line that contains the target word (or obvious variant).
    lines = [ln.strip() for ln in s.split("\n") if ln.strip()]
    w = (target_spelling or "").strip()
    w_lower = w.lower()
    pick = None
    if w and lines:
        for ln in lines:
            if w_lower in ln.lower():
                pick = ln
                break
    if pick is None and lines:
        pick = lines[0]
    elif pick is None:
        pick = s.strip()
    s = _strip_cot_prefix(pick)
    s = s.strip(" \t\"'“”‘’*_`")
    s = re.sub(r"\*+|`+", "", s).strip()
    if not s:
        return ""
    # First sentence only if the model output several.
    if re.search(r"[.!?]\s+\w", s):
        parts = re.split(r"(?<=[.!?])\s+", s, maxsplit=1)
        s = (parts[0] or s).strip()
    if len(s) > 300:
        s = s[:300].rstrip() + "…"
    if w and w_lower not in s.lower():
        return ""
    return s


def _strip_cot_prefix(s: str) -> str:
    t = s.strip()
    for pat in (
        r"^sure[,!.]*\s*",
        r"^(here|here is|here's|the sentence is)[:.,\s]*",
        r"^output[:.\s]+",
        r"^answer[:.\s]+",
    ):
        t2 = re.sub(pat, "", t, flags=re.IGNORECASE)
        if t2 != t:
            t = t2.strip()
    return t
