"""
Admin Ingredients Routes for Orderbot
==========================================

This module contains admin endpoints for managing ingredients and the "86"
system. Ingredients are the building blocks of menu items (breads, proteins,
cheeses, toppings, sauces).

Endpoints:
----------
Ingredient Management:
- GET /admin/ingredients: List all ingredients
- POST /admin/ingredients: Create a new ingredient
- GET /admin/ingredients/{id}: Get a specific ingredient
- PUT /admin/ingredients/{id}: Update an ingredient
- DELETE /admin/ingredients/{id}: Delete an ingredient
- PATCH /admin/ingredients/{id}/availability: Toggle 86 status

86 System:
- GET /admin/ingredients/unavailable: List all 86'd ingredients

Menu Item Availability:
- GET /admin/ingredients/menu-items: List menu items with availability
- GET /admin/ingredients/menu-items/unavailable: List 86'd menu items
- PATCH /admin/ingredients/menu-items/{id}/availability: Toggle menu item 86

The "86" System:
----------------
Restaurant terminology for "out of stock". This module provides a simple
toggle system for marking items unavailable without tracking exact counts.

Store-Specific Availability:
----------------------------
For multi-location restaurants, availability can be set per-store.

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import (
    GlobalAttributeOption,
    Ingredient,
    IngredientMustMatch,
    IngredientStoreAvailability,
    IngredientSubcategory,
    IngredientUnit,
    MenuItem,
    MenuItemIngredient,
    MenuItemStoreAvailability,
)
from ..exceptions import ReferentialIntegrityError, ResourceNotFoundError, ValidationError
from ..schemas.ingredients import (
    IngredientListOut,
    IngredientOut,
    IngredientCreate,
    IngredientUpdate,
    IngredientAvailabilityUpdate,
    IngredientStoreAvailabilityOut,
    MenuItemStoreAvailabilityOut,
    MenuItemAvailabilityUpdate,
)
from ..services.alias_service import sync_entity_aliases
from ..services.helpers import batch_load_store_availability
from .crud_factory import CRUDRouterFactory
from .crud_helpers import get_or_404


logger = logging.getLogger(__name__)


# =============================================================================
# Internal Helpers
# =============================================================================

def _set_ingredient_must_match(db: Session, ingredient: Ingredient, must_match_str: str | None) -> None:
    """Set ingredient must_match from a comma-separated string."""
    for mm in list(ingredient.must_match_records):
        db.delete(mm)
    db.flush()

    if must_match_str:
        for mm in must_match_str.split(","):
            mm = mm.strip()
            if mm:
                db.add(IngredientMustMatch(ingredient=ingredient, must_match=mm))


def _sync_ingredient_to_global_options(db: Session, ingredient: Ingredient) -> int:
    """Link any GlobalAttributeOptions that match this Ingredient by name or slug."""
    matching_options = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.ingredient_id.is_(None),
        (GlobalAttributeOption.display_name == ingredient.name) |
        (GlobalAttributeOption.slug == ingredient.slug)
    ).all()

    for opt in matching_options:
        opt.ingredient_id = ingredient.id
        logger.info(
            "Auto-linked GlobalAttributeOption '%s' (id=%d) to Ingredient '%s' (id=%d)",
            opt.display_name, opt.id, ingredient.name, ingredient.id
        )
        opt.slug = None
        opt.display_name = None

    return len(matching_options)


def _resolve_subcategory(db: Session, subcategory_slug: str) -> "IngredientSubcategory":
    """Look up an IngredientSubcategory by slug."""
    subcat = db.query(IngredientSubcategory).filter(
        IngredientSubcategory.slug == subcategory_slug
    ).first()
    if not subcat:
        raise ValidationError(f"Invalid subcategory: '{subcategory_slug}'")
    return subcat


# =============================================================================
# Factory Callbacks
# =============================================================================


def _build_create_kwargs(payload: IngredientCreate, db: Session) -> dict[str, Any]:
    """Build model kwargs from create payload."""
    existing = db.query(Ingredient).filter(Ingredient.name == payload.name).first()
    if existing:
        raise ValidationError(f"Ingredient '{payload.name}' already exists")

    unit_obj = db.query(IngredientUnit).filter(IngredientUnit.name == payload.unit).first()
    if not unit_obj:
        raise ValidationError(f"Invalid unit: {payload.unit}")

    subcat = _resolve_subcategory(db, payload.subcategory)

    return {
        "name": payload.name,
        "slug": payload.name.lower().replace(" ", "_"),
        "category": subcat.category_slug,
        "subcategory_id": subcat.id,
        "unit_id": unit_obj.id,
        "track_inventory": payload.track_inventory,
        "is_available": payload.is_available,
        "abbreviation": payload.abbreviation,
    }


def _handle_create_pre_commit(item: Ingredient, payload: IngredientCreate, db: Session) -> None:
    """Add aliases, must_match, and auto-link after item has ID."""
    sync_entity_aliases(db, item, payload.aliases, "ingredient")
    _set_ingredient_must_match(db, item, payload.must_match)

    linked_count = _sync_ingredient_to_global_options(db, item)
    if linked_count > 0:
        logger.info("Auto-linked %d GlobalAttributeOptions to new ingredient", linked_count)


def _to_response(item: Ingredient, db: Session) -> IngredientOut:
    """Serialize ingredient with eager-loaded relationships."""
    ingredient = db.query(Ingredient).options(
        joinedload(Ingredient.unit_rel)
    ).filter(Ingredient.id == item.id).first()
    return IngredientOut.model_validate(ingredient)


def _handle_before_update(item: Ingredient, payload: IngredientUpdate, db: Session) -> None:
    """Apply update payload to item."""
    if payload.name is not None:
        item.name = payload.name
    if payload.unit is not None:
        unit_obj = db.query(IngredientUnit).filter(IngredientUnit.name == payload.unit).first()
        if not unit_obj:
            raise ValidationError(f"Invalid unit: {payload.unit}")
        item.unit_id = unit_obj.id
    if payload.track_inventory is not None:
        item.track_inventory = payload.track_inventory
    if payload.is_available is not None:
        item.is_available = payload.is_available
    if payload.aliases is not None:
        sync_entity_aliases(db, item, payload.aliases, "ingredient")
    if payload.must_match is not None:
        _set_ingredient_must_match(db, item, payload.must_match)
        linked_count = _sync_ingredient_to_global_options(db, item)
        if linked_count > 0:
            logger.info("Auto-linked %d GlobalAttributeOptions after must_match update", linked_count)
    if "abbreviation" in payload.model_fields_set:
        item.abbreviation = payload.abbreviation
    if "subcategory" in payload.model_fields_set and payload.subcategory is not None:
        subcat = _resolve_subcategory(db, payload.subcategory)
        item.subcategory_id = subcat.id
        item.category = subcat.category_slug


def _handle_before_delete(item: Ingredient, db: Session) -> None:
    """Check for RESTRICT-protected references before deleting."""
    dependents: list[str] = []

    menu_item_count = db.query(MenuItemIngredient).filter(
        MenuItemIngredient.ingredient_id == item.id
    ).count()
    if menu_item_count:
        dependents.append(f"{menu_item_count} menu item default(s)")

    attr_option_count = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.ingredient_id == item.id
    ).count()
    if attr_option_count:
        dependents.append(f"{attr_option_count} attribute option(s)")

    if dependents:
        raise ReferentialIntegrityError(
            f"Cannot delete ingredient '{item.name}' — "
            f"it still has: {', '.join(dependents)}. "
            f"Remove these records first."
        )


# =============================================================================
# CRUD Factory (create, get, update, delete — list is custom below)
# =============================================================================

_crud = CRUDRouterFactory(
    model=Ingredient,
    create_schema=IngredientCreate,
    update_schema=IngredientUpdate,
    response_schema=IngredientOut,
    prefix="/admin/ingredients",
    tags=["Admin - Ingredients"],
    id_param="ingredient_id",
    not_found_message="Ingredient not found",
    skip_list=True,
    to_response=_to_response,
    on_before_create=_build_create_kwargs,
    on_create_pre_commit=_handle_create_pre_commit,
    on_before_update=_handle_before_update,
    on_before_delete=_handle_before_delete,
)

# Use factory's router as the main router, add custom endpoints to it
admin_ingredients_router = _crud.router


# =============================================================================
# Custom Endpoints (not handled by factory)
# =============================================================================

@admin_ingredients_router.get("/units", response_model=list[str])
def list_ingredient_units(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> list[str]:
    """List all available ingredient units for dropdown selection."""
    units = db.query(IngredientUnit).order_by(IngredientUnit.name).all()
    return [u.name for u in units]


@admin_ingredients_router.get("/list", response_model=list[IngredientListOut])
def list_ingredients_minimal(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    store_id: str | None = Query(None, description="Store ID for availability"),
) -> list[IngredientListOut]:
    """Lightweight list for sidebar - minimal fields for fast loading."""
    ingredients = db.query(Ingredient).order_by(Ingredient.category, Ingredient.name).all()
    store_avail_map = batch_load_store_availability(db, store_id, "ingredient")

    result = []
    for ing in ingredients:
        is_available = store_avail_map.get(ing.id, ing.is_available) if store_id else ing.is_available

        result.append(IngredientListOut(
            id=ing.id,
            name=ing.name,
            category=ing.category,
            is_available=is_available,
        ))
    return result


@admin_ingredients_router.get("", response_model=list[IngredientStoreAvailabilityOut])
def list_ingredients(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    category: str | None = Query(None, description="Filter by category"),
    store_id: str | None = Query(None, description="Store ID for availability"),
) -> list[IngredientStoreAvailabilityOut]:
    """List all ingredients with store-specific availability."""
    query = db.query(Ingredient)
    if category:
        query = query.filter(Ingredient.category == category.lower())
    ingredients = query.order_by(Ingredient.category, Ingredient.name).all()
    store_avail_map = batch_load_store_availability(db, store_id, "ingredient")

    result = []
    for ing in ingredients:
        is_available = store_avail_map.get(ing.id, ing.is_available) if store_id else ing.is_available

        result.append(IngredientStoreAvailabilityOut(
            id=ing.id,
            name=ing.name,
            slug=ing.slug,
            category=ing.category,
            unit=ing.unit,
            track_inventory=ing.track_inventory,
            is_available=is_available,
            aliases=ing.aliases,
            must_match=ing.must_match,
        ))
    return result


@admin_ingredients_router.get("/unavailable", response_model=list[IngredientStoreAvailabilityOut])
def list_unavailable_ingredients(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    store_id: str | None = Query(None, description="Store ID"),
) -> list[IngredientStoreAvailabilityOut]:
    """List all 86'd ingredients for a store."""
    if store_id:
        store_unavail = db.query(IngredientStoreAvailability).filter(
            IngredientStoreAvailability.store_id == store_id,
            IngredientStoreAvailability.is_available == False
        ).all()
        ingredient_ids = [sa.ingredient_id for sa in store_unavail]
        ingredients = db.query(Ingredient).filter(
            Ingredient.id.in_(ingredient_ids)
        ).order_by(Ingredient.category, Ingredient.name).all()
    else:
        ingredients = db.query(Ingredient).filter(
            Ingredient.is_available == False
        ).order_by(Ingredient.category, Ingredient.name).all()

    return [IngredientStoreAvailabilityOut(
        id=ing.id,
        name=ing.name,
        slug=ing.slug,
        category=ing.category,
        unit=ing.unit,
        track_inventory=ing.track_inventory,
        is_available=False,
    ) for ing in ingredients]


