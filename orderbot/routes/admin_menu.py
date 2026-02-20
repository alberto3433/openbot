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
- GET /admin/menu/cache/status: Get cache status
- POST /admin/menu/cache/refresh: Refresh cache

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends
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
from ..exceptions import ValidationError
from ..schemas.menu import MenuItemOut, MenuItemCreate, MenuItemUpdate
from ..schemas.serializers import serialize_menu_item
from ..services.alias_service import sync_entity_aliases
from ..cache import menu_cache
from .crud_factory import CRUDRouterFactory


logger = logging.getLogger(__name__)


# =============================================================================
# Internal Helpers
# =============================================================================

def _set_menu_item_size_prices(
    db: Session,
    item: MenuItem,
    size_category_id: int | None,
    size_prices: list | None,
) -> None:
    """Set menu item size pricing."""
    if size_category_id is not None:
        if size_category_id == 0:
            item.size_category_id = None
        else:
            category = db.query(MenuItemSizeCategory).filter(
                MenuItemSizeCategory.id == size_category_id
            ).first()
            if not category:
                raise ValidationError(
                    f"Size category with ID {size_category_id} not found"
                )
            item.size_category_id = size_category_id

    if size_prices is not None:
        db.query(MenuItemSizePrice).filter(
            MenuItemSizePrice.menu_item_id == item.id
        ).delete()
        db.flush()

        for sp in size_prices:
            size_id = sp.size_id if hasattr(sp, 'size_id') else sp.get('size_id')
            price = sp.price if hasattr(sp, 'price') else sp.get('price')

            size = db.query(MenuItemSize).filter(MenuItemSize.id == size_id).first()
            if not size:
                raise ValidationError(f"Size with ID {size_id} not found")

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
    """Set menu item ingredients from a list of ingredient dicts."""
    if ingredients is None:
        return

    for link in list(item.ingredient_links):
        db.delete(link)
    db.flush()

    for ing_data in ingredients:
        ingredient_id = ing_data.get("ingredient_id")
        quantity = ing_data.get("quantity", 1)

        ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
        if not ingredient:
            raise ValidationError(
                f"Ingredient with ID {ingredient_id} not found"
            )

        db.add(MenuItemIngredient(
            menu_item_id=item.id,
            ingredient_id=ingredient_id,
            quantity=quantity,
        ))


# =============================================================================
# Factory Callbacks
# =============================================================================

def _to_response(item: MenuItem, db: Session) -> MenuItemOut:
    """Serialize a MenuItem with eager-loaded relationships."""
    menu_item = (
        db.query(MenuItem)
        .options(
            joinedload(MenuItem.size_prices).joinedload(MenuItemSizePrice.size),
            joinedload(MenuItem.ingredient_links).joinedload(MenuItemIngredient.ingredient),
            joinedload(MenuItem.item_type),
            joinedload(MenuItem.alias_records),
        )
        .filter(MenuItem.id == item.id)
        .first()
    )
    return serialize_menu_item(menu_item, db)


def _build_create_kwargs(payload: MenuItemCreate, db: Session) -> dict[str, Any]:
    """Build model kwargs from create payload."""
    return {
        "name": payload.name,
        "description": payload.description,
        "is_signature": payload.is_signature,
        "available_qty": payload.available_qty,
        "item_type_id": payload.item_type_id,
        "abbreviation": payload.abbreviation,
        "required_match_phrases": payload.required_match_phrases,
        "size_category_id": payload.size_category_id,
        "is_vegan": payload.is_vegan,
        "is_vegetarian": payload.is_vegetarian,
        "is_gluten_free": payload.is_gluten_free,
        "is_dairy_free": payload.is_dairy_free,
        "is_kosher": payload.is_kosher,
        "contains_eggs": payload.contains_eggs,
        "contains_fish": payload.contains_fish,
        "contains_sesame": payload.contains_sesame,
        "contains_nuts": payload.contains_nuts,
        "unit_type": payload.unit_type or "each",
        "quantity_per_unit": payload.quantity_per_unit,
    }


