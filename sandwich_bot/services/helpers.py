"""
Helper Functions for Sandwich Bot
=================================

This module contains shared utility functions used across multiple routes
and services in the Sandwich Bot application.

Key Functions:
--------------
- get_or_create_company: Get the company record or create default
- lookup_customer_by_phone: Find returning customer by phone number
- get_primary_item_type_name: Get name of primary configurable item type
- serialize_menu_item: Convert MenuItem ORM object to response model

Usage:
------
These helpers are imported by route handlers and other services that need
common database lookups or data transformations.

    from sandwich_bot.services.helpers import (
        get_or_create_company,
        lookup_customer_by_phone,
    )

    # In a route handler
    company = get_or_create_company(db)
    customer = lookup_customer_by_phone(db, phone_number)

Company Lookup:
---------------
get_or_create_company ensures there's always a Company record in the database.
If none exists, it creates a default one with generic names. This is used for:
- Bot persona name (for LLM context)
- Company branding in chat
- Signature item labels

Customer Lookup:
----------------
lookup_customer_by_phone normalizes phone numbers and searches order history
to identify returning customers. It handles various phone formats:
- With/without country code (+1)
- With/without dashes and parentheses
- Returns customer info and last order items for "repeat order" feature

Menu Item Serialization:
------------------------
serialize_menu_item handles the conversion of MenuItem ORM objects to
the API response format, properly parsing the extra_metadata JSON field
and merging with default_config for the generic item type system.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..models import Company, ItemType, MenuItem, Order
from ..schemas.menu import MenuItemOut


logger = logging.getLogger(__name__)


def get_or_create_company(db: Session) -> Company:
    """
    Get the company record or create a default one if none exists.

    This ensures there's always a Company record available for:
    - Bot persona name (used in LLM prompts)
    - Company branding in customer-facing UI
    - Signature item label customization

    Args:
        db: Database session

    Returns:
        The existing or newly created Company record
    """
    company = db.query(Company).first()
    if not company:
        company = Company(
            name="OrderBot Restaurant",
            bot_persona_name="OrderBot",
        )
        db.add(company)
        db.commit()
        db.refresh(company)
    return company


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

    # Normalize phone number (remove common formatting)
    normalized_phone = phone.replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
    # Use last 10 digits for matching (handles +1 country code)
    phone_suffix = normalized_phone[-10:] if len(normalized_phone) >= 10 else normalized_phone

    # Use SQL func.replace to normalize stored phone numbers for comparison
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
    last_order_items: List[Dict[str, Any]] = []
    if recent_order.items:
        for item in recent_order.items:
            item_data = {
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
            }
            # Add item_config fields if present (coffee/drink modifiers: size, style, milk, etc.)
            if item.item_config:
                item_data.update(item.item_config)
            last_order_items.append(item_data)

    return {
        "name": recent_order.customer_name,
        "phone": recent_order.phone,
        "email": recent_order.customer_email,
        "order_count": order_count,
        "last_order_items": last_order_items,
        "last_order_date": recent_order.created_at.isoformat() if recent_order.created_at else None,
        "last_order_type": recent_order.order_type,  # "pickup" or "delivery"
        "last_order_address": recent_order.delivery_address,  # For repeat delivery orders
    }


def get_primary_item_type_name(db: Session) -> str:
    """
    Get the display name of the primary configurable item type.

    This is used for dynamic greeting messages (e.g., "Would you like
    a signature sandwich?" vs "Would you like a signature pizza?").

    Args:
        db: Database session

    Returns:
        Display name of the first configurable item type, or "Sandwich" as default
    """
    primary = db.query(ItemType).filter(ItemType.is_configurable == True).first()
    return primary.display_name if primary else "Sandwich"


def serialize_menu_item(item: MenuItem) -> MenuItemOut:
    """
    Convert a MenuItem ORM instance into MenuItemOut response model.

    Handles the metadata field which can be stored as JSON string or dict,
    and merges data from both extra_metadata (legacy) and default_config
    (new generic item type system).

    Args:
        item: MenuItem ORM instance

    Returns:
        MenuItemOut Pydantic model ready for API response
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
        item_type_id=item.item_type_id,
    )
