"""
Container task models for the hierarchical task system.

Contains ItemsTask (container for order items) and OrderTask (root task).
"""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING
import uuid

from pydantic import Field

from .base import BaseTask, TaskStatus
from .order_flow import (
    DeliveryMethodTask,
    CustomerInfoTask,
    CheckoutTask,
    PaymentTask,
)
from .item_tasks import ItemTask, MenuItemTask

if TYPE_CHECKING:
    from orderbot.tasks.schemas import OrderPhase


class ItemsTask(BaseTask):
    """Container task for all order items."""

    items: list[ItemTask] = Field(default_factory=list)

    def add_item(self, item: "ItemTask") -> None:
        """Add an item to the order."""
        self.items.append(item)
        if self.status == TaskStatus.PENDING:
            self.status = TaskStatus.IN_PROGRESS

    def remove_item(self, index: int) -> "ItemTask | None":
        """Remove and return item at index."""
        if 0 <= index < len(self.items):
            return self.items.pop(index)
        return None

    def skip_item(self, index: int) -> None:
        """Mark item at index as skipped."""
        if 0 <= index < len(self.items):
            self.items[index].mark_skipped()

    def _filter_active(self, filter_func: callable = None) -> list["ItemTask"]:
        """Get active items, optionally filtered by a predicate.

        Args:
            filter_func: Optional predicate to further filter active items

        Returns:
            List of active (non-skipped) items, filtered if predicate provided
        """
        active = [item for item in self.items if item.status != TaskStatus.SKIPPED]
        return [i for i in active if filter_func(i)] if filter_func else active

    def get_active_items(self) -> list["ItemTask"]:
        """Get items that are not skipped."""
        return self._filter_active()

    def get_active_menu_items(self) -> list[MenuItemTask]:
        """Get active items that are MenuItemTask instances.

        This is a convenience method for code that needs to filter
        active items to only MenuItemTask (excluding other item types).
        """
        return self._filter_active(lambda i: isinstance(i, MenuItemTask))

    def get_current_item(self) -> "ItemTask | None":
        """Get the item currently being worked on (first in_progress)."""
        for item in self.items:
            if item.status == TaskStatus.IN_PROGRESS:
                return item
        return None

    def get_next_pending_item(self) -> "ItemTask | None":
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

    def get_item_by_id(self, item_id: str) -> "ItemTask | None":
        """Get an item by its ID."""
        for item in self.items:
            if item.id == item_id:
                return item
        return None

    def get_active_item_by_id(self, item_id: str) -> "ItemTask | None":
        """Get an active (non-cancelled) item by its ID."""
        items = self._filter_active(lambda i: i.id == item_id)
        return items[0] if items else None

    # -------------------------------------------------------------------------
    # Bundle operations
    # -------------------------------------------------------------------------

    def get_bundle_children(self, parent_item_id: str) -> list[MenuItemTask]:
        """Get all bundle children for a parent item.

        Args:
            parent_item_id: The parent item's ID

        Returns:
            List of MenuItemTask items that are children of this parent
        """
        return [
            item for item in self.items
            if isinstance(item, MenuItemTask)
            and item.bundle_parent_item_id == parent_item_id
        ]

    def get_bundle_items(self, bundle_id: str) -> list[MenuItemTask]:
        """Get all items in a bundle (parent and children).

        Args:
            bundle_id: The bundle's unique ID

        Returns:
            List of all MenuItemTask items in this bundle
        """
        return [
            item for item in self.items
            if isinstance(item, MenuItemTask)
            and item.bundle_id == bundle_id
        ]

    def remove_item_with_bundle(self, item_id: str) -> list["ItemTask"]:
        """Remove an item and all its bundle children.

        If the item is a bundle parent, also removes all children.
        If the item is a bundle child, only removes that child.

        Args:
            item_id: The item's ID to remove

        Returns:
            List of removed items
        """
        removed = []
        item = self.get_item_by_id(item_id)
        if not item:
            return removed

        # If this is a bundle parent, find and remove all children first
        if isinstance(item, MenuItemTask) and item.is_bundle_parent():
            children = self.get_bundle_children(item_id)
            for child in children:
                idx = self.items.index(child)
                self.items.pop(idx)
                removed.append(child)

        # Remove the item itself
        idx = next((i for i, x in enumerate(self.items) if x.id == item_id), None)
        if idx is not None:
            removed_item = self.items.pop(idx)
            removed.append(removed_item)

        return removed

    def get_unfilled_bundle_slots(self, parent_item_id: str) -> list[str]:
        """Get slot names that haven't been filled for a bundle parent.

        This requires checking what slots are defined for the parent's item type
        vs what children have been added.

        Args:
            parent_item_id: The parent item's ID

        Returns:
            List of slot names that still need to be filled
        """
        parent = self.get_item_by_id(parent_item_id)
        if not parent or not isinstance(parent, MenuItemTask):
            return []

        # Get children and their slots
        children = self.get_bundle_children(parent_item_id)
        filled_slots = {child.bundle_slot for child in children if child.bundle_slot}

        # We need to check what slots are required - this will be done via menu_cache
        # For now, just return what we know (caller will check against required slots)
        return list(filled_slots)


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

    # Parsed items that haven't been added yet (waiting for disambiguation to resolve)
    # When user says "latte and bagel" and latte triggers disambiguation,
    # the bagel ParsedItem is stored here to be processed after disambiguation resolves
    pending_parsed_items: list[dict] = Field(default_factory=list)

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

    # Pending ingredient suggestion when user orders just a modifier (e.g., "I want caramel syrup")
    # Dict with: ingredient (str), suggested_items (list of item names)
    # Used to suggest items that can have this modifier
    pending_ingredient_suggestion: dict | None = None

    # Pending ingredient to apply to the next item added
    # Set when user confirms ingredient suggestion (e.g., "I want caramel syrup" -> "yes" -> "iced coffee")
    # The ingredient name will be applied as a modifier when the next item is added
    pending_ingredient_to_apply: str | None = None

    # Pending item switch when user asks "can you make it X?" and we find a similar item
    # Dict with menu item info: {id, name, base_price, item_type}
    # Used to offer switching from current item to a similar one with requested modifier
    pending_switch_item: dict | None = None

    # Pending item replacement during disambiguation
    # When user says "make it blueberry" and multiple same-type items match,
    # stores the current item's ID so it can be removed after disambiguation resolves
    pending_replace_item_id: str | None = None

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

    # Unmatched token pagination state
    # Used when user mentions a token that doesn't match any option (e.g., "honey" for coffee)
    # Dict with:
    #   - unmatched_text: str - the unmatched token(s) formatted for display
    #   - attr_slug: str - the attribute with the unmatched token
    #   - available_options: list[dict] - options to paginate through
    #   - page: int - current page number (0-indexed)
    #   - item_id: str - the item being configured
    pending_unmatched_pagination: dict | None = None

    # Modifier disambiguation state (stores which item to add modifier to)
    # Used when "cream cheese" matches multiple options (Plain, Scallion, etc.)
    pending_modifier_target_item_index: int | None = None
    pending_modifier_quantity: int | None = None
    # Flag to indicate that pending_modifier_quantity should be ADDED to existing
    # quantity rather than replacing it. Set when user says "add X" to an item
    # that already has that attribute.
    pending_modifier_is_additive: bool = False

    # Order history selection state
    # Used when user asks "what did I order before?" and we show a list
    # Dict with: orders (list of order dicts with items and summary)
    pending_order_history: dict | None = None

    # Reorder item selection state
    # Used when user says "just the bagel from last time" and there are multiple matches
    # List of item dicts from order history matching the user's reference
    pending_reorder_items: list[dict] | None = None

    # Reorder offer confirmation state
    # Used when we show last order details and ask "Want to reorder it?"
    # List of item dicts from the last order that user can confirm to reorder
    pending_reorder_offer_items: list[dict] | None = None

    # Pending dietary follow-up state
    # Used when user asks "is X vegan?" and we offer to show vegan options instead
    # Dict with: dietary_type (str), category (str | None)
    # Example: {"dietary_type": "is_vegan", "category": None}
    pending_dietary_followup: dict | None = None

    # Pending quantity addition state
    # Used when user says "add 3" with multiple item types in cart
    # Stores the quantity to add after disambiguation resolves
    pending_quantity_addition: int | None = None

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
        from orderbot.tasks.pending_fields import PendingField

        # Handle generic item selection (cookies, muffins, etc.) when multiple options presented
        if self.pending_field == PendingField.ITEM_SELECTION:
            return True
        # Handle category inquiry follow-up
        if self.pending_field == PendingField.CATEGORY_INQUIRY:
            return True
        # Handle duplicate item selection when multiple items in cart
        if self.pending_field == PendingField.DUPLICATE_SELECTION:
            return True
        # Handle suggested item confirmation ("Would you like to order one?" -> "yes")
        if self.pending_field == PendingField.CONFIRM_SUGGESTED_ITEM:
            return True
        # Handle modifier selection (disambiguation like "cream cheese" matching multiple options)
        if self.pending_field == PendingField.MODIFIER_SELECTION:
            return True
        # Handle item switch confirmation ("can you make it X?" -> similar item found)
        if self.pending_field == PendingField.CONFIRM_ITEM_SWITCH:
            return True
        # Handle ingredient suggestion confirmation ("I want caramel syrup" -> "yes")
        if self.pending_field == PendingField.CONFIRM_INGREDIENT_SUGGESTION:
            return True
        # Handle dietary follow-up confirmation ("is X vegan?" -> "no" -> "Would you like vegan options?" -> "yes")
        if self.pending_field == PendingField.CONFIRM_DIETARY_FOLLOWUP:
            return True
        # Handle quantity addition selection ("add 3" with multiple item types in cart)
        if self.pending_field == PendingField.QUANTITY_ADDITION_SELECTION:
            return True
        # Handle attribute disambiguation (e.g., "walnut" -> "honey walnut" or "maple raisin walnut")
        if self.pending_attr_disambiguation is not None:
            return True
        return len(self.pending_item_ids) > 0 and self.pending_field is not None

    def clear_pending(self):
        """Clear pending item/field when done configuring."""
        self.pending_item_ids = []
        self.pending_field = None
        self.config_options_page = 0
        self.pending_suggested_item = None
        self.pending_switch_item = None
        self.pending_replace_item_id = None
        self.pending_item_modifiers = {}
        self.pending_attr_disambiguation = None
        self.pending_unmatched_pagination = None
        self.pending_order_history = None
        self.pending_reorder_items = None
        self.pending_reorder_offer_items = None
        self.pending_dietary_followup = None
        self.pending_quantity_addition = None

    def set_phase(self, phase: "OrderPhase") -> None:
        """Set the order phase from an OrderPhase enum.

        Args:
            phase: The OrderPhase enum value to set
        """
        self.phase = phase.value

    def setup_pending_config(self, item_id: str, pending_field: str) -> None:
        """Set up order state for a pending configuration question.

        Consolidates the repeated pattern of setting phase, item id, field, and page.

        Args:
            item_id: The ID of the item being configured
            pending_field: The field we're asking about
        """
        from orderbot.tasks.schemas import OrderPhase
        self.set_phase(OrderPhase.CONFIGURING_ITEM)
        self.pending_item_id = item_id
        self.pending_field = pending_field
        self.config_options_page = 0

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
                lines.append(f"- {count}x {summary} — ${total_price:.2f}")
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
