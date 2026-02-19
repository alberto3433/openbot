"""
Admin Unrecognized Item Suggestions Routes for Orderbot
=======================================================

This module contains admin endpoints for managing unrecognized item suggestions.
These are curated responses for items users commonly request that aren't on the menu.

Endpoints:
----------
Suggestions:
- GET /admin/unrecognized-suggestions: List all suggestions
- GET /admin/unrecognized-suggestions/stats: Get suggestion statistics
- GET /admin/unrecognized-suggestions/{id}: Get a specific suggestion
- POST /admin/unrecognized-suggestions: Create a new suggestion
- PUT /admin/unrecognized-suggestions/{id}: Update a suggestion
- DELETE /admin/unrecognized-suggestions/{id}: Delete a suggestion

Logs (Analytics):
- GET /admin/unrecognized-logs: List unrecognized item logs
- GET /admin/unrecognized-logs/stats: Get log statistics
- DELETE /admin/unrecognized-logs/clear: Clear old logs

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.
"""

import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import (
    UnrecognizedMenuItemSuggestion, UnrecognizedMenuItemLog, ItemType, MenuItem,
    UnrecognizedOptionSuggestion, GlobalAttribute,
    UnrecognizedIngredientSuggestion, Ingredient,
)
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

logger = logging.getLogger(__name__)

# Router definition
admin_unrecognized_menu_item_suggestions_router = APIRouter(
    prefix="/admin/unrecognized-menu-items",
    tags=["Admin - Unrecognized Menu Items"]
)

admin_unrecognized_menu_item_logs_router = APIRouter(
    prefix="/admin/unrecognized-menu-item-logs",
    tags=["Admin - Unrecognized Menu Item Logs"]
)

admin_unrecognized_option_suggestions_router = APIRouter(
    prefix="/admin/unrecognized-option-suggestions",
    tags=["Admin - Unrecognized Option Suggestions"]
)

# Valid match types
VALID_MATCH_TYPES = {"exact", "prefix", "contains"}


# =============================================================================
# Suggestions Endpoints
# =============================================================================

@admin_unrecognized_menu_item_suggestions_router.get("", response_model=list[UnrecognizedMenuItemSuggestionOut])
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
            raise HTTPException(
                status_code=400,
                detail=f"Invalid match_type. Must be one of: {', '.join(VALID_MATCH_TYPES)}"
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


@admin_unrecognized_menu_item_suggestions_router.get("/stats", response_model=UnrecognizedMenuItemSuggestionStats)
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


@admin_unrecognized_menu_item_suggestions_router.get("/lookups/item-types", response_model=list[dict])
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


@admin_unrecognized_menu_item_suggestions_router.get("/lookups/menu-items", response_model=list[dict])
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


@admin_unrecognized_menu_item_suggestions_router.get("/{suggestion_id}", response_model=UnrecognizedMenuItemSuggestionOut)
def get_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> UnrecognizedMenuItemSuggestionOut:
    """Get a specific suggestion by ID."""
    suggestion = db.query(UnrecognizedMenuItemSuggestion).filter(
        UnrecognizedMenuItemSuggestion.id == suggestion_id
    ).first()

    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    return serialize_menu_item_suggestion(suggestion)


@admin_unrecognized_menu_item_suggestions_router.post("", response_model=UnrecognizedMenuItemSuggestionOut, status_code=201)
def create_suggestion(
    payload: UnrecognizedMenuItemSuggestionCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> UnrecognizedMenuItemSuggestionOut:
    """Create a new unrecognized item suggestion."""
    # Validate match type
    if payload.match_type not in VALID_MATCH_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid match_type. Must be one of: {', '.join(VALID_MATCH_TYPES)}"
        )

    # Normalize pattern to lowercase
    pattern_normalized = payload.input_pattern.lower().strip()

    # Check for duplicate
    existing = db.query(UnrecognizedMenuItemSuggestion).filter(
        UnrecognizedMenuItemSuggestion.input_pattern == pattern_normalized,
        UnrecognizedMenuItemSuggestion.match_type == payload.match_type
    ).first()

    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Pattern '{pattern_normalized}' with match_type '{payload.match_type}' already exists"
        )

    # Look up item type by slug if provided
    item_type_id = None
    if payload.suggested_item_type_slug:
        item_type = db.query(ItemType).filter(
            ItemType.slug == payload.suggested_item_type_slug
        ).first()
        if not item_type:
            raise HTTPException(
                status_code=400,
                detail=f"Item type '{payload.suggested_item_type_slug}' not found"
            )
        item_type_id = item_type.id

    # Look up menu items by name if provided
    menu_items = []
    if payload.suggested_menu_item_names:
        for name in payload.suggested_menu_item_names:
            menu_item = db.query(MenuItem).filter(MenuItem.name == name).first()
            if not menu_item:
                raise HTTPException(
                    status_code=400,
                    detail=f"Menu item '{name}' not found"
                )
            menu_items.append(menu_item)

    suggestion = UnrecognizedMenuItemSuggestion(
        input_pattern=pattern_normalized,
        match_type=payload.match_type,
        suggested_item_type_id=item_type_id,
        is_active=payload.is_active,
    )
    if menu_items:
        suggestion.suggested_menu_items = menu_items

    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)

    logger.info(
        "Created unrecognized suggestion: '%s' -> %s (id=%d)",
        suggestion.input_pattern,
        payload.suggested_item_type_slug or payload.suggested_menu_item_names,
        suggestion.id
    )

    return serialize_menu_item_suggestion(suggestion)


