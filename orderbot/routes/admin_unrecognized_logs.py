"""
Admin Unrecognized Menu Item Logs Routes
=========================================

Endpoints for viewing and managing unrecognized item log entries (analytics).

Endpoints:
----------
- GET /admin/unrecognized-logs: List unrecognized item logs
- GET /admin/unrecognized-logs/stats: Get log statistics
- DELETE /admin/unrecognized-logs/clear: Clear old logs

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
from ..db.models import UnrecognizedMenuItemLog
from ..schemas.unrecognized_suggestions import (
    UnrecognizedMenuItemLogEntry,
    UnrecognizedMenuItemLogStats,
)

logger = logging.getLogger(__name__)


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
