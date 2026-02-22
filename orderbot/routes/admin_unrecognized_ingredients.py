"""
Admin Unrecognized Ingredient Suggestions Routes
=================================================

Endpoints for managing unrecognized ingredient suggestions.

Endpoints:
----------
- GET /admin/unrecognized-ingredient-suggestions: List (custom filters)
- GET /admin/unrecognized-ingredient-suggestions/lookups/ingredients: Dropdown
- GET/POST/PUT/DELETE: Standard CRUD (factory)

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.
"""

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import UnrecognizedIngredientSuggestion, Ingredient
from ..exceptions import ValidationError
from ..schemas.serializers import serialize_ingredient_suggestion
from ..schemas.unrecognized_suggestions import (
    UnrecognizedIngredientSuggestionOut,
    UnrecognizedIngredientSuggestionCreate,
    UnrecognizedIngredientSuggestionUpdate,
)
from .crud_factory import CRUDRouterFactory, reorder_routes_static_first
from .crud_helpers import get_or_404
from ..cache.base import normalize_text

# Valid match types
VALID_MATCH_TYPES = {"exact", "prefix", "contains"}


# =============================================================================
# Ingredient Suggestions - Factory Hooks
# =============================================================================

def _ingredient_before_create(
    payload: UnrecognizedIngredientSuggestionCreate, db: Session
) -> dict:
    """Validate and normalize payload, return kwargs for model creation."""
    if payload.match_type not in VALID_MATCH_TYPES:
        raise ValidationError(
            f"Invalid match_type. Must be one of: {', '.join(VALID_MATCH_TYPES)}"
        )

    pattern_normalized = normalize_text(payload.input_pattern)

    existing = db.query(UnrecognizedIngredientSuggestion).filter(
        UnrecognizedIngredientSuggestion.input_pattern == pattern_normalized,
        UnrecognizedIngredientSuggestion.match_type == payload.match_type
    ).first()
    if existing:
        raise ValidationError(
            f"Pattern '{pattern_normalized}' with match_type "
            f"'{payload.match_type}' already exists"
        )

    return {
        "input_pattern": pattern_normalized,
        "match_type": payload.match_type,
        "suggested_display_name": payload.suggested_display_name,
        "modifier_category": payload.modifier_category,
        "is_active": payload.is_active,
    }


def _ingredient_create_pre_commit(
    item: UnrecognizedIngredientSuggestion,
    payload: UnrecognizedIngredientSuggestionCreate,
    db: Session,
) -> None:
    """Resolve many-to-many alternative ingredients from names after flush."""
    if payload.alternative_ingredient_names:
        alternatives = []
        for name in payload.alternative_ingredient_names:
            ingredient = get_or_404(db, Ingredient, name, id_column="name", detail=f"Ingredient '{name}' not found")
            alternatives.append(ingredient)
        item.alternative_ingredients = alternatives


def _ingredient_before_update(
    item: UnrecognizedIngredientSuggestion,
    payload: UnrecognizedIngredientSuggestionUpdate,
    db: Session,
) -> None:
    """Validate, normalize, and apply updates in place."""
    if payload.match_type is not None and payload.match_type not in VALID_MATCH_TYPES:
        raise ValidationError(
            f"Invalid match_type. Must be one of: {', '.join(VALID_MATCH_TYPES)}"
        )

    new_pattern = (
        normalize_text(payload.input_pattern)
        if payload.input_pattern else item.input_pattern
    )
    new_match_type = payload.match_type if payload.match_type else item.match_type

    if new_pattern != item.input_pattern or new_match_type != item.match_type:
        existing = db.query(UnrecognizedIngredientSuggestion).filter(
            UnrecognizedIngredientSuggestion.input_pattern == new_pattern,
            UnrecognizedIngredientSuggestion.match_type == new_match_type,
            UnrecognizedIngredientSuggestion.id != item.id
        ).first()
        if existing:
            raise ValidationError(
                f"Pattern '{new_pattern}' with match_type "
                f"'{new_match_type}' already exists"
            )

    if payload.input_pattern is not None:
        item.input_pattern = new_pattern
    if payload.match_type is not None:
        item.match_type = payload.match_type
    if payload.suggested_display_name is not None:
        item.suggested_display_name = payload.suggested_display_name
    if payload.modifier_category is not None:
        item.modifier_category = payload.modifier_category
    if payload.is_active is not None:
        item.is_active = payload.is_active

    if payload.alternative_ingredient_names is not None:
        alternatives = []
        for name in payload.alternative_ingredient_names:
            ingredient = get_or_404(db, Ingredient, name, id_column="name", detail=f"Ingredient '{name}' not found")
            alternatives.append(ingredient)
        item.alternative_ingredients = alternatives


# Factory for Ingredient Suggestions CRUD
_ingredient_crud = CRUDRouterFactory(
    model=UnrecognizedIngredientSuggestion,
    create_schema=UnrecognizedIngredientSuggestionCreate,
    update_schema=UnrecognizedIngredientSuggestionUpdate,
    response_schema=UnrecognizedIngredientSuggestionOut,
    prefix="/admin/unrecognized-ingredient-suggestions",
    tags=["Admin - Unrecognized Ingredient Suggestions"],
    id_param="suggestion_id",
    not_found_message="Ingredient suggestion not found",
    on_before_create=_ingredient_before_create,
    on_create_pre_commit=_ingredient_create_pre_commit,
    on_before_update=_ingredient_before_update,
    to_response=lambda item, db: serialize_ingredient_suggestion(item),
)

admin_unrecognized_ingredient_suggestions_router = _ingredient_crud.router
# Remove factory's default list route (doesn't support query filters)
admin_unrecognized_ingredient_suggestions_router.routes.pop(0)


# -- Custom endpoints on the same router --


@admin_unrecognized_ingredient_suggestions_router.get(
    "", response_model=list[UnrecognizedIngredientSuggestionOut]
)
def list_ingredient_suggestions(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    active_only: bool = Query(False, description="Only show active suggestions"),
    category: str | None = Query(None, description="Filter by modifier category"),
) -> list[UnrecognizedIngredientSuggestionOut]:
    """List all unrecognized ingredient suggestions."""
    query = db.query(UnrecognizedIngredientSuggestion)

    if active_only:
        query = query.filter(UnrecognizedIngredientSuggestion.is_active == True)  # noqa: E712

    if category:
        query = query.filter(UnrecognizedIngredientSuggestion.modifier_category == category)

    suggestions = query.order_by(
        UnrecognizedIngredientSuggestion.hit_count.desc(),
        UnrecognizedIngredientSuggestion.input_pattern
    ).all()

    return [serialize_ingredient_suggestion(s) for s in suggestions]


@admin_unrecognized_ingredient_suggestions_router.get(
    "/lookups/ingredients", response_model=list[dict]
)
def get_ingredients_for_dropdown(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> list[dict]:
    """Get all ingredients for dropdown selection."""
    ingredients = db.query(Ingredient).order_by(Ingredient.name).all()
    return [
        {"id": i.id, "name": i.name}
        for i in ingredients
    ]


reorder_routes_static_first(admin_unrecognized_ingredient_suggestions_router)