@admin_unrecognized_menu_item_suggestions_router.put("/{suggestion_id}", response_model=UnrecognizedMenuItemSuggestionOut)
def update_suggestion(
    suggestion_id: int,
    payload: UnrecognizedMenuItemSuggestionUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> UnrecognizedMenuItemSuggestionOut:
    """Update an unrecognized item suggestion."""
    suggestion = db.query(UnrecognizedMenuItemSuggestion).filter(
        UnrecognizedMenuItemSuggestion.id == suggestion_id
    ).first()

    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    # Validate match type if changing it
    if payload.match_type is not None:
        if payload.match_type not in VALID_MATCH_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid match_type. Must be one of: {', '.join(VALID_MATCH_TYPES)}"
            )

    # Normalize pattern if changing it
    new_pattern = payload.input_pattern.lower().strip() if payload.input_pattern else suggestion.input_pattern
    new_match_type = payload.match_type if payload.match_type else suggestion.match_type

    # Check for duplicate if changing pattern or match_type
    if new_pattern != suggestion.input_pattern or new_match_type != suggestion.match_type:
        existing = db.query(UnrecognizedMenuItemSuggestion).filter(
            UnrecognizedMenuItemSuggestion.input_pattern == new_pattern,
            UnrecognizedMenuItemSuggestion.match_type == new_match_type,
            UnrecognizedMenuItemSuggestion.id != suggestion_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Pattern '{new_pattern}' with match_type '{new_match_type}' already exists"
            )

    # Apply updates
    if payload.input_pattern is not None:
        suggestion.input_pattern = new_pattern
    if payload.match_type is not None:
        suggestion.match_type = payload.match_type

    # Update item type FK if provided
    if payload.suggested_item_type_slug is not None:
        if payload.suggested_item_type_slug == "":
            # Clear the item type
            suggestion.suggested_item_type_id = None
        else:
            item_type = db.query(ItemType).filter(
                ItemType.slug == payload.suggested_item_type_slug
            ).first()
            if not item_type:
                raise HTTPException(
                    status_code=400,
                    detail=f"Item type '{payload.suggested_item_type_slug}' not found"
                )
            suggestion.suggested_item_type_id = item_type.id

    # Update menu items relationship if provided
    if payload.suggested_menu_item_names is not None:
        menu_items = []
        for name in payload.suggested_menu_item_names:
            menu_item = db.query(MenuItem).filter(MenuItem.name == name).first()
            if not menu_item:
                raise HTTPException(
                    status_code=400,
                    detail=f"Menu item '{name}' not found"
                )
            menu_items.append(menu_item)
        suggestion.suggested_menu_items = menu_items

    if payload.is_active is not None:
        suggestion.is_active = payload.is_active

    db.commit()
    db.refresh(suggestion)

    logger.info("Updated unrecognized suggestion: '%s' (id=%d)", suggestion.input_pattern, suggestion.id)

    return serialize_menu_item_suggestion(suggestion)


