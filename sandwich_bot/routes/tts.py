"""
TTS (Text-to-Speech) Routes for Sandwich Bot
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

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from ..tts import get_tts_provider


logger = logging.getLogger(__name__)

# Router definition
tts_router = APIRouter(prefix="/tts", tags=["Text-to-Speech"])


# =============================================================================
# Request/Response Models
# =============================================================================

class SynthesizeRequest(BaseModel):
    """Request model for speech synthesis."""
    text: str
    voice: Optional[str] = None
    speed: float = 1.0


class VoiceInfo(BaseModel):
    """Information about an available voice."""
    id: str
    name: str
    language: Optional[str] = None


class VoicesResponse(BaseModel):
    """Response containing list of available voices."""
    voices: list[VoiceInfo]


# =============================================================================
# TTS Endpoints
# =============================================================================

@tts_router.get("/voices", response_model=VoicesResponse)
async def list_voices() -> VoicesResponse:
    """
    List available TTS voices.

    Returns voices supported by the configured TTS provider.
    Voice availability depends on provider configuration.
    """
    try:
        provider = get_tts_provider()
        voices = await provider.list_voices()

        return VoicesResponse(
            voices=[
                VoiceInfo(
                    id=v.get("id", ""),
                    name=v.get("name", "Unknown"),
                    language=v.get("language"),
                )
                for v in voices
            ]
        )
    except ValueError as e:
        logger.warning("TTS provider error: %s", str(e))
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("Failed to list voices: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to list voices")


@tts_router.post("/synthesize")
async def synthesize_speech(req: SynthesizeRequest):
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
        provider = get_tts_provider()

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
    except Exception as e:
        logger.error("TTS synthesis failed: %s", str(e))
        raise HTTPException(status_code=500, detail="Speech synthesis failed")
