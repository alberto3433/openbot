"""Item type component slot and slot option models."""

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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from .base import Base


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

    # Default modifiers to pre-apply when this option is selected as a child item
    # Format: [{"type": "attribute_option", "global_attribute_option_id": 42}, ...]
    default_modifiers = Column(JSONB, nullable=True, default=None)

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
