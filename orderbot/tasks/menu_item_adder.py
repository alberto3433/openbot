"""
Menu Item Adder.

Handles menu-item-name-based addition flow, including looking up items
by name, creating items from lookup results, adding side items, and
applying pending ingredients.

Extracted from item_adder_handler.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from .models import (
    OrderTask,
    MenuItemTask,
    TaskStatus,
)
from .pending_fields import PendingField
from .schemas import OrderPhase, StateMachineResult, Selection
from .attribute_inference import infer_attributes_from_item_name
from .default_ingredients import populate_default_ingredients
from .config_side_choice_handler import SIDE_SLOT_NAME
from .utils.text import normalize_text
from orderbot.cache import menu_cache

if TYPE_CHECKING:
    from .item_adder_handler import ItemAdderHandler

logger = logging.getLogger(__name__)


class MenuItemAdder:
    """Handles menu-item-name-based addition flow.

    Manages looking up items by name, creating items from lookup results,
    adding side items, and applying pending ingredients.
    """

    def __init__(self, parent: "ItemAdderHandler"):
        """Initialize the menu item adder.

        Args:
            parent: The parent ItemAdderHandler providing shared dependencies.
        """
        self._parent = parent

    def add_menu_item(
        self,
        item_name: str,
        quantity: int,
        order: OrderTask,
        attributes: dict | None = None,
        modifications: list[str] | None = None,
    ) -> StateMachineResult:
        """Add a menu item and determine next question.

        Uses DisambiguationHandler for unified disambiguation logic.

        Args:
            item_name: Name of the menu item
            quantity: Number of items to add
            order: Current order task
            attributes: Optional dict of attribute values to pre-fill
            modifications: Optional list of modification strings
        """
        # Ensure quantity is at least 1
        quantity = max(1, quantity)

        # Step 1: Look up menu item with disambiguation handling
        menu_item, disambiguation_result = self._parent.item_lookup_handler.lookup_menu_item_with_disambiguation(
            item_name, quantity, order
        )

        # If disambiguation is needed, return the question
        if disambiguation_result:
            return disambiguation_result

        # If item not found, provide helpful suggestions using hybrid handler
        if not menu_item:
            session_id = order.session_id
            message, category_for_followup, qr = self._parent._unrecognized_handler.get_not_found_response(
                item_name, order=order, session_id=session_id
            )
            if category_for_followup:
                # Track state so "yes" response can list items in this category
                order.pending_field = PendingField.CATEGORY_INQUIRY
                order.pending_config_queue = [category_for_followup]
            return StateMachineResult(
                message=message,
                order=order,
                quick_replies=qr or None,
            )

        # Step 2: Create the item using existing logic
        return self._create_menu_item_from_lookup(
            menu_item=menu_item,
            item_name=item_name,
            quantity=quantity,
            order=order,
            attributes=attributes,
            modifications=modifications,
        )

    def _create_menu_item_from_lookup(
        self,
        menu_item: dict,
        item_name: str,
        quantity: int,
        order: OrderTask,
        attributes: dict | None = None,
        modifications: list[str] | None = None,
    ) -> StateMachineResult:
        """Create a menu item from lookup result.

        Args:
            menu_item: Menu item dict from lookup
            item_name: Original item name from user
            quantity: Number of items to create
            order: Current order task
            attributes: Optional dict of attribute values to pre-fill
            modifications: Optional list of modification strings
        """
        # Use the canonical name from menu if found
        canonical_name = menu_item.get("name", item_name)
        price = menu_item.get("base_price", 0.0)
        menu_item_id = menu_item.get("id")
        category = menu_item.get("item_type", "")  # item_type slug like "spread_sandwich"

        # Check if item type has component slots (data-driven, e.g., omelette includes a side)
        has_component_slots = menu_cache.item_type_has_component_slots(category) if category else False

        # Check if it uses DB-driven configuration (item types with configurable attributes)
        # Note: has_component_slots items are handled separately and return early
        uses_db_config = category and category in menu_cache.get_configurable_item_types()

        logger.info(
            "Menu item check: canonical_name='%s', category='%s', has_component_slots=%s, uses_db_config=%s, quantity=%d",
            canonical_name,
            category,
            has_component_slots,
            uses_db_config,
            quantity,
        )

        # Determine the menu item type for tracking
        if has_component_slots:
            item_type = category  # Use the actual category slug (e.g., "omelette")
        elif uses_db_config:
            item_type = category  # "deli_sandwich", "egg_sandwich", "fish_sandwich", or "spread_sandwich"
        else:
            item_type = None

        # Create the requested quantity of items
        first_item = None
        for i in range(quantity):
            item = MenuItemTask(
                menu_item_name=canonical_name,
                menu_item_id=menu_item_id,
                unit_price=price,
                menu_item_type=item_type,
                modifications=modifications or [],  # User modifications like "with mayo and mustard"
            )
            # Populate default ingredients for items that have them defined
            # This must happen before applying user selections so user selections
            # can replace defaults (e.g., "BEC with swiss" replaces cheddar)
            # Check if item has default ingredients
            if menu_item_id:
                populate_default_ingredients(item)
            # Apply pre-filled attributes
            if attributes:
                for attr_name, attr_value in attributes.items():
                    if attr_value is not None:
                        item[attr_name] = attr_value

            # Apply pending ingredient from ingredient suggestion flow
            # (e.g., "I want caramel syrup" -> "yes" -> "iced coffee" -> apply caramel)
            # Only apply to the first item (first_item is None means this is the first)
            if first_item is None:
                self._apply_pending_ingredient(item, order, item_type, canonical_name)

            # Infer attributes from item name (data-driven, e.g., "Hot Coffee" -> temperature=hot)
            infer_attributes_from_item_name(item)
            item.mark_in_progress()
            order.items.add_item(item)
            if first_item is None:
                first_item = item

        logger.info("Added %d menu item(s): %s (price: $%.2f each, id: %s, attrs=%s, mods=%s)", quantity, canonical_name, price, menu_item_id, attributes, modifications)

        if has_component_slots:
            # Set state to wait for component slot selection (applies to first item, others will be configured after)
            order.phase = OrderPhase.CONFIGURING_ITEM
            order.pending_item_id = first_item.id
            # Get component slot configuration from DB (e.g., "side" slot)
            side_slot = menu_cache.get_component_slot(category, SIDE_SLOT_NAME)
            order.pending_field = PendingField.SIDE_CHOICE
            # Use prompt text from DB or fallback
            question = (
                side_slot.get("prompt_text")
                if side_slot
                else f"What side would you like with your {canonical_name}?"
            )
            # Build quick replies from component slot options (data-driven)
            side_options = menu_cache.get_component_slot_options(category, SIDE_SLOT_NAME)
            qr = [{"label": o.get("display_name", o.get("allowed_item_type", "")), "value": o.get("display_name", o.get("allowed_item_type", ""))} for o in side_options] if side_options else None
            return StateMachineResult(
                message=question,
                order=order,
                quick_replies=qr,
            )
        elif uses_db_config and self._parent.menu_item_handler:
            # For deli/egg sandwiches, use DB-driven configuration with customization checkpoint
            # Capture any attributes mentioned in the initial order
            # Strip the canonical menu item name from user input to prevent
            # words in the item name from falsely matching attribute options
            # e.g., "Tofu Nova Sandwich" -> "Nova" matching "Nova Scotia Salmon"
            capture_input = item_name
            if canonical_name:
                idx = item_name.lower().find(canonical_name.lower())
                if idx >= 0:
                    capture_input = (item_name[:idx] + item_name[idx + len(canonical_name):]).strip()
            self._parent.menu_item_handler.capture_attributes_from_input(capture_input, first_item)
            # Start the configuration flow
            return self._parent.menu_item_handler.get_first_question(first_item, order)
        else:
            # Mark all items complete (non-omelettes don't need configuration)
            for item in order.items.items:
                if isinstance(item, MenuItemTask) and item.menu_item_name == canonical_name and item.status == TaskStatus.IN_PROGRESS:
                    item.mark_complete()
            return self._parent._get_next_question(order)

    def add_side_item(
        self,
        side_item_name: str,
        quantity: int,
        order: OrderTask,
    ) -> tuple[str | None, str | None]:
        """Add a side item to the order without returning a response.

        Used when a side item is ordered alongside another item (e.g., "bagel with a side of sausage").

        Returns:
            Tuple of (canonical_name, error_message).
            If successful: (canonical_name, None)
            If item not found: (None, error_message)
        """
        quantity = max(1, quantity)

        # Look up the side item in the menu
        menu_item = self._parent.menu_lookup.lookup_menu_item(side_item_name)

        # If item not found, return error message using hybrid handler
        if not menu_item:
            logger.warning("Side item not found: '%s' - rejecting", side_item_name)
            message, _, _qr = self._parent._unrecognized_handler.get_not_found_response(
                side_item_name, order=order
            )
            return (None, message)

        # Use canonical name and price from menu
        canonical_name = menu_item.get("name", side_item_name)
        price = menu_item.get("base_price", 0.0)
        menu_item_id = menu_item.get("id")

        # Get item type from DB lookup
        item_type = menu_item.get("item_type")

        # Create the side item(s)
        for _ in range(quantity):
            item = MenuItemTask(
                menu_item_name=canonical_name,
                menu_item_id=menu_item_id,
                unit_price=price,
                menu_item_type=item_type,
            )
            item.mark_complete()  # Side items don't need configuration
            order.items.add_item(item)

        logger.info("Added %d side item(s): %s (price: $%.2f each)", quantity, canonical_name, price)
        return (canonical_name, None)

    def _apply_pending_ingredient(
        self,
        item: MenuItemTask,
        order: OrderTask,
        item_type: str | None,
        canonical_name: str,
    ) -> None:
        """Apply pending ingredient from ingredient suggestion flow.

        When a user orders a modifier without an item (e.g., "I want caramel syrup"),
        then confirms they want to add it to a drink (e.g., "yes"), then orders the item
        (e.g., "iced coffee"), this method applies the pending ingredient to the new item.

        The pending ingredient is stored in order.pending_ingredient_to_apply and is
        cleared after being applied to prevent it from being applied to subsequent items.

        Args:
            item: The MenuItemTask to apply the ingredient to.
            order: The OrderTask containing the pending ingredient.
            item_type: The item type slug for attribute lookup.
            canonical_name: The menu item name for logging.
        """
        if not order.pending_ingredient_to_apply or not self._parent.menu_item_handler:
            return

        pending_ingredient = order.pending_ingredient_to_apply
        # Clear it now so it's not applied to subsequent items
        order.pending_ingredient_to_apply = None

        # Find the attribute and option that match this ingredient
        # Search through item type's attributes for an option matching the ingredient
        attrs = menu_cache.get_item_type_attributes(item_type) if item_type else {}
        pending_lower = normalize_text(pending_ingredient)
        pending_slug = pending_lower.replace(' ', '_')
        found_attr_slug = None
        found_option = None

        for attr_slug_iter, attr_config in attrs.items():
            options = attr_config.get('options', [])
            for opt in options:
                opt_slug = opt.get('slug', '').lower()
                opt_display = opt.get('display_name', '').lower()
                opt_aliases = [a.lower() for a in (opt.get('aliases') or [])]
                # Match by slug, display name, or alias
                if (opt_slug == pending_slug or
                    opt_display == pending_lower or
                    pending_lower in opt_aliases):
                    found_attr_slug = attr_slug_iter
                    found_option = opt
                    break
            if found_option:
                break

        if found_attr_slug and found_option:
            # Get the correct slug and price from the matched option
            option_slug = found_option.get('slug', pending_ingredient)
            option_price = found_option.get('price_modifier', 0.0)
            # Create and apply the selection
            pending_selection = Selection(
                slug=option_slug,
                category=found_attr_slug,
                quantity=1,
                price=option_price,
                display_name=found_option.get('display_name'),
            )
            self._parent.menu_item_handler._apply_selections(item, [pending_selection])
            logger.info(
                "Applied pending ingredient '%s' to %s (attr=%s, price=$%.2f)",
                pending_ingredient, canonical_name, found_attr_slug, option_price
            )
        else:
            logger.warning(
                "Could not find attribute for pending ingredient '%s' on item type '%s'",
                pending_ingredient, item_type
            )
