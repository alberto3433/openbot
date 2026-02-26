"""
Chat Session Lifecycle Routes
==============================

Router definition and session lifecycle endpoints for the ordering chatbot.

Endpoints:
----------
- POST /chat/start: Start a new chat session
- GET /chat/session/{session_id}: Restore an existing session

Message processing and analytics endpoints are in separate modules
that register on this router:
- chat_messages.py: /chat/message, /chat/message/stream
- chat_analytics.py: /chat/abandon, /chat/report, /chat/voice-preference
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..config import get_rate_limit_chat
from ..db import get_db
from ..rate_limiting import limiter
from ..schemas.chat import (
    ChatStartResponse,
    ChatRestoreResponse,
)
from ..services.session import get_or_create_session, save_session
from ..services.customer_service import lookup_customer_by_id, lookup_customer_by_phone
from ..services.store_service import get_or_create_company, build_store_info
from ..schemas.enums import OrderStatus

logger = logging.getLogger(__name__)

# Router definition
chat_router = APIRouter(prefix="/chat", tags=["Chat"])


def _generate_greeting(
    returning_customer: dict | None,
    store_name: str,
    store_is_open: bool,
    next_open_time: str | None,
) -> str:
    """Build the welcome message for a new chat session."""
    if not store_is_open and next_open_time:
        if returning_customer and returning_customer.get("name"):
            return (
                f"Hi {returning_customer['name']}! We're currently closed but we reopen {next_open_time}. "
                f"Would you like to place an order for pickup or delivery then?"
            )
        return (
            f"Hi! We're currently closed but we reopen {next_open_time}. "
            f"Would you like to place an order for pickup or delivery then?"
        )
    if returning_customer and returning_customer.get("name"):
        return f"Hi {returning_customer['name']}, welcome to {store_name}! Would you like to repeat your last order or place a new pickup or delivery order?"
    return f"Hi, welcome to {store_name}! Can I take your pickup or delivery order?"


def _build_initial_session_data(
    welcome: str,
    returning_customer: dict | None,
    resolved_customer_id: int | None,
    caller_id: str | None,
    store_id: str | None,
    store_info: dict,
    store_is_open: bool,
    default_pickup_time: str | None = None,
    store_confirmed: bool = False,
) -> dict:
    """Build the initial session data dict for a new chat session."""
    return {
        "history": [{"role": "assistant", "content": welcome}],
        "order": {
            "status": OrderStatus.PENDING,
            "items": [],
            "customer": {
                "name": returning_customer.get("name") if returning_customer else None,
                "phone": returning_customer.get("phone") if returning_customer else None,
                "pickup_time": default_pickup_time,
            },
            "total_price": 0.0,
            "state_machine_state": {
                "store_confirmed": store_confirmed,
            },
        },
        "menu_version": None,
        "caller_id": caller_id,
        "customer_id": resolved_customer_id,
        "store_id": store_id,
        "returning_customer": returning_customer,
        "store_info": store_info,
        "after_hours": not store_is_open,
    }


def _build_greeting_quick_replies(
    store_is_open: bool,
    next_open_time: str | None,
    returning_customer: dict | None,
) -> list[dict[str, str]]:
    """Build quick-reply buttons for the greeting message."""
    if not store_is_open and next_open_time:
        return [
            {"label": "pickup", "value": "pickup"},
            {"label": "delivery", "value": "delivery"},
        ]
    pickup_delivery_qr = [
        {"label": "pickup", "value": "pickup"},
        {"label": "delivery", "value": "delivery"},
    ]
    if returning_customer and returning_customer.get("name"):
        return [{"label": "Last order", "value": "repeat my last order"}] + pickup_delivery_qr
    return pickup_delivery_qr


@chat_router.post("/start", response_model=ChatStartResponse)
@limiter.limit(get_rate_limit_chat)
def chat_start(
    request: Request,
    db: Session = Depends(get_db),
    caller_id: str | None = Query(None, description="Simulated caller ID / phone number"),
    customer_id: int | None = Query(None, description="Returning customer ID from localStorage"),
    store_id: str | None = Query(None, description="Store identifier"),
) -> ChatStartResponse:
    """
    Start a new chat session.

    Returns a session ID and welcome message. If caller_id is provided,
    attempts to look up returning customer for personalized greeting.
    """
    session_id = str(uuid.uuid4())

    company = get_or_create_company(db)

    # Check for returning customer — priority: customer_id > caller_id
    returning_customer = None
    resolved_customer_id = None
    if customer_id:
        returning_customer = lookup_customer_by_id(db, customer_id)
        if returning_customer:
            resolved_customer_id = returning_customer.get("customer_id")
            logger.info("Customer ID lookup: %d -> found (%s)", customer_id, returning_customer.get("name"))
        else:
            logger.info("Customer ID lookup: %d -> not found", customer_id)
    if not returning_customer and caller_id:
        returning_customer = lookup_customer_by_phone(db, caller_id)
        logger.info("Caller ID lookup: %s -> %s", caller_id, "found" if returning_customer else "new customer")

    # Track whether the store was explicitly chosen (URL param or returning
    # customer preferred store). When False, the taking-items handler will
    # prompt the customer to pick a store before their first item order.
    store_explicitly_chosen = bool(store_id)

    # Returning customer's preferred store overrides the frontend default.
    if returning_customer:
        preferred = returning_customer.get("preferred_store_id")
        if preferred:
            if preferred != store_id:
                logger.info("Overriding frontend store %s with preferred store %s", store_id, preferred)
            store_id = preferred
            store_explicitly_chosen = True

    store_info = build_store_info(db, store_id, company_name=company.name)

    # Single-store company → auto-confirm (no need to ask)
    if not store_explicitly_chosen:
        all_stores = store_info.get("all_stores", [])
        if len(all_stores) == 1:
            store_id = all_stores[0]["store_id"]
            store_info = build_store_info(db, store_id, company_name=company.name)
            store_explicitly_chosen = True
    store_name = store_info.get("name") or company.name

    store_is_open = store_info.get("is_open", True)
    next_open_time = store_info.get("next_open_time")

    # When store is closed, default pickup time to 15 min after next open
    # (gives the kitchen time to prepare the order)
    default_pickup_time = None
    if not store_is_open:
        from ..services.store_hours import get_default_pickup_time_iso
        default_pickup_time = get_default_pickup_time_iso(store_info, lead_minutes=15)

    welcome = _generate_greeting(returning_customer, store_name, store_is_open, next_open_time)

    session_data = _build_initial_session_data(
        welcome, returning_customer, resolved_customer_id,
        caller_id, store_id, store_info, store_is_open, default_pickup_time,
        store_confirmed=store_explicitly_chosen,
    )
    save_session(db, session_id, session_data)

    logger.info("New chat session started: %s (store: %s, caller_id: %s)",
                session_id[:8], store_id or "default", caller_id or "none")

    greeting_qr = _build_greeting_quick_replies(store_is_open, next_open_time, returning_customer)

    # Prefetch TTS audio for the greeting (synthesis runs in background)
    from ..services.tts_cache import prefetch_tts
    audio_id = prefetch_tts(welcome)

    preferred_voice = returning_customer.get("preferred_voice") if returning_customer else None

    # Build initial scheduling dict so the frontend shows the correct pickup time
    from ..tasks.adapter import _build_scheduling_dict
    scheduling = _build_scheduling_dict(default_pickup_time, store_info)

    return ChatStartResponse(
        session_id=session_id,
        message=welcome,
        returning_customer=returning_customer,
        quick_replies=greeting_qr,
        audio_id=audio_id,
        customer_id=resolved_customer_id,
        preferred_voice=preferred_voice,
        scheduling=scheduling,
    )


@chat_router.get("/session/{session_id}", response_model=ChatRestoreResponse)
def chat_restore_session(
    session_id: str,
    db: Session = Depends(get_db),
) -> ChatRestoreResponse:
    """
    Restore an existing chat session.

    Returns conversation history, order state, and store info so the
    frontend can rebuild the UI after a page refresh.
    """
    session = get_or_create_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    store_id = session.get("store_id")
    store_info = build_store_info(db, store_id) if store_id else None

    from .chat_messages import _strip_internal_state
    order_state = _strip_internal_state(session.get("order", {}))

    return ChatRestoreResponse(
        session_id=session_id,
        history=session.get("history", []),
        order_state=order_state,
        store_id=store_id,
        customer_id=session.get("customer_id"),
        store_info=store_info,
    )
