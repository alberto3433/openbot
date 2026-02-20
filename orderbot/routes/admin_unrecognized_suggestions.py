"""
Admin Unrecognized Item Suggestions Routes for Orderbot
=======================================================

This module contains admin endpoints for managing unrecognized item suggestions.
These are curated responses for items users commonly request that aren't on the menu.

Endpoints:
----------
Menu Item Suggestions:
- GET /admin/unrecognized-menu-items: List all suggestions (custom filters)
- GET /admin/unrecognized-menu-items/stats: Get suggestion statistics
- GET /admin/unrecognized-menu-items/lookups/item-types: Item types dropdown
- GET /admin/unrecognized-menu-items/lookups/menu-items: Menu items dropdown
- GET /admin/unrecognized-menu-items/{id}: Get a specific suggestion (factory)
- POST /admin/unrecognized-menu-items: Create a new suggestion (factory)
- PUT /admin/unrecognized-menu-items/{id}: Update a suggestion (factory)
- DELETE /admin/unrecognized-menu-items/{id}: Delete a suggestion (factory)

Logs (Analytics):
- GET /admin/unrecognized-logs: List unrecognized item logs
- GET /admin/unrecognized-logs/stats: Get log statistics
- DELETE /admin/unrecognized-logs/clear: Clear old logs

Option Suggestions:
- GET /admin/unrecognized-option-suggestions: List (custom filters)
- GET /admin/unrecognized-option-suggestions/stats: Statistics
- GET /admin/unrecognized-option-suggestions/lookups/attributes: Attributes dropdown
- GET/POST/PUT/DELETE: Standard CRUD (factory)

Ingredient Suggestions:
- GET /admin/unrecognized-ingredient-suggestions: List (custom filters)
- GET /admin/unrecognized-ingredient-suggestions/lookups/ingredients: Dropdown
- GET/POST/PUT/DELETE: Standard CRUD (factory)

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import (
    UnrecognizedMenuItemSuggestion, UnrecognizedMenuItemLog, ItemType, MenuItem,
    UnrecognizedOptionSuggestion, GlobalAttribute,
    UnrecognizedIngredientSuggestion, Ingredient,
)
from ..exceptions import ValidationError
from ..schemas.serializers import serialize_menu_item_suggestion, serialize_ingredient_suggestion
from ..schemas.unrecognized_suggestions import (
    UnrecognizedMenuItemSuggestionOut,
    UnrecognizedMenuItemSuggestionCreate,
    UnrecognizedMenuItemSuggestionUpdate,
    UnrecognizedMenuItemSuggestionStats,
    UnrecognizedMenuItemLogEntry,
    UnrecognizedMenuItemLogStats,
    UnrecognizedOptionSuggestionOut,
    UnrecognizedOptionSuggestionCreate,
    UnrecognizedOptionSuggestionUpdate,
    UnrecognizedOptionSuggestionStats,
    UnrecognizedIngredientSuggestionOut,
    UnrecognizedIngredientSuggestionCreate,
    UnrecognizedIngredientSuggestionUpdate,
)
from .crud_factory import CRUDRouterFactory, reorder_routes_static_first

logger = logging.getLogger(__name__)

# Valid match types
VALID_MATCH_TYPES = {"exact", "prefix", "contains"}


# =============================================================================
# Menu Item Suggestions - Factory Hooks
# =============================================================================

def _menu_item_before_create(
    payload: UnrecognizedMenuItemSuggestionCreate, db: Session
) -> dict:
    """Validate and normalize payload, return kwargs for model creation."""
    if payload.match_type not in VALID_MATCH_TYPES:
        raise ValidationError(
            f"Invalid match_type. Must be one of: {', '.join(VALID_MATCH_TYPES)}"
        )

    pattern_normalized = payload.input_pattern.lower().strip()

    existing = db.query(UnrecognizedMenuItemSuggestion).filter(
        UnrecognizedMenuItemSuggestion.input_pattern == pattern_normalized,
        UnrecognizedMenuItemSuggestion.match_type == payload.match_type
    ).first()
    if existing:
        raise ValidationError(
            f"Pattern '{pattern_normalized}' with match_type "
            f"'{payload.match_type}' already exists"
        )

    item_type_id = None
    if payload.suggested_item_type_slug:
        item_type = db.query(ItemType).filter(
            ItemType.slug == payload.suggested_item_type_slug
        ).first()
        if not item_type:
            raise ValidationError(
                f"Item type '{payload.suggested_item_type_slug}' not found"
            )
        item_type_id = item_type.id

    return {
        "input_pattern": pattern_normalized,
        "match_type": payload.match_type,
        "suggested_item_type_id": item_type_id,
        "is_active": payload.is_active,
    }


def _menu_item_create_pre_commit(
    item: UnrecognizedMenuItemSuggestion,
    payload: UnrecognizedMenuItemSuggestionCreate,
    db: Session,
) -> None:
    """Resolve many-to-many menu items from names after flush."""
    if payload.suggested_menu_item_names:
        menu_items = []
        for name in payload.suggested_menu_item_names:
            menu_item = db.query(MenuItem).filter(MenuItem.name == name).first()
            if not menu_item:
                raise ValidationError(f"Menu item '{name}' not found")
            menu_items.append(menu_item)
        item.suggested_menu_items = menu_items


def _menu_item_before_update(
    item: UnrecognizedMenuItemSuggestion,
    payload: UnrecognizedMenuItemSuggestionUpdate,
    db: Session,
) -> None:
    """Validate, normalize, and apply updates in place."""
    if payload.match_type is not None and payload.match_type not in VALID_MATCH_TYPES:
        raise ValidationError(
            f"Invalid match_type. Must be one of: {', '.join(VALID_MATCH_TYPES)}"
        )

    new_pattern = (
        payload.input_pattern.lower().strip()
        if payload.input_pattern else item.input_pattern
    )
    new_match_type = payload.match_type if payload.match_type else item.match_type

    if new_pattern != item.input_pattern or new_match_type != item.match_type:
        existing = db.query(UnrecognizedMenuItemSuggestion).filter(
            UnrecognizedMenuItemSuggestion.input_pattern == new_pattern,
            UnrecognizedMenuItemSuggestion.match_type == new_match_type,
            UnrecognizedMenuItemSuggestion.id != item.id
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

    if payload.suggested_item_type_slug is not None:
        if payload.suggested_item_type_slug == "":
            item.suggested_item_type_id = None
        else:
            it = db.query(ItemType).filter(
                ItemType.slug == payload.suggested_item_type_slug
            ).first()
            if not it:
                raise ValidationError(
                    f"Item type '{payload.suggested_item_type_slug}' not found"
                )
            item.suggested_item_type_id = it.id

    if payload.suggested_menu_item_names is not None:
        menu_items = []
        for name in payload.suggested_menu_item_names:
            mi = db.query(MenuItem).filter(MenuItem.name == name).first()
            if not mi:
                raise ValidationError(f"Menu item '{name}' not found")
            menu_items.append(mi)
        item.suggested_menu_items = menu_items

    if payload.is_active is not None:
        item.is_active = payload.is_active


# Factory for Menu Item Suggestions CRUD
_menu_item_crud = CRUDRouterFactory(
    model=UnrecognizedMenuItemSuggestion,
    create_schema=UnrecognizedMenuItemSuggestionCreate,
    update_schema=UnrecognizedMenuItemSuggestionUpdate,
    response_schema=UnrecognizedMenuItemSuggestionOut,
    prefix="/admin/unrecognized-menu-items",
    tags=["Admin - Unrecognized Menu Items"],
    id_param="suggestion_id",
    not_found_message="Suggestion not found",
    on_before_create=_menu_item_before_create,
    on_create_pre_commit=_menu_item_create_pre_commit,
    on_before_update=_menu_item_before_update,
    to_response=lambda item, db: serialize_menu_item_suggestion(item),
)

admin_unrecognized_menu_item_suggestions_router = _menu_item_crud.router
# Remove factory's default list route (doesn't support query filters)
admin_unrecognized_menu_item_suggestions_router.routes.pop(0)


# -- Custom endpoints on the same router --


@admin_unrecognized_menu_item_suggestions_router.get(
    "", response_model=list[UnrecognizedMenuItemSuggestionOut]
)
def list_suggestions(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    match_type: str | None = Query(None, description="Filter by match type"),
    category: str | None = Query(None, description="Filter by item type slug"),
    active_only: bool = Query(False, description="Only show active suggestions"),
) -> list[UnrecognizedMenuItemSuggestionOut]:
    """List all unrecognized item suggestions."""
    query = db.query(UnrecognizedMenuItemSuggestion)

    if match_type:
        if match_type not in VALID_MATCH_TYPES:
            raise ValidationError(
                f"Invalid match_type. Must be one of: {', '.join(VALID_MATCH_TYPES)}"
            )
        query = query.filter(UnrecognizedMenuItemSuggestion.match_type == match_type)

    if category:
        # Filter by item type slug via join
        query = query.join(ItemType).filter(ItemType.slug == category)

    if active_only:
        query = query.filter(UnrecognizedMenuItemSuggestion.is_active == True)

    suggestions = query.order_by(
        UnrecognizedMenuItemSuggestion.hit_count.desc(),
        UnrecognizedMenuItemSuggestion.input_pattern
    ).all()

    return [serialize_menu_item_suggestion(s) for s in suggestions]


@admin_unrecognized_menu_item_suggestions_router.get(
    "/stats", response_model=UnrecognizedMenuItemSuggestionStats
)
def get_suggestion_stats(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> UnrecognizedMenuItemSuggestionStats:
    """Get statistics for unrecognized item suggestions."""
    suggestions = db.query(UnrecognizedMenuItemSuggestion).all()

    # Aggregate stats
    total = len(suggestions)
    active = sum(1 for s in suggestions if s.is_active)
    total_hits = sum(s.hit_count for s in suggestions)

    # Group by match type
    by_match_type: dict[str, int] = {}
    for s in suggestions:
        by_match_type[s.match_type] = by_match_type.get(s.match_type, 0) + 1

    # Group by category (using relationship)
    by_category: dict[str, int] = {}
    for s in suggestions:
        cat = s.suggested_item_type.slug if s.suggested_item_type else "(no category)"
        by_category[cat] = by_category.get(cat, 0) + 1

    # Top hits
    top_hits = sorted(suggestions, key=lambda s: s.hit_count, reverse=True)[:10]

    return UnrecognizedMenuItemSuggestionStats(
        total_suggestions=total,
        active_suggestions=active,
        total_hits=total_hits,
        by_match_type=by_match_type,
        by_category=by_category,
        top_hits=[
            {
                "id": s.id,
                "input_pattern": s.input_pattern,
                "hit_count": s.hit_count,
                "category": s.suggested_item_type.slug if s.suggested_item_type else None,
            }
            for s in top_hits
        ],
    )


@admin_unrecognized_menu_item_suggestions_router.get(
    "/lookups/item-types", response_model=list[dict]
)
def get_item_types_for_dropdown(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> list[dict]:
    """Get all item types for dropdown selection."""
    item_types = db.query(ItemType).order_by(ItemType.display_name).all()
    return [
        {"slug": it.slug, "display_name": it.display_name}
        for it in item_types
    ]


@admin_unrecognized_menu_item_suggestions_router.get(
    "/lookups/menu-items", response_model=list[dict]
)
def get_menu_items_for_dropdown(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> list[dict]:
    """Get all menu items for dropdown selection."""
    menu_items = db.query(MenuItem).order_by(MenuItem.name).all()
    return [
        {"id": mi.id, "name": mi.name}
        for mi in menu_items
    ]


reorder_routes_static_first(admin_unrecognized_menu_item_suggestions_router)


# =============================================================================
# Log Endpoints (Analytics) - UNCHANGED
# =============================================================================

admin_unrecognized_menu_item_logs_router = APIRouter(
    prefix="/admin/unrecognized-menu-item-logs",
    tags=["Admin - Unrecognized Menu Item Logs"]
)


@admin_unrecognized_menu_item_logs_router.get("", response_model=list[UnrecognizedMenuItemLogEntry])
def list_logs(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    fallback_level: str | None = Query(None, description="Filter by fallback level"),
    limit: int = Query(100, ge=1, le=1000, description="Max entries to return"),
    days: int = Query(7, ge=1, le=90, description="Days of history to include"),
) -> list[UnrecognizedMenuItemLogEntry]:
    """List unrecognized item log entries."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    query = db.query(UnrecognizedMenuItemLog).filter(
        UnrecognizedMenuItemLog.created_at >= cutoff
    )

    if fallback_level:
        query = query.filter(UnrecognizedMenuItemLog.fallback_level == fallback_level)

    logs = query.order_by(UnrecognizedMenuItemLog.created_at.desc()).limit(limit).all()

    return [
        UnrecognizedMenuItemLogEntry(
            id=log.id,
            user_input=log.user_input,
            normalized_input=log.normalized_input,
            session_id=log.session_id,
            order_item_count=log.order_item_count,
            fallback_level=log.fallback_level,
            inferred_category=log.inferred_category,
            created_at=log.created_at,
        )
        for log in logs
    ]


