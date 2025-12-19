from typing import Dict, Any, List, Optional
from datetime import datetime
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
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .db import get_db
from .models import MenuItem, Order, OrderItem, ChatSession, Ingredient, SessionAnalytics, IngredientStoreAvailability, MenuItemStoreAvailability, Store, Company, ItemType
from sandwich_bot.sammy.llm_client import call_sandwich_bot, call_sandwich_bot_stream
from .order_logic import apply_intent_to_order_state
from .menu_index_builder import build_menu_index, get_menu_version
# Inventory tracking via available_qty removed - using 86 system instead
# from .inventory import apply_inventory_decrement_on_confirm, check_inventory_for_item, OutOfStockError
from .logging_config import setup_logging
from .tts import get_tts_provider
from .email_service import send_payment_link_email
from .voice_vapi import vapi_router

# Configure logging at module load time
setup_logging()

logger = logging.getLogger(__name__)

# ---------- Store Configuration ----------
# Default store IDs (matching frontend admin_stores.html)
DEFAULT_STORE_IDS = [
    "store_eb_001",  # East Brunswick
    "store_nb_002",  # New Brunswick
    "store_pr_003",  # Princeton
]

# Store ID to name mapping
STORE_NAMES = {
    "store_eb_001": "Sammy's Subs East Brunswick",
    "store_nb_002": "Sammy's Subs New Brunswick",
    "store_pr_003": "Sammy's Subs Princeton",
}


def get_random_store_id() -> str:
    """Get a random store ID for session/order assignment."""
    return random.choice(DEFAULT_STORE_IDS)


def get_store_name(store_id: Optional[str], db: Optional[Session] = None) -> str:
    """Get store name from store_id, with fallback to company name from database."""
    if store_id and store_id in STORE_NAMES:
        return STORE_NAMES[store_id]
    # Try to get company name from database
    if db:
        company = db.query(Company).first()
        if company:
            return company.name
    return "Sammy's Subs"  # Default name if no store specified

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
            "store_id": db_session.store_id,  # Restore store_id for per-store availability
            "caller_id": db_session.caller_id,  # Restore caller_id for returning customer
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
        db_session.store_id = session_data.get("store_id")
        db_session.caller_id = session_data.get("caller_id")
    else:
        db_session = ChatSession(
            session_id=session_id,
            history=session_data.get("history", []),
            order_state=session_data.get("order", {}),
            menu_version_sent=session_data.get("menu_version"),
            store_id=session_data.get("store_id"),
            caller_id=session_data.get("caller_id"),
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
admin_stores_router = APIRouter(prefix="/admin/stores", tags=["Admin - Stores"])
admin_company_router = APIRouter(prefix="/admin/company", tags=["Admin - Company"])

# Public router for store list (used by customer chat)
public_stores_router = APIRouter(prefix="/stores", tags=["Stores"])

# Public router for company settings (used by frontend)
public_company_router = APIRouter(prefix="/company", tags=["Company"])

# TTS router for text-to-speech endpoints
tts_router = APIRouter(prefix="/tts", tags=["Text-to-Speech"])


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
    store_id: Optional[str] = None  # Store identifier for analytics


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
    is_available: bool  # False = "86'd" / out of stock


class IngredientCreate(BaseModel):
    name: str
    category: str  # 'bread', 'protein', 'cheese', 'topping', 'sauce', etc.
    unit: str = "piece"
    track_inventory: bool = False
    is_available: bool = True


class IngredientUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    track_inventory: Optional[bool] = None
    is_available: Optional[bool] = None  # Set to False to "86" an item


class IngredientAvailabilityUpdate(BaseModel):
    """Simple payload for quickly toggling ingredient availability."""
    is_available: bool
    store_id: Optional[str] = None  # If provided, updates per-store availability; otherwise updates global


class IngredientStoreAvailabilityOut(BaseModel):
    """Response model for ingredient with store-specific availability."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    unit: str
    track_inventory: bool
    is_available: bool  # Store-specific availability (or global if no store specified)


class MenuItemStoreAvailabilityOut(BaseModel):
    """Response model for menu item with store-specific availability."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    base_price: float
    is_available: bool  # Store-specific availability


class MenuItemAvailabilityUpdate(BaseModel):
    """Payload for toggling menu item availability."""
    is_available: bool
    store_id: Optional[str] = None  # If provided, updates per-store availability


# ---------- Pydantic models for Store management ----------


class StoreOut(BaseModel):
    """Response model for store data."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    store_id: str
    name: str
    address: str
    city: str
    state: str
    zip_code: str
    phone: str
    hours: Optional[str] = None
    timezone: str = "America/New_York"
    status: str
    payment_methods: List[str] = []
    deleted_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class StoreCreate(BaseModel):
    """Payload for creating a new store."""
    name: str
    address: str
    city: str
    state: str
    zip_code: str
    phone: str
    hours: Optional[str] = None
    timezone: str = "America/New_York"
    status: str = "open"
    payment_methods: List[str] = ["cash", "credit"]


class StoreUpdate(BaseModel):
    """Payload for updating a store."""
    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    phone: Optional[str] = None
    hours: Optional[str] = None
    timezone: Optional[str] = None
    status: Optional[str] = None
    payment_methods: Optional[List[str]] = None


# ---------- Pydantic models for company settings ----------


class CompanyOut(BaseModel):
    """Response model for company settings."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    bot_persona_name: str
    tagline: Optional[str] = None
    headquarters_address: Optional[str] = None
    corporate_phone: Optional[str] = None
    corporate_email: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None
    business_hours: Optional[Dict[str, Any]] = None
    primary_item_type: str = "Sandwich"  # Dynamic: "Pizza", "Sandwich", "Taco", etc.
    signature_item_label: Optional[str] = None  # Custom label for signature items (e.g., "speed menu bagel")


class CompanyUpdate(BaseModel):
    """Payload for updating company settings."""
    name: Optional[str] = None
    bot_persona_name: Optional[str] = None
    tagline: Optional[str] = None
    headquarters_address: Optional[str] = None
    corporate_phone: Optional[str] = None
    corporate_email: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None
    business_hours: Optional[Dict[str, Any]] = None
    signature_item_label: Optional[str] = None  # Custom label for signature items


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
    store_id: Optional[str] = None  # Store identifier
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
    customer_email: Optional[str] = None
    pickup_time: Optional[str] = None
    total_price: float
    store_id: Optional[str] = None
    order_type: Optional[str] = None
    delivery_address: Optional[str] = None
    payment_status: Optional[str] = None
    payment_method: Optional[str] = None


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
    item_config: Optional[Dict[str, Any]] = None  # Coffee/drink modifiers (style, milk, syrup, etc.)
    quantity: int
    unit_price: float
    line_total: float


class OrderDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    customer_email: Optional[str] = None
    pickup_time: Optional[str] = None
    total_price: float
    store_id: Optional[str] = None
    order_type: Optional[str] = None
    delivery_address: Optional[str] = None
    payment_status: Optional[str] = None
    payment_method: Optional[str] = None
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
                "quantity": item.quantity,
                "price": item.unit_price,  # Unit price for repeat order calculations
            })

    return {
        "name": recent_order.customer_name,
        "phone": recent_order.phone,
        "order_count": order_count,
        "last_order_items": last_order_items,
        "last_order_date": recent_order.created_at.isoformat() if recent_order.created_at else None,
    }


