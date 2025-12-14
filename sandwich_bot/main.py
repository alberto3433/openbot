from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import uuid
import random
import secrets
import os
import logging
import json
import time
import threading

from fastapi import FastAPI, Depends, HTTPException, Query, status, Request, APIRouter, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .db import engine, get_db
from .models import Base, MenuItem, Order, OrderItem, ChatSession, Ingredient, SessionAnalytics
from .llm_client import call_sandwich_bot
from .order_logic import apply_intent_to_order_state
from .menu_index_builder import build_menu_index, get_menu_version
from .inventory import apply_inventory_decrement_on_confirm, check_inventory_for_item, OutOfStockError
from .logging_config import setup_logging

# Configure logging at module load time
setup_logging()

logger = logging.getLogger(__name__)

# ---------- Admin Authentication ----------

security = HTTPBasic()

# Load admin credentials from environment variables
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")


def verify_admin_credentials(
    credentials: HTTPBasicCredentials = Depends(security),
) -> str:
    """
    Verify HTTP Basic Auth credentials for admin endpoints.
    Returns the username if valid, raises 401 if invalid.
    """
    if not ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authentication not configured. Set ADMIN_PASSWORD environment variable.",
        )

    # Use secrets.compare_digest to prevent timing attacks
    username_correct = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        ADMIN_USERNAME.encode("utf-8"),
    )
    password_correct = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        ADMIN_PASSWORD.encode("utf-8"),
    )

    if not (username_correct and password_correct):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username

# Database migrations are handled by Alembic.
# Run `alembic upgrade head` to apply migrations before starting the server.
# For fresh databases, this creates all tables. For existing databases, it applies any pending migrations.

# ---------- Rate Limiting Configuration ----------
# Rate limits can be configured via environment variables
# Format: "X per Y" where Y is second, minute, hour, day
# Examples: "20 per minute", "100 per hour", "5 per second"
RATE_LIMIT_CHAT = os.getenv("RATE_LIMIT_CHAT", "30 per minute")
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"


def get_rate_limit_chat() -> str:
    """Return the current chat rate limit (allows dynamic override in tests)."""
    return RATE_LIMIT_CHAT


def get_session_id_or_ip(request: Request) -> str:
    """
    Get rate limit key from session_id (if in request body) or fall back to IP.
    This allows rate limiting per session for chat endpoints.
    """
    # For chat endpoints, try to get session_id from the cached body
    if hasattr(request.state, "body_json") and request.state.body_json:
        session_id = request.state.body_json.get("session_id")
        if session_id:
            return f"session:{session_id}"
    # Fall back to IP address
    return get_remote_address(request)


# Create limiter - uses in-memory storage by default
# For production with multiple workers, use Redis: Limiter(key_func=..., storage_uri="redis://...")
limiter = Limiter(key_func=get_session_id_or_ip, enabled=RATE_LIMIT_ENABLED)

app = FastAPI(
    title="Sandwich Bot API",
    description="API for the Sandwich Bot ordering system",
    version="1.0.0",
    openapi_tags=[
        {"name": "Health", "description": "Health check endpoints"},
        {"name": "Chat", "description": "Chat endpoints for customer ordering"},
        {"name": "Admin - Menu", "description": "Admin endpoints for menu management"},
        {"name": "Admin - Orders", "description": "Admin endpoints for order management"},
    ],
)

