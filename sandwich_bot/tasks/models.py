"""
Pydantic models for the hierarchical task system.

The task hierarchy represents the order capture process:
- OrderTask (root)
  - DeliveryMethodTask
  - ItemsTask (contains multiple ItemTasks)
  - CustomerInfoTask
  - CheckoutTask
  - PaymentTask
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field
import uuid


class TaskStatus(str, Enum):
    """Status of a task in the hierarchy."""
    PENDING = "pending"  # Not started, waiting for prerequisites
    IN_PROGRESS = "in_progress"  # Currently being worked on
    COMPLETE = "complete"  # All required fields filled
    SKIPPED = "skipped"  # Explicitly skipped or cancelled


class FieldConfig(BaseModel):
    """Configuration for a single field in a task."""
    name: str
    required: bool = True
    default: Any | None = None
    ask_if_empty: bool = True  # If True, ask user when field is empty
    question: str | None = None  # Question to ask (if ask_if_empty is True)

    def needs_asking(self, current_value: Any) -> bool:
        """Check if this field needs to be asked about."""
        # Check if current value is meaningful (not None, not empty collection)
        if self._has_meaningful_value(current_value):
            return False
        if not self.ask_if_empty:
            return False
        # Only skip asking if we have a meaningful (truthy) default value
        # Empty defaults like [] or "" still allow asking if ask_if_empty=True
        if self._has_meaningful_value(self.default):
            return False
        return self.required or self.ask_if_empty

    def _has_meaningful_value(self, value: Any) -> bool:
        """Check if a value is meaningful (not None, not empty collection/string)."""
        if value is None:
            return False
        # Empty collections and empty strings don't count as having a value
        if isinstance(value, (list, dict, set)) and not value:
            return False
        if value == "":
            return False
        return True


class BaseTask(BaseModel):
    """Base class for all tasks in the hierarchy."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    def mark_complete(self) -> None:
        """Mark this task as complete."""
        self.status = TaskStatus.COMPLETE
        self.completed_at = datetime.now(timezone.utc)

    def mark_in_progress(self) -> None:
        """Mark this task as in progress."""
        self.status = TaskStatus.IN_PROGRESS

    def mark_skipped(self) -> None:
        """Mark this task as skipped."""
        self.status = TaskStatus.SKIPPED

    def is_complete(self) -> bool:
        """Check if this task is complete."""
        return self.status == TaskStatus.COMPLETE

    def is_actionable(self) -> bool:
        """Check if this task can be worked on."""
        return self.status in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS)

    def get_missing_required_fields(self, field_configs: dict[str, FieldConfig]) -> list[FieldConfig]:
        """Get list of required fields that are missing values."""
        missing = []
        for field_name, config in field_configs.items():
            if not config.required:
                continue
            current_value = getattr(self, field_name, None)
            if current_value is None and config.default is None:
                missing.append(config)
        return missing

    def get_fields_to_ask(self, field_configs: dict[str, FieldConfig]) -> list[FieldConfig]:
        """Get list of fields that need to be asked about."""
        to_ask = []
        for field_name, config in field_configs.items():
            current_value = getattr(self, field_name, None)
            if config.needs_asking(current_value):
                to_ask.append(config)
        return to_ask

    def get_progress(self, field_configs: dict[str, FieldConfig]) -> float:
        """Get completion progress as a percentage (0.0 to 1.0)."""
        if not field_configs:
            return 1.0 if self.is_complete() else 0.0

        required_fields = [f for f in field_configs.values() if f.required]
        if not required_fields:
            return 1.0 if self.is_complete() else 0.0

        filled = 0
        for config in required_fields:
            current_value = getattr(self, config.name, None)
            if current_value is not None or config.default is not None:
                filled += 1

        return filled / len(required_fields)


# =============================================================================
# Item Tasks
# =============================================================================

class ItemTask(BaseTask):
    """Base class for order items (bagels, coffee, etc.)."""

    item_type: str  # "bagel", "coffee", "sandwich", etc.
    quantity: int = 1
    unit_price: float = 0.0

    def get_display_name(self) -> str:
        """Get display name for this item."""
        raise NotImplementedError

    def get_summary(self) -> str:
        """Get a summary description of this item."""
        raise NotImplementedError


