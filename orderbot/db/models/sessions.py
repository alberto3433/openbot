"""Session models.

Contains: ChatSession, SessionAnalytics.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    JSON,
    String,
    Text,
    func,
)

from .base import Base


class ChatSession(Base):
    """
    Persists chat sessions to the database so they survive server restarts.
    """
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, unique=True, nullable=False, index=True)  # UUID string

    # Store conversation history as JSON
    history = Column(JSON, nullable=False, default=list)

    # Store order state as JSON
    order_state = Column(JSON, nullable=False, default=dict)

    # Track which menu version was sent in system prompt (for token optimization)
    # If None, menu hasn't been sent yet; otherwise contains menu hash
    menu_version_sent = Column(String, nullable=True, default=None)

    # Store identifier for per-store availability (86 system)
    store_id = Column(String, nullable=True, index=True)

    # Caller ID for returning customer identification
    caller_id = Column(String, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SessionAnalytics(Base):
    """
    Tracks all sessions for analytics - both abandoned and completed.
    Used to analyze user behavior and identify UX issues.
    """
    __tablename__ = "session_analytics"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, nullable=False, index=True)  # UUID string from chat session

    # Session outcome
    status = Column(String, nullable=False, default="abandoned", index=True)  # 'abandoned' or 'completed'

    # Session state at end
    message_count = Column(Integer, nullable=False, default=0)  # How many messages exchanged
    had_items_in_cart = Column(Boolean, nullable=False, default=False)  # Were there items in cart?
    item_count = Column(Integer, nullable=False, default=0)  # Number of items in cart
    cart_total = Column(Float, nullable=False, default=0.0)  # Cart/order value
    order_status = Column(String, nullable=False, default="pending")  # pending, confirmed, etc.

    # Full conversation history (JSON array of {role, content} objects)
    conversation_history = Column(JSON, nullable=True, default=list)

    # Last interaction details (kept for backward compatibility and quick queries)
    last_bot_message = Column(Text, nullable=True)  # What was the bot's last message?
    last_user_message = Column(Text, nullable=True)  # What did user say last?

    # Session details
    reason = Column(String, nullable=True)  # For abandoned: browser_close, refresh, navigation. For completed: null
    session_duration_seconds = Column(Integer, nullable=True)  # How long was the session?

    # Customer info (for completed orders)
    customer_name = Column(String, nullable=True)
    customer_phone = Column(String, nullable=True)

    # Store info
    store_id = Column(String, nullable=True, index=True)  # Store identifier (e.g., "store_eb_001")

    # Timestamp
    ended_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
