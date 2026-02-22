"""
TTS (Text-to-Speech) Routes for Orderbot
=============================================

This module contains endpoints for text-to-speech synthesis, supporting
the voice interface of the ordering system.

Endpoints:
----------
- GET /tts/voices: List available TTS voices
- POST /tts/synthesize: Convert text to speech audio

Purpose:
--------
These endpoints enable:
1. Voice responses in phone/voice interfaces
2. Audio previews in admin testing
3. Integration with VAPI and other voice platforms

TTS Providers:
--------------
The system supports multiple TTS providers (configured via environment):
- ElevenLabs: High-quality neural voices
- Others can be added via the provider abstraction

Voice Selection:
----------------
The /voices endpoint returns available voices for the configured provider.
Each voice has an ID, name, and language/accent information.

Audio Format:
-------------
The /synthesize endpoint returns audio/mpeg (MP3) content by default.
This is widely compatible with web browsers and voice platforms.

Rate Limiting:
--------------
Consider rate limiting TTS endpoints in production as synthesis
can be computationally expensive.

Usage:
------
    # Get available voices
    GET /tts/voices
    {
        "voices": [
            {"id": "voice_123", "name": "Sarah", "language": "en-US"},
            ...
        ]
    }

    # Synthesize speech
    POST /tts/synthesize
    {
        "text": "Hello, welcome to our restaurant!",
        "voice": "voice_123",
        "speed": 1.0
    }
    # Returns: audio/mpeg binary data
"""

import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.tts import get_configured_tts_provider, BaseTTSProvider
from ..services.tts_cache import get_cached_audio


logger = logging.getLogger(__name__)


# Router definition
tts_router = APIRouter(prefix="/tts", tags=["Text-to-Speech"])


# =============================================================================
# Request/Response Models
# =============================================================================

class SynthesizeRequest(BaseModel):
    """Request model for speech synthesis."""
    text: str
    voice: str | None = None
    speed: float = 1.0


class VoiceInfo(BaseModel):
    """Information about an available voice."""
    id: str
    name: str
    gender: str | None = None
    accent: str | None = None
    description: str | None = None


class VoicesResponse(BaseModel):
    """Response containing list of available voices."""
    provider: str = "openai"
    voices: list[VoiceInfo]
    default_voice: str | None = None


# =============================================================================
# TTS Endpoints
# =============================================================================

@tts_router.get("/voices", response_model=VoicesResponse)
async def list_voices(db: Session = Depends(get_db)) -> VoicesResponse:
    """
    List available TTS voices.

    Returns voices supported by the configured TTS provider,
    plus the admin-configured default voice (if any).
    """
    try:
        provider = get_configured_tts_provider(db)
        voices = provider.voices

        # Read the company's default voice setting
        default_voice = None
        try:
            from ..services.store_service import get_or_create_company
            company = get_or_create_company(db)
            default_voice = company.tts_default_voice
        except (ImportError, OSError, ValueError, TypeError) as e:
            logger.debug("Could not read default voice from company: %s", e)

        return VoicesResponse(
            provider=provider.name,
            voices=[
                VoiceInfo(
                    id=v.id,
                    name=v.name,
                    gender=v.gender,
                    accent=v.accent,
                    description=v.description,
                )
                for v in voices
            ],
            default_voice=default_voice,
        )
    except ValueError as e:
        logger.warning("TTS provider error: %s", str(e))
        raise HTTPException(status_code=503, detail=str(e))
    except (ConnectionError, TimeoutError, RuntimeError, OSError) as e:
        logger.error("Failed to list voices: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to list voices")


@tts_router.post("/synthesize")
async def synthesize_speech(req: SynthesizeRequest, db: Session = Depends(get_db)):
    """
    Convert text to speech audio.

    Takes text and optional voice/speed parameters, returns MP3 audio.
    The audio is streamed directly without caching.

    Args:
        req: Synthesis request with text, voice ID, and speed

    Returns:
        Binary audio/mpeg response
    """
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="Text is required")

    if len(req.text) > 5000:
        raise HTTPException(status_code=400, detail="Text too long (max 5000 chars)")

    try:
        provider = get_configured_tts_provider(db)

        audio_bytes = await provider.synthesize(
            text=req.text,
            voice_id=req.voice,
            speed=req.speed,
        )

        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline",
                "Cache-Control": "no-cache",
            }
        )
    except ValueError as e:
        logger.warning("TTS validation error: %s", str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except (ConnectionError, TimeoutError, RuntimeError, OSError) as e:
        logger.error("TTS synthesis failed: %s", str(e))
        raise HTTPException(status_code=500, detail="Speech synthesis failed")


@tts_router.get("/audio/{audio_id}")
async def get_prefetched_audio(audio_id: str) -> Response:
    """
    Retrieve pre-synthesized TTS audio by ID.

    Audio is prefetched during reply generation so it's ready by the time
    the frontend requests it. Falls back to on-demand synthesis if not found.
    """
    audio_bytes = await asyncio.to_thread(get_cached_audio, audio_id)
    if audio_bytes is None:
        raise HTTPException(status_code=404, detail="Audio not found or expired")
    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-cache"},
    )
