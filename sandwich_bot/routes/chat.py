"""
Chat Routes for Sandwich Bot
=============================

This module contains all customer-facing chat endpoints for the ordering
experience. These endpoints handle the conversational interface that guides
customers through building and completing their orders.

Endpoints:
----------
- POST /chat/start: Start a new chat session
- POST /chat/message: Send a message (synchronous response)
- POST /chat/message/stream: Send a message (streaming response)
- POST /chat/abandon: Log an abandoned session
- POST /chat/debug/add-coffee: Debug endpoint for testing

Conversation Flow:
------------------
1. Customer calls /chat/start to get a session_id and greeting
2. Customer sends messages via /chat/message or /chat/message/stream
3. Bot responds with natural language + structured actions
4. Order state is maintained in the session
5. On order confirmation, order is persisted to database
6. If customer leaves without completing, /chat/abandon logs analytics

Session Management:
-------------------
Each conversation is tracked by a session_id (UUID). Sessions contain:
- Conversation history (for LLM context)
- Current order state (items, customer info, totals)
- Store assignment and menu version

Sessions are cached in memory for performance and persisted to the
database for durability.

Message Processing:
-------------------
Messages flow through the MessageProcessor which:
1. Parses the message for intents (add item, remove, checkout, etc.)
2. Updates order state based on detected intents
3. Generates an appropriate response
4. Returns structured actions for UI updates

Rate Limiting:
--------------
All chat endpoints are rate limited (default: 30/minute per session)
to prevent abuse and manage LLM API costs.

Returning Customers:
--------------------
When a caller_id (phone number) is provided on /chat/start, the system
looks up previous orders to personalize the experience:
- Greet by name
- Offer to repeat last order
- Pre-fill customer information
"""

import json
import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from ..config import get_rate_limit_chat, get_random_store_id
from ..db import get_db
from ..models import Store, SessionAnalytics
from ..order_logic import apply_intent_to_order_state
from ..menu_index_builder import get_menu_version
from ..menu_data_cache import menu_cache
from ..services.session import get_or_create_session, save_session
from ..services.helpers import get_customer_info, get_or_create_company, get_primary_item_type_name
from ..schemas.chat import (
    ChatStartResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    ActionOut,
    AbandonedSessionRequest,
)


logger = logging.getLogger(__name__)

# Router definition
chat_router = APIRouter(prefix="/chat", tags=["Chat"])


# =============================================================================
# Rate Limiting Setup
# =============================================================================

def get_session_id_or_ip(request: Request) -> str:
    """Get rate limit key from session_id or fall back to IP."""
    if hasattr(request.state, "body_json") and request.state.body_json:
        session_id = request.state.body_json.get("session_id")
        if session_id:
            return f"session:{session_id}"
    return get_remote_address(request)


# Import limiter from main app (will be set up there)
# For now, create a placeholder that will be replaced
from ..config import RATE_LIMIT_ENABLED
limiter = Limiter(key_func=get_session_id_or_ip, enabled=RATE_LIMIT_ENABLED)


# =============================================================================
# Helper Functions
# =============================================================================

def _lookup_customer_by_phone(db: Session, phone: str) -> Optional[Dict[str, Any]]:
    """Look up a returning customer by phone number.

    Delegates to the shared get_customer_info helper in services.helpers.
    """
    return get_customer_info(db, phone)


# =============================================================================
# Chat Endpoints
# =============================================================================

@chat_router.post("/start", response_model=ChatStartResponse)
@limiter.limit(get_rate_limit_chat)
def chat_start(
    request: Request,
    db: Session = Depends(get_db),
    caller_id: Optional[str] = Query(None, description="Simulated caller ID / phone number"),
    store_id: Optional[str] = Query(None, description="Store identifier"),
) -> ChatStartResponse:
    """
    Start a new chat session.

    Returns a session ID and welcome message. If caller_id is provided,
    attempts to look up returning customer for personalized greeting.
    """
    session_id = str(uuid.uuid4())

    company = get_or_create_company(db)

    # Get store name
    if store_id:
        store_record = db.query(Store).filter(Store.store_id == store_id).first()
        store_name = store_record.name if store_record else company.name
    else:
        store_name = company.name

    # Check for returning customer
    returning_customer = None
    if caller_id:
        returning_customer = _lookup_customer_by_phone(db, caller_id)
        logger.info("Caller ID lookup: %s -> %s", caller_id, "found" if returning_customer else "new customer")

    # Get primary item type for greeting
    primary_item_type = get_primary_item_type_name(db)
    primary_item_plural = primary_item_type.lower() + ("es" if primary_item_type.lower().endswith("ch") else "s")

    # Get signature label
    signature_label = company.signature_item_label or f"signature {primary_item_plural}"

    # Generate greeting
    if returning_customer and returning_customer.get("name"):
        customer_name = returning_customer["name"]
        welcome = f"Hi {customer_name}, welcome to {store_name}! Would you like to repeat your last order or place a new order?"
    else:
        welcome = f"Hi, welcome to {store_name}! Can I take your order?"

    # Initialize session
    session_data = {
        "history": [{"role": "assistant", "content": welcome}],
        "order": {
            "status": "pending",
            "items": [],
            "customer": {
                "name": returning_customer.get("name") if returning_customer else None,
                "phone": returning_customer.get("phone") if returning_customer else None,
                "pickup_time": None,
            },
            "total_price": 0.0,
        },
        "menu_version": None,
        "caller_id": caller_id,
        "store_id": store_id,
        "returning_customer": returning_customer,
    }

    save_session(db, session_id, session_data)

    logger.info("New chat session started: %s (store: %s, caller_id: %s)",
                session_id[:8], store_id or "default", caller_id or "none")

    return ChatStartResponse(
        session_id=session_id,
        message=welcome,
        returning_customer=returning_customer,
    )


