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
from .schemas import OrderPhase, StateMachineResult, BagelOrderDetails, ExtractedModifiers
from .handler_config import HandlerConfig
from .parsers.constants import DEFAULT_PAGINATION_SIZE, get_coffee_types, is_soda_drink
from .disambiguation_handler import DisambiguationHandler

if TYPE_CHECKING:
    from .menu_lookup import MenuLookup
    from .pricing import PricingEngine
    from .menu_item_config_handler import MenuItemConfigHandler

logger = logging.getLogger(__name__)


class ItemAdderHandler:
    """
    Handles adding items to orders.

    Manages menu item lookup, price calculation, and item creation
    for menu items, side items, and bagels.
    """

    def __init__(
        self,
        config: HandlerConfig | None = None,
        configure_next_incomplete_bagel: Callable[[OrderTask], StateMachineResult] | None = None,
        configure_next_incomplete_coffee: Callable[[OrderTask], StateMachineResult] | None = None,
        menu_item_handler: "MenuItemConfigHandler | None" = None,
        **kwargs,
    ):
        """
        Initialize the item adder handler.

        Args:
            config: HandlerConfig with shared dependencies.
            configure_next_incomplete_bagel: Callback to configure bagels.
            configure_next_incomplete_coffee: Callback to configure coffee/beverages.
            menu_item_handler: Handler for menu item configuration (deli sandwiches, etc.).
            **kwargs: Legacy parameter support.
        """
        if config:
            self.menu_lookup = config.menu_lookup
            self.pricing = config.pricing
            self._get_next_question = config.get_next_question
        else:
            # Legacy support for direct parameters
            self.menu_lookup = kwargs.get("menu_lookup")
            self.pricing = kwargs.get("pricing")
            self._get_next_question = kwargs.get("get_next_question")

        # Handler-specific callbacks
        self._configure_next_incomplete_bagel = configure_next_incomplete_bagel or kwargs.get("configure_next_incomplete_bagel")
        self._configure_next_incomplete_coffee = configure_next_incomplete_coffee or kwargs.get("configure_next_incomplete_coffee")
        self.menu_item_handler = menu_item_handler or kwargs.get("menu_item_handler")
        self._menu_data: dict = {}

        # Generic disambiguation handler
        self.disambiguation_handler = DisambiguationHandler()

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
        DB-driven configuration. The only exception is beverages that need
        disambiguation (generic/unknown drink types) which use _add_coffee().

        Args:
            item_type: The item type slug (e.g., "bagel", "sized_beverage", "deli_sandwich")
            order: The current order
            quantity: Number of items to add (default 1)
            **kwargs: Item-specific parameters:
                - bagel_type, toasted, scooped, spread, spread_type (for bagels)
                - coffee_type/drink_type, size, iced, milk, sweetener, etc. (for beverages)
                - item_name, modifications, bagel_choice (for menu items)
                - extracted_modifiers (for any item with modifiers)

        Returns:
            StateMachineResult with next question or confirmation
        """
        from .schemas import ExtractedCoffeeModifiers

        quantity = max(1, quantity)

        # Determine item name from various kwargs
        item_name = (
            kwargs.get("item_name") or
            kwargs.get("menu_item_name") or
            kwargs.get("coffee_type") or
            kwargs.get("drink_type") or
            kwargs.get("bagel_type") or
            item_type
        )

        # Check if this is a beverage that needs disambiguation
        # (generic request like "drink" or unknown type that needs menu lookup)
        if item_type == "sized_beverage" or kwargs.get("coffee_type") or kwargs.get("drink_type"):
            drink_name = kwargs.get("coffee_type") or kwargs.get("drink_type") or ""
            drink_name_lower = drink_name.lower().strip()
            standard_coffee_types = get_coffee_types()
            generic_terms = {"drink", "drinks", "beverage", "beverages", "something to drink", ""}

            if drink_name_lower in generic_terms or drink_name_lower not in standard_coffee_types:
                # Needs disambiguation - delegate to _add_coffee
                return self._add_coffee(
                    coffee_type=drink_name or None,
                    size=kwargs.get("size"),
                    iced=kwargs.get("iced"),
                    milk=kwargs.get("milk"),
                    sweetener=kwargs.get("sweetener"),
                    sweetener_quantity=kwargs.get("sweetener_quantity", 1),
                    flavor_syrup=kwargs.get("flavor_syrup"),
                    quantity=quantity,
                    order=order,
                    special_instructions=kwargs.get("special_instructions"),
                    decaf=kwargs.get("decaf"),
                    syrup_quantity=kwargs.get("syrup_quantity", 1),
                    wants_syrup=kwargs.get("wants_syrup", False),
                    cream_level=kwargs.get("cream_level"),
                    extra_shots=kwargs.get("extra_shots", 0),
                    original_input=kwargs.get("original_input"),
                )

        # Build menu_item dict
        menu_item = self._build_menu_item_dict(item_type, item_name, kwargs)

        # Build pre_filled_attributes from kwargs
        pre_filled_attributes = self._extract_pre_filled_attributes(item_type, kwargs)

        # Build extracted modifiers for beverages
        extracted_modifiers = kwargs.get("extracted_modifiers")
        if item_type == "sized_beverage" and not extracted_modifiers:
            # Create coffee modifiers from kwargs if not already provided
            sweetener = kwargs.get("sweetener")
            flavor_syrup = kwargs.get("flavor_syrup")
            special_instructions = kwargs.get("special_instructions")
            extra_shots = kwargs.get("extra_shots", 0)
            if any([sweetener, flavor_syrup, special_instructions, extra_shots]):
                extracted_modifiers = ExtractedCoffeeModifiers(
                    sweeteners=[sweetener] if sweetener else [],
                    syrups=[flavor_syrup] if flavor_syrup else [],
                    extra_shots=extra_shots,
                    special_instructions=[special_instructions] if special_instructions else [],
                )

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

        # Apply beverage-specific properties not in standard attributes
        if item_type == "sized_beverage":
            drink_name = kwargs.get("coffee_type") or kwargs.get("drink_type")
            for item in order.items.items:
                if (getattr(item, 'menu_item_name', None) == drink_name and
                        item.status.value == "in_progress"):
                    if kwargs.get("cream_level"):
                        item.cream_level = kwargs.get("cream_level")
                    if kwargs.get("wants_syrup"):
                        item.wants_syrup = True
                    if kwargs.get("syrup_quantity", 1) > 1:
                        item.pending_syrup_quantity = kwargs.get("syrup_quantity")

        return result

    def _build_menu_item_dict(
        self,
        item_type: str,
        item_name: str,
        kwargs: dict,
    ) -> dict:
        """Build menu_item dict for _create_configurable_item().

        Args:
            item_type: The item type slug
            item_name: The item name (e.g., "Bagel", "Latte", "Turkey Club")
            kwargs: Original kwargs with item details

        Returns:
            Dict with name, item_type, base_price, id, is_signature
        """
        # Determine canonical name and price
        if item_type == "bagel":
            canonical_name = "Bagel"
            base_price = self.pricing.lookup_base_price("Bagel") if self.pricing else 0.0
            menu_item_id = None
        elif item_type == "sized_beverage":
            canonical_name = kwargs.get("coffee_type") or kwargs.get("drink_type") or item_name
            # Look up price from menu or pricing engine
            menu_data = self.menu_lookup.lookup_menu_item(canonical_name) if self.menu_lookup else None
            if menu_data and menu_data.get("base_price"):
                base_price = menu_data.get("base_price", 0)
                menu_item_id = menu_data.get("id")
            elif self.pricing:
                try:
                    base_price = self.pricing.lookup_base_price(canonical_name)
                except ValueError:
                    base_price = 0
                menu_item_id = None
            else:
                base_price = 0
                menu_item_id = None
        else:
            # Generic menu item - look up from menu
            canonical_name = item_name
            menu_data = self.menu_lookup.lookup_menu_item(item_name) if self.menu_lookup else None
            if menu_data:
                canonical_name = menu_data.get("name", item_name)
                base_price = menu_data.get("base_price", 0)
                menu_item_id = menu_data.get("id")
            else:
                base_price = 0
                menu_item_id = None

        return {
            "name": canonical_name,
            "item_type": item_type,
            "base_price": base_price,
            "id": menu_item_id,
            "is_signature": False,
        }

    def _extract_pre_filled_attributes(self, item_type: str, kwargs: dict) -> dict:
        """Extract pre-filled attributes from kwargs based on item type.

        Maps various kwargs to canonical attribute names used in the database.

        Args:
            item_type: The item type slug
            kwargs: Original kwargs with item details

        Returns:
            Dict of attribute_slug -> value for pre-filling
        """
        attrs = {}

        # Bagel attributes
        if kwargs.get("bagel_type"):
            attrs["bread"] = kwargs["bagel_type"]
        if kwargs.get("toasted") is not None:
            attrs["toasted"] = kwargs["toasted"]
        if kwargs.get("scooped") is not None:
            attrs["scooped"] = kwargs["scooped"]
        if kwargs.get("spread"):
            attrs["spread_type"] = kwargs["spread"]
        if kwargs.get("spread_type"):
            attrs["spread_variety"] = kwargs["spread_type"]

        # Beverage attributes
        if kwargs.get("size"):
            attrs["size"] = kwargs["size"]
        if kwargs.get("iced") is not None:
            attrs["temperature"] = "iced" if kwargs["iced"] else "hot"
        if kwargs.get("decaf") is not None:
            attrs["decaf"] = kwargs["decaf"]
        if kwargs.get("milk"):
            attrs["milk"] = kwargs["milk"]

        # Menu item attributes
        if kwargs.get("bagel_choice"):
            attrs["bagel_choice"] = kwargs["bagel_choice"]

        return attrs

    # Generic category terms that should trigger disambiguation when multiple items match
    # These are base terms - we check if item_name equals OR ends with these
    GENERIC_CATEGORY_TERMS = frozenset([
        "cookie", "cookies", "muffin", "muffins", "brownie", "brownies",
        "donut", "donuts", "doughnut", "doughnuts", "pastry", "pastries",
        "chip", "chips",
        "juice", "soda", "coke", "sprite",  # Beverages for disambiguation
        "omelette", "omelettes", "omelet", "omelets",  # Omelettes for disambiguation
        "egg omelette", "egg omelet",  # "egg omelette" is generic, not specific
    ])

    def _extract_generic_term(self, item_name: str) -> str | None:
        """Extract a generic category term from item_name if present.

        Returns the generic term for searching, or None if no generic term found.

        Examples:
        - "chips" -> "chips"
        - "Bagel Chips" -> "chips"
        - "Potato Chips" -> "chips"
        - "Chocolate Chip Cookie" -> "cookie"
        - "Turkey Club" -> None
        """
        item_lower = item_name.lower().strip()
        # Exact match
        if item_lower in self.GENERIC_CATEGORY_TERMS:
            return item_lower
        # Check if ends with a generic term (e.g., "Bagel Chips" ends with "chips")
        for term in self.GENERIC_CATEGORY_TERMS:
            if item_lower.endswith(" " + term):
                return term
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

        # Check if it's an omelette (requires side choice)
        is_omelette = "omelette" in canonical_name.lower() or "omelet" in canonical_name.lower()

        # Check if it's a spread sandwich (now uses DB-driven config)
        is_spread_sandwich = category == "spread_sandwich"

        logger.info(
            "Menu item check: canonical_name='%s', category='%s', is_omelette=%s, is_spread_sandwich=%s, quantity=%d",
            canonical_name,
            category,
            is_omelette,
            is_spread_sandwich,
            quantity,
        )

        # Check if it uses DB-driven configuration (deli, egg, fish, spread sandwiches)
        is_deli_sandwich = category == "deli_sandwich"
        is_egg_sandwich = category == "egg_sandwich"
        is_fish_sandwich = category == "fish_sandwich"
        uses_db_config = is_deli_sandwich or is_egg_sandwich or is_fish_sandwich or is_spread_sandwich

        # Determine the menu item type for tracking
        if is_omelette:
            item_type = "omelette"
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
                requires_side_choice=is_omelette,
                menu_item_type=item_type,
                toasted=toasted,  # Set toasted if specified upfront
                bagel_choice=bagel_choice,  # Set bagel choice if specified upfront
                modifications=modifications or [],  # User modifications like "with mayo and mustard"
                is_signature=is_signature,  # Signature item flag from menu data
            )
            item.mark_in_progress()
            order.items.add_item(item)
            if first_item is None:
                first_item = item

        logger.info("Added %d menu item(s): %s (price: $%.2f each, id: %s, toasted=%s, bagel=%s, mods=%s)", quantity, canonical_name, price, menu_item_id, toasted, bagel_choice, modifications)

        if is_omelette:
            # Set state to wait for side choice (applies to first item, others will be configured after)
            order.phase = OrderPhase.CONFIGURING_ITEM
            order.pending_item_id = first_item.id
            order.pending_field = "side_choice"
            return StateMachineResult(
                message=f"Would you like a bagel or fruit salad with your {canonical_name}?",
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
        from sandwich_bot.menu_data_cache import menu_cache

        # Extract item details
        canonical_name = menu_item.get("name", "item")
        price = menu_item.get("base_price", 0.0)
        menu_item_id = menu_item.get("id")
        item_type = menu_item.get("item_type")  # e.g., "bagel", "sized_beverage", "deli_sandwich"
        is_signature = menu_item.get("is_signature", False)

        # Check if this item type is configurable (has attributes in DB)
        configurable_types = menu_cache.get_configurable_item_types()
        is_configurable = item_type in configurable_types if item_type else False

        logger.info(
            "Creating item: name='%s', type='%s', price=$%.2f, qty=%d, configurable=%s",
            canonical_name, item_type, price, quantity, is_configurable
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

            # Recalculate price with modifiers
            if self.pricing:
                self.pricing.recalculate_item_price(item)

            # Mark status based on configurability
            if is_configurable:
                item.mark_in_progress()
            else:
                item.mark_complete()

            order.items.add_item(item)
            if first_item is None:
                first_item = item

        # If configurable, start the configuration flow
        if is_configurable and self.menu_item_handler:
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
    ) -> tuple[dict | None, StateMachineResult | None]:
        """
        Look up a menu item, handling disambiguation if multiple matches.

        Uses DisambiguationHandler for unified disambiguation logic.

        Args:
            item_name: Name of item to look up
            quantity: Number of items (stored during disambiguation)
            order: Current order task

        Returns:
            Tuple of (menu_item, result):
            - (menu_item, None): Single match found
            - (None, result): Disambiguation needed, result contains the question
            - (None, None): Item not found
        """
        item_lower = item_name.lower().strip()

        # Check for generic category terms (chips, cookies, etc.)
        generic_term = self._extract_generic_term(item_name)
        is_exact_generic = item_lower in self.GENERIC_CATEGORY_TERMS

        # Step 1: Try to find matches
        matching_items = []
        search_term = generic_term if is_exact_generic else item_name

        if search_term:
            matching_items = self.menu_lookup.lookup_menu_items(search_term)

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
                pending_field="item_selection",
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
                pending_field="item_selection",
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

    # =========================================================================
    # Beverage Handling (with disambiguation)
    # =========================================================================

    def _add_coffee(
        self,
        coffee_type: str | None,
        size: str | None,
        iced: bool | None,
        milk: str | None,
        sweetener: str | None,
        sweetener_quantity: int,
        flavor_syrup: str | None,
        quantity: int,
        order: OrderTask,
        special_instructions: str | None = None,
        decaf: bool | None = None,
        syrup_quantity: int = 1,
        wants_syrup: bool = False,
        cream_level: str | None = None,
        extra_shots: int = 0,
        original_input: str | None = None,
    ) -> StateMachineResult:
        """Internal: Add coffee/drink(s) and start configuration flow if needed."""
        logger.info(
            "ADD COFFEE: type=%s, size=%s, iced=%s, decaf=%s, QUANTITY=%d, sweetener=%s (sweetener_qty=%d), syrup=%s (syrup_qty=%d), wants_syrup=%s, special_instructions=%s",
            coffee_type, size, iced, decaf, quantity, sweetener, sweetener_quantity, flavor_syrup, syrup_quantity, wants_syrup, special_instructions
        )
        # Ensure quantity is at least 1
        quantity = max(1, quantity)

        # Check if this is a generic drink request (no specific type)
        # If so, present drink options instead of defaulting to coffee
        generic_drink_terms = {"drink", "drinks", "beverage", "beverages", "something to drink"}
        coffee_type_lower = (coffee_type or "").lower().strip()
        is_generic_drink_request = (
            coffee_type is None or
            coffee_type_lower in generic_drink_terms
        )

        if is_generic_drink_request and self.menu_lookup:
            # Get drink items from menu
            items_by_type = self.menu_lookup.menu_data.get("items_by_type", {})
            sized_items = items_by_type.get("sized_beverage", [])
            cold_items = items_by_type.get("beverage", [])
            all_drinks = sized_items + cold_items

            if all_drinks:
                # Show first batch of drinks with pagination
                batch = all_drinks[:DEFAULT_PAGINATION_SIZE]
                remaining = len(all_drinks) - DEFAULT_PAGINATION_SIZE

                drink_names = [item.get("name", "Unknown") for item in batch]

                if remaining > 0:
                    # Format with "and more"
                    if len(drink_names) == 1:
                        drinks_str = drink_names[0]
                    else:
                        drinks_str = ", ".join(drink_names[:-1]) + f", {drink_names[-1]}"
                    message = f"We have {drinks_str}, and more. What type of drink would you like?"
                    # Set pagination for "what else" follow-up
                    order.set_menu_pagination("drink", DEFAULT_PAGINATION_SIZE, len(all_drinks))
                else:
                    # All drinks fit in one batch
                    if len(drink_names) == 1:
                        drinks_str = drink_names[0]
                    elif len(drink_names) == 2:
                        drinks_str = f"{drink_names[0]} and {drink_names[1]}"
                    else:
                        drinks_str = ", ".join(drink_names[:-1]) + f", and {drink_names[-1]}"
                    message = f"We have {drinks_str}. What type of drink would you like?"

                order.pending_field = "drink_type"
                order.phase = OrderPhase.CONFIGURING_ITEM.value
                logger.info("ADD COFFEE: Generic drink request, presenting %d options", len(drink_names))
                return StateMachineResult(
                    message=message,
                    order=order,
                )

        # Check if this is a partial drink category (juice, soda, tea, etc.)
        # Filter drinks to only show matching items instead of full menu
        if coffee_type_lower and self.menu_lookup:
            items_by_type = self.menu_lookup.menu_data.get("items_by_type", {})
            sized_items = items_by_type.get("sized_beverage", [])
            cold_items = items_by_type.get("beverage", [])
            all_drinks = sized_items + cold_items

            # Filter drinks that contain the search term AND pass the required_match_phrases filter
            # Use original_input for the match filter to preserve full context (e.g., "boxed coffee" vs "coffee")
            filter_input = (original_input or coffee_type).lower() if (original_input or coffee_type) else ""
            matching_drinks = [
                item for item in all_drinks
                if coffee_type_lower in item.get("name", "").lower()
                and self.menu_lookup._passes_match_filter(item, filter_input)
            ]

            if len(matching_drinks) == 1:
                # Single match - add it directly with proper skip_config handling
                matched_drink = matching_drinks[0]
                matched_name = matched_drink.get("name")
                matched_price = matched_drink.get("base_price", 0)

                # Check if this is a sized beverage that needs configuration
                is_sized_beverage = matched_drink in sized_items
                needs_size_config = is_sized_beverage and (size is None or iced is None)

                # For sized beverages without size/iced, always ask for configuration
                if needs_size_config:
                    skip_config = False
                else:
                    skip_config = matched_drink.get("skip_config", False) or is_soda_drink(matched_name)
                logger.info("ADD COFFEE: Single match for '%s' -> '%s', skip_config=%s, is_sized=%s, needs_size_config=%s",
                            coffee_type_lower, matched_name, skip_config, is_sized_beverage, needs_size_config)

                if skip_config:
                    # Add directly as complete (no size/iced questions)
                    drink = MenuItemTask(
                        menu_item_name=matched_name,
                        menu_item_type="sized_beverage",
                        unit_price=matched_price,
                    )
                    drink.mark_complete()
                    order.items.add_item(drink)
                    order.clear_pending()
                    if self._get_next_question:
                        return self._get_next_question(order)
                    return StateMachineResult(
                        message=f"Got it, {matched_name}. Anything else?",
                        order=order,
                    )
                else:
                    # Needs configuration - add as in_progress and configure
                    coffee_type = matched_name
                    coffee_type_lower = matched_name.lower()
                    # Fall through to normal add logic below

            elif len(matching_drinks) > 1:
                # Multiple matches - show only the filtered options
                logger.info("ADD COFFEE: Partial term '%s' matched %d drinks", coffee_type_lower, len(matching_drinks))
                drink_names = [item.get("name", "Unknown") for item in matching_drinks]

                if len(drink_names) <= 5:
                    # Show all matches
                    if len(drink_names) == 2:
                        drinks_str = f"{drink_names[0]} or {drink_names[1]}"
                    else:
                        drinks_str = ", ".join(drink_names[:-1]) + f", or {drink_names[-1]}"
                    message = f"We have {drinks_str}. Which would you like?"
                else:
                    # Show first batch with pagination
                    batch = matching_drinks[:DEFAULT_PAGINATION_SIZE]
                    remaining = len(matching_drinks) - DEFAULT_PAGINATION_SIZE
                    batch_names = [item.get("name", "Unknown") for item in batch]
                    drinks_str = ", ".join(batch_names[:-1]) + f", {batch_names[-1]}"
                    message = f"We have {drinks_str}, and {remaining} more. Which would you like?"
                    order.set_menu_pagination(coffee_type_lower, DEFAULT_PAGINATION_SIZE, len(matching_drinks))

                # Store filtered options for selection handling
                order.pending_item_options = matching_drinks
                order.pending_field = "drink_type"
                order.phase = OrderPhase.CONFIGURING_ITEM.value

                # Store original modifiers so they can be applied when user clarifies drink type
                # This preserves "large iced oat milk vanilla" when user clarifies "latte"
                # Convert iced boolean to temperature string for storage
                temperature_str = "iced" if iced is True else ("hot" if iced is False else None)
                order.pending_item_modifiers = {
                    "size": size,
                    "temperature": temperature_str,
                    "milk": milk,
                    "sweetener": sweetener,
                    "sweetener_quantity": sweetener_quantity,
                    "flavor_syrup": flavor_syrup,
                    "syrup_quantity": syrup_quantity,
                    "decaf": decaf,
                    "cream_level": cream_level,
                    "extra_shots": extra_shots,
                    "special_instructions": special_instructions,
                    "quantity": quantity,
                }
                logger.info(
                    "ADD COFFEE: Stored modifiers for disambiguation: size=%s, temperature=%s, milk=%s, syrup=%s",
                    size, temperature_str, milk, flavor_syrup
                )

                return StateMachineResult(
                    message=message,
                    order=order,
                )

            # No partial matches found - check if it's a known coffee type before proceeding
            # Standard coffee types that don't need menu lookup (latte, cappuccino, etc.)
            standard_coffee_types = get_coffee_types()
            if coffee_type_lower not in standard_coffee_types:
                # Unknown drink - mark it so taking_items_handler can show the right message
                logger.info("ADD COFFEE: Unknown drink '%s', no matches found", coffee_type_lower)
                order.pending_field = "drink_type"
                order.unknown_drink_request = coffee_type  # Store for message generation
                order.phase = OrderPhase.CONFIGURING_ITEM.value
                # Note: StateMachineResult message is discarded by _add_parsed_item,
                # the actual message is generated in taking_items_handler.py
                return StateMachineResult(
                    message="",  # Will be overwritten
                    order=order,
                )

        # Check for multiple matching items - ask user to clarify if ambiguous
        if coffee_type and self.menu_lookup:
            matching_items = self.menu_lookup.lookup_menu_items(coffee_type)
            if len(matching_items) > 1:
                # First check for an exact match among the results - if found, use it directly
                coffee_type_lower = coffee_type.lower()
                for match_item in matching_items:
                    if match_item.get("name", "").lower() == coffee_type_lower:
                        logger.info("ADD COFFEE: Exact match found for '%s', using directly", coffee_type)
                        matching_items = [match_item]  # Use only the exact match
                        break

            if len(matching_items) > 1:
                # Before asking for clarification, check if user already has a matching
                # drink in their cart - if so, add another of the same type
                for cart_item in order.items.items:
                    # Use menu_item_name for beverages, get_display_name() for others
                    if hasattr(cart_item, 'drink_type') and cart_item.drink_type:
                        cart_name = cart_item.drink_type.lower()
                    elif hasattr(cart_item, 'get_display_name'):
                        cart_name = cart_item.get_display_name().lower()
                    else:
                        continue
                    # Check if any matching item matches something in the cart
                    for match_item in matching_items:
                        match_name = match_item.get("name", "").lower()
                        if cart_name == match_name or match_name in cart_name or cart_name in match_name:
                            logger.info(
                                "ADD COFFEE: User already has '%s' in cart, adding another",
                                match_item.get("name")
                            )
                            # Use the exact menu item name
                            coffee_type = match_item.get("name")
                            matching_items = []  # Clear to skip clarification
                            break
                    if not matching_items:
                        break

            if len(matching_items) > 1:
                # Multiple matches - need to ask user which one they want
                logger.info(
                    "ADD COFFEE: Multiple matches for '%s': %s",
                    coffee_type,
                    [item.get("name") for item in matching_items]
                )
                # Store the options and pending state
                order.pending_item_options = matching_items
                order.pending_field = "drink_selection"
                order.phase = OrderPhase.CONFIGURING_ITEM.value

                # Store original modifiers so they can be applied when user clarifies drink type
                # This preserves "large iced oat milk vanilla" when user clarifies "latte" vs "matcha latte"
                # Convert iced boolean to temperature string for storage
                temperature_str = "iced" if iced is True else ("hot" if iced is False else None)
                order.pending_item_modifiers = {
                    "size": size,
                    "temperature": temperature_str,
                    "milk": milk,
                    "sweetener": sweetener,
                    "sweetener_quantity": sweetener_quantity,
                    "flavor_syrup": flavor_syrup,
                    "syrup_quantity": syrup_quantity,
                    "decaf": decaf,
                    "cream_level": cream_level,
                    "extra_shots": extra_shots,
                    "special_instructions": special_instructions,
                    "quantity": quantity,
                }
                logger.info(
                    "ADD COFFEE: Stored modifiers for drink_selection disambiguation: size=%s, temperature=%s, milk=%s, syrup=%s",
                    size, temperature_str, milk, flavor_syrup
                )

                # Build the clarification message
                option_list = []
                for i, item in enumerate(matching_items, 1):
                    name = item.get("name", "Unknown")
                    price = item.get("base_price", 0)
                    if price > 0:
                        option_list.append(f"{i}. {name} (${price:.2f})")
                    else:
                        option_list.append(f"{i}. {name}")

                options_str = "\n".join(option_list)
                return StateMachineResult(
                    message=f"We have a few options for {coffee_type}:\n{options_str}\nWhich would you like?",
                    order=order,
                )

        # Look up item from menu to get price and skip_config flag
        menu_item = self.menu_lookup.lookup_menu_item(coffee_type) if coffee_type and self.menu_lookup else None
        if menu_item and menu_item.get("base_price"):
            price = menu_item.get("base_price", 0)
        elif self.pricing and coffee_type:
            try:
                price = self.pricing.lookup_base_price(coffee_type)
            except ValueError:
                price = 0
        else:
            price = 0

        # Check if this drink should skip configuration questions
        # Check if this is a soda/bottled drink FIRST - these skip configuration
        # This handles cases like "snapple iced tea" which contains "tea" but is a bottled drink
        coffee_type_lower = (coffee_type or "").lower()

        should_skip_config = False
        if is_soda_drink(coffee_type):
            # Soda/bottled drinks don't need size or hot/iced configuration
            logger.info("ADD COFFEE: skip_config=True (soda/bottled drink: %s)", coffee_type)
            should_skip_config = True
        elif menu_item and menu_item.get("skip_config"):
            logger.info("ADD COFFEE: skip_config=True (from menu_item)")
            should_skip_config = True
        else:
            # Coffee beverages (cappuccino, latte, etc.) need configuration
            # Also regular tea drinks need configuration (hot/iced, size)
            coffee_types = get_coffee_types()
            is_configurable_coffee = coffee_type_lower in coffee_types or any(
                bev in coffee_type_lower for bev in coffee_types
            )
            if is_configurable_coffee:
                logger.info("ADD COFFEE: skip_config=False (configurable coffee beverage: %s)", coffee_type)
                should_skip_config = False
            else:
                logger.info("ADD COFFEE: skip_config=False, will need configuration")

        if should_skip_config:
            # This drink doesn't need size or hot/iced questions - add directly as complete
            # Create the requested quantity of drinks
            for _ in range(quantity):
                drink = MenuItemTask(
                    menu_item_name=coffee_type,
                    menu_item_type="sized_beverage",
                    unit_price=price,
                    special_instructions=special_instructions,
                )
                if decaf:
                    drink.decaf = decaf
                if cream_level:
                    drink.cream_level = cream_level
                if extra_shots:
                    drink.extra_shots = extra_shots
                drink.mark_complete()  # No configuration needed
                order.items.add_item(drink)

            # Return to taking items
            order.clear_pending()
            return self._get_next_question(order)

        # Note: Espresso is now handled by MenuItemConfigHandler (data-driven)
        # This add_coffee method only handles regular coffee/tea drinks

        # Regular coffee/tea - needs configuration
        # Build sweeteners list from parameters
        sweeteners_list = []
        if sweetener:
            sweeteners_list.append({"type": sweetener, "quantity": sweetener_quantity})

        # Build flavor_syrups list from parameters
        flavor_syrups_list = []
        if flavor_syrup:
            flavor_syrups_list.append({"flavor": flavor_syrup, "quantity": syrup_quantity})

        # Create the requested quantity of drinks
        for _ in range(quantity):
            coffee = MenuItemTask(
                menu_item_name=coffee_type or "coffee",
                menu_item_type="sized_beverage",
                unit_price=price,
                special_instructions=special_instructions,
            )
            # Set beverage properties via attribute_values
            if size:
                coffee.size = size
            if iced is not None:
                coffee.temperature = "iced" if iced else "hot"
            if decaf:
                coffee.decaf = decaf
            if milk:
                coffee.milk = milk
            if cream_level:
                coffee.cream_level = cream_level
            if sweeteners_list:
                coffee.sweeteners = sweeteners_list.copy()
            if flavor_syrups_list:
                coffee.flavor_syrups = flavor_syrups_list.copy()
            if wants_syrup:
                coffee.wants_syrup = wants_syrup
            if syrup_quantity > 1:
                coffee.pending_syrup_quantity = syrup_quantity  # Store quantity from "2 syrups" for later
            if extra_shots:
                coffee.extra_shots = extra_shots
            # Calculate upcharges immediately so cart shows correct price
            if self.pricing:
                self.pricing.recalculate_item_price(coffee)
            coffee.mark_in_progress()
            order.items.add_item(coffee)

        # Start configuration flow
        return self._configure_next_incomplete_coffee(order)
