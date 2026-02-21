"""
Square POS API Client
=========================

Handles order submission against the Square Orders API. Follows the same
graceful-degradation pattern as the Toast integration: when Square env vars
are empty, all functions return None silently.

Square uses a simpler auth model than Toast — just a Bearer token, no JWT
exchange needed.

Environment variables:
- SQUARE_ACCESS_TOKEN: Square API access token
- SQUARE_LOCATION_ID: Fallback Square location ID
- SQUARE_ENVIRONMENT: "sandbox" or "production"
- SQUARE_API_VERSION: Square API version header
"""

import logging
from typing import Any

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
    BASE_URL,
    HTTP_REQUEST_TIMEOUT,
    SQUARE_ACCESS_TOKEN,
    SQUARE_API_BASE_URL,
    SQUARE_API_VERSION,
    SQUARE_LOCATION_ID,
)
from ..schemas.enums import PaymentStatus, SquareOrderStatus

logger = logging.getLogger(__name__)


def is_square_configured() -> bool:
    """Check if Square POS credentials are provided."""
    return bool(SQUARE_ACCESS_TOKEN and SQUARE_LOCATION_ID)


from ..services.pos_utils import get_httpx as _get_httpx


def _make_request(
    method: str,
    path: str,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Make an authenticated request to the Square API.

    Args:
        method: HTTP method (GET, POST, etc.)
        path: API path (e.g. /v2/orders)
        json_body: Optional JSON body for POST/PUT
        headers: Optional extra headers

    Returns:
        Parsed JSON response, or None on failure.
    """
    httpx = _get_httpx()
    if httpx is None:
        return None

    url = f"{SQUARE_API_BASE_URL}{path}"
    request_headers = {
        "Authorization": f"Bearer {SQUARE_ACCESS_TOKEN}",
        "Square-Version": SQUARE_API_VERSION,
        "Content-Type": "application/json",
    }
    if headers:
        request_headers.update(headers)

    try:
        resp = httpx.request(
            method, url,
            headers=request_headers,
            json=json_body,
            timeout=HTTP_REQUEST_TIMEOUT,
        )
        if resp.status_code >= 400:
            # Log the response body so we can see Square's error details
            try:
                error_body = resp.json()
            except (ValueError, TypeError):
                error_body = resp.text[:500]
            logger.error(
                "Square API error (%s %s) status=%d: %s",
                method, path, resp.status_code, error_body,
            )
            return None
        return resp.json()

    except _httpx_errors as e:
        logger.error("Square API request failed (%s %s): %s", method, path, e)
        return None


def submit_order(
    db: Session,
    order_state: dict[str, Any],
) -> dict[str, Any] | None:
    """Submit an order to Square POS.

    Builds the Square order payload from our internal order state, then POSTs
    it to the Square Orders API. Updates the Order row with Square tracking info.

    Args:
        db: Database session (for store lookups and order updates)
        order_state: Internal order state dict (must have db_order_id)

    Returns:
        Square response dict on success, None on failure or when unconfigured.
    """
    if not is_square_configured():
        logger.debug("Square not configured; skipping order submission")
        return None

    db_order_id = order_state.get("db_order_id")
    if not db_order_id:
        logger.warning("Cannot submit to Square: no db_order_id in order_state")
        return None

    # Mark order as pending Square sync
    _update_square_status(db, db_order_id, SquareOrderStatus.PENDING_SYNC)

    try:
        from .order_builder import build_square_order
        payload = build_square_order(db, order_state)

        if payload is None:
            logger.warning("Square order payload build failed for order #%d", db_order_id)
            _update_square_status(db, db_order_id, SquareOrderStatus.FAILED)
            return None

        result = _make_request("POST", "/v2/orders", json_body=payload)

        if result:
            square_order_id = result.get("order", {}).get("id")
            _update_square_status(
                db, db_order_id, SquareOrderStatus.SUBMITTED,
                square_order_id=square_order_id,
            )
            logger.info(
                "Order #%d submitted to Square (id: %s)", db_order_id, square_order_id
            )
            return result
        else:
            _update_square_status(db, db_order_id, SquareOrderStatus.FAILED)
            return None

    except (ValueError, KeyError, TypeError, ConnectionError, TimeoutError) as e:
        logger.error("Failed to submit order #%d to Square: %s", db_order_id, e)
        _update_square_status(db, db_order_id, SquareOrderStatus.FAILED)
        return None


def create_payment_link(
    db: Session,
    order_state: dict[str, Any],
) -> dict[str, Any] | None:
    """Create a Square Payment Link for an order.

    Uses Square's Payment Links API to create a checkout URL. This creates
    the Square order and checkout page in one call, so when the customer
    pays, the order is automatically paid and visible in KDS.

    Args:
        db: Database session (for store lookups and order updates)
        order_state: Internal order state dict (must have db_order_id)

    Returns:
        Dict with 'url' and 'square_order_id' on success, None on failure.
    """
    if not is_square_configured():
        logger.debug("Square not configured; skipping payment link creation")
        return None

    db_order_id = order_state.get("db_order_id")
    if not db_order_id:
        logger.warning("Cannot create Square payment link: no db_order_id in order_state")
        return None

    try:
        from .order_builder import build_square_order
        payload = build_square_order(db, order_state)

        if payload is None:
            logger.warning("Square order payload build failed for payment link (order #%d)", db_order_id)
            return None

        # Build the payment link request.
        # Keep fulfillments (has customer name/email/phone) — don't use
        # pre_populated_data since Square rejects both at the same time.
        order_body = payload["order"]

        # Build redirect URL for after payment
        redirect_url = f"{BASE_URL}/static/order_confirmed.html?order_id={db_order_id}"

        link_body: dict[str, Any] = {
            "idempotency_key": f"orderbot-link-{db_order_id}",
            "order": order_body,
            "checkout_options": {
                "redirect_url": redirect_url,
            },
        }

        result = _make_request("POST", "/v2/online-checkout/payment-links", json_body=link_body)

        if result:
            payment_link = result.get("payment_link", {})
            link_url = payment_link.get("url")
            related_resources = result.get("related_resources", {})
            orders = related_resources.get("orders", [])
            square_order_id = orders[0].get("id") if orders else payment_link.get("order_id")

            # Update local order with Square tracking info
            _update_square_status(
                db, db_order_id, SquareOrderStatus.SUBMITTED,
                square_order_id=square_order_id,
            )
            _update_payment_status(db, db_order_id, PaymentStatus.PENDING_PAYMENT)

            logger.info(
                "Square payment link created for order #%d (url: %s, square_order_id: %s)",
                db_order_id, link_url, square_order_id,
            )
            return {"url": link_url, "square_order_id": square_order_id}
        else:
            logger.warning("Square payment link creation failed for order #%d", db_order_id)
            return None

    except (ValueError, KeyError, TypeError, ConnectionError, TimeoutError) as e:
        logger.error("Failed to create Square payment link for order #%d: %s", db_order_id, e)
        return None


def _update_payment_status(
    db: Session,
    order_id: int,
    status: str,
) -> None:
    """Update payment_status on the Order row. Best-effort: never raises."""
    try:
        from ..db.models import Order
        order = db.get(Order, order_id)
        if order:
            order.payment_status = status
            db.commit()
    except (SQLAlchemyError, KeyError, ValueError, AttributeError) as e:
        logger.error("Failed to update payment status for order #%d: %s", order_id, e)
        try:
            db.rollback()
        except SQLAlchemyError:
            pass


def _update_square_status(
    db: Session,
    order_id: int,
    status: str,
    square_order_id: str | None = None,
) -> None:
    """Update Square-related columns on the Order row.

    Best-effort: logs errors but never raises.
    """
    try:
        from ..db.models import Order
        from datetime import datetime, timezone

        order = db.get(Order, order_id)
        if not order:
            logger.warning("Order #%d not found for Square status update", order_id)
            return

        order.square_order_status = status
        if square_order_id:
            order.square_order_id = square_order_id
        if status == SquareOrderStatus.SUBMITTED:
            order.square_submitted_at = datetime.now(timezone.utc)

        db.commit()
    except (SQLAlchemyError, KeyError, ValueError, AttributeError) as e:
        logger.error("Failed to update Square status for order #%d: %s", order_id, e)
        try:
            db.rollback()
        except SQLAlchemyError:
            pass
