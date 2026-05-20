"""Audio normalization via ffmpeg: convert any upload to mono 16 kHz WAV."""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1


class AudioError(Exception):
    """Raised when audio cannot be normalized or inspected."""


@dataclass
class AudioMetadata:
    path: str
    duration_sec: float
    sample_rate: int
    channels: int


def _require_tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise AudioError(f"`{name}` not found on PATH. Install ffmpeg.")
    return found


def _probe_duration(path: Path) -> float:
    """Return audio duration in seconds via ffprobe; 0.0 if unavailable."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        proc = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json", str(path),
            ],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(proc.stdout or "{}")
        return round(float(data.get("format", {}).get("duration", 0.0)), 3)
    except (subprocess.CalledProcessError, ValueError, KeyError):
        return 0.0


def normalize_audio(input_path: str | Path, output_path: str | Path) -> AudioMetadata:
    """Convert input audio to mono, 16 kHz, WAV at output_path."""
    ffmpeg = _require_tool("ffmpeg")
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(
            [
                ffmpeg, "-y", "-i", str(input_path),
                "-ac", str(TARGET_CHANNELS),
                "-ar", str(TARGET_SAMPLE_RATE),
                str(output_path),
            ],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise AudioError(f"ffmpeg failed: {exc.stderr.strip()[-500:]}") from exc

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise AudioError("ffmpeg produced no output.")

    return AudioMetadata(
        path=str(output_path),
        duration_sec=_probe_duration(output_path),
        sample_rate=TARGET_SAMPLE_RATE,
        channels=TARGET_CHANNELS,
    )
