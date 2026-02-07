"""Global attribute models for data-driven item configuration.

Contains: GlobalAttribute, GlobalAttributeAlias, GlobalAttributeOption,
GlobalAttributeOptionAlias, ItemTypeGlobalAttribute.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
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


class GlobalAttribute(Base):
    """
    Global attribute definition shared across item types.

    For example, a 'spread' attribute with all cream cheese options.
    Item types reference this global attribute instead of defining their own.

    This normalizes the data so all item types share the same option lists.
    """
    __tablename__ = "global_attributes"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(50), unique=True, nullable=False, index=True)
    display_name = Column(String(100), nullable=False)

    # Input type determines UI and validation
    # "single_select": Pick exactly one
    # "multi_select": Pick multiple
    # "boolean": Yes/no
    input_type = Column(String(20), nullable=False, default="single_select")

    # Description for admin UI
    description = Column(Text, nullable=True)  # e.g., "Cream cheese and other spread options"

    # Question text to ask the user for this attribute (shared across all item types)
    question_text = Column(Text, nullable=True)

    # Property name mapping for Python model access
    # When different from slug (e.g., slug="milk_sweetener_syrup" but property_name="milk")
    # If null, uses slug as property name
    property_name = Column(String(50), nullable=True)

    # Link to ingredient slug that this attribute modifies
    # When set, selecting an option (e.g., "3_eggs") updates the existing
    # ingredient modifier's quantity instead of creating a duplicate entry
    modifies_ingredient_slug = Column(String(100), nullable=True)

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    options = relationship("GlobalAttributeOption", back_populates="attribute", order_by="GlobalAttributeOption.display_order")
    item_type_links = relationship("ItemTypeGlobalAttribute", back_populates="global_attribute")
    alias_records = relationship("GlobalAttributeAlias", back_populates="global_attribute", cascade="all, delete-orphan")

    @property
    def aliases(self) -> str:
        """Return comma-separated list of aliases for display."""
        return ", ".join(a.alias for a in self.alias_records)


class GlobalAttributeAlias(Base):
    """
    Alias for a global attribute.

    Allows users to refer to attributes by alternative names.
    For example, "cream cheese" as an alias for "spread_type".
    Aliases are globally unique across all global attributes.
    """
    __tablename__ = "global_attribute_aliases"

    id = Column(Integer, primary_key=True, index=True)
    global_attribute_id = Column(Integer, ForeignKey("global_attributes.id", ondelete="CASCADE"), nullable=False, index=True)
    alias = Column(String(100), nullable=False, unique=True)  # Globally unique
    created_at = Column(DateTime, server_default=func.now())

    global_attribute = relationship("GlobalAttribute", back_populates="alias_records")


class GlobalAttributeOption(Base):
    """
    An option for a global attribute.

    For example, "Plain Cream Cheese", "Scallion Cream Cheese" are options
    for the "spread" global attribute.

    Aliases can come from:
    1. This option's own alias_records (GlobalAttributeOptionAlias)
    2. The linked Ingredient's alias_records (IngredientAlias)

    The cache loader merges both sources when building the options dict.
    """
    __tablename__ = "global_attribute_options"

    id = Column(Integer, primary_key=True, index=True)
    global_attribute_id = Column(Integer, ForeignKey("global_attributes.id", ondelete="RESTRICT"), nullable=False, index=True)

    # NULL when ingredient_id is set (derived from ingredient at read time)
    slug = Column(String(100), nullable=True)
    display_name = Column(String(100), nullable=True)

    # Link to ingredient for aliases/must_match lookup
    # Options that need special parsing MUST link to an Ingredient
    ingredient_id = Column(Integer, ForeignKey("ingredients.id", ondelete="SET NULL"), nullable=True, index=True)

    # Link to modifier category for sub-categorization within an attribute
    # Used to answer "what milks do you have?" when milks/sweeteners/syrups are in same attribute
    modifier_category_id = Column(Integer, ForeignKey("modifier_categories.id", ondelete="SET NULL"), nullable=True, index=True)

    price_modifier = Column(Float, nullable=False, default=0.0)  # +/- to base price
    is_default = Column(Boolean, nullable=False, default=False)  # Pre-selected by default
    is_available = Column(Boolean, nullable=False, default=True)  # False = 86'd

    # Display order (lower = shown first)
    display_order = Column(Integer, nullable=False, default=0)

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Unique constraint: one option per slug per global attribute
    __table_args__ = (
        UniqueConstraint("global_attribute_id", "slug", name="uq_global_attr_option_slug"),
    )

    # Relationships
    attribute = relationship("GlobalAttribute", back_populates="options")
    ingredient = relationship("Ingredient", backref="global_attribute_options")
    modifier_category = relationship("ModifierCategory", backref="global_attribute_options")
    alias_records = relationship(
        "GlobalAttributeOptionAlias",
        back_populates="option",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def aliases(self) -> list[str]:
        """Return list of alias strings from this option's alias_records."""
        return [ar.alias for ar in self.alias_records]


