# LocalVoiceLab

A local-first **Voice AI agent**. Talk to it hands-free in the browser; it
transcribes your speech, asks a local LLM, synthesizes the reply, and speaks back
— streaming the answer so audio starts almost immediately. No paid APIs.

Two modes:
- **Real-time (default)** — hands-free with voice-activity detection (VAD): just
  talk, it auto-detects when you stop, streams the reply as it's generated, and you
  can **interrupt by speaking** (barge-in).
- **Turn-based** — upload (or the old record-and-submit) → one JSON response with
  transcript, assistant text, an audio URL, and per-stage latency.

> Built from `Design_Doc.md` (MVP) + the streaming/VAD iteration. See the design
> doc for the full roadmap (streaming STT, WebRTC, RAG, eval, etc.).

## Architecture

```
Browser (mic + Silero VAD)            Browser (file upload)
   │ auto-endpointed utterance           │ multipart audio
   ▼                                      ▼
FastAPI  ──►  ffmpeg normalize (mono, 16 kHz, WAV)
         ──►  STT  (faster-whisper, full utterance)
         ──►  LLM  (Ollama, streamed tokens)
         ──►  TTS  (piper-tts, in-process, per sentence)
   │
   ├─ stream:  SSE meta → transcript → delta/audio… → done  (audio plays as it arrives)
   └─ turn:    JSON { transcript, assistant_response, audio_url, timing, metadata }
```

- `POST /api/voice-turn/stream` — SSE; streams transcript, text deltas, and audio chunks.
- `POST /api/voice-turn` — audio in, full assistant turn out (JSON).
- `GET /api/audio/{filename}` — serves generated WAVs (incl. per-sentence stream chunks).
- `GET /api/health` — reports whether STT/LLM/TTS are ready.

## Prerequisites

- **Python** ≥ 3.11 and [`uv`](https://docs.astral.sh/uv/)
- **Node** ≥ 18 (for the frontend)
- **ffmpeg** (and `ffprobe`) on your PATH
  - macOS: `brew install ffmpeg`
- **Ollama** for the LLM (installed separately, see below)

## Setup

```bash
# 1. Backend deps (creates .venv with a managed Python)
uv venv --python 3.12
uv pip install -e ".[dev]"

# 2. Piper voice model (the piper-tts engine ships with the venv)
bash scripts/setup_piper.sh

# 3. Ollama (LLM) — install, start, and pull the model
brew install ollama      # or download from https://ollama.com
ollama serve             # in its own terminal
ollama pull llama3.2:3b

# 4. Frontend deps
cd frontend && npm install && cd ..
```

Copy `.env.example` to `.env` to override any defaults (model names, paths, port).

## Run

```bash
# Backend (http://localhost:8000, Swagger at /docs)
bash scripts/run_backend.sh

# Frontend (http://localhost:5173)
bash scripts/run_frontend.sh
```

Open http://localhost:5173 and click **Start conversation**, then just talk. It
detects when you stop, streams the spoken reply (audio begins within ~1s while the
text streams in), and you can **interrupt by speaking** to start a new turn. The
status pill cycles Listening → Thinking → Speaking. Prefer not to use the mic? Use
**upload a clip** for a one-off turn.

> **Use headphones.** With laptop speakers, the mic can pick up the assistant's own
> voice and self-interrupt. Browser echo cancellation + a short grace window help,
> but headphones eliminate it. The mic only works on a secure origin —
> `localhost` counts, so dev is fine.

The first backend start downloads the faster-whisper model (~480 MB for
`small.en`); subsequent starts are fast. Real-time mode needs Ollama running.

## Tests

```bash
uv run pytest backend/tests
```

Unit tests mock the model/HTTP/subprocess layers, so they need neither a
downloaded Whisper model, a running Ollama, nor Piper — only the audio test
needs `ffmpeg` (it's skipped otherwise).

## Quick API check

```bash
curl localhost:8000/api/health
curl -F audio_file=@some_speech.wav localhost:8000/api/voice-turn

# Streaming endpoint (-N disables curl buffering so you see events live):
curl -N -F audio_file=@some_speech.wav localhost:8000/api/voice-turn/stream
```

For the turn endpoint, if Ollama isn't running you get a clear `503
llm_unavailable`; the stream endpoint emits an `event: error` instead. Start Ollama
and re-run for a full turn — you'll see `event: transcript`, streaming `event:
delta`, `event: audio` (first one well before the reply finishes), then `event:
done` with `first_audio_ms`.

## Tools / system actions

The assistant can actually *do things* on your Mac via function calling
(`llama3.2:3b` + Ollama tools). When you ask it to do something, it calls a tool,
then confirms out loud.

Available actions:

| Tool | What it does | Gate |
| --- | --- | --- |
| `notify` | macOS desktop notification | auto-runs |
| `music` | play / pause / next / previous / volume (Music app) | auto-runs |
| `open_url` | open an http/https URL in the browser | **Allow/Deny** |
| `open_app` | launch an allowlisted app | **Allow/Deny** |

**Hybrid safety model:** harmless actions run immediately; side-effecting ones
(`open_url`, `open_app`) pause and wait for you to click **Allow** or **Deny** in
the UI. All actions validate inputs regardless — URLs must be http/https, and
`open_app` only launches apps in `OPEN_APP_ALLOWLIST`. Tool arguments are passed
to `osascript`/`open` as argv (never shell-interpolated), so there's no injection.

Example phrases: "send a notification that says tea is ready", "pause the music",
"set the volume to 30", "open hacker news", "open the calculator".

> Requires macOS (uses `osascript`/`open`) and Ollama running. Set
> `TOOLS_ENABLED=false` to disable tools entirely (falls back to token-by-token
> text streaming). Confirm-required actions over the API use a two-step flow:
> `POST /api/voice-turn/stream` emits `event: tool_request` and pauses, then
> `POST /api/voice-turn/resume` `{pending_id, approved}` continues the turn.

## Configuration

All settings have defaults and can be overridden via environment variables
(see `.env.example`): `STT_MODEL_NAME`, `STT_DEVICE`, `STT_COMPUTE_TYPE`,
`OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `PIPER_VOICE_MODEL`, `DATA_DIR`,
`CORS_ORIGINS`, `TOOLS_ENABLED`, `TOOLS_MAX_ITERS`, `OPEN_APP_ALLOWLIST`.
Per-turn logs are appended to `data/logs/voice_turns.jsonl`.

## Known limitations

- **STT is still full-utterance** (not streaming) — the VAD captures a whole
  utterance, then it's transcribed at once. Only the *response* (LLM + TTS) streams.
- **Barge-in is client-side:** interrupting aborts the request and stops playback,
  but the server may briefly keep generating before it notices the disconnect.
- **Self-trigger:** without headphones the mic can hear the assistant; mitigated by
  echo cancellation + a grace window, not eliminated.
- VAD assets (`@ricky0123/vad-web`) load from a CDN by default — not fully offline
  yet (self-hosting them is a documented follow-up).
- Conversation memory is in-memory (last 6 messages/session), lost on restart, and
  reset when the page reloads.
- CPU-oriented defaults; latency depends on your machine and chosen models.

## Roadmap

See the **Post-MVP Extensions** section of `Design_Doc.md` (streaming, VAD,
barge-in, WebRTC, tool use, RAG, latency observatory, STT/TTS eval, quantization
comparisons, deployment).
