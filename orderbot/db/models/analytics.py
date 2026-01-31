"""Analytics models for unrecognized item tracking.

Contains: UnrecognizedItemSuggestion, UnrecognizedItemLog.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    func,
)
from sqlalchemy.orm import relationship

from .base import Base


# Junction table for many-to-many relationship between suggestions and menu items
unrecognized_suggestion_menu_items = Table(
    "unrecognized_suggestion_menu_items",
    Base.metadata,
    Column("suggestion_id", Integer, ForeignKey("unrecognized_item_suggestions.id", ondelete="CASCADE"), primary_key=True),
    Column("menu_item_id", Integer, ForeignKey("menu_items.id", ondelete="CASCADE"), primary_key=True),
)


class UnrecognizedItemSuggestion(Base):
    """
    Curated suggestions for unrecognized menu item requests.

    When users ask for items not on the menu, this table provides
    data-driven responses that suggest appropriate menu categories
    or specific items.

    Match types:
    - 'exact': input_pattern must exactly match (case-insensitive)
    - 'prefix': input must start with pattern
    - 'contains': input must contain pattern
    """
    __tablename__ = "unrecognized_item_suggestions"

    id = Column(Integer, primary_key=True, index=True)
    input_pattern = Column(String(200), nullable=False, index=True)
    match_type = Column(String(20), nullable=False, default="exact")
    suggested_item_type_id = Column(Integer, ForeignKey("item_types.id", ondelete="SET NULL"), nullable=True, index=True)
    hit_count = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    suggested_item_type = relationship("ItemType", lazy="joined")
    suggested_menu_items = relationship("MenuItem", secondary=unrecognized_suggestion_menu_items, lazy="joined")


class UnrecognizedItemLog(Base):
    """
    Analytics log for unrecognized item requests.

    Tracks what users ask for that isn't found, which fallback
    was used, and whether a category was inferred. Used to
    identify common requests that should be added to the menu
    or suggestion table.
    """
    __tablename__ = "unrecognized_item_log"

    id = Column(Integer, primary_key=True, index=True)
    user_input = Column(String(500), nullable=False)
    normalized_input = Column(String(200), nullable=False, index=True)
    session_id = Column(String(100), nullable=True)
    order_item_count = Column(Integer, nullable=False, default=0)
    fallback_level = Column(String(20), nullable=False, index=True)  # curated, fuzzy, llm, generic
    inferred_category = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
