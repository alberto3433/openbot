"""
Admin Menu Routes for Sandwich Bot
===================================

This module contains admin endpoints for managing menu items. Menu items are
the products customers can order (sandwiches, drinks, sides, etc.).

Endpoints:
----------
- GET /admin/menu: List all menu items
- POST /admin/menu: Create a new menu item
- GET /admin/menu/{id}: Get a specific menu item
- PUT /admin/menu/{id}: Update a menu item
- DELETE /admin/menu/{id}: Delete a menu item

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.
See auth.py for credential verification.

Menu Item Structure:
--------------------
Menu items have:
- name: Display name (e.g., "Turkey Club")
- category: Grouping (sandwiches, drinks, sides)
- is_signature: Pre-configured items on the speed menu
- base_price: Starting price before modifiers
- metadata: Additional data (description, defaults, allergens)
- item_type_id: Links to ItemType for configuration options

Metadata Field:
---------------
The metadata field stores JSON data including:
- description: Item description for display
- default_config: Default selections for signature items
- allergens: List of allergen warnings
- calories: Nutritional information

Usage:
------
    # Create a signature sandwich
    POST /admin/menu
    {
        "name": "The Italian",
        "category": "sandwiches",
        "is_signature": true,
        "base_price": 12.99,
        "metadata": {
            "description": "Salami, capicola, and provolone",
            "default_config": {"bread": "italian", "toasted": true}
        }
    }
"""

import json
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..auth import verify_admin_credentials
from ..db import get_db
from ..models import (
    MenuItem,
    MenuItemAlias,
    MenuItemCategory,
    MenuItemSizePrice,
    MenuItemSize,
    MenuItemSizeCategory,
    Category,
)
from ..schemas.menu import MenuItemOut, MenuItemCreate, MenuItemUpdate, SizePriceOut
from ..services.helpers import validate_aliases
from ..menu_data_cache import menu_cache


logger = logging.getLogger(__name__)

# Router definition
admin_menu_router = APIRouter(prefix="/admin/menu", tags=["Admin - Menu"])


# =============================================================================
# Helper Functions
# =============================================================================

from typing import Optional


def _set_menu_item_aliases(db: Session, item: MenuItem, aliases_str: Optional[str]) -> None:
    """
    Set menu item aliases from a comma-separated string.
    Clears existing aliases and creates new ones from the input string.
    Validates global uniqueness of aliases before adding.

    Raises:
        HTTPException: If any alias conflicts with an existing alias
    """
    # Clear existing aliases
    for alias in list(item.alias_records):
        db.delete(alias)

    # Flush deletes before inserting new records to avoid unique constraint violations
    db.flush()

    # Validate and add new aliases if provided
    if aliases_str:
        try:
            validated_aliases = validate_aliases(db, aliases_str, exclude_table="menu_item_aliases")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        for alias in validated_aliases:
            db.add(MenuItemAlias(menu_item=item, alias=alias))


def _set_menu_item_categories(db: Session, item: MenuItem, category_ids: Optional[List[int]]) -> None:
    """
    Set menu item categories from a list of category IDs.
    Clears existing category assignments and creates new ones.

    Args:
        db: Database session
        item: The menu item to update
        category_ids: List of category IDs to assign (None means don't change)

    Raises:
        HTTPException: If any category ID is invalid
    """
    if category_ids is None:
        return

    # Clear existing category assignments
    for cr in list(item.category_records):
        db.delete(cr)

    # Flush deletes before inserting new records to avoid unique constraint violations
    db.flush()

    # Add new category assignments
    for cat_id in category_ids:
        # Verify category exists
        category = db.query(Category).filter(Category.id == cat_id).first()
        if not category:
            raise HTTPException(
                status_code=400,
                detail=f"Category with ID {cat_id} not found"
            )
        db.add(MenuItemCategory(menu_item_id=item.id, category_id=cat_id))


