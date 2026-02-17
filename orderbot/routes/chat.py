"""
Chat Routes for Orderbot
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
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..config import get_rate_limit_chat, get_random_store_id
from ..db import get_db
from ..db.models import SessionAnalytics
from ..schemas.enums import OrderStatus
from ..services.session import get_or_create_session, save_session
from ..services.customer_service import lookup_customer_by_phone
from ..services.helpers import get_primary_item_type_name
from ..services.store_service import get_or_create_company, build_store_info
from ..schemas.chat import (
    ChatStartResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    ActionOut,
    AbandonedSessionRequest,
    ReportSessionRequest,
)


logger = logging.getLogger(__name__)

# Router definition
chat_router = APIRouter(prefix="/chat", tags=["Chat"])


# =============================================================================
# Rate Limiting Setup
# =============================================================================

from ..rate_limiting import limiter


# =============================================================================
# Chat Endpoints
# =============================================================================

@chat_router.post("/start", response_model=ChatStartResponse)
@limiter.limit(get_rate_limit_chat)
def chat_start(
    request: Request,
    db: Session = Depends(get_db),
    caller_id: str | None = Query(None, description="Simulated caller ID / phone number"),
    store_id: str | None = Query(None, description="Store identifier"),
) -> ChatStartResponse:
    """
    Start a new chat session.

    Returns a session ID and welcome message. If caller_id is provided,
    attempts to look up returning customer for personalized greeting.
    """
    session_id = str(uuid.uuid4())

    company = get_or_create_company(db)

    # Build full store_info and cache in session (for use by MessageProcessor later)
    store_info = build_store_info(db, store_id, company_name=company.name)

    # Get store name from the cached store_info
    store_name = store_info.get("name") or company.name

    # Check for returning customer
    returning_customer = None
    if caller_id:
        returning_customer = lookup_customer_by_phone(db, caller_id)
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
            "status": OrderStatus.PENDING,
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
        "store_info": store_info,  # Pre-loaded store info for faster message processing
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
            item_id=req.item_id,
        ))

        processed_actions = [
            ActionOut(intent=a.get("intent", "unknown"), slots=a.get("slots", {}))
            for a in result.actions
        ]

        return ChatMessageResponse(
            reply=result.reply,
            order_state=result.order_state,
            actions=processed_actions,
            quick_replies=result.quick_replies,
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (KeyError, TypeError, AttributeError, SQLAlchemyError) as e:
        logger.error("MessageProcessor failed: %s", str(e), exc_info=True)
        return ChatMessageResponse(
            reply="I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.",
            order_state={},
            actions=[],
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
                item_id=req.item_id,
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

            final_event = {
                'done': True,
                'reply': result.reply,
                'order_state': result.order_state,
                'actions': processed_actions,
            }
            if result.quick_replies:
                final_event['quick_replies'] = result.quick_replies
            yield f"data: {json.dumps(final_event)}\n\n"

        except (ValueError, KeyError, TypeError, AttributeError, SQLAlchemyError) as e:
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
    from ..email_service import send_report_email

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
