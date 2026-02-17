"""
Admin Ingredient Subcategories Routes for Orderbot
======================================================

CRUD endpoints for managing ingredient subcategories. Subcategories group
ingredients within a category (e.g., 'bagel' under 'bread', 'cream_cheese'
under 'spread').

Endpoints:
----------
- GET /admin/ingredient-subcategories: List all (optional ?category_slug= filter)
- POST /admin/ingredient-subcategories: Create
- GET /admin/ingredient-subcategories/{id}: Get
- PUT /admin/ingredient-subcategories/{id}: Update
- DELETE /admin/ingredient-subcategories/{id}: Delete
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import Ingredient, IngredientCategory, IngredientSubcategory
from ..schemas.ingredient_subcategories import (
    IngredientSubcategoryCreate,
    IngredientSubcategoryList,
    IngredientSubcategoryOut,
    IngredientSubcategoryUpdate,
)

logger = logging.getLogger(__name__)

admin_ingredient_subcategories_router = APIRouter(
    prefix="/admin/ingredient-subcategories",
    tags=["Admin - Ingredient Subcategories"],
)


@admin_ingredient_subcategories_router.get("", response_model=IngredientSubcategoryList)
def list_subcategories(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    category_slug: Optional[str] = Query(None, description="Filter by parent category slug"),
) -> IngredientSubcategoryList:
    """List all ingredient subcategories, optionally filtered by category."""
    query = db.query(IngredientSubcategory)
    if category_slug:
        query = query.filter(IngredientSubcategory.category_slug == category_slug)
    query = query.order_by(
        IngredientSubcategory.category_slug,
        IngredientSubcategory.display_order,
        IngredientSubcategory.slug,
    )
    items = query.all()
    return IngredientSubcategoryList(
        subcategories=[IngredientSubcategoryOut.model_validate(i) for i in items],
        total=len(items),
    )


@admin_ingredient_subcategories_router.post(
    "", response_model=IngredientSubcategoryOut, status_code=201
)
def create_subcategory(
    payload: IngredientSubcategoryCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> IngredientSubcategoryOut:
    """Create a new ingredient subcategory."""
    slug = payload.slug.lower().strip()
    category_slug = payload.category_slug.lower().strip()

    # Validate parent category exists
    cat = db.query(IngredientCategory).filter(IngredientCategory.slug == category_slug).first()
    if not cat:
        raise HTTPException(status_code=400, detail=f"Category '{category_slug}' not found")

    # Check slug uniqueness
    existing = db.query(IngredientSubcategory).filter(
        IngredientSubcategory.slug == slug
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Subcategory slug '{slug}' already exists")

    item = IngredientSubcategory(
        slug=slug,
        display_name=payload.display_name.strip(),
        category_slug=category_slug,
        display_order=payload.display_order,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    logger.info("Created ingredient subcategory: %s (id=%d)", item.slug, item.id)
    return IngredientSubcategoryOut.model_validate(item)


@admin_ingredient_subcategories_router.get(
    "/{subcategory_id}", response_model=IngredientSubcategoryOut
)
def get_subcategory(
    subcategory_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> IngredientSubcategoryOut:
    """Get a specific ingredient subcategory."""
    item = db.query(IngredientSubcategory).filter(
        IngredientSubcategory.id == subcategory_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Ingredient subcategory not found")
    return IngredientSubcategoryOut.model_validate(item)


@admin_ingredient_subcategories_router.put(
    "/{subcategory_id}", response_model=IngredientSubcategoryOut
)
def update_subcategory(
    subcategory_id: int,
    payload: IngredientSubcategoryUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> IngredientSubcategoryOut:
    """Update an ingredient subcategory."""
    item = db.query(IngredientSubcategory).filter(
        IngredientSubcategory.id == subcategory_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Ingredient subcategory not found")

    if payload.slug is not None:
        new_slug = payload.slug.lower().strip()
        if new_slug != item.slug:
            existing = db.query(IngredientSubcategory).filter(
                IngredientSubcategory.slug == new_slug,
                IngredientSubcategory.id != subcategory_id,
            ).first()
            if existing:
                raise HTTPException(
                    status_code=400, detail=f"Subcategory slug '{new_slug}' already exists"
                )
            # No need to update ingredients — they reference by ID, not slug
            item.slug = new_slug

    if payload.display_name is not None:
        item.display_name = payload.display_name.strip()
    if payload.display_order is not None:
        item.display_order = payload.display_order

    db.commit()
    db.refresh(item)
    logger.info("Updated ingredient subcategory: %s (id=%d)", item.slug, item.id)
    return IngredientSubcategoryOut.model_validate(item)


@admin_ingredient_subcategories_router.delete("/{subcategory_id}", status_code=204)
def delete_subcategory(
    subcategory_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete an ingredient subcategory. Rejects if ingredients reference it."""
    item = db.query(IngredientSubcategory).filter(
        IngredientSubcategory.id == subcategory_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Ingredient subcategory not found")

    ref_count = db.query(Ingredient).filter(Ingredient.subcategory_id == item.id).count()
    if ref_count:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete subcategory '{item.slug}' — "
                   f"{ref_count} ingredient(s) still reference it. "
                   f"Reassign them first.",
        )

    logger.info("Deleting ingredient subcategory: %s (id=%d)", item.slug, item.id)
    db.delete(item)
    db.commit()
    return None
