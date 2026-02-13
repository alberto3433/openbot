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


class ItemType(Base):
    """
    Defines a type of menu item (sandwich, pizza, taco, drink, etc.).

    Configurability is derived from linked global attributes:
    - is_configurable = True if has ANY linked global attributes
    - skip_config = True if has NO attributes with ask_in_conversation=True

    Use services.item_type_helpers for these derived values.

    Note: Category grouping (e.g., "sandwich" containing egg sandwiches and fish sandwiches)
    is handled via MenuItem.categories (MenuItemCategory join table), not via ItemType.

    The overall category (food vs beverage) is inherited from the menu_display_group.
    """
    __tablename__ = "item_types"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, unique=True, nullable=False, index=True)  # e.g., "sandwich", "pizza", "drink"
    display_name = Column(String, nullable=False)  # e.g., "Sandwich", "Pizza", "Drink"
    display_name_plural = Column(String, nullable=True)  # e.g., "coffees and teas" for sized_beverage (if irregular)

    # Menu display grouping (required) - category is inherited from this
    menu_display_group_id = Column(Integer, ForeignKey("menu_display_groups.id", ondelete="RESTRICT"), nullable=False, index=True)
    menu_display_group = relationship("MenuDisplayGroup", back_populates="item_types")

    # Note: is_by_pound column was removed - use MenuItem.unit_type instead
    # Items sold by weight have unit_type="by_weight" on the MenuItem level

    # Side choice: some items (e.g., omelettes) prompt for a side dish
    has_side_choice = Column(Boolean, nullable=False, default=False)

    # Variant pricing: which global attribute determines variant pricing
    # Example: "size" attribute for beverages (small, medium, large)
    variant_pricing_attribute_id = Column(
        Integer,
        ForeignKey("global_attributes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    @property
    def overall_category(self):
        """Get overall category from the display group."""
        if self.menu_display_group:
            return self.menu_display_group.overall_category
        return None

    @property
    def overall_category_id(self):
        """Get overall category ID from the display group."""
        if self.menu_display_group:
            return self.menu_display_group.overall_category_id
        return None

    # Relationships
    menu_items = relationship("MenuItem", back_populates="item_type")
    global_attribute_links = relationship("ItemTypeGlobalAttribute", back_populates="item_type")
    alias_records = relationship("ItemTypeAlias", back_populates="item_type", cascade="all, delete-orphan")
    component_slots = relationship("ItemTypeComponentSlot", back_populates="parent_item_type", cascade="all, delete-orphan")
    variant_pricing_attribute = relationship("GlobalAttribute", foreign_keys=[variant_pricing_attribute_id])

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


class AttributeInquiryKeyword(Base):
    """
    Maps inquiry keywords to global attributes for data-driven attribute inquiry parsing.

    When user asks "what bagel types do you have?", the word "types" (keyword)
    combined with the item type "bagel" is matched against this table to determine
    which attribute's options to show (e.g., "bread" attribute).

    Examples:
    - ("types", bagel_item_type_id) -> bread_global_attribute_id
    - ("sizes", None) -> size_global_attribute_id (None means any/no item type)
    - ("flavors", bagel_item_type_id) -> bread_global_attribute_id

    This replaces the hardcoded common_mappings dict in menu_options_inquiry_handler.py.
    """
    __tablename__ = "attribute_inquiry_keywords"

    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String(50), nullable=False, index=True)  # e.g., "types", "sizes", "flavors"
    item_type_id = Column(Integer, ForeignKey("item_types.id", ondelete="CASCADE"), nullable=True, index=True)
    global_attribute_id = Column(Integer, ForeignKey("global_attributes.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    item_type = relationship("ItemType")
    global_attribute = relationship("GlobalAttribute")

    __table_args__ = (
        UniqueConstraint('keyword', 'item_type_id', name='uq_attr_inquiry_keyword_item_type'),
        Index('idx_attr_inquiry_keyword_lookup', 'keyword', 'item_type_id'),
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


class ItemTypeComponentSlot(Base):
    """
    Defines component slots for item types that include other configurable items.

    For example, an omelette has a "side" slot that can be filled by a bagel
    or fruit salad. This enables items to bundle other items with their own
    configuration flows.

    Examples:
    - Omelette: has "side" slot accepting bagel or fruit_salad
    - Pick Two combo: has "first_pick" and "second_pick" slots
    - Kids meal: has "entree", "side", "drink" slots
    """
    __tablename__ = "item_type_component_slots"

    id = Column(Integer, primary_key=True, index=True)
    parent_item_type_id = Column(
        Integer,
        ForeignKey("item_types.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    slot_name = Column(String(50), nullable=False)  # e.g., "side", "first_pick"
    display_name = Column(String(100))  # e.g., "Side", "First Item"
    prompt_text = Column(Text)  # e.g., "Would you like a bagel or fruit salad?"
    is_required = Column(Boolean, nullable=False, default=True)
    min_quantity = Column(Integer, nullable=False, default=1)
    max_quantity = Column(Integer, nullable=False, default=1)
    display_order = Column(Integer, nullable=False, default=0)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    parent_item_type = relationship("ItemType", back_populates="component_slots")
    slot_options = relationship(
        "ComponentSlotOption",
        back_populates="slot",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint('parent_item_type_id', 'slot_name', name='uq_component_slot_type_name'),
    )

    def __repr__(self):
        return f"<ItemTypeComponentSlot(slot_name='{self.slot_name}', parent_item_type_id={self.parent_item_type_id})>"


class ComponentSlotOption(Base):
    """
    Defines what can fill a component slot.

    Each option specifies an item type (e.g., "bagel") or specific menu item
    that can be selected for this slot, along with pricing rules.

    Pricing rules:
    - 'included': Base price is $0, but upcharges (GF, modifiers) still apply
    - 'full_price': Normal pricing for the item
    - 'fixed': Use fixed_price value as the base price
    - 'discount_flat': Subtract fixed_price from normal base price
    - 'discount_percent': Apply fixed_price as percentage discount
    """
    __tablename__ = "component_slot_options"

    id = Column(Integer, primary_key=True, index=True)
    slot_id = Column(
        Integer,
        ForeignKey("item_type_component_slots.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # What's allowed - one of these should be set
    allowed_item_type_id = Column(
        Integer,
        ForeignKey("item_types.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    allowed_menu_item_id = Column(
        Integer,
        ForeignKey("menu_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )

    # Pricing
    price_rule = Column(String(20), nullable=False, default='included')
    fixed_price = Column(Integer, nullable=True)  # In cents, for fixed/discount rules
    # Amount included in parent's price (in cents) for differential pricing
    # NULL = entire base is free (e.g., bagel), value = amount included (e.g., 795 for small fruit salad)
    included_price_cents = Column(Integer, nullable=True)

    # Display
    display_name = Column(String(100))  # e.g., "Bagel", "Fruit Salad"
    display_order = Column(Integer, nullable=False, default=0)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    slot = relationship("ItemTypeComponentSlot", back_populates="slot_options")
    allowed_item_type = relationship("ItemType", foreign_keys=[allowed_item_type_id])
    allowed_menu_item = relationship("MenuItem", foreign_keys=[allowed_menu_item_id])

    __table_args__ = (
        # Ensure at least one of item_type or menu_item is set
        Index('idx_slot_option_slot', 'slot_id'),
    )

    def __repr__(self):
        target = f"item_type={self.allowed_item_type_id}" if self.allowed_item_type_id else f"menu_item={self.allowed_menu_item_id}"
        return f"<ComponentSlotOption(slot_id={self.slot_id}, {target}, price_rule='{self.price_rule}')>"
