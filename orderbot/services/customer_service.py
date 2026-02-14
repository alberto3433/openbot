"""
Customer Service
================

Functions for customer lookup by phone number and order history.

Functions:
- lookup_customer_by_phone: Find returning customer by phone number
- lookup_customer_order_history: Get customer's full order history
- get_order_by_id: Get a specific order by ID with phone verification
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..db.models import Order
from .helpers import build_order_items_summary


logger = logging.getLogger(__name__)


def _normalize_phone_for_lookup(phone: str) -> str:
    """Normalize phone number for database lookup.

    Strips common formatting characters and returns the last 10 digits
    to handle country code variations.

    Args:
        phone: Phone number in any format

    Returns:
        Normalized phone suffix (last 10 digits)
    """
    normalized = phone.replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
    return normalized[-10:] if len(normalized) >= 10 else normalized


def _get_normalized_phone_filter(phone_column):
    """Create a SQLAlchemy filter expression for normalized phone matching.

    Args:
        phone_column: SQLAlchemy column to normalize (e.g., Order.phone)

    Returns:
        SQLAlchemy expression with formatting characters removed
    """
    return func.replace(
        func.replace(
            func.replace(
                func.replace(phone_column, "-", ""),
                " ", ""
            ),
            "(", ""
        ),
        ")", ""
    )


def _order_item_to_dict(item) -> Dict[str, Any]:
    """Convert an OrderItem ORM object to a dict for API responses.

    Args:
        item: OrderItem ORM instance

    Returns:
        Dict with menu_item_name, quantity, price, and any item_config fields
    """
    item_data: Dict[str, Any] = {
        "menu_item_name": item.menu_item_name,
        "quantity": item.quantity,
        "price": item.unit_price,
    }
    if item.item_config:
        item_data.update(item.item_config)
    return item_data


def lookup_customer_by_phone(db: Session, phone: str) -> Optional[Dict[str, Any]]:
    """
    Look up a returning customer by phone number.

    Normalizes phone numbers to handle various formats:
    - (123) 456-7890
    - 123-456-7890
    - +1 123 456 7890
    - 1234567890

    Uses the last 10 digits for matching to handle country code variations.

    Args:
        db: Database session
        phone: Phone number to look up (any format)

    Returns:
        Dict with customer info if found:
        - name: Customer's name from last order
        - phone: Phone number
        - email: Email if provided
        - order_count: Total number of orders
        - last_order_items: Items from most recent order (for repeat order)
        - last_order_date: ISO date of last order
        - last_order_type: "pickup" or "delivery"
        - last_order_address: Delivery address if applicable

        None if no orders found for this phone number
    """
    if not phone:
        return None

    # Normalize phone and get SQL filter expression
    phone_suffix = _normalize_phone_for_lookup(phone)
    normalized_db_phone = _get_normalized_phone_filter(Order.phone)

    # Find most recent order with this phone number
    # Use joinedload to eagerly load items for repeat order functionality
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

    # Get order history count (using same normalized phone matching)
    order_count = (
        db.query(Order)
        .filter(Order.phone.isnot(None))
        .filter(normalized_db_phone.like(f"%{phone_suffix}%"))
        .count()
    )

    # Get last order items for "usual" feature
    last_order_items = [_order_item_to_dict(item) for item in recent_order.items] if recent_order.items else []

    return {
        "name": recent_order.customer_name,
        "phone": recent_order.phone,
        "email": recent_order.customer_email,
        "order_count": order_count,
        "last_order_id": recent_order.id,
        "last_order_items": last_order_items,
        "last_order_date": recent_order.created_at.isoformat() if recent_order.created_at else None,
        "last_order_type": recent_order.order_type,  # "pickup" or "delivery"
        "last_order_address": recent_order.delivery_address,  # For repeat delivery orders
    }


def lookup_customer_order_history(
    db: Session,
    phone: str,
    days: int = 90,
    limit: int = 10,
) -> Optional[Dict[str, Any]]:
    """
    Look up a customer's full order history by phone number.

    Returns customer info along with a list of recent orders (not just the last one).
    Each order includes a summary of items for display.

    Args:
        db: Database session
        phone: Phone number to look up (any format)
        days: Number of days to look back (default 90)
        limit: Maximum number of orders to return (default 10)

    Returns:
        Dict with customer info and order history if found:
        - customer: {name, phone, email}
        - order_count: Total number of orders
        - orders: List of order dicts with:
            - order_id: int
            - order_date: datetime (ISO format)
            - order_type: "pickup" | "delivery"
            - items: List of item dicts
            - total_price: float
            - summary: Short description (e.g., "2 bagels, 1 latte")

        None if no orders found for this phone number
    """
    from datetime import datetime, timedelta

    if not phone:
        return None

    phone_suffix = _normalize_phone_for_lookup(phone)
    normalized_db_phone = _get_normalized_phone_filter(Order.phone)

    # Calculate cutoff date
    cutoff_date = datetime.utcnow() - timedelta(days=days)

    # Find orders within the time window
    orders = (
        db.query(Order)
        .options(joinedload(Order.items))
        .filter(Order.phone.isnot(None))
        .filter(normalized_db_phone.like(f"%{phone_suffix}%"))
        .filter(Order.created_at >= cutoff_date)
        .order_by(Order.created_at.desc())
        .limit(limit)
        .all()
    )

    if not orders:
        return None

    # Get total order count (all time)
    total_count = (
        db.query(Order)
        .filter(Order.phone.isnot(None))
        .filter(normalized_db_phone.like(f"%{phone_suffix}%"))
        .count()
    )

    # Build customer info from most recent order
    most_recent = orders[0]
    customer_info = {
        "name": most_recent.customer_name,
        "phone": most_recent.phone,
        "email": most_recent.customer_email,
    }

    # Build order list with summaries
    order_list: List[Dict[str, Any]] = []
    for order in orders:
        items = [_order_item_to_dict(item) for item in order.items]
        summary = build_order_items_summary(order.items)

        order_list.append({
            "order_id": order.id,
            "order_date": order.created_at.isoformat() if order.created_at else None,
            "order_type": order.order_type,
            "items": items,
            "total_price": order.total_price or 0.0,
            "summary": summary,
        })

    return {
        "customer": customer_info,
        "order_count": total_count,
        "orders": order_list,
    }


def get_order_by_id(
    db: Session,
    order_id: int,
    phone: str,
) -> Optional[Dict[str, Any]]:
    """
    Get a specific order by ID, verifying phone ownership for security.

    Args:
        db: Database session
        order_id: The order ID to look up
        phone: Phone number for ownership verification

    Returns:
        Dict with order details if found and phone matches:
        - order_id: int
        - order_date: datetime (ISO format)
        - order_type: "pickup" | "delivery"
        - items: List of item dicts
        - total_price: float
        - summary: Short description

        None if order not found or phone doesn't match
    """
    if not phone:
        return None

    phone_suffix = _normalize_phone_for_lookup(phone)
    normalized_db_phone = _get_normalized_phone_filter(Order.phone)

    order = (
        db.query(Order)
        .options(joinedload(Order.items))
        .filter(Order.id == order_id)
        .filter(Order.phone.isnot(None))
        .filter(normalized_db_phone.like(f"%{phone_suffix}%"))
        .first()
    )

    if not order:
        return None

    items = [_order_item_to_dict(item) for item in order.items]
    summary = build_order_items_summary(order.items)

    return {
        "order_id": order.id,
        "order_date": order.created_at.isoformat() if order.created_at else None,
        "order_type": order.order_type,
        "items": items,
        "total_price": order.total_price or 0.0,
        "summary": summary,
    }
