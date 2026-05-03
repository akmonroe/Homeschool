"""Local file storage for science experiment photos and video."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

DATA_DIR = Path(os.getenv("SCIENCE_DATA_DIR", "/app/data/science")).resolve()

# Single-file upload cap (set via env; default 100 MiB)
MAX_MEDIA_BYTES = int(os.getenv("SCIENCE_MAX_MEDIA_BYTES", str(100 * 1024 * 1024)))

_IMAGE_CT = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
    }
)
_VIDEO_CT = frozenset(
    {
        "video/mp4",
        "video/webm",
        "video/quicktime",
    }
)
_ALLOWED = _IMAGE_CT | _VIDEO_CT


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def is_allowed_content_type(content_type: str | None) -> bool:
    if not content_type:
        return False
    ct = content_type.split(";", 1)[0].strip().lower()
    return ct in _ALLOWED


def kind_for_content_type(content_type: str) -> str:
    ct = content_type.split(";", 1)[0].strip().lower()
    if ct in _IMAGE_CT:
        return "image"
    if ct in _VIDEO_CT:
        return "video"
    return "file"


def ext_for_content_type(content_type: str) -> str:
    ct = content_type.split(";", 1)[0].strip().lower()
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
    }.get(ct, ".bin")


def write_stream(
    run_id: uuid.UUID,
    media_id: uuid.UUID,
    file_obj,
    content_type: str,
) -> tuple[str, str, int]:
    """Return (rel_path, kind, bytes_written)."""
    if not is_allowed_content_type(content_type):
        raise ValueError("Use JPEG, PNG, GIF, WebP, MP4, WebM, or QuickTime (MOV).")
    ensure_data_dir()
    kind = kind_for_content_type(content_type)
    if kind not in ("image", "video"):
        raise ValueError("Unsupported kind.")
    ext = ext_for_content_type(content_type)
    run_dir = DATA_DIR / str(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    rel = f"{run_id}/{media_id}{ext}"
    dest = DATA_DIR / rel
    size = 0
    with dest.open("wb") as out:
        shutil.copyfileobj(file_obj, out, length=1024 * 1024)
        size = dest.stat().st_size
    if size > MAX_MEDIA_BYTES:
        dest.unlink(missing_ok=True)
        raise ValueError(f"File is too large (max {MAX_MEDIA_BYTES} bytes).")
    return (rel, kind, size)


def file_path_for_rel(rel_path: str) -> Path:
    p = (DATA_DIR / rel_path).resolve()
    if not str(p).startswith(str(DATA_DIR)) or ".." in rel_path:
        raise ValueError("Invalid path")
    return p


def safe_unlink_rel(rel_path: str | None) -> None:
    if not rel_path:
        return
    try:
        p = file_path_for_rel(rel_path)
        p.unlink(missing_ok=True)
    except ValueError:
        return


def delete_run_folder(run_id: uuid.UUID) -> None:
    d = DATA_DIR / str(run_id)
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