def get_primary_item_type_name(db: Session) -> str:
    """Get the display name of the primary configurable item type."""
    primary = db.query(ItemType).filter(ItemType.is_configurable == True).first()
    return primary.display_name if primary else "Sandwich"


@chat_router.post("/start", response_model=ChatStartResponse)
@limiter.limit(get_rate_limit_chat)
def chat_start(
    request: Request,
    db: Session = Depends(get_db),
    caller_id: Optional[str] = Query(None, description="Simulated caller ID / phone number"),
    store_id: Optional[str] = Query(None, description="Store identifier (e.g., store_eb_001)"),
) -> ChatStartResponse:
    """
    Start a new chat session. Returns a session ID and welcome message.

    Args:
        caller_id: Optional phone number to simulate caller identification.
                   If provided, looks up returning customer and personalizes greeting.
        store_id: Optional store identifier to customize greeting with store name.
    """
    session_id = str(uuid.uuid4())

    # Get company info for greeting
    company = get_or_create_company(db)

    # Get store name for greeting - try database first, then use company name as fallback
    if store_id:
        store_record = db.query(Store).filter(Store.store_id == store_id).first()
        if store_record:
            store_name = store_record.name
        else:
            store_name = company.name
    else:
        store_name = company.name

    # Check for returning customer if caller_id is provided
    returning_customer = None
    if caller_id:
        returning_customer = _lookup_customer_by_phone(db, caller_id)
        logger.info("Caller ID lookup: %s -> %s", caller_id, "found" if returning_customer else "new customer")

    # Get the primary item type for dynamic greeting (e.g., "Pizza", "Sandwich")
    primary_item_type = get_primary_item_type_name(db)
    primary_item_plural = primary_item_type.lower() + ("es" if primary_item_type.lower().endswith("ch") else "s")

    # Get custom signature item label or use default
    if company.signature_item_label:
        signature_label = company.signature_item_label
    else:
        signature_label = f"signature {primary_item_plural}"

    # Generate personalized greeting for returning customers
    if returning_customer and returning_customer.get("name"):
        customer_name = returning_customer["name"]
        welcome = f"Hi {customer_name}, welcome to {store_name}! Would you like to repeat your last order or place a new order?"
    else:
        # Default greeting for new customers
        welcome = f"Hi, welcome to {store_name}! Would you like to try one of our {signature_label} or build your own?"

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
        "store_id": store_id,  # Store identifier for analytics
        "returning_customer": returning_customer,  # Store customer history for LLM context
    }

    # Save to database and cache
    save_session(db, session_id, session_data)

    logger.info("New chat session started: %s (store: %s, caller_id: %s)", session_id[:8], store_id or "default", caller_id or "none")

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
    session_store_id: Optional[str] = session.get("store_id")
    session_caller_id: Optional[str] = session.get("caller_id")

    # Get company info for LLM persona
    company = get_or_create_company(db)

    # Build menu index for LLM (with store-specific ingredient availability)
    menu_index = build_menu_index(db, store_id=session_store_id)

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
            caller_id=session_caller_id,
            bot_name=company.bot_persona_name,
            company_name=company.name,
            db=db,
            use_dynamic_prompt=True,
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
    ADD_INTENTS = {"add_sandwich", "add_pizza", "add_side", "add_drink", "add_coffee", "add_sized_beverage", "add_beverage"}

    # Apply each action sequentially
    for action in actions:
        intent = action.get("intent", "unknown")
        slots = action.get("slots", {})

        logger.debug("Processing action - intent: %s, menu_item: %s",
                    intent, slots.get("menu_item_name"))

        # If adding items to an already-persisted order, start a new order
        # This allows customers to add more items after their first order is confirmed
        # The customer info (name, phone) is preserved for convenience
        if intent in ADD_INTENTS and "db_order_id" in updated_order_state:
            logger.info("Starting new order after previous order %s was confirmed",
                       updated_order_state["db_order_id"])
            # Clear the db_order_id so the new order can be persisted
            del updated_order_state["db_order_id"]
            # Clear items from the previous order
            updated_order_state["items"] = []
            # Reset status
            updated_order_state["status"] = "pending"

        updated_order_state = apply_intent_to_order_state(
            updated_order_state, intent, slots, menu_index, returning_customer
        )
        processed_actions.append(ActionOut(intent=intent, slots=slots))

    # Save updated state back into the session
    session["order"] = updated_order_state

    logger.debug("Order state updated - status: %s, items: %d",
                updated_order_state.get("status"),
                len(updated_order_state.get("items", [])))

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
    customer_email = (
        updated_order_state.get("customer", {}).get("email")
        or all_slots.get("customer_email")
    )

    # Check if we need to send a payment link email
    payment_link_action = next(
        (a for a in actions if a.get("intent") == "request_payment_link"),
        None
    )
    if payment_link_action:
        link_method = (
            updated_order_state.get("link_delivery_method")
            or all_slots.get("link_delivery_method")
        )
        if link_method == "email" and customer_email:
            # Calculate order total for the email
            items = updated_order_state.get("items", [])
            order_total = sum(item.get("line_total", 0) for item in items)
            order_type = updated_order_state.get("order_type", "pickup")

            # Persist order early so we have an order ID for the email
            session_store_id = session.get("store_id") or get_random_store_id()
            pending_order = persist_pending_order(
                db, updated_order_state, all_slots, store_id=session_store_id
            )
            order_id = pending_order.id if pending_order else 0

            # Send the payment link email
            email_result = send_payment_link_email(
                to_email=customer_email,
                order_id=order_id,
                amount=order_total,
                store_name=company.name if company else "Restaurant",
                customer_name=customer_name,
                customer_phone=customer_phone,
                order_type=order_type,
                items=items,
            )
            logger.info("Payment link email sent: %s", email_result.get("status"))

    # Update history FIRST (before logging analytics, so conversation is complete)
    history.append({"role": "user", "content": req.message})
    history.append({"role": "assistant", "content": reply})

    # Persist if order is confirmed AND we have customer info
    # (either from this request or from a previous request)
    order_is_confirmed = updated_order_state.get("status") == "confirmed"
    has_customer_info = customer_name and customer_phone
    order_not_yet_confirmed = updated_order_state.get("_confirmed_logged") is not True

    if order_is_confirmed and has_customer_info:
        updated_order_state.setdefault("customer", {})
        updated_order_state["customer"]["name"] = customer_name
        updated_order_state["customer"]["phone"] = customer_phone

        # Get store_id from session for the order
        session_store_id = session.get("store_id") or get_random_store_id()

        # persist_confirmed_order handles both creating new orders and updating pending ones
        persist_confirmed_order(db, updated_order_state, all_slots, store_id=session_store_id)
        logger.info("Order persisted for customer: %s (store: %s)", customer_name, session_store_id)

        # Log completed session for analytics (only once per order)
        if order_not_yet_confirmed:
            updated_order_state["_confirmed_logged"] = True
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
                store_id=session_store_id,
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
    This provides immediate feedback to users instead of waiting for the full response.

    Event format:
    - data: {"token": "partial text"} - streamed tokens
    - data: {"done": true, "reply": "full reply", "order_state": {...}, "actions": [...]} - final result
    - data: {"error": "message"} - error occurred
    """
    # Get session from cache or database
    session = get_or_create_session(db, req.session_id)
    if session is None:
        def error_stream():
            yield f"data: {json.dumps({'error': 'Invalid session_id'})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    history: List[Dict[str, str]] = session["history"]
    order_state: Dict[str, Any] = session["order"]
    returning_customer: Dict[str, Any] = session.get("returning_customer")
    session_store_id: Optional[str] = session.get("store_id")
    session_caller_id: Optional[str] = session.get("caller_id")

    # Get company info for LLM persona
    company = get_or_create_company(db)

    # Build menu index for LLM (with store-specific ingredient availability)
    menu_index = build_menu_index(db, store_id=session_store_id)

    # Determine if menu needs to be sent in system prompt
    current_menu_version = get_menu_version(menu_index)
    session_menu_version = session.get("menu_version")
    include_menu_in_system = (
        session_menu_version is None or
        session_menu_version != current_menu_version
    )

    # Store values we need inside the generator (before db session closes)
    company_bot_name = company.bot_persona_name
    company_name = company.name

    def generate_stream():
        nonlocal session, history, order_state

        full_content = ""

        # Create a new database session for use inside the generator
        # (The original db session from Depends(get_db) is closed after the handler returns)
        from .db import SessionLocal
        stream_db = SessionLocal()

        try:
            # Stream tokens from LLM
            stream_gen = call_sandwich_bot_stream(
                history,
                order_state,
                menu_index,
                req.message,
                include_menu_in_system=include_menu_in_system,
                returning_customer=returning_customer,
                caller_id=session_caller_id,
                bot_name=company_bot_name,
                company_name=company_name,
                db=stream_db,
                use_dynamic_prompt=True,
                timeout=20,  # 20 second timeout for LLM response
            )

            # Yield tokens as they arrive
            token_count = 0
            for token in stream_gen:
                token_count += 1
                full_content += token
                yield f"data: {json.dumps({'token': token})}\n\n"

            logger.debug("Stream complete, %d tokens", token_count)
            # Parse the full response
            try:
                llm_result = json.loads(full_content)
            except json.JSONDecodeError:
                logger.error("JSON decode failed! Raw content: %s", full_content[:500])
                llm_result = {
                    "reply": "I'm sorry, I had trouble understanding that. Could you please rephrase?",
                    "actions": []
                }

            # Update menu version in session if we sent it
            if include_menu_in_system:
                session["menu_version"] = current_menu_version

            # Process actions (same logic as non-streaming endpoint)
            actions = llm_result.get("actions", [])
            reply = llm_result.get("reply", "")

            # Debug logging for action tracking
            logger.info("LLM response - actions: %s, reply preview: %s", actions, reply[:100] if reply else "")
            if not actions and "added" in reply.lower():
                logger.warning("LLM said 'added' but returned no actions! Reply: %s", reply[:200])

            # Backward compatibility
            if not actions and llm_result.get("intent"):
                actions = [{
                    "intent": llm_result.get("intent"),
                    "slots": llm_result.get("slots", {}),
                }]

            processed_actions = []
            updated_order_state = order_state

            ADD_INTENTS = {"add_sandwich", "add_pizza", "add_side", "add_drink", "add_coffee", "add_sized_beverage", "add_beverage"}

            # Track items that existed BEFORE this turn - only check duplicates against these
            # This allows ordering multiple of the same item type in one message
            items_before_turn = [item.get("menu_item_name", "").lower().strip()
                                 for item in order_state.get("items", [])]

            for action in actions:
                intent = action.get("intent", "unknown")
                slots = action.get("slots", {})

                # Only skip if item existed BEFORE this turn (prevents re-adding on follow-up messages)
                # Don't skip items added in this same turn (allows "two coffees" in one message)
                if intent in ADD_INTENTS:
                    menu_item_name = slots.get("menu_item_name", "").lower().strip()
                    if menu_item_name in items_before_turn:
                        intent = "noop"

                if intent != "noop":
                    updated_order_state = apply_intent_to_order_state(
                        updated_order_state, intent, slots, menu_index
                    )

                processed_actions.append({
                    "intent": intent,
                    "slots": slots
                })

            # Check if we should persist the order to database
            # Gather customer info from various sources
            all_slots = {}
            for action in processed_actions:
                all_slots.update(action.get("slots", {}))

            customer_name = (
                updated_order_state.get("customer", {}).get("name")
                or all_slots.get("customer_name")
            )
            customer_phone = (
                updated_order_state.get("customer", {}).get("phone")
                or all_slots.get("phone")
            )
            customer_email = (
                updated_order_state.get("customer", {}).get("email")
                or all_slots.get("customer_email")
            )

            # Check if we need to send a payment link email
            payment_link_action = next(
                (a for a in processed_actions if a.get("intent") == "request_payment_link"),
                None
            )
            if payment_link_action:
                link_method = (
                    updated_order_state.get("link_delivery_method")
                    or all_slots.get("link_delivery_method")
                )
                if link_method == "email" and customer_email:
                    # Calculate order total for the email
                    items = updated_order_state.get("items", [])
                    order_total = sum(item.get("line_total", 0) for item in items)
                    order_type = updated_order_state.get("order_type", "pickup")

                    # Persist order early so we have an order ID for the email
                    order_store_id = session.get("store_id") or get_random_store_id()
                    pending_order = persist_pending_order(
                        stream_db, updated_order_state, all_slots, store_id=order_store_id
                    )
                    order_id = pending_order.id if pending_order else 0

                    # Send the payment link email
                    email_result = send_payment_link_email(
                        to_email=customer_email,
                        order_id=order_id,
                        amount=order_total,
                        store_name=company_name,
                        customer_name=customer_name,
                        customer_phone=customer_phone,
                        order_type=order_type,
                        items=items,
                    )
                    logger.info("Payment link email sent: %s", email_result.get("status"))

            # Persist if order is confirmed AND we have customer info
            order_is_confirmed = updated_order_state.get("status") == "confirmed"
            has_customer_info = customer_name and customer_phone
            order_not_yet_confirmed = updated_order_state.get("_confirmed_logged") is not True

            if order_is_confirmed and has_customer_info:
                updated_order_state.setdefault("customer", {})
                updated_order_state["customer"]["name"] = customer_name
                updated_order_state["customer"]["phone"] = customer_phone

                # Get store_id from session for the order
                order_store_id = session.get("store_id") or get_random_store_id()

                # persist_confirmed_order handles both creating new orders and updating pending ones
                persist_confirmed_order(stream_db, updated_order_state, all_slots, store_id=order_store_id)
                logger.info("Order persisted for customer: %s (store: %s)", customer_name, order_store_id)

                # Log completed session for analytics (only once per order)
                if order_not_yet_confirmed:
                    updated_order_state["_confirmed_logged"] = True
                    items = updated_order_state.get("items", [])
                    session_record = SessionAnalytics(
                        session_id=req.session_id,
                        status="completed",
                        message_count=len(history) + 2,  # +2 for current exchange
                        had_items_in_cart=len(items) > 0,
                        item_count=len(items),
                        cart_total=updated_order_state.get("total_price", 0.0),
                        order_status="confirmed",
                        conversation_history=history + [
                            {"role": "user", "content": req.message},
                            {"role": "assistant", "content": reply}
                        ],
                        last_bot_message=reply[:500] if reply else None,
                        last_user_message=req.message[:500] if req.message else None,
                        reason=None,
                        customer_name=customer_name,
                        customer_phone=customer_phone,
                        store_id=order_store_id,
                    )
                    stream_db.add(session_record)
                    stream_db.commit()
                    logger.info("Completed session logged: %s", req.session_id[:8])

            # Update session
            history.append({"role": "user", "content": req.message})
            history.append({"role": "assistant", "content": reply})
            session["order"] = updated_order_state

            try:
                save_session(stream_db, req.session_id, session)
                logger.debug("Session saved successfully")
            except Exception as save_error:
                logger.error("Failed to save session: %s", str(save_error), exc_info=True)

            # Send final result
            primary_intent = processed_actions[0]["intent"] if processed_actions else "unknown"
            primary_slots = processed_actions[0]["slots"] if processed_actions else {}

            yield f"data: {json.dumps({'done': True, 'reply': reply, 'order_state': updated_order_state, 'actions': processed_actions, 'intent': primary_intent, 'slots': primary_slots})}\n\n"

        except Exception as e:
            logger.error("Streaming LLM call failed: %s", str(e), exc_info=True)
            yield f"data: {json.dumps({'error': 'An error occurred. Please try again.'})}\n\n"
        finally:
            # Close the database session we created for this generator
            stream_db.close()

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@chat_router.post("/debug/add-coffee")
def debug_add_coffee(
    session_id: str,
    size: str = "medium",
    db: Session = Depends(get_db),
):
    """
    DEBUG ENDPOINT: Directly add a coffee to a session, bypassing the LLM.
    Use this to test if the order logic works correctly.

    Example: POST /api/chat/debug/add-coffee?session_id=xxx&size=medium
    """
    session = get_or_create_session(db, session_id)
    if session is None:
        return {"error": "Invalid session_id"}

    order_state = session["order"]
    menu_index = build_menu_index(db)

    # Directly apply add_drink intent
    slots = {
        "menu_item_name": "Coffee",
        "quantity": 1,
        "item_config": {"size": size, "style": "black"}
    }

    updated_state = apply_intent_to_order_state(order_state, "add_drink", slots, menu_index)

    # Save the session
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
    # Use store_id from payload, fallback to random if not provided
    abandon_store_id = payload.store_id or get_random_store_id()
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


def persist_pending_order(
    db: Session,
    order_state: Dict[str, Any],
    slots: Optional[Dict[str, Any]] = None,
    store_id: Optional[str] = None,
) -> Optional[Order]:
    """
    Persist an order in pending_payment status (before confirmation).

    Used when a payment link is requested so we have an order ID for the email.
    If an order already exists (db_order_id set), returns that order.

    Args:
        db: Database session
        order_state: Current order state dict
        slots: Optional slots from the LLM action
        store_id: Optional store identifier
    """
    # If order already persisted, just return it
    existing_id = order_state.get("db_order_id")
    if existing_id:
        order = db.get(Order, existing_id)
        if order:
            return order

    slots = slots or {}
    items = order_state.get("items") or []
    customer_block = order_state.get("customer") or {}

    def first_non_empty(*vals):
        for v in vals:
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

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

    customer_email = first_non_empty(
        customer_block.get("email"),
        order_state.get("customer_email"),
        slots.get("customer_email"),
        slots.get("email"),
    )

    # Total price from items
    total_price = sum((it.get("line_total") or 0.0) for it in items)

    order_type = order_state.get("order_type", "pickup")
    delivery_address = order_state.get("delivery_address")

    # Create order with pending_payment status
    order = Order(
        status="pending_payment",
        customer_name=customer_name,
        phone=phone,
        customer_email=customer_email,
        total_price=total_price,
        store_id=store_id,
        order_type=order_type,
        delivery_address=delivery_address,
        payment_status="pending",
        payment_method=order_state.get("payment_method"),
    )
    db.add(order)
    db.flush()
    order_state["db_order_id"] = order.id

    # Add order items
    for it in items:
        menu_item_name = (
            it.get("menu_item_name")
            or it.get("name")
            or it.get("item_type")
            or "Unknown item"
        )
        bread_or_crust = it.get("bread") or it.get("crust")
        quantity = it.get("quantity", 1)
        line_total = it.get("line_total", 0.0)
        unit_price = line_total / quantity if quantity > 0 else line_total

        order_item = OrderItem(
            order_id=order.id,
            menu_item_name=menu_item_name,
            quantity=quantity,
            size=it.get("size"),
            bread=bread_or_crust,
            cheese=it.get("cheese"),
            toppings=json.dumps(it.get("toppings")) if it.get("toppings") else None,
            sauces=json.dumps(it.get("sauces") or it.get("sauce")) if (it.get("sauces") or it.get("sauce")) else None,
            unit_price=unit_price,
            line_total=line_total,
            item_config=json.dumps(it.get("item_config")) if it.get("item_config") else None,
        )
        db.add(order_item)

    db.commit()
    logger.info("Pending order #%d created for payment link", order.id)
    return order


def persist_confirmed_order(
    db: Session,
    order_state: Dict[str, Any],
    slots: Optional[Dict[str, Any]] = None,
    store_id: Optional[str] = None,
) -> Optional[Order]:
    """
    Persist a confirmed order + its items to the database.

    Idempotent:
      - If order_state has a db_order_id and that row exists, we UPDATE it.
      - Otherwise, we CREATE a new Order and store its id back into order_state["db_order_id"].

    Args:
        db: Database session
        order_state: Current order state dict
        slots: Optional slots from the LLM action
        store_id: Optional store identifier (e.g., "store_eb_001")
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

    customer_email = first_non_empty(
        customer_block.get("email"),
        order_state.get("customer_email"),
        slots.get("customer_email"),
        slots.get("email"),
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

    # Get order type, delivery address, and payment info from state
    order_type = order_state.get("order_type", "pickup")
    delivery_address = order_state.get("delivery_address")
    payment_status = order_state.get("payment_status", "unpaid")
    payment_method = order_state.get("payment_method")

    if not existing_id:
        # New order
        order = Order(
            status="confirmed",
            customer_name=customer_name,
            phone=phone,
            customer_email=customer_email,
            pickup_time=pickup_time,
            total_price=total_price,
            store_id=store_id,
            order_type=order_type,
            delivery_address=delivery_address,
            payment_status=payment_status,
            payment_method=payment_method,
        )
        db.add(order)
        db.flush()  # assign order.id
        order_state["db_order_id"] = order.id
    else:
        # Update existing order
        order.status = "confirmed"
        order.customer_name = customer_name
        order.phone = phone
        order.customer_email = customer_email
        order.pickup_time = pickup_time
        order.total_price = total_price
        order.order_type = order_type
        order.delivery_address = delivery_address
        order.payment_status = payment_status
        order.payment_method = payment_method

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

        # For pizza, use crust in the bread field (they serve same purpose)
        bread_or_crust = it.get("bread") or it.get("crust")

        oi = OrderItem(
            order_id=order.id,
            menu_item_id=it.get("menu_item_id"),
            menu_item_name=menu_item_name,
            item_type=it.get("item_type"),
            size=it.get("size"),
            bread=bread_or_crust,
            protein=it.get("protein"),
            cheese=it.get("cheese"),
            toppings=it.get("toppings") or [],
            sauces=it.get("sauces") or [],
            toasted=it.get("toasted"),
            item_config=it.get("item_config"),  # Coffee/drink modifiers (style, milk, syrup, etc.)
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

    Merges data from both extra_metadata (legacy) and default_config (new generic system).
    """
    # Start with extra_metadata (legacy field)
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

    # Merge default_config (new generic item type system) if present
    default_config = getattr(item, "default_config", None)
    if default_config and isinstance(default_config, dict):
        # Wrap in default_config key for frontend compatibility
        meta["default_config"] = default_config

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
            customer_email=o.customer_email,
            pickup_time=o.pickup_time,
            total_price=o.total_price,
            store_id=o.store_id,
            order_type=o.order_type,
            delivery_address=o.delivery_address,
            payment_status=o.payment_status,
            payment_method=o.payment_method,
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
        # Append 'Z' to indicate UTC so JavaScript parses it correctly
        created_at_str = order.created_at.isoformat() + "Z"

    return OrderDetailOut(
        id=order.id,
        status=order.status,
        customer_name=order.customer_name,
        phone=order.phone,
        customer_email=order.customer_email,
        pickup_time=order.pickup_time,
        total_price=order.total_price,
        store_id=order.store_id,
        order_type=order.order_type,
        delivery_address=order.delivery_address,
        payment_status=order.payment_status,
        payment_method=order.payment_method,
        created_at=created_at_str,
        items=items_out,
    )


# ---------- Admin ingredients endpoints ----------


@admin_ingredients_router.get("", response_model=List[IngredientStoreAvailabilityOut])
def list_ingredients(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    category: Optional[str] = Query(None, description="Filter by category: bread, protein, cheese, topping, sauce"),
    store_id: Optional[str] = Query(None, description="Store ID to check availability for"),
) -> List[IngredientStoreAvailabilityOut]:
    """List all ingredients, optionally filtered by category. If store_id provided, returns store-specific availability."""
    query = db.query(Ingredient)
    if category:
        query = query.filter(Ingredient.category == category.lower())
    ingredients = query.order_by(Ingredient.category, Ingredient.name).all()

    result = []
    for ing in ingredients:
        # Determine availability: check store-specific first, then fall back to global
        is_available = ing.is_available  # Global default
        if store_id:
            store_avail = db.query(IngredientStoreAvailability).filter(
                IngredientStoreAvailability.ingredient_id == ing.id,
                IngredientStoreAvailability.store_id == store_id
            ).first()
            if store_avail:
                is_available = store_avail.is_available

        result.append(IngredientStoreAvailabilityOut(
            id=ing.id,
            name=ing.name,
            category=ing.category,
            unit=ing.unit,
            track_inventory=ing.track_inventory,
            is_available=is_available,
        ))
    return result


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
        is_available=payload.is_available,
    )
    db.add(ingredient)
    db.commit()
    db.refresh(ingredient)
    return IngredientOut.model_validate(ingredient)


@admin_ingredients_router.get("/unavailable", response_model=List[IngredientStoreAvailabilityOut])
def list_unavailable_ingredients(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    store_id: Optional[str] = Query(None, description="Store ID to check availability for"),
) -> List[IngredientStoreAvailabilityOut]:
    """List all ingredients that are currently out of stock (86'd) for a store. Requires admin authentication."""
    if store_id:
        # Get ingredients that are 86'd for this specific store
        store_unavail = db.query(IngredientStoreAvailability).filter(
            IngredientStoreAvailability.store_id == store_id,
            IngredientStoreAvailability.is_available == False
        ).all()
        ingredient_ids = [sa.ingredient_id for sa in store_unavail]
        ingredients = db.query(Ingredient).filter(Ingredient.id.in_(ingredient_ids)).order_by(Ingredient.category, Ingredient.name).all()
    else:
        # Fall back to global unavailable
        ingredients = db.query(Ingredient).filter(Ingredient.is_available == False).order_by(Ingredient.category, Ingredient.name).all()

    return [IngredientStoreAvailabilityOut(
        id=ing.id,
        name=ing.name,
        category=ing.category,
        unit=ing.unit,
        track_inventory=ing.track_inventory,
        is_available=False,  # These are all unavailable
    ) for ing in ingredients]


# ---------- Admin menu item availability endpoints (86 system) ----------
# NOTE: These routes MUST be defined before /{ingredient_id} routes to avoid path conflicts


@admin_ingredients_router.get("/menu-items", response_model=List[MenuItemStoreAvailabilityOut])
def list_menu_items_availability(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    store_id: Optional[str] = Query(None, description="Store ID to check availability for"),
) -> List[MenuItemStoreAvailabilityOut]:
    """List all menu items with store-specific availability. Used by admin_ingredients page."""
    items = db.query(MenuItem).order_by(MenuItem.category, MenuItem.name).all()

    result = []
    for item in items:
        # Determine availability: check store-specific first, then default to True (available)
        is_available = True  # Default: available
        if store_id:
            store_avail = db.query(MenuItemStoreAvailability).filter(
                MenuItemStoreAvailability.menu_item_id == item.id,
                MenuItemStoreAvailability.store_id == store_id
            ).first()
            if store_avail:
                is_available = store_avail.is_available

        result.append(MenuItemStoreAvailabilityOut(
            id=item.id,
            name=item.name,
            category=item.category,
            base_price=item.base_price,
            is_available=is_available,
        ))
    return result


@admin_ingredients_router.get("/menu-items/unavailable", response_model=List[MenuItemStoreAvailabilityOut])
def list_unavailable_menu_items(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    store_id: Optional[str] = Query(None, description="Store ID to check availability for"),
) -> List[MenuItemStoreAvailabilityOut]:
    """List all menu items that are currently out of stock (86'd) for a store."""
    if not store_id:
        # No store specified, return empty list (menu items are per-store only)
        return []

    # Get menu items that are 86'd for this specific store
    store_unavail = db.query(MenuItemStoreAvailability).filter(
        MenuItemStoreAvailability.store_id == store_id,
        MenuItemStoreAvailability.is_available == False
    ).all()
    item_ids = [sa.menu_item_id for sa in store_unavail]
    items = db.query(MenuItem).filter(MenuItem.id.in_(item_ids)).order_by(MenuItem.category, MenuItem.name).all()

    return [MenuItemStoreAvailabilityOut(
        id=item.id,
        name=item.name,
        category=item.category,
        base_price=item.base_price,
        is_available=False,  # These are all unavailable
    ) for item in items]


@admin_ingredients_router.patch("/menu-items/{item_id}/availability", response_model=MenuItemStoreAvailabilityOut)
def update_menu_item_availability(
    item_id: int,
    payload: MenuItemAvailabilityUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> MenuItemStoreAvailabilityOut:
    """
    Quick toggle for menu item availability (86 system).
    Use this to mark menu items as out of stock or back in stock for a specific store.
    store_id is required for menu items (they are tracked per-store only).
    Requires admin authentication.
    """
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")

    if not payload.store_id:
        raise HTTPException(status_code=400, detail="store_id is required for menu item availability")

    # Update per-store availability
    store_avail = db.query(MenuItemStoreAvailability).filter(
        MenuItemStoreAvailability.menu_item_id == item_id,
        MenuItemStoreAvailability.store_id == payload.store_id
    ).first()

    if store_avail:
        store_avail.is_available = payload.is_available
    else:
        # Create new entry
        store_avail = MenuItemStoreAvailability(
            menu_item_id=item_id,
            store_id=payload.store_id,
            is_available=payload.is_available
        )
        db.add(store_avail)

    db.commit()

    status = "available" if payload.is_available else "86'd (out of stock)"
    logger.info("Menu item '%s' marked as %s for store %s", item.name, status, payload.store_id)

    return MenuItemStoreAvailabilityOut(
        id=item.id,
        name=item.name,
        category=item.category,
        base_price=item.base_price,
        is_available=payload.is_available,
    )


# ---------- Admin ingredient endpoints (parameterized routes) ----------


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
    if payload.is_available is not None:
        ingredient.is_available = payload.is_available

    db.commit()
    db.refresh(ingredient)
    return IngredientOut.model_validate(ingredient)


@admin_ingredients_router.patch("/{ingredient_id}/availability", response_model=IngredientStoreAvailabilityOut)
def update_ingredient_availability(
    ingredient_id: int,
    payload: IngredientAvailabilityUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> IngredientStoreAvailabilityOut:
    """
    Quick toggle for ingredient availability (86 system).
    Use this to mark ingredients as out of stock or back in stock.
    If store_id is provided in payload, updates per-store availability.
    Otherwise updates the global availability.
    Requires admin authentication.
    """
    ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")

    if payload.store_id:
        # Update per-store availability
        store_avail = db.query(IngredientStoreAvailability).filter(
            IngredientStoreAvailability.ingredient_id == ingredient_id,
            IngredientStoreAvailability.store_id == payload.store_id
        ).first()

        if store_avail:
            store_avail.is_available = payload.is_available
        else:
            # Create new entry
            store_avail = IngredientStoreAvailability(
                ingredient_id=ingredient_id,
                store_id=payload.store_id,
                is_available=payload.is_available
            )
            db.add(store_avail)

        db.commit()

        status = "available" if payload.is_available else "86'd (out of stock)"
        logger.info("Ingredient '%s' marked as %s for store %s", ingredient.name, status, payload.store_id)

        return IngredientStoreAvailabilityOut(
            id=ingredient.id,
            name=ingredient.name,
            category=ingredient.category,
            unit=ingredient.unit,
            track_inventory=ingredient.track_inventory,
            is_available=payload.is_available,
        )
    else:
        # Update global availability
        ingredient.is_available = payload.is_available
        db.commit()
        db.refresh(ingredient)

        status = "available" if payload.is_available else "86'd (out of stock)"
        logger.info("Ingredient '%s' marked as %s (global)", ingredient.name, status)

        return IngredientStoreAvailabilityOut(
            id=ingredient.id,
            name=ingredient.name,
            category=ingredient.category,
            unit=ingredient.unit,
            track_inventory=ingredient.track_inventory,
            is_available=ingredient.is_available,
        )


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
            store_id=s.store_id,
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


# ---------- Admin Store Management Endpoints ----------


def generate_store_id() -> str:
    """Generate a unique store ID."""
    import time
    import random
    timestamp = hex(int(time.time()))[2:]
    random_part = hex(random.randint(0, 0xFFFF))[2:].zfill(4)
    return f"store_{timestamp}_{random_part}"


def seed_default_stores(db: Session) -> None:
    """Seed default stores if the stores table is empty."""
    existing = db.query(Store).first()
    if existing:
        return  # Already has stores

    default_stores = [
        {
            "store_id": "store_eb_001",
            "name": "Sammy's Subs - East Brunswick",
            "address": "123 Main Street",
            "city": "East Brunswick",
            "state": "NJ",
            "zip_code": "08816",
            "phone": "(732) 555-0101",
            "hours": "Mon-Sat 10:00 AM - 9:00 PM, Sun 11:00 AM - 7:00 PM",
            "status": "open",
            "payment_methods": ["cash", "credit"],
        },
        {
            "store_id": "store_nb_002",
            "name": "Sammy's Subs - New Brunswick",
            "address": "456 George Street",
            "city": "New Brunswick",
            "state": "NJ",
            "zip_code": "08901",
            "phone": "(732) 555-0202",
            "hours": "Mon-Fri 9:00 AM - 10:00 PM, Sat-Sun 10:00 AM - 8:00 PM",
            "status": "open",
            "payment_methods": ["cash", "credit", "bitcoin"],
        },
        {
            "store_id": "store_pr_003",
            "name": "Sammy's Subs - Princeton",
            "address": "789 Nassau Street",
            "city": "Princeton",
            "state": "NJ",
            "zip_code": "08540",
            "phone": "(609) 555-0303",
            "hours": "Mon-Sun 11:00 AM - 8:00 PM",
            "status": "closed",
            "payment_methods": ["cash", "credit"],
        },
    ]

    for store_data in default_stores:
        store = Store(**store_data)
        db.add(store)

    db.commit()
    logger.info("Seeded %d default stores", len(default_stores))


@admin_stores_router.get("", response_model=List[StoreOut])
def list_stores(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    include_deleted: bool = Query(False, description="Include deleted stores"),
) -> List[StoreOut]:
    """List all stores. Requires admin authentication."""
    # Seed default stores if table is empty
    seed_default_stores(db)

    query = db.query(Store)
    if not include_deleted:
        query = query.filter(Store.deleted_at.is_(None))
    stores = query.order_by(Store.name).all()
    return stores


@admin_stores_router.post("", response_model=StoreOut, status_code=201)
def create_store(
    payload: StoreCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> StoreOut:
    """Create a new store. Requires admin authentication."""
    store = Store(
        store_id=generate_store_id(),
        name=payload.name,
        address=payload.address,
        city=payload.city,
        state=payload.state.upper(),
        zip_code=payload.zip_code,
        phone=payload.phone,
        hours=payload.hours,
        status=payload.status,
        payment_methods=payload.payment_methods,
    )
    db.add(store)
    db.commit()
    db.refresh(store)
    logger.info("Created store: %s (%s)", store.name, store.store_id)
    return store


@admin_stores_router.get("/{store_id}", response_model=StoreOut)
def get_store(
    store_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> StoreOut:
    """Get a single store by ID. Requires admin authentication."""
    store = db.query(Store).filter(Store.store_id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    return store


@admin_stores_router.put("/{store_id}", response_model=StoreOut)
def update_store(
    store_id: str,
    payload: StoreUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> StoreOut:
    """Update a store. Requires admin authentication."""
    store = db.query(Store).filter(Store.store_id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Update only provided fields
    if payload.name is not None:
        store.name = payload.name
    if payload.address is not None:
        store.address = payload.address
    if payload.city is not None:
        store.city = payload.city
    if payload.state is not None:
        store.state = payload.state.upper()
    if payload.zip_code is not None:
        store.zip_code = payload.zip_code
    if payload.phone is not None:
        store.phone = payload.phone
    if payload.hours is not None:
        store.hours = payload.hours
    if payload.status is not None:
        store.status = payload.status
    if payload.payment_methods is not None:
        store.payment_methods = payload.payment_methods

    db.commit()
    db.refresh(store)
    logger.info("Updated store: %s (%s)", store.name, store.store_id)
    return store


@admin_stores_router.delete("/{store_id}", status_code=204)
def delete_store(
    store_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Soft delete a store. Requires admin authentication."""
    store = db.query(Store).filter(Store.store_id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    store.deleted_at = datetime.now()
    db.commit()
    logger.info("Soft deleted store: %s (%s)", store.name, store.store_id)
    return None


@admin_stores_router.post("/{store_id}/restore", response_model=StoreOut)
def restore_store(
    store_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> StoreOut:
    """Restore a soft-deleted store. Requires admin authentication."""
    store = db.query(Store).filter(Store.store_id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    store.deleted_at = None
    db.commit()
    db.refresh(store)
    logger.info("Restored store: %s (%s)", store.name, store.store_id)
    return store


# ---------- Public Store Endpoints (for customer chat) ----------


@public_stores_router.get("", response_model=List[StoreOut])
def list_available_stores(
    db: Session = Depends(get_db),
) -> List[StoreOut]:
    """List all active and open stores. Used by customer chat for store selection."""
    # Seed default stores if table is empty
    seed_default_stores(db)

    stores = db.query(Store).filter(
        Store.deleted_at.is_(None),
        Store.status == "open"
    ).order_by(Store.name).all()
    return stores


# ---------- Company Settings Endpoints ----------


def get_or_create_company(db: Session) -> Company:
    """Get the single company record, creating it with defaults if it doesn't exist."""
    company = db.query(Company).first()
    if not company:
        company = Company(
            name="Sammy's Subs",
            bot_persona_name="Sammy",
            tagline="The best subs in town!",
        )
        db.add(company)
        db.commit()
        db.refresh(company)
        logger.info("Created default company record")
    return company


@admin_company_router.get("", response_model=CompanyOut)
def get_company_settings(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> CompanyOut:
    """Get company settings. Requires admin authentication."""
    company = get_or_create_company(db)
    return CompanyOut.model_validate(company)


@admin_company_router.put("", response_model=CompanyOut)
def update_company_settings(
    payload: CompanyUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> CompanyOut:
    """Update company settings. Requires admin authentication."""
    company = get_or_create_company(db)

    if payload.name is not None:
        company.name = payload.name
    if payload.bot_persona_name is not None:
        company.bot_persona_name = payload.bot_persona_name
    if payload.tagline is not None:
        company.tagline = payload.tagline
    if payload.headquarters_address is not None:
        company.headquarters_address = payload.headquarters_address
    if payload.corporate_phone is not None:
        company.corporate_phone = payload.corporate_phone
    if payload.corporate_email is not None:
        company.corporate_email = payload.corporate_email
    if payload.website is not None:
        company.website = payload.website
    if payload.logo_url is not None:
        company.logo_url = payload.logo_url
    if payload.business_hours is not None:
        company.business_hours = payload.business_hours
    if payload.signature_item_label is not None:
        company.signature_item_label = payload.signature_item_label

    db.commit()
    db.refresh(company)
    logger.info("Updated company settings: %s", company.name)

    return CompanyOut.model_validate(company)


@public_company_router.get("", response_model=CompanyOut)
def get_public_company_info(
    db: Session = Depends(get_db),
) -> CompanyOut:
    """Get public company information. No authentication required."""
    company = get_or_create_company(db)
    primary_item_type = get_primary_item_type_name(db)

    # Create response with dynamic primary_item_type
    company_data = {
        "id": company.id,
        "name": company.name,
        "bot_persona_name": company.bot_persona_name,
        "tagline": company.tagline,
        "headquarters_address": company.headquarters_address,
        "corporate_phone": company.corporate_phone,
        "corporate_email": company.corporate_email,
        "website": company.website,
        "logo_url": company.logo_url,
        "business_hours": company.business_hours,
        "primary_item_type": primary_item_type,
        "signature_item_label": company.signature_item_label,
    }
    return CompanyOut(**company_data)


# ---------- TTS (Text-to-Speech) Endpoints ----------


class TTSSynthesizeRequest(BaseModel):
    """Request model for TTS synthesis."""
    text: str = Field(..., min_length=1, max_length=5000, description="Text to synthesize")
    voice: Optional[str] = Field(None, description="Voice ID (provider-specific)")
    speed: float = Field(1.0, ge=0.25, le=4.0, description="Speech speed multiplier")


class VoiceInfo(BaseModel):
    """Information about an available voice."""
    id: str
    name: str
    gender: Optional[str] = None
    accent: Optional[str] = None
    description: Optional[str] = None


class VoicesResponse(BaseModel):
    """Response containing available voices."""
    provider: str
    voices: List[VoiceInfo]


@tts_router.get("/voices", response_model=VoicesResponse)
async def list_voices() -> VoicesResponse:
    """
    List available TTS voices.

    Returns the provider name and list of available voices with their metadata.
    """
    try:
        provider = get_tts_provider()
        voices = [
            VoiceInfo(
                id=v.id,
                name=v.name,
                gender=v.gender,
                accent=v.accent,
                description=v.description,
            )
            for v in provider.voices
        ]
        return VoicesResponse(provider=provider.name, voices=voices)
    except Exception as e:
        logger.error("Failed to get TTS voices: %s", str(e))
        raise HTTPException(status_code=500, detail="TTS service unavailable")


@tts_router.post("/synthesize")
async def synthesize_speech(req: TTSSynthesizeRequest) -> Response:
    """
    Synthesize text to speech.

    Returns audio as MP3 binary data. Use the audio/mpeg content type
    to play the response directly in the browser.

    Args:
        text: The text to convert to speech (max 5000 characters)
        voice: Voice ID to use (optional, uses default if not specified)
        speed: Speech speed multiplier between 0.25 and 4.0 (default 1.0)
    """
    try:
        provider = get_tts_provider()
        audio_bytes = await provider.synthesize(
            text=req.text,
            voice_id=req.voice,
            speed=req.speed,
        )

        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline",
                "Cache-Control": "no-cache",
            }
        )
    except ValueError as e:
        logger.warning("TTS validation error: %s", str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("TTS synthesis failed: %s", str(e))
        raise HTTPException(status_code=500, detail="Speech synthesis failed")


# ---------- Include Routers with API Version Prefix ----------
# All API endpoints are available under /api/v1/
# Example: /api/v1/chat/start, /api/v1/admin/menu, etc.

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(chat_router)
api_v1_router.include_router(admin_menu_router)
api_v1_router.include_router(admin_orders_router)
api_v1_router.include_router(admin_ingredients_router)
api_v1_router.include_router(admin_analytics_router)
api_v1_router.include_router(admin_stores_router)
api_v1_router.include_router(admin_company_router)
api_v1_router.include_router(public_stores_router)
api_v1_router.include_router(public_company_router)
api_v1_router.include_router(tts_router)
api_v1_router.include_router(vapi_router)

app.include_router(api_v1_router)

# Also mount at root for backward compatibility (will be deprecated in v2)
# This allows existing clients to continue working without changes
app.include_router(chat_router)
app.include_router(admin_menu_router)
app.include_router(admin_orders_router)
app.include_router(admin_ingredients_router)
app.include_router(admin_analytics_router)
app.include_router(admin_stores_router)
app.include_router(admin_company_router)
app.include_router(public_stores_router)
app.include_router(public_company_router)
app.include_router(tts_router)
app.include_router(vapi_router)
