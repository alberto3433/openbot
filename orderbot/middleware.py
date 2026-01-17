"""
FastAPI middleware for multi-tenant support.
"""

import logging
from typing import Callable, Optional

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .tenant import (
    get_tenant_manager,
    set_current_tenant,
    clear_current_tenant,
)

logger = logging.getLogger(__name__)


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Middleware that resolves tenant from incoming requests and sets context.

    Tenant resolution order:
    1. X-Tenant-ID header (for testing/debugging)
    2. Host header (domain-based routing)
    3. Server port
    4. Default tenant
    """

    def __init__(self, app, tenant_slug: Optional[str] = None):
        """
        Initialize tenant middleware.

        Args:
            app: FastAPI application
            tenant_slug: If provided, force this tenant for all requests.
                        Used when running a single-tenant instance.
        """
        super().__init__(app)
        self.forced_tenant = tenant_slug

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        tenant_slug = None

        try:
            if self.forced_tenant:
                # Single-tenant mode: use forced tenant
                tenant_slug = self.forced_tenant
            else:
                # Multi-tenant mode: resolve from request
                tenant_slug = self._resolve_tenant(request)

            if not tenant_slug:
                logger.warning("Could not resolve tenant for request: %s", request.url)
                raise HTTPException(status_code=400, detail="Could not determine tenant")

            # Set tenant in context for this request
            set_current_tenant(tenant_slug)

            # Store tenant in request state for easy access
            request.state.tenant_slug = tenant_slug

            logger.debug("Request tenant resolved: %s", tenant_slug)

            response = await call_next(request)
            return response

        finally:
            # Always clear tenant context after request
            clear_current_tenant()

    def _resolve_tenant(self, request: Request) -> Optional[str]:
        """Resolve tenant from request information."""
        manager = get_tenant_manager()

        # 1. Check X-Tenant-ID header (for testing)
        tenant_header = request.headers.get("X-Tenant-ID")
        if tenant_header:
            tenant = manager.get_tenant(tenant_header)
            if tenant:
                logger.debug("Tenant resolved from header: %s", tenant_header)
                return tenant_header
            else:
                logger.warning("Unknown tenant in header: %s", tenant_header)

        # 2. Resolve from host and port
        host = request.headers.get("host", "")

        # Get server port from scope
        server = request.scope.get("server")
        port = server[1] if server and len(server) > 1 else None

        return manager.resolve_tenant_from_request(host=host, port=port)


def get_tenant_from_request(request: Request) -> str:
    """
    Get tenant slug from request state.

    Use this in route handlers to access the current tenant.

    Usage:
        @app.get("/items")
        def get_items(request: Request):
            tenant = get_tenant_from_request(request)
            ...
    """
    if not hasattr(request.state, "tenant_slug"):
        raise HTTPException(status_code=500, detail="Tenant not set in request")
    return request.state.tenant_slug