class BagelItemTask(ItemTask):
    """Task for capturing a bagel order."""

    item_type: Literal["bagel"] = "bagel"

    # Bagel-specific fields
    bagel_type: str | None = None  # plain, everything, sesame, etc.
    toasted: bool | None = None
    spread: str | None = None  # cream cheese, butter, etc.
    spread_type: str | None = None  # plain, scallion, veggie, etc.
    extras: list[str] = Field(default_factory=list)
    sandwich_protein: str | None = None  # egg, bacon, lox, etc.

    def get_display_name(self) -> str:
        """Get display name for this bagel."""
        if self.bagel_type:
            return f"{self.bagel_type} bagel"
        return "bagel"

    def get_summary(self) -> str:
        """Get a summary description of this bagel."""
        parts = []

        if self.quantity > 1:
            parts.append(f"{self.quantity}x")

        if self.bagel_type:
            parts.append(f"{self.bagel_type} bagel")
        else:
            parts.append("bagel")

        if self.toasted:
            parts.append("toasted")

        # Build the "with X" part - combine spread, protein, and extras
        with_parts = []

        # Add spread if it's not "none"
        if self.spread and self.spread.lower() != "none":
            spread_desc = self.spread
            if self.spread_type and self.spread_type != "plain":
                spread_desc = f"{self.spread_type} {self.spread}"
            with_parts.append(spread_desc)

        # Add protein
        if self.sandwich_protein:
            with_parts.append(self.sandwich_protein)

        # Add extras
        if self.extras:
            with_parts.extend(self.extras)

        # Format the with clause
        if with_parts:
            parts.append(f"with {', '.join(with_parts)}")
        elif self.spread and self.spread.lower() == "none":
            # Only say "with nothing on it" if there's truly nothing
            parts.append("with nothing on it")

        return " ".join(parts)


class CoffeeItemTask(ItemTask):
    """Task for capturing a coffee/drink order."""

    item_type: Literal["coffee"] = "coffee"

    # Coffee-specific fields
    drink_type: str | None = None  # drip, latte, espresso, etc.
    size: str | None = None  # small, medium, large
    iced: bool | None = None  # True=iced, False=hot, None=not specified
    milk: str | None = None  # whole, skim, oat, almond, etc.
    sweetener: str | None = None  # sugar, splenda, stevia, etc.
    sweetener_quantity: int = 1  # number of sweetener packets (e.g., 2 splendas)
    flavor_syrup: str | None = None  # vanilla, caramel, hazelnut, etc.
    extra_shots: int = 0

    # Upcharge tracking (set by recalculate_coffee_price)
    size_upcharge: float = 0.0
    milk_upcharge: float = 0.0
    syrup_upcharge: float = 0.0

    def get_display_name(self) -> str:
        """Get display name for this drink."""
        parts = []
        if self.size:
            parts.append(self.size)
        if self.iced is True:
            parts.append("iced")
        elif self.iced is False:
            parts.append("hot")
        if self.drink_type:
            parts.append(self.drink_type)
        else:
            parts.append("coffee")
        return " ".join(parts)

    def get_summary(self) -> str:
        """Get a summary description of this drink with upcharges."""
        parts = []

        if self.size:
            parts.append(self.size)

        if self.iced is True:
            parts.append("iced")
        elif self.iced is False:
            parts.append("hot")

        if self.drink_type:
            parts.append(self.drink_type)
        else:
            parts.append("coffee")

        # Add flavor syrup with upcharge
        if self.flavor_syrup:
            if self.syrup_upcharge > 0:
                parts.append(f"with {self.flavor_syrup} syrup (+${self.syrup_upcharge:.2f})")
            else:
                parts.append(f"with {self.flavor_syrup} syrup")

        if self.milk:
            # "none" or "black" means no milk - show as "black" for clarity
            if self.milk.lower() in ("none", "black"):
                parts.append("black")
            elif self.milk_upcharge > 0:
                parts.append(f"with {self.milk} milk (+${self.milk_upcharge:.2f})")
            else:
                parts.append(f"with {self.milk} milk")

        # Add sweetener with quantity
        if self.sweetener:
            if self.sweetener_quantity > 1:
                parts.append(f"with {self.sweetener_quantity} {self.sweetener}s")
            else:
                parts.append(f"with {self.sweetener}")

        if self.extra_shots:
            parts.append(f"({self.extra_shots} extra shot{'s' if self.extra_shots > 1 else ''})")

        return " ".join(parts)


