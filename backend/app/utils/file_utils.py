"""Filesystem helpers for saving uploads and generating output paths."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import BinaryIO


def unique_name(suffix: str = "") -> str:
    """Return a unique base name, optionally with an extension like '.wav'."""
    return f"{uuid.uuid4().hex}{suffix}"


def unique_path(directory: Path, suffix: str = "") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return directory / unique_name(suffix)


def save_stream(stream: BinaryIO, dest_dir: Path, original_name: str | None) -> Path:
    """Persist an uploaded file stream to dest_dir under a unique name.

    The original extension (if any) is preserved to help ffmpeg detect format.
    """
    ext = ""
    if original_name and "." in Path(original_name).name:
        ext = Path(original_name).suffix
    dest = unique_path(dest_dir, ext)
    with dest.open("wb") as out:
        shutil.copyfileobj(stream, out)
    return dest
