"""
Slot Orchestrator for order capture.

This module provides a slot-filling architecture that determines
what information to collect next based on the current OrderTask state.

See docs/slot-orchestrator-migration.md for the full migration plan.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable
import logging

from .models import (
    OrderTask,
    ItemTask,
    BagelItemTask,
    MenuItemTask,
)

logger = logging.getLogger(__name__)


class SlotCategory(str, Enum):
    """Categories of slots, in priority order."""
    ITEMS = "items"
    DELIVERY_METHOD = "delivery_method"
    DELIVERY_ADDRESS = "delivery_address"
    CUSTOMER_NAME = "customer_name"
    ORDER_CONFIRM = "order_confirm"
    PAYMENT_METHOD = "payment_method"
    NOTIFICATION = "notification"


@dataclass
class SlotDefinition:
    """Defines a slot that needs to be filled."""
    category: SlotCategory
    field_path: str  # e.g., "delivery_method.order_type"
    question: str | None  # Question to ask (None for dynamic questions)
    required: bool = True
    condition: Callable[[OrderTask], bool] | None = None  # When this slot applies

    def applies_to(self, order: OrderTask) -> bool:
        """Check if this slot applies given the current order state."""
        if self.condition is None:
            return True
        return self.condition(order)


# Order-level slot definitions in priority order
ORDER_SLOTS: list[SlotDefinition] = [
    SlotDefinition(
        category=SlotCategory.ITEMS,
        field_path="items",
        question="What can I get for you?",
        required=True,
    ),
    SlotDefinition(
        category=SlotCategory.DELIVERY_METHOD,
        field_path="delivery_method.order_type",
        question="Is this for pickup or delivery?",
        required=True,
        condition=lambda order: len(order.items.get_active_items()) > 0,
    ),
    SlotDefinition(
        category=SlotCategory.DELIVERY_ADDRESS,
        field_path="delivery_method.address.street",
        question="What's the delivery address?",
        required=True,
        condition=lambda order: order.delivery_method.order_type == "delivery",
    ),
    SlotDefinition(
        category=SlotCategory.CUSTOMER_NAME,
        field_path="customer_info.name",
        question="Can I get a name for the order?",
        required=True,
    ),
    SlotDefinition(
        category=SlotCategory.ORDER_CONFIRM,
        field_path="checkout.order_reviewed",  # User confirmed summary, not final order
        question=None,  # Generated dynamically with order summary
        required=True,
    ),
    SlotDefinition(
        category=SlotCategory.PAYMENT_METHOD,
        field_path="payment.method",
        question="Would you like to pay in store, or should I text or email you a payment link?",
        required=True,
    ),
    SlotDefinition(
        category=SlotCategory.NOTIFICATION,
        field_path="customer_info.phone",  # or email - handled specially
        question="Should I text or email you the confirmation?",
        required=True,
        condition=lambda order: order.payment.method == "card_link",
    ),
]


class SlotOrchestrator:
    """
    Determines what slot to fill next based on OrderTask state.

    This provides a declarative way to define the order flow,
    replacing hardcoded phase transitions.
    """

    def __init__(
        self,
        order: OrderTask,
        slot_definitions: list[SlotDefinition] | None = None
    ):
        self.order = order
        self.slots = slot_definitions or ORDER_SLOTS

    def get_next_slot(self) -> SlotDefinition | None:
        """
        Get the next slot that needs to be filled.

        Returns None if all required slots are filled.
        """
        for slot in self.slots:
            # Check if slot applies (condition passes)
            if not slot.applies_to(self.order):
                continue

            # Check if slot is already filled
            if self._is_slot_filled(slot):
                continue

            return slot

        return None  # All slots filled

    def _is_slot_filled(self, slot: SlotDefinition) -> bool:
        """Check if a slot has been filled."""
        # Special handling for items
        if slot.category == SlotCategory.ITEMS:
            active_items = self.order.items.get_active_items()
            if not active_items:
                return False
            # Items slot is filled when we have items AND all are complete
            return self.order.items.all_items_complete()

        # Special handling for notification - need phone OR email
        if slot.category == SlotCategory.NOTIFICATION:
            return bool(self.order.customer_info.phone or self.order.customer_info.email)

        # Get the field value
        value = self._get_field_value(slot.field_path)

        # For boolean fields (like checkout.confirmed)
        if isinstance(value, bool):
            return value

        # For other fields, check if truthy
        return value is not None and value != ""

    def _get_field_value(self, field_path: str) -> Any:
        """Get a nested field value using dot notation."""
        obj = self.order
        for part in field_path.split("."):
            if obj is None:
                return None
            obj = getattr(obj, part, None)
        return obj

    def _set_field_value(self, field_path: str, value: Any) -> None:
        """Set a nested field value using dot notation."""
        parts = field_path.split(".")
        obj = self.order

        # Navigate to parent
        for part in parts[:-1]:
            obj = getattr(obj, part)

        # Set the value
        setattr(obj, parts[-1], value)

    def fill_slot(self, slot: SlotDefinition, value: Any) -> None:
        """Fill a slot with a value."""
        self._set_field_value(slot.field_path, value)

    def get_current_phase(self) -> str:
        """
        Derive the current phase from slot state.

        This provides backward compatibility with the OrderPhase enum.
        """
        # Check if any items are being configured
        current_item = self.order.items.get_current_item()
        if current_item is not None:
            return "configuring_item"

        next_slot = self.get_next_slot()
        if next_slot is None:
            return "complete"

        phase_map = {
            SlotCategory.ITEMS: "taking_items",
            SlotCategory.DELIVERY_METHOD: "checkout_delivery",
            SlotCategory.DELIVERY_ADDRESS: "checkout_address",
            SlotCategory.CUSTOMER_NAME: "checkout_name",
            SlotCategory.ORDER_CONFIRM: "checkout_confirm",
            SlotCategory.PAYMENT_METHOD: "checkout_payment_method",
            SlotCategory.NOTIFICATION: "checkout_notification",
        }
        return phase_map.get(next_slot.category, "unknown")

    def is_complete(self) -> bool:
        """Check if all required slots are filled."""
        return self.get_next_slot() is None

    def get_progress(self) -> dict[str, bool]:
        """
        Get progress for each slot category.

        Returns dict mapping category name to filled status.
        """
        progress = {}
        for slot in self.slots:
            if slot.applies_to(self.order):
                progress[slot.category.value] = self._is_slot_filled(slot)
        return progress

    def get_summary(self) -> str:
        """Get a human-readable summary of slot states."""
        lines = ["Slot Status:"]
        for slot in self.slots:
            if slot.applies_to(self.order):
                filled = self._is_slot_filled(slot)
                status = "filled" if filled else "EMPTY"
                value = self._get_field_value(slot.field_path)
                # Truncate long values
                if isinstance(value, str) and len(value) > 30:
                    value = value[:30] + "..."
                lines.append(f"  {slot.category.value}: {status} ({value})")
        return "\n".join(lines)


# =============================================================================
# Item-Level Slot Orchestration
# =============================================================================

@dataclass
class ItemSlotDefinition:
    """Defines a slot for an item field."""
    field_name: str
    question: str
    required: bool = True
    default: Any = None
    condition: Callable[[ItemTask], bool] | None = None


# Item slot definitions by item type
BAGEL_SLOTS: list[ItemSlotDefinition] = [
    ItemSlotDefinition("bagel_type", "What kind of bagel?", required=True),
    ItemSlotDefinition("toasted", "Would you like it toasted?", required=True),
    ItemSlotDefinition("spread", "Any spread - cream cheese, butter?", required=False),
]

COFFEE_SLOTS: list[ItemSlotDefinition] = [
    ItemSlotDefinition("size", "What size - small or large?", required=True),
    ItemSlotDefinition("iced", "Hot or iced?", required=True),
    ItemSlotDefinition("milk", "Any milk?", required=False),
    ItemSlotDefinition("sweetener", "Any sweetener?", required=False),
]

MENU_ITEM_SLOTS: list[ItemSlotDefinition] = [
    ItemSlotDefinition(
        "side_choice",
        "Would you like that with a bagel or fruit salad?",
        required=True,
        condition=lambda item: getattr(item, "requires_side_choice", False),
    ),
    ItemSlotDefinition(
        "bagel_choice",
        "What kind of bagel?",
        required=True,
        condition=lambda item: getattr(item, "side_choice", None) == "bagel",
    ),
]


def get_item_slots(item: ItemTask) -> list[ItemSlotDefinition]:
    """Get slot definitions for an item based on its type."""
    if isinstance(item, BagelItemTask):
        return BAGEL_SLOTS
    elif isinstance(item, MenuItemTask):
        # sized_beverage items use coffee slots
        if item.is_sized_beverage:
            return COFFEE_SLOTS
        return MENU_ITEM_SLOTS
    else:
        return []


class ItemSlotOrchestrator:
    """Handles slot filling for individual items."""

    def __init__(self, item: ItemTask):
        self.item = item
        self.slots = get_item_slots(item)

    def get_next_slot(self) -> ItemSlotDefinition | None:
        """Get the next unfilled required slot for this item."""
        for slot in self.slots:
            # Check condition
            if slot.condition and not slot.condition(self.item):
                continue

            # Check if filled
            value = getattr(self.item, slot.field_name, None)
            if value is None and slot.required:
                return slot

        return None

    def is_complete(self) -> bool:
        """Check if all required slots are filled."""
        return self.get_next_slot() is None

    def fill_slot(self, slot: ItemSlotDefinition, value: Any) -> None:
        """Fill an item slot."""
        setattr(self.item, slot.field_name, value)


# =============================================================================
# Sync Helper: DB Order -> OrderTask
# =============================================================================

def sync_db_order_to_task(db_order: Any, order_task: OrderTask) -> None:
    """
    Sync data from a database Order object to an OrderTask.

    This bridges the gap between the existing DB model and the new
    slot-filling architecture.

    Args:
        db_order: The database Order object (from models.py)
        order_task: The OrderTask to update
    """
    if db_order is None:
        return

    # Sync order type
    if hasattr(db_order, "order_type") and db_order.order_type:
        order_task.delivery_method.order_type = db_order.order_type

    # Sync customer name
    if hasattr(db_order, "customer_name") and db_order.customer_name:
        order_task.customer_info.name = db_order.customer_name

    # Sync customer phone
    if hasattr(db_order, "customer_phone") and db_order.customer_phone:
        order_task.customer_info.phone = db_order.customer_phone

    # Sync customer email
    if hasattr(db_order, "customer_email") and db_order.customer_email:
        order_task.customer_info.email = db_order.customer_email

    # Sync delivery address
    if hasattr(db_order, "delivery_address") and db_order.delivery_address:
        order_task.delivery_method.address.street = db_order.delivery_address

    # Sync order status to checkout
    if hasattr(db_order, "status"):
        if db_order.status == "confirmed":
            order_task.checkout.confirmed = True

    # Note: Items are synced separately since they require more complex mapping
    logger.debug(
        f"Synced DB order to OrderTask: "
        f"order_type={order_task.delivery_method.order_type}, "
        f"name={order_task.customer_info.name}, "
        f"confirmed={order_task.checkout.confirmed}"
    )
