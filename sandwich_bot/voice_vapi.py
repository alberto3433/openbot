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
from sqlalchemy.orm.attributes import flag_modified

from .db import get_db
from .models import ChatSession, Store, Company, SessionAnalytics
from .menu_index_builder import build_menu_index, get_menu_version
from sandwich_bot.sammy.llm_client import call_sandwich_bot
from .order_logic import apply_intent_to_order_state
from .email_service import send_payment_link_email
from .chains.integration import process_voice_message


def _build_store_info(store_id: str, company_name: str, db: Session) -> Dict[str, Any]:
    """Build store info dict for orchestrator."""
    store_info = {
        "name": company_name,
        "store_id": store_id,
        "city_tax_rate": 0.0,
        "state_tax_rate": 0.0,
        "delivery_zip_codes": [],
        # Store location and contact info
        "address": None,
        "city": None,
        "state": None,
        "zip_code": None,
        "phone": None,
        "hours": None,
        # All stores info for cross-store delivery lookup
        "all_stores": [],
    }
    if db and store_id:
        store = db.query(Store).filter(Store.store_id == store_id).first()
        if store:
            store_info["name"] = store.name or company_name
            store_info["city_tax_rate"] = store.city_tax_rate or 0.0
            store_info["state_tax_rate"] = store.state_tax_rate or 0.0
            store_info["delivery_zip_codes"] = store.delivery_zip_codes or []
            # Add location and contact info
            store_info["address"] = store.address
            store_info["city"] = store.city
            store_info["state"] = store.state
            store_info["zip_code"] = store.zip_code
            store_info["phone"] = store.phone
            store_info["hours"] = store.hours

    # Get all stores for delivery zone lookup
    if db:
        all_stores = db.query(Store).filter(Store.status == "open").all()
        store_info["all_stores"] = [
            {
                "store_id": s.store_id,
                "name": s.name,
                "delivery_zip_codes": s.delivery_zip_codes or [],
                "address": s.address,
                "city": s.city,
                "state": s.state,
                "phone": s.phone,
            }
            for s in all_stores
        ]

    return store_info

logger = logging.getLogger(__name__)

# Router for Vapi voice endpoints
vapi_router = APIRouter(prefix="/voice/vapi", tags=["Voice - Vapi"])


# ----- Flow Guidance Generator -----

def _item_uses_bagel(item: Dict[str, Any]) -> bool:
    """
    Check if an order item uses a bagel.

    An item uses a bagel if:
    - Its item_type is "bagel"
    - Its bread field contains "bagel" (case insensitive)
    - Its menu_item_name contains "bagel" (case insensitive)
    """
    # Check item type
    item_type = (item.get("item_type") or "").lower()
    if item_type == "bagel":
        return True

    # Check bread field
    bread = (item.get("bread") or "").lower()
    if "bagel" in bread:
        return True

    # Check menu item name (e.g., "Lox Bagel", "Everything Bagel")
    name = (item.get("menu_item_name") or "").lower()
    if "bagel" in name:
        return True

    return False


