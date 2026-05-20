"""TTS tests with a fake PiperVoice so no model is loaded."""
import wave

import pytest

from backend.app.services import tts_service
from backend.app.services.tts_service import TTSError, TTSService


class _FakeVoice:
    def synthesize_wav(self, text, wav_file, **kwargs):
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 100)


class _FakePiperVoice:
    last_loaded = None

    @staticmethod
    def load(model_path, *args, **kwargs):
        _FakePiperVoice.last_loaded = str(model_path)
        return _FakeVoice()


def _make_voice_model(tmp_path):
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"\x00")  # presence is all is_available()/load() needs
    return model


def test_synthesize_writes_wav(tmp_path, monkeypatch):
    monkeypatch.setattr(tts_service, "PiperVoice", _FakePiperVoice)
    model = _make_voice_model(tmp_path)
    out = tmp_path / "out.wav"

    result = TTSService(model).synthesize("  Hello   world  ", out)

    assert result.audio_path == str(out)
    assert out.exists() and out.stat().st_size > 0
    assert _FakePiperVoice.last_loaded == str(model)
    # Output is a valid WAV.
    with wave.open(str(out), "rb") as w:
        assert w.getnchannels() == 1


def test_voice_loaded_once(tmp_path, monkeypatch):
    calls = {"n": 0}

    class CountingVoice(_FakePiperVoice):
        @staticmethod
        def load(model_path, *args, **kwargs):
            calls["n"] += 1
            return _FakeVoice()

    monkeypatch.setattr(tts_service, "PiperVoice", CountingVoice)
    svc = TTSService(_make_voice_model(tmp_path))
    svc.synthesize("one", tmp_path / "a.wav")
    svc.synthesize("two", tmp_path / "b.wav")
    assert calls["n"] == 1  # warm: loaded only once


def test_empty_text_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(tts_service, "PiperVoice", _FakePiperVoice)
    with pytest.raises(TTSError):
        TTSService(_make_voice_model(tmp_path)).synthesize("   ", tmp_path / "out.wav")


def test_missing_model_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(tts_service, "PiperVoice", _FakePiperVoice)
    with pytest.raises(TTSError):
        TTSService(tmp_path / "nope.onnx").synthesize("hello", tmp_path / "out.wav")
