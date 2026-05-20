"""Speech-to-text using faster-whisper. The model is loaded once and reused."""
from __future__ import annotations

from dataclasses import dataclass, field


class STTError(Exception):
    """Raised when transcription fails."""


@dataclass
class STTSegment:
    start: float
    end: float
    text: str


@dataclass
class STTResult:
    text: str
    segments: list[STTSegment] = field(default_factory=list)


class STTService:
    def __init__(self, model_name: str, device: str, compute_type: str):
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        # Imported lazily so importing this module doesn't pull in ctranslate2.
        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            model_name, device=device, compute_type=compute_type
        )

    def transcribe(self, audio_path: str) -> STTResult:
        try:
            segments, _info = self._model.transcribe(audio_path)
            collected = [
                STTSegment(start=round(s.start, 3), end=round(s.end, 3), text=s.text.strip())
                for s in segments
            ]
        except Exception as exc:  # faster-whisper raises various low-level errors
            raise STTError(f"Transcription failed: {exc}") from exc

        full_text = " ".join(s.text for s in collected).strip()
        return STTResult(text=full_text, segments=collected)
