"""
Admin Ingredient Categories Routes for Sandwich Bot
====================================================

This module contains admin endpoints for managing ingredient categories.
Categories classify ingredients by type (protein, topping, cheese, etc.)
and modifier type (food vs beverage).

Endpoints:
----------
- GET /admin/ingredient-categories: List all categories
- POST /admin/ingredient-categories: Create a new category
- GET /admin/ingredient-categories/{id}: Get a specific category
- PUT /admin/ingredient-categories/{id}: Update a category
- DELETE /admin/ingredient-categories/{id}: Delete a category

Modifier Types:
---------------
- **food**: Modifiers for food items (bagels, sandwiches, omelettes)
- **beverage**: Modifiers for beverages (coffee, tea)
- **None**: Not a modifier (used for item types, not customizations)

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.

Usage:
------
    # Add a new category
    POST /admin/ingredient-categories
    {
        "slug": "garnish",
        "display_name": "Garnishes",
        "modifier_type": "food",
        "display_order": 6
    }

    # Update a category
    PUT /admin/ingredient-categories/5
    {
        "modifier_type": "beverage"
    }
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..models import IngredientCategory
from ..schemas.ingredient_categories import (
    IngredientCategoryCreate,
    IngredientCategoryUpdate,
    IngredientCategoryOut,
    IngredientCategoryList,
)


logger = logging.getLogger(__name__)

# Router definition
admin_ingredient_categories_router = APIRouter(
    prefix="/admin/ingredient-categories",
    tags=["Admin - Ingredient Categories"]
)


# =============================================================================
# Ingredient Category Endpoints
# =============================================================================

@admin_ingredient_categories_router.get("", response_model=IngredientCategoryList)
def list_ingredient_categories(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> IngredientCategoryList:
    """List all ingredient categories."""
    categories = db.query(IngredientCategory).order_by(
        IngredientCategory.display_order,
        IngredientCategory.slug
    ).all()

    return IngredientCategoryList(
        categories=[IngredientCategoryOut.model_validate(c) for c in categories],
        total=len(categories)
    )


@admin_ingredient_categories_router.post("", response_model=IngredientCategoryOut, status_code=201)
def create_ingredient_category(
    payload: IngredientCategoryCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> IngredientCategoryOut:
    """Create a new ingredient category."""
    # Check for duplicate slug
    existing = db.query(IngredientCategory).filter(
        IngredientCategory.slug == payload.slug.lower().strip()
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"A category with slug '{payload.slug}' already exists"
        )

    category = IngredientCategory(
        slug=payload.slug.lower().strip(),
        display_name=payload.display_name.strip(),
        modifier_type=payload.modifier_type,
        display_order=payload.display_order,
    )
    db.add(category)
    db.commit()
    db.refresh(category)

    logger.info(
        "Created ingredient category: %s (%s)",
        category.slug,
        category.modifier_type
    )
    return IngredientCategoryOut.model_validate(category)


@admin_ingredient_categories_router.get("/{category_id}", response_model=IngredientCategoryOut)
def get_ingredient_category(
    category_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> IngredientCategoryOut:
    """Get a specific ingredient category by ID."""
    category = db.query(IngredientCategory).filter(
        IngredientCategory.id == category_id
    ).first()

    if not category:
        raise HTTPException(status_code=404, detail="Ingredient category not found")

    return IngredientCategoryOut.model_validate(category)


@admin_ingredient_categories_router.put("/{category_id}", response_model=IngredientCategoryOut)
def update_ingredient_category(
    category_id: int,
    payload: IngredientCategoryUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> IngredientCategoryOut:
    """Update an ingredient category."""
    category = db.query(IngredientCategory).filter(
        IngredientCategory.id == category_id
    ).first()

    if not category:
        raise HTTPException(status_code=404, detail="Ingredient category not found")

    # Update fields if provided
    if payload.slug is not None:
        new_slug = payload.slug.lower().strip()
        # Check for duplicate slug (excluding self)
        existing = db.query(IngredientCategory).filter(
            IngredientCategory.slug == new_slug,
            IngredientCategory.id != category_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"A category with slug '{payload.slug}' already exists"
            )
        category.slug = new_slug

    if payload.display_name is not None:
        category.display_name = payload.display_name.strip()

    if payload.modifier_type is not None:
        # Handle empty string as null
        category.modifier_type = payload.modifier_type if payload.modifier_type else None

    if payload.display_order is not None:
        category.display_order = payload.display_order

    db.commit()
    db.refresh(category)

    logger.info(
        "Updated ingredient category %d: %s (%s)",
        category.id,
        category.slug,
        category.modifier_type
    )
    return IngredientCategoryOut.model_validate(category)


@admin_ingredient_categories_router.delete("/{category_id}", status_code=204)
def delete_ingredient_category(
    category_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete an ingredient category."""
    category = db.query(IngredientCategory).filter(
        IngredientCategory.id == category_id
    ).first()

    if not category:
        raise HTTPException(status_code=404, detail="Ingredient category not found")

    slug = category.slug
    db.delete(category)
    db.commit()

    logger.info("Deleted ingredient category: %s", slug)
