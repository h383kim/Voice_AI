"""Pydantic models for API responses (see Design_Doc.md §6)."""
from __future__ import annotations

from pydantic import BaseModel


class TimingInfo(BaseModel):
    audio_save_ms: float = 0
    audio_normalization_ms: float = 0
    stt_ms: float = 0
    llm_ms: float = 0
    tts_ms: float = 0
    # Request -> first audio chunk; the key real-time metric (streaming only).
    first_audio_ms: float = 0
    total_ms: float = 0


class TurnMetadata(BaseModel):
    stt_model: str
    llm_model: str
    tts_engine: str = "piper"
    audio_duration_sec: float = 0


class VoiceTurnResponse(BaseModel):
    session_id: str
    transcript: str
    assistant_response: str
    audio_url: str
    timing: TimingInfo
    metadata: TurnMetadata


class HealthResponse(BaseModel):
    status: str
    stt_loaded: bool
    llm_available: bool
    tts_available: bool


class ErrorResponse(BaseModel):
    error: str
    message: str


class ResumeRequest(BaseModel):
    pending_id: str
    approved: bool
    session_id: str | None = None
