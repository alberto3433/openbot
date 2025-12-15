"""
Application factory for multi-tenant FastAPI applications.

This module provides functions to create FastAPI applications configured
for either single-tenant or multi-tenant operation.
"""

import logging
import os
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .middleware import TenantMiddleware
from .tenant import get_tenant_manager, TenantManager

logger = logging.getLogger(__name__)


def create_app(
    tenant_slug: Optional[str] = None,
    tenant_manager: Optional[TenantManager] = None,
) -> FastAPI:
    """
    Create a FastAPI application.

    Args:
        tenant_slug: If provided, run in single-tenant mode for this tenant.
                    If None, run in multi-tenant mode with dynamic resolution.
        tenant_manager: Optional tenant manager instance. If not provided,
                       the global instance will be used.

    Returns:
        Configured FastAPI application
    """
    # Import here to avoid circular imports
    from .main import (
        app as base_app,
        api_v1_router,
        chat_router,
        admin_menu_router,
        admin_orders_router,
        admin_ingredients_router,
        admin_analytics_router,
        admin_stores_router,
        admin_company_router,
        public_stores_router,
        public_company_router,
        tts_router,
        limiter,
    )
    from slowapi.errors import RateLimitExceeded
    from slowapi import _rate_limit_exceeded_handler

    # Determine mode
    if tenant_slug:
        mode = f"single-tenant ({tenant_slug})"
    else:
        mode = "multi-tenant"

    logger.info("Creating FastAPI application in %s mode", mode)

    # Create new app instance
    app = FastAPI(
        title="Restaurant Order Bot API",
        description="Multi-tenant restaurant ordering chatbot API",
        version="2.0.0",
    )

    # Add tenant middleware
    app.add_middleware(TenantMiddleware, tenant_slug=tenant_slug)

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Configure rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Mount static files
    static_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
    if os.path.exists(static_path):
        app.mount("/static", StaticFiles(directory=static_path), name="static")

    # Include routers with API version prefix
    from fastapi import APIRouter
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(chat_router)
    api_v1.include_router(admin_menu_router)
    api_v1.include_router(admin_orders_router)
    api_v1.include_router(admin_ingredients_router)
    api_v1.include_router(admin_analytics_router)
    api_v1.include_router(admin_stores_router)
    api_v1.include_router(admin_company_router)
    api_v1.include_router(public_stores_router)
    api_v1.include_router(public_company_router)
    api_v1.include_router(tts_router)
    app.include_router(api_v1)

    # Also mount at root for backward compatibility
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

    # Health check endpoint
    @app.get("/health")
    def health_check():
        return {
            "status": "healthy",
            "mode": mode,
            "tenant": tenant_slug,
        }

    # Root redirect
    from fastapi.responses import RedirectResponse

    @app.get("/")
    def root():
        return RedirectResponse(url="/static/index.html")

    logger.info("Application created successfully in %s mode", mode)

    return app


def run_tenant(
    tenant_slug: str,
    host: str = "0.0.0.0",
    port: Optional[int] = None,
    reload: bool = False,
) -> None:
    """
    Run the application for a specific tenant.

    Args:
        tenant_slug: Tenant identifier
        host: Host to bind to
        port: Port to run on (if None, uses tenant's configured port)
        reload: Enable auto-reload for development
    """
    import uvicorn

    manager = get_tenant_manager()
    tenant = manager.get_tenant(tenant_slug)

    if not tenant:
        raise ValueError(f"Unknown tenant: {tenant_slug}")

    # Use tenant's configured port if not specified
    if port is None:
        port = tenant.port

    logger.info("Starting server for tenant '%s' on %s:%d", tenant_slug, host, port)

    # Create app for this tenant
    app = create_app(tenant_slug=tenant_slug)

    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload,
    )
