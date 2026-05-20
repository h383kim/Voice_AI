"""In-memory per-session conversation history (not persisted).

A session keeps only the last N messages (config.SESSION_HISTORY_LIMIT) so the
LLM prompt stays small.
"""
from __future__ import annotations

import uuid

from .. import config

# session_id -> list of {"role": ..., "content": ...}
SESSION_MESSAGES: dict[str, list[dict]] = {}


def ensure_session(session_id: str | None) -> str:
    """Return a valid session id, creating one if none was provided."""
    if not session_id:
        session_id = uuid.uuid4().hex
    SESSION_MESSAGES.setdefault(session_id, [])
    return session_id


def get_history(session_id: str) -> list[dict]:
    return list(SESSION_MESSAGES.get(session_id, []))


def append(session_id: str, role: str, content: str) -> None:
    history = SESSION_MESSAGES.setdefault(session_id, [])
    history.append({"role": role, "content": content})
    limit = config.SESSION_HISTORY_LIMIT
    if len(history) > limit:
        del history[:-limit]


def reset(session_id: str) -> None:
    SESSION_MESSAGES.pop(session_id, None)
