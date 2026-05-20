"""Structured logging helpers: one JSON line per completed voice turn."""
from __future__ import annotations

import json
import logging

from .. import config

logger = logging.getLogger("localvoicelab")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def log_voice_turn(record: dict) -> None:
    """Append a single JSON record to data/logs/voice_turns.jsonl."""
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    with config.VOICE_TURN_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
