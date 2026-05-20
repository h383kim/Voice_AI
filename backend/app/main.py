"""FastAPI application entrypoint for LocalVoiceLab.

On startup it builds the STT / LLM / TTS services into app.state. The STT model
is loaded eagerly (it can take a moment on first run); if it fails to load the
server still starts and /api/health reports stt_loaded=false.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .api.routes import router
from .services.llm_service import LLMService
from .services.tts_service import TTSService

logger = logging.getLogger("localvoicelab")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()

    app.state.stt = None
    try:
        from .services.stt_service import STTService

        logger.info("Loading STT model %s ...", config.STT_MODEL_NAME)
        app.state.stt = STTService(
            config.STT_MODEL_NAME, config.STT_DEVICE, config.STT_COMPUTE_TYPE
        )
        logger.info("STT model loaded.")
    except Exception as exc:  # noqa: BLE001 - keep server up, report via health
        logger.warning("Failed to load STT model: %s", exc)

    app.state.llm = LLMService(
        config.OLLAMA_BASE_URL, config.OLLAMA_MODEL, router_model=config.ROUTER_MODEL
    )
    app.state.tts = TTSService(config.PIPER_VOICE_MODEL)
    try:
        logger.info("Loading Piper voice %s ...", config.PIPER_VOICE_MODEL)
        app.state.tts.load()
        logger.info("Piper voice loaded.")
    except Exception as exc:  # noqa: BLE001 - keep server up, report via health
        logger.warning("Failed to load Piper voice: %s", exc)

    yield


app = FastAPI(title="LocalVoiceLab", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root():
    return {"service": "LocalVoiceLab", "docs": "/docs", "health": "/api/health"}