@admin_unrecognized_menu_item_suggestions_router.delete("/{suggestion_id}", status_code=204)
def delete_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete an unrecognized item suggestion."""
    suggestion = db.query(UnrecognizedMenuItemSuggestion).filter(
        UnrecognizedMenuItemSuggestion.id == suggestion_id
    ).first()

    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    logger.info(
        "Deleting unrecognized suggestion: '%s' (id=%d)",
        suggestion.input_pattern,
        suggestion.id
    )
    db.delete(suggestion)
    db.commit()
    return None


# =============================================================================
# Log Endpoints (Analytics)
# =============================================================================

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
# Option Suggestions Endpoints
# =============================================================================

@admin_unrecognized_option_suggestions_router.get("", response_model=list[UnrecognizedOptionSuggestionOut])
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


@admin_unrecognized_option_suggestions_router.get("/stats", response_model=UnrecognizedOptionSuggestionStats)
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


@admin_unrecognized_option_suggestions_router.get("/lookups/attributes", response_model=list[dict])
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


@admin_unrecognized_option_suggestions_router.get("/{suggestion_id}", response_model=UnrecognizedOptionSuggestionOut)
def get_option_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> UnrecognizedOptionSuggestionOut:
    """Get a specific option suggestion by ID."""
    suggestion = db.query(UnrecognizedOptionSuggestion).filter(
        UnrecognizedOptionSuggestion.id == suggestion_id
    ).first()

    if not suggestion:
        raise HTTPException(status_code=404, detail="Option suggestion not found")

    return UnrecognizedOptionSuggestionOut.model_validate(suggestion)


@admin_unrecognized_option_suggestions_router.post("", response_model=UnrecognizedOptionSuggestionOut, status_code=201)
def create_option_suggestion(
    payload: UnrecognizedOptionSuggestionCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> UnrecognizedOptionSuggestionOut:
    """Create a new unrecognized option suggestion."""
    # Normalize pattern to lowercase
    pattern_normalized = payload.input_pattern.lower().strip()

    # Check for duplicate
    existing = db.query(UnrecognizedOptionSuggestion).filter(
        UnrecognizedOptionSuggestion.input_pattern == pattern_normalized,
        UnrecognizedOptionSuggestion.attribute_slug == payload.attribute_slug
    ).first()

    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Pattern '{pattern_normalized}' for attribute '{payload.attribute_slug}' already exists"
        )

    suggestion = UnrecognizedOptionSuggestion(
        input_pattern=pattern_normalized,
        attribute_slug=payload.attribute_slug,
        suggested_display_name=payload.suggested_display_name,
        is_active=payload.is_active,
    )

    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)

    logger.info(
        "Created unrecognized option suggestion: '%s' -> '%s' for attribute '%s' (id=%d)",
        suggestion.input_pattern,
        suggestion.suggested_display_name,
        suggestion.attribute_slug,
        suggestion.id
    )

    return UnrecognizedOptionSuggestionOut.model_validate(suggestion)


@admin_unrecognized_option_suggestions_router.put("/{suggestion_id}", response_model=UnrecognizedOptionSuggestionOut)
def update_option_suggestion(
    suggestion_id: int,
    payload: UnrecognizedOptionSuggestionUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> UnrecognizedOptionSuggestionOut:
    """Update an unrecognized option suggestion."""
    suggestion = db.query(UnrecognizedOptionSuggestion).filter(
        UnrecognizedOptionSuggestion.id == suggestion_id
    ).first()

    if not suggestion:
        raise HTTPException(status_code=404, detail="Option suggestion not found")

    # Normalize pattern if changing it
    new_pattern = payload.input_pattern.lower().strip() if payload.input_pattern else suggestion.input_pattern
    new_attr_slug = payload.attribute_slug if payload.attribute_slug else suggestion.attribute_slug

    # Check for duplicate if changing pattern or attribute
    if new_pattern != suggestion.input_pattern or new_attr_slug != suggestion.attribute_slug:
        existing = db.query(UnrecognizedOptionSuggestion).filter(
            UnrecognizedOptionSuggestion.input_pattern == new_pattern,
            UnrecognizedOptionSuggestion.attribute_slug == new_attr_slug,
            UnrecognizedOptionSuggestion.id != suggestion_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Pattern '{new_pattern}' for attribute '{new_attr_slug}' already exists"
            )

    # Apply updates
    if payload.input_pattern is not None:
        suggestion.input_pattern = new_pattern
    if payload.attribute_slug is not None:
        suggestion.attribute_slug = payload.attribute_slug
    if payload.suggested_display_name is not None:
        suggestion.suggested_display_name = payload.suggested_display_name
    if payload.is_active is not None:
        suggestion.is_active = payload.is_active

    db.commit()
    db.refresh(suggestion)

    logger.info("Updated unrecognized option suggestion: '%s' (id=%d)", suggestion.input_pattern, suggestion.id)

    return UnrecognizedOptionSuggestionOut.model_validate(suggestion)


@admin_unrecognized_option_suggestions_router.delete("/{suggestion_id}", status_code=204)
def delete_option_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete an unrecognized option suggestion."""
    suggestion = db.query(UnrecognizedOptionSuggestion).filter(
        UnrecognizedOptionSuggestion.id == suggestion_id
    ).first()

    if not suggestion:
        raise HTTPException(status_code=404, detail="Option suggestion not found")

    logger.info(
        "Deleting unrecognized option suggestion: '%s' (id=%d)",
        suggestion.input_pattern,
        suggestion.id
    )
    db.delete(suggestion)
    db.commit()
    return None


