"""
Admin Ingredients Routes for Sandwich Bot
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

When an ingredient is 86'd:
1. Chatbot won't offer it as an option
2. Admin dashboard highlights it for restocking
3. Orders with that item show warnings

Store-Specific Availability:
----------------------------
For multi-location restaurants, availability can be set per-store.
If store_id is provided, it affects only that location.
If omitted, it affects global availability.

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.

Usage:
------
    # 86 Swiss cheese at all stores
    PATCH /admin/ingredients/5/availability
    {"is_available": false}

    # 86 Swiss cheese at one store only
    PATCH /admin/ingredients/5/availability
    {"is_available": false, "store_id": "store_eb_001"}

    # List what's 86'd at a specific store
    GET /admin/ingredients/unavailable?store_id=store_eb_001
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..models import (
    Ingredient,
    IngredientStoreAvailability,
    MenuItem,
    MenuItemStoreAvailability,
)
from ..schemas.ingredients import (
    IngredientOut,
    IngredientCreate,
    IngredientUpdate,
    IngredientAvailabilityUpdate,
    IngredientStoreAvailabilityOut,
    MenuItemStoreAvailabilityOut,
    MenuItemAvailabilityUpdate,
)


logger = logging.getLogger(__name__)

# Router definition
admin_ingredients_router = APIRouter(
    prefix="/admin/ingredients",
    tags=["Admin - Ingredients"]
)


# =============================================================================
# Ingredient Endpoints
# =============================================================================

@admin_ingredients_router.get("", response_model=List[IngredientStoreAvailabilityOut])
def list_ingredients(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    category: Optional[str] = Query(None, description="Filter by category"),
    store_id: Optional[str] = Query(None, description="Store ID for availability"),
) -> List[IngredientStoreAvailabilityOut]:
    """List all ingredients with store-specific availability."""
    query = db.query(Ingredient)
    if category:
        query = query.filter(Ingredient.category == category.lower())
    ingredients = query.order_by(Ingredient.category, Ingredient.name).all()

    result = []
    for ing in ingredients:
        is_available = ing.is_available
        if store_id:
            store_avail = db.query(IngredientStoreAvailability).filter(
                IngredientStoreAvailability.ingredient_id == ing.id,
                IngredientStoreAvailability.store_id == store_id
            ).first()
            if store_avail:
                is_available = store_avail.is_available

        result.append(IngredientStoreAvailabilityOut(
            id=ing.id,
            name=ing.name,
            category=ing.category,
            unit=ing.unit,
            track_inventory=ing.track_inventory,
            is_available=is_available,
        ))
    return result


@admin_ingredients_router.post("", response_model=IngredientOut, status_code=201)
def create_ingredient(
    payload: IngredientCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> IngredientOut:
    """Create a new ingredient."""
    existing = db.query(Ingredient).filter(Ingredient.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Ingredient '{payload.name}' already exists")

    ingredient = Ingredient(
        name=payload.name,
        category=payload.category.lower(),
        unit=payload.unit,
        track_inventory=payload.track_inventory,
        is_available=payload.is_available,
    )
    db.add(ingredient)
    db.commit()
    db.refresh(ingredient)
    logger.info("Created ingredient: %s (id=%d)", ingredient.name, ingredient.id)
    return IngredientOut.model_validate(ingredient)


@admin_ingredients_router.get("/unavailable", response_model=List[IngredientStoreAvailabilityOut])
def list_unavailable_ingredients(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    store_id: Optional[str] = Query(None, description="Store ID"),
) -> List[IngredientStoreAvailabilityOut]:
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
        category=ing.category,
        unit=ing.unit,
        track_inventory=ing.track_inventory,
        is_available=False,
    ) for ing in ingredients]


@admin_ingredients_router.get("/menu-items", response_model=List[MenuItemStoreAvailabilityOut])
def list_menu_items_availability(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    store_id: Optional[str] = Query(None, description="Store ID"),
) -> List[MenuItemStoreAvailabilityOut]:
    """List all menu items with store-specific availability."""
    items = db.query(MenuItem).order_by(MenuItem.category, MenuItem.name).all()

    result = []
    for item in items:
        is_available = True
        if store_id:
            store_avail = db.query(MenuItemStoreAvailability).filter(
                MenuItemStoreAvailability.menu_item_id == item.id,
                MenuItemStoreAvailability.store_id == store_id
            ).first()
            if store_avail:
                is_available = store_avail.is_available

        result.append(MenuItemStoreAvailabilityOut(
            id=item.id,
            name=item.name,
            category=item.category,
            base_price=float(item.base_price),
            is_available=is_available,
        ))
    return result


@admin_ingredients_router.get("/menu-items/unavailable", response_model=List[MenuItemStoreAvailabilityOut])
def list_unavailable_menu_items(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    store_id: Optional[str] = Query(None, description="Store ID"),
) -> List[MenuItemStoreAvailabilityOut]:
    """List all 86'd menu items for a store."""
    if store_id:
        store_unavail = db.query(MenuItemStoreAvailability).filter(
            MenuItemStoreAvailability.store_id == store_id,
            MenuItemStoreAvailability.is_available == False
        ).all()
        item_ids = [sa.menu_item_id for sa in store_unavail]
        items = db.query(MenuItem).filter(
            MenuItem.id.in_(item_ids)
        ).order_by(MenuItem.category, MenuItem.name).all()
    else:
        items = []

    return [MenuItemStoreAvailabilityOut(
        id=item.id,
        name=item.name,
        category=item.category,
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
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")

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

    return MenuItemStoreAvailabilityOut(
        id=item.id,
        name=item.name,
        category=item.category,
        base_price=float(item.base_price),
        is_available=is_available,
    )


@admin_ingredients_router.get("/{ingredient_id}", response_model=IngredientOut)
def get_ingredient(
    ingredient_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> IngredientOut:
    """Get a specific ingredient by ID."""
    ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")
    return IngredientOut.model_validate(ingredient)


@admin_ingredients_router.put("/{ingredient_id}", response_model=IngredientOut)
def update_ingredient(
    ingredient_id: int,
    payload: IngredientUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> IngredientOut:
    """Update an ingredient."""
    ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")

    if payload.name is not None:
        ingredient.name = payload.name
    if payload.category is not None:
        ingredient.category = payload.category.lower()
    if payload.unit is not None:
        ingredient.unit = payload.unit
    if payload.track_inventory is not None:
        ingredient.track_inventory = payload.track_inventory
    if payload.is_available is not None:
        ingredient.is_available = payload.is_available

    db.commit()
    db.refresh(ingredient)
    logger.info("Updated ingredient: %s (id=%d)", ingredient.name, ingredient.id)
    return IngredientOut.model_validate(ingredient)


@admin_ingredients_router.patch("/{ingredient_id}/availability", response_model=IngredientStoreAvailabilityOut)
def update_ingredient_availability(
    ingredient_id: int,
    payload: IngredientAvailabilityUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> IngredientStoreAvailabilityOut:
    """Toggle ingredient availability (86/un-86)."""
    ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")

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
        category=ingredient.category,
        unit=ingredient.unit,
        track_inventory=ingredient.track_inventory,
        is_available=is_available,
    )


@admin_ingredients_router.delete("/{ingredient_id}", status_code=204)
def delete_ingredient(
    ingredient_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete an ingredient."""
    ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")

    db.query(IngredientStoreAvailability).filter(
        IngredientStoreAvailability.ingredient_id == ingredient_id
    ).delete()

    logger.info("Deleting ingredient: %s (id=%d)", ingredient.name, ingredient.id)
    db.delete(ingredient)
    db.commit()
    return None
