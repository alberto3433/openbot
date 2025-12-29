"""
Admin Analytics Routes for Sandwich Bot
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
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..models import SessionAnalytics
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
    status: Optional[str] = Query(None, description="Filter: completed, abandoned"),
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
        ended_at_str = s.ended_at.isoformat() + "Z" if s.ended_at else ""
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
    cutoff = datetime.utcnow() - timedelta(days=days)

    # Base query for the time period
    query = db.query(SessionAnalytics).filter(SessionAnalytics.ended_at >= cutoff)

    # Counts by status
    total_sessions = query.count()
    completed_sessions = query.filter(SessionAnalytics.status == "completed").count()
    abandoned_sessions = query.filter(SessionAnalytics.status == "abandoned").count()
    abandoned_with_items = query.filter(
        SessionAnalytics.status == "abandoned",
        SessionAnalytics.had_items_in_cart == True
    ).count()

    # Revenue calculations
    completed_query = query.filter(SessionAnalytics.status == "completed")
    total_revenue = db.query(func.sum(SessionAnalytics.cart_total)).filter(
        SessionAnalytics.ended_at >= cutoff,
        SessionAnalytics.status == "completed"
    ).scalar() or 0.0

    total_lost_revenue = db.query(func.sum(SessionAnalytics.cart_total)).filter(
        SessionAnalytics.ended_at >= cutoff,
        SessionAnalytics.status == "abandoned",
        SessionAnalytics.had_items_in_cart == True
    ).scalar() or 0.0

    # Average session duration
    avg_duration = db.query(func.avg(SessionAnalytics.session_duration_seconds)).filter(
        SessionAnalytics.ended_at >= cutoff,
        SessionAnalytics.session_duration_seconds.isnot(None)
    ).scalar()

    # Completion rate
    completion_rate = (completed_sessions / total_sessions * 100) if total_sessions > 0 else 0.0

    # Abandonment by reason
    reason_counts = db.query(
        SessionAnalytics.reason,
        func.count(SessionAnalytics.id)
    ).filter(
        SessionAnalytics.ended_at >= cutoff,
        SessionAnalytics.status == "abandoned"
    ).group_by(SessionAnalytics.reason).all()

    abandonment_by_reason: Dict[str, int] = {
        reason or "unknown": count for reason, count in reason_counts
    }

    # Recent trend (last 7 days)
    recent_trend: List[Dict[str, Any]] = []
    for i in range(6, -1, -1):
        day = datetime.utcnow().date() - timedelta(days=i)
        day_start = datetime.combine(day, datetime.min.time())
        day_end = datetime.combine(day, datetime.max.time())

        completed = db.query(SessionAnalytics).filter(
            SessionAnalytics.ended_at >= day_start,
            SessionAnalytics.ended_at <= day_end,
            SessionAnalytics.status == "completed"
        ).count()

        abandoned = db.query(SessionAnalytics).filter(
            SessionAnalytics.ended_at >= day_start,
            SessionAnalytics.ended_at <= day_end,
            SessionAnalytics.status == "abandoned"
        ).count()

        recent_trend.append({
            "date": day.isoformat(),
            "completed": completed,
            "abandoned": abandoned,
        })

    return AnalyticsSummary(
        total_sessions=total_sessions,
        completed_sessions=completed_sessions,
        abandoned_sessions=abandoned_sessions,
        abandoned_with_items=abandoned_with_items,
        total_revenue=float(total_revenue),
        total_lost_revenue=float(total_lost_revenue),
        avg_session_duration=float(avg_duration) if avg_duration else None,
        completion_rate=round(completion_rate, 1),
        abandonment_by_reason=abandonment_by_reason,
        recent_trend=recent_trend,
    )
