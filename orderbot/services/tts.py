# orderbot/tts.py
"""
Text-to-Speech provider abstraction layer.

This module provides a pluggable TTS system that makes it easy to swap
between different TTS providers (OpenAI, ElevenLabs, Cartesia, etc.)

Usage:
    from orderbot.tts import get_tts_provider

    provider = get_tts_provider()
    audio_bytes = await provider.synthesize("Hello, welcome to Sammy's Subs!")
"""

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from collections.abc import AsyncIterator

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")


class TTSProvider(str, Enum):
    """Supported TTS providers."""
    OPENAI = "openai"
    ELEVENLABS = "elevenlabs"
    CARTESIA = "cartesia"
    GOOGLE = "google"
    BROWSER = "browser"  # Web Speech API (client-side only)


@dataclass
class Voice:
    """Represents a TTS voice option."""
    id: str
    name: str
    gender: str | None = None
    accent: str | None = None
    description: str | None = None


class BaseTTSProvider(ABC):
    """Abstract base class for TTS providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for display."""

    @property
    @abstractmethod
    def voices(self) -> list[Voice]:
        """List of available voices."""

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float = 1.0,
    ) -> bytes:
        """
        Synthesize text to speech.

        Args:
            text: The text to convert to speech
            voice_id: Voice identifier (provider-specific)
            speed: Speech speed multiplier (0.25 to 4.0)

        Returns:
            Audio data as bytes (MP3 format)
        """

    async def synthesize_stream(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float = 1.0,
    ) -> AsyncIterator[bytes]:
        """
        Synthesize text to speech with streaming.

        Default implementation buffers the full response.
        Providers can override for true streaming support.
        """
        audio = await self.synthesize(text, voice_id, speed)
        yield audio


class OpenAITTSProvider(BaseTTSProvider):
    """OpenAI Text-to-Speech provider."""

    # Available OpenAI TTS voices with descriptions
    VOICES = [
        Voice("alloy", "Alloy", "neutral", "American", "Neutral and balanced"),
        Voice("echo", "Echo", "male", "American", "Warm and confident"),
        Voice("fable", "Fable", "male", "British", "Expressive and dramatic"),
        Voice("onyx", "Onyx", "male", "American", "Deep and authoritative"),
        Voice("nova", "Nova", "female", "American", "Friendly and upbeat"),
        Voice("shimmer", "Shimmer", "female", "American", "Clear and pleasant"),
    ]

    def __init__(self, api_key: str | None = None, model: str = "tts-1"):
        """
        Initialize OpenAI TTS provider.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: TTS model to use ("tts-1" for speed, "tts-1-hd" for quality)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key not found. Set OPENAI_API_KEY environment variable.")

        self.model = model
        self.default_voice = "nova"  # Friendly female voice, good for customer service

        # Import OpenAI client
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=self.api_key)

        logger.debug("OpenAI TTS provider initialized with model: %s", model)

    @property
    def name(self) -> str:
        return "OpenAI"

    @property
    def voices(self) -> list[Voice]:
        return self.VOICES

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float = 1.0,
    ) -> bytes:
        """Synthesize text using OpenAI TTS API."""
        voice = voice_id or self.default_voice

        # Validate voice
        valid_voices = [v.id for v in self.VOICES]
        if voice not in valid_voices:
            logger.warning("Invalid voice '%s', using default '%s'", voice, self.default_voice)
            voice = self.default_voice

        # Clamp speed to valid range
        speed = max(0.25, min(4.0, speed))

        logger.debug("Synthesizing %d chars with voice '%s', speed %.1f", len(text), voice, speed)

        response = await self.client.audio.speech.create(
            model=self.model,
            voice=voice,
            input=text,
            speed=speed,
            response_format="mp3",
        )

        # Read the response content
        audio_bytes = response.content
        logger.debug("Generated %d bytes of audio", len(audio_bytes))

        return audio_bytes


class ElevenLabsTTSProvider(BaseTTSProvider):
    """
    ElevenLabs Text-to-Speech provider.

    ElevenLabs offers high quality voices with more customization.
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY")
        if not self.api_key:
            raise ValueError("ElevenLabs API key not found. Set ELEVENLABS_API_KEY environment variable.")

        self._voices = [
            Voice("21m00Tcm4TlvDq8ikWAM", "Rachel", "female", "American", "Calm and professional"),
            Voice("AZnzlk1XvdvUeBnXmlld", "Domi", "female", "American", "Strong and confident"),
            Voice("EXAVITQu4vr4xnSDxMaL", "Bella", "female", "American", "Soft and gentle"),
            Voice("ErXwobaYiN019PkySvjV", "Antoni", "male", "American", "Friendly and conversational"),
            Voice("MF3mGyEYCl7XYWbV9V6O", "Elli", "female", "American", "Young and cheerful"),
            Voice("TxGEqnHWrfWFTfGW9XjX", "Josh", "male", "American", "Deep and narrative"),
        ]

        logger.debug("ElevenLabs TTS provider initialized")

    @property
    def name(self) -> str:
        return "ElevenLabs"

    @property
    def voices(self) -> list[Voice]:
        return self._voices

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float = 1.0,
    ) -> bytes:
        """Synthesize text using ElevenLabs API."""
        import aiohttp

        voice = voice_id or self._voices[0].id

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": self.api_key,
        }
        data = {
            "text": text,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.5,
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data, headers=headers) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise RuntimeError(f"ElevenLabs API error: {error_text}")
                return await response.read()


