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
    BagelItemTask,
    TaskStatus,
)
from .schemas import OrderPhase, StateMachineResult, BagelOrderDetails, ExtractedModifiers

if TYPE_CHECKING:
    from .menu_lookup import MenuLookup
    from .pricing_engine import PricingEngine

logger = logging.getLogger(__name__)


class ItemAdderHandler:
    """
    Handles adding items to orders.

    Manages menu item lookup, price calculation, and item creation
    for menu items, side items, and bagels.
    """

    def __init__(
        self,
        menu_lookup: "MenuLookup | None" = None,
        pricing: "PricingEngine | None" = None,
        get_next_question: Callable[[OrderTask], StateMachineResult] | None = None,
        configure_next_incomplete_bagel: Callable[[OrderTask], StateMachineResult] | None = None,
    ):
        """
        Initialize the item adder handler.

        Args:
            menu_lookup: MenuLookup instance for item lookups.
            pricing: PricingEngine instance for price calculations.
            get_next_question: Callback to determine the next question.
            configure_next_incomplete_bagel: Callback to configure bagels.
        """
        self.menu_lookup = menu_lookup
        self.pricing = pricing
        self._get_next_question = get_next_question
        self._configure_next_incomplete_bagel = configure_next_incomplete_bagel
        self._menu_data: dict = {}

    @property
    def menu_data(self) -> dict:
        return self._menu_data

    @menu_data.setter
    def menu_data(self, value: dict) -> None:
        self._menu_data = value or {}

    # Generic category terms that should trigger disambiguation when multiple items match
    GENERIC_CATEGORY_TERMS = frozenset([
        "cookie", "cookies", "muffin", "muffins", "brownie", "brownies",
        "donut", "donuts", "doughnut", "doughnuts", "pastry", "pastries",
        "chip", "chips",
    ])

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

        # Check if the item_name is a generic category term (like "cookie", "muffin")
        # In this case, we should check for multiple matches and disambiguate
        item_lower = item_name.lower().strip()
        if item_lower in self.GENERIC_CATEGORY_TERMS:
            # For generic terms, check if there are multiple matching items
            matching_items = self.menu_lookup.lookup_menu_items(item_name)
            if len(matching_items) > 1:
                # Multiple matches - ask user to clarify
                logger.info(
                    "Generic term '%s' matched %d items - asking for disambiguation",
                    item_name, len(matching_items)
                )
                order.pending_item_options = matching_items
                order.pending_item_quantity = quantity
                order.pending_field = "item_selection"
                order.phase = OrderPhase.CONFIGURING_ITEM.value

                # Build the clarification message (without prices for generic queries)
                option_list = []
                for i, item in enumerate(matching_items[:6], 1):  # Limit to 6 options
                    name = item.get("name", "Unknown")
                    option_list.append(f"{i}. {name}")

                options_str = "\n".join(option_list)
                return StateMachineResult(
                    message=f"We have a few {item_name} options:\n{options_str}\nWhich would you like?",
                    order=order,
                )
            elif len(matching_items) == 1:
                # Single match - use it directly
                menu_item = matching_items[0]
                logger.info("Generic term '%s' matched single item: %s", item_name, menu_item.get("name"))
            else:
                # No matches found for generic term - let the regular flow handle the error
                menu_item = None
        else:
            # Not a generic term - use regular lookup
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

        # Check if it's an omelette (requires side choice)
        is_omelette = "omelette" in canonical_name.lower() or "omelet" in canonical_name.lower()

        # Check if it's a spread or salad sandwich (requires toasted question)
        is_spread_or_salad_sandwich = category in ("spread_sandwich", "salad_sandwich")

        logger.info(
            "Menu item check: canonical_name='%s', category='%s', is_omelette=%s, is_spread_salad=%s, quantity=%d",
            canonical_name,
            category,
            is_omelette,
            is_spread_or_salad_sandwich,
            quantity,
        )

        # Determine the menu item type for tracking
        if is_omelette:
            item_type = "omelette"
        elif is_spread_or_salad_sandwich:
            item_type = category  # "spread_sandwich" or "salad_sandwich"
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
        elif is_spread_or_salad_sandwich:
            # For spread/salad sandwiches, ask for bagel choice first, then toasted
            if bagel_choice and toasted is not None:
                # Both bagel and toasted specified - mark complete
                first_item.mark_complete()
                return self._get_next_question(order)
            else:
                # Use unified configuration flow (handles ordinals for multiple items)
                return self._configure_next_incomplete_bagel(order)
        else:
            # Mark all items complete (non-omelettes don't need configuration)
            for item in order.items.items:
                # Use getattr since not all item types have menu_item_name (e.g., BagelItemTask)
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

    def add_bagel(
        self,
        bagel_type: str | None,
        order: OrderTask,
        toasted: bool | None = None,
        spread: str | None = None,
        spread_type: str | None = None,
        extracted_modifiers: ExtractedModifiers | None = None,
    ) -> StateMachineResult:
        """Add a bagel and start configuration, pre-filling any provided details."""
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

        # Extract notes from modifiers
        notes: str | None = None
        if extracted_modifiers and extracted_modifiers.has_notes():
            notes = extracted_modifiers.get_notes_string()
            logger.info("Applying notes to bagel: %s", notes)

        # Check if bagel needs cheese clarification
        needs_cheese = False
        if extracted_modifiers and extracted_modifiers.needs_cheese_clarification:
            needs_cheese = True
            logger.info("Bagel needs cheese clarification (user said 'cheese' without type)")

        # Create bagel with all provided details
        bagel = BagelItemTask(
            bagel_type=bagel_type,
            toasted=toasted,
            spread=spread,
            spread_type=spread_type,
            sandwich_protein=sandwich_protein,
            extras=extras,
            unit_price=price,
            notes=notes,
            needs_cheese_clarification=needs_cheese,
        )
        bagel.mark_in_progress()
        order.items.add_item(bagel)

        logger.info(
            "Adding bagel: type=%s, toasted=%s, spread=%s, spread_type=%s, protein=%s, extras=%s, notes=%s",
            bagel_type, toasted, spread, spread_type, sandwich_protein, extras, notes
        )

        # Determine what question to ask based on what's missing
        # Flow: bagel_type -> toasted -> spread

        if not bagel_type:
            # Need bagel type
            order.phase = OrderPhase.CONFIGURING_ITEM
            order.pending_item_id = bagel.id
            order.pending_field = "bagel_choice"
            return StateMachineResult(
                message="What kind of bagel would you like?",
                order=order,
            )

        if toasted is None:
            # Need toasted preference
            order.phase = OrderPhase.CONFIGURING_ITEM
            order.pending_item_id = bagel.id
            order.pending_field = "toasted"
            return StateMachineResult(
                message="Would you like that toasted?",
                order=order,
            )

        # Check if user said "cheese" without specifying type
        if needs_cheese:
            order.phase = OrderPhase.CONFIGURING_ITEM
            order.pending_item_id = bagel.id
            order.pending_field = "cheese_choice"
            return StateMachineResult(
                message="What kind of cheese would you like? We have American, cheddar, Swiss, and muenster.",
                order=order,
            )

        if spread is None:
            # Skip spread question if bagel already has sandwich toppings (ham, egg, cheese, etc.)
            if extras or sandwich_protein:
                logger.info("Skipping spread question - bagel has toppings: extras=%s, protein=%s", extras, sandwich_protein)
            else:
                # Need spread choice
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = bagel.id
                order.pending_field = "spread"
                return StateMachineResult(
                    message="Would you like cream cheese or butter on that?",
                    order=order,
                )

        # All details provided - bagel is complete!
        bagel.mark_complete()
        return self._get_next_question(order)

    def add_bagels(
        self,
        quantity: int,
        bagel_type: str | None,
        toasted: bool | None,
        spread: str | None,
        spread_type: str | None,
        order: OrderTask,
        extracted_modifiers: ExtractedModifiers | None = None,
    ) -> StateMachineResult:
        """
        Add multiple bagels with the same configuration.

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

            # Extract notes for first bagel
            notes: str | None = None

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

            # Apply notes to first bagel
            if i == 0 and extracted_modifiers and extracted_modifiers.has_notes():
                notes = extracted_modifiers.get_notes_string()
                logger.info("Applying notes to first bagel: %s", notes)

            # Check if first bagel needs cheese clarification
            needs_cheese = False
            if i == 0 and extracted_modifiers and extracted_modifiers.needs_cheese_clarification:
                needs_cheese = True
                logger.info("Bagel needs cheese clarification (user said 'cheese' without type)")

            # Calculate total price including modifiers (for first bagel with modifiers)
            price = self.pricing.calculate_bagel_price_with_modifiers(
                base_price, sandwich_protein, extras, bagel_spread, spread_type
            )

            bagel = BagelItemTask(
                bagel_type=bagel_type,
                toasted=toasted,
                spread=bagel_spread,
                spread_type=spread_type,
                sandwich_protein=sandwich_protein,
                extras=extras,
                unit_price=price,
                notes=notes,
                needs_cheese_clarification=needs_cheese,
            )
            # Mark complete if all fields provided (and no cheese clarification needed), otherwise in_progress
            if bagel_type and toasted is not None and bagel_spread is not None and not needs_cheese:
                bagel.mark_complete()
            else:
                bagel.mark_in_progress()
            order.items.add_item(bagel)

        # Find first incomplete bagel and start configuring it
        return self._configure_next_incomplete_bagel(order)

    def add_bagels_from_details(
        self,
        bagel_details: list[BagelOrderDetails],
        order: OrderTask,
        extracted_modifiers: ExtractedModifiers | None = None,
    ) -> StateMachineResult:
        """
        Add multiple bagels with different configurations.

        Creates all bagels upfront, then configures incomplete ones one at a time.
        Extracted modifiers are applied to the first bagel.
        """
        logger.info("Adding %d bagels from details", len(bagel_details))

        for i, details in enumerate(bagel_details):
            # Look up base price
            base_price = 2.50
            if details.bagel_type:
                bagel_name = f"{details.bagel_type.title()} Bagel" if "bagel" not in details.bagel_type.lower() else details.bagel_type
                menu_item = self.menu_lookup.lookup_menu_item(bagel_name)
                if menu_item:
                    base_price = menu_item.get("base_price", 2.50)

            # Build extras list from extracted modifiers (apply to first bagel only)
            extras: list[str] = []
            sandwich_protein: str | None = None
            spread = details.spread

            # Extract notes for first bagel
            notes: str | None = None

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

            # Apply notes to first bagel
            if i == 0 and extracted_modifiers and extracted_modifiers.has_notes():
                notes = extracted_modifiers.get_notes_string()
                logger.info("Applying notes to first bagel: %s", notes)

            # Check if first bagel needs cheese clarification
            needs_cheese = False
            if i == 0 and extracted_modifiers and extracted_modifiers.needs_cheese_clarification:
                needs_cheese = True
                logger.info("Bagel needs cheese clarification (user said 'cheese' without type)")

            # Calculate total price including modifiers
            price = self.pricing.calculate_bagel_price_with_modifiers(
                base_price, sandwich_protein, extras, spread, details.spread_type
            )

            bagel = BagelItemTask(
                bagel_type=details.bagel_type,
                toasted=details.toasted,
                spread=spread,
                spread_type=details.spread_type,
                sandwich_protein=sandwich_protein,
                extras=extras,
                unit_price=price,
                notes=notes,
                needs_cheese_clarification=needs_cheese,
            )

            # Mark complete if all fields provided (and no cheese clarification needed)
            if details.bagel_type and details.toasted is not None and details.spread is not None and not needs_cheese:
                bagel.mark_complete()
            else:
                bagel.mark_in_progress()

            order.items.add_item(bagel)

            logger.info(
                "Bagel %d: type=%s, toasted=%s, spread=%s (status=%s)",
                i + 1, details.bagel_type, details.toasted, details.spread,
                bagel.status.value
            )

        # Find first incomplete bagel and start configuring it
        return self._configure_next_incomplete_bagel(order)
