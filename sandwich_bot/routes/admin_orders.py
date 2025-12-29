"""
Admin Orders Routes for Sandwich Bot
=====================================

This module contains admin endpoints for viewing and managing customer orders.
Orders represent confirmed purchases including customer information, items,
and payment details.

Endpoints:
----------
- GET /admin/orders: List orders with pagination and filtering
- GET /admin/orders/{id}: Get detailed order information

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.

Order States:
-------------
- pending: Order not yet confirmed
- pending_payment: Awaiting payment (payment link sent)
- confirmed: Order confirmed by customer
- completed: Order fulfilled
- cancelled: Order was cancelled

Filtering:
----------
Orders can be filtered by status:
- ?status=pending - Only pending orders
- ?status=confirmed - Only confirmed orders
- No status parameter - All orders

Pagination:
-----------
Uses page/page_size parameters:
- ?page=1&page_size=20 (defaults)
- Returns total count and has_next flag for navigation

Order Details:
--------------
The detail endpoint returns the full order including:
- Customer information (name, phone, email)
- All line items with configurations
- Tax breakdown (city, state, subtotal, total)
- Delivery information if applicable
- Payment status and method

Usage:
------
    # List recent confirmed orders
    GET /admin/orders?status=confirmed&page=1&page_size=20

    # Get order details
    GET /admin/orders/123
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..models import Order
from ..schemas.orders import (
    OrderSummaryOut,
    OrderDetailOut,
    OrderItemOut,
    OrderListResponse,
)


logger = logging.getLogger(__name__)

# Router definition
admin_orders_router = APIRouter(prefix="/admin/orders", tags=["Admin - Orders"])


# =============================================================================
# Order Endpoints
# =============================================================================

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
    Return a paginated list of orders.

    Requires admin authentication. Orders are sorted by creation date
    (newest first).
    """
    query = db.query(Order)

    if status in ("pending", "confirmed", "pending_payment", "completed", "cancelled"):
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
    """
    Get detailed information about a specific order.

    Requires admin authentication. Returns full order including all
    line items with their configurations.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Convert order items to response format
    items_out = [OrderItemOut.model_validate(item) for item in order.items]

    # Format created_at with UTC indicator for JavaScript
    created_at_str = ""
    if getattr(order, "created_at", None):
        created_at_str = order.created_at.isoformat() + "Z"

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
        created_at=created_at_str,
        items=items_out,
    )
