"""
Sandwich Bot API - Main Application Entry Point
=================================================

This is the main FastAPI application for the Sandwich Bot ordering system.
It orchestrates all components by configuring the application, middleware,
and routing.

Application Overview:
---------------------
The Sandwich Bot is an AI-powered ordering system that handles:
- Customer chat interactions for food ordering
- Menu management for administrators
- Order tracking and persistence
- Session analytics and reporting
- Multi-store support with per-store configurations

Architecture:
-------------
The codebase is organized into logical modules:

- **main.py** (this file): Application setup, middleware, router mounting
- **config.py**: Environment variables and configuration
- **auth.py**: Admin authentication
- **routes/**: API endpoint handlers organized by domain
- **schemas/**: Pydantic models for request/response validation
- **services/**: Business logic and data operations
- **models.py**: SQLAlchemy ORM models
- **db.py**: Database connection and session management

Middleware Stack:
-----------------
1. RequestIDMiddleware: Adds unique ID to each request for debugging
2. AdminStaticProtectionMiddleware: Protects admin HTML files
3. CORSMiddleware: Handles cross-origin requests
4. Rate limiting via slowapi

API Versioning:
---------------
All API endpoints are available under two prefixes:
- /api/v1/* - Versioned API (recommended for new integrations)
- /* - Root paths for backward compatibility

Environment Variables:
----------------------
- ADMIN_USERNAME, ADMIN_PASSWORD: Admin authentication
- RATE_LIMIT_CHAT: Chat endpoint rate limit (default: "30 per minute")
- SESSION_TTL_SECONDS: Session cache TTL (default: 3600)
- CORS_ORIGINS: Allowed CORS origins (comma-separated)
- DATABASE_URL: Database connection string

Running the Server:
-------------------
    # Development
    uvicorn sandwich_bot.main:app --reload

    # Production
    gunicorn sandwich_bot.main:app -w 4 -k uvicorn.workers.UvicornWorker
"""

# Load environment variables FIRST, before any module imports that need them
from dotenv import load_dotenv
load_dotenv()

import logging
import pathlib
import uuid
from contextlib import asynccontextmanager
from typing import Dict

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .auth import verify_admin_credentials
from .config import (
    CORS_ORIGINS,
    RATE_LIMIT_ENABLED,
    ADMIN_PAGES,
)
from .logging_config import setup_logging

# Import routers
from .routes import (
    chat_router,
    admin_menu_router,
    admin_orders_router,
    admin_ingredients_router,
    admin_analytics_router,
    admin_stores_router,
    admin_company_router,
    admin_modifiers_router,
    admin_modifier_categories_router,
    admin_testing_router,
    public_stores_router,
    public_company_router,
    tts_router,
)
from .voice_vapi import vapi_router
from fastapi import APIRouter


# =============================================================================
# Logging Setup
# =============================================================================

setup_logging()
logger = logging.getLogger(__name__)


# =============================================================================
# Rate Limiting
# =============================================================================

def get_session_id_or_ip(request: Request) -> str:
    """Get rate limit key from session_id or fall back to IP."""
    if hasattr(request.state, "body_json") and request.state.body_json:
        session_id = request.state.body_json.get("session_id")
        if session_id:
            return f"session:{session_id}"
    return get_remote_address(request)


limiter = Limiter(key_func=get_session_id_or_ip, enabled=RATE_LIMIT_ENABLED)


