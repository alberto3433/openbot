"""Modifier category, alias, and qualifier models."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from .base import Base


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
    ingredient_category = Column(
        String, ForeignKey("ingredient_categories.slug"), nullable=True,
    )  # Maps to Ingredient.category value

    # Relationships
    alias_records = relationship("ModifierCategoryAlias", back_populates="modifier_category", cascade="all, delete-orphan")
    # FK-based relationship to IngredientCategory (when loads_from_ingredients=True)
    ingredient_category_rel = relationship(
        "IngredientCategory", foreign_keys=[ingredient_category],
    )

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
