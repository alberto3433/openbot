"""
Admin Response Patterns Routes for Orderbot
================================================

This module contains admin endpoints for managing response patterns.
Response patterns define how to recognize user intent from their input
(yes/no/cancel/done responses).

Endpoints:
----------
- GET /admin/response-patterns: List all patterns
- GET /admin/response-patterns/stats: Get pattern counts by type
- GET /admin/response-patterns/{id}: Get a specific pattern
- POST /admin/response-patterns: Create a new pattern
- PUT /admin/response-patterns/{id}: Update a pattern
- DELETE /admin/response-patterns/{id}: Delete a pattern

Pattern Types:
--------------
- affirmative: Yes responses (yes, yeah, sure, ok, etc.)
- negative: No responses (no, nope, no thanks, etc.)
- cancel: Cancel responses (cancel, never mind, forget it, etc.)
- done: Done responses (that's all, nothing else, etc.)

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.

Usage:
------
    # List all affirmative patterns
    GET /admin/response-patterns?pattern_type=affirmative

    # Create a new pattern
    POST /admin/response-patterns
    {
        "pattern_type": "affirmative",
        "pattern": "you bet"
    }
"""

import logging

from fastapi import Depends
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import ResponsePattern
from ..exceptions import ValidationError
from ..schemas.response_patterns import (
    ResponsePatternOut,
    ResponsePatternCreate,
    ResponsePatternUpdate,
    ResponsePatternTypeStats,
)
from .crud_factory import CRUDRouterFactory

logger = logging.getLogger(__name__)

# Valid pattern types
VALID_PATTERN_TYPES = {"affirmative", "negative", "cancel", "done"}


def _validate_pattern_type(pattern_type: str) -> None:
    """Raise ValidationError if pattern_type is not in the allowed set."""
    if pattern_type not in VALID_PATTERN_TYPES:
        raise ValidationError(
            f"Invalid pattern_type. Must be one of: {', '.join(sorted(VALID_PATTERN_TYPES))}"
        )


def _check_composite_unique(
    db: Session,
    pattern_type: str,
    pattern: str,
    exclude_id: int | None = None,
) -> None:
    """Raise ValidationError if (pattern_type, pattern) already exists."""
    query = db.query(ResponsePattern).filter(
        ResponsePattern.pattern_type == pattern_type,
        ResponsePattern.pattern == pattern,
    )
    if exclude_id is not None:
        query = query.filter(ResponsePattern.id != exclude_id)
    if query.first():
        raise ValidationError(
            f"Pattern '{pattern}' already exists for type '{pattern_type}'"
        )


def _on_before_create(payload: ResponsePatternCreate, db: Session) -> dict:
    """Validate and normalize before creating a response pattern."""
    _validate_pattern_type(payload.pattern_type)
    normalized_pattern = payload.pattern.lower().strip()
    _check_composite_unique(db, payload.pattern_type, normalized_pattern)
    return {
        "pattern_type": payload.pattern_type,
        "pattern": normalized_pattern,
    }


def _on_before_update(
    item: ResponsePattern,
    payload: ResponsePatternUpdate,
    db: Session,
) -> None:
    """Validate and normalize before updating a response pattern."""
    if payload.pattern_type is not None:
        _validate_pattern_type(payload.pattern_type)

    new_pattern = payload.pattern.lower().strip() if payload.pattern else item.pattern
    new_type = payload.pattern_type if payload.pattern_type else item.pattern_type

    if new_pattern != item.pattern or new_type != item.pattern_type:
        _check_composite_unique(db, new_type, new_pattern, exclude_id=item.id)

    if payload.pattern_type is not None:
        item.pattern_type = payload.pattern_type
    if payload.pattern is not None:
        item.pattern = new_pattern


_crud = CRUDRouterFactory(
    model=ResponsePattern,
    create_schema=ResponsePatternCreate,
    update_schema=ResponsePatternUpdate,
    response_schema=ResponsePatternOut,
    prefix="/admin/response-patterns",
    tags=["Admin - Response Patterns"],
    not_found_message="Response pattern not found",
    order_by=["pattern_type", "pattern"],
    on_before_create=_on_before_create,
    on_before_update=_on_before_update,
)

admin_response_patterns_router = _crud.router


# =============================================================================
# Custom Endpoints (not covered by CRUD factory)
# =============================================================================

@admin_response_patterns_router.get("/stats", response_model=list[ResponsePatternTypeStats])
def get_response_pattern_stats(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> list[ResponsePatternTypeStats]:
    """Get pattern counts and examples for each type."""
    result = []

    for pattern_type in sorted(VALID_PATTERN_TYPES):
        patterns = (
            db.query(ResponsePattern)
            .filter(ResponsePattern.pattern_type == pattern_type)
            .order_by(ResponsePattern.pattern)
            .all()
        )
        result.append(ResponsePatternTypeStats(
            pattern_type=pattern_type,
            count=len(patterns),
            patterns=[p.pattern for p in patterns],
        ))

    return result