class SpeedMenuBagelItemTask(ItemTask):
    """Task for a pre-configured speed menu bagel (e.g., 'The Classic', 'The Leo').

    These items only need a toasted preference - no other configuration.
    """

    item_type: Literal["speed_menu_bagel"] = "speed_menu_bagel"

    # Speed menu bagel fields
    menu_item_name: str  # The name of the item (e.g., "The Classic")
    menu_item_id: int | None = None  # Database ID if matched
    toasted: bool | None = None  # True=toasted, False=not toasted, None=not specified

    def get_display_name(self) -> str:
        """Get display name for this item."""
        return self.menu_item_name

    def get_summary(self) -> str:
        """Get a summary description of this item."""
        parts = []

        parts.append(self.menu_item_name)

        if self.toasted is True:
            parts.append("toasted")
        elif self.toasted is False:
            parts.append("not toasted")

        return " ".join(parts)

    def get_next_question(self) -> str | None:
        """Get the next question to ask for this item."""
        if self.toasted is None:
            return "Would you like that toasted?"
        return None


class MenuItemTask(ItemTask):
    """Task for a menu item ordered by name (e.g., 'The Chipotle Egg Omelette')."""

    item_type: Literal["menu_item"] = "menu_item"

    # Menu item fields
    menu_item_name: str  # The name of the menu item
    menu_item_id: int | None = None  # Database ID if matched
    menu_item_type: str | None = None  # Type slug (e.g., "omelette", "sandwich")
    modifications: list[str] = Field(default_factory=list)  # User modifications

    # Customization fields for configurable items (e.g., omelettes, sandwiches)
    side_choice: str | None = None  # "bagel" or "fruit_salad" for omelettes
    bagel_choice: str | None = None  # Which bagel if side is bagel, or bagel for sandwiches
    toasted: bool | None = None  # Whether sandwich should be toasted
    requires_side_choice: bool = False  # Whether this item needs side selection

    def get_display_name(self) -> str:
        """Get display name for this menu item."""
        return self.menu_item_name

    def get_summary(self) -> str:
        """Get a summary description of this menu item."""
        parts = []

        if self.quantity > 1:
            parts.append(f"{self.quantity}x")

        parts.append(self.menu_item_name)

        # Add bagel choice for spread/salad sandwiches
        if self.menu_item_type in ("spread_sandwich", "salad_sandwich") and self.bagel_choice:
            parts.append(f"on {self.bagel_choice} bagel")
            if self.toasted:
                parts.append("toasted")
        # Add side choice info for omelettes
        elif self.side_choice == "bagel" and self.bagel_choice:
            parts.append(f"with {self.bagel_choice} bagel")
        elif self.side_choice == "fruit_salad":
            parts.append("with fruit salad")

        if self.modifications:
            parts.append(f"({', '.join(self.modifications)})")

        return " ".join(parts)

    def get_missing_customizations(self) -> list[str]:
        """Get list of missing required customizations."""
        missing = []
        if self.requires_side_choice and not self.side_choice:
            missing.append("side_choice")
        if self.side_choice == "bagel" and not self.bagel_choice:
            missing.append("bagel_choice")
        return missing

    def is_fully_customized(self) -> bool:
        """Check if all required customizations are complete."""
        return len(self.get_missing_customizations()) == 0


# =============================================================================
# Order Flow Tasks
# =============================================================================

class AddressTask(BaseTask):
    """Task for capturing delivery address."""

    street: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    apt_unit: str | None = None
    delivery_instructions: str | None = None
    is_validated: bool = False

    def get_formatted_address(self) -> str | None:
        """Get formatted address string."""
        if not self.street:
            return None

        parts = [self.street]
        if self.apt_unit:
            parts.append(f"Apt {self.apt_unit}")

        city_state_zip = []
        if self.city:
            city_state_zip.append(self.city)
        if self.state:
            city_state_zip.append(self.state)
        if self.zip_code:
            city_state_zip.append(self.zip_code)

        if city_state_zip:
            parts.append(", ".join(city_state_zip))

        return ", ".join(parts)


