"""
Item Adder Handler for Order State Machine.

This module handles adding new items to orders, including menu items,
side items, and bagels with their configurations.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
from typing import Callable, TYPE_CHECKING

from .models import (
    OrderTask,
    MenuItemTask,
    TaskStatus,
)
from .schemas import OrderPhase, StateMachineResult, ExtractedModifiers
from .handler_config import HandlerConfig
from .disambiguation_handler import DisambiguationHandler
from ..menu_data_cache import menu_cache

logger = logging.getLogger(__name__)


class ItemAdderHandler:
    """
    Handles adding items to orders.

    Manages menu item lookup, price calculation, and item creation
    for menu items, side items, and bagels.
    """

    def __init__(
        self,
        config: HandlerConfig,
        configure_next_incomplete_bagel: Callable[[OrderTask], StateMachineResult] | None = None,
        configure_next_incomplete_coffee: Callable[[OrderTask], StateMachineResult] | None = None,
        menu_item_handler: "MenuItemConfigHandler | None" = None,
    ):
        """
        Initialize the item adder handler.

        Args:
            config: HandlerConfig with shared dependencies.
            configure_next_incomplete_bagel: Callback to configure bagels.
            configure_next_incomplete_coffee: Callback to configure coffee/beverages.
            menu_item_handler: Handler for menu item configuration (deli sandwiches, etc.).
        """
        self.menu_lookup = config.menu_lookup
        self.pricing = config.pricing
        self._get_next_question = config.get_next_question

        # Handler-specific callbacks
        self._configure_next_incomplete_bagel = configure_next_incomplete_bagel
        self._configure_next_incomplete_coffee = configure_next_incomplete_coffee
        self.menu_item_handler = menu_item_handler
        self._menu_data: dict = {}

        # Generic disambiguation handler
        self.disambiguation_handler = DisambiguationHandler()

    def _infer_attributes_from_item_name(self, item: MenuItemTask) -> None:
        """
        Infer attribute values from the menu item name using database configuration.

        This is a data-driven approach that scans the item name against attribute
        options and pre-populates matching values. This prevents asking questions
        that are already answered by the item name.

        For example:
        - "Hot Coffee" → temperature = "hot" (if "hot" is an option for temperature)
        - "Iced Latte" → temperature = "iced"
        - "Decaf Americano" → decaf = True (if decaf is a boolean attribute)

        Args:
            item: The MenuItemTask to update with inferred attribute values
        """
        logger.info(
            "INFER_ATTRIBUTES: Called for item_name='%s', item_type='%s'",
            item.menu_item_name, item.menu_item_type
        )
        if not item.menu_item_type or not item.menu_item_name:
            logger.info("INFER_ATTRIBUTES: Skipping - missing type or name")
            return

        # Get all attributes for this item type from the database
        attrs = menu_cache.get_item_type_attributes(item.menu_item_type)
        if not attrs:
            logger.info("INFER_ATTRIBUTES: No attributes found for type '%s'", item.menu_item_type)
            return

        logger.info("INFER_ATTRIBUTES: Found %d attributes for '%s'", len(attrs), item.menu_item_type)
        item_name_lower = item.menu_item_name.lower()

        for attr_slug, attr_data in attrs.items():
            # Skip if attribute is already set
            if attr_slug in item.attribute_values:
                continue

            options = attr_data.get("options", [])
            input_type = attr_data.get("input_type", "single_select")

            if attr_slug == "temperature":
                logger.info(
                    "INFER_ATTRIBUTES: Checking temperature attr, input_type=%s, options=%s",
                    input_type, [o.get("slug") for o in options]
                )

            # For boolean attributes, check if the attribute name appears in item name
            if input_type == "boolean":
                attr_display = attr_data.get("display_name", attr_slug).lower()
                if attr_display in item_name_lower:
                    item.attribute_values[attr_slug] = True
                    logger.info(
                        "Inferred %s=True from item name '%s'",
                        attr_slug, item.menu_item_name
                    )
                continue

            # For select attributes, check if any option appears in item name
            for opt in options:
                opt_slug = opt.get("slug", "")
                opt_display = opt.get("display_name", "").lower()
                opt_slug_readable = opt_slug.replace("_", " ").lower()

                # Check if option slug or display name appears in item name
                if (opt_slug_readable in item_name_lower or
                        opt_display in item_name_lower or
                        opt_slug.lower() in item_name_lower):
                    # Set the attribute value
                    item.attribute_values[attr_slug] = opt_slug
                    logger.info(
                        "Inferred %s='%s' from item name '%s'",
                        attr_slug, opt_slug, item.menu_item_name
                    )
                    break  # Only match first option per attribute

    @property
    def menu_data(self) -> dict:
        return self._menu_data

    @menu_data.setter
    def menu_data(self, value: dict) -> None:
        self._menu_data = value or {}

    def add_item(
        self,
        item_type: str,
        order: OrderTask,
        quantity: int = 1,
        **kwargs,
    ) -> StateMachineResult:
        """
        Unified item adder using data-driven configuration.

        All item types flow through _create_configurable_item() which handles
        DB-driven configuration. Items that need disambiguation (matching multiple
        menu items) use _lookup_menu_item_with_disambiguation().

        Args:
            item_type: The item type slug (e.g., "bagel", "sized_beverage", "deli_sandwich")
            order: The current order
            quantity: Number of items to add (default 1)
            **kwargs: Item-specific parameters:
                - item_name: Menu item name (e.g., "Iced Latte", "Turkey Club")
                - Any attribute values to pre-fill (bread, toasted, size, milk, etc.)
                - modifications, bagel_choice (for menu items with bagel choice)
                - extracted_modifiers (for any item with modifiers)

        Returns:
            StateMachineResult with next question or confirmation
        """
        quantity = max(1, quantity)

        # Get item name from kwargs - use standardized "item_name" parameter
        item_name = kwargs.get("item_name") or item_type

        # Check if this needs disambiguation (any item type, not just beverages)
        # Disambiguation is needed when:
        # 1. Item name is a category reference (e.g., "coffee" matches multiple items)
        # 2. Item name is empty but we have an item_type (generic request)
        item_name_lower = (item_name or "").lower().strip()
        category_ref = menu_cache.is_category_reference(item_name_lower) if item_name_lower else None
        is_category_reference = category_ref is not None
        is_empty_name = not item_name_lower

        # Generic modifier storage for disambiguation (stores ALL non-None kwargs)
        # This preserves modifiers like size, milk, sweetener during disambiguation
        item_modifiers = {k: v for k, v in kwargs.items() if v is not None}
        item_modifiers["quantity"] = quantity

        # Trigger disambiguation for category references or empty names with item_type
        if is_category_reference or is_empty_name:
            menu_item, disambiguation_result = self._lookup_menu_item_with_disambiguation(
                item_name=item_name_lower or "item",
                quantity=quantity,
                order=order,
                modifiers=item_modifiers,
                pending_field="item_selection",
                item_type_filter=category_ref if is_category_reference else item_type,
            )

            if disambiguation_result:
                return disambiguation_result

            if menu_item:
                canonical_name = menu_item.get("name", item_name)
                item_name = canonical_name
                item_type = menu_item.get("item_type") or item_type
                kwargs["item_name"] = canonical_name
            elif item_name_lower and not is_category_reference:
                # Unknown item - mark for error handling
                order.pending_field = "item_selection"
                order.unknown_item_request = item_name
                order.phase = OrderPhase.CONFIGURING_ITEM.value
                return StateMachineResult(message="", order=order)

        # Build menu_item dict (unified lookup for all item types)
        menu_item = self._build_menu_item_dict(item_type, item_name, kwargs)

        # Build pre_filled_attributes from kwargs (data-driven, queries DB for item type attributes)
        pre_filled_attributes = self._extract_pre_filled_attributes(item_type, kwargs)

        # Get extracted_modifiers from kwargs if provided
        extracted_modifiers = kwargs.get("extracted_modifiers")

        logger.info(
            "ADD ITEM: type=%s, name=%s, qty=%d, pre_filled=%s",
            item_type, item_name, quantity,
            {k: v for k, v in pre_filled_attributes.items() if v is not None}
        )

        # Create item through generic flow
        result = self._create_configurable_item(
            menu_item=menu_item,
            order=order,
            quantity=quantity,
            user_input=kwargs.get("original_input"),
            pre_filled_attributes=pre_filled_attributes if pre_filled_attributes else None,
            extracted_modifiers=extracted_modifiers,
        )

        return result

    def _build_menu_item_dict(
        self,
        item_type: str,
        item_name: str,
        kwargs: dict,
    ) -> dict:
        """Build menu_item dict for _create_configurable_item().

        Uses unified price lookup for all item types - no category-specific branching.

        Args:
            item_type: The item type slug
            item_name: The item name (e.g., "Bagel", "Latte", "Turkey Club")
            kwargs: Original kwargs with item details

        Returns:
            Dict with name, item_type, base_price, id, is_signature
        """
        # Use item_name from kwargs if provided (may have been canonicalized)
        lookup_name = kwargs.get("item_name") or item_name

        # Step 1: Try menu lookup (works for all menu-backed items)
        menu_data = self.menu_lookup.lookup_menu_item(lookup_name) if self.menu_lookup else None
        if menu_data:
            return {
                "name": menu_data.get("name", lookup_name),
                "item_type": menu_data.get("item_type") or item_type,
                "base_price": menu_data.get("base_price", 0),
                "id": menu_data.get("id"),
                "is_signature": menu_data.get("is_signature", False),
            }

        # Step 2: Check if this is a configurable item type (e.g., bagel, which has "bread" attribute)
        # These use the item type display name and pricing engine instead of menu lookup
        is_configurable_type = item_type and menu_cache.item_type_has_attribute(item_type, "bread")
        if is_configurable_type:
            canonical_name = menu_cache.get_item_type_display_name(item_type) or lookup_name
            base_price = self.pricing.lookup_base_price(canonical_name) if self.pricing else 0.0
            return {
                "name": canonical_name,
                "item_type": item_type,
                "base_price": base_price,
                "id": None,
                "is_signature": False,
            }

        # Step 3: Try pricing engine as fallback
        if self.pricing:
            try:
                base_price = self.pricing.lookup_base_price(lookup_name)
                return {
                    "name": lookup_name,
                    "item_type": item_type,
                    "base_price": base_price,
                    "id": None,
                    "is_signature": False,
                }
            except ValueError:
                pass

        # Step 4: Return with zero price (item will need configuration or is unknown)
        return {
            "name": lookup_name,
            "item_type": item_type,
            "base_price": 0,
            "id": None,
            "is_signature": False,
        }

    def _extract_pre_filled_attributes(self, item_type: str, kwargs: dict) -> dict:
        """Extract pre-filled attributes from kwargs based on item type.

        Extracts only kwargs that match known attribute slugs for the item type.
        Callers should use canonical attribute names (e.g., 'bread' not 'bagel_type').

        Legacy aliases are still supported for backwards compatibility:
        - bagel_type -> bread
        - spread -> spread (direct pass-through if attribute exists)

        Args:
            item_type: The item type slug
            kwargs: Original kwargs with item details

        Returns:
            Dict of attribute_slug -> value for pre-filling
        """
        if not item_type:
            return {}

        # Get known attributes for this item type from DB
        known_attrs = set(menu_cache.get_item_type_attributes(item_type).keys())

        attrs = {}

        # Legacy alias mappings for backwards compatibility
        # TODO: Remove these once all callers use canonical names
        legacy_aliases = {
            "bagel_type": "bread",
        }

        for key, value in kwargs.items():
            if value is None:
                continue

            # Check if it's a legacy alias
            if key in legacy_aliases:
                canonical = legacy_aliases[key]
                if canonical in known_attrs:
                    attrs[canonical] = value
            # Check if it's a known attribute
            elif key in known_attrs:
                attrs[key] = value

        return attrs

    def _extract_generic_term(self, item_name: str) -> str | None:
        """Extract a generic category term from item_name if present.

        Uses data-driven matching - checks if the term or its suffix matches
        multiple menu items, indicating it's a generic term that needs disambiguation.

        Returns the generic term for searching, or None if no generic term found.

        Examples:
        - "chips" -> "chips" (if multiple chip items exist)
        - "Bagel Chips" -> "chips" (suffix matches multiple items)
        - "Potato Chips" -> "chips"
        - "Chocolate Chip Cookie" -> "cookie"
        - "Turkey Club" -> None (specific item)
        """
        item_lower = item_name.lower().strip()

        # Check if exact term matches multiple menu items
        matches = menu_cache.search_menu_items_by_name(item_lower)
        if len(matches) > 1:
            return item_lower

        # Check if last word is a generic term (matches multiple items)
        words = item_lower.split()
        if len(words) > 1:
            last_word = words[-1]
            suffix_matches = menu_cache.search_menu_items_by_name(last_word)
            if len(suffix_matches) > 1:
                return last_word

        return None

    def add_menu_item(
        self,
        item_name: str,
        quantity: int,
        order: OrderTask,
        toasted: bool | None = None,
        bagel_choice: str | None = None,
        modifications: list[str] | None = None,
    ) -> StateMachineResult:
        """Add a menu item and determine next question.

        Uses DisambiguationHandler for unified disambiguation logic.
        """
        # Ensure quantity is at least 1
        quantity = max(1, quantity)

        # Step 1: Look up menu item with disambiguation handling
        menu_item, disambiguation_result = self._lookup_menu_item_with_disambiguation(
            item_name, quantity, order
        )

        # If disambiguation is needed, return the question
        if disambiguation_result:
            return disambiguation_result

        # If item not found, provide helpful suggestions
        if not menu_item:
            message, category_for_followup = self.menu_lookup.get_not_found_message(item_name)
            if category_for_followup:
                # Track state so "yes" response can list items in this category
                order.pending_field = "category_inquiry"
                order.pending_config_queue = [category_for_followup]
            return StateMachineResult(
                message=message,
                order=order,
            )

        # Step 2: Create the item using existing logic
        # (Phase 4 will replace this with _create_configurable_item())
        return self._create_menu_item_from_lookup(
            menu_item=menu_item,
            item_name=item_name,
            quantity=quantity,
            order=order,
            toasted=toasted,
            bagel_choice=bagel_choice,
            modifications=modifications,
        )

    def _create_menu_item_from_lookup(
        self,
        menu_item: dict,
        item_name: str,
        quantity: int,
        order: OrderTask,
        toasted: bool | None = None,
        bagel_choice: str | None = None,
        modifications: list[str] | None = None,
    ) -> StateMachineResult:
        """Create a menu item from lookup result.

        This is the existing item creation logic, extracted for clarity.
        Phase 4 will consolidate this with _create_configurable_item().
        """
        # Use the canonical name from menu if found
        canonical_name = menu_item.get("name", item_name)
        price = menu_item.get("base_price", 0.0)
        menu_item_id = menu_item.get("id")
        category = menu_item.get("item_type", "")  # item_type slug like "spread_sandwich"
        is_signature = menu_item.get("is_signature", False)  # Signature item like "The Classic BEC"

        # Check if item type requires side choice (data-driven, e.g., omelette)
        has_side_choice = menu_cache.item_type_has_side_choice(category) if category else False

        # Check if it uses DB-driven configuration (item types with configurable attributes)
        # Note: has_side_choice items are handled separately and return early
        uses_db_config = category and category in menu_cache.get_configurable_item_types()

        logger.info(
            "Menu item check: canonical_name='%s', category='%s', has_side_choice=%s, uses_db_config=%s, quantity=%d",
            canonical_name,
            category,
            has_side_choice,
            uses_db_config,
            quantity,
        )

        # Determine the menu item type for tracking
        if has_side_choice:
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
                requires_side_choice=has_side_choice,
                menu_item_type=item_type,
                modifications=modifications or [],  # User modifications like "with mayo and mustard"
                is_signature=is_signature,  # Signature item flag from menu data
            )
            # Set toasted and bagel_choice directly in attribute_values
            if toasted is not None:
                item.attribute_values["toasted"] = toasted
            if bagel_choice is not None:
                item.attribute_values["bagel_choice"] = bagel_choice
            # Infer attributes from item name (data-driven, e.g., "Hot Coffee" -> temperature=hot)
            self._infer_attributes_from_item_name(item)
            item.mark_in_progress()
            order.items.add_item(item)
            if first_item is None:
                first_item = item

        logger.info("Added %d menu item(s): %s (price: $%.2f each, id: %s, toasted=%s, bagel=%s, mods=%s)", quantity, canonical_name, price, menu_item_id, toasted, bagel_choice, modifications)

        if has_side_choice:
            # Set state to wait for side choice (applies to first item, others will be configured after)
            order.phase = OrderPhase.CONFIGURING_ITEM
            order.pending_item_id = first_item.id
            # Get side choice attribute configuration from DB
            side_attr = menu_cache.get_side_choice_attribute(category)
            order.pending_field = side_attr.get("slug", "side_choice") if side_attr else "side_choice"
            # Use question text from DB or fallback
            question = (
                side_attr.get("question_text")
                if side_attr
                else f"What side would you like with your {canonical_name}?"
            )
            return StateMachineResult(
                message=question,
                order=order,
            )
        elif uses_db_config and self.menu_item_handler:
            # For deli/egg sandwiches, use DB-driven configuration with customization checkpoint
            # Capture any attributes mentioned in the initial order
            # Note: item_name contains the item + any modifiers the user mentioned
            self.menu_item_handler.capture_attributes_from_input(item_name, first_item)
            # Start the configuration flow
            return self.menu_item_handler.get_first_question(first_item, order)
        else:
            # Mark all items complete (non-omelettes don't need configuration)
            for item in order.items.items:
                # Use getattr to safely access menu_item_name on any item type
                if getattr(item, 'menu_item_name', None) == canonical_name and item.status == TaskStatus.IN_PROGRESS:
                    item.mark_complete()
            return self._get_next_question(order)

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
        menu_item = self.menu_lookup.lookup_menu_item(side_item_name)

        # If item not found, return error message
        if not menu_item:
            logger.warning("Side item not found: '%s' - rejecting", side_item_name)
            message, _ = self.menu_lookup.get_not_found_message(side_item_name)
            return (None, message)

        # Use canonical name and price from menu
        canonical_name = menu_item.get("name", side_item_name)
        price = menu_item.get("base_price", 0.0)
        menu_item_id = menu_item.get("id")

        # Create the side item(s)
        for _ in range(quantity):
            item = MenuItemTask(
                menu_item_name=canonical_name,
                menu_item_id=menu_item_id,
                unit_price=price,
                menu_item_type="side",
            )
            item.mark_complete()  # Side items don't need configuration
            order.items.add_item(item)

        logger.info("Added %d side item(s): %s (price: $%.2f each)", quantity, canonical_name, price)
        return (canonical_name, None)

    def add_side_item_with_response(
        self,
        side_item_name: str,
        quantity: int,
        order: OrderTask,
    ) -> StateMachineResult:
        """Add a side item to the order and return an appropriate response.

        Used when a side item is ordered on its own (e.g., "I'll have a side of bacon").
        """
        canonical_name, error_message = self.add_side_item(side_item_name, quantity, order)

        # If item wasn't found, return the error message
        if error_message:
            return StateMachineResult(
                message=error_message,
                order=order,
            )

        # Pluralize if quantity > 1
        if quantity > 1:
            item_display = f"{quantity} {canonical_name}s"
        else:
            item_display = canonical_name

        order.phase = OrderPhase.TAKING_ITEMS.value
        return StateMachineResult(
            message=f"I've added {item_display} to your order. Anything else?",
            order=order,
        )

    # =========================================================================
    # Generic Item Creation (Data-Driven)
    # =========================================================================

    def _create_configurable_item(
        self,
        menu_item: dict,
        order: OrderTask,
        quantity: int = 1,
        user_input: str | None = None,
        pre_filled_attributes: dict | None = None,
        extracted_modifiers: "ExtractedModifiers | None" = None,
    ) -> StateMachineResult:
        """
        Create an item and start its configuration flow if needed.

        This is the generic, data-driven item creation method. It handles all item types
        by checking the database for configuration requirements.

        Args:
            menu_item: Menu item dict from lookup (must have 'name', 'item_type', 'base_price')
            order: Current order task
            quantity: Number of items to create (default: 1)
            user_input: Original user input for attribute extraction (optional)
            pre_filled_attributes: Dict of attribute values to pre-fill (optional)
            extracted_modifiers: ExtractedModifiers object to apply (optional)

        Returns:
            StateMachineResult with next question or confirmation
        """
        # Extract item details
        canonical_name = menu_item.get("name", "item")
        price = menu_item.get("base_price", 0.0)
        menu_item_id = menu_item.get("id")
        item_type = menu_item.get("item_type")  # e.g., "bagel", "sized_beverage", "deli_sandwich"
        is_signature = menu_item.get("is_signature", False)
        skip_config = menu_item.get("skip_config", False)

        # Check if this item type is configurable (has attributes in DB)
        # But also respect skip_config flag (item type has no ask_in_conversation attributes)
        configurable_types = menu_cache.get_configurable_item_types()
        is_configurable = item_type in configurable_types if item_type else False

        # If skip_config is set (from DB - e.g., soda/bottled items), don't configure
        needs_configuration = is_configurable and not skip_config

        logger.info(
            "Creating item: name='%s', type='%s', price=$%.2f, qty=%d, configurable=%s, skip_config=%s, needs_config=%s",
            canonical_name, item_type, price, quantity, is_configurable, skip_config, needs_configuration
        )

        # Create the requested quantity of items
        first_item = None
        for _ in range(quantity):
            item = MenuItemTask(
                menu_item_name=canonical_name,
                menu_item_id=menu_item_id,
                unit_price=price,
                menu_item_type=item_type,
                is_signature=is_signature,
            )

            # Apply pre-filled attributes
            if pre_filled_attributes:
                for attr_name, attr_value in pre_filled_attributes.items():
                    if attr_value is not None:
                        item.attribute_values[attr_name] = attr_value

            # Apply extracted modifiers if provided
            if extracted_modifiers and self.menu_item_handler:
                self.menu_item_handler._apply_extracted_modifiers(item, extracted_modifiers)

            # Infer attributes from item name (data-driven, e.g., "Hot Coffee" -> temperature=hot)
            # This prevents asking questions already answered by the item name
            self._infer_attributes_from_item_name(item)

            # Recalculate price with modifiers
            if self.pricing:
                self.pricing.recalculate_item_price(item)

            # Mark status based on whether item needs configuration
            if needs_configuration:
                item.mark_in_progress()
            else:
                item.mark_complete()

            order.items.add_item(item)
            if first_item is None:
                first_item = item

        # If item needs configuration, start the configuration flow
        if needs_configuration and self.menu_item_handler:
            # Capture any attributes from original user input
            if user_input:
                self.menu_item_handler.capture_attributes_from_input(user_input, first_item)
            # Start configuration flow
            return self.menu_item_handler.get_first_question(first_item, order)
        else:
            # Not configurable - item is complete
            order.clear_pending()
            if quantity > 1:
                return StateMachineResult(
                    message=f"Got it, {quantity} {canonical_name}. Anything else?",
                    order=order,
                )
            else:
                return StateMachineResult(
                    message=f"Got it, {canonical_name}. Anything else?",
                    order=order,
                )

    def _lookup_menu_item_with_disambiguation(
        self,
        item_name: str,
        quantity: int,
        order: OrderTask,
        modifiers: dict | None = None,
        pending_field: str = "item_selection",
        item_type_filter: str | None = None,
    ) -> tuple[dict | None, StateMachineResult | None]:
        """
        Look up a menu item, handling disambiguation if multiple matches.

        Uses DisambiguationHandler for unified disambiguation logic.

        Args:
            item_name: Name of item to look up
            quantity: Number of items (stored during disambiguation)
            order: Current order task
            modifiers: Optional dict of modifiers to store during disambiguation (for beverages)
            pending_field: The pending_field value to use (default: "item_selection",
                          use "drink_selection" or "drink_type" for beverages)
            item_type_filter: Optional item type to filter matches (e.g., "sized_beverage")

        Returns:
            Tuple of (menu_item, result):
            - (menu_item, None): Single match found
            - (None, result): Disambiguation needed, result contains the question
            - (None, None): Item not found
        """
        item_lower = item_name.lower().strip()

        # Check for generic drink terms using data-driven category reference
        category_slug = menu_cache.is_category_reference(item_lower)
        is_generic_drink = category_slug == "drink"  # Matches "drink", "drinks", "beverage", etc.
        if is_generic_drink:
            # Generic drink request - show beverages from category
            all_drinks = menu_cache.get_items_by_category("drink")
            # Filter by item_type if specified (e.g., only show sized_beverage items)
            if item_type_filter and all_drinks:
                all_drinks = [
                    d for d in all_drinks
                    if d.get("item_type_slug") == item_type_filter or d.get("item_type") == item_type_filter
                ]
            if all_drinks:
                logger.info("Generic drink request '%s', showing %d drinks (filter: %s)",
                           item_name, len(all_drinks), item_type_filter)
                result = self.disambiguation_handler.start_disambiguation(
                    item_name="drink",
                    matching_items=all_drinks,
                    order=order,
                    quantity=quantity,
                    pending_field="drink_type",
                    modifiers=modifiers,
                    show_prices=False,
                )
                return (None, result)

        # Check for generic category terms (chips, cookies, etc.) - data-driven
        generic_term = self._extract_generic_term(item_name)
        # Input is "exact generic" if it directly matches multiple items (e.g., "chips")
        is_exact_generic = generic_term == item_lower

        # Step 1: Try to find matches
        matching_items = []
        search_term = generic_term if is_exact_generic else item_name

        if search_term:
            matching_items = self.menu_lookup.lookup_menu_items(search_term)

        # Filter by item_type if specified
        if item_type_filter and matching_items:
            matching_items = [
                item for item in matching_items
                if item.get("item_type") == item_type_filter
            ]

        # If no matches found but we have an item_type_filter, get all items of that type
        # This handles cases like "coffee" where user wants a beverage but didn't specify which one
        if not matching_items and item_type_filter:
            all_drinks = menu_cache.get_items_by_category("drink")
            if all_drinks:
                matching_items = [
                    d for d in all_drinks
                    if d.get("item_type_slug") == item_type_filter or d.get("item_type") == item_type_filter
                ]
                if matching_items:
                    logger.info("No text matches for '%s', using all %d items of type '%s'",
                               item_name, len(matching_items), item_type_filter)

        # Step 2: Handle results
        if len(matching_items) == 1:
            # Single match - return it directly
            menu_item = matching_items[0]
            logger.info("Single match for '%s': %s", item_name, menu_item.get("name"))
            return (menu_item, None)

        elif len(matching_items) > 1:
            # Multiple matches - check for exact match first
            exact_match = self.disambiguation_handler.check_exact_match(item_name, matching_items)
            if exact_match:
                return (exact_match, None)

            # Check if user already has one in cart
            cart_match = self.disambiguation_handler.check_cart_match(matching_items, order)
            if cart_match:
                return (cart_match, None)

            # Need disambiguation
            logger.info("Multiple matches for '%s' (%d items), starting disambiguation",
                       item_name, len(matching_items))
            result = self.disambiguation_handler.start_disambiguation(
                item_name=item_name,
                matching_items=matching_items,
                order=order,
                quantity=quantity,
                pending_field=pending_field,
                modifiers=modifiers,
                show_prices=not is_exact_generic,  # Show prices for specific items, not generic
            )
            return (None, result)

        # Step 3: No matches - try partial search
        # Try singular form (cookies -> cookie)
        search_terms = [item_lower]
        if item_lower.endswith('ies'):
            search_terms.append(item_lower[:-3] + 'y')
            search_terms.append(item_lower[:-1])
        elif item_lower.endswith('es'):
            search_terms.append(item_lower[:-2])
        elif item_lower.endswith('s') and len(item_lower) > 2:
            search_terms.append(item_lower[:-1])

        for term in search_terms:
            matching_items = self.menu_lookup.lookup_menu_items(term)
            if matching_items:
                break

        # Step 4: Try direct items_by_type search as fallback
        if not matching_items and self._menu_data:
            items_by_type = self._menu_data.get("items_by_type", {})
            for type_slug, type_items in items_by_type.items():
                for item in type_items:
                    item_name_db = item.get("name", "").lower()
                    for term in search_terms:
                        if term in item_name_db:
                            matching_items.append(item)
                            break
            if matching_items:
                logger.info("Direct items_by_type search for %s: found %d items",
                           search_terms, len(matching_items))

        # Step 5: Handle partial match results
        if len(matching_items) == 1:
            menu_item = matching_items[0]
            logger.info("Single partial match for '%s': %s", item_name, menu_item.get("name"))
            return (menu_item, None)
        elif len(matching_items) > 1:
            # Check for exact match among partials
            exact_match = self.disambiguation_handler.check_exact_match(item_name, matching_items)
            if exact_match:
                return (exact_match, None)

            # Need disambiguation
            logger.info("Multiple partial matches for '%s' (%d items), starting disambiguation",
                       item_name, len(matching_items))
            result = self.disambiguation_handler.start_disambiguation(
                item_name=item_name,
                matching_items=matching_items,
                order=order,
                quantity=quantity,
                pending_field=pending_field,
                modifiers=modifiers,
                show_prices=True,
            )
            return (None, result)

        # Step 6: Still no match - try single item lookup as last resort
        menu_item = self.menu_lookup.lookup_menu_item(item_name)
        if menu_item:
            return (menu_item, None)

        # Not found
        logger.warning("Menu item not found: '%s'", item_name)
        return (None, None)
