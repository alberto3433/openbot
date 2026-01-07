"""
Admin Response Patterns Routes for Sandwich Bot
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
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..models import ResponsePattern
from ..schemas.response_patterns import (
    ResponsePatternOut,
    ResponsePatternCreate,
    ResponsePatternUpdate,
    ResponsePatternTypeStats,
)

logger = logging.getLogger(__name__)

# Router definition
admin_response_patterns_router = APIRouter(
    prefix="/admin/response-patterns",
    tags=["Admin - Response Patterns"]
)

# Valid pattern types
VALID_PATTERN_TYPES = {"affirmative", "negative", "cancel", "done"}


@admin_response_patterns_router.get("", response_model=List[ResponsePatternOut])
def list_response_patterns(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    pattern_type: Optional[str] = Query(None, description="Filter by pattern type"),
) -> List[ResponsePatternOut]:
    """List all response patterns, optionally filtered by type."""
    query = db.query(ResponsePattern)

    if pattern_type:
        if pattern_type not in VALID_PATTERN_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid pattern_type. Must be one of: {', '.join(VALID_PATTERN_TYPES)}"
            )
        query = query.filter(ResponsePattern.pattern_type == pattern_type)

    patterns = query.order_by(ResponsePattern.pattern_type, ResponsePattern.pattern).all()

    return [
        ResponsePatternOut(
            id=p.id,
            pattern_type=p.pattern_type,
            pattern=p.pattern,
            created_at=p.created_at,
        )
        for p in patterns
    ]


@admin_response_patterns_router.get("/stats", response_model=List[ResponsePatternTypeStats])
def get_response_pattern_stats(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> List[ResponsePatternTypeStats]:
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


@admin_response_patterns_router.get("/{pattern_id}", response_model=ResponsePatternOut)
def get_response_pattern(
    pattern_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ResponsePatternOut:
    """Get a specific response pattern by ID."""
    pattern = db.query(ResponsePattern).filter(ResponsePattern.id == pattern_id).first()
    if not pattern:
        raise HTTPException(status_code=404, detail="Response pattern not found")

    return ResponsePatternOut(
        id=pattern.id,
        pattern_type=pattern.pattern_type,
        pattern=pattern.pattern,
        created_at=pattern.created_at,
    )


@admin_response_patterns_router.post("", response_model=ResponsePatternOut, status_code=201)
def create_response_pattern(
    payload: ResponsePatternCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ResponsePatternOut:
    """Create a new response pattern."""
    # Validate pattern type
    if payload.pattern_type not in VALID_PATTERN_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid pattern_type. Must be one of: {', '.join(VALID_PATTERN_TYPES)}"
        )

    # Normalize pattern to lowercase
    pattern_normalized = payload.pattern.lower().strip()

    # Check for duplicate
    existing = db.query(ResponsePattern).filter(
        ResponsePattern.pattern_type == payload.pattern_type,
        ResponsePattern.pattern == pattern_normalized
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Pattern '{pattern_normalized}' already exists for type '{payload.pattern_type}'"
        )

    pattern = ResponsePattern(
        pattern_type=payload.pattern_type,
        pattern=pattern_normalized,
    )
    db.add(pattern)
    db.commit()
    db.refresh(pattern)

    logger.info(
        "Created response pattern: '%s' (type=%s, id=%d)",
        pattern.pattern,
        pattern.pattern_type,
        pattern.id
    )

    return ResponsePatternOut(
        id=pattern.id,
        pattern_type=pattern.pattern_type,
        pattern=pattern.pattern,
        created_at=pattern.created_at,
    )


@admin_response_patterns_router.put("/{pattern_id}", response_model=ResponsePatternOut)
def update_response_pattern(
    pattern_id: int,
    payload: ResponsePatternUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ResponsePatternOut:
    """Update a response pattern."""
    pattern = db.query(ResponsePattern).filter(ResponsePattern.id == pattern_id).first()
    if not pattern:
        raise HTTPException(status_code=404, detail="Response pattern not found")

    # Validate pattern type if changing it
    if payload.pattern_type is not None:
        if payload.pattern_type not in VALID_PATTERN_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid pattern_type. Must be one of: {', '.join(VALID_PATTERN_TYPES)}"
            )

    # Normalize pattern if changing it
    new_pattern = payload.pattern.lower().strip() if payload.pattern else pattern.pattern
    new_type = payload.pattern_type if payload.pattern_type else pattern.pattern_type

    # Check for duplicate if changing pattern or type
    if new_pattern != pattern.pattern or new_type != pattern.pattern_type:
        existing = db.query(ResponsePattern).filter(
            ResponsePattern.pattern_type == new_type,
            ResponsePattern.pattern == new_pattern,
            ResponsePattern.id != pattern_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Pattern '{new_pattern}' already exists for type '{new_type}'"
            )

    if payload.pattern_type is not None:
        pattern.pattern_type = payload.pattern_type
    if payload.pattern is not None:
        pattern.pattern = new_pattern

    db.commit()
    db.refresh(pattern)

    logger.info("Updated response pattern: '%s' (type=%s, id=%d)",
                pattern.pattern, pattern.pattern_type, pattern.id)

    return ResponsePatternOut(
        id=pattern.id,
        pattern_type=pattern.pattern_type,
        pattern=pattern.pattern,
        created_at=pattern.created_at,
    )


@admin_response_patterns_router.delete("/{pattern_id}", status_code=204)
def delete_response_pattern(
    pattern_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete a response pattern."""
    pattern = db.query(ResponsePattern).filter(ResponsePattern.id == pattern_id).first()
    if not pattern:
        raise HTTPException(status_code=404, detail="Response pattern not found")

    logger.info(
        "Deleting response pattern: '%s' (type=%s, id=%d)",
        pattern.pattern,
        pattern.pattern_type,
        pattern.id
    )
    db.delete(pattern)
    db.commit()
    return None