@admin_ingredients_router.get("/menu-items", response_model=list[MenuItemStoreAvailabilityOut])
def list_menu_items_availability(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    store_id: str | None = Query(None, description="Store ID"),
) -> list[MenuItemStoreAvailabilityOut]:
    """List all menu items with store-specific availability."""
    items = db.query(MenuItem).options(joinedload(MenuItem.item_type)).order_by(MenuItem.name).all()
    store_avail_map = batch_load_store_availability(db, store_id, "menu_item")

    result = []
    for item in items:
        is_available = store_avail_map.get(item.id, True) if store_id else True
        category = item.item_type.display_name if item.item_type else None
        result.append(MenuItemStoreAvailabilityOut(
            id=item.id,
            name=item.name,
            category=category,
            base_price=float(item.base_price),
            is_available=is_available,
        ))
    return result


@admin_ingredients_router.get("/menu-items/unavailable", response_model=list[MenuItemStoreAvailabilityOut])
def list_unavailable_menu_items(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    store_id: str | None = Query(None, description="Store ID"),
) -> list[MenuItemStoreAvailabilityOut]:
    """List all 86'd menu items for a store."""
    if store_id:
        store_unavail = db.query(MenuItemStoreAvailability).filter(
            MenuItemStoreAvailability.store_id == store_id,
            MenuItemStoreAvailability.is_available == False
        ).all()
        item_ids = [sa.menu_item_id for sa in store_unavail]
        items = db.query(MenuItem).options(
            joinedload(MenuItem.item_type)
        ).filter(
            MenuItem.id.in_(item_ids)
        ).order_by(MenuItem.name).all()
    else:
        items = []

    return [MenuItemStoreAvailabilityOut(
        id=item.id,
        name=item.name,
        category=item.item_type.display_name if item.item_type else None,
        base_price=float(item.base_price),
        is_available=False,
    ) for item in items]