class DeliveryMethodTask(BaseTask):
    """Task for capturing delivery method (pickup vs delivery)."""

    order_type: Literal["pickup", "delivery"] | None = None
    address: AddressTask = Field(default_factory=AddressTask)
    store_location_confirmed: bool = False

    def is_complete(self) -> bool:
        """Check if delivery method is complete."""
        if self.order_type is None:
            return False
        if self.order_type == "pickup":
            return True  # Pickup doesn't need address
        if self.order_type == "delivery":
            # Need at least street and zip for delivery
            return bool(self.address.street and self.address.zip_code)
        return False


class CustomerInfoTask(BaseTask):
    """Task for capturing customer information."""

    name: str | None = None
    phone: str | None = None
    email: str | None = None

    def has_contact(self) -> bool:
        """Check if we have at least one contact method."""
        return bool(self.phone or self.email)


class CheckoutTask(BaseTask):
    """Task for order review and confirmation."""

    order_reviewed: bool = False
    subtotal: float = 0.0
    city_tax: float = 0.0
    state_tax: float = 0.0
    tax: float = 0.0  # Total tax
    delivery_fee: float = 0.0
    tip: float = 0.0
    total: float = 0.0
    confirmed: bool = False
    order_number: str | None = None

    def calculate_total(
        self,
        subtotal: float,
        is_delivery: bool = False,
        city_tax_rate: float = 0.0,
        state_tax_rate: float = 0.0,
        delivery_fee: float = 2.99,
    ) -> None:
        """Calculate order totals."""
        self.subtotal = subtotal
        self.city_tax = round(subtotal * city_tax_rate, 2)
        self.state_tax = round(subtotal * state_tax_rate, 2)
        self.tax = self.city_tax + self.state_tax
        self.delivery_fee = delivery_fee if is_delivery else 0.0
        self.total = round(self.subtotal + self.tax + self.delivery_fee + self.tip, 2)

    def generate_order_number(self) -> str:
        """Generate a unique order number."""
        import random
        hex_part = uuid.uuid4().hex[:6].upper()
        digit_suffix = f"{random.randint(0, 99):02d}"
        self.order_number = f"ORD-{hex_part}-{digit_suffix}"
        return self.order_number

    @property
    def short_order_number(self) -> str:
        """Get just the last 2 digits of the order number for easy verbal reference."""
        if self.order_number and "-" in self.order_number:
            return self.order_number.split("-")[-1]
        return self.order_number or ""


class PaymentTask(BaseTask):
    """Task for capturing payment method."""

    method: Literal["in_store", "cash_delivery", "card_link"] | None = None
    payment_link_sent: bool = False
    payment_link_destination: str | None = None  # email or phone
    payment_received: bool = False


# =============================================================================
# Container Tasks
# =============================================================================

class ItemsTask(BaseTask):
    """Container task for all order items."""

    items: list[ItemTask] = Field(default_factory=list)

    def add_item(self, item: ItemTask) -> None:
        """Add an item to the order."""
        self.items.append(item)
        if self.status == TaskStatus.PENDING:
            self.status = TaskStatus.IN_PROGRESS

    def remove_item(self, index: int) -> ItemTask | None:
        """Remove and return item at index."""
        if 0 <= index < len(self.items):
            return self.items.pop(index)
        return None

    def skip_item(self, index: int) -> None:
        """Mark item at index as skipped."""
        if 0 <= index < len(self.items):
            self.items[index].mark_skipped()

    def get_active_items(self) -> list[ItemTask]:
        """Get items that are not skipped."""
        return [item for item in self.items if item.status != TaskStatus.SKIPPED]

    def get_current_item(self) -> ItemTask | None:
        """Get the item currently being worked on (first in_progress)."""
        for item in self.items:
            if item.status == TaskStatus.IN_PROGRESS:
                return item
        return None

    def get_next_pending_item(self) -> ItemTask | None:
        """Get the next pending item."""
        for item in self.items:
            if item.status == TaskStatus.PENDING:
                return item
        return None

    def all_items_complete(self) -> bool:
        """Check if all non-skipped items are complete."""
        active_items = self.get_active_items()
        if not active_items:
            return False
        return all(item.is_complete() for item in active_items)

    def is_complete(self) -> bool:
        """Check if all items are complete."""
        return self.all_items_complete()

    def get_subtotal(self) -> float:
        """Calculate subtotal for all active items."""
        return sum(
            item.unit_price * item.quantity
            for item in self.get_active_items()
        )

    def get_item_count(self) -> int:
        """Get total count of active items."""
        return sum(item.quantity for item in self.get_active_items())


