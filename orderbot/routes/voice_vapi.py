"""
Vapi.ai Voice Integration for Orderbot.

This module provides an OpenAI-compatible endpoint for Vapi's Custom LLM feature,
allowing the orderbot to handle phone orders through voice.

Architecture:
    Phone Call -> Vapi (STT) -> This endpoint -> Bot Logic -> Response -> Vapi (TTS) -> Caller

The endpoint translates between Vapi's OpenAI-compatible format and our existing
chat logic, enabling voice ordering without modifying the core bot.
"""

import json
import logging
import time
import uuid
import os
from typing import Any
from ..utils.datetime_helpers import utc_now

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..menu_index import get_menu_version
from ..cache import menu_cache
from ..services.customer_service import lookup_customer_by_phone
from ..services.store_service import get_company
from ..services.vapi_session import (
    get_or_create_phone_session,
    get_session_data,
    save_call_analytics,
    phone_sessions,
)


logger = logging.getLogger(__name__)

# Router for Vapi voice endpoints
vapi_router = APIRouter(prefix="/voice/vapi", tags=["Voice - Vapi"])


# Environment configuration
VAPI_SECRET_KEY = os.getenv("VAPI_SECRET_KEY", "")  # Optional: for webhook authentication


# ----- OpenAI-Compatible Streaming -----

async def _generate_sse_stream(text: str, model: str = "sammy-bot"):
    """
    Generate OpenAI-compatible Server-Sent Events stream.

    Vapi expects the standard OpenAI streaming format with delta chunks.
    """
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    # Split response into words for natural streaming
    words = text.split()

    for i, word in enumerate(words):
        # Add space after word (except for last word)
        content = word + (" " if i < len(words) - 1 else "")

        chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {"content": content},
                "finish_reason": None,
            }],
        }
        yield f"data: {json.dumps(chunk)}\n\n"

    # Send final chunk with finish_reason
    final_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{
            "index": 0,
            "delta": {},
            "finish_reason": "stop",
        }],
    }
    yield f"data: {json.dumps(final_chunk)}\n\n"
    yield "data: [DONE]\n\n"


# ----- Main Endpoints -----

def _parse_vapi_request(data: dict) -> tuple[list, bool, dict, str, str]:
    """Unpack a Vapi request and extract phone number + store_id.

    Returns:
        (messages, stream, call_info, phone_number, store_id)
    """
    messages = data.get("messages", [])
    stream = data.get("stream", False)
    call_info = data.get("call", {})
    customer = call_info.get("customer", {}) if call_info else {}

    phone_number = customer.get("number")
    if not phone_number:
        phone_number = data.get("metadata", {}).get("phoneNumber")
    if not phone_number:
        logger.warning("No phone number in Vapi request, using call ID as fallback")
        phone_number = call_info.get("id", f"unknown-{uuid.uuid4().hex[:8]}")

    store_id = data.get("metadata", {}).get("store_id")
    if not store_id:
        store_id = "borough_tribeca"
        logger.info("Defaulting VAPI call to Tribeca store")

    return messages, stream, call_info, phone_number, store_id


def _prepare_vapi_session(
    db: Session,
    phone_number: str,
    store_id: str,
    session_data: dict,
    order_state: dict,
) -> dict | None:
    """Look up returning customer and pre-fill order state fields.

    Returns the returning_customer dict (or None).
    """
    returning_customer = session_data.get("returning_customer")

    if not returning_customer and phone_number:
        returning_customer = lookup_customer_by_phone(db, phone_number)
        if returning_customer:
            session_data["returning_customer"] = returning_customer
            logger.info("Looked up returning customer: %s", returning_customer.get("name"))

    if not order_state.get("customer"):
        order_state["customer"] = {}

    if returning_customer and returning_customer.get("name"):
        if not order_state["customer"].get("name"):
            order_state["customer"]["name"] = returning_customer["name"]
            logger.info("Pre-filled customer name in order state: %s", returning_customer["name"])

    if phone_number and not order_state["customer"].get("phone"):
        order_state["customer"]["phone"] = phone_number
        logger.info("Pre-filled customer phone in order state: %s", phone_number[-4:])

    if returning_customer and returning_customer.get("email"):
        if not order_state["customer"].get("email"):
            order_state["customer"]["email"] = returning_customer["email"]
            logger.info("Pre-filled customer email in order state: %s", returning_customer["email"])

    return returning_customer