# ---------- Request ID Middleware ----------
# Adds a unique request ID to each request for debugging and log correlation


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds a unique request ID to each request.
    The ID is available in request.state.request_id and returned in X-Request-ID header.
    """

    async def dispatch(self, request: Request, call_next):
        # Generate unique request ID (or use one from header if provided)
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # Store in request state for access in endpoints
        request.state.request_id = request_id

        # Process request
        response = await call_next(request)

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        return response


# Add request ID middleware (before other middleware)
app.add_middleware(RequestIDMiddleware)

# Add rate limit exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS configuration
# In production, set CORS_ORIGINS environment variable to restrict allowed origins
# Example: CORS_ORIGINS="https://myshop.com,https://admin.myshop.com"
# Default allows all origins for local development
_cors_origins_env = os.getenv("CORS_ORIGINS", "")
CORS_ORIGINS = [origin.strip() for origin in _cors_origins_env.split(",") if origin.strip()] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session cache for performance (backed by database)
# This acts as a write-through cache - reads check DB if not in cache
# Sessions expire from cache after SESSION_TTL_SECONDS (still persisted in DB)
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "3600"))  # Default 1 hour
SESSION_MAX_CACHE_SIZE = int(os.getenv("SESSION_MAX_CACHE_SIZE", "1000"))  # Max cached sessions

# Cache structure: {session_id: {"data": {...}, "last_access": timestamp}}
SESSION_CACHE: Dict[str, Dict[str, Any]] = {}
_cache_lock = threading.Lock()


def _cleanup_expired_sessions() -> int:
    """Remove expired sessions from cache. Returns number of sessions removed."""
    now = time.time()
    expired = []
    with _cache_lock:
        for sid, entry in SESSION_CACHE.items():
            if now - entry.get("last_access", 0) > SESSION_TTL_SECONDS:
                expired.append(sid)
        for sid in expired:
            del SESSION_CACHE[sid]
    if expired:
        logger.debug("Cleaned up %d expired sessions from cache", len(expired))
    return len(expired)


def _evict_oldest_sessions(count: int) -> None:
    """Evict the oldest sessions from cache to make room for new ones."""
    with _cache_lock:
        if len(SESSION_CACHE) <= SESSION_MAX_CACHE_SIZE:
            return
        # Sort by last_access and remove oldest
        sorted_sessions = sorted(
            SESSION_CACHE.items(),
            key=lambda x: x[1].get("last_access", 0)
        )
        to_remove = sorted_sessions[:count]
        for sid, _ in to_remove:
            del SESSION_CACHE[sid]
        logger.debug("Evicted %d oldest sessions from cache", len(to_remove))


def get_or_create_session(db: Session, session_id: str) -> Optional[Dict[str, Any]]:
    """
    Get session from cache or database. Returns None if not found.
    Updates last_access time on cache hit.
    """
    # Periodic cleanup (roughly every 100 calls)
    if random.randint(1, 100) == 1:
        _cleanup_expired_sessions()

    # Check cache first
    with _cache_lock:
        if session_id in SESSION_CACHE:
            entry = SESSION_CACHE[session_id]
            entry["last_access"] = time.time()
            return entry["data"]

    # Check database
    db_session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
    if db_session:
        session_data = {
            "history": db_session.history or [],
            "order": db_session.order_state or {},
            "menu_version": db_session.menu_version_sent,  # Track which menu version was sent
        }
        # Add to cache
        with _cache_lock:
            if len(SESSION_CACHE) >= SESSION_MAX_CACHE_SIZE:
                _evict_oldest_sessions(SESSION_MAX_CACHE_SIZE // 10)  # Evict 10%
            SESSION_CACHE[session_id] = {
                "data": session_data,
                "last_access": time.time(),
            }
        return session_data

    return None


def save_session(db: Session, session_id: str, session_data: Dict[str, Any]) -> None:
    """
    Save session to both cache and database.
    """
    # Update cache with TTL tracking
    with _cache_lock:
        if len(SESSION_CACHE) >= SESSION_MAX_CACHE_SIZE and session_id not in SESSION_CACHE:
            _evict_oldest_sessions(SESSION_MAX_CACHE_SIZE // 10)  # Evict 10%
        SESSION_CACHE[session_id] = {
            "data": session_data,
            "last_access": time.time(),
        }

    # Update or create in database
    db_session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
    if db_session:
        db_session.history = session_data.get("history", [])
        db_session.order_state = session_data.get("order", {})
        db_session.menu_version_sent = session_data.get("menu_version")
    else:
        db_session = ChatSession(
            session_id=session_id,
            history=session_data.get("history", []),
            order_state=session_data.get("order", {}),
            menu_version_sent=session_data.get("menu_version"),
        )
        db.add(db_session)

    db.commit()

# Mount static files (chat UI, admin UI)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ---------- API Routers with Versioning ----------
# All API endpoints are versioned under /api/v1/
# This allows future API versions without breaking existing clients

# Chat router for customer-facing endpoints
chat_router = APIRouter(prefix="/chat", tags=["Chat"])

# Admin routers for management endpoints
admin_menu_router = APIRouter(prefix="/admin/menu", tags=["Admin - Menu"])
admin_orders_router = APIRouter(prefix="/admin/orders", tags=["Admin - Orders"])
admin_ingredients_router = APIRouter(prefix="/admin/ingredients", tags=["Admin - Ingredients"])
admin_analytics_router = APIRouter(prefix="/admin/analytics", tags=["Admin - Analytics"])


# ---------- Pydantic models for chat / menu ----------


class ReturningCustomerInfo(BaseModel):
    """Info about a returning customer identified by caller ID."""
    name: Optional[str] = None
    phone: Optional[str] = None
    order_count: int = 0
    last_order_items: List[Dict[str, Any]] = []
    last_order_date: Optional[str] = None


class ChatStartResponse(BaseModel):
    session_id: str
    message: str  # initial greeting from Sammy
    returning_customer: Optional[ReturningCustomerInfo] = None  # Present if caller ID matched a returning customer


# Maximum allowed message length (characters) - prevents excessive LLM token usage
MAX_MESSAGE_LENGTH = int(os.getenv("MAX_MESSAGE_LENGTH", "2000"))


class ChatMessageRequest(BaseModel):
    session_id: str
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LENGTH)


class ActionOut(BaseModel):
    """A single action performed on the order."""
    intent: str
    slots: Dict[str, Any]


class ChatMessageResponse(BaseModel):
    reply: str
    order_state: Dict[str, Any]
    actions: List[ActionOut] = Field(default_factory=list, description="List of actions performed")
    # Keep these for backward compatibility
    intent: Optional[str] = Field(None, description="Primary intent (deprecated, use actions)")
    slots: Optional[Dict[str, Any]] = Field(None, description="Primary slots (deprecated, use actions)")


class AbandonedSessionRequest(BaseModel):
    """Request to log an abandoned session (user hung up / closed browser)."""
    session_id: str
    message_count: int = 0
    had_items_in_cart: bool = False
    item_count: int = 0
    cart_total: float = 0.0
    order_status: str = "pending"
    last_bot_message: Optional[str] = None
    last_user_message: Optional[str] = None
    reason: str = "browser_close"  # browser_close, refresh, navigation
    session_duration_seconds: Optional[int] = None
    conversation_history: Optional[List[Dict[str, str]]] = None  # Full conversation [{role, content}, ...]


class MenuItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    is_signature: bool
    base_price: float
    available_qty: int
    metadata: Dict[str, Any]


class MenuItemCreate(BaseModel):
    name: str
    category: str
    is_signature: bool = False
    base_price: float
    available_qty: int = 0
    metadata: Dict[str, Any] = {}


class MenuItemUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    is_signature: Optional[bool] = None
    base_price: Optional[float] = None
    available_qty: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


# ---------- Pydantic models for ingredients admin ----------


class IngredientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    unit: str
    track_inventory: bool


class IngredientCreate(BaseModel):
    name: str
    category: str  # 'bread', 'protein', 'cheese', 'topping', 'sauce', etc.
    unit: str = "piece"
    track_inventory: bool = False


class IngredientUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    track_inventory: Optional[bool] = None


# ---------- Pydantic models for analytics admin UI ----------


class SessionAnalyticsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    status: str  # 'abandoned' or 'completed'
    message_count: int
    had_items_in_cart: bool
    item_count: int
    cart_total: float
    order_status: str
    conversation_history: Optional[List[Dict[str, str]]] = None  # Full conversation
    last_bot_message: Optional[str] = None
    last_user_message: Optional[str] = None
    reason: Optional[str] = None  # For abandoned sessions
    session_duration_seconds: Optional[int] = None
    customer_name: Optional[str] = None  # For completed sessions
    customer_phone: Optional[str] = None  # For completed sessions
    ended_at: str  # ISO format string


class SessionAnalyticsListResponse(BaseModel):
    items: List[SessionAnalyticsOut]
    page: int
    page_size: int
    total: int
    has_next: bool


class AnalyticsSummary(BaseModel):
    total_sessions: int
    completed_sessions: int
    abandoned_sessions: int
    abandoned_with_items: int
    total_revenue: float  # From completed orders
    total_lost_revenue: float  # From abandoned with items
    avg_session_duration: Optional[float] = None
    completion_rate: float  # Percentage
    abandonment_by_reason: Dict[str, int]
    recent_trend: List[Dict[str, Any]]  # Last 7 days counts by status


# ---------- Pydantic models for orders admin UI ----------


class OrderSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    pickup_time: Optional[str] = None
    total_price: float


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    menu_item_name: str
    item_type: Optional[str] = None
    size: Optional[str] = None
    bread: Optional[str] = None
    protein: Optional[str] = None
    cheese: Optional[str] = None
    toppings: Optional[List[str]] = None
    sauces: Optional[List[str]] = None
    toasted: Optional[bool] = None
    quantity: int
    unit_price: float
    line_total: float


class OrderDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    pickup_time: Optional[str] = None
    total_price: float
    created_at: str
    items: List[OrderItemOut]


class OrderListResponse(BaseModel):
    items: List[OrderSummaryOut]
    page: int
    page_size: int
    total: int
    has_next: bool


# ---------- Health ----------


@app.get("/health", tags=["Health"])
def health() -> Dict[str, str]:
    """Health check endpoint. Returns ok if the service is running."""
    return {"status": "ok"}


# ---------- Chat endpoints ----------


def _lookup_customer_by_phone(db: Session, phone: str) -> Optional[Dict[str, Any]]:
    """
    Look up a returning customer by phone number.
    Returns customer info and order history if found.
    """
    if not phone:
        return None

    # Normalize phone number (remove common formatting)
    normalized_phone = phone.replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
    # Use last 10 digits for matching (handles +1 country code)
    phone_suffix = normalized_phone[-10:] if len(normalized_phone) >= 10 else normalized_phone

    # Use SQL func.replace to normalize stored phone numbers for comparison
    from sqlalchemy import func
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

    # Find most recent order with this phone number
    recent_order = (
        db.query(Order)
        .filter(Order.phone.isnot(None))
        .filter(normalized_db_phone.like(f"%{phone_suffix}%"))
        .order_by(Order.created_at.desc())
        .first()
    )

    if not recent_order:
        return None

    # Get order history count (using same normalized phone matching)
    order_count = (
        db.query(Order)
        .filter(Order.phone.isnot(None))
        .filter(normalized_db_phone.like(f"%{phone_suffix}%"))
        .count()
    )

    # Get last order items for "usual" feature
    last_order_items = []
    if recent_order.items:
        for item in recent_order.items:
            last_order_items.append({
                "menu_item_name": item.menu_item_name,
                "item_type": item.item_type,
                "bread": item.bread,
                "protein": item.protein,
                "cheese": item.cheese,
                "toppings": item.toppings,
                "sauces": item.sauces,
                "toasted": item.toasted,
            })

    return {
        "name": recent_order.customer_name,
        "phone": recent_order.phone,
        "order_count": order_count,
        "last_order_items": last_order_items,
        "last_order_date": recent_order.created_at.isoformat() if recent_order.created_at else None,
    }


@chat_router.post("/start", response_model=ChatStartResponse)
@limiter.limit(get_rate_limit_chat)
def chat_start(
    request: Request,
    db: Session = Depends(get_db),
    caller_id: Optional[str] = Query(None, description="Simulated caller ID / phone number"),
) -> ChatStartResponse:
    """
    Start a new chat session. Returns a session ID and welcome message.

    Args:
        caller_id: Optional phone number to simulate caller identification.
                   If provided, looks up returning customer and personalizes greeting.
    """
    session_id = str(uuid.uuid4())

    # Check for returning customer if caller_id is provided
    returning_customer = None
    if caller_id:
        returning_customer = _lookup_customer_by_phone(db, caller_id)
        logger.info("Caller ID lookup: %s -> %s", caller_id, "found" if returning_customer else "new customer")

    # Generate personalized greeting for returning customers
    if returning_customer and returning_customer.get("name"):
        customer_name = returning_customer["name"]
        welcome = f"Hi {customer_name}, welcome to Subby's! Would you like to repeat your last order or place a new order?"
    else:
        # Default greeting for new customers
        welcome = "Hi, welcome to Subby's! Would you like to try one of our signature sandwiches or build your own?"

    # Initialize session data
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
        "menu_version": None,  # Will be set on first message when menu is sent to LLM
        "caller_id": caller_id,  # Store for reference
        "returning_customer": returning_customer,  # Store customer history for LLM context
    }

    # Save to database and cache
    save_session(db, session_id, session_data)

    logger.info("New chat session started: %s (caller_id: %s)", session_id[:8], caller_id or "none")

    return ChatStartResponse(
        session_id=session_id,
        message=welcome,
        returning_customer=returning_customer,  # Include in response for frontend
    )


@chat_router.post("/message", response_model=ChatMessageResponse)
@limiter.limit(get_rate_limit_chat)
def chat_message(
    request: Request,
    req: ChatMessageRequest,
    db: Session = Depends(get_db),
) -> ChatMessageResponse:
    """Send a message to the chat bot and receive a response with order updates."""
    # Get session from cache or database
    session = get_or_create_session(db, req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Invalid session_id")

    history: List[Dict[str, str]] = session["history"]
    order_state: Dict[str, Any] = session["order"]
    returning_customer: Dict[str, Any] = session.get("returning_customer")

    # Build menu index for LLM
    menu_index = build_menu_index(db)

    # Determine if menu needs to be sent in system prompt
    # Send menu if: first message (no menu_version yet) OR menu has changed
    current_menu_version = get_menu_version(menu_index)
    session_menu_version = session.get("menu_version")
    include_menu_in_system = (
        session_menu_version is None or
        session_menu_version != current_menu_version
    )

    if include_menu_in_system:
        logger.debug("Including menu in system prompt (version: %s)", current_menu_version)
    else:
        logger.debug("Skipping menu in system prompt (already sent version: %s)", session_menu_version)

    # Call OpenAI (LLM) with error handling
    try:
        llm_result = call_sandwich_bot(
            history,
            order_state,
            menu_index,
            req.message,
            include_menu_in_system=include_menu_in_system,
            returning_customer=returning_customer,
        )
        # Update menu version in session if we sent it
        if include_menu_in_system:
            session["menu_version"] = current_menu_version
    except Exception as e:
        logger.error("LLM call failed: %s", str(e))
        # Return a friendly error message without exposing internal details
        return ChatMessageResponse(
            reply="I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.",
            order_state=order_state,
            actions=[],
            intent="error",
            slots={},
        )

    # Log LLM result at DEBUG level (may contain order details)
    logger.debug("LLM result - actions: %d", len(llm_result.get("actions", [])))

    # Extract actions from the LLM response
    # Support both new format (actions array) and old format (single intent/slots)
    actions = llm_result.get("actions", [])
    reply = llm_result.get("reply", "")

    # Backward compatibility: if no actions but has intent/slots, convert to actions format
    if not actions and llm_result.get("intent"):
        actions = [
            {
                "intent": llm_result.get("intent"),
                "slots": llm_result.get("slots", {}),
            }
        ]
        logger.debug("Converted legacy intent/slots to actions format")

    # Track all processed actions for the response
    processed_actions: List[ActionOut] = []
    updated_order_state = order_state

    # Intents that add items to the order
    ADD_INTENTS = {"add_sandwich", "add_side", "add_drink"}

    # Apply each action sequentially
    out_of_stock_errors: List[str] = []
    for action in actions:
        intent = action.get("intent", "unknown")
        slots = action.get("slots", {})

        logger.debug("Processing action - intent: %s, menu_item: %s",
                    intent, slots.get("menu_item_name"))

        # Check inventory BEFORE adding items
        if intent in ADD_INTENTS:
            item_name = slots.get("menu_item_name")
            quantity = slots.get("quantity") or 1
            try:
                check_inventory_for_item(db, item_name, quantity)
            except OutOfStockError as e:
                out_of_stock_errors.append(str(e))
                logger.warning("Out of stock: %s", str(e))
                # Skip this action - don't add to order
                continue

            # If adding items to an already-persisted order, start a new order
            # This allows customers to add more items after their first order is confirmed
            # The customer info (name, phone) is preserved for convenience
            if "db_order_id" in updated_order_state:
                logger.info("Starting new order after previous order %s was confirmed",
                           updated_order_state["db_order_id"])
                # Clear the db_order_id so the new order can be persisted
                del updated_order_state["db_order_id"]
                # Clear items from the previous order
                updated_order_state["items"] = []
                # Reset status
                updated_order_state["status"] = "pending"

        try:
            updated_order_state = apply_intent_to_order_state(
                updated_order_state, intent, slots, menu_index, returning_customer
            )
            processed_actions.append(ActionOut(intent=intent, slots=slots))

        except OutOfStockError as e:
            out_of_stock_errors.append(str(e))
            logger.warning("Out of stock for item: %s", slots.get("menu_item_name"))

    # Save updated state back into the session
    session["order"] = updated_order_state

    logger.debug("Order state updated - status: %s, items: %d",
                updated_order_state.get("status"),
                len(updated_order_state.get("items", [])))

    # If there were out of stock errors, replace the reply with error info
    if out_of_stock_errors:
        error_messages = " ".join(out_of_stock_errors)
        reply = error_messages

    # Check if we should persist the order
    # This happens when:
    # 1. A confirm_order action was processed, OR
    # 2. The order is already confirmed and we just received customer info
    confirm_action = next(
        (a for a in actions if a.get("intent") == "confirm_order"),
        None
    )
    customer_info_action = next(
        (a for a in actions if a.get("intent") == "collect_customer_info"),
        None
    )

    # Gather customer info from various sources
    all_slots = {}
    for action in actions:
        all_slots.update(action.get("slots", {}))

    customer_name = (
        updated_order_state.get("customer", {}).get("name")
        or all_slots.get("customer_name")
    )
    customer_phone = (
        updated_order_state.get("customer", {}).get("phone")
        or all_slots.get("phone")
    )

    # Update history FIRST (before logging analytics, so conversation is complete)
    history.append({"role": "user", "content": req.message})
    history.append({"role": "assistant", "content": reply})

    # Persist if order is confirmed AND we have customer info
    # (either from this request or from a previous request)
    order_is_confirmed = updated_order_state.get("status") == "confirmed"
    has_customer_info = customer_name and customer_phone
    order_not_yet_persisted = "db_order_id" not in updated_order_state

    if order_is_confirmed and has_customer_info and order_not_yet_persisted:
        updated_order_state.setdefault("customer", {})
        updated_order_state["customer"]["name"] = customer_name
        updated_order_state["customer"]["phone"] = customer_phone

        apply_inventory_decrement_on_confirm(db, updated_order_state)
        persist_confirmed_order(db, updated_order_state, all_slots)
        logger.info("Order persisted for customer: %s", customer_name)

        # Log completed session for analytics
        items = updated_order_state.get("items", [])
        session_record = SessionAnalytics(
            session_id=req.session_id,
            status="completed",
            message_count=len(history),
            had_items_in_cart=len(items) > 0,
            item_count=len(items),
            cart_total=updated_order_state.get("total_price", 0.0),
            order_status="confirmed",
            conversation_history=history,  # Now includes current exchange
            last_bot_message=reply[:500] if reply else None,
            last_user_message=req.message[:500] if req.message else None,
            reason=None,  # No abandonment reason for completed orders
            customer_name=customer_name,
            customer_phone=customer_phone,
        )
        db.add(session_record)
        db.commit()
        logger.info("Completed session logged: %s", req.session_id[:8])

    # Persist session to database
    save_session(db, req.session_id, session)

    # For backward compatibility, set primary intent/slots from first action
    primary_intent = processed_actions[0].intent if processed_actions else "unknown"
    primary_slots = processed_actions[0].slots if processed_actions else {}

    return ChatMessageResponse(
        reply=reply,
        order_state=session["order"],
        actions=processed_actions,
        intent=primary_intent,
        slots=primary_slots,
    )


@chat_router.post("/abandon", status_code=204)
def log_abandoned_session(
    payload: AbandonedSessionRequest,
    db: Session = Depends(get_db),
) -> None:
    """
    Log an abandoned session for analytics.

    Called by frontend when user closes browser, refreshes, or navigates away
    before completing their order. Uses navigator.sendBeacon() for reliability.

    This endpoint does NOT require authentication since it needs to work
    during page unload when cookies/headers may not be sent.
    """
    # Don't log if order was already confirmed (completed sessions are logged separately)
    if payload.order_status == "confirmed":
        logger.debug("Skipping abandon log for confirmed order: %s", payload.session_id[:8])
        return None

    # Create the session analytics record with status='abandoned'
    session_record = SessionAnalytics(
        session_id=payload.session_id,
        status="abandoned",
        message_count=payload.message_count,
        had_items_in_cart=payload.had_items_in_cart,
        item_count=payload.item_count,
        cart_total=payload.cart_total,
        order_status=payload.order_status,
        conversation_history=payload.conversation_history,  # Store full conversation
        last_bot_message=payload.last_bot_message[:500] if payload.last_bot_message else None,
        last_user_message=payload.last_user_message[:500] if payload.last_user_message else None,
        reason=payload.reason,
        session_duration_seconds=payload.session_duration_seconds,
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


def persist_confirmed_order(
    db: Session,
    order_state: Dict[str, Any],
    slots: Optional[Dict[str, Any]] = None,
) -> Optional[Order]:
    """
    Persist a confirmed order + its items to the database.

    Idempotent:
      - If order_state has a db_order_id and that row exists, we UPDATE it.
      - Otherwise, we CREATE a new Order and store its id back into order_state["db_order_id"].
    """
    if order_state.get("status") != "confirmed":
        return None  # nothing to persist

    slots = slots or {}
    items = order_state.get("items") or []
    customer_block = order_state.get("customer") or {}

    def first_non_empty(*vals):
        for v in vals:
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    # Where can name/phone/pickup_time live?
    customer_name = first_non_empty(
        customer_block.get("name"),
        order_state.get("customer_name"),
        order_state.get("name"),
        slots.get("customer_name"),
        slots.get("name"),
    )

    phone = first_non_empty(
        customer_block.get("phone"),
        order_state.get("phone"),
        slots.get("phone"),
        slots.get("phone_number"),
    )

    pickup_time = first_non_empty(
        customer_block.get("pickup_time"),
        order_state.get("pickup_time"),
        slots.get("pickup_time"),
        slots.get("pickup_time_str"),
    )

    # Total price: try state, then slots, then sum of line_totals
    total_price = order_state.get("total_price")
    if not isinstance(total_price, (int, float)) or total_price <= 0:
        slots_total = slots.get("total_price")
        if isinstance(slots_total, (int, float)) and slots_total > 0:
            total_price = float(slots_total)
        else:
            total_price = sum((it.get("line_total") or 0.0) for it in items)

    # --- Create or update Order row ---
    existing_id = order_state.get("db_order_id")
    order: Optional[Order] = None

    if existing_id:
        # SQLAlchemy 1.4/2.0 compatible get
        order = db.get(Order, existing_id)
        if order is None:
            # stale id: fall back to creating a new one below
            existing_id = None

    if not existing_id:
        # New order
        order = Order(
            status="confirmed",
            customer_name=customer_name,
            phone=phone,
            pickup_time=pickup_time,
            total_price=total_price,
        )
        db.add(order)
        db.flush()  # assign order.id
        order_state["db_order_id"] = order.id
    else:
        # Update existing order
        order.status = "confirmed"
        order.customer_name = customer_name
        order.phone = phone
        order.pickup_time = pickup_time
        order.total_price = total_price

    # --- Replace order items with the latest items ---
    # Clear any previous items for this order
    db.query(OrderItem).filter(OrderItem.order_id == order.id).delete()

    for it in items:
        menu_item_name = (
            it.get("menu_item_name")
            or it.get("name")
            or it.get("item_type")
            or "Unknown item"
        )

        oi = OrderItem(
            order_id=order.id,
            menu_item_id=it.get("menu_item_id"),
            menu_item_name=menu_item_name,
            item_type=it.get("item_type"),
            size=it.get("size"),
            bread=it.get("bread"),
            protein=it.get("protein"),
            cheese=it.get("cheese"),
            toppings=it.get("toppings") or [],
            sauces=it.get("sauces") or [],
            toasted=it.get("toasted"),
            quantity=it.get("quantity", 1),
            unit_price=it.get("unit_price", 0.0),
            line_total=it.get("line_total", 0.0),
        )
        db.add(oi)

    db.commit()
    db.refresh(order)
    return order


def serialize_menu_item(item: MenuItem) -> MenuItemOut:
    """
    Safely convert a MenuItem ORM instance into MenuItemOut, making sure that
    the metadata field is always a plain dict.
    """
    raw_meta = getattr(item, "extra_metadata", None)

    if isinstance(raw_meta, dict):
        meta = raw_meta
    elif isinstance(raw_meta, str) and raw_meta.strip():
        try:
            meta = json.loads(raw_meta)
        except json.JSONDecodeError:
            meta = {}
    else:
        meta = {}

    return MenuItemOut(
        id=item.id,
        name=item.name,
        category=item.category,
        is_signature=item.is_signature,
        base_price=item.base_price,
        available_qty=item.available_qty,
        metadata=meta,
    )

# ---------- Admin menu endpoints ----------


@admin_menu_router.get("", response_model=List[MenuItemOut])
def admin_menu(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> List[MenuItemOut]:
    """List all menu items. Requires admin authentication."""
    items = db.query(MenuItem).order_by(MenuItem.id.asc()).all()
    return [serialize_menu_item(m) for m in items]


@admin_menu_router.post("", response_model=MenuItemOut)
def create_menu_item(
    payload: MenuItemCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> MenuItemOut:
    """Create a new menu item. Requires admin authentication."""
    item = MenuItem(
        name=payload.name,
        category=payload.category,
        is_signature=payload.is_signature,
        base_price=payload.base_price,
        available_qty=payload.available_qty,
        extra_metadata=json.dumps(payload.metadata or {}),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return serialize_menu_item(item)


@admin_menu_router.get("/{item_id}", response_model=MenuItemOut)
def get_menu_item(
    item_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> MenuItemOut:
    """Get a specific menu item by ID. Requires admin authentication."""
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    return serialize_menu_item(item)


@admin_menu_router.put("/{item_id}", response_model=MenuItemOut)
def update_menu_item(
    item_id: int,
    payload: MenuItemUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> MenuItemOut:
    """Update a menu item. Requires admin authentication."""
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")

    if payload.name is not None:
        item.name = payload.name
    if payload.category is not None:
        item.category = payload.category
    if payload.is_signature is not None:
        item.is_signature = payload.is_signature
    if payload.base_price is not None:
        item.base_price = payload.base_price
    if payload.available_qty is not None:
        item.available_qty = payload.available_qty
    if payload.metadata is not None:
        item.extra_metadata = json.dumps(payload.metadata)

    db.commit()
    db.refresh(item)
    return serialize_menu_item(item)


@admin_menu_router.delete("/{item_id}", status_code=204)
def delete_menu_item(
    item_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete a menu item. Requires admin authentication."""
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    db.delete(item)
    db.commit()
    return None


