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
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from ..config import get_rate_limit_chat, get_random_store_id
from ..db import get_db
from ..models import Order, OrderItem, Store, Company, SessionAnalytics, ItemType
from ..order_logic import apply_intent_to_order_state
from ..menu_index_builder import build_menu_index, get_menu_version
from ..email_service import send_payment_link_email
from ..services.session import get_or_create_session, save_session
from ..services.order import persist_confirmed_order
from ..sammy.llm_client import call_sandwich_bot
from ..schemas.chat import (
    ChatStartResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    ActionOut,
    AbandonedSessionRequest,
    ReturningCustomerInfo,
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
    """
    Look up a returning customer by phone number.
    Returns customer info and order history if found.
    """
    if not phone:
        return None

    # Normalize phone number
    normalized_phone = phone.replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
    phone_suffix = normalized_phone[-10:] if len(normalized_phone) >= 10 else normalized_phone

    from sqlalchemy import func
    from sqlalchemy.orm import joinedload

    normalized_db_phone = func.replace(
        func.replace(
            func.replace(
                func.replace(Order.phone, "-", ""),
                " ", ""
            ),
            "(", ""
        ),
        ")", ""
    )

    recent_order = (
        db.query(Order)
        .options(joinedload(Order.items))
        .filter(Order.phone.isnot(None))
        .filter(normalized_db_phone.like(f"%{phone_suffix}%"))
        .order_by(Order.created_at.desc())
        .first()
    )

    if not recent_order:
        return None

    order_count = (
        db.query(Order)
        .filter(Order.phone.isnot(None))
        .filter(normalized_db_phone.like(f"%{phone_suffix}%"))
        .count()
    )

    last_order_items = []
    if recent_order.items:
        for item in recent_order.items:
            item_data = {
                "menu_item_name": item.menu_item_name,
                "item_type": item.item_type,
                "bread": item.bread,
                "protein": item.protein,
                "cheese": item.cheese,
                "toppings": item.toppings,
                "sauces": item.sauces,
                "toasted": item.toasted,
                "quantity": item.quantity,
                "price": item.unit_price,
            }
            if item.item_config:
                item_data.update(item.item_config)
            last_order_items.append(item_data)

    return {
        "name": recent_order.customer_name,
        "phone": recent_order.phone,
        "email": recent_order.customer_email,
        "order_count": order_count,
        "last_order_items": last_order_items,
        "last_order_date": recent_order.created_at.isoformat() if recent_order.created_at else None,
        "last_order_type": recent_order.order_type,
        "last_order_address": recent_order.delivery_address,
    }


def get_or_create_company(db: Session) -> Company:
    """Get the company record or create a default one."""
    company = db.query(Company).first()
    if not company:
        company = Company(
            name="OrderBot Restaurant",
            bot_persona_name="OrderBot",
        )
        db.add(company)
        db.commit()
    return company


def get_primary_item_type_name(db: Session) -> str:
    """Get the display name of the primary configurable item type."""
    primary = db.query(ItemType).filter(ItemType.is_configurable == True).first()
    return primary.display_name if primary else "Sandwich"


def build_store_info(store_id: Optional[str], company_name: str, db: Optional[Session] = None) -> Dict[str, Any]:
    """Build store_info dict with tax rates and delivery zip codes."""
    store_info = {
        "name": company_name,
        "store_id": store_id,
        "city_tax_rate": 0.0,
        "state_tax_rate": 0.0,
        "delivery_zip_codes": [],
    }

    if db and store_id:
        store = db.query(Store).filter(Store.store_id == store_id).first()
        if store:
            store_info["name"] = store.name or company_name
            store_info["city_tax_rate"] = store.city_tax_rate or 0.0
            store_info["state_tax_rate"] = store.state_tax_rate or 0.0
            store_info["delivery_zip_codes"] = store.delivery_zip_codes or []

    return store_info


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
        welcome = f"Hi, welcome to {store_name}! Would you like to try one of our {signature_label} or build your own?"

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
    from ..tasks.state_machine_adapter import is_state_machine_enabled

    # Use MessageProcessor when state machine is enabled (default)
    # Fall back to LLM path when state machine is disabled (for testing)
    use_chain_orchestrator = is_state_machine_enabled()

    if use_chain_orchestrator:
        logger.info("Using MessageProcessor for chat message")
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

    # LLM Fallback path (when chain orchestrator is disabled)
    return _process_message_llm_fallback(request, req, db)


def _process_message_llm_fallback(
    request: Request,
    req: ChatMessageRequest,
    db: Session,
) -> ChatMessageResponse:
    """Process message using LLM when chain orchestrator is disabled."""
    session = get_or_create_session(db, req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Invalid session_id")

    history = session["history"]
    order_state = session["order"]
    returning_customer = session.get("returning_customer")
    session_store_id = session.get("store_id")
    session_caller_id = session.get("caller_id")

    if not returning_customer and session_caller_id:
        returning_customer = _lookup_customer_by_phone(db, session_caller_id)
        if returning_customer:
            session["returning_customer"] = returning_customer

    company = get_or_create_company(db)
    menu_index = build_menu_index(db, store_id=session_store_id)
    current_menu_version = get_menu_version(menu_index)
    session_menu_version = session.get("menu_version")
    include_menu_in_system = session_menu_version is None or session_menu_version != current_menu_version

    try:
        llm_result = call_sandwich_bot(
            history,
            order_state,
            menu_index,
            req.message,
            include_menu_in_system=include_menu_in_system,
            returning_customer=returning_customer,
            caller_id=session_caller_id,
            bot_name=company.bot_persona_name,
            company_name=company.name,
            db=db,
            use_dynamic_prompt=True,
        )
        if include_menu_in_system:
            session["menu_version"] = current_menu_version
    except Exception as e:
        logger.error("LLM call failed: %s", str(e))
        return ChatMessageResponse(
            reply="I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.",
            order_state=order_state,
            actions=[],
            intent="error",
            slots={},
        )

    actions = llm_result.get("actions", [])
    reply = llm_result.get("reply", "")

    if not actions and llm_result.get("intent"):
        actions = [{"intent": llm_result.get("intent"), "slots": llm_result.get("slots", {})}]

    processed_actions = []
    updated_order_state = order_state
    ADD_INTENTS = {"add_sandwich", "add_pizza", "add_side", "add_drink", "add_coffee", "add_sized_beverage", "add_beverage"}

    for action in actions:
        intent = action.get("intent", "unknown")
        slots = action.get("slots", {})

        if intent in ADD_INTENTS and "db_order_id" in updated_order_state:
            del updated_order_state["db_order_id"]
            updated_order_state["items"] = []
            updated_order_state["status"] = "pending"

        updated_order_state = apply_intent_to_order_state(
            updated_order_state, intent, slots, menu_index, returning_customer
        )
        processed_actions.append(ActionOut(intent=intent, slots=slots))

    # Collect all slots for order persistence
    all_slots = {}
    for action in actions:
        all_slots.update(action.get("slots", {}))

    # Get customer info from order state
    customer_block = updated_order_state.get("customer", {})
    customer_name = customer_block.get("name") or all_slots.get("customer_name") or all_slots.get("name")
    customer_phone = customer_block.get("phone") or all_slots.get("phone") or session_caller_id
    customer_email = customer_block.get("email") or all_slots.get("email")

    # Persist if order is confirmed AND we have customer info
    order_is_confirmed = updated_order_state.get("status") == "confirmed"
    has_customer_info = customer_name and (customer_phone or customer_email)
    order_not_yet_confirmed = updated_order_state.get("_confirmed_logged") is not True

    if order_is_confirmed and has_customer_info and order_not_yet_confirmed:
        # Ensure customer info is in order state for persistence
        if "customer" not in updated_order_state:
            updated_order_state["customer"] = {}
        updated_order_state["customer"]["name"] = customer_name
        updated_order_state["customer"]["phone"] = customer_phone

        # persist_confirmed_order handles both creating new orders and updating pending ones
        persist_confirmed_order(db, updated_order_state, all_slots, store_id=session_store_id)
        logger.info("Order persisted for customer: %s (store: %s)", customer_name, session_store_id)
        updated_order_state["_confirmed_logged"] = True

    session["order"] = updated_order_state
    history.append({"role": "user", "content": req.message})
    history.append({"role": "assistant", "content": reply})
    save_session(db, req.session_id, session)

    primary_intent = processed_actions[0].intent if processed_actions else "unknown"
    primary_slots = processed_actions[0].slots if processed_actions else {}

    return ChatMessageResponse(
        reply=reply,
        order_state=session["order"],
        actions=processed_actions,
        intent=primary_intent,
        slots=primary_slots,
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
    from ..tasks.state_machine_adapter import is_state_machine_enabled
    from ..db import SessionLocal

    session = get_or_create_session(db, req.session_id)
    if session is None:
        def error_stream():
            yield f"data: {json.dumps({'error': 'Invalid session_id'})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    # Use MessageProcessor when state machine is enabled (default)
    # Fall back to LLM path when state machine is disabled (for testing)
    use_chain_orchestrator = is_state_machine_enabled()
    session_store_id = session.get("store_id")
    session_caller_id = session.get("caller_id")

    def generate_stream():
        nonlocal session
        stream_db = SessionLocal()

        try:
            if use_chain_orchestrator:
                logger.info("Using MessageProcessor for streaming chat message")
                try:
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
                    return

                except Exception as e:
                    logger.error("MessageProcessor failed in stream: %s", e, exc_info=True)
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
                    return

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
    size: str = "medium",
    db: Session = Depends(get_db),
):
    """DEBUG: Directly add a coffee to a session, bypassing the LLM."""
    session = get_or_create_session(db, session_id)
    if session is None:
        return {"error": "Invalid session_id"}

    order_state = session["order"]
    menu_index = build_menu_index(db)

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