def _personalize_vapi_greeting(
    reply: str, history: list[dict], returning_customer: dict | None
) -> str:
    """Prepend a personalized greeting for the first message to a returning customer."""
    user_message_count = sum(1 for msg in history if msg.get("role") == "user")
    if user_message_count <= 1 and returning_customer and returning_customer.get("name"):
        customer_name = returning_customer.get("name")
        reply = f"Hi {customer_name}! Great to hear from you again. " + reply
        logger.info("Added personalized greeting for returning customer: %s", customer_name)
    return reply


@vapi_router.post("/chat/completions")
async def vapi_chat_completions(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    OpenAI-compatible chat completions endpoint for Vapi Custom LLM.

    Vapi sends transcribed speech in OpenAI format, we process it through
    our bot logic and return a response that Vapi will speak to the caller.
    """
    try:
        data = await request.json()
    except (ValueError, KeyError, TypeError) as e:
        logger.error("Failed to parse Vapi request JSON: %s", e)
        raise HTTPException(status_code=400, detail="Invalid JSON")

    messages, stream, call_info, phone_number, store_id = _parse_vapi_request(data)

    # Get or create session for this phone number
    session_id = get_or_create_phone_session(db, phone_number, store_id)
    session_data = get_session_data(db, session_id)

    if not session_data:
        logger.error("Session data not found for session %s", session_id)
        raise HTTPException(status_code=500, detail="Session error")

    # Extract the latest user message
    user_message = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg.get("content", "")
            break

    if not user_message:
        greeting = session_data["history"][0]["content"] if session_data["history"] else "Hello!"
        if stream:
            return StreamingResponse(
                _generate_sse_stream(greeting),
                media_type="text/event-stream",
            )
        else:
            return _build_completion_response(greeting)

    logger.info("Voice message from %s: %s", phone_number[-4:], user_message[:50])

    order_state = session_data["order"]
    session_store_id = session_data.get("store_id") or store_id
    returning_customer = _prepare_vapi_session(db, phone_number, store_id, session_data, order_state)

    # Check if menu needs to be sent
    menu_index = menu_cache.get_menu_index(session_store_id)
    current_menu_version = get_menu_version(menu_index)
    include_menu = session_data.get("menu_version") != current_menu_version

    # Use MessageProcessor for unified processing
    from ..message_processor import MessageProcessor, ProcessingContext

    logger.info("Using MessageProcessor for voice message")
    try:
        processor = MessageProcessor(db)
        result = processor.process(ProcessingContext(
            user_message=user_message,
            session_id=session_id,
            caller_id=phone_number,
            store_id=session_store_id,
            session=session_data,
        ))

        reply = result.reply
        order_state = result.order_state
        history = result.session.get("history", [])

        if include_menu:
            session_data["menu_version"] = current_menu_version

    except (ValueError, KeyError, TypeError, AttributeError, ConnectionError, TimeoutError) as e:
        logger.error("MessageProcessor failed for voice session: %s", e, exc_info=True)
        error_reply = "I'm sorry, I'm having trouble right now. Could you please repeat that?"
        if stream:
            return StreamingResponse(
                _generate_sse_stream(error_reply),
                media_type="text/event-stream",
            )
        else:
            return _build_completion_response(error_reply)

    reply = _personalize_vapi_greeting(reply, history, returning_customer)

    # Update phone session cache
    session_data["history"] = result.session.get("history", [])
    session_data["order"] = order_state
    normalized_phone = "".join(c for c in phone_number if c.isdigit() or c == "+")
    if normalized_phone in phone_sessions:
        phone_sessions[normalized_phone]["session_data"] = session_data
        phone_sessions[normalized_phone]["last_access"] = time.time()

    logger.info("Voice reply to %s: %s", phone_number[-4:], reply[:50])

    if stream:
        return StreamingResponse(
            _generate_sse_stream(reply),
            media_type="text/event-stream",
        )
    else:
        return _build_completion_response(reply)


def _build_completion_response(content: str, model: str = "sammy-bot") -> dict[str, Any]:
    """Build a non-streaming OpenAI-compatible completion response."""
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": content,
            },
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


@vapi_router.post("/webhook")
async def vapi_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Webhook endpoint for Vapi server events.

    Receives notifications about call events:
    - end-of-call-report: Call summary and transcript
    - status-update: Call status changes
    - transcript: Real-time transcript updates
    - etc.

    This endpoint is optional but useful for:
    - Analytics and reporting
    - Saving call transcripts
    - Triggering post-call actions
    """
    try:
        data = await request.json()
    except (ValueError, KeyError, TypeError) as e:
        logger.error("Failed to parse Vapi webhook JSON: %s", e)
        raise HTTPException(status_code=400, detail="Invalid JSON")

    message = data.get("message", {})
    message_type = message.get("type", "unknown")

    logger.info("Vapi webhook received: %s", message_type)

    if message_type == "end-of-call-report":
        # Call ended - log summary
        call_info = message.get("call", {})
        artifact = message.get("artifact", {})
        ended_reason = message.get("endedReason", "unknown")

        call_id = call_info.get("id")
        transcript = artifact.get("transcript", "")
        duration = call_info.get("duration")  # in seconds if available

        # Extract phone number from call info
        customer = call_info.get("customer", {})
        phone_number = customer.get("number")

        logger.info(
            "Call ended - ID: %s, Phone: %s, Reason: %s, Duration: %s sec",
            call_id,
            phone_number[-4:] if phone_number else "unknown",
            ended_reason,
            duration,
        )

        # Log transcript summary (first 200 chars)
        if transcript:
            logger.debug("Transcript preview: %s...", transcript[:200])

        # Save to analytics table
        if phone_number:
            try:
                save_call_analytics(
                    db=db,
                    phone_number=phone_number,
                    ended_reason=ended_reason,
                    duration=duration,
                    transcript=transcript,
                )
            except (ValueError, KeyError, TypeError, OSError) as e:
                logger.error("Failed to save call analytics: %s", e)
        else:
            logger.warning("No phone number in end-of-call-report, cannot save analytics")

    elif message_type == "status-update":
        # Call status changed
        status = message.get("status", {})
        logger.debug("Call status update: %s", status)

    elif message_type == "assistant-request":
        # Vapi is asking for assistant configuration at call start
        # We use this to provide a personalized first message based on caller
        call_info = message.get("call", {})
        customer = call_info.get("customer", {})
        phone_number = customer.get("number", "")

        logger.info("Assistant request for phone: %s", phone_number[-4:] if phone_number else "unknown")

        # Look up returning customer
        returning_customer = None
        if phone_number:
            returning_customer = lookup_customer_by_phone(db, phone_number)

        # Get company/store info for greeting
        company = get_company(db)
        store_name = company.name if company else "Borough Bagels"
        bot_name = company.bot_persona_name if company else "Zara"

        # Generate personalized greeting
        if returning_customer and returning_customer.get("name"):
            first_message = f"Hello {returning_customer['name']}! Would you like to repeat your last order?"
            logger.info("Returning customer greeting for: %s", returning_customer['name'])
        else:
            first_message = f"Hi, thanks for calling {store_name}! I'm {bot_name}. What can I get started for you today?"
            logger.info("New customer greeting")

        # Return assistant override with personalized first message
        return {
            "assistant": {
                "firstMessage": first_message,
            }
        }

    elif message_type == "hang":
        # Call was put on hold or assistant was slow to respond
        logger.warning("Vapi hang notification - assistant may be responding too slowly")

    # Return success for all webhook types
    return {"status": "ok"}


@vapi_router.get("/health")
async def vapi_health():
    """Health check endpoint for Vapi to verify server is reachable."""
    return {
        "status": "ok",
        "service": "sammy-bot-voice",
        "timestamp": utc_now().isoformat(),
    }
