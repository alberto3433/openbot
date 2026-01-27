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

from ..models import IngredientCategory
from ..schemas.ingredient_categories import (
    IngredientCategoryCreate,
    IngredientCategoryUpdate,
    IngredientCategoryOut,
    IngredientCategoryList,
)
from .crud_factory import CRUDRouterFactory
from .crud_helpers import make_list_builder, build_create_kwargs, apply_payload_updates


# Field normalization rules
_NORMALIZE = {"slug": "lower_strip", "display_name": "strip"}


def _build_create_kwargs(payload, db):
    """Build model kwargs from create payload with normalization."""
    return build_create_kwargs(payload, normalize_fields=_NORMALIZE)


def _handle_before_update(item, payload, db):
    """Apply update payload to item with normalization."""
    apply_payload_updates(item, payload, db, normalize_fields=_NORMALIZE)
    # Handle empty string modifier_type as null
    if payload.modifier_type is not None and not payload.modifier_type:
        item.modifier_type = None


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
    list_response_builder=make_list_builder(IngredientCategoryList, "categories"),
)

# Export the router
admin_ingredient_categories_router = _crud.router
