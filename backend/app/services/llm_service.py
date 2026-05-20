"""LLM responses via the Ollama HTTP API, with graceful unavailability.

Ollama may not be installed/running yet; callers should handle
LLMUnavailableError and surface a clear 503 to the client.
"""
from __future__ import annotations

import json
from typing import Iterator

import requests

from . import session_service

SYSTEM_PROMPT = (
    "You are a helpful, concise voice assistant.\n"
    "The user is speaking, so respond naturally and briefly.\n"
    "Avoid markdown unless necessary.\n"
    "Keep answers under 4 sentences unless the user asks for detail.\n"
    "You can control the user's Mac with the provided tools (notifications, "
    "opening URLs/apps, music). When the user asks you to DO something, call the "
    "appropriate tool rather than only describing it. After a tool runs, confirm "
    "what you did in one short sentence."
)


class LLMUnavailableError(Exception):
    """Raised when the Ollama server cannot be reached."""


class LLMError(Exception):
    """Raised when Ollama responds but the result is unusable."""


class LLMService:
    def __init__(self, base_url: str, model: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def is_available(self) -> bool:
        """Quick liveness check used by the health endpoint."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=2.0)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """Low-level non-streaming chat. Returns the assistant `message` dict
        (may contain `content` and/or `tool_calls`). Used by the agent loop.
        """
        payload: dict = {"model": self.model, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools
        try:
            resp = requests.post(
                f"{self.base_url}/api/chat", json=payload, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise LLMUnavailableError(
                f"Could not connect to Ollama at {self.base_url}"
            ) from exc
        if resp.status_code != 200:
            raise LLMError(f"Ollama returned {resp.status_code}: {resp.text[:300]}")
        return resp.json().get("message", {}) or {}

    def generate_response(self, session_id: str, user_text: str) -> str:
        history = session_service.get_history(session_id)
        messages = (
            [{"role": "system", "content": SYSTEM_PROMPT}]
            + history
            + [{"role": "user", "content": user_text}]
        )
        payload = {"model": self.model, "messages": messages, "stream": False}

        try:
            resp = requests.post(
                f"{self.base_url}/api/chat", json=payload, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise LLMUnavailableError(
                f"Could not connect to Ollama at {self.base_url}"
            ) from exc

        if resp.status_code != 200:
            raise LLMError(
                f"Ollama returned {resp.status_code}: {resp.text[:300]}"
            )

        content = (resp.json().get("message", {}) or {}).get("content", "").strip()
        if not content:
            raise LLMError("Ollama returned an empty response.")

        # Persist this turn so future turns have context.
        session_service.append(session_id, "user", user_text)
        session_service.append(session_id, "assistant", content)
        return content

    def generate_response_stream(
        self, session_id: str, user_text: str
    ) -> Iterator[str]:
        """Yield assistant text deltas as Ollama produces them.

        Raises LLMUnavailableError if Ollama can't be reached. The full turn is
        appended to the session once the stream completes.
        """
        history = session_service.get_history(session_id)
        messages = (
            [{"role": "system", "content": SYSTEM_PROMPT}]
            + history
            + [{"role": "user", "content": user_text}]
        )
        payload = {"model": self.model, "messages": messages, "stream": True}

        try:
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
                stream=True,
            )
        except requests.RequestException as exc:
            raise LLMUnavailableError(
                f"Could not connect to Ollama at {self.base_url}"
            ) from exc

        if resp.status_code != 200:
            raise LLMError(f"Ollama returned {resp.status_code}: {resp.text[:300]}")

        full_parts: list[str] = []
        try:
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                delta = (data.get("message", {}) or {}).get("content", "")
                if delta:
                    full_parts.append(delta)
                    yield delta
                if data.get("done"):
                    break
        finally:
            resp.close()

        full_text = "".join(full_parts).strip()
        if full_text:
            session_service.append(session_id, "user", user_text)
            session_service.append(session_id, "assistant", full_text)
