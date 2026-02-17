"""
Toast POS API Client
========================

Handles authentication, order submission, and configuration queries against the
Toast REST API. Follows the same graceful-degradation pattern as stripe_service.py:
when Toast env vars are empty, all functions return None silently.

Environment variables:
- TOAST_CLIENT_ID: Toast API client ID
- TOAST_CLIENT_SECRET: Toast API client secret
- TOAST_RESTAURANT_GUID: Toast restaurant GUID
- TOAST_API_BASE_URL: API base (default: Toast sandbox)
"""

import logging
import time
from typing import Any, Dict, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

try:
    from httpx import HTTPError as HttpxHTTPError
except ImportError:
    HttpxHTTPError = None

# Build exception tuple for httpx operations (HTTPError may not be available)
_httpx_errors: tuple[type[Exception], ...] = (ConnectionError, TimeoutError, ValueError, OSError)
if HttpxHTTPError is not None:
    _httpx_errors = (HttpxHTTPError,) + _httpx_errors

from ..config import (
    HTTP_REQUEST_TIMEOUT,
    TOAST_API_BASE_URL,
    TOAST_CLIENT_ID,
    TOAST_CLIENT_SECRET,
    TOAST_RESTAURANT_GUID,
    TOAST_TOKEN_BUFFER_SECONDS,
)
from ..schemas.enums import ToastOrderStatus

logger = logging.getLogger(__name__)

# Cached auth token and expiry (module-level singleton)
_auth_token: Optional[str] = None
_token_expires_at: float = 0.0

# Token lifetime: refresh before actual expiry
_TOKEN_BUFFER_SECONDS = TOAST_TOKEN_BUFFER_SECONDS


def is_toast_configured() -> bool:
    """Check if Toast POS credentials are provided."""
    return bool(TOAST_CLIENT_ID and TOAST_CLIENT_SECRET and TOAST_RESTAURANT_GUID)


def _get_httpx():
    """Lazy-import httpx to avoid hard dependency at module level."""
    try:
        import httpx
        return httpx
    except ImportError:
        logger.warning("httpx package not installed; Toast POS integration disabled")
        return None


def _authenticate() -> Optional[str]:
    """Authenticate with Toast and cache the JWT.

    Returns the access token, or None on failure.
    """
    global _auth_token, _token_expires_at

    # Return cached token if still valid
    if _auth_token and time.time() < _token_expires_at:
        return _auth_token

    httpx = _get_httpx()
    if httpx is None:
        return None

    url = f"{TOAST_API_BASE_URL}/authentication/v1/authentication/login"
    payload = {
        "clientId": TOAST_CLIENT_ID,
        "clientSecret": TOAST_CLIENT_SECRET,
        "userAccessType": "TOAST_MACHINE_CLIENT",
    }

    try:
        resp = httpx.post(url, json=payload, timeout=HTTP_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        _auth_token = data.get("token") or data.get("accessToken")
        # Toast tokens typically last 24 hours; refresh 5 min early
        expires_in = data.get("expiresIn", 86400)
        _token_expires_at = time.time() + expires_in - _TOKEN_BUFFER_SECONDS

        logger.info("Toast auth token obtained (expires in %ds)", expires_in)
        return _auth_token

    except _httpx_errors as e:
        logger.error("Toast authentication failed: %s", e)
        _auth_token = None
        _token_expires_at = 0.0
        return None


def _make_request(
    method: str,
    path: str,
    json_body: Optional[Dict[str, Any]] = None,
    retry_auth: bool = True,
) -> Optional[Dict[str, Any]]:
    """Make an authenticated request to the Toast API.

    Automatically retries once on 401 (token expired).

    Args:
        method: HTTP method (GET, POST, etc.)
        path: API path (e.g. /orders/v2/orders)
        json_body: Optional JSON body for POST/PUT
        retry_auth: Whether to retry on 401

    Returns:
        Parsed JSON response, or None on failure.
    """
    httpx = _get_httpx()
    if httpx is None:
        return None

    token = _authenticate()
    if not token:
        return None

    url = f"{TOAST_API_BASE_URL}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Toast-Restaurant-External-ID": TOAST_RESTAURANT_GUID,
        "Content-Type": "application/json",
    }

    try:
        resp = httpx.request(method, url, headers=headers, json=json_body, timeout=HTTP_REQUEST_TIMEOUT)

        # Handle 401 by re-authenticating once
        if resp.status_code == 401 and retry_auth:
            global _auth_token, _token_expires_at
            _auth_token = None
            _token_expires_at = 0.0
            logger.info("Toast token expired, re-authenticating...")
            return _make_request(method, path, json_body=json_body, retry_auth=False)

        resp.raise_for_status()
        return resp.json()

    except _httpx_errors as e:
        logger.error("Toast API request failed (%s %s): %s", method, path, e)
        return None


