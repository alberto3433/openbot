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
from datetime import timedelta

from ..utils.datetime_helpers import utc_now

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
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
    cutoff = utc_now() - timedelta(days=days)
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
    cutoff = utc_now() - timedelta(days=days)

    Log = UnrecognizedMenuItemLog
    date_filter = Log.created_at >= cutoff

    # Total count
    total = db.query(func.count(Log.id)).filter(date_filter).scalar()

    # Count by fallback level (1 query)
    fallback_rows = db.query(
        Log.fallback_level, func.count(Log.id),
    ).filter(date_filter).group_by(Log.fallback_level).all()
    by_fallback: dict[str, int] = dict(fallback_rows)

    # Count by inferred category (1 query)
    category_rows = db.query(
        func.coalesce(Log.inferred_category, "(none)"),
        func.count(Log.id),
    ).filter(date_filter).group_by(Log.inferred_category).all()
    by_category: dict[str, int] = dict(category_rows)

    # Top unrecognized inputs (1 query with LIMIT)
    top_rows = db.query(
        Log.normalized_input,
        func.count(Log.id).label("cnt"),
    ).filter(
        date_filter,
    ).group_by(
        Log.normalized_input,
    ).order_by(
        func.count(Log.id).desc(),
    ).limit(20).all()
    top_unrecognized = [{"input": row[0], "count": row[1]} for row in top_rows]

    # Recent entries (1 query with LIMIT)
    recent = db.query(Log).filter(
        date_filter,
    ).order_by(Log.created_at.desc()).limit(10).all()

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
    cutoff = utc_now() - timedelta(days=days)

    deleted = db.query(UnrecognizedMenuItemLog).filter(
        UnrecognizedMenuItemLog.created_at < cutoff
    ).delete()

    db.commit()

    logger.info("Cleared %d unrecognized item logs older than %d days", deleted, days)

    return {"deleted": deleted, "days_threshold": days}