@chat_router.post("/message", response_model=ChatMessageResponse)
@limiter.limit(get_rate_limit_chat)
def chat_message(
    request: Request,
    req: ChatMessageRequest,
    db: Session = Depends(get_db),
) -> ChatMessageResponse:
    """Send a message to the chat bot and receive a response with order updates."""
    from ..message_processor import MessageProcessor, ProcessingContext

    logger.info("Processing chat message for session: %s", req.session_id[:8])
    try:
        processor = MessageProcessor(db)
        result = processor.process(ProcessingContext(
            user_message=req.message,
            session_id=req.session_id,
        ))

        processed_actions = [
            ActionOut(intent=a.get("intent", "unknown"), slots=a.get("slots", {}))
            for a in result.actions
        ]

        return ChatMessageResponse(
            reply=result.reply,
            order_state=result.order_state,
            actions=processed_actions,
            intent=result.primary_intent,
            slots=result.primary_slots,
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("MessageProcessor failed: %s", str(e), exc_info=True)
        return ChatMessageResponse(
            reply="I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.",
            order_state={},
            actions=[],
            intent="error",
            slots={},
        )


@chat_router.post("/message/stream")
@limiter.limit(get_rate_limit_chat)
def chat_message_stream(
    request: Request,
    req: ChatMessageRequest,
    db: Session = Depends(get_db),
):
    """
    Streaming version of chat message endpoint.

    Uses Server-Sent Events (SSE) to stream the response as it's generated.
    """
    from ..message_processor import MessageProcessor, ProcessingContext
    from ..db import SessionLocal

    session = get_or_create_session(db, req.session_id)
    if session is None:
        def error_stream():
            yield f"data: {json.dumps({'error': 'Invalid session_id'})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    session_store_id = session.get("store_id")
    session_caller_id = session.get("caller_id")

    def generate_stream():
        nonlocal session
        stream_db = SessionLocal()

        try:
            logger.info("Processing streaming chat message for session: %s", req.session_id[:8])
            processor = MessageProcessor(stream_db)
            result = processor.process(ProcessingContext(
                user_message=req.message,
                session_id=req.session_id,
                caller_id=session_caller_id,
                store_id=session_store_id,
                session=session,
            ))

            words = result.reply.split()
            for i, word in enumerate(words):
                token = word + (" " if i < len(words) - 1 else "")
                yield f"data: {json.dumps({'token': token})}\n\n"

            processed_actions = [
                {"intent": a.get("intent", "unknown"), "slots": a.get("slots", {})}
                for a in result.actions
            ]

            yield f"data: {json.dumps({'done': True, 'reply': result.reply, 'order_state': result.order_state, 'actions': processed_actions})}\n\n"

        except Exception as e:
            logger.error("MessageProcessor failed in stream: %s", e, exc_info=True)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

        finally:
            stream_db.close()

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@chat_router.post("/debug/add-coffee")
def debug_add_coffee(
    session_id: str,
    size: str = "small",
    db: Session = Depends(get_db),
):
    """DEBUG: Directly add a coffee to a session, bypassing the LLM."""
    session = get_or_create_session(db, session_id)
    if session is None:
        return {"error": "Invalid session_id"}

    order_state = session["order"]
    menu_index = menu_cache.get_menu_index()

    slots = {
        "menu_item_name": "Coffee",
        "quantity": 1,
        "item_config": {"size": size, "style": "black"}
    }

    updated_state = apply_intent_to_order_state(order_state, "add_drink", slots, menu_index)
    session["order"] = updated_state
    save_session(db, session_id, session)

    return {
        "success": True,
        "items_count": len(updated_state.get("items", [])),
        "items": [{"name": i.get("menu_item_name"), "price": i.get("unit_price")} for i in updated_state.get("items", [])],
        "order_state": updated_state,
    }


@chat_router.post("/abandon", status_code=204)
def log_abandoned_session(
    payload: AbandonedSessionRequest,
    db: Session = Depends(get_db),
) -> None:
    """
    Log an abandoned session for analytics.

    Called by frontend when user leaves before completing their order.
    """
    if payload.order_status == "confirmed":
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
