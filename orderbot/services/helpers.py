"""
Helper Functions for Orderbot
=================================

Remaining utility functions that don't belong to a specific service domain.
Most functions have been moved to focused service modules:

- store_service: Store info, caching, company lookup
- customer_service: Customer lookup by phone, order history
- alias_service: Alias validation, uniqueness, syncing

Functions in this module:
- get_primary_item_type_name: Get name of primary configurable item type
- batch_load_store_availability: Batch-load store availability
"""

import logging
from typing import Dict, Optional

from sqlalchemy.orm import Session

from ..db.models import (
    IngredientStoreAvailability,
    ItemType,
    MenuItemStoreAvailability,
)
from .item_type_helpers import has_linked_attributes

# Re-exports for backward compatibility — all imports via helpers still work
from .store_service import (  # noqa: F401
    get_or_create_company,
    build_store_info,
    invalidate_store_cache,
    warmup_store_cache,
)
from .customer_service import (  # noqa: F401
    lookup_customer_by_phone,
    lookup_customer_order_history,
    get_order_by_id,
)
from .alias_service import (  # noqa: F401
    check_alias_uniqueness,
    validate_aliases,
    sync_entity_aliases,
)


logger = logging.getLogger(__name__)


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
