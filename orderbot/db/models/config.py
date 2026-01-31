"""Item type configuration models.

Contains: OverallCategory, ItemType, ItemTypeAlias, ResponsePattern,
ModifierCategory, ModifierCategoryAlias, ModifierQualifier.
"""

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
    func,
)
from sqlalchemy.orm import relationship

from .base import Base


class OverallCategory(Base):
    """
    Defines a category for item types (e.g., "food" vs "beverage").

    This determines which modifier extraction rules apply to items of this type.
    Food items use food modifiers (proteins, cheeses, toppings).
    Beverage items use beverage modifiers (milk, sweetener, syrup).

    Also governs ingredient classification via IngredientCategory.modifier_type.
    """
    __tablename__ = "overall_categories"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(50), unique=True, nullable=False, index=True)  # "food", "beverage"
    display_name = Column(String(100), nullable=False)  # "Food", "Beverage"

    # Relationships
    item_types = relationship("ItemType", back_populates="overall_category")


class ItemType(Base):
    """
    Defines a type of menu item (sandwich, pizza, taco, drink, etc.).

    Configurability is derived from linked global attributes:
    - is_configurable = True if has ANY linked global attributes
    - skip_config = True if has NO attributes with ask_in_conversation=True

    Use services.item_type_helpers for these derived values.

    Note: Category grouping (e.g., "sandwich" containing egg sandwiches and fish sandwiches)
    is handled via MenuItem.categories (MenuItemCategory join table), not via ItemType.
    """
    __tablename__ = "item_types"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, unique=True, nullable=False, index=True)  # e.g., "sandwich", "pizza", "drink"
    display_name = Column(String, nullable=False)  # e.g., "Sandwich", "Pizza", "Drink"
    display_name_plural = Column(String, nullable=True)  # e.g., "coffees and teas" for sized_beverage (if irregular)

    # Overall category: "food" (proteins, cheeses, toppings) or "beverage" (milk, sweetener, syrup)
    overall_category_id = Column(Integer, ForeignKey("overall_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    overall_category = relationship("OverallCategory", back_populates="item_types")

    # Note: is_by_pound column was removed - use MenuItem.unit_type instead
    # Items sold by weight have unit_type="by_weight" on the MenuItem level

    # Side choice: some items (e.g., omelettes) prompt for a side dish
    has_side_choice = Column(Boolean, nullable=False, default=False)

    # Relationships
    menu_items = relationship("MenuItem", back_populates="item_type")
    type_ingredients = relationship("ItemTypeIngredient", back_populates="item_type")
    global_attribute_links = relationship("ItemTypeGlobalAttribute", back_populates="item_type")
    alias_records = relationship("ItemTypeAlias", back_populates="item_type", cascade="all, delete-orphan")

    @property
    def aliases(self) -> list[str]:
        """Get list of aliases from child table."""
        return [a.alias for a in self.alias_records]



class ItemTypeAlias(Base):
    """Child table for item type aliases. Aliases are globally unique."""
    __tablename__ = "item_type_aliases"

    id = Column(Integer, primary_key=True, index=True)
    item_type_id = Column(Integer, ForeignKey("item_types.id", ondelete="CASCADE"), nullable=False, index=True)
    alias = Column(String(100), nullable=False, unique=True)  # Globally unique
    created_at = Column(DateTime, server_default=func.now())

    item_type = relationship("ItemType", back_populates="alias_records")


class ResponsePattern(Base):
    """
    Stores patterns for recognizing user response types.

    This table enables data-driven response classification for:
    - Affirmative responses (yes, yeah, yep, sure, ok, etc.)
    - Negative responses (no, nope, nah, no thanks, etc.)
    - Cancel responses (cancel, never mind, forget it, etc.)
    - Done responses (that's all, that's it, nothing else, etc.)

    Patterns are matched case-insensitively against normalized user input.
    """
    __tablename__ = "response_pattern"

    id = Column(Integer, primary_key=True, index=True)
    pattern_type = Column(String(50), nullable=False, index=True)  # 'affirmative', 'negative', 'cancel', 'done', 'greeting'
    pattern = Column(String(100), nullable=False)  # The pattern to match (exact string or regex)
    is_regex = Column(Boolean, nullable=False, default=False)  # If True, pattern is treated as regex
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint('pattern_type', 'pattern', name='uq_response_pattern_type_pattern'),
        Index('idx_response_pattern_type', 'pattern_type'),
    )


class ModifierCategory(Base):
    """
    Defines a modifier/add-on category for menu item customization.

    This maps user input keywords (like "sweetener", "sugar", "milk", "dairy")
    to canonical category names (like "sweeteners", "milks") for answering
    questions like "what sweeteners do you have?".

    Some categories are database-backed (toppings, proteins, cheeses, spreads)
    where items are loaded from the Ingredient table. Others are static
    (sweeteners, milks, syrups) with predefined descriptions.
    """
    __tablename__ = "modifier_categories"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, unique=True, nullable=False, index=True)  # e.g., "sweeteners", "milks"
    display_name = Column(String, nullable=False)  # e.g., "Sweeteners", "Milks"

    # For static response categories (not database-backed)
    description = Column(String, nullable=True)  # e.g., "we have sugar, raw sugar, honey..."
    prompt_suffix = Column(String, nullable=True)  # e.g., "Would you like any in your drink?"

    # For database-backed categories (load from Ingredient table)
    loads_from_ingredients = Column(Boolean, nullable=False, default=False)
    ingredient_category = Column(String, nullable=True)  # Maps to Ingredient.category value

    # Relationships
    alias_records = relationship("ModifierCategoryAlias", back_populates="modifier_category", cascade="all, delete-orphan")

    @property
    def aliases(self) -> list[str]:
        """Get list of aliases from child table."""
        return [a.alias for a in self.alias_records]



