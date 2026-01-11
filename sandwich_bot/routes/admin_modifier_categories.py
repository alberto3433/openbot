"""
Admin Modifier Categories Routes for Sandwich Bot
===================================================

This module contains admin endpoints for managing modifier categories.
Modifier categories define groups of add-ons/modifiers that customers can
ask about, like "what sweeteners do you have?" or "what toppings are available?".

Endpoints:
----------
- GET /admin/modifier-categories: List all modifier categories
- POST /admin/modifier-categories: Create a new modifier category
- GET /admin/modifier-categories/{id}: Get a specific modifier category
- PUT /admin/modifier-categories/{id}: Update a modifier category
- DELETE /admin/modifier-categories/{id}: Delete a modifier category

Category Types:
---------------
1. Static Categories:
   - Have a fixed `description` field with pre-defined options
   - Example: sweeteners, milks, syrups
   - Options are hardcoded in the description

2. Database-Backed Categories:
   - Have `loads_from_ingredients=True`
   - Options are loaded dynamically from the Ingredient table
   - Example: toppings, proteins, cheeses, spreads

Aliases:
--------
The `aliases` field contains comma-separated keywords that trigger this category.
Example: "sweetener, sweeteners, sugar, sugars" all map to the "sweeteners" category.

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.
"""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..models import ModifierCategory, ModifierCategoryAlias
from ..schemas.modifiers import (
    ModifierCategoryOut,
    ModifierCategoryCreate,
    ModifierCategoryUpdate,
)
from ..services.helpers import validate_aliases


logger = logging.getLogger(__name__)

# Router definition
admin_modifier_categories_router = APIRouter(
    prefix="/admin/modifier-categories",
    tags=["Admin - Modifier Categories"]
)


def _set_modifier_category_aliases(db: Session, category: ModifierCategory, aliases_str: str | None) -> None:
    """
    Set modifier category aliases from a comma-separated string.
    Clears existing aliases and creates new ones from the input string.
    Validates global uniqueness of aliases before adding.

    Raises:
        HTTPException: If any alias conflicts with an existing alias
    """
    # Clear existing aliases
    for alias in list(category.alias_records):
        db.delete(alias)

    # Validate and add new aliases if provided
    if aliases_str:
        try:
            validated_aliases = validate_aliases(db, aliases_str, exclude_table="modifier_category_aliases")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        for alias in validated_aliases:
            db.add(ModifierCategoryAlias(modifier_category=category, alias=alias))


# =============================================================================
# Modifier Category Endpoints
# =============================================================================

@admin_modifier_categories_router.get("", response_model=List[ModifierCategoryOut])
def list_modifier_categories(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> List[ModifierCategoryOut]:
    """List all modifier categories."""
    categories = db.query(ModifierCategory).order_by(ModifierCategory.slug).all()
    return [ModifierCategoryOut.model_validate(cat) for cat in categories]


@admin_modifier_categories_router.post("", response_model=ModifierCategoryOut, status_code=201)
def create_modifier_category(
    payload: ModifierCategoryCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ModifierCategoryOut:
    """Create a new modifier category."""
    # Check for duplicate slug
    existing = db.query(ModifierCategory).filter(
        ModifierCategory.slug == payload.slug
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Modifier category with slug '{payload.slug}' already exists"
        )

    category = ModifierCategory(
        slug=payload.slug,
        display_name=payload.display_name,
        description=payload.description,
        prompt_suffix=payload.prompt_suffix,
        loads_from_ingredients=payload.loads_from_ingredients,
        ingredient_category=payload.ingredient_category,
    )
    db.add(category)
    db.flush()  # Get the category ID before adding child records

    # Add aliases through child table
    _set_modifier_category_aliases(db, category, payload.aliases)

    db.commit()
    db.refresh(category)
    logger.info("Created modifier category: %s (id=%d)", category.slug, category.id)
    return ModifierCategoryOut.model_validate(category)


@admin_modifier_categories_router.get("/{category_id}", response_model=ModifierCategoryOut)
def get_modifier_category(
    category_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ModifierCategoryOut:
    """Get a specific modifier category by ID."""
    category = db.query(ModifierCategory).filter(
        ModifierCategory.id == category_id
    ).first()
    if not category:
        raise HTTPException(status_code=404, detail="Modifier category not found")
    return ModifierCategoryOut.model_validate(category)


@admin_modifier_categories_router.put("/{category_id}", response_model=ModifierCategoryOut)
def update_modifier_category(
    category_id: int,
    payload: ModifierCategoryUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ModifierCategoryOut:
    """Update a modifier category."""
    category = db.query(ModifierCategory).filter(
        ModifierCategory.id == category_id
    ).first()
    if not category:
        raise HTTPException(status_code=404, detail="Modifier category not found")

    # Check for slug uniqueness if updating slug
    if payload.slug is not None and payload.slug != category.slug:
        existing = db.query(ModifierCategory).filter(
            ModifierCategory.slug == payload.slug
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Modifier category with slug '{payload.slug}' already exists"
            )
        category.slug = payload.slug

    if payload.display_name is not None:
        category.display_name = payload.display_name
    if payload.aliases is not None:
        _set_modifier_category_aliases(db, category, payload.aliases)
    if payload.description is not None:
        category.description = payload.description
    if payload.prompt_suffix is not None:
        category.prompt_suffix = payload.prompt_suffix
    if payload.loads_from_ingredients is not None:
        category.loads_from_ingredients = payload.loads_from_ingredients
    if payload.ingredient_category is not None:
        category.ingredient_category = payload.ingredient_category

    db.commit()
    db.refresh(category)
    logger.info("Updated modifier category: %s (id=%d)", category.slug, category.id)
    return ModifierCategoryOut.model_validate(category)


@admin_modifier_categories_router.delete("/{category_id}", status_code=204)
def delete_modifier_category(
    category_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete a modifier category."""
    category = db.query(ModifierCategory).filter(
        ModifierCategory.id == category_id
    ).first()
    if not category:
        raise HTTPException(status_code=404, detail="Modifier category not found")

    logger.info("Deleting modifier category: %s (id=%d)", category.slug, category.id)
    db.delete(category)
    db.commit()
    return None
