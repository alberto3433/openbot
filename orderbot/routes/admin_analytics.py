"""
Admin Analytics Routes for Orderbot
========================================

This module contains admin endpoints for viewing session analytics and
business metrics. Analytics track both completed orders and abandoned
sessions to help understand customer behavior.

Endpoints:
----------
- GET /admin/analytics/sessions: List session records with pagination
- GET /admin/analytics/summary: Get aggregated analytics summary

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.

Session Analytics:
------------------
Every chat session is tracked with:
- Status (completed or abandoned)
- Message count and duration
- Cart state at end (items, value)
- Conversation history (for analysis)
- Abandonment reason (if applicable)

Summary Metrics:
----------------
The summary endpoint provides:
- Total sessions count
- Completion rate percentage
- Revenue from completed orders
- Lost revenue from abandoned carts
- Breakdown by abandonment reason
- 7-day trend data

Use Cases:
----------
1. Identify friction points in the ordering flow
2. Track conversion rates over time
3. Analyze abandoned carts for improvement opportunities
4. Compare performance across stores

Privacy Notes:
--------------
Session data may contain customer information. Access is restricted
to authenticated admins. Consider data retention policies.

Usage:
------
    # Get analytics summary
    GET /admin/analytics/summary

    # List abandoned sessions with items
    GET /admin/analytics/sessions?status=abandoned&page=1&page_size=50
"""

import logging
from datetime import datetime, timedelta

from ..utils.datetime_helpers import utc_now
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, case, func
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import SessionAnalytics
from ..schemas.analytics import (
    SessionAnalyticsOut,
    SessionAnalyticsListResponse,
    AnalyticsSummary,
)


logger = logging.getLogger(__name__)

# Router definition
admin_analytics_router = APIRouter(
    prefix="/admin/analytics",
    tags=["Admin - Analytics"]
)


# =============================================================================
# Analytics Endpoints
# =============================================================================

