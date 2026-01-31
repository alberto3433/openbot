"""Ingredient models.

Contains: IngredientUnit, Ingredient, IngredientAlias, IngredientMustMatch,
IngredientCategory, IngredientStoreAvailability, ItemTypeIngredient.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from .base import Base


class IngredientUnit(Base):
    """Unit of measurement for ingredients (e.g., slice, pump, ounce)."""
    __tablename__ = "ingredient_units"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)  # 'serving', 'ounce', etc.

    # Relationship
    ingredients = relationship("Ingredient", back_populates="unit_rel")


class Ingredient(Base):
    __tablename__ = "ingredients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)  # Canonical identifier
    category = Column(String, nullable=False)
    unit_id = Column(Integer, ForeignKey("ingredient_units.id"), nullable=False)
    track_inventory = Column(Boolean, nullable=False, default=True)
    # NOTE: Pricing for ingredients is managed via GlobalAttributeOption.price_modifier,
    # not in this table. See the data model documentation for details.
    is_available = Column(Boolean, nullable=False, default=True)  # False = "86'd" / out of stock

    # Dietary attributes (source of truth - ingredients define what they are)
    is_vegan = Column(Boolean, nullable=False, default=False)
    is_vegetarian = Column(Boolean, nullable=False, default=False)
    is_gluten_free = Column(Boolean, nullable=False, default=False)
    is_dairy_free = Column(Boolean, nullable=False, default=False)
    is_kosher = Column(Boolean, nullable=False, default=False)

    # Allergen attributes (what allergens this ingredient contains)
    contains_eggs = Column(Boolean, nullable=False, default=False)
    contains_fish = Column(Boolean, nullable=False, default=False)
    contains_sesame = Column(Boolean, nullable=False, default=False)
    contains_nuts = Column(Boolean, nullable=False, default=False)

    # Abbreviation for text expansion (e.g., "cc" expands to "cream cheese" before parsing)
    abbreviation = Column(String, nullable=True)

    # relationships
    store_availability = relationship("IngredientStoreAvailability", back_populates="ingredient", cascade="all, delete-orphan")
    item_type_links = relationship("ItemTypeIngredient", back_populates="ingredient")
    # Alias and must_match child tables
    alias_records = relationship("IngredientAlias", back_populates="ingredient", cascade="all, delete-orphan")
    must_match_records = relationship("IngredientMustMatch", back_populates="ingredient", cascade="all, delete-orphan")
    # Menu items that contain this ingredient by default
    menu_item_links = relationship("MenuItemIngredient", back_populates="ingredient")
    # Unit relationship
    unit_rel = relationship("IngredientUnit", back_populates="ingredients")

    @property
    def aliases(self) -> list[str]:
        """Get list of aliases from child table."""
        return [a.alias for a in self.alias_records]

    @property
    def must_match(self) -> list[str]:
        """Get list of must_match strings from child table."""
        return [m.must_match for m in self.must_match_records]

    @property
    def unit(self) -> str:
        """Get unit name from relationship (backward compatibility)."""
        return self.unit_rel.name if self.unit_rel else "serving"


class IngredientAlias(Base):
    """Child table for ingredient aliases. Aliases are globally unique."""
    __tablename__ = "ingredient_aliases"

    id = Column(Integer, primary_key=True, index=True)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False, index=True)
    alias = Column(String(100), nullable=False, unique=True)  # Globally unique
    created_at = Column(DateTime, server_default=func.now())

    ingredient = relationship("Ingredient", back_populates="alias_records")


class IngredientMustMatch(Base):
    """Child table for ingredient must_match strings."""
    __tablename__ = "ingredient_must_match"

    id = Column(Integer, primary_key=True, index=True)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False, index=True)
    must_match = Column(String(100), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("ingredient_id", "must_match", name="uq_ingredient_must_match"),
    )

    ingredient = relationship("Ingredient", back_populates="must_match_records")


class IngredientCategory(Base):
    """
    Metadata about ingredient categories (protein, topping, cheese, milk, etc.).

    This table provides classification of ingredient categories for data-driven
    lookups. The modifier_type field indicates whether ingredients in this category
    are used as food modifiers (bagels, sandwiches) or beverage modifiers (coffee).

    The code_field_name and is_multi_select fields enable data-driven modifier
    field configuration, replacing hardcoded INGREDIENT_GROUP_TO_FIELD mappings.

    """
    __tablename__ = "ingredient_categories"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(50), unique=True, nullable=False, index=True)  # "protein", "topping", etc.
    display_name = Column(String(100), nullable=False)  # "Proteins", "Toppings", etc.
    modifier_type = Column(String(20), nullable=True)  # "food", "beverage", or None
    display_order = Column(Integer, nullable=False, default=0)  # For UI ordering

    # Data-driven modifier field configuration
    # code_field_name: Python property name on MenuItemTask (e.g., "toppings", "extra_protein")
    # If NULL, defaults to slug (e.g., "milk" -> "milk")
    code_field_name = Column(String(50), nullable=True)
    # is_multi_select: True if this category supports multiple selections (e.g., toppings, sweeteners)
    # If NULL, defaults to False (single selection)
    is_multi_select = Column(Boolean, nullable=True, default=False)
    # is_name_forming: True if ingredient display name should replace menu item name
    # e.g., bread category - "Garlic Bagel" instead of "Bagel, Garlic Bagel"
    is_name_forming = Column(Boolean, nullable=False, default=False)
    # quantity_unit: Unit name for numeric quantities (e.g., "pump", "packet", "piece")
    # If NULL, category uses qualifiers (extra/light) instead of numeric quantities
    # Display: "2 pumps of Vanilla Syrup" vs "extra oat milk"
    quantity_unit = Column(String(50), nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class IngredientStoreAvailability(Base):
    """Tracks ingredient availability per store. If no entry exists for a store+ingredient, assume available."""
    __tablename__ = "ingredient_store_availability"

    id = Column(Integer, primary_key=True, index=True)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False)
    store_id = Column(String, nullable=False, index=True)
    is_available = Column(Boolean, nullable=False, default=True)

    # Unique constraint: one entry per ingredient per store
    __table_args__ = (
        UniqueConstraint("ingredient_id", "store_id", name="uix_ingredient_store"),
    )

    # relationships
    ingredient = relationship("Ingredient", back_populates="store_availability")


class ItemTypeIngredient(Base):
    """
    Links ingredients to item types with per-type configuration.

    This enables a unified ingredient system where physical items like milk,
    sweeteners, and syrups can be managed alongside proteins, toppings, and spreads
    in a single ingredients table, with per-item-type configuration.

    When an attribute has loads_from_ingredients=True, its options come from
    this table filtered by ingredient_group, instead of from attribute_options.

    NOTE: Pricing comes from GlobalAttributeOption.price_modifier (where ingredient_id matches),
    NOT from this table. This table only handles linking and display configuration.

    Examples:
    - Oat Milk linked to 'sized_beverage' with ingredient_group='milk'
    - Bacon linked to 'bagel' with ingredient_group='protein'
    - Vanilla Syrup linked to 'sized_beverage' with ingredient_group='syrup'
    """
    __tablename__ = "item_type_ingredients"

    id = Column(Integer, primary_key=True, index=True)
    item_type_id = Column(Integer, ForeignKey("item_types.id", ondelete="RESTRICT"), nullable=False)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id", ondelete="RESTRICT"), nullable=False)

    # Grouping - which selector/category this appears in
    # e.g., 'milk', 'sweetener', 'syrup', 'spread', 'protein', 'topping', 'cheese'
    ingredient_group = Column(String(50), nullable=False)

    # Display configuration
    display_order = Column(Integer, nullable=False, default=0)
    display_name_override = Column(String(100), nullable=True)  # e.g., "Oat" instead of "Oat Milk"

    # Selection behavior
    is_default = Column(Boolean, nullable=False, default=False)
    is_available = Column(Boolean, nullable=False, default=True)  # Per-item-type override

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Unique constraint: one entry per item_type + ingredient + group combination
    __table_args__ = (
        UniqueConstraint('item_type_id', 'ingredient_id', 'ingredient_group', name='uq_item_type_ingredient_group'),
        Index('idx_item_type_ingredients_item_type', 'item_type_id'),
        Index('idx_item_type_ingredients_ingredient', 'ingredient_id'),
        Index('idx_item_type_ingredients_group', 'ingredient_group'),
        Index('idx_item_type_ingredients_item_type_group', 'item_type_id', 'ingredient_group'),
    )

    # Relationships
    item_type = relationship("ItemType", back_populates="type_ingredients")
    ingredient = relationship("Ingredient", back_populates="item_type_links")