def _get_items_needing_toasting(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Get bagel items that haven't been asked about toasting yet.

    Returns items where:
    - Item uses a bagel (by type, bread, or name)
    - toasted field is None (not yet set to True or False)
    """
    needs_toasting = []
    for i, item in enumerate(items):
        if _item_uses_bagel(item) and item.get("toasted") is None:
            needs_toasting.append({"index": i, "item": item})
    return needs_toasting


def generate_flow_guidance(order_state: Dict[str, Any], history: List[Dict[str, str]]) -> str:
    """
    Generate explicit guidance about current order status and next steps.

    This helps prevent the LLM from asking for information it already has
    by making the current state crystal clear.
    """
    customer = order_state.get("customer", {})
    items = order_state.get("items", [])
    order_type = order_state.get("order_type")
    payment_status = order_state.get("payment_status")
    payment_method = order_state.get("payment_method")

    lines = ["\n=== CURRENT ORDER STATUS (READ THIS CAREFULLY) ==="]

    # Items status
    if items:
        lines.append(f"  ITEMS IN CART: {len(items)} item(s)")
        for idx, item in enumerate(items[:3]):  # Show first 3
            item_name = item.get('menu_item_name', 'Unknown')
            toasted_status = ""
            if _item_uses_bagel(item):
                if item.get("toasted") is True:
                    toasted_status = " [TOASTED]"
                elif item.get("toasted") is False:
                    toasted_status = " [NOT TOASTED]"
                else:
                    toasted_status = " [TOASTING: NOT YET ASKED]"
            lines.append(f"    - {item_name}{toasted_status}")
        if len(items) > 3:
            lines.append(f"    - ... and {len(items) - 3} more")
    else:
        lines.append("  ITEMS IN CART: None yet")

    # Check for bagel items needing toasting confirmation
    items_needing_toasting = _get_items_needing_toasting(items)

    # Customer info - be very explicit
    lines.append("")
    lines.append("  CUSTOMER INFO:")

    if customer.get("name"):
        lines.append(f"    ✓ Name: {customer['name']} — ALREADY HAVE, DO NOT ASK")
    else:
        lines.append("    ✗ Name: NOT YET COLLECTED")

    if customer.get("phone"):
        phone = customer["phone"]
        masked = f"...{phone[-4:]}" if len(phone) >= 4 else phone
        lines.append(f"    ✓ Phone: {masked} — ALREADY HAVE, DO NOT ASK")
    else:
        lines.append("    ✗ Phone: NOT YET COLLECTED")

    if customer.get("email"):
        lines.append(f"    ✓ Email: {customer['email']} — ALREADY HAVE, DO NOT ASK")
    else:
        lines.append("    ✗ Email: Not collected (only needed for email payment link)")

    # Order type
    lines.append("")
    if order_type:
        lines.append(f"  ✓ Order Type: {order_type.upper()} — ALREADY SET, DO NOT ASK")
    else:
        lines.append("  ✗ Order Type: NOT YET SET (pickup or delivery)")

    # Payment
    if payment_status or payment_method:
        lines.append(f"  ✓ Payment: {payment_method or payment_status} — ALREADY HANDLED")
    else:
        lines.append("  ✗ Payment: NOT YET HANDLED")

    # Determine next step
    lines.append("")
    lines.append("  >>> NEXT STEP:")

    if not items:
        lines.append("      Take their order - ask what they'd like")
    elif items_needing_toasting:
        # Bagel items need toasting confirmation BEFORE proceeding
        lines.append("      *** STOP - TOASTING REQUIRED BEFORE CONTINUING ***")
        lines.append(f"      You have {len(items_needing_toasting)} bagel item(s) that MUST be asked about toasting:")
        for x in items_needing_toasting:
            lines.append(f"        - Item #{x['index']}: {x['item'].get('menu_item_name', 'Unknown')}")
        lines.append("      YOUR RESPONSE MUST ASK: 'Would you like that toasted?'")
        lines.append("      DO NOT ask about sides, drinks, pickup, or anything else until toasting is answered!")
        idx = items_needing_toasting[0]['index']  # First item needing toasting
        lines.append(f"      When they answer, use update_sandwich with toasted=true or toasted=false and item_index={idx}")
    elif not order_type:
        lines.append("      Ask: 'Is this for pickup or delivery?'")
    elif not customer.get("name"):
        lines.append("      Ask for their name (you have their phone from caller ID)")
    elif not payment_status and not payment_method:
        lines.append("      Offer payment options: text link, email link, card over phone, or pay at pickup")
    else:
        lines.append("      CONFIRM THE ORDER with confirm_order intent - DO NOT ask more questions!")

    lines.append("=== END STATUS ===\n")

    return "\n".join(lines)

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

    Session lookup priority:
    1. In-memory cache (fastest, for same instance)
    2. Database lookup (survives deployments)
    3. Create new session (if no active session found)
    """
    # Periodic cleanup
    if len(_phone_sessions) > 100:
        _cleanup_expired_phone_sessions()

    # Normalize phone number (remove spaces, dashes)
    normalized_phone = "".join(c for c in phone_number if c.isdigit() or c == "+")

    # Check for existing session in memory cache
    if normalized_phone in _phone_sessions:
        session_data = _phone_sessions[normalized_phone]
        session_data["last_access"] = time.time()
        logger.info("Resuming phone session from cache for %s (session: %s)",
                   normalized_phone[-4:], session_data["session_id"][:8])
        return session_data["session_id"]

    # Check database for active session from this phone (survives deployments)
    existing_db_session = (
        db.query(ChatSession)
        .filter(ChatSession.caller_id == normalized_phone)
        .order_by(ChatSession.id.desc())
        .first()
    )

    if existing_db_session:
        # Check if session is still active (not confirmed, has history)
        order_state = existing_db_session.order_state or {}
        order_status = order_state.get("status", "pending")

        # Resume if order is not yet confirmed (still in progress)
        if order_status not in ("confirmed",):
            session_id = existing_db_session.session_id

            # Rebuild session data from database
            session_data = {
                "history": existing_db_session.history or [],
                "order": order_state,
                "menu_version": existing_db_session.menu_version_sent,
                "caller_id": normalized_phone,
                "store_id": existing_db_session.store_id or store_id,
                "returning_customer": None,  # Will be looked up if needed
                "channel": "voice",
            }

            # Repopulate the cache
            _phone_sessions[normalized_phone] = {
                "session_id": session_id,
                "last_access": time.time(),
                "store_id": existing_db_session.store_id or store_id,
                "session_data": session_data,
            }

            logger.info("Resumed phone session from database for %s (session: %s, messages: %d, items: %d)",
                       normalized_phone[-4:], session_id[:8],
                       len(session_data["history"]),
                       len(order_state.get("items", [])))
            return session_id

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
        welcome = f"Hello {returning_customer['name']}! Would you like to repeat your last order?"
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
    from sqlalchemy.orm import joinedload
    from .models import Order

    # Normalize phone for lookup - extract just digits
    normalized = "".join(c for c in phone if c.isdigit())
    # Get last 10 digits for matching (handles +1 prefix variations)
    phone_suffix = normalized[-10:] if len(normalized) >= 10 else normalized

    if not phone_suffix:
        return None

    # Find most recent confirmed order matching this phone number
    # Use joinedload to eagerly load items for repeat order functionality
    recent_orders = (
        db.query(Order)
        .options(joinedload(Order.items))
        .filter(
            Order.phone.isnot(None),
            Order.status == "confirmed",
        )
        .order_by(Order.created_at.desc())
        .limit(20)  # Check recent orders for a match
        .all()
    )

    # Find an order that matches this phone number
    for order in recent_orders:
        if order.phone:
            order_phone = "".join(c for c in order.phone if c.isdigit())
            order_suffix = order_phone[-10:] if len(order_phone) >= 10 else order_phone

            if order_suffix == phone_suffix:
                # Build last_order_items from the order's items
                last_order_items = []
                for item in order.items:
                    item_data = {
                        "menu_item_name": item.menu_item_name,
                        "item_type": item.item_type or "sandwich",
                        "bread": item.bread,
                        "toasted": item.toasted,
                        "quantity": item.quantity,
                        "price": item.unit_price,
                    }
                    # Add item_config fields if present (spread, coffee settings, etc.)
                    if item.item_config:
                        item_data.update(item.item_config)
                    last_order_items.append(item_data)

                return {
                    "name": order.customer_name,
                    "phone": order.phone,
                    "email": order.customer_email,
                    "last_order_id": order.id,
                    "last_order_items": last_order_items,
                    "last_order_type": order.order_type,  # "pickup" or "delivery"
                    "last_order_address": order.delivery_address,  # For repeat delivery orders
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
        # Force SQLAlchemy to detect changes to mutable JSON columns
        flag_modified(db_session, "history")
        flag_modified(db_session, "order_state")
        db.commit()


def _save_call_analytics(
    db: Session,
    phone_number: str,
    ended_reason: str,
    duration: Optional[int] = None,
    transcript: Optional[str] = None,
) -> None:
    """
    Save voice call analytics to SessionAnalytics table.

    Called when a VAPI call ends to track voice session analytics
    alongside web chat analytics.
    """
    # Normalize phone number
    normalized_phone = "".join(c for c in phone_number if c.isdigit() or c == "+")

    # Look up session data from cache
    session_data = None
    session_id = None

    if normalized_phone in _phone_sessions:
        cached = _phone_sessions[normalized_phone]
        session_id = cached.get("session_id")
        session_data = cached.get("session_data", {})

    if not session_id:
        # Try to find by phone in database
        db_session = (
            db.query(ChatSession)
            .filter(ChatSession.caller_id == normalized_phone)
            .order_by(ChatSession.id.desc())
            .first()
        )
        if db_session:
            session_id = db_session.session_id
            session_data = {
                "history": db_session.history or [],
                "order": db_session.order_state or {},
                "store_id": db_session.store_id,
            }

    if not session_id:
        logger.warning("No session found for phone %s, creating minimal analytics record", normalized_phone[-4:])
        session_id = f"voice-{uuid.uuid4()}"
        session_data = {"history": [], "order": {}}

    # Extract analytics data from session
    history = session_data.get("history", [])
    order_state = session_data.get("order", {})
    store_id = session_data.get("store_id")

    items = order_state.get("items", [])
    order_status = order_state.get("status", "pending")
    cart_total = order_state.get("total_price", 0.0)
    customer = order_state.get("customer", {})

    # Determine session status
    if order_status == "confirmed":
        status = "completed"
        reason = None
    else:
        status = "abandoned"
        # Map VAPI ended reasons to our reason format
        reason_map = {
            "customer-ended-call": "customer_hangup",
            "assistant-ended-call": "assistant_ended",
            "customer-did-not-answer": "no_answer",
            "voicemail": "voicemail",
            "silence-timed-out": "silence_timeout",
            "phone-call-provider-closed-websocket": "connection_lost",
        }
        reason = reason_map.get(ended_reason, f"voice_{ended_reason}")

    # Get last messages
    last_bot_message = None
    last_user_message = None
    for msg in reversed(history):
        if msg.get("role") == "assistant" and not last_bot_message:
            last_bot_message = msg.get("content", "")[:500]
        elif msg.get("role") == "user" and not last_user_message:
            last_user_message = msg.get("content", "")[:500]
        if last_bot_message and last_user_message:
            break

    # Create analytics record
    analytics_record = SessionAnalytics(
        session_id=session_id,
        status=status,
        message_count=len([m for m in history if m.get("role") == "user"]),
        had_items_in_cart=len(items) > 0,
        item_count=len(items),
        cart_total=cart_total,
        order_status=order_status,
        conversation_history=history,
        last_bot_message=last_bot_message,
        last_user_message=last_user_message,
        reason=reason,
        session_duration_seconds=duration,
        customer_name=customer.get("name"),
        customer_phone=normalized_phone,
        store_id=store_id,
    )

    db.add(analytics_record)
    db.commit()

    logger.info(
        "Voice session analytics saved: %s (status: %s, messages: %d, items: %d, total: $%.2f, reason: %s)",
        session_id[:8],
        status,
        analytics_record.message_count,
        len(items),
        cart_total,
        reason,
    )

    # Clean up phone session cache
    if normalized_phone in _phone_sessions:
        del _phone_sessions[normalized_phone]


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

    # Default to Tribeca store for VAPI calls
    # The main VAPI phone number (732-813-9409) is for Tribeca
    # This can be overridden by passing store_id in metadata
    if not store_id:
        store_id = "zuckers_tribeca"
        logger.info("Defaulting VAPI call to Tribeca store")

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

    # Get session context
    history = session_data["history"]
    order_state = session_data["order"]
    returning_customer = session_data.get("returning_customer")
    session_store_id = session_data.get("store_id") or store_id

    # Look up returning customer if not already in session (e.g., resumed from DB)
    if not returning_customer and phone_number:
        returning_customer = _lookup_customer_by_phone(db, phone_number)
        if returning_customer:
            session_data["returning_customer"] = returning_customer
            logger.info("Looked up returning customer: %s", returning_customer.get("name"))

    # Ensure customer info is in order state if we know it (so bot doesn't ask again)
    if not order_state.get("customer"):
        order_state["customer"] = {}

    # Pre-fill name from returning customer lookup
    if returning_customer and returning_customer.get("name"):
        if not order_state["customer"].get("name"):
            order_state["customer"]["name"] = returning_customer["name"]
            logger.info("Pre-filled customer name in order state: %s", returning_customer["name"])

    # Pre-fill phone from caller ID
    if phone_number and not order_state["customer"].get("phone"):
        order_state["customer"]["phone"] = phone_number
        logger.info("Pre-filled customer phone in order state: %s", phone_number[-4:])

    # Pre-fill email from returning customer lookup
    if returning_customer and returning_customer.get("email"):
        if not order_state["customer"].get("email"):
            order_state["customer"]["email"] = returning_customer["email"]
            logger.info("Pre-filled customer email in order state: %s", returning_customer["email"])

    # Get company info
    company = db.query(Company).first()
    bot_name = company.bot_persona_name if company else "Sammy"
    company_name = company.name if company else "Sammy's Subs"

    # Build menu index
    menu_index = build_menu_index(db, store_id=session_store_id)

    # Check if menu needs to be sent
    current_menu_version = get_menu_version(menu_index)
    include_menu = session_data.get("menu_version") != current_menu_version

    # Use MessageProcessor when state machine is enabled (default)
    # Fall back to LLM path when state machine is disabled (for testing)
    from .tasks.state_machine_adapter import is_state_machine_enabled
    use_orchestrator = is_state_machine_enabled()
    if use_orchestrator:
        # Use MessageProcessor for unified processing
        logger.info("Using MessageProcessor for voice message")
        try:
            from .message_processor import MessageProcessor, ProcessingContext

            processor = MessageProcessor(db)
            result = processor.process(ProcessingContext(
                user_message=user_message,
                session_id=session_id,
                caller_id=phone_number,
                store_id=session_store_id,
                session=session_data,  # Pass pre-loaded session
            ))

            reply = result.reply
            order_state = result.order_state
            actions = result.actions

            if include_menu:
                session_data["menu_version"] = current_menu_version

        except Exception as e:
            logger.error("MessageProcessor failed for voice session: %s", e, exc_info=True)
            error_reply = "I'm sorry, I'm having trouble right now. Could you please repeat that?"
            if stream:
                return StreamingResponse(
                    _generate_sse_stream(error_reply),
                    media_type="text/event-stream",
                )
            else:
                return _build_completion_response(error_reply)
    else:
        # Use the legacy LLM-based approach
        # Generate flow guidance to help LLM know what to do next
        flow_guidance = generate_flow_guidance(order_state, history)
        logger.info("Flow guidance generated:\n%s", flow_guidance)

        # Prepend flow guidance to user message so LLM sees current state clearly
        enhanced_user_message = flow_guidance + "\nUSER SAID: " + user_message

        # Call the bot
        try:
            llm_result = call_sandwich_bot(
                history,
                order_state,
                menu_index,
                enhanced_user_message,
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

        # Process actions from LLM result
        reply = llm_result.get("reply", "")
        actions = llm_result.get("actions", [])

        # Backward compatibility
        if not actions and llm_result.get("intent"):
            actions = [{"intent": llm_result.get("intent"), "slots": llm_result.get("slots", {})}]

        # Apply actions to order state (only for LLM path - MessageProcessor already did this)
        all_slots = {}
        for action in actions:
            intent = action.get("intent", "unknown")
            slots = action.get("slots", {})
            all_slots.update(slots)
            order_state = apply_intent_to_order_state(
                order_state, intent, slots, menu_index, returning_customer
            )

    # Check if this is the first user message - add personalized greeting
    # This is VAPI-specific and applies to both paths
    # Note: For MessageProcessor path, history was updated inside the processor
    if use_orchestrator:
        # Get updated history from result
        history = result.session.get("history", [])
    user_message_count = sum(1 for msg in history if msg.get("role") == "user")
    if user_message_count <= 1 and returning_customer and returning_customer.get("name"):
        # This is the first exchange with a returning customer
        # Prepend a personalized greeting to the LLM's response
        customer_name = returning_customer.get("name")
        greeting_prefix = f"Hi {customer_name}! Great to hear from you again. "
        reply = greeting_prefix + reply
        logger.info("Added personalized greeting for returning customer: %s", customer_name)

    # For LLM fallback path only - handle history update, payment link, order persistence, session save
    # MessageProcessor already handles these for the orchestrator path
    if not use_orchestrator:
        # Add messages to history
        session_data["history"].append({"role": "user", "content": user_message})
        session_data["history"].append({"role": "assistant", "content": reply})

        # Check if we need to send a payment link email
        payment_link_action = next(
            (a for a in actions if a.get("intent") == "request_payment_link"),
            None
        )
        if payment_link_action:
            link_method = (
                order_state.get("link_delivery_method")
                or all_slots.get("link_delivery_method")
            )
            customer_email = (
                order_state.get("customer", {}).get("email")
                or all_slots.get("customer_email")
            )
            customer_name = (
                order_state.get("customer", {}).get("name")
                or all_slots.get("customer_name")
            )
            customer_phone_for_email = (
                order_state.get("customer", {}).get("phone")
                or phone_number
            )

            if link_method == "email" and customer_email:
                items = order_state.get("items", [])
                order_type = order_state.get("order_type", "pickup")

                # Persist order early so we have an order ID for the email
                # This also calculates the total with tax
                from .main import persist_pending_order
                pending_order = persist_pending_order(
                    db, order_state, all_slots, store_id=session_store_id
                )
                order_id = pending_order.id if pending_order else 0

                # Read checkout_state AFTER persist_pending_order (which populates it with tax)
                checkout_state = order_state.get("checkout_state", {})
                order_total = (
                    pending_order.total_price if pending_order
                    else checkout_state.get("total")
                    or sum(item.get("line_total", 0) for item in items)
                )

                # Extract tax breakdown from checkout state
                subtotal = checkout_state.get("subtotal")
                city_tax = checkout_state.get("city_tax", 0)
                state_tax = checkout_state.get("state_tax", 0)
                delivery_fee = checkout_state.get("delivery_fee", 0)

                # Send the payment link email
                try:
                    email_result = send_payment_link_email(
                        to_email=customer_email,
                        order_id=order_id,
                        amount=order_total,
                        store_name=company_name,
                        customer_name=customer_name,
                        customer_phone=customer_phone_for_email,
                        order_type=order_type,
                        items=items,
                        subtotal=subtotal,
                        city_tax=city_tax,
                        state_tax=state_tax,
                        delivery_fee=delivery_fee,
                    )
                    logger.info("Voice order payment link email sent: %s", email_result.get("status"))
                except Exception as e:
                    logger.error("Failed to send payment link email for voice order: %s", e)

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

        # Update session data and save
        session_data["order"] = order_state
        _save_session_data(db, session_id, session_data)
    else:
        # For MessageProcessor path, update the phone session cache with the new session data
        # MessageProcessor already saved to database, but we need to update our local cache
        session_data["history"] = result.session.get("history", [])
        session_data["order"] = order_state
        # Update phone session cache
        normalized_phone = "".join(c for c in phone_number if c.isdigit() or c == "+")
        if normalized_phone in _phone_sessions:
            _phone_sessions[normalized_phone]["session_data"] = session_data
            _phone_sessions[normalized_phone]["last_access"] = time.time()

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
                _save_call_analytics(
                    db=db,
                    phone_number=phone_number,
                    ended_reason=ended_reason,
                    duration=duration,
                    transcript=transcript,
                )
            except Exception as e:
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
            returning_customer = _lookup_customer_by_phone(db, phone_number)

        # Get company/store info for greeting
        company = db.query(Company).first()
        store_name = company.name if company else "Zucker's Bagels"
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
        "timestamp": datetime.utcnow().isoformat(),
    }
