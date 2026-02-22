"""
Vapi Session Manager for Orderbot
=====================================

Manages phone-to-session mapping, session lifecycle, and call analytics
for Vapi voice integration. Extracted from voice_vapi.py.

Functions:
----------
- get_or_create_phone_session: Map phone number to chat session
- get_session_data: Retrieve session data from cache or database
- save_call_analytics: Record voice call analytics
- cleanup_expired_phone_sessions: Remove stale phone session entries
"""

import logging
import os
import time
import uuid
from typing import Any

from sqlalchemy.orm import Session

from ..db.models import ChatSession, SessionAnalytics
from ..schemas.enums import OrderStatus
from .customer_service import lookup_customer_by_phone
from .store_service import build_store_info, get_company


logger = logging.getLogger(__name__)

__all__ = [
    "get_or_create_phone_session",
    "get_session_data",
    "save_call_analytics",
    "cleanup_expired_phone_sessions",
    "phone_sessions",
    "PHONE_SESSION_TTL_SECONDS",
]

# Phone number to session mapping with TTL
# Structure: {phone_number: {"session_id": str, "last_access": float, "store_id": str}}
phone_sessions: dict[str, dict[str, Any]] = {}
PHONE_SESSION_TTL_SECONDS = int(os.getenv("VAPI_SESSION_TTL", "1800"))  # 30 minutes default


def cleanup_expired_phone_sessions() -> int:
    """Remove expired phone sessions. Returns count of removed sessions."""
    now = time.time()
    expired = [
        phone for phone, data in phone_sessions.items()
        if now - data.get("last_access", 0) > PHONE_SESSION_TTL_SECONDS
    ]
    for phone in expired:
        del phone_sessions[phone]
    if expired:
        logger.debug("Cleaned up %d expired phone sessions", len(expired))
    return len(expired)


def get_or_create_phone_session(
    db: Session,
    phone_number: str,
    store_id: str | None = None,
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
    if len(phone_sessions) > 100:
        cleanup_expired_phone_sessions()

    # Normalize phone number (remove spaces, dashes)
    normalized_phone = "".join(c for c in phone_number if c.isdigit() or c == "+")

    # Check for existing session in memory cache
    if normalized_phone in phone_sessions:
        session_data = phone_sessions[normalized_phone]
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
        order_status = order_state.get("status", OrderStatus.PENDING)

        # Resume if order is not yet confirmed (still in progress)
        if order_status not in (OrderStatus.CONFIRMED,):
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
            phone_sessions[normalized_phone] = {
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
    company = get_company(db)
    company_name = company.name if company else "Sammy's Subs"
    bot_name = company.bot_persona_name if company else "Sammy"

    # Get store name
    store_info = build_store_info(db, store_id, company_name=company_name)
    store_name = store_info["name"]

    # Check for returning customer
    returning_customer = lookup_customer_by_phone(db, normalized_phone)

    # Generate greeting
    if returning_customer and returning_customer.get("name"):
        welcome = f"Hello {returning_customer['name']}! Would you like to repeat your last order?"
    else:
        welcome = f"Hi, thanks for calling {store_name}! I'm {bot_name}. What can I get started for you today?"

    # Initialize session data
    session_data = {
        "history": [{"role": "assistant", "content": welcome}],
        "order": {
            "status": OrderStatus.PENDING,
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
    phone_sessions[normalized_phone] = {
        "session_id": session_id,
        "last_access": time.time(),
        "store_id": store_id,
        "session_data": session_data,
    }

    logger.info("Created new voice session for phone %s (session: %s, store: %s)",
               normalized_phone[-4:], session_id[:8], store_id or "default")

    return session_id


def get_session_data(db: Session, session_id: str) -> dict[str, Any] | None:
    """Get session data from cache or database."""
    # Check phone session cache first
    for phone, data in phone_sessions.items():
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


def save_call_analytics(
    db: Session,
    phone_number: str,
    ended_reason: str,
    duration: int | None = None,
    transcript: str | None = None,
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

    if normalized_phone in phone_sessions:
        cached = phone_sessions[normalized_phone]
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
    order_status = order_state.get("status", OrderStatus.PENDING)
    cart_total = order_state.get("total_price", 0.0)
    customer = order_state.get("customer", {})

    # Determine session status
    if order_status == OrderStatus.CONFIRMED:
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
    if normalized_phone in phone_sessions:
        del phone_sessions[normalized_phone]
