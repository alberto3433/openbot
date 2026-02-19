"""Menu display group and overall category models."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from .base import Base


class MenuDisplayGroup(Base):
    """Groups item types for user-friendly menu display.

    When user asks "what's on your menu?", show these 7 groups instead of 25+ item types.
    Examples: Breads, Sandwiches, Omelettes and Breakfasts, Drinks, etc.

    The overall_category determines modifier extraction rules for all item types in this group:
    - Food groups use food modifiers (proteins, cheeses, toppings)
    - Beverage groups use beverage modifiers (milk, sweetener, syrup)

    Aliases enable users to reference display groups by various names:
    - "desserts_pastries" group has aliases ["pastries", "pastry", "desserts", "dessert", "sweets"]
    - When user says "pastries", we show items from this display group
    """
    __tablename__ = "menu_display_groups"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(50), unique=True, nullable=False, index=True)
    display_name = Column(String(100), nullable=False)
    display_order = Column(Integer, nullable=False, default=0)

    # Parent-child hierarchy: enables "candy bars are snacks" relationships
    parent_id = Column(Integer, ForeignKey("menu_display_groups.id", ondelete="SET NULL"), nullable=True, index=True)
    parent = relationship("MenuDisplayGroup", remote_side=[id], backref="children")

    # Overall category: "food" or "beverage" - determines modifier extraction rules
    overall_category_id = Column(Integer, ForeignKey("overall_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    overall_category = relationship("OverallCategory", back_populates="menu_display_groups")

    # Relationships
    item_types = relationship("ItemType", back_populates="menu_display_group")
    alias_records = relationship("MenuDisplayGroupAlias", back_populates="menu_display_group", cascade="all, delete-orphan")

    @property
    def aliases(self) -> list[str]:
        """Get list of aliases from child table."""
        return [a.alias for a in self.alias_records]


class MenuDisplayGroupAlias(Base):
    """Child table for menu display group aliases. Aliases are globally unique.

    When user says a display group alias (like "pastries"), we show items from
    all item types in that display group.
    """
    __tablename__ = "menu_display_group_aliases"

    id = Column(Integer, primary_key=True, index=True)
    menu_display_group_id = Column(Integer, ForeignKey("menu_display_groups.id", ondelete="CASCADE"), nullable=False, index=True)
    alias = Column(String(100), nullable=False, unique=True)  # Globally unique
    created_at = Column(DateTime, server_default=func.now())

    menu_display_group = relationship("MenuDisplayGroup", back_populates="alias_records")


class OverallCategory(Base):
    """
    Defines a category for menu display groups (e.g., "food" vs "beverage").

    This determines which modifier extraction rules apply to items in a display group.
    Food groups use food modifiers (proteins, cheeses, toppings).
    Beverage groups use beverage modifiers (milk, sweetener, syrup).

    Also governs ingredient classification via IngredientCategory.modifier_type.
    """
    __tablename__ = "overall_categories"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(50), unique=True, nullable=False, index=True)  # "food", "beverage"
    display_name = Column(String(100), nullable=False)  # "Food", "Beverage"

    # Relationships
    menu_display_groups = relationship("MenuDisplayGroup", back_populates="overall_category")
