"""Item type and item type alias models."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from .base import Base


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

    # Generic item types are deprioritized in trigger matching (e.g., broad catch-all types)
    is_generic = Column(Boolean, nullable=False, default=False, server_default="false")

    # Variant pricing: which global attribute determines variant pricing
    # Example: "size" attribute for beverages (small, medium, large)
    variant_pricing_attribute_id = Column(
        Integer,
        ForeignKey("global_attributes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    @property
    def overall_category(self) -> str | None:
        """Get overall category from the display group."""
        if self.menu_display_group:
            return self.menu_display_group.overall_category
        return None

    @property
    def overall_category_id(self) -> int | None:
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
