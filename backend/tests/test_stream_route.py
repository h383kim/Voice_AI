"""SSE streaming + resume tests with fully faked services (no models/Ollama)."""
import io
import json
import types
import wave

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes
from backend.app.api.routes import router
from backend.app.services import tools_service


class _FakeSTT:
    def transcribe(self, path):
        return types.SimpleNamespace(text="hello world")


class _FakeLLM:
    """Configurable router + scripted agent/chat responses."""

    def __init__(self, needs_tools, chat_script=None, stream_deltas=None):
        self._needs_tools = needs_tools
        self._chat_script = list(chat_script or [])
        self._stream_deltas = list(stream_deltas or [])

    def classify_needs_tools(self, user_text):
        return self._needs_tools

    def chat(self, messages, tools=None):
        return self._chat_script.pop(0)

    def generate_response_stream(self, session_id, user_text):
        for d in self._stream_deltas:
            yield d


class _FakeTTS:
    def synthesize(self, text, output_path):
        with open(output_path, "wb") as f:
            f.write(b"RIFFfake")
        return types.SimpleNamespace(audio_path=str(output_path), format="wav")


def _tool_call(name, args):
    return {"role": "assistant", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


def _tiny_wav_bytes() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 1600)
    return buf.getvalue()


def _build_client(monkeypatch, llm):
    monkeypatch.setattr(
        routes, "normalize_audio", lambda *a, **k: types.SimpleNamespace(duration_sec=0.1)
    )
    monkeypatch.setattr(tools_service, "_run", lambda args: None)  # no real osascript/open
    app = FastAPI()
    app.include_router(router)
    app.state.stt = _FakeSTT()
    app.state.llm = llm
    app.state.tts = _FakeTTS()
    return TestClient(app)


def _post_stream(client):
    return client.post(
        "/api/voice-turn/stream",
        files={"audio_file": ("a.wav", _tiny_wav_bytes(), "audio/wav")},
    )


def _event_data(body, event):
    for block in body.split("\n\n"):
        if f"event: {event}" in block:
            for line in block.split("\n"):
                if line.startswith("data:"):
                    return json.loads(line[5:].strip())
    return None


def test_router_chat_path_skips_tools(monkeypatch):
    # Router says CHAT -> plain token streaming, no tools.
    llm = _FakeLLM(needs_tools=False, stream_deltas=["Hello ", "there. ", "How are you?"])
    body = _post_stream(_build_client(monkeypatch, llm)).text
    assert "event: tool" not in body
    assert "event: tool_request" not in body
    assert body.index("event: transcript") < body.index("event: delta") < body.index("event: done")
    assert _event_data(body, "done")["assistant_response"] == "Hello there. How are you?"


def test_router_action_path_runs_tool(monkeypatch):
    llm = _FakeLLM(
        needs_tools=True,
        chat_script=[_tool_call("notify", {"message": "hi"}), {"content": "Sent it."}],
    )
    body = _post_stream(_build_client(monkeypatch, llm)).text
    assert _event_data(body, "tool")["name"] == "notify"
    assert _event_data(body, "done")["assistant_response"] == "Sent it."


def test_confirm_flow_tool_request_then_resume(monkeypatch):
    llm = _FakeLLM(
        needs_tools=True,
        chat_script=[
            _tool_call("open_url", {"url": "https://example.com"}),
            {"content": "Opened it."},
        ],
    )
    client = _build_client(monkeypatch, llm)
    body = _post_stream(client).text
    assert "event: tool_request" in body
    assert "event: done" not in body
    req = _event_data(body, "tool_request")
    assert req["name"] == "open_url" and req["pending_id"]

    resume = client.post(
        "/api/voice-turn/resume",
        json={"pending_id": req["pending_id"], "approved": True},
    )
    rbody = resume.text
    assert "event: tool" in rbody
    assert _event_data(rbody, "done")["assistant_response"] == "Opened it."
