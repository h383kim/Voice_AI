"""LLM tests with mocked HTTP so no Ollama server is required."""
import pytest
import requests

from backend.app.services import session_service
from backend.app.services.llm_service import (
    LLMError,
    LLMService,
    LLMUnavailableError,
)


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", lines=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self._lines = lines or []
        self.closed = False

    def json(self):
        return self._payload

    def iter_lines(self):
        for line in self._lines:
            yield line

    def close(self):
        self.closed = True


def test_generate_response_returns_content(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse(payload={"message": {"content": "Hi there!"}})

    monkeypatch.setattr(requests, "post", fake_post)

    sid = session_service.ensure_session("llm-test-1")
    out = LLMService("http://localhost:11434", "llama3.2:3b").generate_response(
        sid, "Hello"
    )

    assert out == "Hi there!"
    # System prompt first, user message present.
    roles = [m["role"] for m in captured["json"]["messages"]]
    assert roles[0] == "system"
    assert captured["json"]["messages"][-1] == {"role": "user", "content": "Hello"}
    assert captured["json"]["stream"] is False
    # Turn stored in history.
    assert len(session_service.get_history(sid)) == 2
    session_service.reset(sid)


def test_unavailable_when_connection_fails(monkeypatch):
    def fake_post(*args, **kwargs):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(requests, "post", fake_post)
    sid = session_service.ensure_session("llm-test-2")
    with pytest.raises(LLMUnavailableError):
        LLMService("http://localhost:11434", "m").generate_response(sid, "hi")
    session_service.reset(sid)


def test_error_on_non_200(monkeypatch):
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: _FakeResponse(status_code=500, text="boom")
    )
    sid = session_service.ensure_session("llm-test-3")
    with pytest.raises(LLMError):
        LLMService("http://localhost:11434", "m").generate_response(sid, "hi")
    session_service.reset(sid)


def test_generate_response_stream_yields_deltas(monkeypatch):
    import json as _json

    lines = [
        _json.dumps({"message": {"content": "Hello"}, "done": False}).encode(),
        b"",  # blank lines should be skipped
        _json.dumps({"message": {"content": " world"}, "done": False}).encode(),
        _json.dumps({"message": {"content": "!"}, "done": True}).encode(),
    ]

    def fake_post(url, json, timeout, stream):
        assert stream is True
        assert json["stream"] is True
        return _FakeResponse(lines=lines)

    monkeypatch.setattr(requests, "post", fake_post)
    sid = session_service.ensure_session("llm-stream-1")
    deltas = list(
        LLMService("http://localhost:11434", "m").generate_response_stream(sid, "hi")
    )
    assert deltas == ["Hello", " world", "!"]
    # Full turn persisted to history (user + assistant).
    history = session_service.get_history(sid)
    assert history[-1] == {"role": "assistant", "content": "Hello world!"}
    session_service.reset(sid)


def test_generate_response_stream_unavailable(monkeypatch):
    def fake_post(*args, **kwargs):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(requests, "post", fake_post)
    sid = session_service.ensure_session("llm-stream-2")
    with pytest.raises(LLMUnavailableError):
        list(LLMService("http://x", "m").generate_response_stream(sid, "hi"))
    session_service.reset(sid)


def test_classify_needs_tools(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["json"] = json
        content = "ACTION" if "open" in json["messages"][-1]["content"] else "CHAT"
        return _FakeResponse(payload={"message": {"content": content}})

    monkeypatch.setattr(requests, "post", fake_post)
    svc = LLMService("http://localhost:11434", "llama3.2:3b", router_model="llama3.2:1b")

    assert svc.classify_needs_tools("open the calculator") is True
    assert svc.classify_needs_tools("what is the capital of France") is False
    # Uses the router model + non-streaming + a small output cap.
    assert captured["json"]["model"] == "llama3.2:1b"
    assert captured["json"]["stream"] is False
    assert captured["json"]["options"]["num_predict"] <= 5


def test_classify_unclear_defaults_to_chat(monkeypatch):
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: _FakeResponse(payload={"message": {"content": "hmm"}})
    )
    assert LLMService("http://x", "m").classify_needs_tools("hello") is False


def test_classify_unavailable(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError()

    monkeypatch.setattr(requests, "post", boom)
    with pytest.raises(LLMUnavailableError):
        LLMService("http://x", "m").classify_needs_tools("hi")


def test_is_available(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(status_code=200))
    assert LLMService("http://x", "m").is_available() is True

    def boom(*a, **k):
        raise requests.ConnectionError()

    monkeypatch.setattr(requests, "get", boom)
    assert LLMService("http://x", "m").is_available() is False