def _set_menu_item_size_prices(
    db: Session,
    item: MenuItem,
    size_category_id: Optional[int],
    size_prices: Optional[List],
) -> None:
    """
    Set menu item size pricing.
    Updates size_category_id and size_price entries.

    Args:
        db: Database session
        item: The menu item to update
        size_category_id: Size category ID (or None to clear)
        size_prices: List of {size_id, price} dicts (or None to skip)
    """
    # Update size_category_id if provided
    if size_category_id is not None:
        if size_category_id == 0:
            # Special case: 0 means clear the size category
            item.size_category_id = None
        else:
            # Verify category exists
            category = db.query(MenuItemSizeCategory).filter(
                MenuItemSizeCategory.id == size_category_id
            ).first()
            if not category:
                raise HTTPException(
                    status_code=400,
                    detail=f"Size category with ID {size_category_id} not found"
                )
            item.size_category_id = size_category_id

    # Update size prices if provided
    if size_prices is not None:
        # Clear existing size prices
        db.query(MenuItemSizePrice).filter(
            MenuItemSizePrice.menu_item_id == item.id
        ).delete()
        db.flush()

        # Add new size prices
        for sp in size_prices:
            size_id = sp.size_id if hasattr(sp, 'size_id') else sp.get('size_id')
            price = sp.price if hasattr(sp, 'price') else sp.get('price')

            # Verify size exists
            size = db.query(MenuItemSize).filter(MenuItemSize.id == size_id).first()
            if not size:
                raise HTTPException(
                    status_code=400,
                    detail=f"Size with ID {size_id} not found"
                )

            db.add(MenuItemSizePrice(
                menu_item_id=item.id,
                size_id=size_id,
                price=price,
            ))


def serialize_menu_item(item: MenuItem, db: Session) -> MenuItemOut:
    """Convert MenuItem model to response schema."""
    try:
        meta = json.loads(item.extra_metadata) if item.extra_metadata else {}
    except (json.JSONDecodeError, TypeError):
        meta = {}

    # Get category IDs from the category_records relationship
    category_ids = [cr.category_id for cr in item.category_records] if item.category_records else []

    # Get size prices
    size_prices = []
    if item.size_prices:
        for sp in item.size_prices:
            size_prices.append(SizePriceOut(
                size_id=sp.size_id,
                size_name=sp.size.name if sp.size else "Unknown",
                price=float(sp.price),
            ))

    return MenuItemOut(
        id=item.id,
        name=item.name,
        description=item.description,
        category=item.category,
        is_signature=item.is_signature,
        base_price=float(item.base_price),
        available_qty=item.available_qty,
        metadata=meta,
        item_type_id=item.item_type_id,
        aliases=item.aliases,
        abbreviation=item.abbreviation,
        required_match_phrases=item.required_match_phrases,
        category_ids=category_ids,
        size_category_id=item.size_category_id,
        size_prices=size_prices,
    )


# =============================================================================
# Menu Endpoints
# =============================================================================

