"""Application settings, sourced from environment variables with sane defaults.

Mirrors .env.example. Directories are created on import so the rest of the app
can assume they exist.
"""
from __future__ import annotations

import os
from pathlib import Path

# Project root = two levels up from this file (backend/app/config.py -> repo root).
ROOT_DIR = Path(__file__).resolve().parents[2]


def _path(env_value: str) -> Path:
    p = Path(env_value)
    return p if p.is_absolute() else (ROOT_DIR / p)


# --- STT (faster-whisper) ---
STT_MODEL_NAME = os.getenv("STT_MODEL_NAME", "Systran/faster-whisper-small.en")
STT_DEVICE = os.getenv("STT_DEVICE", "cpu")
STT_COMPUTE_TYPE = os.getenv("STT_COMPUTE_TYPE", "int8")

# --- LLM (Ollama) ---
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

# --- TTS (piper-tts pip package; only a voice model is required) ---
PIPER_VOICE_MODEL = _path(
    os.getenv("PIPER_VOICE_MODEL", "./models/piper/en_US-lessac-medium.onnx")
)

# --- Storage ---
DATA_DIR = _path(os.getenv("DATA_DIR", "./data"))
UPLOAD_DIR = DATA_DIR / "uploads"
NORMALIZED_DIR = DATA_DIR / "normalized"
TTS_OUTPUT_DIR = DATA_DIR / "tts_outputs"
LOG_DIR = DATA_DIR / "logs"
VOICE_TURN_LOG = LOG_DIR / "voice_turns.jsonl"

# --- CORS ---
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]

# Keep the last N messages per session in memory.
SESSION_HISTORY_LIMIT = int(os.getenv("SESSION_HISTORY_LIMIT", "6"))

# --- Agent / tools ---
TOOLS_ENABLED = os.getenv("TOOLS_ENABLED", "true").lower() in ("1", "true", "yes")
TOOLS_MAX_ITERS = int(os.getenv("TOOLS_MAX_ITERS", "5"))
OPEN_APP_ALLOWLIST = [
    a.strip()
    for a in os.getenv(
        "OPEN_APP_ALLOWLIST",
        "Calculator,Notes,Safari,Music,Calendar,Reminders,Maps",
    ).split(",")
    if a.strip()
]


def ensure_dirs() -> None:
    for d in (UPLOAD_DIR, NORMALIZED_DIR, TTS_OUTPUT_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


ensure_dirs()