# =============================================================================
# Ingredient Suggestions Endpoints
# =============================================================================

admin_unrecognized_ingredient_suggestions_router = APIRouter(
    prefix="/admin/unrecognized-ingredient-suggestions",
    tags=["Admin - Unrecognized Ingredient Suggestions"]
)


@admin_unrecognized_ingredient_suggestions_router.get("", response_model=list[UnrecognizedIngredientSuggestionOut])
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


@admin_unrecognized_ingredient_suggestions_router.get(
    "/{suggestion_id}", response_model=UnrecognizedIngredientSuggestionOut
)
def get_ingredient_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> UnrecognizedIngredientSuggestionOut:
    """Get a specific ingredient suggestion by ID."""
    suggestion = db.query(UnrecognizedIngredientSuggestion).filter(
        UnrecognizedIngredientSuggestion.id == suggestion_id
    ).first()

    if not suggestion:
        raise HTTPException(status_code=404, detail="Ingredient suggestion not found")

    return serialize_ingredient_suggestion(suggestion)


@admin_unrecognized_ingredient_suggestions_router.post(
    "", response_model=UnrecognizedIngredientSuggestionOut, status_code=201
)
def create_ingredient_suggestion(
    payload: UnrecognizedIngredientSuggestionCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> UnrecognizedIngredientSuggestionOut:
    """Create a new unrecognized ingredient suggestion."""
    if payload.match_type not in VALID_MATCH_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid match_type. Must be one of: {', '.join(VALID_MATCH_TYPES)}"
        )

    pattern_normalized = payload.input_pattern.lower().strip()

    # Check for duplicate
    existing = db.query(UnrecognizedIngredientSuggestion).filter(
        UnrecognizedIngredientSuggestion.input_pattern == pattern_normalized,
        UnrecognizedIngredientSuggestion.match_type == payload.match_type
    ).first()

    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Pattern '{pattern_normalized}' with match_type '{payload.match_type}' already exists"
        )

    # Look up alternative ingredients by name
    alternatives = []
    if payload.alternative_ingredient_names:
        for name in payload.alternative_ingredient_names:
            ingredient = db.query(Ingredient).filter(Ingredient.name == name).first()
            if not ingredient:
                raise HTTPException(status_code=400, detail=f"Ingredient '{name}' not found")
            alternatives.append(ingredient)

    suggestion = UnrecognizedIngredientSuggestion(
        input_pattern=pattern_normalized,
        match_type=payload.match_type,
        suggested_display_name=payload.suggested_display_name,
        modifier_category=payload.modifier_category,
        is_active=payload.is_active,
    )
    if alternatives:
        suggestion.alternative_ingredients = alternatives

    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)

    logger.info(
        "Created unrecognized ingredient suggestion: '%s' (id=%d)",
        suggestion.input_pattern,
        suggestion.id,
    )

    return serialize_ingredient_suggestion(suggestion)