@admin_menu_router.get("", response_model=List[MenuItemOut])
def admin_menu(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> List[MenuItemOut]:
    """List all menu items. Requires admin authentication."""
    items = (
        db.query(MenuItem)
        .options(
            joinedload(MenuItem.alias_records),
            joinedload(MenuItem.category_records),
            joinedload(MenuItem.size_prices).joinedload(MenuItemSizePrice.size),
        )
        .order_by(MenuItem.id.asc())
        .all()
    )
    return [serialize_menu_item(m, db) for m in items]


@admin_menu_router.post("", response_model=MenuItemOut)
def create_menu_item(
    payload: MenuItemCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> MenuItemOut:
    """Create a new menu item. Requires admin authentication."""
    item = MenuItem(
        name=payload.name,
        description=payload.description,
        category=payload.category,
        is_signature=payload.is_signature,
        base_price=payload.base_price,
        available_qty=payload.available_qty,
        extra_metadata=json.dumps(payload.metadata or {}),
        item_type_id=payload.item_type_id,
        abbreviation=payload.abbreviation,
        required_match_phrases=payload.required_match_phrases,
        size_category_id=payload.size_category_id,
    )
    db.add(item)
    db.flush()  # Get the item ID before adding child records

    # Add aliases through child table
    _set_menu_item_aliases(db, item, payload.aliases)

    # Add category assignments
    _set_menu_item_categories(db, item, payload.category_ids)

    # Add size prices
    _set_menu_item_size_prices(db, item, None, payload.size_prices)

    db.commit()
    db.refresh(item)
    logger.info("Created menu item: %s (id=%d)", item.name, item.id)

    # Refresh menu cache so pricing engine uses new data
    menu_cache.load_from_db(db, fail_on_error=False, force=True)

    return serialize_menu_item(item, db)


@admin_menu_router.get("/{item_id}", response_model=MenuItemOut)
def get_menu_item(
    item_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> MenuItemOut:
    """Get a specific menu item by ID. Requires admin authentication."""
    item = (
        db.query(MenuItem)
        .options(
            joinedload(MenuItem.size_prices).joinedload(MenuItemSizePrice.size),
        )
        .filter(MenuItem.id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    return serialize_menu_item(item, db)


@admin_menu_router.put("/{item_id}", response_model=MenuItemOut)
def update_menu_item(
    item_id: int,
    payload: MenuItemUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> MenuItemOut:
    """Update a menu item. Requires admin authentication."""
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")

    if payload.name is not None:
        item.name = payload.name
    if payload.description is not None:
        item.description = payload.description
    if payload.category is not None:
        item.category = payload.category
    if payload.is_signature is not None:
        item.is_signature = payload.is_signature
    if payload.base_price is not None:
        item.base_price = payload.base_price
    if payload.available_qty is not None:
        item.available_qty = payload.available_qty
    if payload.metadata is not None:
        item.extra_metadata = json.dumps(payload.metadata)
    if payload.item_type_id is not None:
        item.item_type_id = payload.item_type_id
    if payload.aliases is not None:
        _set_menu_item_aliases(db, item, payload.aliases)
    if payload.abbreviation is not None:
        item.abbreviation = payload.abbreviation
    if payload.required_match_phrases is not None:
        item.required_match_phrases = payload.required_match_phrases
    if payload.category_ids is not None:
        _set_menu_item_categories(db, item, payload.category_ids)

    # Update size pricing
    _set_menu_item_size_prices(db, item, payload.size_category_id, payload.size_prices)

    db.commit()
    db.refresh(item)
    logger.info("Updated menu item: %s (id=%d)", item.name, item.id)

    # Refresh menu cache so pricing engine uses new data
    menu_cache.load_from_db(db, fail_on_error=False, force=True)

    return serialize_menu_item(item, db)


@admin_menu_router.delete("/{item_id}", status_code=204)
def delete_menu_item(
    item_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete a menu item. Requires admin authentication."""
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")

    logger.info("Deleting menu item: %s (id=%d)", item.name, item.id)
    db.delete(item)
    db.commit()

    # Refresh menu cache so pricing engine uses updated data
    menu_cache.load_from_db(db, fail_on_error=False, force=True)

    return None


# =============================================================================
# Cache Management Endpoints
# =============================================================================

@admin_menu_router.get("/cache/status", response_model=Dict[str, Any])
def get_cache_status(
    _admin: str = Depends(verify_admin_credentials),
) -> Dict[str, Any]:
    """
    Get menu data cache status.

    Returns information about the cache including:
    - Whether it's loaded
    - Last refresh timestamp
    - Item counts by category
    - Keyword index sizes

    Requires admin authentication.
    """
    return menu_cache.get_status()


@admin_menu_router.post("/cache/refresh", response_model=Dict[str, Any])
def refresh_cache(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> Dict[str, Any]:
    """
    Manually refresh the menu data cache.

    Reloads all menu data from the database including:
    - Spread types and varieties
    - Bagel types
    - Proteins, toppings, and cheeses
    - Coffee and soda types
    - Known menu items

    This is useful after making menu changes that should take effect
    immediately without waiting for the scheduled 3 AM refresh.

    Requires admin authentication.

    Returns:
        Cache status after refresh
    """
    logger.info("Manual cache refresh triggered by admin")
    menu_cache.load_from_db(db, fail_on_error=False, force=True)

    return {
        "message": "Cache refreshed successfully",
        "status": menu_cache.get_status(),
    }


