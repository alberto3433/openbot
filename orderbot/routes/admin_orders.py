"""
Admin Orders Routes for Orderbot
=====================================

This module contains admin endpoints for viewing and managing customer orders.
Orders represent confirmed purchases including customer information, items,
and payment details.

Endpoints:
----------
- GET /admin/orders: List orders with pagination and filtering
- GET /admin/orders/{id}: Get detailed order information
- PATCH /admin/orders/{id}/status: Update order status with validation
- PATCH /admin/orders/{id}/estimated-time: Set estimated ready time
- PATCH /admin/orders/{id}/notes: Update staff notes
- GET /admin/orders/{id}/history: Get status transition history
- GET /admin/orders/counts: Get order counts by status

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.
"""

import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import Order, OrderStatusHistory
from ..schemas.enums import OrderStatus
from ..schemas.orders import (
    OrderSummaryOut,
    OrderDetailOut,
    OrderItemOut,
    OrderListResponse,
    OrderStatusUpdateIn,
    OrderEstimatedTimeIn,
    OrderNotesIn,
    OrderStatusHistoryOut,
)
from ..services.order import (
    transition_order_status,
    InvalidStatusTransition,
)


logger = logging.getLogger(__name__)

# Router definition
admin_orders_router = APIRouter(prefix="/admin/orders", tags=["Admin - Orders"])


def _format_dt(dt: datetime | None) -> str | None:
    """Format a datetime to ISO string with Z suffix, or None."""
    if dt is None:
        return None
    return dt.isoformat() + ("Z" if dt.tzinfo is None else "")


# =============================================================================
# Order List + Detail Endpoints
# =============================================================================

@admin_orders_router.get("/counts")
def get_order_counts(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> dict:
    """Get order counts grouped by status for the dashboard filter bar."""
    rows = (
        db.query(Order.status, func.count(Order.id))
        .group_by(Order.status)
        .all()
    )
    counts = {status: count for status, count in rows}
    counts["all"] = sum(counts.values())
    return counts


@admin_orders_router.get("", response_model=OrderListResponse)
def list_orders(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    status: str | None = Query(
        None,
        description="Filter by status: pending, confirmed, preparing, ready, completed, cancelled",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> OrderListResponse:
    """Return a paginated list of orders sorted by creation date (newest first)."""
    query = db.query(Order)

    valid_statuses = {s.value for s in OrderStatus}
    if status in valid_statuses:
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
            subtotal=o.subtotal,
            city_tax=o.city_tax,
            state_tax=o.state_tax,
            delivery_fee=o.delivery_fee,
            total_price=o.total_price,
            store_id=o.store_id,
            order_type=o.order_type,
            delivery_address=o.delivery_address,
            payment_status=o.payment_status,
            payment_method=o.payment_method,
            estimated_ready_at=_format_dt(o.estimated_ready_at),
            staff_notes=o.staff_notes,
            created_at=_format_dt(o.created_at),
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
    """Get detailed information about a specific order."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    items_out = [OrderItemOut.model_validate(item) for item in order.items]

    return OrderDetailOut(
        id=order.id,
        status=order.status,
        customer_name=order.customer_name,
        phone=order.phone,
        customer_email=order.customer_email,
        pickup_time=order.pickup_time,
        subtotal=order.subtotal,
        city_tax=order.city_tax,
        state_tax=order.state_tax,
        delivery_fee=order.delivery_fee,
        total_price=order.total_price,
        store_id=order.store_id,
        order_type=order.order_type,
        delivery_address=order.delivery_address,
        payment_status=order.payment_status,
        payment_method=order.payment_method,
        estimated_ready_at=_format_dt(order.estimated_ready_at),
        ready_at=_format_dt(order.ready_at),
        completed_at=_format_dt(order.completed_at),
        cancelled_at=_format_dt(order.cancelled_at),
        cancellation_reason=order.cancellation_reason,
        staff_notes=order.staff_notes,
        created_at=_format_dt(order.created_at) or "",
        updated_at=_format_dt(order.updated_at),
        items=items_out,
    )


# =============================================================================
# Fulfillment Endpoints
# =============================================================================

@admin_orders_router.patch("/{order_id}/status")
def update_order_status(
    order_id: int,
    body: OrderStatusUpdateIn,
    db: Session = Depends(get_db),
    admin: str = Depends(verify_admin_credentials),
) -> dict:
    """Update an order's status with validation.

    Valid transitions: confirmed->preparing->ready->completed, any->cancelled.
    """
    try:
        order = transition_order_status(
            db=db,
            order_id=order_id,
            new_status=body.status,
            changed_by=admin,
            note=body.note,
            cancellation_reason=body.cancellation_reason,
        )
        return {"status": order.status, "order_id": order.id}
    except ValueError:
        raise HTTPException(status_code=404, detail="Order not found")
    except InvalidStatusTransition as e:
        raise HTTPException(status_code=400, detail=str(e))


@admin_orders_router.patch("/{order_id}/estimated-time")
def set_estimated_time(
    order_id: int,
    body: OrderEstimatedTimeIn,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> dict:
    """Set the estimated ready time for an order (minutes from now)."""
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    order.estimated_ready_at = datetime.now(timezone.utc) + timedelta(minutes=body.estimated_minutes)
    db.commit()

    return {
        "order_id": order.id,
        "estimated_ready_at": _format_dt(order.estimated_ready_at),
    }


@admin_orders_router.patch("/{order_id}/notes")
def update_staff_notes(
    order_id: int,
    body: OrderNotesIn,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> dict:
    """Update staff notes on an order."""
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    order.staff_notes = body.staff_notes
    db.commit()

    return {"order_id": order.id, "staff_notes": order.staff_notes}


@admin_orders_router.get("/{order_id}/history", response_model=list[OrderStatusHistoryOut])
def get_order_history(
    order_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> list[OrderStatusHistoryOut]:
    """Get the status transition history for an order."""
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    entries = (
        db.query(OrderStatusHistory)
        .filter(OrderStatusHistory.order_id == order_id)
        .order_by(OrderStatusHistory.created_at.asc())
        .all()
    )

    return [
        OrderStatusHistoryOut(
            id=e.id,
            from_status=e.from_status,
            to_status=e.to_status,
            changed_by=e.changed_by,
            note=e.note,
            created_at=_format_dt(e.created_at) or "",
        )
        for e in entries
    ]
