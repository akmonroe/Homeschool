"""Dictation TTS helpers: post-process WAV for clearer, slower playback (ffmpeg atempo)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _ffmpeg_atempo_chain(tempo: float) -> str:
    """Build atempo filter; each factor must be between 0.5 and 2.0."""
    if tempo >= 1.0:
        return f"atempo={tempo:.4f}"
    parts: list[str] = []
    t = tempo
    while t < 0.5:
        parts.append("atempo=0.5")
        t /= 0.5
    if abs(t - 1.0) > 1e-6:
        parts.append(f"atempo={t:.4f}")
    return ",".join(parts) if parts else "atempo=1.0"


def apply_playback_tempo(input_wav: Path, output_wav: Path, tempo: float) -> None:
    """Stretch audio duration by ~1/tempo using ffmpeg (tempo<1 = slower, clearer for dictation)."""
    if tempo >= 0.999:
        shutil.copyfile(input_wav, output_wav)
        return
    filt = _ffmpeg_atempo_chain(tempo)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_wav),
        "-af",
        filt,
        str(output_wav),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def wav_through_tempo(in_path: Path, out_path: Path, tempo: float) -> None:
    """Write processed audio to out_path (uses temp file if in_path == out_path)."""
    if abs(tempo - 1.0) < 1e-6:
        if in_path.resolve() != out_path.resolve():
            shutil.copyfile(in_path, out_path)
        return
    if in_path.resolve() == out_path.resolve():
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            apply_playback_tempo(in_path, tmp_path, tempo)
            shutil.move(str(tmp_path), out_path)
        finally:
            tmp_path.unlink(missing_ok=True)
    else:
        apply_playback_tempo(in_path, out_path, tempo)


def playback_tempo_from_env() -> float:
    raw = os.getenv("DICTATION_TTS_PLAYBACK_TEMPO", "0.58").strip()
    try:
        v = float(raw)
    except ValueError:
        return 0.58
    return max(0.25, min(1.0, v))


def word_playback_tempo_from_env() -> float:
    raw = os.getenv("DICTATION_TTS_WORD_PLAYBACK_TEMPO", "").strip()
    if not raw:
        return min(0.72, playback_tempo_from_env() * 1.15)
    try:
        v = float(raw)
    except ValueError:
        return 0.65
    return max(0.25, min(1.0, v))


def tts_speaker_from_env() -> str:
    return os.getenv("DICTATION_TTS_SPEAKER", "p225").strip() or "p225"