class GlobalAttributeOptionAlias(Base):
    """
    Child table for global attribute option aliases.

    Aliases are globally unique across all alias tables to prevent
    ambiguous lookups during parsing.

    Examples:
    - "2 shots" -> double_shot option
    - "triple" -> triple_shot option
    """
    __tablename__ = "global_attribute_option_aliases"

    id = Column(Integer, primary_key=True, index=True)
    global_attribute_option_id = Column(
        Integer,
        ForeignKey("global_attribute_options.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alias = Column(String(100), nullable=False, unique=True)  # Globally unique
    created_at = Column(DateTime, server_default=func.now())

    option = relationship("GlobalAttributeOption", back_populates="alias_records")


class GlobalAttributeOptionSkip(Base):
    """
    Defines skip rules for attribute options.

    When a specific option is selected (e.g., "black" for coffee),
    related attributes (e.g., milk, sweetener, syrup) should be automatically
    skipped during configuration.

    This enables data-driven logic like:
    - User says "black coffee" -> milk, sweetener, syrup questions skipped
    - User says "plain bagel" -> skip asking about spread (if configured)
    """
    __tablename__ = "global_attribute_option_skips"

    id = Column(Integer, primary_key=True, index=True)

    # The option that triggers the skip (e.g., "black" option)
    triggering_option_id = Column(
        Integer,
        ForeignKey("global_attribute_options.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The attribute to skip (e.g., "milk" attribute)
    skipped_attribute_id = Column(
        Integer,
        ForeignKey("global_attributes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at = Column(DateTime, server_default=func.now())

    # Unique constraint: one skip rule per option-attribute pair
    __table_args__ = (
        UniqueConstraint(
            "triggering_option_id", "skipped_attribute_id",
            name="uq_option_skip_rule"
        ),
    )

    # Relationships
    triggering_option = relationship("GlobalAttributeOption", backref="skip_rules")
    skipped_attribute = relationship("GlobalAttribute", backref="skipped_by_options")


class ItemTypeGlobalAttribute(Base):
    """
    Links an item type to a global attribute.

    Contains item-type-specific settings like question_text and is_required.
    The actual options come from the GlobalAttribute, not duplicated here.

    For example, both fish_sandwich and egg_sandwich can link to the "spread"
    global attribute, but each can have different question_text and is_required.
    """
    __tablename__ = "item_type_global_attributes"

    id = Column(Integer, primary_key=True, index=True)
    item_type_id = Column(Integer, ForeignKey("item_types.id", ondelete="RESTRICT"), nullable=False, index=True)
    global_attribute_id = Column(Integer, ForeignKey("global_attributes.id", ondelete="RESTRICT"), nullable=False, index=True)

    # Item-type-specific settings
    display_order = Column(Integer, nullable=False, default=0)  # Order in which to ask
    is_required = Column(Boolean, nullable=False, default=False)  # Must be specified
    allow_none = Column(Boolean, nullable=False, default=True)  # Can select "none" option
    ask_in_conversation = Column(Boolean, nullable=False, default=True)  # Should prompt user
    listen_only = Column(Boolean, nullable=False, default=False)  # Never ask, only capture if volunteered

    # For multi_select types
    min_selections = Column(Integer, nullable=True)
    max_selections = Column(Integer, nullable=True)

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Unique constraint: one link per item type per global attribute
    __table_args__ = (
        UniqueConstraint("item_type_id", "global_attribute_id", name="uq_item_type_global_attr"),
        Index("idx_item_type_global_attr_item_type", "item_type_id"),
        Index("idx_item_type_global_attr_global_attr", "global_attribute_id"),
    )

    # Relationships
    item_type = relationship("ItemType", back_populates="global_attribute_links")
    global_attribute = relationship("GlobalAttribute", back_populates="item_type_links")