@admin_unrecognized_menu_item_logs_router.get("/stats", response_model=UnrecognizedMenuItemLogStats)
def get_log_stats(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    days: int = Query(7, ge=1, le=90, description="Days of history to include"),
) -> UnrecognizedMenuItemLogStats:
    """Get statistics for unrecognized item logs."""
    cutoff = datetime.utcnow() - timedelta(days=days)

    logs = db.query(UnrecognizedMenuItemLog).filter(
        UnrecognizedMenuItemLog.created_at >= cutoff
    ).all()

    total = len(logs)

    # Group by fallback level
    by_fallback: dict[str, int] = {}
    for log in logs:
        by_fallback[log.fallback_level] = by_fallback.get(log.fallback_level, 0) + 1

    # Group by inferred category
    by_category: dict[str, int] = {}
    for log in logs:
        cat = log.inferred_category or "(none)"
        by_category[cat] = by_category.get(cat, 0) + 1

    # Top unrecognized items (most frequent normalized inputs)
    input_counts: dict[str, int] = {}
    for log in logs:
        input_counts[log.normalized_input] = input_counts.get(log.normalized_input, 0) + 1

    top_unrecognized = sorted(
        [{"input": k, "count": v} for k, v in input_counts.items()],
        key=lambda x: x["count"],
        reverse=True
    )[:20]

    # Recent entries
    recent = sorted(logs, key=lambda x: x.created_at, reverse=True)[:10]

    return UnrecognizedMenuItemLogStats(
        total_requests=total,
        by_fallback_level=by_fallback,
        by_inferred_category=by_category,
        top_unrecognized=top_unrecognized,
        recent_entries=[
            UnrecognizedMenuItemLogEntry(
                id=log.id,
                user_input=log.user_input,
                normalized_input=log.normalized_input,
                session_id=log.session_id,
                order_item_count=log.order_item_count,
                fallback_level=log.fallback_level,
                inferred_category=log.inferred_category,
                created_at=log.created_at,
            )
            for log in recent
        ],
    )