@admin_ingredients_router.patch("/menu-items/{item_id}/availability", response_model=MenuItemStoreAvailabilityOut)
def update_menu_item_availability(
    item_id: int,
    payload: MenuItemAvailabilityUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> MenuItemStoreAvailabilityOut:
    """Toggle menu item availability (86/un-86)."""
    item = get_or_404(db, MenuItem, item_id, detail="Menu item not found")

    if payload.store_id:
        store_avail = db.query(MenuItemStoreAvailability).filter(
            MenuItemStoreAvailability.menu_item_id == item_id,
            MenuItemStoreAvailability.store_id == payload.store_id
        ).first()

        if store_avail:
            store_avail.is_available = payload.is_available
        else:
            store_avail = MenuItemStoreAvailability(
                menu_item_id=item_id,
                store_id=payload.store_id,
                is_available=payload.is_available,
            )
            db.add(store_avail)
        is_available = payload.is_available
    else:
        is_available = True

    db.commit()
    logger.info("Updated menu item %d availability: %s (store: %s)",
                item_id, payload.is_available, payload.store_id or "global")

    category = item.item_type.display_name if item.item_type else None
    return MenuItemStoreAvailabilityOut(
        id=item.id,
        name=item.name,
        category=category,
        base_price=float(item.base_price),
        is_available=is_available,
    )


@admin_ingredients_router.get("/{ingredient_id}/references")
def get_ingredient_references(
    ingredient_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> dict:
    """Get all references to this ingredient for the References tab."""
    ingredient = get_or_404(db, Ingredient, ingredient_id)

    menu_item_refs = db.query(MenuItemIngredient).options(
        joinedload(MenuItemIngredient.menu_item)
    ).filter(MenuItemIngredient.ingredient_id == ingredient_id).all()

    menu_items = [
        {
            "id": ref.menu_item.id,
            "name": ref.menu_item.name,
            "quantity": ref.quantity,
        }
        for ref in menu_item_refs
    ]

    attr_options = db.query(GlobalAttributeOption).options(
        joinedload(GlobalAttributeOption.attribute)
    ).filter(GlobalAttributeOption.ingredient_id == ingredient_id).all()

    attribute_options = [
        {
            "id": opt.id,
            "attribute_slug": opt.attribute.slug,
            "attribute_display_name": opt.attribute.display_name,
            "display_name": opt.display_name or ingredient.name,
            "price_modifier": float(opt.price_modifier) if opt.price_modifier else 0.0,
        }
        for opt in attr_options
    ]

    return {
        "menu_items": menu_items,
        "attribute_options": attribute_options,
    }


@admin_ingredients_router.patch("/{ingredient_id}/availability", response_model=IngredientStoreAvailabilityOut)
def update_ingredient_availability(
    ingredient_id: int,
    payload: IngredientAvailabilityUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> IngredientStoreAvailabilityOut:
    """Toggle ingredient availability (86/un-86)."""
    ingredient = get_or_404(db, Ingredient, ingredient_id)

    if payload.store_id:
        store_avail = db.query(IngredientStoreAvailability).filter(
            IngredientStoreAvailability.ingredient_id == ingredient_id,
            IngredientStoreAvailability.store_id == payload.store_id
        ).first()

        if store_avail:
            store_avail.is_available = payload.is_available
        else:
            store_avail = IngredientStoreAvailability(
                ingredient_id=ingredient_id,
                store_id=payload.store_id,
                is_available=payload.is_available,
            )
            db.add(store_avail)
        is_available = payload.is_available
    else:
        ingredient.is_available = payload.is_available
        is_available = payload.is_available

    db.commit()
    logger.info("Updated ingredient %d availability: %s (store: %s)",
                ingredient_id, payload.is_available, payload.store_id or "global")

    return IngredientStoreAvailabilityOut(
        id=ingredient.id,
        name=ingredient.name,
        slug=ingredient.slug,
        category=ingredient.category,
        unit=ingredient.unit,
        track_inventory=ingredient.track_inventory,
        is_available=is_available,
    )
