"""HTTP routes: the full voice-turn pipeline, audio serving, and health."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .. import config
from ..schemas import (
    HealthResponse,
    ResumeRequest,
    TimingInfo,
    TurnMetadata,
    VoiceTurnResponse,
)
from ..services import agent_service, session_service
from ..services.audio_service import AudioError, normalize_audio
from ..services.llm_service import LLMError, LLMUnavailableError
from ..services.sentence_chunker import SentenceChunker
from ..services.stt_service import STTError
from ..services.tts_service import TTSError
from ..services.timing_service import timer
from ..utils import file_utils
from ..utils.logging_utils import log_voice_turn

router = APIRouter(prefix="/api")


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    app = request.app
    stt = getattr(app.state, "stt", None)
    llm = getattr(app.state, "llm", None)
    tts = getattr(app.state, "tts", None)
    return HealthResponse(
        status="ok",
        stt_loaded=stt is not None,
        llm_available=bool(llm and llm.is_available()),
        tts_available=bool(tts and tts.is_available()),
    )


@router.get("/audio/{filename}")
def get_audio(filename: str):
    # Reject any path traversal; only serve plain names from the TTS output dir.
    if "/" in filename or "\\" in filename or ".." in filename:
        return _error(400, "invalid_filename", "Invalid audio filename.")
    path = (config.TTS_OUTPUT_DIR / filename).resolve()
    if config.TTS_OUTPUT_DIR.resolve() not in path.parents or not path.exists():
        return _error(404, "not_found", "Audio file not found.")
    return FileResponse(path, media_type="audio/wav", filename=filename)


@router.post("/voice-turn")
async def voice_turn(
    request: Request,
    audio_file: UploadFile = File(...),
    session_id: str | None = Form(None),
):
    app = request.app
    stt = app.state.stt
    llm = app.state.llm
    tts = app.state.tts

    if audio_file is None:
        return _error(400, "missing_audio", "No audio file provided.")

    session_id = session_service.ensure_session(session_id)
    timing: dict[str, float] = {}

    # 1) Save the upload.
    try:
        with timer("audio_save_ms", timing):
            raw_path = file_utils.save_stream(
                audio_file.file, config.UPLOAD_DIR, audio_file.filename
            )
        if raw_path.stat().st_size == 0:
            return _error(400, "empty_audio", "Uploaded audio file is empty.")
    except Exception as exc:  # noqa: BLE001 - boundary, report cleanly
        return _error(500, "save_failed", f"Could not save upload: {exc}")

    # 2) Normalize to mono 16 kHz WAV.
    try:
        normalized_path = file_utils.unique_path(config.NORMALIZED_DIR, ".wav")
        with timer("audio_normalization_ms", timing):
            audio_meta = normalize_audio(raw_path, normalized_path)
    except AudioError as exc:
        return _error(400, "audio_normalization_failed", str(exc))

    # 3) Speech to text.
    try:
        with timer("stt_ms", timing):
            stt_result = stt.transcribe(str(normalized_path))
    except STTError as exc:
        return _error(500, "stt_failed", str(exc))

    if not stt_result.text.strip():
        return _error(400, "empty_transcript", "No speech detected in the audio.")

    # 4) LLM response.
    try:
        with timer("llm_ms", timing):
            assistant_text = llm.generate_response(session_id, stt_result.text)
    except LLMUnavailableError as exc:
        return _error(503, "llm_unavailable", str(exc))
    except LLMError as exc:
        return _error(502, "llm_error", str(exc))

    # 5) Text to speech.
    try:
        tts_path = file_utils.unique_path(config.TTS_OUTPUT_DIR, ".wav")
        with timer("tts_ms", timing):
            tts.synthesize(assistant_text, tts_path)
    except TTSError as exc:
        return _error(503, "tts_failed", str(exc))

    timing["total_ms"] = round(sum(timing.values()), 2)

    response = VoiceTurnResponse(
        session_id=session_id,
        transcript=stt_result.text,
        assistant_response=assistant_text,
        audio_url=f"/api/audio/{Path(tts_path).name}",
        timing=TimingInfo(**timing),
        metadata=TurnMetadata(
            stt_model=config.STT_MODEL_NAME,
            llm_model=config.OLLAMA_MODEL,
            tts_engine="piper",
            audio_duration_sec=audio_meta.duration_sec,
        ),
    )

    log_voice_turn(
        {
            "event": "voice_turn_completed",
            "session_id": session_id,
            "audio_duration_sec": audio_meta.duration_sec,
            "transcript_chars": len(stt_result.text),
            "response_chars": len(assistant_text),
            **{k: timing.get(k, 0) for k in (
                "audio_save_ms", "audio_normalization_ms",
                "stt_ms", "llm_ms", "tts_ms", "total_ms",
            )},
            "stt_model": config.STT_MODEL_NAME,
            "llm_model": config.OLLAMA_MODEL,
            "tts_engine": "piper",
        }
    )

    return response


def _emit_agent_stream(
    events,
    *,
    tts,
    t0: float,
    timing: dict[str, float],
    session_id: str,
    audio_duration_sec: float,
    transcript_chars: int = 0,
) -> Iterator[str]:
    """Translate agent events into SSE, synthesizing audio per sentence.

    Shared by the stream endpoint and the resume endpoint. On a ToolConfirm it
    emits `tool_request` and stops (the client resumes); otherwise it finishes
    with a `done` event and logs the turn.
    """
    chunker = SentenceChunker()
    tts_ms = 0.0
    agent_start = time.perf_counter()
    assistant_text: str | None = None

    def synth(sentence: str) -> Iterator[str]:
        nonlocal tts_ms
        try:
            chunk_path = file_utils.unique_path(config.TTS_OUTPUT_DIR, ".wav")
            s = time.perf_counter()
            tts.synthesize(sentence, chunk_path)
            tts_ms += (time.perf_counter() - s) * 1000
        except TTSError as exc:
            yield _sse("error", {"error": "tts_failed", "message": str(exc)})
            return
        if "first_audio_ms" not in timing:
            timing["first_audio_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        yield _sse("audio", {"url": f"/api/audio/{chunk_path.name}", "text": sentence})

    try:
        for ev in events:
            if isinstance(ev, agent_service.ToolStarted):
                yield _sse("tool", {"name": ev.name, "args": ev.args, "status": "running"})
            elif isinstance(ev, agent_service.ToolResult):
                yield _sse(
                    "tool",
                    {"name": ev.name, "result": ev.result, "ok": ev.ok, "status": "done"},
                )
            elif isinstance(ev, agent_service.ToolConfirm):
                yield _sse(
                    "tool_request",
                    {"pending_id": ev.pending_id, "name": ev.name, "args": ev.args},
                )
                return  # paused for confirmation; client will call resume
            elif isinstance(ev, agent_service.Done):
                assistant_text = ev.text
                for sentence in chunker.feed(ev.text):
                    yield _sse("delta", {"text": sentence + " "})
                    yield from synth(sentence)
                remainder = chunker.flush()
                if remainder:
                    yield _sse("delta", {"text": remainder})
                    yield from synth(remainder)
    except LLMUnavailableError as exc:
        yield _sse("error", {"error": "llm_unavailable", "message": str(exc)})
        return
    except LLMError as exc:
        yield _sse("error", {"error": "llm_error", "message": str(exc)})
        return

    if assistant_text is None:
        return

    timing["llm_ms"] = round((time.perf_counter() - agent_start) * 1000, 2)
    timing["tts_ms"] = round(tts_ms, 2)
    timing["total_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    log_voice_turn(
        {
            "event": "voice_turn_completed",
            "mode": "agent",
            "session_id": session_id,
            "audio_duration_sec": audio_duration_sec,
            "transcript_chars": transcript_chars,
            "response_chars": len(assistant_text),
            **{k: timing.get(k, 0) for k in (
                "audio_save_ms", "audio_normalization_ms", "stt_ms",
                "llm_ms", "tts_ms", "first_audio_ms", "total_ms",
            )},
            "stt_model": config.STT_MODEL_NAME,
            "llm_model": config.OLLAMA_MODEL,
            "tts_engine": "piper",
        }
    )

    yield _sse(
        "done",
        {
            "assistant_response": assistant_text,
            "timing": TimingInfo(**timing).model_dump(),
            "metadata": TurnMetadata(
                stt_model=config.STT_MODEL_NAME,
                llm_model=config.OLLAMA_MODEL,
                tts_engine="piper",
                audio_duration_sec=audio_duration_sec,
            ).model_dump(),
        },
    )


@router.post("/voice-turn/stream")
async def voice_turn_stream(
    request: Request,
    audio_file: UploadFile = File(...),
    session_id: str | None = Form(None),
):
    """Streaming variant: emits SSE events as the reply is produced.

    Events: meta -> transcript -> (delta | audio)* -> done, or error.
    STT is still full-utterance; only the response (LLM + TTS) streams.
    """
    app = request.app
    stt = app.state.stt
    llm = app.state.llm
    tts = app.state.tts

    session_id = session_service.ensure_session(session_id)
    audio_bytes = await audio_file.read()
    original_name = audio_file.filename

    def generate() -> Iterator[str]:
        t0 = time.perf_counter()
        timing: dict[str, float] = {}
        yield _sse("meta", {"session_id": session_id})

        if not audio_bytes:
            yield _sse("error", {"error": "empty_audio", "message": "Empty audio."})
            return

        # 1) Save + 2) normalize.
        try:
            raw_path = file_utils.unique_path(
                config.UPLOAD_DIR, Path(original_name or "").suffix or ".bin"
            )
            with timer("audio_save_ms", timing):
                raw_path.write_bytes(audio_bytes)
            normalized_path = file_utils.unique_path(config.NORMALIZED_DIR, ".wav")
            with timer("audio_normalization_ms", timing):
                audio_meta = normalize_audio(raw_path, normalized_path)
        except AudioError as exc:
            yield _sse("error", {"error": "audio_normalization_failed", "message": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - boundary
            yield _sse("error", {"error": "save_failed", "message": str(exc)})
            return

        # 3) STT (full utterance).
        try:
            with timer("stt_ms", timing):
                stt_result = stt.transcribe(str(normalized_path))
        except STTError as exc:
            yield _sse("error", {"error": "stt_failed", "message": str(exc)})
            return
        if not stt_result.text.strip():
            yield _sse("error", {"error": "empty_transcript", "message": "No speech detected."})
            return
        yield _sse("transcript", {"text": stt_result.text})

        # 4) Agent (LLM + tools) -> 5) per-sentence TTS.
        if config.TOOLS_ENABLED:
            yield from _emit_agent_stream(
                agent_service.run_agent(llm, session_id, stt_result.text),
                tts=tts,
                t0=t0,
                timing=timing,
                session_id=session_id,
                audio_duration_sec=audio_meta.duration_sec,
                transcript_chars=len(stt_result.text),
            )
            return

        # --- no-tools fallback: token-by-token streaming ---
        chunker = SentenceChunker()
        assistant_parts: list[str] = []
        tts_ms = 0.0
        llm_start = time.perf_counter()

        def synth(sentence: str) -> Iterator[str]:
            nonlocal tts_ms
            try:
                chunk_path = file_utils.unique_path(config.TTS_OUTPUT_DIR, ".wav")
                s = time.perf_counter()
                tts.synthesize(sentence, chunk_path)
                tts_ms += (time.perf_counter() - s) * 1000
            except TTSError as exc:
                yield _sse("error", {"error": "tts_failed", "message": str(exc)})
                return
            if "first_audio_ms" not in timing:
                timing["first_audio_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            yield _sse("audio", {"url": f"/api/audio/{chunk_path.name}", "text": sentence})

        try:
            for delta in llm.generate_response_stream(session_id, stt_result.text):
                assistant_parts.append(delta)
                yield _sse("delta", {"text": delta})
                for sentence in chunker.feed(delta):
                    yield from synth(sentence)
        except LLMUnavailableError as exc:
            yield _sse("error", {"error": "llm_unavailable", "message": str(exc)})
            return
        except LLMError as exc:
            yield _sse("error", {"error": "llm_error", "message": str(exc)})
            return

        remainder = chunker.flush()
        if remainder:
            yield from synth(remainder)

        timing["llm_ms"] = round((time.perf_counter() - llm_start) * 1000, 2)
        timing["tts_ms"] = round(tts_ms, 2)
        timing["total_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        assistant_text = "".join(assistant_parts).strip()

        log_voice_turn(
            {
                "event": "voice_turn_completed",
                "mode": "stream",
                "session_id": session_id,
                "audio_duration_sec": audio_meta.duration_sec,
                "transcript_chars": len(stt_result.text),
                "response_chars": len(assistant_text),
                **{k: timing.get(k, 0) for k in (
                    "audio_save_ms", "audio_normalization_ms", "stt_ms",
                    "llm_ms", "tts_ms", "first_audio_ms", "total_ms",
                )},
                "stt_model": config.STT_MODEL_NAME,
                "llm_model": config.OLLAMA_MODEL,
                "tts_engine": "piper",
            }
        )

        yield _sse(
            "done",
            {
                "assistant_response": assistant_text,
                "timing": TimingInfo(**timing).model_dump(),
                "metadata": TurnMetadata(
                    stt_model=config.STT_MODEL_NAME,
                    llm_model=config.OLLAMA_MODEL,
                    tts_engine="piper",
                    audio_duration_sec=audio_meta.duration_sec,
                ).model_dump(),
            },
        )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/voice-turn/resume")
async def voice_turn_resume(request: Request, body: ResumeRequest):
    """Continue a paused agent turn after the user approves/denies an action."""
    tts = request.app.state.tts

    def generate() -> Iterator[str]:
        t0 = time.perf_counter()
        timing: dict[str, float] = {}
        yield from _emit_agent_stream(
            agent_service.resume_agent(body.pending_id, body.approved),
            tts=tts,
            t0=t0,
            timing=timing,
            session_id=body.session_id or "",
            audio_duration_sec=0,
        )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
