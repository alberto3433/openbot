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
        Unified item adder that routes to appropriate handler based on item type attributes.

        This is the data-driven entry point for adding items. Instead of checking
        item type names, callers should use this method which routes based on
        what attributes the item type has in the database.

        Args:
            item_type: The item type slug (e.g., "bagel", "sized_beverage", "espresso")
            order: The current order
            quantity: Number of items to add (default 1)
            **kwargs: Item-specific parameters passed to the specialized handler

        Returns:
            StateMachineResult with next question or confirmation
        """
        from sandwich_bot.menu_data_cache import menu_cache

        # Get attributes for this item type from database
        attrs = menu_cache.get_item_type_attributes(item_type) if item_type else {}

        # Route based on attributes (data-driven, not type names)
        if "bread" in attrs:
            # Items with bread attribute (bagels) - use bagel handler
            return self._add_bagel_item(order, quantity, **kwargs)
        elif "size" in attrs:
            # Items with size attribute (beverages) - use coffee handler
            return self._add_coffee_item(order, quantity, **kwargs)
        else:
            # Generic menu item - use menu item handler
            item_name = kwargs.get("item_name") or kwargs.get("menu_item_name") or item_type
            return self.add_menu_item(
                item_name=item_name,
                quantity=quantity,
                order=order,
                toasted=kwargs.get("toasted"),
                bagel_choice=kwargs.get("bagel_choice"),
                modifications=kwargs.get("modifications"),
            )

    def _add_bagel_item(
        self,
        order: OrderTask,
        quantity: int = 1,
        **kwargs,
    ) -> StateMachineResult:
        """Internal: Route bagel item to _add_bagel or _add_bagels."""
        if quantity > 1:
            return self._add_bagels(
                quantity=quantity,
                bagel_type=kwargs.get("bagel_type"),
                toasted=kwargs.get("toasted"),
                scooped=kwargs.get("scooped"),
                spread=kwargs.get("spread"),
                spread_type=kwargs.get("spread_type"),
                order=order,
                extracted_modifiers=kwargs.get("extracted_modifiers"),
            )
        else:
            return self._add_bagel(
                bagel_type=kwargs.get("bagel_type"),
                order=order,
                toasted=kwargs.get("toasted"),
                scooped=kwargs.get("scooped"),
                spread=kwargs.get("spread"),
                spread_type=kwargs.get("spread_type"),
                extracted_modifiers=kwargs.get("extracted_modifiers"),
            )

    def _add_coffee_item(
        self,
        order: OrderTask,
        quantity: int = 1,
        **kwargs,
    ) -> StateMachineResult:
        """Internal: Route coffee/beverage item to _add_coffee."""
        return self._add_coffee(
            coffee_type=kwargs.get("coffee_type") or kwargs.get("drink_type"),
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
        """Add a menu item and determine next question."""
        # Ensure quantity is at least 1
        quantity = max(1, quantity)

        item_lower = item_name.lower().strip()

        # Check if the item_name is or contains a generic category term (like "cookie", "muffin", "chips")
        generic_term = self._extract_generic_term(item_name)

        # Determine if this is an EXACT generic term (e.g., "chips") vs a specific item ending with
        # a generic term (e.g., "potato chips"). Only the former should always trigger disambiguation.
        is_exact_generic = item_lower in self.GENERIC_CATEGORY_TERMS

        if is_exact_generic:
            # User said exactly "chips", "cookies", etc. - always disambiguate if multiple matches
            matching_items = self.menu_lookup.lookup_menu_items(generic_term)
            if len(matching_items) > 1:
                logger.info(
                    "Exact generic term '%s' matched %d items - asking for disambiguation",
                    generic_term, len(matching_items)
                )
                order.pending_item_options = matching_items
                order.pending_item_quantity = quantity
                order.pending_field = "item_selection"
                order.phase = OrderPhase.CONFIGURING_ITEM.value

                option_list = []
                for i, item in enumerate(matching_items[:6], 1):
                    name = item.get("name", "Unknown")
                    option_list.append(f"{i}. {name}")

                options_str = "\n".join(option_list)
                return StateMachineResult(
                    message=f"We have a few {generic_term} options:\n{options_str}\nWhich would you like?",
                    order=order,
                )
            elif len(matching_items) == 1:
                menu_item = matching_items[0]
                logger.info("Generic term '%s' matched single item: %s", generic_term, menu_item.get("name"))
            else:
                menu_item = None
        else:
            # Not an exact generic term - but item may end with a generic term
            # First try to find matches for the user's SPECIFIC input (e.g., "bagel chips")
            # Only if that fails, fall back to generic term search
            if generic_term:
                # First, try exact match for the specific item name
                matching_items = self.menu_lookup.lookup_menu_items(item_name)
                if len(matching_items) == 1:
                    # Single match - use it directly (no disambiguation needed)
                    menu_item = matching_items[0]
                    logger.info("Specific item '%s' matched single item: %s", item_name, menu_item.get("name"))
                elif len(matching_items) > 1:
                    # Multiple matches for specific input - disambiguate among these
                    logger.info(
                        "Specific item '%s' matched %d items - asking for disambiguation",
                        item_name, len(matching_items)
                    )
                    order.pending_item_options = matching_items
                    order.pending_item_quantity = quantity
                    order.pending_field = "item_selection"
                    order.phase = OrderPhase.CONFIGURING_ITEM.value

                    option_list = []
                    for i, item in enumerate(matching_items[:6], 1):
                        name = item.get("name", "Unknown")
                        option_list.append(f"{i}. {name}")

                    options_str = "\n".join(option_list)
                    return StateMachineResult(
                        message=f"We have a few {item_name} options:\n{options_str}\nWhich would you like?",
                        order=order,
                    )
                else:
                    # No matches for specific input - fall back to regular lookup
                    menu_item = self.menu_lookup.lookup_menu_item(item_name)
            else:
                # No generic term - regular lookup
                menu_item = self.menu_lookup.lookup_menu_item(item_name)

        # Log omelette items in menu for debugging
        omelette_items = self._menu_data.get("items_by_type", {}).get("omelette", [])
        logger.info(
            "Menu lookup for '%s': found=%s, omelette_items=%s",
            item_name,
            menu_item is not None,
            [i.get("name") for i in omelette_items],
        )

        # If item not found in menu, try finding partial matches for disambiguation
        if not menu_item:
            logger.warning("Menu item not found: '%s' - trying partial match", item_name)

            # Try to find partial matches (similar to orange juice disambiguation)
            # First, get singular form for better matching (cookies -> cookie)
            item_lower = item_name.lower()
            search_terms = [item_lower]
            if item_lower.endswith('ies'):
                # Try both: "ladies" -> "lady", and "cookies" -> "cookie"
                search_terms.append(item_lower[:-3] + 'y')  # ladies -> lady
                search_terms.append(item_lower[:-1])  # cookies -> cookie
            elif item_lower.endswith('es'):
                search_terms.append(item_lower[:-2])  # dishes -> dish
            elif item_lower.endswith('s') and len(item_lower) > 2:
                search_terms.append(item_lower[:-1])  # bagels -> bagel

            # First, try _lookup_menu_items for each search term
            matching_items = []
            for term in search_terms:
                matching_items = self.menu_lookup.lookup_menu_items(term)
                if matching_items:
                    break

            # If no matches from _lookup_menu_items, try a direct search through items_by_type
            # (same approach as _get_category_suggestions which we know finds the items)
            if not matching_items and self._menu_data:
                items_by_type = self._menu_data.get("items_by_type", {})
                for type_slug, type_items in items_by_type.items():
                    for item in type_items:
                        item_name_db = item.get("name", "").lower()
                        for term in search_terms:
                            if term in item_name_db:
                                matching_items.append(item)
                                break
                logger.info(
                    "Direct items_by_type search for %s: found %d items",
                    search_terms, len(matching_items)
                )

            if matching_items:
                # Found partial matches - offer disambiguation
                logger.info(
                    "Found %d partial matches for '%s': %s",
                    len(matching_items),
                    item_name,
                    [item.get("name") for item in matching_items]
                )

                if len(matching_items) == 1:
                    # Only one match - use it directly
                    menu_item = matching_items[0]
                    logger.info("Single partial match found, using: %s", menu_item.get("name"))
                else:
                    # Multiple matches - ask user to clarify
                    order.pending_item_options = matching_items
                    order.pending_item_quantity = quantity
                    order.pending_field = "item_selection"
                    order.phase = OrderPhase.CONFIGURING_ITEM.value

                    # Build the clarification message (with prices for specific item lookups)
                    option_list = []
                    for i, item in enumerate(matching_items[:6], 1):  # Limit to 6 options
                        name = item.get("name", "Unknown")
                        price = item.get("base_price", 0)
                        if price > 0:
                            option_list.append(f"{i}. {name} (${price:.2f})")
                        else:
                            option_list.append(f"{i}. {name}")

                    options_str = "\n".join(option_list)
                    return StateMachineResult(
                        message=f"We have a few options for {item_name}:\n{options_str}\nWhich would you like?",
                        order=order,
                    )

        # If still no match, provide helpful suggestions
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

    def _add_bagel(
        self,
        bagel_type: str | None,
        order: OrderTask,
        toasted: bool | None = None,
        scooped: bool | None = None,
        spread: str | None = None,
        spread_type: str | None = None,
        extracted_modifiers: ExtractedModifiers | None = None,
    ) -> StateMachineResult:
        """Internal: Add a bagel and start configuration, pre-filling any provided details."""
        # Look up base bagel price from menu
        base_price = self.pricing.lookup_bagel_price(bagel_type)

        # Build extras list from extracted modifiers
        extras: list[str] = []
        sandwich_protein: str | None = None

        if extracted_modifiers and extracted_modifiers.has_modifiers():
            # First protein goes to sandwich_protein field
            if extracted_modifiers.proteins:
                sandwich_protein = extracted_modifiers.proteins[0]
                # Additional proteins go to extras
                extras.extend(extracted_modifiers.proteins[1:])

            # Cheeses go to extras
            extras.extend(extracted_modifiers.cheeses)

            # Toppings go to extras
            extras.extend(extracted_modifiers.toppings)

            # If modifiers include a spread, use it (unless already specified)
            if not spread and extracted_modifiers.spreads:
                spread = extracted_modifiers.spreads[0]

            logger.info(
                "Extracted modifiers: protein=%s, extras=%s, spread=%s",
                sandwich_protein, extras, spread
            )

        # Calculate total price including modifiers
        price = self.pricing.calculate_bagel_price_with_modifiers(
            base_price, sandwich_protein, extras, spread, spread_type
        )
        logger.info(
            "Bagel price: base=$%.2f, total=$%.2f (with modifiers)",
            base_price, price
        )

        # Extract special instructions from modifiers
        special_instructions: str | None = None
        if extracted_modifiers and extracted_modifiers.has_special_instructions():
            special_instructions = extracted_modifiers.get_special_instructions_string()
            logger.info("Applying special instructions to bagel: %s", special_instructions)

        # Check if bagel needs cheese clarification
        needs_cheese = False
        if extracted_modifiers and extracted_modifiers.needs_cheese_clarification:
            needs_cheese = True
            logger.info("Bagel needs cheese clarification (user said 'cheese' without type)")

        # Create bagel with all provided details (using MenuItemTask with menu_item_type="bagel")
        bagel = MenuItemTask(
            menu_item_name="Bagel",
            menu_item_type="bagel",
            toasted=toasted,
            spread=spread,
            unit_price=price,
            special_instructions=special_instructions,
        )
        # Set bagel-specific fields via property setters
        if bagel_type:
            bagel.bagel_type = bagel_type
        if scooped is not None:
            bagel.scooped = scooped
        if spread_type:
            bagel.spread_type = spread_type
        if sandwich_protein:
            bagel.sandwich_protein = sandwich_protein
        if extras:
            bagel.extras = extras
        if needs_cheese:
            bagel.needs_cheese_clarification = needs_cheese
        bagel.mark_in_progress()
        order.items.add_item(bagel)

        # Recalculate price to set bagel_type_upcharge field (e.g., gluten free +$0.80)
        self.pricing.recalculate_item_price(bagel)

        logger.info(
            "Adding bagel: type=%s, toasted=%s, spread=%s, spread_type=%s, protein=%s, extras=%s, special_instructions=%s",
            bagel_type, toasted, spread, spread_type, sandwich_protein, extras, special_instructions
        )

        # Use unified configuration flow which reads questions from database
        # and handles all business rules (skip spread if has toppings, etc.)
        return self._configure_next_incomplete_bagel(order)

    def _add_bagels(
        self,
        quantity: int,
        bagel_type: str | None,
        toasted: bool | None,
        scooped: bool | None,
        spread: str | None,
        spread_type: str | None,
        order: OrderTask,
        extracted_modifiers: ExtractedModifiers | None = None,
    ) -> StateMachineResult:
        """
        Internal: Add multiple bagels with the same configuration.

        Creates all bagels upfront, then configures them one at a time.
        Extracted modifiers are applied to the first bagel.
        """
        logger.info(
            "Adding %d bagels: type=%s, toasted=%s, spread=%s, spread_type=%s",
            quantity, bagel_type, toasted, spread, spread_type
        )

        # Look up base bagel price from menu
        base_price = self.pricing.lookup_bagel_price(bagel_type)

        # Create all the bagels
        for i in range(quantity):
            # Build extras list from extracted modifiers (apply to first bagel only)
            extras: list[str] = []
            sandwich_protein: str | None = None
            bagel_spread = spread

            # Extract special instructions for first bagel
            special_instructions: str | None = None

            if i == 0 and extracted_modifiers and extracted_modifiers.has_modifiers():
                # First protein goes to sandwich_protein field
                if extracted_modifiers.proteins:
                    sandwich_protein = extracted_modifiers.proteins[0]
                    # Additional proteins go to extras
                    extras.extend(extracted_modifiers.proteins[1:])

                # Cheeses go to extras
                extras.extend(extracted_modifiers.cheeses)

                # Toppings go to extras
                extras.extend(extracted_modifiers.toppings)

                # If modifiers include a spread, use it (unless already specified)
                if not bagel_spread and extracted_modifiers.spreads:
                    bagel_spread = extracted_modifiers.spreads[0]

                logger.info(
                    "Applying extracted modifiers to first bagel: protein=%s, extras=%s, spread=%s",
                    sandwich_protein, extras, bagel_spread
                )

            # Apply special instructions to first bagel
            if i == 0 and extracted_modifiers and extracted_modifiers.has_special_instructions():
                special_instructions = extracted_modifiers.get_special_instructions_string()
                logger.info("Applying special instructions to first bagel: %s", special_instructions)

            # Check if first bagel needs cheese clarification
            needs_cheese = False
            if i == 0 and extracted_modifiers and extracted_modifiers.needs_cheese_clarification:
                needs_cheese = True
                logger.info("Bagel needs cheese clarification (user said 'cheese' without type)")

            # Calculate total price including modifiers (for first bagel with modifiers)
            price = self.pricing.calculate_bagel_price_with_modifiers(
                base_price, sandwich_protein, extras, bagel_spread, spread_type
            )

            # Create bagel using MenuItemTask with menu_item_type="bagel"
            bagel = MenuItemTask(
                menu_item_name="Bagel",
                menu_item_type="bagel",
                toasted=toasted,
                spread=bagel_spread,
                unit_price=price,
                special_instructions=special_instructions,
            )
            # Set bagel-specific fields via property setters
            if bagel_type:
                bagel.bagel_type = bagel_type
            if scooped is not None:
                bagel.scooped = scooped
            if spread_type:
                bagel.spread_type = spread_type
            if sandwich_protein:
                bagel.sandwich_protein = sandwich_protein
            if extras:
                bagel.extras = extras
            if needs_cheese:
                bagel.needs_cheese_clarification = needs_cheese

            # Mark complete if all fields provided (and no cheese clarification needed), otherwise in_progress
            if bagel_type and toasted is not None and bagel_spread is not None and not needs_cheese:
                bagel.mark_complete()
            else:
                bagel.mark_in_progress()
            order.items.add_item(bagel)

            # Recalculate price to set bagel_type_upcharge field (e.g., gluten free +$0.80)
            self.pricing.recalculate_item_price(bagel)

        # Find first incomplete bagel and start configuring it
        return self._configure_next_incomplete_bagel(order)

    def _add_bagels_from_details(
        self,
        bagel_details: list[BagelOrderDetails],
        order: OrderTask,
        extracted_modifiers: ExtractedModifiers | None = None,
    ) -> StateMachineResult:
        """
        Internal: Add multiple bagels with different configurations.

        Creates all bagels upfront, then configures incomplete ones one at a time.
        Extracted modifiers are applied to the first bagel.
        """
        logger.info("Adding %d bagels from details", len(bagel_details))

        for i, details in enumerate(bagel_details):
            # Look up base price from menu (no fallback - fail gracefully with 0)
            base_price = 0
            if details.bagel_type:
                bagel_name = f"{details.bagel_type.title()} Bagel" if "bagel" not in details.bagel_type.lower() else details.bagel_type
                menu_item = self.menu_lookup.lookup_menu_item(bagel_name)
                if menu_item:
                    base_price = menu_item.get("base_price", 0)

            # Build extras list from extracted modifiers (apply to first bagel only)
            extras: list[str] = []
            sandwich_protein: str | None = None
            spread = details.spread

            # Extract special instructions for first bagel
            special_instructions: str | None = None

            if i == 0 and extracted_modifiers and extracted_modifiers.has_modifiers():
                # First protein goes to sandwich_protein field
                if extracted_modifiers.proteins:
                    sandwich_protein = extracted_modifiers.proteins[0]
                    # Additional proteins go to extras
                    extras.extend(extracted_modifiers.proteins[1:])

                # Cheeses go to extras
                extras.extend(extracted_modifiers.cheeses)

                # Toppings go to extras
                extras.extend(extracted_modifiers.toppings)

                # If modifiers include a spread, use it (unless already specified)
                if not spread and extracted_modifiers.spreads:
                    spread = extracted_modifiers.spreads[0]

                logger.info(
                    "Applying extracted modifiers to first bagel: protein=%s, extras=%s, spread=%s",
                    sandwich_protein, extras, spread
                )

            # Apply special instructions to first bagel
            if i == 0 and extracted_modifiers and extracted_modifiers.has_special_instructions():
                special_instructions = extracted_modifiers.get_special_instructions_string()
                logger.info("Applying special instructions to first bagel: %s", special_instructions)

            # Check if first bagel needs cheese clarification
            needs_cheese = False
            if i == 0 and extracted_modifiers and extracted_modifiers.needs_cheese_clarification:
                needs_cheese = True
                logger.info("Bagel needs cheese clarification (user said 'cheese' without type)")

            # Calculate total price including modifiers
            price = self.pricing.calculate_bagel_price_with_modifiers(
                base_price, sandwich_protein, extras, spread, details.spread_type
            )

            # Create bagel using MenuItemTask with menu_item_type="bagel"
            bagel = MenuItemTask(
                menu_item_name="Bagel",
                menu_item_type="bagel",
                toasted=details.toasted,
                spread=spread,
                unit_price=price,
                special_instructions=special_instructions,
            )
            # Set bagel-specific fields via property setters
            if details.bagel_type:
                bagel.bagel_type = details.bagel_type
            if details.spread_type:
                bagel.spread_type = details.spread_type
            if sandwich_protein:
                bagel.sandwich_protein = sandwich_protein
            if extras:
                bagel.extras = extras
            if needs_cheese:
                bagel.needs_cheese_clarification = needs_cheese

            # Mark complete if all fields provided (and no cheese clarification needed)
            if details.bagel_type and details.toasted is not None and details.spread is not None and not needs_cheese:
                bagel.mark_complete()
            else:
                bagel.mark_in_progress()

            order.items.add_item(bagel)

            # Recalculate price to set bagel_type_upcharge field (e.g., gluten free +$0.80)
            self.pricing.recalculate_item_price(bagel)

            logger.info(
                "Bagel %d: type=%s, toasted=%s, spread=%s (status=%s)",
                i + 1, details.bagel_type, details.toasted, details.spread,
                bagel.status.value
            )

        # Find first incomplete bagel and start configuring it
        return self._configure_next_incomplete_bagel(order)

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
                order.pending_drink_options = matching_drinks
                order.pending_field = "drink_type"
                order.phase = OrderPhase.CONFIGURING_ITEM.value

                # Store original modifiers so they can be applied when user clarifies drink type
                # This preserves "large iced oat milk vanilla" when user clarifies "latte"
                # Convert iced boolean to temperature string for storage
                temperature_str = "iced" if iced is True else ("hot" if iced is False else None)
                order.pending_coffee_modifiers = {
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
                order.pending_drink_options = matching_items
                order.pending_field = "drink_selection"
                order.phase = OrderPhase.CONFIGURING_ITEM.value

                # Store original modifiers so they can be applied when user clarifies drink type
                # This preserves "large iced oat milk vanilla" when user clarifies "latte" vs "matcha latte"
                # Convert iced boolean to temperature string for storage
                temperature_str = "iced" if iced is True else ("hot" if iced is False else None)
                order.pending_coffee_modifiers = {
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
        price = menu_item.get("base_price", 0) if menu_item else (self.pricing.lookup_coffee_price(coffee_type) if self.pricing else 0)

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
