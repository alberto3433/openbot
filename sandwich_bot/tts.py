# sandwich_bot/tts.py
"""
Text-to-Speech provider abstraction layer.

This module provides a pluggable TTS system that makes it easy to swap
between different TTS providers (OpenAI, ElevenLabs, Google, etc.)

Usage:
    from sandwich_bot.tts import get_tts_provider

    provider = get_tts_provider()
    audio_bytes = await provider.synthesize("Hello, welcome to Sammy's Subs!")
"""

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, List, AsyncIterator

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")


class TTSProvider(str, Enum):
    """Supported TTS providers."""
    OPENAI = "openai"
    ELEVENLABS = "elevenlabs"
    GOOGLE = "google"
    BROWSER = "browser"  # Web Speech API (client-side only)


@dataclass
class Voice:
    """Represents a TTS voice option."""
    id: str
    name: str
    gender: Optional[str] = None
    accent: Optional[str] = None
    description: Optional[str] = None


class BaseTTSProvider(ABC):
    """Abstract base class for TTS providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for display."""
        pass

    @property
    @abstractmethod
    def voices(self) -> List[Voice]:
        """List of available voices."""
        pass

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
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
        pass

    async def synthesize_stream(
        self,
        text: str,
        voice_id: Optional[str] = None,
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

    def __init__(self, api_key: Optional[str] = None, model: str = "tts-1"):
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
    def voices(self) -> List[Voice]:
        return self.VOICES

    async def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
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

    Placeholder implementation - can be expanded when needed.
    ElevenLabs offers the highest quality voices with more customization.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY")
        if not self.api_key:
            raise ValueError("ElevenLabs API key not found. Set ELEVENLABS_API_KEY environment variable.")

        # TODO: Fetch available voices from ElevenLabs API
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
    def voices(self) -> List[Voice]:
        return self._voices

    async def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
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


# Provider registry
_PROVIDERS = {
    TTSProvider.OPENAI: OpenAITTSProvider,
    TTSProvider.ELEVENLABS: ElevenLabsTTSProvider,
}

# Cached provider instance
_provider_instance: Optional[BaseTTSProvider] = None


def get_tts_provider(
    provider_type: Optional[TTSProvider] = None,
    **kwargs
) -> BaseTTSProvider:
    """
    Get a TTS provider instance.

    Uses a singleton pattern - the same provider instance is returned
    for subsequent calls (unless provider_type changes).

    Args:
        provider_type: Which provider to use (defaults to TTS_PROVIDER env var or OpenAI)
        **kwargs: Additional arguments passed to the provider constructor

    Returns:
        A TTS provider instance
    """
    global _provider_instance

    # Determine provider type
    if provider_type is None:
        provider_name = os.getenv("TTS_PROVIDER", "openai").lower()
        try:
            provider_type = TTSProvider(provider_name)
        except ValueError:
            logger.warning("Unknown TTS provider '%s', defaulting to OpenAI", provider_name)
            provider_type = TTSProvider.OPENAI

    # Return cached instance if same provider type
    if _provider_instance is not None:
        if provider_type.value in _provider_instance.name.lower():
            return _provider_instance

    # Create new provider instance
    provider_class = _PROVIDERS.get(provider_type)
    if provider_class is None:
        raise ValueError(f"Unsupported TTS provider: {provider_type}")

    try:
        _provider_instance = provider_class(**kwargs)
        logger.info("Initialized TTS provider: %s", _provider_instance.name)
    except Exception as e:
        logger.error("Failed to initialize TTS provider %s: %s", provider_type, e)
        raise

    return _provider_instance


def get_available_voices(provider_type: Optional[TTSProvider] = None) -> List[Voice]:
    """Get list of available voices for the specified provider."""
    provider = get_tts_provider(provider_type)
    return provider.voices