@admin_unrecognized_ingredient_suggestions_router.put(
    "/{suggestion_id}", response_model=UnrecognizedIngredientSuggestionOut
)
def update_ingredient_suggestion(
    suggestion_id: int,
    payload: UnrecognizedIngredientSuggestionUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> UnrecognizedIngredientSuggestionOut:
    """Update an unrecognized ingredient suggestion."""
    suggestion = db.query(UnrecognizedIngredientSuggestion).filter(
        UnrecognizedIngredientSuggestion.id == suggestion_id
    ).first()

    if not suggestion:
        raise HTTPException(status_code=404, detail="Ingredient suggestion not found")

    if payload.match_type is not None and payload.match_type not in VALID_MATCH_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid match_type. Must be one of: {', '.join(VALID_MATCH_TYPES)}"
        )

    new_pattern = payload.input_pattern.lower().strip() if payload.input_pattern else suggestion.input_pattern
    new_match_type = payload.match_type if payload.match_type else suggestion.match_type

    if new_pattern != suggestion.input_pattern or new_match_type != suggestion.match_type:
        existing = db.query(UnrecognizedIngredientSuggestion).filter(
            UnrecognizedIngredientSuggestion.input_pattern == new_pattern,
            UnrecognizedIngredientSuggestion.match_type == new_match_type,
            UnrecognizedIngredientSuggestion.id != suggestion_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Pattern '{new_pattern}' with match_type '{new_match_type}' already exists"
            )

    if payload.input_pattern is not None:
        suggestion.input_pattern = new_pattern
    if payload.match_type is not None:
        suggestion.match_type = payload.match_type
    if payload.suggested_display_name is not None:
        suggestion.suggested_display_name = payload.suggested_display_name
    if payload.modifier_category is not None:
        suggestion.modifier_category = payload.modifier_category
    if payload.is_active is not None:
        suggestion.is_active = payload.is_active

    if payload.alternative_ingredient_names is not None:
        alternatives = []
        for name in payload.alternative_ingredient_names:
            ingredient = db.query(Ingredient).filter(Ingredient.name == name).first()
            if not ingredient:
                raise HTTPException(status_code=400, detail=f"Ingredient '{name}' not found")
            alternatives.append(ingredient)
        suggestion.alternative_ingredients = alternatives

    db.commit()
    db.refresh(suggestion)

    logger.info("Updated unrecognized ingredient suggestion: '%s' (id=%d)", suggestion.input_pattern, suggestion.id)

    return serialize_ingredient_suggestion(suggestion)


@admin_unrecognized_ingredient_suggestions_router.delete("/{suggestion_id}", status_code=204)
def delete_ingredient_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete an unrecognized ingredient suggestion."""
    suggestion = db.query(UnrecognizedIngredientSuggestion).filter(
        UnrecognizedIngredientSuggestion.id == suggestion_id
    ).first()

    if not suggestion:
        raise HTTPException(status_code=404, detail="Ingredient suggestion not found")

    logger.info(
        "Deleting unrecognized ingredient suggestion: '%s' (id=%d)",
        suggestion.input_pattern,
        suggestion.id,
    )
    db.delete(suggestion)
    db.commit()
    return None
