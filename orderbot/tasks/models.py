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
from typing import Any, Literal
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
    """Base class for order items."""

    item_type: str
    quantity: int = 1
    unit_price: float = 0.0

    def get_display_name(self) -> str:
        """Get display name for this item."""
        raise NotImplementedError

    def get_summary(self) -> str:
        """Get a summary description of this item."""
        raise NotImplementedError


class MenuItemTask(ItemTask):
    """Task for a menu item ordered by name (e.g., 'The Chipotle Egg Omelette').

    All customizations (attribute choices and modifier add-ons) are stored in
    a unified `selections` list using the Selection format.

    Access methods:
    - get_selection(category): Get first selection for a category
    - get_selections(category): Get all selections for a category
    - get_selection_value(category): Get slug of first selection
    - has_selection(category): Check if any selection exists
    - add_selection(...): Add a new selection
    - remove_selection(...): Remove selection(s)

    Examples:
        item.add_selection("everything", "bread", display_name="Everything")
        item.add_selection("yes", "toasted", display_name="Toasted")
        item.add_selection("bacon", "protein", quantity=2, price=1.50)

        bread = item.get_selection_value("bread")  # "everything"
        is_toasted = item.get_selection_value("toasted") == "yes"
    """

    item_type: Literal["menu_item"] = "menu_item"

    # Menu item fields
    menu_item_name: str  # The name of the menu item
    menu_item_id: int | None = None  # Database ID if matched
    menu_item_type: str | None = None  # Type slug (e.g., "omelette", "sandwich")
    modifications: list[str] = Field(default_factory=list)  # User modifications
    removed_ingredients: list[str] = Field(default_factory=list)  # Default ingredients that were removed

    is_signature: bool = False  # Whether this is a signature/featured menu item

    # Unified selections list - all customizations (attributes and modifiers)
    # Import Selection type for type hint
    selections: list[dict] = Field(default_factory=list)  # list[Selection] but stored as dict for serialization

    # Track if customization checkpoint has been offered
    customization_offered: bool = False

    # Side item linking - if this item is a side (e.g., bagel with omelette),
    # this holds the ID of the parent item
    side_of_item_id: str | None = None

    # -------------------------------------------------------------------------
    # Side item helpers
    # -------------------------------------------------------------------------

    def is_side(self) -> bool:
        """Check if this item is a side of another item."""
        return self.side_of_item_id is not None

    # -------------------------------------------------------------------------
    # Selection access methods
    # -------------------------------------------------------------------------

    def get_selection(self, category: str) -> dict | None:
        """Get first selection for a category (for single-select attributes).

        Args:
            category: The category to look up (e.g., "bread", "size", "toasted")

        Returns:
            Selection dict or None if not found
        """
        for sel in self.selections:
            if sel.get("category") == category:
                return sel
        return None

    def get_selections(self, category: str) -> list[dict]:
        """Get all selections for a category (for multi-select).

        Args:
            category: The category to filter by

        Returns:
            List of Selection dicts matching the category
        """
        return [sel for sel in self.selections if sel.get("category") == category]

    def get_selection_value(self, category: str) -> str | None:
        """Get the slug of the first selection for a category.

        Convenience method for single-select attributes.

        Args:
            category: The category to look up

        Returns:
            The slug value or None if not found
        """
        sel = self.get_selection(category)
        return sel.get("slug") if sel else None

    def has_selection(self, category: str) -> bool:
        """Check if any selection exists for a category.

        Args:
            category: The category to check

        Returns:
            True if at least one selection exists for this category
        """
        return any(sel.get("category") == category for sel in self.selections)

    def add_selection(
        self,
        slug: str,
        category: str,
        quantity: int = 1,
        price: float = 0.0,
        display_name: str | None = None,
    ) -> None:
        """Add a selection to the item.

        Args:
            slug: Selected option identifier (e.g., "plain", "bacon", "yes")
            category: What type of selection (e.g., "bread", "protein", "toasted")
            quantity: How many (default 1)
            price: Price contribution per unit (default 0.0)
            display_name: Human-readable name (looked up from cache if not provided)
        """
        # Check if already present (same slug and category)
        if any(s.get("slug") == slug and s.get("category") == category for s in self.selections):
            return

        # Look up display name from database if not provided
        if not display_name:
            try:
                from orderbot.menu_data_cache import menu_cache
                # Try ingredient lookup first
                display_name = menu_cache.get_ingredient_display_name(slug)
                if not display_name:
                    # Try attribute option lookup
                    display_name = menu_cache.get_attribute_option_display_name(category, slug)
            except Exception:
                pass

        # Fall back to title-cased slug if lookup failed
        if not display_name:
            # Handle boolean slugs specially
            if slug == "yes":
                display_name = category.replace("_", " ").title()
            elif slug == "no":
                display_name = f"Not {category.replace('_', ' ').title()}"
            else:
                display_name = slug.replace("_", " ").title()

        # Build selection entry
        selection = {
            "slug": slug,
            "category": category,
            "quantity": quantity,
            "price": price,
            "display_name": display_name,
        }

        self.selections.append(selection)

        # Update unit_price if selection has a price
        if price > 0:
            self.unit_price = (self.unit_price or 0.0) + (price * quantity)

    def remove_selection(self, category: str, slug: str | None = None) -> bool:
        """Remove selection(s) by category and optionally slug.

        Args:
            category: The category to remove from
            slug: If provided, only remove selection with this slug.
                  If None, removes ALL selections for this category.

        Returns:
            True if any selections were removed, False otherwise
        """
        removed_any = False
        i = 0
        while i < len(self.selections):
            sel = self.selections[i]
            if sel.get("category") == category:
                if slug is None or sel.get("slug") == slug:
                    removed = self.selections.pop(i)
                    # Subtract price from unit_price
                    price = removed.get("price", 0)
                    if price > 0:
                        self.unit_price -= price * removed.get("quantity", 1)
                    removed_any = True
                    continue  # Don't increment i since we removed an element
            i += 1
        return removed_any

    def update_selection_quantity(self, category: str, slug: str, quantity: int) -> bool:
        """Update quantity for an existing selection.

        Args:
            category: The category to find
            slug: The slug to find
            quantity: New quantity

        Returns:
            True if found and updated, False otherwise
        """
        for sel in self.selections:
            if sel.get("category") == category and sel.get("slug") == slug:
                old_quantity = sel.get("quantity", 1)
                price = sel.get("price", 0)
                # Update unit_price
                if price > 0:
                    self.unit_price -= price * old_quantity
                    self.unit_price += price * quantity
                sel["quantity"] = quantity
                return True
        return False

    # -------------------------------------------------------------------------
    # Dict-style access API (primary interface)
    # -------------------------------------------------------------------------

    @property
    def attribute_values(self) -> dict[str, Any]:
        """Get selection values as a dict for display/serialization.

        Returns a dict with category->value mapping. Used for logging, display, and
        backward compatibility with code that reads attribute_values.
        """
        result: dict[str, Any] = {}
        for sel in self.selections:
            category = sel.get("category", "")
            slug = sel.get("slug", "")
            display_name = sel.get("display_name")
            price = sel.get("price", 0)

            # For boolean categories, convert yes/no to True/False
            if slug == "yes":
                result[category] = True
            elif slug == "no":
                result[category] = False
            else:
                # Check if multi-select (already have a value for this category)
                if category in result:
                    existing = result[category]
                    if isinstance(existing, list):
                        existing.append(slug)
                    else:
                        result[category] = [existing, slug]
                else:
                    result[category] = slug

            # Store _selections for display name lookup (backward compat)
            selections_key = f"{category}_selections"
            if selections_key not in result:
                result[selections_key] = []
            result[selections_key].append({"slug": slug, "display_name": display_name})

            # Store price
            if price > 0:
                result[f"{category}_price"] = price

        return result

    @attribute_values.setter
    def attribute_values(self, value: dict[str, Any]) -> None:
        """Set selection values from a dict. Used for bulk initialization."""
        # Clear existing selections that would be overwritten
        # This is for backward compat when code sets attribute_values directly
        for key, val in value.items():
            # Skip metadata keys
            if key.endswith("_selections") or key.endswith("_price") or key.endswith("_upcharge"):
                continue

            # Remove existing selections for this category
            self.remove_selection(key)

            # Add new selection(s)
            if isinstance(val, bool):
                self.add_selection("yes" if val else "no", key)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        self.add_selection(item, key)
            elif val is not None:
                self.add_selection(str(val), key)

    def __getitem__(self, key: str) -> Any:
        """Get selection value by category: item["size"], item["bread"], etc."""
        return self.attribute_values.get(key)

    def __setitem__(self, key: str, value: Any) -> None:
        """Set selection by category: item["size"] = "large"."""
        # Remove existing selection for this category
        self.remove_selection(key)

        if value is None:
            return  # Just remove, don't add

        # Add new selection
        if isinstance(value, bool):
            self.add_selection("yes" if value else "no", key)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    self.add_selection(item, key)
        else:
            self.add_selection(str(value), key)

    def __delitem__(self, key: str) -> None:
        """Delete selection by category: del item["size"]."""
        self.remove_selection(key)

    def __contains__(self, key: str) -> bool:
        """Check if selection exists: "size" in item."""
        return self.has_selection(key)

    def get(self, key: str, default: Any = None) -> Any:
        """Get selection value with default."""
        val = self.attribute_values.get(key)
        return val if val is not None else default

    # -------------------------------------------------------------------------
    # Attribute query method (data-driven)
    # -------------------------------------------------------------------------

    def has_attribute(self, attr_slug: str) -> bool:
        """Check if this item type has a specific attribute defined in the database.

        Args:
            attr_slug: The attribute slug to check for

        Returns:
            True if this item type has the specified attribute, False otherwise.
        """
        if not self.menu_item_type:
            return False
        from orderbot.menu_data_cache import menu_cache
        attrs = menu_cache.get_item_type_attributes(self.menu_item_type)

        if attr_slug in attrs:
            return True

        # Check legacy aliases
        from orderbot.tasks.field_config import _FIELD_TO_SLUG_MAP
        field_map = _FIELD_TO_SLUG_MAP.get(self.menu_item_type, {})
        db_slug = field_map.get(attr_slug)
        if db_slug and db_slug in attrs:
            return True

        return False

    # -------------------------------------------------------------------------
    # Display helpers
    # -------------------------------------------------------------------------

    def get_display_name(self) -> str:
        """Get display name for this menu item."""
        return self.menu_item_name

    def get_summary(self) -> str:
        """Get a summary description of this menu item.

        Returns uniform summary in format:
        "{quantity}x {menu_item_name}, {selection1}, {selection2}, ..."

        Examples:
            "Everything Bagel, Toasted, Scallion Cream Cheese"
            "Latte, Large, Iced, Oat Milk"
            "2x Turkey Club, Sourdough, Bacon"
        """
        base_name = self.get_display_name()
        if self.quantity > 1:
            base_name = f"{self.quantity}x {base_name}"

        # Collect display names from selections
        displays = []
        for sel in self.selections:
            slug = sel.get("slug", "")
            display_name = sel.get("display_name", "")
            quantity = sel.get("quantity", 1)

            # Skip "no" selections (user declined)
            if slug == "no":
                continue

            if display_name:
                if quantity > 1:
                    displays.append(f"{quantity}x {display_name}")
                else:
                    displays.append(display_name)

        # Build final summary
        if displays:
            summary = f"{base_name}, {', '.join(displays)}"
        else:
            summary = base_name

        # Add modifications in parentheses
        if self.modifications:
            summary += f" ({', '.join(self.modifications)})"

        # Add removed ingredients
        if self.removed_ingredients:
            removed_parts = [f"no {ing}" for ing in self.removed_ingredients]
            summary += f" ({', '.join(removed_parts)})"

        return summary

    def get_missing_customizations(self) -> list[str]:
        """Get list of missing required customizations.

        Uses data-driven approach: check for {side_choice}_choice field dynamically.
        """
        missing = []
        if self.get_selection_value("requires_side_choice") == "yes" and not self.has_selection("side_choice"):
            missing.append("side_choice")
        # Check if side_choice type needs a specific choice (e.g., bagel_choice for bagel)
        side_choice = self.get_selection_value("side_choice")
        if side_choice:
            choice_field = f"{side_choice}_choice"
            if not self.has_selection(choice_field):
                missing.append(choice_field)
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
        delivery_fee: float = 0.0,
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

    def get_item_by_id(self, item_id: str) -> ItemTask | None:
        """Get an item by its ID."""
        for item in self.items:
            if item.id == item_id:
                return item
        return None


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

    # Order-level special instructions (extracted once per message, not per-item)
    special_instructions: str | None = None

    # Conversation tracking
    conversation_history: list[dict] = Field(default_factory=list)

    # Flow state (moved from FlowState in Phase 4)
    phase: str = "greeting"  # Current order phase (stored as string to avoid circular imports)
    pending_item_ids: list[str] = Field(default_factory=list)  # Items needing input
    pending_field: str | None = None  # Field we're asking about
    last_bot_message: str | None = None  # For context

    # Queue of items that need configuration after the current one is done
    # Each entry is a dict with: item_id, item_type
    pending_config_queue: list[dict] = Field(default_factory=list)

    # Modifiers stored during item disambiguation
    # When user says "large iced oat milk latte" and we ask "Latte or Seasonal Matcha Latte?",
    # we store the modifiers here so they can be applied when user clarifies the item type
    # Works for any item type (coffee, bagels, etc.), not just beverages
    pending_item_modifiers: dict = Field(default_factory=dict)

    # Unknown item request - stores the item name user asked for that doesn't exist
    # Used to show "Sorry, we don't have X" message
    unknown_item_request: str | None = Field(default=None)

    # Generic menu item options for disambiguation (cookies, muffins, etc.)
    # Used when user says "cookies" and there are multiple cookie types
    pending_item_options: list[dict] = Field(default_factory=list)

    # Quantity stored during item disambiguation
    pending_item_quantity: int = Field(default=1)

    # Pending modifier change clarification
    # Used when user says "change it to blueberry" and we need to clarify bagel vs spread
    # Dict with: new_value, possible_attributes (list of attribute slugs), item_id
    pending_change_clarification: dict | None = None

    # Pending duplicate selection
    # Used when user says "another one" with multiple items in cart
    # Dict with: count (int - how many to duplicate), items (list of item summaries for question)
    pending_duplicate_selection: dict | None = None

    # Pending "same thing" disambiguation
    # Used when user says "same thing" and we have both a previous order AND items in cart
    # Dict with: has_previous_order (bool), cart_items (list of item summaries)
    pending_same_thing_clarification: dict | None = None

    # Pending suggested item from menu inquiry
    # Set when bot describes an item and asks "Would you like to order one?"
    # Stores the menu item name (e.g., "The Lexington") for confirmation
    pending_suggested_item: str | None = None

    # Menu query pagination state for "show more" functionality
    # Dict with: category (str), offset (int), total_items (int)
    # Used when user asks "what other X do you have?" or "more X"
    menu_query_pagination: dict | None = None

    # Ingredient search pagination state for "what else" follow-up
    # Dict with: ingredient (str), matches (list of item dicts), offset (int)
    # Used when user says "chicken" and we show items, then they say "what else"
    pending_ingredient_search: dict | None = None

    # Configuration options page for "what else" during field configuration
    # Tracks which page of options (e.g., bagel types) we're showing
    # 0 = first page (default), 1 = second page, etc.
    config_options_page: int = 0

    # Names of items in a multi-item order that need configuration
    # Used to build final summary like "Great, both toasted. Anything else?"
    multi_item_config_names: list[str] = Field(default_factory=list)

    # Transient error storage for _add_parsed_item -> _process_items communication
    # This is a transient field that should not be serialized
    last_add_error: Any | None = Field(default=None, exclude=True)

    # Generic attribute disambiguation state for MenuItemConfigHandler
    # Used when user input matches multiple options for an attribute (e.g., "walnut" matches
    # "honey walnut" and "maple raisin walnut" for cream cheese spread)
    # Dict with:
    #   - options: list[dict] - the options to choose from
    #   - attr_slug: str - the attribute being disambiguated
    #   - modifiers: dict - extracted modifiers to apply after resolution
    #   - item_id: str - the item being configured
    pending_attr_disambiguation: dict | None = None

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
        # Handle drink selection when multiple options were presented
        if self.pending_field == "drink_selection":
            return True
        # Handle drink type selection (disambiguation like "latte" matching multiple items)
        if self.pending_field == "drink_type":
            return True
        # Handle generic item selection (cookies, muffins, etc.) when multiple options presented
        if self.pending_field == "item_selection":
            return True
        # Handle category inquiry follow-up
        if self.pending_field == "category_inquiry":
            return True
        # Handle duplicate item selection when multiple items in cart
        if self.pending_field == "duplicate_selection":
            return True
        # Handle suggested item confirmation ("Would you like to order one?" -> "yes")
        if self.pending_field == "confirm_suggested_item":
            return True
        # Handle attribute disambiguation (e.g., "walnut" -> "honey walnut" or "maple raisin walnut")
        if self.pending_attr_disambiguation is not None:
            return True
        return len(self.pending_item_ids) > 0 and self.pending_field is not None

    def is_configuring_multiple(self) -> bool:
        """Check if we're configuring multiple items at once."""
        return len(self.pending_item_ids) > 1

    def clear_pending(self):
        """Clear pending item/field when done configuring."""
        self.pending_item_ids = []
        self.pending_field = None
        self.config_options_page = 0
        self.pending_suggested_item = None
        self.pending_item_modifiers = {}
        self.pending_attr_disambiguation = None

    def clear_menu_pagination(self):
        """Clear menu query pagination state."""
        self.menu_query_pagination = None

    def set_menu_pagination(self, category: str, offset: int, total_items: int):
        """Set menu query pagination state for 'show more' functionality."""
        self.menu_query_pagination = {
            "category": category,
            "offset": offset,
            "total_items": total_items,
        }

    def get_menu_pagination(self) -> dict | None:
        """Get current menu query pagination state."""
        return self.menu_query_pagination

    def queue_item_for_config(
        self,
        item_id: str,
        item_type: str,
        item_name: str | None = None,
        pending_field: str | None = None,
    ) -> None:
        """Add an item to the configuration queue.

        Args:
            item_id: The item's unique ID
            item_type: Type of item (bagel, coffee, signature_item, etc.)
            item_name: Display name for abbreviated follow-up questions
            pending_field: The field to configure (toasted, bread, etc.)
        """
        # Don't add duplicates - handle mixed types (strings from category inquiry, dicts from item config)
        for entry in self.pending_config_queue:
            if isinstance(entry, dict) and entry.get("item_id") == item_id:
                return
        self.pending_config_queue.append({
            "item_id": item_id,
            "item_type": item_type,
            "item_name": item_name,
            "pending_field": pending_field,
        })

    def pop_next_config_item(self) -> dict | None:
        """Pop the next config item (dict) from the queue, skipping category strings."""
        while self.pending_config_queue:
            entry = self.pending_config_queue.pop(0)
            if isinstance(entry, dict) and "item_id" in entry:
                return entry
            # Skip non-dict entries (category strings from by_pound inquiry)
        return None

    def has_queued_config_items(self) -> bool:
        """Check if there are item config dicts waiting in the queue."""
        return any(isinstance(e, dict) and "item_id" in e for e in self.pending_config_queue)

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