# =============================================================================
# Root Order Task
# =============================================================================

class OrderTask(BaseTask):
    """Root task representing the entire order."""

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    db_order_id: int | None = None  # Database order ID for persistence

    # Sub-tasks
    delivery_method: DeliveryMethodTask = Field(default_factory=DeliveryMethodTask)
    items: ItemsTask = Field(default_factory=ItemsTask)
    customer_info: CustomerInfoTask = Field(default_factory=CustomerInfoTask)
    checkout: CheckoutTask = Field(default_factory=CheckoutTask)
    payment: PaymentTask = Field(default_factory=PaymentTask)

    # Conversation tracking
    conversation_history: list[dict] = Field(default_factory=list)

    # Flow state (moved from FlowState in Phase 4)
    pending_item_ids: list[str] = Field(default_factory=list)  # Items needing input
    pending_field: str | None = None  # Field we're asking about
    last_bot_message: str | None = None  # For context

    # Legacy single-item property for backwards compatibility
    @property
    def pending_item_id(self) -> str | None:
        """Get the first pending item ID (backwards compat)."""
        return self.pending_item_ids[0] if self.pending_item_ids else None

    @pending_item_id.setter
    def pending_item_id(self, value: str | None):
        """Set a single pending item ID (backwards compat)."""
        if value is None:
            self.pending_item_ids = []
        else:
            self.pending_item_ids = [value]

    def is_configuring_item(self) -> bool:
        """Check if we're waiting for input on a specific item or menu inquiry."""
        # Also handle by-pound category selection (no item, just pending_field)
        if self.pending_field == "by_pound_category":
            return True
        return len(self.pending_item_ids) > 0 and self.pending_field is not None

    def is_configuring_multiple(self) -> bool:
        """Check if we're configuring multiple items at once."""
        return len(self.pending_item_ids) > 1

    def clear_pending(self):
        """Clear pending item/field when done configuring."""
        self.pending_item_ids = []
        self.pending_field = None

    def add_message(self, role: str, content: str) -> None:
        """Add a message to conversation history."""
        self.conversation_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def is_complete(self) -> bool:
        """Check if the entire order is complete."""
        return (
            self.items.is_complete()
            and self.delivery_method.is_complete()
            and self.checkout.confirmed
        )

    def get_order_summary(self) -> str:
        """Generate human-readable order summary with consolidated identical items."""
        from collections import defaultdict

        # Group items by their summary string to consolidate identical items
        item_data: dict[str, dict] = defaultdict(lambda: {"count": 0, "total_price": 0.0})
        for item in self.items.get_active_items():
            summary = item.get_summary()
            price = item.unit_price * item.quantity
            item_data[summary]["count"] += 1
            item_data[summary]["total_price"] += price

        if not item_data:
            return "No items in order yet."

        # Build consolidated lines
        lines = []
        for summary, data in item_data.items():
            count = data["count"]
            total_price = data["total_price"]
            if count > 1:
                lines.append(f"- {count}× {summary} — ${total_price:.2f}")
            else:
                lines.append(f"- {summary} — ${total_price:.2f}")

        return "\n".join(lines)

    def get_progress_summary(self) -> dict[str, str]:
        """Get progress summary for each sub-task."""
        def status_emoji(task: BaseTask) -> str:
            if task.status == TaskStatus.COMPLETE:
                return "✅"
            elif task.status == TaskStatus.IN_PROGRESS:
                return "🔄"
            elif task.status == TaskStatus.SKIPPED:
                return "⏭️"
            else:
                return "⏳"

        return {
            "items": f"{status_emoji(self.items)} Items ({len(self.items.get_active_items())})",
            "delivery_method": f"{status_emoji(self.delivery_method)} Delivery Method",
            "customer_info": f"{status_emoji(self.customer_info)} Customer Info",
            "checkout": f"{status_emoji(self.checkout)} Checkout",
            "payment": f"{status_emoji(self.payment)} Payment",
        }
