"""
Admin Unrecognized Option Suggestions Routes
=============================================

Endpoints for managing unrecognized option suggestions.

Endpoints:
----------
- GET /admin/unrecognized-option-suggestions: List (custom filters)
- GET /admin/unrecognized-option-suggestions/stats: Statistics
- GET /admin/unrecognized-option-suggestions/lookups/attributes: Attributes dropdown
- GET/POST/PUT/DELETE: Standard CRUD (factory)

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.
"""

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import UnrecognizedOptionSuggestion, GlobalAttribute
from ..exceptions import ValidationError
from ..schemas.unrecognized_suggestions import (
    UnrecognizedOptionSuggestionOut,
    UnrecognizedOptionSuggestionCreate,
    UnrecognizedOptionSuggestionUpdate,
    UnrecognizedOptionSuggestionStats,
)
from .crud_factory import CRUDRouterFactory, reorder_routes_static_first
from ..cache.base import normalize_text


# =============================================================================
# Option Suggestions - Factory Hooks
# =============================================================================

def _option_before_create(
    payload: UnrecognizedOptionSuggestionCreate, db: Session
) -> dict:
    """Validate and normalize payload, return kwargs for model creation."""
    pattern_normalized = normalize_text(payload.input_pattern)

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
        normalize_text(payload.input_pattern)
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
