"""
Vapi Webhook Schemas
====================

Pydantic models for Vapi.ai voice integration request/response formats.
Used by the voice_vapi.py endpoint module.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VapiMessage(BaseModel):
    """OpenAI-compatible message format."""
    role: str
    content: str


class VapiCallCustomer(BaseModel):
    """Customer info from Vapi call object."""
    number: str | None = None
    name: str | None = None


class VapiCall(BaseModel):
    """Vapi call object with metadata."""
    id: str | None = None
    customer: VapiCallCustomer | None = None


class VapiChatCompletionRequest(BaseModel):
    """
    OpenAI-compatible chat completion request from Vapi.

    Vapi sends this format when using Custom LLM integration.
    """
    model_config = ConfigDict(extra="allow")  # Allow additional fields from Vapi

    model: str | None = "gpt-4"
    messages: list[VapiMessage] = Field(default_factory=list)
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    # Vapi-specific fields
    call: VapiCall | None = None


class VapiWebhookMessage(BaseModel):
    """Vapi webhook message wrapper."""
    model_config = ConfigDict(extra="allow")  # Additional fields vary by message type

    type: str
    call: dict[str, Any] | None = None
    artifact: dict[str, Any] | None = None
    endedReason: str | None = None


class VapiWebhookRequest(BaseModel):
    """Vapi webhook request envelope."""
    message: VapiWebhookMessage