def _handle_create_pre_commit(item: MenuItem, payload: MenuItemCreate, db: Session) -> None:
    """Add aliases and size prices after item has ID."""
    sync_entity_aliases(db, item, payload.aliases, "menu_item")

    # Add size prices - if no size_prices provided, create default from base_price
    size_prices_to_set = payload.size_prices
    if not size_prices_to_set and payload.base_price is not None:
        size_prices_to_set = [{"size_id": 6, "price": payload.base_price}]
        if not payload.size_category_id:
            item.size_category_id = 3  # Quantity category
    _set_menu_item_size_prices(db, item, None, size_prices_to_set)


def _handle_before_update(item: MenuItem, payload: MenuItemUpdate, db: Session) -> None:
    """Apply update payload to item."""
    if payload.name is not None:
        item.name = payload.name
    if "description" in payload.model_fields_set:
        item.description = payload.description
    if payload.is_signature is not None:
        item.is_signature = payload.is_signature
    # If base_price is provided without size_prices, update the default size price
    if payload.base_price is not None and not payload.size_prices:
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

    # Update dietary attributes
    for field in ("is_vegan", "is_vegetarian", "is_gluten_free", "is_dairy_free", "is_kosher"):
        if field in payload.model_fields_set:
            setattr(item, field, getattr(payload, field))

    # Update allergen attributes
    for field in ("contains_eggs", "contains_fish", "contains_sesame", "contains_nuts"):
        if field in payload.model_fields_set:
            setattr(item, field, getattr(payload, field))

    # Update unit of sale
    for field in ("unit_type", "quantity_per_unit"):
        if field in payload.model_fields_set:
            setattr(item, field, getattr(payload, field))


def _handle_before_delete(item: MenuItem, db: Session) -> None:
    """Delete related records before the menu item."""
    db.query(MenuItemSizePrice).filter(MenuItemSizePrice.menu_item_id == item.id).delete()
    db.query(MenuItemAlias).filter(MenuItemAlias.menu_item_id == item.id).delete()
    db.query(MenuItemIngredient).filter(MenuItemIngredient.menu_item_id == item.id).delete()


# =============================================================================
# CRUD Factory (create, get, update, delete — list is custom below)
# =============================================================================

_crud = CRUDRouterFactory(
    model=MenuItem,
    create_schema=MenuItemCreate,
    update_schema=MenuItemUpdate,
    response_schema=MenuItemOut,
    prefix="/admin/menu",
    tags=["Admin - Menu"],
    id_param="item_id",
    not_found_message="Menu item not found",
    skip_list=True,
    to_response=_to_response,
    on_before_create=_build_create_kwargs,
    on_create_pre_commit=_handle_create_pre_commit,
    on_before_update=_handle_before_update,
    on_before_delete=_handle_before_delete,
)

# Use factory's router as the main router, add custom endpoints to it
admin_menu_router = _crud.router


# =============================================================================
# Custom Endpoints (list + cache management)
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
            joinedload(MenuItem.item_type),
        )
        .order_by(MenuItem.id.asc())
        .all()
    )
    return [serialize_menu_item(m, db, include_ingredients=False) for m in items]


@admin_menu_router.get("/cache/status", response_model=dict[str, Any])
def get_cache_status(
    _admin: str = Depends(verify_admin_credentials),
) -> dict[str, Any]:
    """Get menu data cache status."""
    return menu_cache.get_status()


@admin_menu_router.post("/cache/refresh", response_model=dict[str, Any])
def refresh_cache(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> dict[str, Any]:
    """Manually refresh the menu data cache."""
    logger.info("Manual cache refresh triggered by admin")
    menu_cache.load_from_db(db, fail_on_error=False, force=True)

    return {
        "message": "Cache refreshed successfully",
        "status": menu_cache.get_status(),
    }
