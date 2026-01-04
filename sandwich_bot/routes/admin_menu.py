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
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..models import MenuItem
from ..schemas.menu import MenuItemOut, MenuItemCreate, MenuItemUpdate


logger = logging.getLogger(__name__)

# Router definition
admin_menu_router = APIRouter(prefix="/admin/menu", tags=["Admin - Menu"])


# =============================================================================
# Helper Functions
# =============================================================================

def serialize_menu_item(item: MenuItem) -> MenuItemOut:
    """Convert MenuItem model to response schema."""
    try:
        meta = json.loads(item.extra_metadata) if item.extra_metadata else {}
    except (json.JSONDecodeError, TypeError):
        meta = {}

    return MenuItemOut(
        id=item.id,
        name=item.name,
        category=item.category,
        is_signature=item.is_signature,
        base_price=float(item.base_price),
        available_qty=item.available_qty,
        metadata=meta,
        item_type_id=item.item_type_id,
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
    items = db.query(MenuItem).order_by(MenuItem.id.asc()).all()
    return [serialize_menu_item(m) for m in items]


@admin_menu_router.post("", response_model=MenuItemOut)
def create_menu_item(
    payload: MenuItemCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> MenuItemOut:
    """Create a new menu item. Requires admin authentication."""
    item = MenuItem(
        name=payload.name,
        category=payload.category,
        is_signature=payload.is_signature,
        base_price=payload.base_price,
        available_qty=payload.available_qty,
        extra_metadata=json.dumps(payload.metadata or {}),
        item_type_id=payload.item_type_id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    logger.info("Created menu item: %s (id=%d)", item.name, item.id)
    return serialize_menu_item(item)


@admin_menu_router.get("/{item_id}", response_model=MenuItemOut)
def get_menu_item(
    item_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> MenuItemOut:
    """Get a specific menu item by ID. Requires admin authentication."""
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    return serialize_menu_item(item)


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

    db.commit()
    db.refresh(item)
    logger.info("Updated menu item: %s (id=%d)", item.name, item.id)
    return serialize_menu_item(item)


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
    from ..menu_data_cache import menu_cache
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
    from ..menu_data_cache import menu_cache

    logger.info("Manual cache refresh triggered by admin")
    menu_cache.load_from_db(db, fail_on_error=False)

    return {
        "message": "Cache refreshed successfully",
        "status": menu_cache.get_status(),
    }