# ---------- Admin orders endpoints (for UI) ----------


@admin_orders_router.get("", response_model=OrderListResponse)
def list_orders(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    status: Optional[str] = Query(
        None,
        description="Filter by status: pending, confirmed, or leave empty for all",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> OrderListResponse:
    """
    Return a paginated list of orders. Requires admin authentication.
    """
    query = db.query(Order)

    if status in ("pending", "confirmed"):
        query = query.filter(Order.status == status)

    total = query.count()
    offset = (page - 1) * page_size

    orders = (
        query.order_by(Order.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    items = [
        OrderSummaryOut(
            id=o.id,
            status=o.status,
            customer_name=o.customer_name,
            phone=o.phone,
            pickup_time=o.pickup_time,
            total_price=o.total_price,
        )
        for o in orders
    ]

    has_next = offset + len(items) < total

    return OrderListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        has_next=has_next,
    )


@admin_orders_router.get("/{order_id}", response_model=OrderDetailOut)
def get_order_detail(
    order_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> OrderDetailOut:
    """Get detailed information about a specific order. Requires admin authentication."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    items_out = [OrderItemOut.model_validate(item) for item in order.items]

    created_at_str = ""
    if getattr(order, "created_at", None):
        created_at_str = order.created_at.isoformat()

    return OrderDetailOut(
        id=order.id,
        status=order.status,
        customer_name=order.customer_name,
        phone=order.phone,
        pickup_time=order.pickup_time,
        total_price=order.total_price,
        created_at=created_at_str,
        items=items_out,
    )


# ---------- Admin ingredients endpoints ----------


@admin_ingredients_router.get("", response_model=List[IngredientOut])
def list_ingredients(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    category: Optional[str] = Query(None, description="Filter by category: bread, protein, cheese, topping, sauce"),
) -> List[IngredientOut]:
    """List all ingredients, optionally filtered by category. Requires admin authentication."""
    query = db.query(Ingredient)
    if category:
        query = query.filter(Ingredient.category == category.lower())
    ingredients = query.order_by(Ingredient.category, Ingredient.name).all()
    return [IngredientOut.model_validate(ing) for ing in ingredients]


@admin_ingredients_router.post("", response_model=IngredientOut, status_code=201)
def create_ingredient(
    payload: IngredientCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> IngredientOut:
    """Create a new ingredient. Requires admin authentication."""
    # Check for duplicate name
    existing = db.query(Ingredient).filter(Ingredient.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Ingredient '{payload.name}' already exists")

    ingredient = Ingredient(
        name=payload.name,
        category=payload.category.lower(),
        unit=payload.unit,
        track_inventory=payload.track_inventory,
    )
    db.add(ingredient)
    db.commit()
    db.refresh(ingredient)
    return IngredientOut.model_validate(ingredient)


@admin_ingredients_router.get("/{ingredient_id}", response_model=IngredientOut)
def get_ingredient(
    ingredient_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> IngredientOut:
    """Get a specific ingredient by ID. Requires admin authentication."""
    ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")
    return IngredientOut.model_validate(ingredient)


@admin_ingredients_router.put("/{ingredient_id}", response_model=IngredientOut)
def update_ingredient(
    ingredient_id: int,
    payload: IngredientUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> IngredientOut:
    """Update an ingredient. Requires admin authentication."""
    ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")

    if payload.name is not None:
        # Check for duplicate name
        existing = db.query(Ingredient).filter(
            Ingredient.name == payload.name,
            Ingredient.id != ingredient_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Ingredient '{payload.name}' already exists")
        ingredient.name = payload.name
    if payload.category is not None:
        ingredient.category = payload.category.lower()
    if payload.unit is not None:
        ingredient.unit = payload.unit
    if payload.track_inventory is not None:
        ingredient.track_inventory = payload.track_inventory

    db.commit()
    db.refresh(ingredient)
    return IngredientOut.model_validate(ingredient)


@admin_ingredients_router.delete("/{ingredient_id}", status_code=204)
def delete_ingredient(
    ingredient_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete an ingredient. Requires admin authentication."""
    ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")
    db.delete(ingredient)
    db.commit()
    return None


# ---------- Admin analytics endpoints ----------


@admin_analytics_router.get("/sessions", response_model=SessionAnalyticsListResponse)
def list_sessions(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    status: Optional[str] = Query(None, description="Filter by status: abandoned, completed"),
    reason: Optional[str] = Query(None, description="Filter by reason: browser_close, refresh, navigation"),
    had_items: Optional[bool] = Query(None, description="Filter by whether cart had items"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> SessionAnalyticsListResponse:
    """List all sessions with pagination and filters. Requires admin authentication."""
    query = db.query(SessionAnalytics)

    if status:
        query = query.filter(SessionAnalytics.status == status)
    if reason:
        query = query.filter(SessionAnalytics.reason == reason)
    if had_items is not None:
        query = query.filter(SessionAnalytics.had_items_in_cart == had_items)

    total = query.count()
    offset = (page - 1) * page_size

    sessions = (
        query.order_by(SessionAnalytics.ended_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    items = []
    for s in sessions:
        items.append(SessionAnalyticsOut(
            id=s.id,
            session_id=s.session_id,
            status=s.status,
            message_count=s.message_count,
            had_items_in_cart=s.had_items_in_cart,
            item_count=s.item_count,
            cart_total=s.cart_total,
            order_status=s.order_status,
            conversation_history=s.conversation_history,
            last_bot_message=s.last_bot_message,
            last_user_message=s.last_user_message,
            reason=s.reason,
            session_duration_seconds=s.session_duration_seconds,
            customer_name=s.customer_name,
            customer_phone=s.customer_phone,
            ended_at=s.ended_at.isoformat() if s.ended_at else "",
        ))

    has_next = offset + len(sessions) < total

    return SessionAnalyticsListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        has_next=has_next,
    )


@admin_analytics_router.get("/summary", response_model=AnalyticsSummary)
def get_analytics_summary(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> AnalyticsSummary:
    """Get summary analytics for all sessions. Requires admin authentication."""
    from sqlalchemy import func as sqlfunc
    from datetime import datetime, timedelta

    # Total sessions
    total_sessions = db.query(SessionAnalytics).count()

    # Completed sessions
    completed_sessions = db.query(SessionAnalytics).filter(
        SessionAnalytics.status == "completed"
    ).count()

    # Abandoned sessions
    abandoned_sessions = db.query(SessionAnalytics).filter(
        SessionAnalytics.status == "abandoned"
    ).count()

    # Abandoned with items in cart
    abandoned_with_items = db.query(SessionAnalytics).filter(
        SessionAnalytics.status == "abandoned",
        SessionAnalytics.had_items_in_cart == True
    ).count()

    # Total revenue (from completed orders)
    revenue_result = db.query(sqlfunc.sum(SessionAnalytics.cart_total)).filter(
        SessionAnalytics.status == "completed"
    ).scalar()
    total_revenue = float(revenue_result) if revenue_result else 0.0

    # Total lost revenue (from abandoned with items)
    lost_revenue_result = db.query(sqlfunc.sum(SessionAnalytics.cart_total)).filter(
        SessionAnalytics.status == "abandoned",
        SessionAnalytics.had_items_in_cart == True
    ).scalar()
    total_lost_revenue = float(lost_revenue_result) if lost_revenue_result else 0.0

    # Average session duration
    avg_duration_result = db.query(sqlfunc.avg(SessionAnalytics.session_duration_seconds)).filter(
        SessionAnalytics.session_duration_seconds.isnot(None)
    ).scalar()
    avg_session_duration = float(avg_duration_result) if avg_duration_result else None

    # Completion rate
    completion_rate = (completed_sessions / total_sessions * 100) if total_sessions > 0 else 0.0

    # Abandonment by reason (only for abandoned sessions)
    reason_counts = db.query(
        SessionAnalytics.reason,
        sqlfunc.count(SessionAnalytics.id)
    ).filter(
        SessionAnalytics.status == "abandoned",
        SessionAnalytics.reason.isnot(None)
    ).group_by(SessionAnalytics.reason).all()
    abandonment_by_reason = {reason: count for reason, count in reason_counts if reason}

    # Recent trend (last 7 days) - counts by status
    recent_trend = []
    today = datetime.now().date()
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_start = datetime.combine(day, datetime.min.time())
        day_end = datetime.combine(day, datetime.max.time())

        completed_count = db.query(SessionAnalytics).filter(
            SessionAnalytics.ended_at >= day_start,
            SessionAnalytics.ended_at <= day_end,
            SessionAnalytics.status == "completed"
        ).count()

        abandoned_count = db.query(SessionAnalytics).filter(
            SessionAnalytics.ended_at >= day_start,
            SessionAnalytics.ended_at <= day_end,
            SessionAnalytics.status == "abandoned"
        ).count()

        recent_trend.append({
            "date": day.isoformat(),
            "completed": completed_count,
            "abandoned": abandoned_count,
            "total": completed_count + abandoned_count
        })

    return AnalyticsSummary(
        total_sessions=total_sessions,
        completed_sessions=completed_sessions,
        abandoned_sessions=abandoned_sessions,
        abandoned_with_items=abandoned_with_items,
        total_revenue=total_revenue,
        total_lost_revenue=total_lost_revenue,
        avg_session_duration=avg_session_duration,
        completion_rate=round(completion_rate, 1),
        abandonment_by_reason=abandonment_by_reason,
        recent_trend=recent_trend,
    )


# ---------- Include Routers with API Version Prefix ----------
# All API endpoints are available under /api/v1/
# Example: /api/v1/chat/start, /api/v1/admin/menu, etc.

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(chat_router)
api_v1_router.include_router(admin_menu_router)
api_v1_router.include_router(admin_orders_router)
api_v1_router.include_router(admin_ingredients_router)
api_v1_router.include_router(admin_analytics_router)

app.include_router(api_v1_router)

# Also mount at root for backward compatibility (will be deprecated in v2)
# This allows existing clients to continue working without changes
app.include_router(chat_router)
app.include_router(admin_menu_router)
app.include_router(admin_orders_router)
app.include_router(admin_ingredients_router)
app.include_router(admin_analytics_router)
