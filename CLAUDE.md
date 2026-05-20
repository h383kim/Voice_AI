# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

**LocalVoiceLab** is an implemented, local-first Voice AI agent (no paid APIs). `Design_Doc.md`
is the original spec and roadmap; the code now covers the MVP **plus** a real-time iteration:

- **Turn-based mode** — `POST /api/voice-turn`: upload/record a clip → JSON with transcript,
  assistant text, an audio URL, and per-stage latency. (File-upload fallback.)
- **Real-time mode** — `POST /api/voice-turn/stream` (SSE) + client-side VAD: hands-free,
  auto-endpointed, streamed reply (audio sentence-by-sentence), with barge-in.
- **Tool-calling agent** — the assistant performs macOS actions (notify/open_url/open_app/
  music) via Ollama function calling. Hybrid safety: notify/music auto-run; open_url/open_app
  need UI Allow/Deny (two-step `tool_request` → `/api/voice-turn/resume`).

## Architecture

Pipeline, one service module per stage (`backend/app/services/`):

```
Browser → FastAPI → ffmpeg normalize (mono,16kHz,WAV) → STT (faster-whisper)
  → LLM (Ollama) → TTS (Piper) → audio → browser
```

- **Endpoints** (`backend/app/api/routes.py`): `POST /api/voice-turn` (JSON),
  `POST /api/voice-turn/stream` (SSE: `meta`→`transcript`→`tool`/`tool_request`/`delta`/`audio`
  →`done`, or `error`), `POST /api/voice-turn/resume` (`{pending_id,approved,session_id}` →
  same SSE event types), `GET /api/audio/{filename}` (serves WAVs incl. per-sentence chunks;
  path-traversal guarded), `GET /api/health`.
- **Streaming flow:** STT is **full-utterance** ("middle path" — no streaming STT). After the
  `transcript` event a **router** (`llm_service.classify_needs_tools`, model `ROUTER_MODEL`)
  classifies ACTION vs CHAT. ACTION → `agent_service.run_agent` (function calling); CHAT →
  `llm_service.generate_response_stream` (token-by-token, no tools). Either way,
  `sentence_chunker.SentenceChunker` splits the answer and each sentence is synthesized
  immediately → `audio` event. Key metrics: `router_ms`, `first_audio_ms`.
- **Agent loop** (`backend/app/services/agent_service.py`): calls `llm_service.chat(messages,
  tools=...)` (non-stream, for reliable `tool_calls`), executes `tools_service` actions, loops
  (capped by `TOOLS_MAX_ITERS`), yields typed events (`ToolStarted/ToolResult/ToolConfirm/Done`)
  the route maps to SSE. Confirm-required tools pause: state saved in `PENDING[pending_id]`, a
  `tool_request` is emitted, and `resume_agent(pending_id, approved)` continues the turn.
- **Tools** (`backend/app/services/tools_service.py`): registry with JSON schemas + handlers;
  `requires_confirmation` flag per tool; macOS via `osascript`/`open` with **argv-passed args
  (no shell/AppleScript injection)**; `open_url` validates scheme, `open_app` uses
  `OPEN_APP_ALLOWLIST`. Tools: `notify`, `music` (auto); `find_contact` (auto, read-only,
  searches macOS Contacts); `open_url`, `open_app`, `send_imessage` (confirm). **Messaging:** two
  paths — a NAME (model calls `find_contact` → handle) or a directly-spoken PHONE NUMBER (model
  passes it straight to `send_imessage`). `_normalize_handle` converts spelled-out digits, strips
  formatting, and applies `DEFAULT_COUNTRY_CODE` (e.g. `+82`) to national-format numbers; it
  normalizes-then-validates. The send AppleScript returns `OK`/`ERR <n>: <msg>` so failures aren't
  silent (`IMESSAGE_ENABLED` gates it). Contacts + Messages need macOS Automation permission.
- **Warm TTS:** `tts_service.TTSService` loads `PiperVoice` once (in-process) and reuses it via
  `synthesize_wav` — needed so per-sentence streaming synthesis is fast.
- **Session memory:** in-memory `dict[session_id, list[messages]]`, last ~6 (`session_service`).
  Not persisted. Frontend keeps `session_id` across turns (lost on page reload).
- **Latency:** `timing_service.timer(...)` ctx manager; one JSONL record per turn →
  `data/logs/voice_turns.jsonl`.
- **Storage:** local filesystem only — `data/{uploads,normalized,tts_outputs,logs}/`.

## Stack

- **Backend:** Python + FastAPI + uvicorn, deps via `uv` (venv at `.venv/`).
- **STT:** `faster-whisper`. Default `Systran/faster-whisper-small.en`, cpu/int8.
- **LLM:** Ollama HTTP API `http://localhost:11434` (`/api/chat`), model `llama3.2:3b`.
- **TTS:** `piper-tts` pip package, **in-process** via `from piper import PiperVoice`
  (not a CLI binary). Voice model in `models/piper/` (downloaded by `scripts/setup_piper.sh`).
- **Frontend:** React + Vite + TS. VAD via `@ricky0123/vad-web` (Silero, lazy-loaded). Key files:
  `src/hooks/useConversation.ts` (state machine + audio queue + barge-in), `src/api.ts`
  (`streamVoiceTurn` SSE parser), `src/wav.ts` (Float32→WAV), `src/components/MicControl.tsx`.

## Conventions / Gotchas

- **TTS:** sanitize text before synth; the voice is loaded lazily/once — don't reload per call.
- **Audio:** always normalize to mono/16 kHz/WAV via ffmpeg before STT (idempotent on already-16k WAV).
- **Streaming endpoint** uses a **sync generator** in `StreamingResponse` (Starlette threadpools it);
  `requests`/Piper are blocking, which is fine there.
- **Barge-in** is client-driven (abort the fetch + stop playback); the server may briefly keep
  generating before it notices the disconnect (acceptable for local single-user use).
- **Config:** env vars w/ defaults in `config.py` (mirror `.env.example`).
- **Runtime deps:** `ffmpeg` on PATH, Ollama running with the model pulled, Piper voice model present.

## Commands

```bash
# Setup
uv venv --python 3.12 && uv pip install -e ".[dev]"
bash scripts/setup_piper.sh
cd frontend && npm install && cd ..

# Run (separate terminals)
bash scripts/run_backend.sh        # uvicorn :8000  (first run downloads small.en ~480MB)
bash scripts/run_frontend.sh       # vite :5173
ollama serve && ollama pull llama3.2:3b

# Tip: faster STT for dev — STT_MODEL_NAME=Systran/faster-whisper-tiny.en bash scripts/run_backend.sh

# Tests
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -m pytest backend/tests/test_stream_route.py   # single file
```
