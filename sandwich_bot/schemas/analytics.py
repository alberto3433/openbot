"""
Analytics Schemas for Sandwich Bot
===================================

This module defines Pydantic models for session analytics and reporting.
Analytics track both completed orders and abandoned sessions to help
understand customer behavior and improve the ordering experience.

Endpoint Coverage:
------------------
- GET /admin/analytics/sessions: List session records with pagination
- GET /admin/analytics/summary: Get aggregated analytics summary

Analytics Goals:
----------------
1. **Understand Abandonment**: Track when and why customers abandon orders
   to identify friction points in the ordering flow.

2. **Measure Success**: Track completion rates, average order values, and
   revenue to measure business performance.

3. **Identify Patterns**: Analyze conversation histories to find common
   issues, popular items, and improvement opportunities.

4. **Per-Store Insights**: Compare performance across locations to identify
   best practices and struggling stores.

Session Types:
--------------
- **Completed**: Customer finished and confirmed their order
- **Abandoned**: Customer left without completing (browser close, timeout, etc.)

Abandonment Reasons:
--------------------
- browser_close: User closed the browser/tab
- refresh: User refreshed the page
- navigation: User navigated away
- timeout: Session timed out due to inactivity

Metrics Tracked:
----------------
- Session duration
- Message count (conversation length)
- Cart state at abandonment (items, total value)
- Last messages exchanged
- Full conversation history (for analysis)

Privacy Considerations:
-----------------------
Conversation histories may contain customer information. Ensure proper
access controls on analytics endpoints and consider data retention policies.

Usage:
------
    # Get summary stats
    summary = AnalyticsSummary(
        total_sessions=1000,
        completed_sessions=750,
        abandoned_sessions=250,
        completion_rate=75.0,
        ...
    )

    # Page through session records
    sessions = SessionAnalyticsListResponse(
        items=[...],
        page=1,
        page_size=50,
        total=250,
        has_next=True
    )
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class SessionAnalyticsOut(BaseModel):
    """
    Response model for a single session analytics record.

    Contains detailed information about a chat session, whether it
    resulted in a completed order or was abandoned.

    Attributes:
        id: Database primary key
        session_id: UUID of the chat session
        status: "completed" or "abandoned"
        message_count: Total messages in conversation
        had_items_in_cart: Whether cart had items at end
        item_count: Number of items in cart
        cart_total: Total value of cart
        order_status: Order status at session end
        conversation_history: Full conversation [{role, content}, ...]
        last_bot_message: Last message from bot (truncated)
        last_user_message: Last message from user (truncated)
        reason: Abandonment reason (null for completed sessions)
        session_duration_seconds: How long session was active
        customer_name: Customer name (for completed orders)
        customer_phone: Customer phone (for completed orders)
        store_id: Which store location
        ended_at: ISO timestamp when session ended
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    status: str
    message_count: int
    had_items_in_cart: bool
    item_count: int
    cart_total: float
    order_status: str
    conversation_history: Optional[List[Dict[str, str]]] = None
    last_bot_message: Optional[str] = None
    last_user_message: Optional[str] = None
    reason: Optional[str] = None
    session_duration_seconds: Optional[int] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    store_id: Optional[str] = None
    ended_at: str


class SessionAnalyticsListResponse(BaseModel):
    """
    Paginated response for session analytics listing.

    Wraps session records with pagination metadata for efficient
    navigation through analytics data.

    Attributes:
        items: List of session records for current page
        page: Current page number (1-indexed)
        page_size: Number of items per page
        total: Total matching records
        has_next: Whether more pages exist
    """
    items: List[SessionAnalyticsOut]
    page: int
    page_size: int
    total: int
    has_next: bool


class AnalyticsSummary(BaseModel):
    """
    Aggregated analytics summary.

    Provides high-level metrics about session performance over a
    time period. Used for dashboard displays and reporting.

    Attributes:
        total_sessions: Total number of sessions
        completed_sessions: Sessions that resulted in orders
        abandoned_sessions: Sessions that were abandoned
        abandoned_with_items: Abandoned sessions that had items in cart
        total_revenue: Sum of completed order totals
        total_lost_revenue: Sum of abandoned cart totals
        avg_session_duration: Average session length in seconds
        completion_rate: Percentage of sessions that completed (0-100)
        abandonment_by_reason: Count of abandonments by reason
        recent_trend: Daily counts for trend visualization

    Example abandonment_by_reason:
        {
            "browser_close": 150,
            "refresh": 45,
            "navigation": 30,
            "timeout": 25
        }

    Example recent_trend (last 7 days):
        [
            {"date": "2024-01-15", "completed": 50, "abandoned": 12},
            {"date": "2024-01-16", "completed": 48, "abandoned": 15},
            ...
        ]
    """
    total_sessions: int
    completed_sessions: int
    abandoned_sessions: int
    abandoned_with_items: int
    total_revenue: float
    total_lost_revenue: float
    avg_session_duration: Optional[float] = None
    completion_rate: float
    abandonment_by_reason: Dict[str, int]
    recent_trend: List[Dict[str, Any]]
