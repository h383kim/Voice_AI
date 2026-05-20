"""Text-to-speech via the piper-tts pip package, loaded in-process and kept warm.

The voice model is loaded once (PiperVoice.load) and reused for every
synthesis, so per-sentence streaming synthesis is fast (no process spawn).
"""
from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

from piper import PiperVoice

MAX_CHARS = 2000


class TTSError(Exception):
    """Raised when synthesis fails."""


@dataclass
class TTSResult:
    audio_path: str
    format: str = "wav"


def _sanitize(text: str) -> str:
    cleaned = " ".join(text.split()).strip()
    return cleaned[:MAX_CHARS]


class TTSService:
    def __init__(self, voice_model_path: str | Path):
        self.voice_model_path = Path(voice_model_path)
        self._voice = None

    def is_available(self) -> bool:
        """The voice model file must exist for synthesis to work."""
        return self.voice_model_path.exists()

    def load(self) -> None:
        """Load the voice model once. Safe to call repeatedly."""
        if self._voice is not None:
            return
        if not self.is_available():
            raise TTSError(
                f"Piper voice model not found at {self.voice_model_path}. "
                "Run scripts/setup_piper.sh."
            )
        try:
            self._voice = PiperVoice.load(str(self.voice_model_path))
        except Exception as exc:  # noqa: BLE001 - surface as a clean TTS error
            raise TTSError(f"Failed to load Piper voice: {exc}") from exc

    def synthesize(self, text: str, output_path: str | Path) -> TTSResult:
        clean = _sanitize(text)
        if not clean:
            raise TTSError("Cannot synthesize empty text.")
        self.load()

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with wave.open(str(output_path), "wb") as wav_file:
                self._voice.synthesize_wav(clean, wav_file)
        except Exception as exc:  # noqa: BLE001 - boundary, report cleanly
            raise TTSError(f"Piper synthesis failed: {exc}") from exc

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise TTSError("Piper produced no audio output.")

        return TTSResult(audio_path=str(output_path), format="wav")