def submit_order(
    db: Session,
    order_state: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Submit an order to Toast POS.

    Builds the Toast order payload from our internal order state, then POSTs
    it to the Toast orders API. Updates the Order row with Toast tracking info.

    Args:
        db: Database session (for GUID lookups and order updates)
        order_state: Internal order state dict (must have db_order_id)

    Returns:
        Toast response dict on success, None on failure or when unconfigured.
    """
    if not is_toast_configured():
        logger.debug("Toast not configured; skipping order submission")
        return None

    db_order_id = order_state.get("db_order_id")
    if not db_order_id:
        logger.warning("Cannot submit to Toast: no db_order_id in order_state")
        return None

    # Mark order as pending Toast sync
    _update_toast_status(db, db_order_id, ToastOrderStatus.PENDING_SYNC)

    try:
        from .order_builder import build_toast_order
        payload = build_toast_order(db, order_state)

        if payload is None:
            logger.warning("Toast order payload build failed for order #%d", db_order_id)
            _update_toast_status(db, db_order_id, ToastOrderStatus.FAILED)
            return None

        result = _make_request("POST", "/orders/v2/orders", json_body=payload)

        if result:
            toast_guid = result.get("guid")
            _update_toast_status(db, db_order_id, ToastOrderStatus.SUBMITTED, toast_guid=toast_guid)
            logger.info(
                "Order #%d submitted to Toast (guid: %s)", db_order_id, toast_guid
            )
            return result
        else:
            _update_toast_status(db, db_order_id, ToastOrderStatus.FAILED)
            return None

    except (ValueError, KeyError, TypeError, ConnectionError, TimeoutError) as e:
        logger.error("Failed to submit order #%d to Toast: %s", db_order_id, e)
        _update_toast_status(db, db_order_id, ToastOrderStatus.FAILED)
        return None


def get_dining_options() -> Optional[list]:
    """Fetch dining options (pickup, delivery, etc.) from Toast config.

    Returns:
        List of dining option dicts, or None on failure.
    """
    if not is_toast_configured():
        return None

    result = _make_request("GET", "/config/v2/diningOptions")
    return result if isinstance(result, list) else None


def get_menus() -> Optional[list]:
    """Fetch full menu configuration from Toast.

    Returns:
        List of menu dicts, or None on failure.
    """
    if not is_toast_configured():
        return None

    result = _make_request("GET", "/config/v2/menus")
    return result if isinstance(result, list) else None


def _update_toast_status(
    db: Session,
    order_id: int,
    status: str,
    toast_guid: Optional[str] = None,
) -> None:
    """Update Toast-related columns on the Order row.

    Best-effort: logs errors but never raises.
    """
    try:
        from ..db.models import Order
        from datetime import datetime, timezone

        order = db.get(Order, order_id)
        if not order:
            logger.warning("Order #%d not found for Toast status update", order_id)
            return

        order.toast_order_status = status
        if toast_guid:
            order.toast_order_guid = toast_guid
        if status == ToastOrderStatus.SUBMITTED:
            order.toast_submitted_at = datetime.now(timezone.utc)

        db.commit()
    except (SQLAlchemyError, KeyError, ValueError, AttributeError) as e:
        logger.error("Failed to update Toast status for order #%d: %s", order_id, e)
        try:
            db.rollback()
        except SQLAlchemyError:
            pass
