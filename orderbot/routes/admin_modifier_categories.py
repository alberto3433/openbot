"""
Admin Modifier Categories Routes for Orderbot
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

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import ModifierCategory, ModifierCategoryAlias
from ..schemas.modifiers import (
    ModifierCategoryOut,
    ModifierCategoryCreate,
    ModifierCategoryUpdate,
)
from ..services.helpers import validate_aliases
from .crud_factory import CRUDRouterFactory


def _set_modifier_category_aliases(
    db: Session,
    category: ModifierCategory,
    aliases_str: str | None,
) -> None:
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

    # Flush deletes before inserting new records to avoid unique constraint violations
    db.flush()

    # Validate and add new aliases if provided
    if aliases_str:
        try:
            # Exclude current category's own ID so re-saving same aliases works
            validated_aliases = validate_aliases(
                db,
                aliases_str,
                exclude_modifier_category_id=category.id,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        for alias in validated_aliases:
            db.add(ModifierCategoryAlias(modifier_category=category, alias=alias))


def _build_create_kwargs(payload: ModifierCategoryCreate, db: Session) -> dict[str, Any]:
    """Build model kwargs from create payload."""
    return {
        "slug": payload.slug,
        "display_name": payload.display_name,
        "description": payload.description,
        "prompt_suffix": payload.prompt_suffix,
        "loads_from_ingredients": payload.loads_from_ingredients,
        "ingredient_category": payload.ingredient_category,
    }


def _handle_create_pre_commit(
    item: ModifierCategory,
    payload: ModifierCategoryCreate,
    db: Session,
) -> None:
    """Add aliases after item has ID but before commit."""
    _set_modifier_category_aliases(db, item, payload.aliases)


def _handle_before_update(
    item: ModifierCategory,
    payload: ModifierCategoryUpdate,
    db: Session,
) -> None:
    """Apply update payload to item with custom alias handling."""
    if payload.slug is not None:
        item.slug = payload.slug
    if payload.display_name is not None:
        item.display_name = payload.display_name
    if payload.aliases is not None:
        _set_modifier_category_aliases(db, item, payload.aliases)
    if payload.description is not None:
        item.description = payload.description
    if payload.prompt_suffix is not None:
        item.prompt_suffix = payload.prompt_suffix
    if payload.loads_from_ingredients is not None:
        item.loads_from_ingredients = payload.loads_from_ingredients
    if payload.ingredient_category is not None:
        item.ingredient_category = payload.ingredient_category


# Create the CRUD router using the factory
_crud = CRUDRouterFactory(
    model=ModifierCategory,
    create_schema=ModifierCategoryCreate,
    update_schema=ModifierCategoryUpdate,
    response_schema=ModifierCategoryOut,
    prefix="/admin/modifier-categories",
    tags=["Admin - Modifier Categories"],
    id_param="category_id",
    not_found_message="Modifier category not found",
    unique_fields=["slug"],
    order_by=["slug"],
    on_before_create=_build_create_kwargs,
    on_create_pre_commit=_handle_create_pre_commit,
    on_before_update=_handle_before_update,
)

# Export the router
admin_modifier_categories_router = _crud.router
