"""
STT (Speech-to-Text) Routes for Orderbot
=============================================

Provides a backend transcription endpoint using OpenAI Whisper,
enabling voice input in browsers that lack the Web Speech API
(Firefox, Safari).

Endpoints:
----------
- POST /stt/transcribe: Convert uploaded audio to text
"""

import logging
import os

from fastapi import APIRouter, HTTPException, UploadFile

import openai

logger = logging.getLogger(__name__)

stt_router = APIRouter(prefix="/stt", tags=["Speech-to-Text"])

ALLOWED_MIME_PREFIXES = ("audio/webm", "audio/ogg", "audio/mp4", "audio/wav", "audio/mpeg")
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB (Whisper API limit)


@stt_router.post("/transcribe")
async def transcribe_audio(audio: UploadFile) -> dict:
    """Transcribe an audio file using OpenAI Whisper.

    Accepts audio uploads (webm, ogg, mp4, wav, mpeg) up to 25 MB
    and returns the transcribed text.

    Args:
        audio: The uploaded audio file.

    Returns:
        dict with ``text`` key containing the transcription.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="Speech-to-text service not configured")

    # Validate MIME type
    content_type = audio.content_type or ""
    if not any(content_type.startswith(prefix) for prefix in ALLOWED_MIME_PREFIXES):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format: {content_type}. "
                   f"Accepted: webm, ogg, mp4, wav, mpeg.",
        )

    # Read and validate size
    data = await audio.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Audio file too large (max 25 MB)")

    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Audio file is empty")

    # Map content type to a file extension Whisper accepts
    ext_map = {
        "audio/webm": "webm",
        "audio/ogg": "ogg",
        "audio/mp4": "mp4",
        "audio/wav": "wav",
        "audio/mpeg": "mp3",
    }
    ext = "webm"
    for prefix, extension in ext_map.items():
        if content_type.startswith(prefix):
            ext = extension
            break

    try:
        client = openai.OpenAI(api_key=api_key)
        transcription = client.audio.transcriptions.create(
            model="whisper-1",
            file=(f"audio.{ext}", data),
        )
        return {"text": transcription.text}
    except openai.AuthenticationError:
        logger.error("OpenAI API key invalid for STT")
        raise HTTPException(status_code=503, detail="Speech-to-text service not configured")
    except (openai.APIConnectionError, openai.APITimeoutError) as e:
        logger.error("OpenAI STT connection error: %s", e)
        raise HTTPException(status_code=500, detail="Speech-to-text service unavailable")
    except (openai.BadRequestError, openai.APIStatusError) as e:
        logger.error("OpenAI STT API error: %s", e)
        raise HTTPException(status_code=500, detail="Transcription failed")