@admin_unrecognized_menu_item_logs_router.delete("/clear", status_code=200)
def clear_old_logs(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    days: int = Query(30, ge=1, le=365, description="Delete logs older than this many days"),
) -> dict:
    """Clear old unrecognized item logs."""
    cutoff = datetime.utcnow() - timedelta(days=days)

    deleted = db.query(UnrecognizedMenuItemLog).filter(
        UnrecognizedMenuItemLog.created_at < cutoff
    ).delete()

    db.commit()

    logger.info("Cleared %d unrecognized item logs older than %d days", deleted, days)

    return {"deleted": deleted, "days_threshold": days}


# =============================================================================
# Option Suggestions - Factory Hooks
# =============================================================================

def _option_before_create(
    payload: UnrecognizedOptionSuggestionCreate, db: Session
) -> dict:
    """Validate and normalize payload, return kwargs for model creation."""
    pattern_normalized = payload.input_pattern.lower().strip()

    existing = db.query(UnrecognizedOptionSuggestion).filter(
        UnrecognizedOptionSuggestion.input_pattern == pattern_normalized,
        UnrecognizedOptionSuggestion.attribute_slug == payload.attribute_slug
    ).first()
    if existing:
        raise ValidationError(
            f"Pattern '{pattern_normalized}' for attribute "
            f"'{payload.attribute_slug}' already exists"
        )

    return {
        "input_pattern": pattern_normalized,
        "attribute_slug": payload.attribute_slug,
        "suggested_display_name": payload.suggested_display_name,
        "is_active": payload.is_active,
    }


