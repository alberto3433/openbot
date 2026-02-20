"""
Admin Menu Routes for Orderbot
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
- is_signature: Pre-configured items on the speed menu
- base_price: Starting price before modifiers
- item_type_id: Links to ItemType for configuration options
- ingredients: Default ingredients via menu_item_ingredients junction table

Note: Categories are now derived from item_type -> display_group -> overall_category

Usage:
------
    # Create a signature sandwich
    POST /admin/menu
    {
        "name": "The Italian",
        "item_type_id": 3,
        "is_signature": true,
        "base_price": 12.99,
        "ingredients": [
            {"ingredient_id": 1, "quantity": 1},
            {"ingredient_id": 2, "quantity": 1}
        ]
    }
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import (
    MenuItem,
    MenuItemAlias,
    MenuItemIngredient,
    MenuItemSizePrice,
    MenuItemSize,
    MenuItemSizeCategory,
    Ingredient,
)
from ..schemas.menu import (
    MenuItemOut,
    MenuItemCreate,
    MenuItemUpdate,
    SizePriceOut,
    MenuItemIngredientOut,
)
from ..schemas.serializers import serialize_menu_item
from ..services.alias_service import sync_entity_aliases
from ..cache import menu_cache
from .crud_helpers import get_or_404


logger = logging.getLogger(__name__)

# Router definition
admin_menu_router = APIRouter(prefix="/admin/menu", tags=["Admin - Menu"])


# =============================================================================
# Helper Functions
# =============================================================================

def _set_menu_item_size_prices(
    db: Session,
    item: MenuItem,
    size_category_id: int | None,
    size_prices: list | None,
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


def _set_menu_item_ingredients(
    db: Session,
    item: MenuItem,
    ingredients: list[dict] | None,
) -> None:
    """
    Set menu item ingredients from a list of ingredient dicts.
    Clears existing ingredients and creates new ones from the input list.

    Args:
        db: Database session
        item: The menu item to update
        ingredients: List of {"ingredient_id": int, "quantity": int} dicts (None means don't change)

    Raises:
        HTTPException: If any ingredient ID is invalid
    """
    if ingredients is None:
        return

    # Clear existing ingredient links
    for link in list(item.ingredient_links):
        db.delete(link)
    db.flush()

    # Add new ingredient links
    for ing_data in ingredients:
        ingredient_id = ing_data.get("ingredient_id")
        quantity = ing_data.get("quantity", 1)

        # Verify ingredient exists
        ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
        if not ingredient:
            raise HTTPException(
                status_code=400,
                detail=f"Ingredient with ID {ingredient_id} not found"
            )

        db.add(MenuItemIngredient(
            menu_item_id=item.id,
            ingredient_id=ingredient_id,
            quantity=quantity,
        ))


# =============================================================================
# Menu Endpoints
# =============================================================================

@admin_menu_router.get("", response_model=list[MenuItemOut])
def admin_menu(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> list[MenuItemOut]:
    """List all menu items. Requires admin authentication."""
    items = (
        db.query(MenuItem)
        .options(
            joinedload(MenuItem.alias_records),
            joinedload(MenuItem.size_prices).joinedload(MenuItemSizePrice.size),
            joinedload(MenuItem.item_type),  # For category display name
        )
        .order_by(MenuItem.id.asc())
        .all()
    )
    # Skip ingredients in list to avoid N+1 queries - fetch on single item GET
    return [serialize_menu_item(m, db, include_ingredients=False) for m in items]


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
        is_signature=payload.is_signature,
        available_qty=payload.available_qty,
        item_type_id=payload.item_type_id,
        abbreviation=payload.abbreviation,
        required_match_phrases=payload.required_match_phrases,
        size_category_id=payload.size_category_id,
        # Dietary attributes (fallback when no ingredients defined)
        is_vegan=payload.is_vegan,
        is_vegetarian=payload.is_vegetarian,
        is_gluten_free=payload.is_gluten_free,
        is_dairy_free=payload.is_dairy_free,
        is_kosher=payload.is_kosher,
        # Allergen attributes
        contains_eggs=payload.contains_eggs,
        contains_fish=payload.contains_fish,
        contains_sesame=payload.contains_sesame,
        contains_nuts=payload.contains_nuts,
        # Unit of sale
        unit_type=payload.unit_type or "each",
        quantity_per_unit=payload.quantity_per_unit,
    )
    db.add(item)
    db.flush()  # Get the item ID before adding child records

    # Add aliases through child table
    sync_entity_aliases(db, item, payload.aliases, "menu_item")

    # Add size prices - if no size_prices provided, create default from base_price
    size_prices_to_set = payload.size_prices
    if not size_prices_to_set and payload.base_price is not None:
        # Create a default "each" size price from the base_price
        # size_id=6 is the "each" size in the Quantity category
        size_prices_to_set = [{"size_id": 6, "price": payload.base_price}]
        if not payload.size_category_id:
            item.size_category_id = 3  # Quantity category
    _set_menu_item_size_prices(db, item, None, size_prices_to_set)

    db.commit()
    db.refresh(item)
    logger.info("Created menu item: %s (id=%d)", item.name, item.id)

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
            joinedload(MenuItem.ingredient_links).joinedload(MenuItemIngredient.ingredient),
            joinedload(MenuItem.item_type),
            joinedload(MenuItem.alias_records),
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
    item = get_or_404(db, MenuItem, item_id, detail="Menu item not found")

    if payload.name is not None:
        item.name = payload.name
    if "description" in payload.model_fields_set:
        item.description = payload.description
    if payload.is_signature is not None:
        item.is_signature = payload.is_signature
    # Note: base_price is now computed from size_prices, not stored directly
    # If base_price is provided without size_prices, create/update the default size price
    if payload.base_price is not None and not payload.size_prices:
        from orderbot.db.models import MenuItemSizePrice
        # Find existing "each" price or create one
        each_price = next((sp for sp in item.size_prices if sp.size_id == 6), None)
        if each_price:
            each_price.price = payload.base_price
        else:
            db.add(MenuItemSizePrice(menu_item_id=item.id, size_id=6, price=payload.base_price))
            if not item.size_category_id:
                item.size_category_id = 3  # Quantity category
    if payload.available_qty is not None:
        item.available_qty = payload.available_qty
    if payload.item_type_id is not None:
        item.item_type_id = payload.item_type_id
    if payload.aliases is not None:
        sync_entity_aliases(db, item, payload.aliases, "menu_item")
    if "abbreviation" in payload.model_fields_set:
        item.abbreviation = payload.abbreviation
    if "required_match_phrases" in payload.model_fields_set:
        item.required_match_phrases = payload.required_match_phrases

    # Update size pricing
    _set_menu_item_size_prices(db, item, payload.size_category_id, payload.size_prices)

    # Update ingredients
    if payload.ingredients is not None:
        _set_menu_item_ingredients(db, item, [ing.model_dump() for ing in payload.ingredients])

    # Update dietary attributes (fallback values when no ingredients defined)
    if "is_vegan" in payload.model_fields_set:
        item.is_vegan = payload.is_vegan
    if "is_vegetarian" in payload.model_fields_set:
        item.is_vegetarian = payload.is_vegetarian
    if "is_gluten_free" in payload.model_fields_set:
        item.is_gluten_free = payload.is_gluten_free
    if "is_dairy_free" in payload.model_fields_set:
        item.is_dairy_free = payload.is_dairy_free
    if "is_kosher" in payload.model_fields_set:
        item.is_kosher = payload.is_kosher

    # Update allergen attributes
    if "contains_eggs" in payload.model_fields_set:
        item.contains_eggs = payload.contains_eggs
    if "contains_fish" in payload.model_fields_set:
        item.contains_fish = payload.contains_fish
    if "contains_sesame" in payload.model_fields_set:
        item.contains_sesame = payload.contains_sesame
    if "contains_nuts" in payload.model_fields_set:
        item.contains_nuts = payload.contains_nuts

    # Update unit of sale
    if "unit_type" in payload.model_fields_set:
        item.unit_type = payload.unit_type
    if "quantity_per_unit" in payload.model_fields_set:
        item.quantity_per_unit = payload.quantity_per_unit

    db.commit()
    db.refresh(item)
    logger.info("Updated menu item: %s (id=%d)", item.name, item.id)

    return serialize_menu_item(item, db)


@admin_menu_router.delete("/{item_id}", status_code=204)
def delete_menu_item(
    item_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete a menu item and all related records. Requires admin authentication."""
    item = get_or_404(db, MenuItem, item_id, detail="Menu item not found")

    item_name = item.name
    logger.info("Deleting menu item: %s (id=%d)", item_name, item_id)

    try:
        # Delete related records first (tables with foreign keys to menu_items)
        # These must be deleted before the menu item due to FK constraints
        db.query(MenuItemSizePrice).filter(MenuItemSizePrice.menu_item_id == item_id).delete()
        db.query(MenuItemAlias).filter(MenuItemAlias.menu_item_id == item_id).delete()
        db.query(MenuItemIngredient).filter(MenuItemIngredient.menu_item_id == item_id).delete()

        # Now delete the menu item itself
        db.delete(item)
        db.commit()
        logger.info("Successfully deleted menu item: %s (id=%d)", item_name, item_id)
    except (SQLAlchemyError, ValueError, KeyError) as e:
        db.rollback()
        logger.error("Failed to delete menu item %s (id=%d): %s", item_name, item_id, str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete menu item: {str(e)}"
        )

    return None


# =============================================================================
# Cache Management Endpoints
# =============================================================================

@admin_menu_router.get("/cache/status", response_model=dict[str, Any])
def get_cache_status(
    _admin: str = Depends(verify_admin_credentials),
) -> dict[str, Any]:
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


@admin_menu_router.post("/cache/refresh", response_model=dict[str, Any])
def refresh_cache(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> dict[str, Any]:
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


