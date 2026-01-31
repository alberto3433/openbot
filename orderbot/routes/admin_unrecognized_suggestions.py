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
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import UnrecognizedItemSuggestion, UnrecognizedItemLog, ItemType, MenuItem
from ..schemas.unrecognized_suggestions import (
    UnrecognizedSuggestionOut,
    UnrecognizedSuggestionCreate,
    UnrecognizedSuggestionUpdate,
    UnrecognizedSuggestionStats,
    UnrecognizedLogEntry,
    UnrecognizedLogStats,
)

logger = logging.getLogger(__name__)

# Router definition
admin_unrecognized_suggestions_router = APIRouter(
    prefix="/admin/unrecognized-suggestions",
    tags=["Admin - Unrecognized Suggestions"]
)

admin_unrecognized_logs_router = APIRouter(
    prefix="/admin/unrecognized-logs",
    tags=["Admin - Unrecognized Logs"]
)

# Valid match types
VALID_MATCH_TYPES = {"exact", "prefix", "contains"}


# =============================================================================
# Suggestions Endpoints
# =============================================================================

@admin_unrecognized_suggestions_router.get("", response_model=List[UnrecognizedSuggestionOut])
def list_suggestions(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    match_type: Optional[str] = Query(None, description="Filter by match type"),
    category: Optional[str] = Query(None, description="Filter by item type slug"),
    active_only: bool = Query(False, description="Only show active suggestions"),
) -> List[UnrecognizedSuggestionOut]:
    """List all unrecognized item suggestions."""
    query = db.query(UnrecognizedItemSuggestion)

    if match_type:
        if match_type not in VALID_MATCH_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid match_type. Must be one of: {', '.join(VALID_MATCH_TYPES)}"
            )
        query = query.filter(UnrecognizedItemSuggestion.match_type == match_type)

    if category:
        # Filter by item type slug via join
        query = query.join(ItemType).filter(ItemType.slug == category)

    if active_only:
        query = query.filter(UnrecognizedItemSuggestion.is_active == True)

    suggestions = query.order_by(
        UnrecognizedItemSuggestion.hit_count.desc(),
        UnrecognizedItemSuggestion.input_pattern
    ).all()

    return [UnrecognizedSuggestionOut.from_db(s) for s in suggestions]


@admin_unrecognized_suggestions_router.get("/stats", response_model=UnrecognizedSuggestionStats)
def get_suggestion_stats(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> UnrecognizedSuggestionStats:
    """Get statistics for unrecognized item suggestions."""
    suggestions = db.query(UnrecognizedItemSuggestion).all()

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

    return UnrecognizedSuggestionStats(
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


@admin_unrecognized_suggestions_router.get("/{suggestion_id}", response_model=UnrecognizedSuggestionOut)
def get_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> UnrecognizedSuggestionOut:
    """Get a specific suggestion by ID."""
    suggestion = db.query(UnrecognizedItemSuggestion).filter(
        UnrecognizedItemSuggestion.id == suggestion_id
    ).first()

    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    return UnrecognizedSuggestionOut.from_db(suggestion)


@admin_unrecognized_suggestions_router.post("", response_model=UnrecognizedSuggestionOut, status_code=201)
def create_suggestion(
    payload: UnrecognizedSuggestionCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> UnrecognizedSuggestionOut:
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
    existing = db.query(UnrecognizedItemSuggestion).filter(
        UnrecognizedItemSuggestion.input_pattern == pattern_normalized,
        UnrecognizedItemSuggestion.match_type == payload.match_type
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

    suggestion = UnrecognizedItemSuggestion(
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

    return UnrecognizedSuggestionOut.from_db(suggestion)


@admin_unrecognized_suggestions_router.put("/{suggestion_id}", response_model=UnrecognizedSuggestionOut)
def update_suggestion(
    suggestion_id: int,
    payload: UnrecognizedSuggestionUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> UnrecognizedSuggestionOut:
    """Update an unrecognized item suggestion."""
    suggestion = db.query(UnrecognizedItemSuggestion).filter(
        UnrecognizedItemSuggestion.id == suggestion_id
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
        existing = db.query(UnrecognizedItemSuggestion).filter(
            UnrecognizedItemSuggestion.input_pattern == new_pattern,
            UnrecognizedItemSuggestion.match_type == new_match_type,
            UnrecognizedItemSuggestion.id != suggestion_id
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

    return UnrecognizedSuggestionOut.from_db(suggestion)


@admin_unrecognized_suggestions_router.delete("/{suggestion_id}", status_code=204)
def delete_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete an unrecognized item suggestion."""
    suggestion = db.query(UnrecognizedItemSuggestion).filter(
        UnrecognizedItemSuggestion.id == suggestion_id
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

@admin_unrecognized_logs_router.get("", response_model=List[UnrecognizedLogEntry])
def list_logs(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    fallback_level: Optional[str] = Query(None, description="Filter by fallback level"),
    limit: int = Query(100, ge=1, le=1000, description="Max entries to return"),
    days: int = Query(7, ge=1, le=90, description="Days of history to include"),
) -> List[UnrecognizedLogEntry]:
    """List unrecognized item log entries."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    query = db.query(UnrecognizedItemLog).filter(
        UnrecognizedItemLog.created_at >= cutoff
    )

    if fallback_level:
        query = query.filter(UnrecognizedItemLog.fallback_level == fallback_level)

    logs = query.order_by(UnrecognizedItemLog.created_at.desc()).limit(limit).all()

    return [
        UnrecognizedLogEntry(
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


@admin_unrecognized_logs_router.get("/stats", response_model=UnrecognizedLogStats)
def get_log_stats(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    days: int = Query(7, ge=1, le=90, description="Days of history to include"),
) -> UnrecognizedLogStats:
    """Get statistics for unrecognized item logs."""
    cutoff = datetime.utcnow() - timedelta(days=days)

    logs = db.query(UnrecognizedItemLog).filter(
        UnrecognizedItemLog.created_at >= cutoff
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

    return UnrecognizedLogStats(
        total_requests=total,
        by_fallback_level=by_fallback,
        by_inferred_category=by_category,
        top_unrecognized=top_unrecognized,
        recent_entries=[
            UnrecognizedLogEntry(
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


@admin_unrecognized_logs_router.delete("/clear", status_code=200)
def clear_old_logs(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    days: int = Query(30, ge=1, le=365, description="Delete logs older than this many days"),
) -> dict:
    """Clear old unrecognized item logs."""
    cutoff = datetime.utcnow() - timedelta(days=days)

    deleted = db.query(UnrecognizedItemLog).filter(
        UnrecognizedItemLog.created_at < cutoff
    ).delete()

    db.commit()

    logger.info("Cleared %d unrecognized item logs older than %d days", deleted, days)

    return {"deleted": deleted, "days_threshold": days}