class ModifierCategoryAlias(Base):
    """Child table for modifier category aliases. Aliases are globally unique."""
    __tablename__ = "modifier_category_aliases"

    id = Column(Integer, primary_key=True, index=True)
    modifier_category_id = Column(Integer, ForeignKey("modifier_categories.id", ondelete="CASCADE"), nullable=False, index=True)
    alias = Column(String(100), nullable=False, unique=True)  # Globally unique
    created_at = Column(DateTime, server_default=func.now())

    modifier_category = relationship("ModifierCategory", back_populates="alias_records")


class ModifierQualifier(Base):
    """
    Stores modifier qualifier patterns and their normalized forms.

    These patterns are used to detect qualifiers in user input like "extra mayo",
    "light cream cheese", "on the side", etc. The normalized_form is what gets
    displayed in parentheses after the modifier, e.g., "Mayo (extra)".

    Categories:
    - amount: Quantity modifiers (extra, light, double, etc.)
    - position: Location modifiers (on the side, on top)
    - preparation: How to prepare (crispy, well done, etc.)

    This is a company-wide table - all stores share the same qualifier definitions.
    """
    __tablename__ = "modifier_qualifiers"

    id = Column(Integer, primary_key=True, index=True)

    # The pattern to match (e.g., "extra", "lots of", "a little bit of")
    # Matched as whole words, case-insensitive
    pattern = Column(String(100), nullable=False, unique=True, index=True)

    # The normalized form to display (e.g., "extra", "light", "on the side")
    normalized_form = Column(String(50), nullable=False)

    # Category for grouping and conflict detection
    # amount: extra, light, double, etc. - these can conflict with each other
    # position: on the side, on top - no conflict with amount
    # preparation: crispy, well done - no conflict with amount
    category = Column(String(50), nullable=False, default="amount")

    # Whether this qualifier is active
    is_active = Column(Boolean, nullable=False, default=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<ModifierQualifier(pattern='{self.pattern}', normalized='{self.normalized_form}', category='{self.category}')>"