def _option_before_update(
    item: UnrecognizedOptionSuggestion,
    payload: UnrecognizedOptionSuggestionUpdate,
    db: Session,
) -> None:
    """Validate, normalize, and apply updates in place."""
    new_pattern = (
        payload.input_pattern.lower().strip()
        if payload.input_pattern else item.input_pattern
    )
    new_attr_slug = payload.attribute_slug if payload.attribute_slug else item.attribute_slug

    if new_pattern != item.input_pattern or new_attr_slug != item.attribute_slug:
        existing = db.query(UnrecognizedOptionSuggestion).filter(
            UnrecognizedOptionSuggestion.input_pattern == new_pattern,
            UnrecognizedOptionSuggestion.attribute_slug == new_attr_slug,
            UnrecognizedOptionSuggestion.id != item.id
        ).first()
        if existing:
            raise ValidationError(
                f"Pattern '{new_pattern}' for attribute "
                f"'{new_attr_slug}' already exists"
            )

    if payload.input_pattern is not None:
        item.input_pattern = new_pattern
    if payload.attribute_slug is not None:
        item.attribute_slug = payload.attribute_slug
    if payload.suggested_display_name is not None:
        item.suggested_display_name = payload.suggested_display_name
    if payload.is_active is not None:
        item.is_active = payload.is_active


