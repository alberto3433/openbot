"""
Admin Unrecognized Menu Item Suggestions Routes
================================================

Endpoints for managing unrecognized menu item suggestions - curated responses
for items users commonly request that aren't on the menu.

Endpoints:
----------
- GET /admin/unrecognized-menu-items: List all suggestions (custom filters)
- GET /admin/unrecognized-menu-items/stats: Get suggestion statistics
- GET /admin/unrecognized-menu-items/lookups/item-types: Item types dropdown
- GET /admin/unrecognized-menu-items/lookups/menu-items: Menu items dropdown
- GET /admin/unrecognized-menu-items/{id}: Get a specific suggestion (factory)
- POST /admin/unrecognized-menu-items: Create a new suggestion (factory)
- PUT /admin/unrecognized-menu-items/{id}: Update a suggestion (factory)
- DELETE /admin/unrecognized-menu-items/{id}: Delete a suggestion (factory)

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.
"""

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import UnrecognizedMenuItemSuggestion, ItemType, MenuItem
from ..exceptions import ValidationError
from ..schemas.serializers import serialize_menu_item_suggestion
from ..schemas.unrecognized_suggestions import (
    UnrecognizedMenuItemSuggestionOut,
    UnrecognizedMenuItemSuggestionCreate,
    UnrecognizedMenuItemSuggestionUpdate,
    UnrecognizedMenuItemSuggestionStats,
)
from .crud_factory import CRUDRouterFactory, reorder_routes_static_first
from ..cache.base import normalize_text

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

    pattern_normalized = normalize_text(payload.input_pattern)

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
        normalize_text(payload.input_pattern)
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