class CartesiaTTSProvider(BaseTTSProvider):
    """
    Cartesia Text-to-Speech provider.

    Uses the Cartesia Sonic model for high-quality, low-latency speech synthesis.
    """

    # Curated voice list from Cartesia's voice library (verified UUIDs)
    VOICES = [
        Voice("a0e99841-438c-4a64-b679-ae501e7d6091", "Barbershop Man", "male", "American", "Warm and friendly"),
        Voice("b7d50908-b17c-442d-ad8d-810c63997ed9", "California Girl", "female", "American", "Upbeat and casual"),
        Voice("c2ac25f9-ecc4-4f56-9095-651354df60c0", "Commercial Lady", "female", "American", "Professional and clear"),
        Voice("e00d0e4c-a5c8-443f-a8a3-473eb9a62355", "Friendly Sidekick", "male", "American", "Energetic and cheerful"),
        Voice("79a125e8-cd45-4c13-8a67-188112f4dd22", "British Lady", "female", "British", "Polished and articulate"),
        Voice("69267136-1bdc-412f-ad78-0caad210fb40", "Friendly Reading Man", "male", "American", "Calm and clear"),
    ]

    def __init__(self, api_key: str | None = None):
        """
        Initialize Cartesia TTS provider.

        Args:
            api_key: Cartesia API key (defaults to CARTESIA_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("CARTESIA_API_KEY")
        if not self.api_key:
            raise ValueError("Cartesia API key not found. Set CARTESIA_API_KEY environment variable.")

        from cartesia import AsyncCartesia
        self.client = AsyncCartesia(api_key=self.api_key)

        logger.debug("Cartesia TTS provider initialized")

    @property
    def name(self) -> str:
        return "Cartesia"

    @property
    def voices(self) -> list[Voice]:
        return self.VOICES

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float = 1.0,
    ) -> bytes:
        """Synthesize text using Cartesia API."""
        voice = voice_id or self.VOICES[0].id

        # Validate voice is a known ID, fall back to first voice
        valid_ids = [v.id for v in self.VOICES]
        if voice not in valid_ids:
            logger.warning("Unknown Cartesia voice '%s', using default", voice)
            voice = self.VOICES[0].id

        logger.debug("Synthesizing %d chars with Cartesia voice '%s'", len(text), voice)

        response = await self.client.tts.bytes(
            model_id="sonic-3",
            transcript=text,
            voice={"mode": "id", "id": voice},
            output_format={
                "container": "mp3",
                "bit_rate": 128000,
                "sample_rate": 44100,
            },
        )

        # Collect all chunks into a single bytes object
        chunks = []
        async for chunk in response:
            chunks.append(chunk)
        audio_bytes = b"".join(chunks)

        logger.debug("Generated %d bytes of Cartesia audio", len(audio_bytes))
        return audio_bytes


# Provider registry
_PROVIDERS: dict[TTSProvider, type[BaseTTSProvider]] = {
    TTSProvider.OPENAI: OpenAITTSProvider,
    TTSProvider.ELEVENLABS: ElevenLabsTTSProvider,
    TTSProvider.CARTESIA: CartesiaTTSProvider,
}

# Cached provider instance and its type
_provider_instance: BaseTTSProvider | None = None
_provider_type: TTSProvider | None = None


def _resolve_provider_type(provider_name: str | TTSProvider | None) -> TTSProvider:
    """Resolve a provider name string or enum to a TTSProvider enum value."""
    if provider_name is None:
        provider_name = os.getenv("TTS_PROVIDER", "openai").lower()

    if isinstance(provider_name, TTSProvider):
        return provider_name

    # Handle string names
    name = provider_name.strip().lower()
    try:
        return TTSProvider(name)
    except ValueError:
        logger.warning("Unknown TTS provider '%s', defaulting to OpenAI", name)
        return TTSProvider.OPENAI


def invalidate_tts_provider() -> None:
    """Reset the cached TTS provider singleton so the next call creates a new one."""
    global _provider_instance, _provider_type
    _provider_instance = None
    _provider_type = None
    logger.info("TTS provider cache invalidated")


def get_tts_provider(
    provider_type: str | TTSProvider | None = None,
    **kwargs,
) -> BaseTTSProvider:
    """
    Get a TTS provider instance.

    Uses a singleton pattern - the same provider instance is returned
    for subsequent calls (unless provider_type changes).

    Args:
        provider_type: Which provider to use. Accepts a TTSProvider enum or a
            string like "openai", "elevenlabs", "cartesia". Defaults to
            TTS_PROVIDER env var or OpenAI.
        **kwargs: Additional arguments passed to the provider constructor

    Returns:
        A TTS provider instance
    """
    global _provider_instance, _provider_type

    resolved = _resolve_provider_type(provider_type)

    # Return cached instance if same provider type
    if _provider_instance is not None and _provider_type == resolved:
        return _provider_instance

    # Create new provider instance
    provider_class = _PROVIDERS.get(resolved)
    if provider_class is None:
        raise ValueError(f"Unsupported TTS provider: {resolved}")

    try:
        _provider_instance = provider_class(**kwargs)
        _provider_type = resolved
        logger.info("Initialized TTS provider: %s", _provider_instance.name)
    except (ConnectionError, TimeoutError, OSError, ValueError, ImportError) as e:
        logger.error("Failed to initialize TTS provider %s: %s", resolved, e)
        raise

    return _provider_instance


def get_configured_tts_provider(db: "Session") -> BaseTTSProvider:
    """Get TTS provider using the Company DB setting.

    Reads ``company.tts_provider`` from the database and returns the
    corresponding provider instance.  Falls back to the environment
    variable / OpenAI default when the company row cannot be read.

    Args:
        db: An open SQLAlchemy session.

    Returns:
        A ready-to-use TTS provider.
    """
    provider_name = None
    try:
        from .store_service import get_or_create_company

        company = get_or_create_company(db)
        provider_name = company.tts_provider
    except (ImportError, OSError, ValueError, TypeError) as e:
        logger.debug("Could not read TTS provider from company: %s", e)
    return get_tts_provider(provider_name)