# Factory for Option Suggestions CRUD
_option_crud = CRUDRouterFactory(
    model=UnrecognizedOptionSuggestion,
    create_schema=UnrecognizedOptionSuggestionCreate,
    update_schema=UnrecognizedOptionSuggestionUpdate,
    response_schema=UnrecognizedOptionSuggestionOut,
    prefix="/admin/unrecognized-option-suggestions",
    tags=["Admin - Unrecognized Option Suggestions"],
    id_param="suggestion_id",
    not_found_message="Option suggestion not found",
    on_before_create=_option_before_create,
    on_before_update=_option_before_update,
)

admin_unrecognized_option_suggestions_router = _option_crud.router
# Remove factory's default list route (doesn't support query filters)
admin_unrecognized_option_suggestions_router.routes.pop(0)


# -- Custom endpoints on the same router --


@admin_unrecognized_option_suggestions_router.get(
    "", response_model=list[UnrecognizedOptionSuggestionOut]
)
def list_option_suggestions(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    attribute_slug: str | None = Query(None, description="Filter by attribute slug"),
    active_only: bool = Query(False, description="Only show active suggestions"),
) -> list[UnrecognizedOptionSuggestionOut]:
    """List all unrecognized option suggestions."""
    query = db.query(UnrecognizedOptionSuggestion)

    if attribute_slug:
        query = query.filter(UnrecognizedOptionSuggestion.attribute_slug == attribute_slug)

    if active_only:
        query = query.filter(UnrecognizedOptionSuggestion.is_active == True)

    suggestions = query.order_by(
        UnrecognizedOptionSuggestion.attribute_slug,
        UnrecognizedOptionSuggestion.input_pattern
    ).all()

    return [UnrecognizedOptionSuggestionOut.model_validate(s) for s in suggestions]


@admin_unrecognized_option_suggestions_router.get(
    "/stats", response_model=UnrecognizedOptionSuggestionStats
)
def get_option_suggestion_stats(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> UnrecognizedOptionSuggestionStats:
    """Get statistics for unrecognized option suggestions."""
    suggestions = db.query(UnrecognizedOptionSuggestion).all()

    total = len(suggestions)
    active = sum(1 for s in suggestions if s.is_active)

    # Group by attribute
    by_attribute: dict[str, int] = {}
    for s in suggestions:
        by_attribute[s.attribute_slug] = by_attribute.get(s.attribute_slug, 0) + 1

    return UnrecognizedOptionSuggestionStats(
        total_suggestions=total,
        active_suggestions=active,
        by_attribute=by_attribute,
    )


@admin_unrecognized_option_suggestions_router.get(
    "/lookups/attributes", response_model=list[dict]
)
def get_attributes_for_dropdown(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> list[dict]:
    """Get all global attributes for dropdown selection."""
    attributes = db.query(GlobalAttribute).order_by(GlobalAttribute.display_name).all()
    return [
        {"slug": a.slug, "display_name": a.display_name}
        for a in attributes
    ]


reorder_routes_static_first(admin_unrecognized_option_suggestions_router)


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

    pattern_normalized = payload.input_pattern.lower().strip()

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
            ingredient = db.query(Ingredient).filter(Ingredient.name == name).first()
            if not ingredient:
                raise ValidationError(f"Ingredient '{name}' not found")
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
        payload.input_pattern.lower().strip()
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
            ingredient = db.query(Ingredient).filter(Ingredient.name == name).first()
            if not ingredient:
                raise ValidationError(f"Ingredient '{name}' not found")
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
