"""Menu item models.

Contains: MenuItem, MenuItemAlias, Category, MenuItemCategory,
MenuItemIngredient, MenuItemStoreAvailability.
"""

import logging
import os
import traceback

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.orm import relationship

from .base import Base


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    description = Column(Text, nullable=True)  # Item description (e.g., "Two Eggs, Bacon, and Cheddar")
    # Note: category column removed - use category_records relationship (MenuItemCategory join table)
    # or item_type.display_name for display purposes
    is_signature = Column(Boolean, default=False, nullable=False)
    # Note: base_price column removed - use menu_item_size_prices instead
    available_qty = Column(Integer, default=0, nullable=False)

    # Note: extra_metadata column removed - default ingredients now stored
    # in menu_item_ingredients junction table (via ingredient_links relationship)

    # Link to generic item type system (optional - for migration compatibility)
    item_type_id = Column(Integer, ForeignKey("item_types.id"), nullable=True, index=True)
    item_type = relationship("ItemType", back_populates="menu_items")

    # Required match phrases for search filtering (comma-separated)
    # If set, user input must contain at least ONE of these phrases for a match
    # Example: "coffee cake, cake" for "Russian Coffee Cake" prevents "coffee" from matching
    required_match_phrases = Column(String, nullable=True)

    # Abbreviation for text expansion (e.g., "oj" expands to "orange juice" before parsing)
    abbreviation = Column(String, nullable=True)

    # Unit of sale: how this item is sold
    # - 'each' (default): sold individually (bagels, sandwiches, drinks)
    # - 'by_weight': sold by weight (cream cheese by the lb, smoked fish)
    # - 'dozen': sold by the dozen (bagel packages)
    unit_type = Column(String(20), nullable=False, default="each")

    # Dietary attributes (computed/cached from ingredients - NULL = not computed)
    # For "is_X" flags: True only if ALL ingredients qualify
    # For "contains_X" flags: True if ANY ingredient contains the allergen
    is_vegan = Column(Boolean, nullable=True)
    is_vegetarian = Column(Boolean, nullable=True)
    is_gluten_free = Column(Boolean, nullable=True)
    is_dairy_free = Column(Boolean, nullable=True)
    is_kosher = Column(Boolean, nullable=True)

    # Allergen attributes
    contains_eggs = Column(Boolean, nullable=True)
    contains_fish = Column(Boolean, nullable=True)
    contains_sesame = Column(Boolean, nullable=True)
    contains_nuts = Column(Boolean, nullable=True)

    order_items = relationship(
        "OrderItem",
        back_populates="menu_item",
        cascade="all, delete-orphan",
    )
    store_availability = relationship("MenuItemStoreAvailability", back_populates="menu_item")
    alias_records = relationship("MenuItemAlias", back_populates="menu_item")
    category_records = relationship("MenuItemCategory", back_populates="menu_item")
    ingredient_links = relationship("MenuItemIngredient", back_populates="menu_item")

    # Size-based pricing (variant pricing)
    size_category_id = Column(Integer, ForeignKey("menu_item_size_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    size_category = relationship("MenuItemSizeCategory", back_populates="menu_items")
    size_prices = relationship("MenuItemSizePrice", back_populates="menu_item")

    @property
    def aliases(self) -> list[str]:
        """Get list of aliases from child table."""
        return [a.alias for a in self.alias_records]

    @property
    def categories(self) -> list[str]:
        """Get list of category slugs from child table."""
        return [c.category.slug for c in self.category_records]

    @property
    def category_names(self) -> list[str]:
        """Get list of category display names from child table."""
        return [c.category.name for c in self.category_records]

    @property
    def base_price(self) -> float:
        """Computed base price from size_prices (minimum price).

        This property provides backward compatibility after removing the
        base_price column. Returns the minimum price from size_prices or 0.0
        if no prices are defined.
        """
        if self.size_prices:
            return min(sp.price for sp in self.size_prices)
        return 0.0


class MenuItemAlias(Base):
    """Child table for menu item aliases. Aliases are globally unique."""
    __tablename__ = "menu_item_aliases"

    id = Column(Integer, primary_key=True, index=True)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id", ondelete="RESTRICT"), nullable=False, index=True)
    alias = Column(String(100), nullable=False, unique=True)  # Globally unique
    created_at = Column(DateTime, server_default=func.now())

    menu_item = relationship("MenuItem", back_populates="alias_records")


class Category(Base):
    """Predefined categories for menu items (e.g., 'drink', 'food')."""
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, unique=True)  # Display name: "Drink", "Food"
    slug = Column(String(50), nullable=False, unique=True, index=True)  # Lowercase identifier: "drink", "food"
    description = Column(String(200), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    # Relationship to menu items via join table
    menu_item_categories = relationship("MenuItemCategory", back_populates="category")

    @property
    def menu_items(self) -> list:
        """Get all menu items in this category."""
        return [mic.menu_item for mic in self.menu_item_categories]


class MenuItemCategory(Base):
    """Join table linking menu items to categories (many-to-many)."""
    __tablename__ = "menu_item_categories"

    id = Column(Integer, primary_key=True, index=True)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id", ondelete="RESTRICT"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())

    # Unique constraint: a menu item can only be in a category once
    __table_args__ = (
        UniqueConstraint("menu_item_id", "category_id", name="uix_menu_item_category"),
    )

    menu_item = relationship("MenuItem", back_populates="category_records")
    category = relationship("Category", back_populates="menu_item_categories")


class MenuItemIngredient(Base):
    """
    Junction table linking menu items to their default ingredients.

    This replaces the JSON-based approach of storing ingredients in
    extra_metadata.default_config with proper relational integrity.

    Benefits:
    - FK constraints ensure valid ingredient references
    - Accurate ingredient-based search (no text matching)
    - Easier to update and query ingredient associations
    """
    __tablename__ = "menu_item_ingredients"

    id = Column(Integer, primary_key=True, index=True)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id", ondelete="RESTRICT"), nullable=False)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id", ondelete="RESTRICT"), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    # Optional preparation modifier (e.g., "fried" for eggs, "grilled" for chicken)
    # References global_attribute_options for preparation styles
    preparation_option_id = Column(
        Integer,
        ForeignKey("global_attribute_options.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("menu_item_id", "ingredient_id", name="uq_menu_item_ingredient"),
        Index("idx_menu_item_ingredients_menu_item", "menu_item_id"),
        Index("idx_menu_item_ingredients_ingredient", "ingredient_id"),
    )

    # Relationships
    menu_item = relationship("MenuItem", back_populates="ingredient_links")
    ingredient = relationship("Ingredient", back_populates="menu_item_links")
    preparation_option = relationship("GlobalAttributeOption")


class MenuItemStoreAvailability(Base):
    """Tracks menu item availability per store. If no entry exists for a store+item, assume available."""
    __tablename__ = "menu_item_store_availability"

    id = Column(Integer, primary_key=True, index=True)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id", ondelete="RESTRICT"), nullable=False)
    store_id = Column(String, nullable=False, index=True)
    is_available = Column(Boolean, nullable=False, default=True)

    # Unique constraint: one entry per menu item per store
    __table_args__ = (
        UniqueConstraint("menu_item_id", "store_id", name="uix_menu_item_store"),
    )

    # relationships
    menu_item = relationship("MenuItem", back_populates="store_availability")


# --- MenuItem Insert Logging (for debugging duplicate inserts) ---
# Enable with environment variable: MENU_ITEM_INSERT_LOGGING=1

_menu_item_insert_logger = logging.getLogger("menu_item_inserts")


@event.listens_for(MenuItem, "before_insert")
def log_menu_item_insert(mapper, connection, target):
    """Log MenuItem inserts with stack trace to help identify duplicate sources."""
    if not os.environ.get("MENU_ITEM_INSERT_LOGGING"):
        return

    stack = "".join(traceback.format_stack()[:-1])  # Exclude this function
    _menu_item_insert_logger.warning(
        f"MenuItem INSERT: name='{target.name}', item_type_id={target.item_type_id}\n"
        f"Stack trace:\n{stack}"
    )
