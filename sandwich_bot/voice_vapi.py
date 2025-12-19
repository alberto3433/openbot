"""
Vapi.ai Voice Integration for Sandwich Bot.

This module provides an OpenAI-compatible endpoint for Vapi's Custom LLM feature,
allowing the sandwich bot to handle phone orders through voice.

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
from typing import Any, Dict, Optional, List
from datetime import datetime

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .db import get_db
from .models import ChatSession, Store, Company
from .menu_index_builder import build_menu_index, get_menu_version
from sandwich_bot.sammy.llm_client import call_sandwich_bot
from .order_logic import apply_intent_to_order_state

logger = logging.getLogger(__name__)

# Router for Vapi voice endpoints
vapi_router = APIRouter(prefix="/voice/vapi", tags=["Voice - Vapi"])

# Environment configuration
VAPI_SECRET_KEY = os.getenv("VAPI_SECRET_KEY", "")  # Optional: for webhook authentication

# Phone number to session mapping with TTL
# Structure: {phone_number: {"session_id": str, "last_access": float, "store_id": str}}
_phone_sessions: Dict[str, Dict[str, Any]] = {}
PHONE_SESSION_TTL_SECONDS = int(os.getenv("VAPI_SESSION_TTL", "1800"))  # 30 minutes default


# ----- Pydantic Models for Vapi Request/Response -----

class VapiMessage(BaseModel):
    """OpenAI-compatible message format."""
    role: str
    content: str


class VapiCallCustomer(BaseModel):
    """Customer info from Vapi call object."""
    number: Optional[str] = None
    name: Optional[str] = None


class VapiCall(BaseModel):
    """Vapi call object with metadata."""
    id: Optional[str] = None
    customer: Optional[VapiCallCustomer] = None


class VapiChatCompletionRequest(BaseModel):
    """
    OpenAI-compatible chat completion request from Vapi.

    Vapi sends this format when using Custom LLM integration.
    """
    model: Optional[str] = "gpt-4"
    messages: List[VapiMessage] = Field(default_factory=list)
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    # Vapi-specific fields
    call: Optional[VapiCall] = None

    class Config:
        extra = "allow"  # Allow additional fields from Vapi


class VapiWebhookMessage(BaseModel):
    """Vapi webhook message wrapper."""
    type: str
    call: Optional[Dict[str, Any]] = None
    artifact: Optional[Dict[str, Any]] = None
    endedReason: Optional[str] = None
    # Additional fields vary by message type

    class Config:
        extra = "allow"


class VapiWebhookRequest(BaseModel):
    """Vapi webhook request envelope."""
    message: VapiWebhookMessage


# ----- Session Management -----

def _cleanup_expired_phone_sessions() -> int:
    """Remove expired phone sessions. Returns count of removed sessions."""
    now = time.time()
    expired = [
        phone for phone, data in _phone_sessions.items()
        if now - data.get("last_access", 0) > PHONE_SESSION_TTL_SECONDS
    ]
    for phone in expired:
        del _phone_sessions[phone]
    if expired:
        logger.debug("Cleaned up %d expired phone sessions", len(expired))
    return len(expired)


def _get_or_create_phone_session(
    db: Session,
    phone_number: str,
    store_id: Optional[str] = None,
) -> str:
    """
    Get existing session for phone number or create a new one.

    This enables returning customer detection and session continuity
    for callers who call back within the TTL window.
    """
    # Periodic cleanup
    if len(_phone_sessions) > 100:
        _cleanup_expired_phone_sessions()

    # Normalize phone number (remove spaces, dashes)
    normalized_phone = "".join(c for c in phone_number if c.isdigit() or c == "+")

    # Check for existing session
    if normalized_phone in _phone_sessions:
        session_data = _phone_sessions[normalized_phone]
        session_data["last_access"] = time.time()
        logger.info("Resuming phone session for %s (session: %s)",
                   normalized_phone[-4:], session_data["session_id"][:8])
        return session_data["session_id"]

    # Create new session
    session_id = str(uuid.uuid4())

    # Get company info
    company = db.query(Company).first()
    company_name = company.name if company else "Sammy's Subs"
    bot_name = company.bot_persona_name if company else "Sammy"

    # Get store name
    store_name = company_name
    if store_id:
        store = db.query(Store).filter(Store.store_id == store_id).first()
        if store:
            store_name = store.name

    # Check for returning customer
    returning_customer = _lookup_customer_by_phone(db, normalized_phone)

    # Generate greeting
    if returning_customer and returning_customer.get("name"):
        welcome = f"Hi {returning_customer['name']}, welcome back to {store_name}! Would you like your usual order or something different today?"
    else:
        welcome = f"Hi, thanks for calling {store_name}! I'm {bot_name}. What can I get started for you today?"

    # Initialize session data
    session_data = {
        "history": [{"role": "assistant", "content": welcome}],
        "order": {
            "status": "pending",
            "items": [],
            "customer": {
                "name": returning_customer.get("name") if returning_customer else None,
                "phone": normalized_phone,
                "pickup_time": None,
            },
            "total_price": 0.0,
        },
        "menu_version": None,
        "caller_id": normalized_phone,
        "store_id": store_id,
        "returning_customer": returning_customer,
        "channel": "voice",  # Mark as voice channel for analytics
    }

    # Save to database
    db_session = ChatSession(
        session_id=session_id,
        history=session_data["history"],
        order_state=session_data["order"],
        store_id=store_id,
        caller_id=normalized_phone,
    )
    db.add(db_session)
    db.commit()

    # Cache the phone-to-session mapping
    _phone_sessions[normalized_phone] = {
        "session_id": session_id,
        "last_access": time.time(),
        "store_id": store_id,
        "session_data": session_data,
    }

    logger.info("Created new voice session for phone %s (session: %s, store: %s)",
               normalized_phone[-4:], session_id[:8], store_id or "default")

    return session_id


def _lookup_customer_by_phone(db: Session, phone: str) -> Optional[Dict[str, Any]]:
    """Look up returning customer by phone number from past orders."""
    from .models import Order

    # Normalize phone for lookup
    normalized = "".join(c for c in phone if c.isdigit())
    if len(normalized) == 10:
        normalized = "1" + normalized

    # Find most recent confirmed order with this phone
    recent_order = (
        db.query(Order)
        .filter(
            Order.phone.isnot(None),
            Order.status == "confirmed",
        )
        .order_by(Order.created_at.desc())
        .first()
    )

    # Check if phone matches (handle various formats)
    if recent_order and recent_order.phone:
        order_phone = "".join(c for c in recent_order.phone if c.isdigit())
        if len(order_phone) == 10:
            order_phone = "1" + order_phone

        if order_phone == normalized or order_phone.endswith(normalized[-10:]):
            return {
                "name": recent_order.customer_name,
                "phone": recent_order.phone,
                "last_order_id": recent_order.id,
            }

    return None


def _get_session_data(db: Session, session_id: str) -> Optional[Dict[str, Any]]:
    """Get session data from cache or database."""
    # Check phone session cache first
    for phone, data in _phone_sessions.items():
        if data.get("session_id") == session_id:
            return data.get("session_data")

    # Fall back to database
    db_session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
    if db_session:
        return {
            "history": db_session.history or [],
            "order": db_session.order_state or {},
            "menu_version": db_session.menu_version_sent,
            "store_id": db_session.store_id,
            "caller_id": db_session.caller_id,
        }

    return None


def _save_session_data(db: Session, session_id: str, session_data: Dict[str, Any]) -> None:
    """Save session data to cache and database."""
    # Update phone session cache
    phone = session_data.get("caller_id")
    if phone and phone in _phone_sessions:
        _phone_sessions[phone]["session_data"] = session_data
        _phone_sessions[phone]["last_access"] = time.time()

    # Update database
    db_session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
    if db_session:
        db_session.history = session_data.get("history", [])
        db_session.order_state = session_data.get("order", {})
        db_session.menu_version_sent = session_data.get("menu_version")
        db.commit()


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

@vapi_router.post("/chat/completions")
async def vapi_chat_completions(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    OpenAI-compatible chat completions endpoint for Vapi Custom LLM.

    Vapi sends transcribed speech in OpenAI format, we process it through
    our bot logic and return a response that Vapi will speak to the caller.

    This endpoint:
    1. Extracts caller phone number from Vapi's call object
    2. Maps phone to session (creating new session if needed)
    3. Processes the user's message through existing bot logic
    4. Returns OpenAI-compatible response (streaming or non-streaming)
    """
    try:
        data = await request.json()
    except Exception as e:
        logger.error("Failed to parse Vapi request JSON: %s", e)
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Parse request
    messages = data.get("messages", [])
    stream = data.get("stream", False)
    call_info = data.get("call", {})
    customer = call_info.get("customer", {}) if call_info else {}

    # Extract phone number
    phone_number = customer.get("number")
    if not phone_number:
        # Try to find phone in other locations Vapi might put it
        phone_number = data.get("metadata", {}).get("phoneNumber")

    if not phone_number:
        logger.warning("No phone number in Vapi request, using call ID as fallback")
        phone_number = call_info.get("id", f"unknown-{uuid.uuid4().hex[:8]}")

    # Extract store_id from metadata if provided
    store_id = data.get("metadata", {}).get("store_id")

    # Get or create session for this phone number
    session_id = _get_or_create_phone_session(db, phone_number, store_id)
    session_data = _get_session_data(db, session_id)

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
        # No user message - might be initial call, return greeting
        greeting = session_data["history"][0]["content"] if session_data["history"] else "Hello!"
        if stream:
            return StreamingResponse(
                _generate_sse_stream(greeting),
                media_type="text/event-stream",
            )
        else:
            return _build_completion_response(greeting)

    logger.info("Voice message from %s: %s", phone_number[-4:], user_message[:50])

    # Add user message to history
    session_data["history"].append({"role": "user", "content": user_message})

    # Get session context
    history = session_data["history"]
    order_state = session_data["order"]
    returning_customer = session_data.get("returning_customer")
    session_store_id = session_data.get("store_id") or store_id

    # Get company info
    company = db.query(Company).first()
    bot_name = company.bot_persona_name if company else "Sammy"
    company_name = company.name if company else "Sammy's Subs"

    # Build menu index
    menu_index = build_menu_index(db, store_id=session_store_id)

    # Check if menu needs to be sent
    current_menu_version = get_menu_version(menu_index)
    include_menu = session_data.get("menu_version") != current_menu_version

    # Call the bot
    try:
        llm_result = call_sandwich_bot(
            history,
            order_state,
            menu_index,
            user_message,
            include_menu_in_system=include_menu,
            returning_customer=returning_customer,
            caller_id=phone_number,
            bot_name=bot_name,
            company_name=company_name,
            db=db,
            use_dynamic_prompt=True,
        )

        if include_menu:
            session_data["menu_version"] = current_menu_version

    except Exception as e:
        logger.error("LLM call failed for voice session: %s", e)
        error_reply = "I'm sorry, I'm having trouble right now. Could you please repeat that?"
        if stream:
            return StreamingResponse(
                _generate_sse_stream(error_reply),
                media_type="text/event-stream",
            )
        else:
            return _build_completion_response(error_reply)

    # Process actions
    reply = llm_result.get("reply", "")
    actions = llm_result.get("actions", [])

    # Backward compatibility
    if not actions and llm_result.get("intent"):
        actions = [{"intent": llm_result.get("intent"), "slots": llm_result.get("slots", {})}]

    # Apply actions to order state
    all_slots = {}
    for action in actions:
        intent = action.get("intent", "unknown")
        slots = action.get("slots", {})
        all_slots.update(slots)
        order_state = apply_intent_to_order_state(
            order_state, intent, slots, menu_index, returning_customer
        )

    # Check if order should be persisted to database
    if order_state.get("status") == "confirmed":
        # Late import to avoid circular dependency
        from .main import persist_confirmed_order
        persisted_order = persist_confirmed_order(
            db, order_state, all_slots, store_id=session_store_id
        )
        if persisted_order:
            logger.info("Voice order persisted for customer: %s (store: %s)",
                       persisted_order.customer_name, session_store_id or "default")

    # Update session
    session_data["order"] = order_state
    session_data["history"].append({"role": "assistant", "content": reply})
    _save_session_data(db, session_id, session_data)

    logger.info("Voice reply to %s: %s", phone_number[-4:], reply[:50])

    # Return response
    if stream:
        return StreamingResponse(
            _generate_sse_stream(reply),
            media_type="text/event-stream",
        )
    else:
        return _build_completion_response(reply)


def _build_completion_response(content: str, model: str = "sammy-bot") -> Dict[str, Any]:
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
    except Exception as e:
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

        logger.info(
            "Call ended - ID: %s, Reason: %s, Duration: %s sec",
            call_id,
            ended_reason,
            duration,
        )

        # Log transcript summary (first 200 chars)
        if transcript:
            logger.debug("Transcript preview: %s...", transcript[:200])

        # TODO: Save to analytics table if desired
        # save_call_analytics(db, call_id, transcript, ended_reason, duration)

    elif message_type == "status-update":
        # Call status changed
        status = message.get("status", {})
        logger.debug("Call status update: %s", status)

    elif message_type == "assistant-request":
        # Vapi is asking for assistant configuration
        # This happens when using dynamic assistant selection
        # For now, we don't use this - our assistant is configured in Vapi dashboard
        logger.debug("Assistant request received (not implemented)")
        return {"error": "Assistant request not implemented - configure assistant in Vapi dashboard"}

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
        "timestamp": datetime.utcnow().isoformat(),
    }