# =============================================================================
# Application Lifespan
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events for startup and shutdown."""
    # Startup
    logger.info("Sandwich Bot API starting up")

    # Initialize menu data cache from database
    from .menu_data_cache import menu_cache
    from .db import SessionLocal

    logger.info("Initializing menu data cache...")
    try:
        db = SessionLocal()
        try:
            menu_cache.load_from_db(db, fail_on_error=True)
        finally:
            db.close()
    except Exception as e:
        logger.error("Failed to initialize menu data cache: %s", e)
        raise RuntimeError(f"Server startup failed: Could not load menu data cache: {e}") from e

    # Start background refresh task (runs daily at 3 AM)
    def get_db_session():
        """Context manager for database sessions."""
        from contextlib import contextmanager
        @contextmanager
        def _session():
            db = SessionLocal()
            try:
                yield db
            finally:
                db.close()
        return _session()

    await menu_cache.start_background_refresh(get_db_session)

    yield

    # Shutdown
    logger.info("Sandwich Bot API shutting down")
    await menu_cache.stop_background_refresh()


# =============================================================================
# FastAPI Application
# =============================================================================

app = FastAPI(
    title="Sandwich Bot API",
    description="API for the Sandwich Bot ordering system",
    version="1.0.0",
    openapi_tags=[
        {"name": "Health", "description": "Health check endpoints"},
        {"name": "Chat", "description": "Chat endpoints for customer ordering"},
        {"name": "Admin - Menu", "description": "Admin endpoints for menu management"},
        {"name": "Admin - Orders", "description": "Admin endpoints for order management"},
        {"name": "Admin - Ingredients", "description": "Admin endpoints for ingredient management"},
        {"name": "Admin - Analytics", "description": "Admin endpoints for session analytics"},
        {"name": "Admin - Stores", "description": "Admin endpoints for store management"},
        {"name": "Admin - Company", "description": "Admin endpoints for company settings"},
        {"name": "Admin - Modifiers", "description": "Admin endpoints for item type modifiers"},
        {"name": "Admin - Testing", "description": "Admin endpoints for testing utilities"},
        {"name": "Stores", "description": "Public store information"},
        {"name": "Company", "description": "Public company information"},
        {"name": "Text-to-Speech", "description": "TTS synthesis endpoints"},
        {"name": "VAPI", "description": "Voice API integration"},
    ],
    lifespan=lifespan,
)


# =============================================================================
# Middleware
# =============================================================================

class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Adds a unique request ID to each request for debugging and log correlation.
    The ID is available in request.state.request_id and returned in X-Request-ID header.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class AdminStaticProtectionMiddleware(BaseHTTPMiddleware):
    """
    Blocks direct access to admin HTML files in /static/.
    Users must access admin pages through the protected /admin-ui/{page} route.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Block direct access to admin files in /static/
        if path.startswith("/static/admin_") and path.endswith(".html"):
            page_name = path.replace("/static/admin_", "").replace(".html", "")
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=f"/admin-ui/{page_name}", status_code=302)

        return await call_next(request)


# Add middleware (order matters - last added is first executed)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(AdminStaticProtectionMiddleware)

# Rate limit exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Static Files
# =============================================================================

app.mount("/static", StaticFiles(directory="static"), name="static")


# =============================================================================
# Root and Health Endpoints
# =============================================================================

@app.get("/", include_in_schema=False)
def root(request: Request):
    """Redirect root to static index page, preserving query parameters."""
    from fastapi.responses import RedirectResponse
    url = "/static/index.html"
    if request.query_params:
        url += f"?{request.query_params}"
    return RedirectResponse(url=url)


@app.get("/health", tags=["Health"])
def health() -> Dict[str, str]:
    """Health check endpoint. Returns ok if the service is running."""
    return {"status": "ok"}


# =============================================================================
# Protected Admin UI
# =============================================================================

@app.get("/admin-ui/{page}", include_in_schema=False)
async def serve_admin_page(
    page: str,
    _admin: str = Depends(verify_admin_credentials),
):
    """
    Serve admin HTML pages with basic auth protection.
    Maps /admin-ui/menu -> /static/admin_menu.html, etc.
    """
    if page not in ADMIN_PAGES:
        raise HTTPException(status_code=404, detail="Admin page not found")

    file_path = pathlib.Path("static") / ADMIN_PAGES[page]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Admin page not found")

    return FileResponse(file_path, media_type="text/html")


# =============================================================================
# Router Registration
# =============================================================================

# Create versioned API router
api_v1_router = APIRouter(prefix="/api/v1")

# Register all routers under /api/v1
api_v1_router.include_router(chat_router)
api_v1_router.include_router(admin_menu_router)
api_v1_router.include_router(admin_orders_router)
api_v1_router.include_router(admin_ingredients_router)
api_v1_router.include_router(admin_analytics_router)
api_v1_router.include_router(admin_stores_router)
api_v1_router.include_router(admin_company_router)
api_v1_router.include_router(admin_modifiers_router)
api_v1_router.include_router(admin_modifier_categories_router)
api_v1_router.include_router(admin_testing_router)
api_v1_router.include_router(public_stores_router)
api_v1_router.include_router(public_company_router)
api_v1_router.include_router(tts_router)
api_v1_router.include_router(vapi_router)

# Mount versioned API
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
app.include_router(admin_modifiers_router)
app.include_router(admin_modifier_categories_router)
app.include_router(admin_testing_router)
app.include_router(public_stores_router)
app.include_router(public_company_router)
app.include_router(tts_router)
app.include_router(vapi_router)


# =============================================================================
# Backward Compatibility Exports
# =============================================================================
# These imports are re-exported for backward compatibility with existing code
# that imports from main.py. New code should import from the specific modules.

# From config
from .config import (
    RATE_LIMIT_ENABLED,
)

# From services/session

# From services/order

# From services/helpers

# From schemas - Pydantic models

# From sammy/llm_client - LLM functions
