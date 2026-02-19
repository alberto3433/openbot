"""Analytics models for unrecognized item and ingredient tracking.

Contains: UnrecognizedMenuItemSuggestion, UnrecognizedMenuItemLog,
          UnrecognizedOptionSuggestion, UnrecognizedIngredientSuggestion.
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


# Junction table for many-to-many: menu item suggestions <-> menu items
unrecognized_menu_item_suggestion_items = Table(
    "unrecognized_menu_item_suggestion_items",
    Base.metadata,
    Column("suggestion_id", Integer, ForeignKey("unrecognized_menu_item_suggestions.id", ondelete="CASCADE"), primary_key=True),
    Column("menu_item_id", Integer, ForeignKey("menu_items.id", ondelete="CASCADE"), primary_key=True),
)


# Junction table for many-to-many: ingredient suggestions <-> ingredients
unrecognized_ingredient_suggestion_alternatives = Table(
    "unrecognized_ingredient_suggestion_alternatives",
    Base.metadata,
    Column("suggestion_id", Integer, ForeignKey("unrecognized_ingredient_suggestions.id", ondelete="CASCADE"), primary_key=True),
    Column("ingredient_id", Integer, ForeignKey("ingredients.id", ondelete="CASCADE"), primary_key=True),
)


class UnrecognizedMenuItemSuggestion(Base):
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
    __tablename__ = "unrecognized_menu_item_suggestions"

    id = Column(Integer, primary_key=True, index=True)
    input_pattern = Column(String(200), nullable=False, index=True)
    match_type = Column(String(20), nullable=False, default="exact")
    suggested_item_type_id = Column(Integer, ForeignKey("item_types.id", ondelete="SET NULL"), nullable=True, index=True)
    hit_count = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    suggested_item_type = relationship("ItemType", lazy="joined")
    suggested_menu_items = relationship("MenuItem", secondary=unrecognized_menu_item_suggestion_items, lazy="joined")


class UnrecognizedMenuItemLog(Base):
    """
    Analytics log for unrecognized item requests.

    Tracks what users ask for that isn't found, which fallback
    was used, and whether a category was inferred. Used to
    identify common requests that should be added to the menu
    or suggestion table.
    """
    __tablename__ = "unrecognized_menu_item_log"

    id = Column(Integer, primary_key=True, index=True)
    user_input = Column(String(500), nullable=False)
    normalized_input = Column(String(200), nullable=False, index=True)
    session_id = Column(String(100), nullable=True)
    order_item_count = Column(Integer, nullable=False, default=0)
    fallback_level = Column(String(20), nullable=False, index=True)  # curated, fuzzy, llm, generic
    inferred_category = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class UnrecognizedOptionSuggestion(Base):
    """
    Curated suggestions for unrecognized attribute option requests.

    When users ask for options not on the menu (e.g., "venti" size),
    this table stores common terms to detect and respond appropriately.
    """
    __tablename__ = "unrecognized_option_suggestions"

    id = Column(Integer, primary_key=True, index=True)
    input_pattern = Column(String(100), nullable=False, index=True)  # "venti"
    attribute_slug = Column(String(50), nullable=False, index=True)  # "size"
    suggested_display_name = Column(String(100), nullable=False)     # "Venti"
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UnrecognizedIngredientSuggestion(Base):
    """
    Curated suggestions for unrecognized ingredient requests.

    When users ask for ingredients not on the menu (e.g., "honey"),
    this table stores the pattern to detect and links to alternative
    ingredients we actually carry.
    """
    __tablename__ = "unrecognized_ingredient_suggestions"

    id = Column(Integer, primary_key=True, index=True)
    input_pattern = Column(String(100), nullable=False, index=True)
    match_type = Column(String(20), nullable=False, default="exact")
    suggested_display_name = Column(String(100), nullable=False)
    modifier_category = Column(String(50), nullable=True)
    hit_count = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Many-to-many: alternative ingredients we actually carry
    alternative_ingredients = relationship(
        "Ingredient",
        secondary=unrecognized_ingredient_suggestion_alternatives,
        lazy="joined",
    )