@admin_analytics_router.get("/sessions", response_model=SessionAnalyticsListResponse)
def list_sessions(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    status: str | None = Query(None, description="Filter: completed, abandoned"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> SessionAnalyticsListResponse:
    """
    List session analytics records with pagination.

    Can filter by status (completed/abandoned) and paginate results.
    Sessions are sorted by end time (newest first).
    """
    query = db.query(SessionAnalytics)

    if status in ("completed", "abandoned"):
        query = query.filter(SessionAnalytics.status == status)

    total = query.count()
    offset = (page - 1) * page_size

    sessions = (
        query.order_by(SessionAnalytics.ended_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    items = []
    for s in sessions:
        ended_at_str = s.ended_at.isoformat().replace("+00:00", "Z") if s.ended_at else ""
        items.append(SessionAnalyticsOut(
            id=s.id,
            session_id=s.session_id,
            status=s.status,
            message_count=s.message_count,
            had_items_in_cart=s.had_items_in_cart,
            item_count=s.item_count,
            cart_total=s.cart_total,
            order_status=s.order_status,
            conversation_history=s.conversation_history,
            last_bot_message=s.last_bot_message,
            last_user_message=s.last_user_message,
            reason=s.reason,
            session_duration_seconds=s.session_duration_seconds,
            customer_name=s.customer_name,
            customer_phone=s.customer_phone,
            store_id=s.store_id,
            ended_at=ended_at_str,
        ))

    has_next = offset + len(items) < total

    return SessionAnalyticsListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        has_next=has_next,
    )


@admin_analytics_router.get("/summary", response_model=AnalyticsSummary)
def get_summary(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    days: int = Query(30, ge=1, le=365, description="Days to include"),
) -> AnalyticsSummary:
    """
    Get aggregated analytics summary.

    Returns high-level metrics including completion rates, revenue,
    abandonment breakdown, and recent trends.
    """
    cutoff = utc_now() - timedelta(days=days)

    # Single query for all summary metrics (replaces 7 separate queries)
    summary_row = db.query(
        func.count(SessionAnalytics.id).label("total"),
        func.count(case(
            (SessionAnalytics.status == "completed", SessionAnalytics.id),
        )).label("completed"),
        func.count(case(
            (SessionAnalytics.status == "abandoned", SessionAnalytics.id),
        )).label("abandoned"),
        func.count(case(
            (and_(
                SessionAnalytics.status == "abandoned",
                SessionAnalytics.had_items_in_cart == True,
            ), SessionAnalytics.id),
        )).label("abandoned_with_items"),
        func.coalesce(func.sum(case(
            (SessionAnalytics.status == "completed", SessionAnalytics.cart_total),
            else_=0,
        )), 0).label("revenue"),
        func.coalesce(func.sum(case(
            (and_(
                SessionAnalytics.status == "abandoned",
                SessionAnalytics.had_items_in_cart == True,
            ), SessionAnalytics.cart_total),
            else_=0,
        )), 0).label("lost_revenue"),
        func.avg(SessionAnalytics.session_duration_seconds).label("avg_duration"),
    ).filter(
        SessionAnalytics.ended_at >= cutoff,
    ).first()

    total_sessions = summary_row.total
    completed_sessions = summary_row.completed
    abandoned_sessions = summary_row.abandoned
    abandoned_with_items = summary_row.abandoned_with_items
    total_revenue = float(summary_row.revenue)
    total_lost_revenue = float(summary_row.lost_revenue)
    avg_duration = summary_row.avg_duration

    completion_rate = (completed_sessions / total_sessions * 100) if total_sessions > 0 else 0.0

    # Abandonment by reason (already a single GROUP BY query — no change needed)
    reason_counts = db.query(
        SessionAnalytics.reason,
        func.count(SessionAnalytics.id),
    ).filter(
        SessionAnalytics.ended_at >= cutoff,
        SessionAnalytics.status == "abandoned",
    ).group_by(SessionAnalytics.reason).all()

    abandonment_by_reason: dict[str, int] = {
        reason or "unknown": count for reason, count in reason_counts
    }

    # 7-day trend: single GROUP BY query (replaces 14 per-day COUNT queries)
    seven_days_ago = datetime.combine(
        utc_now().date() - timedelta(days=6), datetime.min.time(),
    )
    trend_rows = db.query(
        func.date(SessionAnalytics.ended_at).label("day"),
        SessionAnalytics.status,
        func.count(SessionAnalytics.id).label("cnt"),
    ).filter(
        SessionAnalytics.ended_at >= seven_days_ago,
    ).group_by(
        func.date(SessionAnalytics.ended_at),
        SessionAnalytics.status,
    ).all()

    # Build lookup from query results, fill missing days with zeros
    trend_lookup: dict[str, dict[str, int]] = {}
    for row in trend_rows:
        day_str = row.day.isoformat() if hasattr(row.day, "isoformat") else str(row.day)
        if day_str not in trend_lookup:
            trend_lookup[day_str] = {"completed": 0, "abandoned": 0}
        if row.status in ("completed", "abandoned"):
            trend_lookup[day_str][row.status] = row.cnt

    recent_trend: list[dict[str, Any]] = []
    for i in range(6, -1, -1):
        day = utc_now().date() - timedelta(days=i)
        day_str = day.isoformat()
        counts = trend_lookup.get(day_str, {"completed": 0, "abandoned": 0})
        recent_trend.append({
            "date": day_str,
            "completed": counts["completed"],
            "abandoned": counts["abandoned"],
        })

    return AnalyticsSummary(
        total_sessions=total_sessions,
        completed_sessions=completed_sessions,
        abandoned_sessions=abandoned_sessions,
        abandoned_with_items=abandoned_with_items,
        total_revenue=total_revenue,
        total_lost_revenue=total_lost_revenue,
        avg_session_duration=float(avg_duration) if avg_duration else None,
        completion_rate=round(completion_rate, 1),
        abandonment_by_reason=abandonment_by_reason,
        recent_trend=recent_trend,
    )
