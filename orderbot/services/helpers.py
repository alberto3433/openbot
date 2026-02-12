"""
Helper Functions for Orderbot
=================================

Utility functions that don't belong to a specific service domain.

Functions in this module:
- get_primary_item_type_name: Get name of primary configurable item type
- batch_load_store_availability: Batch-load store availability
"""

import logging
from typing import Dict, Iterable, Optional

from sqlalchemy.orm import Session

from ..db.models import (
    IngredientStoreAvailability,
    ItemType,
    MenuItemStoreAvailability,
)
from .item_type_helpers import has_linked_attributes



logger = logging.getLogger(__name__)


def build_order_items_summary(items: Iterable) -> str:
    """Build a human-readable summary string from order items.

    Works with both ORM objects (attribute access) and dicts.

    Args:
        items: Iterable of order items with quantity and menu_item_name.

    Returns:
        Comma-separated summary like "2 Bagels, Latte" or "No items".
    """
    parts = []
    for item in items:
        if isinstance(item, dict):
            qty = item.get("quantity", 1)
            name = item.get("menu_item_name", "item")
        else:
            qty = item.quantity
            name = item.menu_item_name
        parts.append(f"{qty} {name}s" if qty > 1 else name)
    return ", ".join(parts) if parts else "No items"


def get_primary_item_type_name(db: Session) -> str:
    """
    Get the display name of the primary configurable item type.

    This is used for dynamic greeting messages (e.g., "Would you like
    a signature sandwich?" vs "Would you like a signature pizza?").

    Configurability is derived from linked global attributes.

    Args:
        db: Database session

    Returns:
        Display name of the first configurable item type, or "Sandwich" as default
    """
    # Find the first item type with linked global attributes (configurable)
    item_types = db.query(ItemType).all()
    for it in item_types:
        if has_linked_attributes(it.id, db):
            return it.display_name
    return "Sandwich"


def batch_load_store_availability(
    db: Session,
    store_id: Optional[str],
    entity_type: str,
) -> Dict[int, bool]:
    """
    Batch-load store availability for a list of entities in a single query.

    This eliminates N+1 queries when loading store-specific availability
    for multiple entities at once.

    Args:
        db: Database session
        store_id: Store ID to check availability for (or None for global)
        entity_type: One of "ingredient" or "menu_item"

    Returns:
        Dict mapping entity ID to availability status.
        If store_id is None, returns empty dict (caller should use default).

    Example:
        >>> avail_map = batch_load_store_availability(db, "store_123", "ingredient")
        >>> is_available = avail_map.get(ing.id, ing.is_available)
    """
    if not store_id:
        return {}

    if entity_type == "ingredient":
        store_avails = db.query(IngredientStoreAvailability).filter(
            IngredientStoreAvailability.store_id == store_id
        ).all()
        return {sa.ingredient_id: sa.is_available for sa in store_avails}
    elif entity_type == "menu_item":
        store_avails = db.query(MenuItemStoreAvailability).filter(
            MenuItemStoreAvailability.store_id == store_id
        ).all()
        return {sa.menu_item_id: sa.is_available for sa in store_avails}
    else:
        raise ValueError(f"Unknown entity_type: {entity_type}. Must be 'ingredient' or 'menu_item'")
