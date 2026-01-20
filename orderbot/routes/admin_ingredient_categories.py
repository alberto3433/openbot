"""
Admin Ingredient Categories Routes for Orderbot
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
"""

from typing import Any

from sqlalchemy.orm import Session

from ..models import IngredientCategory
from ..schemas.ingredient_categories import (
    IngredientCategoryCreate,
    IngredientCategoryUpdate,
    IngredientCategoryOut,
    IngredientCategoryList,
)
from .crud_factory import CRUDRouterFactory


def _build_create_kwargs(payload: IngredientCategoryCreate, db: Session) -> dict[str, Any]:
    """Build model kwargs from create payload with normalization."""
    return {
        "slug": payload.slug.lower().strip(),
        "display_name": payload.display_name.strip(),
        "modifier_type": payload.modifier_type,
        "display_order": payload.display_order,
    }


def _handle_before_update(
    item: IngredientCategory,
    payload: IngredientCategoryUpdate,
    db: Session,
) -> None:
    """Apply update payload to item with custom normalization."""
    if payload.slug is not None:
        item.slug = payload.slug.lower().strip()
    if payload.display_name is not None:
        item.display_name = payload.display_name.strip()
    if payload.modifier_type is not None:
        # Handle empty string as null
        item.modifier_type = payload.modifier_type if payload.modifier_type else None
    if payload.display_order is not None:
        item.display_order = payload.display_order


def _build_list_response(
    items: list[IngredientCategoryOut],
    total: int,
) -> IngredientCategoryList:
    """Build list response wrapper."""
    return IngredientCategoryList(categories=items, total=total)


# Create the CRUD router using the factory
_crud = CRUDRouterFactory(
    model=IngredientCategory,
    create_schema=IngredientCategoryCreate,
    update_schema=IngredientCategoryUpdate,
    response_schema=IngredientCategoryOut,
    prefix="/admin/ingredient-categories",
    tags=["Admin - Ingredient Categories"],
    id_param="category_id",
    not_found_message="Ingredient category not found",
    unique_fields=["slug"],
    order_by=["display_order", "slug"],
    on_before_create=_build_create_kwargs,
    on_before_update=_handle_before_update,
    list_response_schema=IngredientCategoryList,
    list_response_builder=_build_list_response,
)

# Export the router
admin_ingredient_categories_router = _crud.router
