"""
Chat Analytics & Preferences Endpoints
=======================================

Analytics logging and customer preference endpoints.

Endpoints:
----------
- POST /chat/abandon: Log an abandoned session
- POST /chat/report: Report a conversation for review
- POST /chat/voice-preference: Save customer's preferred TTS voice
"""

import logging

from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import get_random_store_id
from ..db import get_db
from ..db.models import Customer, SessionAnalytics
from ..schemas.enums import OrderStatus
from ..schemas.chat import (
    AbandonedSessionRequest,
    ReportSessionRequest,
)
from ..services.session import get_or_create_session
from .chat import chat_router

logger = logging.getLogger(__name__)


@chat_router.post("/abandon", status_code=204)
def log_abandoned_session(
    payload: AbandonedSessionRequest,
    db: Session = Depends(get_db),
) -> None:
    """
    Log an abandoned session for analytics.

    Called by frontend when user leaves before completing their order.
    """
    if payload.order_status == OrderStatus.CONFIRMED:
        logger.debug("Skipping abandon log for confirmed order: %s", payload.session_id[:8])
        return None

    abandon_store_id = payload.store_id or get_random_store_id()
    session_record = SessionAnalytics(
        session_id=payload.session_id,
        status="abandoned",
        message_count=payload.message_count,
        had_items_in_cart=payload.had_items_in_cart,
        item_count=payload.item_count,
        cart_total=payload.cart_total,
        order_status=payload.order_status,
        conversation_history=payload.conversation_history,
        last_bot_message=payload.last_bot_message[:500] if payload.last_bot_message else None,
        last_user_message=payload.last_user_message[:500] if payload.last_user_message else None,
        reason=payload.reason,
        session_duration_seconds=payload.session_duration_seconds,
        store_id=abandon_store_id,
    )

    db.add(session_record)
    db.commit()

    logger.info(
        "Abandoned session logged: %s (messages: %d, items: %d, total: $%.2f, reason: %s)",
        payload.session_id[:8],
        payload.message_count,
        payload.item_count,
        payload.cart_total,
        payload.reason,
    )

    return None


@chat_router.post("/report")
def report_session(
    payload: ReportSessionRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    Report a conversation for review.

    Sends an email with session details to the review team.
    """
    from ..services.email_service import send_report_email

    session = get_or_create_session(db, payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Extract session data
    store_id = session.get("store_id")
    caller_id = session.get("caller_id")
    order = session.get("order", {})
    order_status = order.get("status", OrderStatus.PENDING)
    items = order.get("items", [])
    item_count = len(items)
    customer = order.get("customer", {})
    customer_name = customer.get("name")
    customer_phone = customer.get("phone")

    # Get last 6 messages from history
    history = session.get("history", [])
    recent_messages = history[-6:] if history else []

    try:
        result = send_report_email(
            session_id=payload.session_id,
            store_id=store_id,
            caller_id=caller_id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            recent_messages=recent_messages,
            order_status=order_status,
            item_count=item_count,
            items=items,
        )

        if result.get("status") == "error":
            logger.error("Report email failed for session %s: %s",
                         payload.session_id[:8], result.get("error"))
            raise HTTPException(status_code=500, detail="Failed to send report email")

        logger.info("Session reported: %s", payload.session_id[:8])
        return {"status": "ok"}

    except HTTPException:
        raise
    except (ValueError, KeyError, TypeError, ConnectionError, TimeoutError, OSError) as e:
        logger.error("Report endpoint failed for session %s: %s",
                     payload.session_id[:8], str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to send report")


class VoicePreferenceRequest(BaseModel):
    """Request body for saving a customer's preferred TTS voice."""
    session_id: str
    voice: str


@chat_router.post("/voice-preference", status_code=204)
def save_voice_preference(
    payload: VoicePreferenceRequest,
    db: Session = Depends(get_db),
) -> None:
    """Save the customer's preferred TTS voice to their profile."""
    session = get_or_create_session(db, payload.session_id)
    if session is None:
        return None

    customer_id = session.get("customer_id")
    if not customer_id:
        return None

    customer = db.get(Customer, customer_id)
    if customer:
        customer.preferred_voice = payload.voice
        db.commit()
