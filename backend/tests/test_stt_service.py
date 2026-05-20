"""STT tests with a fake faster_whisper so no model is downloaded."""
import sys
import types
from dataclasses import dataclass


@dataclass
class _FakeSegment:
    start: float
    end: float
    text: str


class _FakeWhisperModel:
    def __init__(self, *args, **kwargs):
        pass

    def transcribe(self, audio_path):
        segments = [
            _FakeSegment(0.0, 1.0, " hello "),
            _FakeSegment(1.0, 2.0, " world "),
        ]
        return segments, {"language": "en"}


def _install_fake_faster_whisper(monkeypatch):
    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = _FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)


def test_transcribe_joins_segments(monkeypatch):
    _install_fake_faster_whisper(monkeypatch)
    from backend.app.services.stt_service import STTService

    svc = STTService("fake-model", "cpu", "int8")
    result = svc.transcribe("/tmp/whatever.wav")

    assert result.text == "hello world"
    assert len(result.segments) == 2
    assert result.segments[0].text == "hello"
