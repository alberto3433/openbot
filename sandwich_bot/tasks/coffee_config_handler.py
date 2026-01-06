"""
Coffee Configuration Handler for Order State Machine.

This module handles the coffee ordering and configuration flow,
including size selection and hot/iced preference.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import re
from typing import Callable, TYPE_CHECKING

from .models import CoffeeItemTask, OrderTask, ItemTask, TaskStatus
from .schemas import OrderPhase, StateMachineResult
from .parsers import (
    parse_coffee_size,
    parse_coffee_style,
    parse_hot_iced_deterministic,
    extract_coffee_modifiers_from_input,
)
from .parsers.constants import get_coffee_types, is_soda_drink
from .message_builder import MessageBuilder
from .handler_config import HandlerConfig

if TYPE_CHECKING:
    from .pricing import PricingEngine
    from .menu_lookup import MenuLookup

logger = logging.getLogger(__name__)


def _check_redirect_to_pending_item(
    user_input: str,
    item: ItemTask,
    order: OrderTask,
    question: str,
) -> StateMachineResult | None:
    """Check if user is trying to order a new item while configuring an existing one.

    Import from state_machine to avoid circular imports - this is just a type stub
    for the callback pattern.
    """
    pass  # Will be injected via callback


class CoffeeConfigHandler:
    """
    Handles coffee ordering and configuration flow.

    Manages adding coffee items, size selection, and hot/iced preference.
    """

    def __init__(self, config: HandlerConfig | None = None, **kwargs):
        """
        Initialize the coffee config handler.

        Args:
            config: HandlerConfig with shared dependencies.
            **kwargs: Legacy parameter support.
        """
        if config:
            self.model = config.model
            self.pricing = config.pricing
            self.menu_lookup = config.menu_lookup
            self._get_next_question = config.get_next_question
            self._check_redirect = config.check_redirect
        else:
            # Legacy support for direct parameters
            self.model = kwargs.get("model", "gpt-4o-mini")
            self.pricing = kwargs.get("pricing")
            self.menu_lookup = kwargs.get("menu_lookup")
            self._get_next_question = kwargs.get("get_next_question")
            self._check_redirect = kwargs.get("check_redirect")

    def add_coffee(
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
    ) -> StateMachineResult:
        """Add coffee/drink(s) and start configuration flow if needed."""
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
                batch_size = 5
                batch = all_drinks[:batch_size]
                remaining = len(all_drinks) - batch_size

                drink_names = [item.get("name", "Unknown") for item in batch]

                if remaining > 0:
                    # Format with "and more"
                    if len(drink_names) == 1:
                        drinks_str = drink_names[0]
                    else:
                        drinks_str = ", ".join(drink_names[:-1]) + f", {drink_names[-1]}"
                    message = f"We have {drinks_str}, and more. What type of drink would you like?"
                    # Set pagination for "what else" follow-up
                    order.set_menu_pagination("drink", batch_size, len(all_drinks))
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

            # Filter drinks that contain the search term
            matching_drinks = [
                item for item in all_drinks
                if coffee_type_lower in item.get("name", "").lower()
            ]

            if len(matching_drinks) == 1:
                # Single match - add it directly with proper skip_config handling
                matched_drink = matching_drinks[0]
                matched_name = matched_drink.get("name")
                matched_price = matched_drink.get("base_price", 0)
                skip_config = matched_drink.get("skip_config", False) or is_soda_drink(matched_name)
                logger.info("ADD COFFEE: Single match for '%s' -> '%s', skip_config=%s", coffee_type_lower, matched_name, skip_config)

                if skip_config:
                    # Add directly as complete (no size/iced questions)
                    drink = CoffeeItemTask(
                        drink_type=matched_name,
                        size=None,
                        iced=None,
                        milk=None,
                        sweeteners=[],
                        flavor_syrups=[],
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
                    batch_size = 5
                    batch = matching_drinks[:batch_size]
                    remaining = len(matching_drinks) - batch_size
                    batch_names = [item.get("name", "Unknown") for item in batch]
                    drinks_str = ", ".join(batch_names[:-1]) + f", {batch_names[-1]}"
                    message = f"We have {drinks_str}, and {remaining} more. Which would you like?"
                    order.set_menu_pagination(coffee_type_lower, batch_size, len(matching_drinks))

                # Store filtered options for selection handling
                order.pending_drink_options = matching_drinks
                order.pending_field = "drink_type"
                order.phase = OrderPhase.CONFIGURING_ITEM.value

                # Store original modifiers so they can be applied when user clarifies drink type
                # This preserves "large iced oat milk vanilla" when user clarifies "latte"
                order.pending_coffee_modifiers = {
                    "size": size,
                    "iced": iced,
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
                    "ADD COFFEE: Stored modifiers for disambiguation: size=%s, iced=%s, milk=%s, syrup=%s",
                    size, iced, milk, flavor_syrup
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
                    # Use drink_type for CoffeeItemTask, get_display_name() for others
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
                order.pending_coffee_modifiers = {
                    "size": size,
                    "iced": iced,
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
                    "ADD COFFEE: Stored modifiers for drink_selection disambiguation: size=%s, iced=%s, milk=%s, syrup=%s",
                    size, iced, milk, flavor_syrup
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
                drink = CoffeeItemTask(
                    drink_type=coffee_type,
                    size=None,  # No size options for skip_config drinks
                    iced=None,  # No hot/iced label needed for sodas/bottled drinks
                    decaf=decaf,
                    milk=None,
                    cream_level=cream_level,
                    sweeteners=[],
                    flavor_syrups=[],
                    extra_shots=extra_shots,
                    unit_price=price,
                    special_instructions=special_instructions,
                )
                drink.mark_complete()  # No configuration needed
                order.items.add_item(drink)

            # Return to taking items
            order.clear_pending()
            return self._get_next_question(order)

        # Note: Espresso is now handled by EspressoConfigHandler in taking_items_handler.py
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
            coffee = CoffeeItemTask(
                drink_type=coffee_type or "coffee",
                size=size,
                iced=iced,
                decaf=decaf,
                milk=milk,
                cream_level=cream_level,
                sweeteners=sweeteners_list.copy(),
                flavor_syrups=flavor_syrups_list.copy(),
                wants_syrup=wants_syrup,
                pending_syrup_quantity=syrup_quantity,  # Store quantity from "2 syrups" for later
                extra_shots=extra_shots,
                unit_price=price,
                special_instructions=special_instructions,
            )
            # Calculate upcharges immediately so cart shows correct price
            if self.pricing:
                self.pricing.recalculate_coffee_price(coffee)
            coffee.mark_in_progress()
            order.items.add_item(coffee)

        # Start configuration flow
        return self.configure_next_incomplete_coffee(order)

    def configure_next_incomplete_coffee(
        self,
        order: OrderTask,
    ) -> StateMachineResult:
        """Configure the next incomplete coffee item."""
        # Find all coffee items (both complete and incomplete) to determine total count
        all_coffees = [
            item for item in order.items.items
            if isinstance(item, CoffeeItemTask)
        ]
        total_coffees = len(all_coffees)

        logger.info(
            "CONFIGURE COFFEE: Found %d total coffee items (total items: %d)",
            total_coffees, len(order.items.items)
        )

        # Configure coffees one at a time (fully configure each before moving to next)
        for coffee in all_coffees:
            if coffee.status != TaskStatus.IN_PROGRESS:
                continue

            logger.info(
                "CONFIGURE COFFEE: Checking coffee id=%s, size=%s, iced=%s, status=%s",
                coffee.id, coffee.size, coffee.iced, coffee.status
            )

            # Get drink name for the question
            drink_name = coffee.drink_type or "coffee"

            # Count items of the SAME drink type to determine if ordinals needed
            same_type_items = [c for c in all_coffees if (c.drink_type or "coffee") == drink_name]
            same_type_count = len(same_type_items)

            # Build ordinal descriptor only if multiple items of same type
            if same_type_count > 1:
                # Find position among items of same type
                item_num = next((i + 1 for i, c in enumerate(same_type_items) if c.id == coffee.id), 1)
                ordinal = MessageBuilder.get_ordinal(item_num)
                drink_desc = f"the {ordinal} {drink_name}"
            else:
                drink_desc = f"the {drink_name}"

            # Ask about size first (skip for espresso - no size options)
            if not coffee.size and not coffee.is_espresso:
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = coffee.id
                order.pending_field = "coffee_size"
                message = f"What size would you like for {drink_desc}? Small or large?"
                return StateMachineResult(
                    message=message,
                    order=order,
                )

            # Then ask about hot/iced (skip for espresso - always hot)
            if coffee.iced is None and not coffee.is_espresso:
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = coffee.id
                order.pending_field = "coffee_style"
                if same_type_count > 1:
                    return StateMachineResult(
                        message=f"Would you like {drink_desc} hot or iced?",
                        order=order,
                    )
                else:
                    return StateMachineResult(
                        message="Would you like that hot or iced?",
                        order=order,
                    )

            # Check if user requested syrup without specifying flavor
            # If so, skip the generic modifier question and ask for syrup flavor directly
            if coffee.wants_syrup and not coffee.flavor_syrups:
                # Recalculate price with size/iced upcharges so cart displays correctly
                if self.pricing:
                    self.pricing.recalculate_coffee_price(coffee)
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = coffee.id
                order.pending_field = "syrup_flavor"
                logger.info("Coffee has wants_syrup flag, skipping to syrup flavor question")
                return StateMachineResult(
                    message="Which flavor syrup would you like? We have vanilla, caramel, and hazelnut.",
                    order=order,
                )

            # Ask about milk/sugar/syrup if none specified yet (optional question)
            if (coffee.milk is None and not coffee.sweeteners
                    and not coffee.flavor_syrups):
                # Recalculate price with size/iced upcharges so cart displays correctly
                # This handles cases where user orders "large iced coffee" directly
                if self.pricing:
                    self.pricing.recalculate_coffee_price(coffee)
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = coffee.id
                order.pending_field = "coffee_modifiers"
                return StateMachineResult(
                    message="Would you like any milk, sugar or syrup?",
                    order=order,
                )

            # This coffee is complete - recalculate price with modifiers
            if self.pricing:
                self.pricing.recalculate_coffee_price(coffee)
            coffee.mark_complete()

        # All coffees configured - no incomplete ones found
        logger.info("CONFIGURE COFFEE: No incomplete coffees, going to next question")
        order.clear_pending()
        return self._get_next_question(order)

    def handle_coffee_size(
        self,
        user_input: str,
        item: CoffeeItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle coffee size selection."""
        if self._check_redirect:
            redirect = self._check_redirect(
                user_input, item, order, "What size would you like? Small or large?"
            )
            if redirect:
                return redirect

        parsed = parse_coffee_size(user_input, model=self.model)

        if not parsed.size:
            drink_name = item.drink_type or "drink"
            return StateMachineResult(
                message=f"What size would you like for your {drink_name}? Small or large?",
                order=order,
            )

        item.size = parsed.size

        # Also extract any milk/sweetener/syrup mentioned with the size response
        # e.g., "small with two sugars" or "large with oat milk"
        coffee_mods = extract_coffee_modifiers_from_input(user_input)
        if coffee_mods.milk and not item.milk:
            item.milk = coffee_mods.milk
            logger.info(f"Extracted milk from size response: {coffee_mods.milk}")
        if coffee_mods.sweetener and not item.sweeteners:
            item.sweeteners.append({"type": coffee_mods.sweetener, "quantity": coffee_mods.sweetener_quantity})
            logger.info(f"Extracted sweetener from size response: {coffee_mods.sweetener_quantity} {coffee_mods.sweetener}")
        if coffee_mods.flavor_syrup and not item.flavor_syrups:
            item.flavor_syrups.append({"flavor": coffee_mods.flavor_syrup, "quantity": coffee_mods.syrup_quantity})
            logger.info(f"Extracted syrup from size response: {coffee_mods.syrup_quantity} {coffee_mods.flavor_syrup}")

        # Recalculate price with size upcharge (iced upcharge will be 0 if not iced yet)
        # This ensures the order display shows correct pricing even during configuration
        if self.pricing:
            self.pricing.recalculate_coffee_price(item)

        # If hot/iced was already specified (e.g., "hot latte"), check for modifiers question
        if item.iced is not None:
            order.clear_pending()
            # Check for modifiers question or move to next incomplete coffee
            return self.configure_next_incomplete_coffee(order)

        # Move to hot/iced question with ordinal if multiple items of same drink type
        order.pending_field = "coffee_style"

        # Count items of the SAME drink type to determine if ordinals needed
        drink_name = item.drink_type or "coffee"
        all_coffees = [
            c for c in order.items.items
            if isinstance(c, CoffeeItemTask)
        ]
        same_type_items = [c for c in all_coffees if (c.drink_type or "coffee") == drink_name]
        same_type_count = len(same_type_items)

        if same_type_count > 1:
            # Find this coffee's position among items of same type
            item_num = next((i + 1 for i, c in enumerate(same_type_items) if c.id == item.id), 1)
            ordinal = MessageBuilder.get_ordinal(item_num)
            return StateMachineResult(
                message=f"Would you like the {ordinal} {drink_name} hot or iced?",
                order=order,
            )
        else:
            return StateMachineResult(
                message="Would you like that hot or iced?",
                order=order,
            )

    def handle_coffee_style(
        self,
        user_input: str,
        item: CoffeeItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle hot/iced preference for coffee."""
        if self._check_redirect:
            redirect = self._check_redirect(
                user_input, item, order, "Would you like it hot or iced?"
            )
            if redirect:
                return redirect

        # Try deterministic parsing first for hot/iced, fall back to LLM
        iced = parse_hot_iced_deterministic(user_input)
        if iced is None:
            parsed = parse_coffee_style(user_input, model=self.model)
            iced = parsed.iced

        if iced is None:
            return StateMachineResult(
                message="Would you like that hot or iced?",
                order=order,
            )

        item.iced = iced

        # Also extract any milk/sweetener/syrup mentioned with the hot/iced response
        # e.g., "hot with 2 splenda" or "iced with oat milk"
        coffee_mods = extract_coffee_modifiers_from_input(user_input)
        if coffee_mods.milk and not item.milk:
            item.milk = coffee_mods.milk
            logger.info(f"Extracted milk from style response: {coffee_mods.milk}")
        if coffee_mods.sweetener and not item.sweeteners:
            item.sweeteners.append({"type": coffee_mods.sweetener, "quantity": coffee_mods.sweetener_quantity})
            logger.info(f"Extracted sweetener from style response: {coffee_mods.sweetener_quantity} {coffee_mods.sweetener}")
        if coffee_mods.flavor_syrup and not item.flavor_syrups:
            item.flavor_syrups.append({"flavor": coffee_mods.flavor_syrup, "quantity": coffee_mods.syrup_quantity})
            logger.info(f"Extracted syrup from style response: {coffee_mods.syrup_quantity} {coffee_mods.flavor_syrup}")

        # Recalculate price with iced upcharge and any modifiers extracted so far
        if self.pricing:
            self.pricing.recalculate_coffee_price(item)

        order.clear_pending()

        # Check for more questions (modifiers) or move to next incomplete coffee
        return self.configure_next_incomplete_coffee(order)

    def handle_coffee_modifiers(
        self,
        user_input: str,
        item: CoffeeItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle milk/sugar/syrup preferences for coffee."""
        if self._check_redirect:
            redirect = self._check_redirect(
                user_input, item, order, "Would you like any milk, sugar or syrup?"
            )
            if redirect:
                return redirect

        user_lower = user_input.lower().strip()

        # Check for negative responses - user doesn't want any modifiers
        negative_patterns = [
            r'\bno\b', r'\bnope\b', r'\bnothing\b', r'\bnone\b',
            r"\bthat'?s? it\b", r"\bi'?m good\b", r"\bi'?m fine\b",
            r'\bjust that\b', r'\bno thanks\b', r'\bno thank you\b',
        ]
        is_negative = any(re.search(p, user_lower) for p in negative_patterns)

        # Extract any modifiers mentioned
        coffee_mods = extract_coffee_modifiers_from_input(user_input)

        # Check if user said "syrup" without specifying a flavor
        # This handles responses like "syrup", "yes syrup", "with syrup" etc.
        syrup_requested_no_flavor = (
            re.search(r'\bsyrups?\b', user_lower)
            and not coffee_mods.flavor_syrup
            and not is_negative
        )

        if syrup_requested_no_flavor:
            # User wants syrup but didn't specify flavor - ask which one
            logger.info("User requested syrup without specifying flavor, asking for clarification")
            # Apply any other modifiers they mentioned (milk, sweetener)
            if coffee_mods.milk and not item.milk:
                item.milk = coffee_mods.milk
                logger.info(f"Set coffee milk: {coffee_mods.milk}")
            if coffee_mods.sweetener and not item.sweeteners:
                item.sweeteners.append({"type": coffee_mods.sweetener, "quantity": coffee_mods.sweetener_quantity})
                logger.info(f"Set coffee sweetener: {coffee_mods.sweetener_quantity} {coffee_mods.sweetener}")

            # Store the pending syrup quantity for when flavor is specified (e.g., "2 syrups")
            item.pending_syrup_quantity = coffee_mods.syrup_quantity
            logger.info(f"Set pending syrup quantity: {coffee_mods.syrup_quantity}")

            order.pending_field = "syrup_flavor"
            return StateMachineResult(
                message="Which flavor syrup would you like? We have vanilla, caramel, and hazelnut.",
                order=order,
            )

        # If negative response and no modifiers extracted, skip
        if is_negative and not (coffee_mods.milk or coffee_mods.sweetener or coffee_mods.flavor_syrup):
            logger.info("User declined coffee modifiers")
        else:
            # Apply any extracted modifiers
            if coffee_mods.milk and not item.milk:
                item.milk = coffee_mods.milk
                logger.info(f"Set coffee milk: {coffee_mods.milk}")
            if coffee_mods.sweetener and not item.sweeteners:
                item.sweeteners.append({"type": coffee_mods.sweetener, "quantity": coffee_mods.sweetener_quantity})
                logger.info(f"Set coffee sweetener: {coffee_mods.sweetener_quantity} {coffee_mods.sweetener}")
            if coffee_mods.flavor_syrup and not item.flavor_syrups:
                item.flavor_syrups.append({"flavor": coffee_mods.flavor_syrup, "quantity": coffee_mods.syrup_quantity})
                logger.info(f"Set coffee syrup: {coffee_mods.syrup_quantity} {coffee_mods.flavor_syrup}")

            # Apply special instructions (e.g., "splash of milk", "light sugar")
            if coffee_mods.has_special_instructions():
                instructions_str = coffee_mods.get_special_instructions_string()
                if item.special_instructions:
                    item.special_instructions = f"{item.special_instructions}, {instructions_str}"
                else:
                    item.special_instructions = instructions_str
                logger.info(f"Set coffee special instructions: {instructions_str}")

        # Coffee is now complete - recalculate price with modifiers
        if self.pricing:
            self.pricing.recalculate_coffee_price(item)
        item.mark_complete()
        order.clear_pending()

        # Check for more incomplete coffees before moving on
        return self.configure_next_incomplete_coffee(order)

    def handle_syrup_flavor(
        self,
        user_input: str,
        item: CoffeeItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle syrup flavor selection after user said 'syrup' without specifying flavor."""
        if self._check_redirect:
            redirect = self._check_redirect(
                user_input, item, order, "Which flavor syrup would you like?"
            )
            if redirect:
                return redirect

        user_lower = user_input.lower().strip()

        # Check for negative/cancellation responses
        negative_patterns = [
            r'\bno\b', r'\bnope\b', r'\bnothing\b', r'\bnone\b',
            r'\bnevermind\b', r'\bnever mind\b', r'\bcancel\b',
            r'\bno thanks\b', r'\bno thank you\b', r"\bi'?m good\b",
        ]
        is_negative = any(re.search(p, user_lower) for p in negative_patterns)

        if is_negative:
            logger.info("User cancelled syrup selection")
            # Continue without syrup - complete the coffee
            if self.pricing:
                self.pricing.recalculate_coffee_price(item)
            item.mark_complete()
            order.clear_pending()
            return self.configure_next_incomplete_coffee(order)

        # Try to extract the syrup flavor from the response
        coffee_mods = extract_coffee_modifiers_from_input(user_input)

        if coffee_mods.flavor_syrup:
            # Use the maximum of: pending quantity (from "2 syrups") and flavor response quantity (from "3 caramel")
            # This handles cases like: user says "2 syrups" then just "caramel" -> should be 2 caramel syrups
            # Also handles: user says "2 syrups" then "3 caramel" -> should be 3 caramel syrups
            syrup_quantity = max(item.pending_syrup_quantity, coffee_mods.syrup_quantity)
            item.flavor_syrups.append({"flavor": coffee_mods.flavor_syrup, "quantity": syrup_quantity})
            logger.info(f"Set coffee syrup from flavor selection: {syrup_quantity} {coffee_mods.flavor_syrup} (pending_qty={item.pending_syrup_quantity}, response_qty={coffee_mods.syrup_quantity})")

            # Complete the coffee
            if self.pricing:
                self.pricing.recalculate_coffee_price(item)
            item.mark_complete()
            order.clear_pending()
            return self.configure_next_incomplete_coffee(order)

        # Couldn't parse a flavor - ask again
        return StateMachineResult(
            message="I didn't catch that. Which syrup flavor would you like - vanilla, caramel, or hazelnut?",
            order=order,
        )

    def handle_drink_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user selecting from multiple drink options."""
        if not order.pending_drink_options:
            order.clear_pending()
            return StateMachineResult(
                message="What would you like to order?",
                order=order,
            )

        user_lower = user_input.lower().strip()
        options = order.pending_drink_options

        # Reject negative numbers or other invalid input early
        if user_lower.startswith('-') or user_lower.startswith('−'):
            option_list = []
            for i, item in enumerate(options, 1):
                name = item.get("name", "Unknown")
                price = item.get("base_price", 0)
                if price > 0:
                    option_list.append(f"{i}. {name} (${price:.2f})")
                else:
                    option_list.append(f"{i}. {name}")
            options_str = "\n".join(option_list)
            return StateMachineResult(
                message=f"Please choose a number from 1 to {len(options)}:\n{options_str}",
                order=order,
            )

        # Try to match by number (1, 2, 3, "first", "second", etc.)
        number_map = {
            "1": 0, "one": 0, "first": 0, "the first": 0, "number 1": 0, "number one": 0,
            "2": 1, "two": 1, "second": 1, "the second": 1, "number 2": 1, "number two": 1,
            "3": 2, "three": 2, "third": 2, "the third": 2, "number 3": 2, "number three": 2,
            "4": 3, "four": 3, "fourth": 3, "the fourth": 3, "number 4": 3, "number four": 3,
        }

        selected_item = None

        # Check for number/ordinal selection
        for key, idx in number_map.items():
            if key in user_lower:
                if idx < len(options):
                    selected_item = options[idx]
                    break
                else:
                    # User selected a number that's out of range - ask again
                    logger.info("DRINK SELECTION: User selected %s but only %d options available", key, len(options))
                    option_list = []
                    for i, item in enumerate(options, 1):
                        name = item.get("name", "Unknown")
                        price = item.get("base_price", 0)
                        if price > 0:
                            option_list.append(f"{i}. {name} (${price:.2f})")
                        else:
                            option_list.append(f"{i}. {name}")
                    options_str = "\n".join(option_list)
                    return StateMachineResult(
                        message=f"I only have {len(options)} options. Please choose:\n{options_str}",
                        order=order,
                    )

        # If not found by number, try to match by name
        if not selected_item:
            for option in options:
                option_name = option.get("name", "").lower()
                # Check if the option name is in user input or vice versa
                # But require minimum length to avoid false matches like "4" in "46 oz"
                if len(user_lower) > 3 and (option_name in user_lower or user_lower in option_name):
                    selected_item = option
                    break
                # Also try matching individual words
                for word in user_lower.split():
                    if len(word) > 3 and word in option_name:
                        selected_item = option
                        break

        if not selected_item:
            # Couldn't determine which one - ask again
            option_list = []
            for i, item in enumerate(options, 1):
                name = item.get("name", "Unknown")
                price = item.get("base_price", 0)
                if price > 0:
                    option_list.append(f"{i}. {name} (${price:.2f})")
                else:
                    option_list.append(f"{i}. {name}")
            options_str = "\n".join(option_list)
            return StateMachineResult(
                message=f"I didn't catch which one. Please choose:\n{options_str}",
                order=order,
            )

        # Found the selection - retrieve stored modifiers BEFORE clearing pending state
        selected_name = selected_item.get("name", "drink")
        selected_price = selected_item.get("base_price", 0)

        # Retrieve stored modifiers from disambiguation (e.g., "large iced oat milk latte")
        stored_mods = order.pending_coffee_modifiers or {}
        stored_size = stored_mods.get("size")
        stored_iced = stored_mods.get("iced")
        stored_milk = stored_mods.get("milk")
        stored_sweetener = stored_mods.get("sweetener")
        stored_sweetener_qty = stored_mods.get("sweetener_quantity", 1)
        stored_syrup = stored_mods.get("flavor_syrup")
        stored_syrup_qty = stored_mods.get("syrup_quantity", 1)
        stored_decaf = stored_mods.get("decaf")
        stored_cream = stored_mods.get("cream_level")
        stored_shots = stored_mods.get("extra_shots", 0)
        stored_instructions = stored_mods.get("special_instructions")
        stored_quantity = stored_mods.get("quantity", 1)

        order.pending_drink_options = []
        order.clear_pending()

        logger.info(
            "DRINK SELECTION: User chose '%s' (price: $%.2f), applying stored modifiers: size=%s, iced=%s, milk=%s, syrup=%s",
            selected_name, selected_price, stored_size, stored_iced, stored_milk, stored_syrup
        )

        # Check if this drink should skip configuration
        is_configurable_coffee = any(
            bev in selected_name.lower() for bev in get_coffee_types()
        )
        should_skip_config = selected_item.get("skip_config", False) or is_soda_drink(selected_name)

        if should_skip_config or not is_configurable_coffee:
            # Add directly as complete (no size/iced questions)
            drink = CoffeeItemTask(
                drink_type=selected_name,
                size=None,
                iced=None,
                milk=None,
                sweeteners=[],
                flavor_syrups=[],
                unit_price=selected_price,
            )
            drink.mark_complete()
            order.items.add_item(drink)

            return StateMachineResult(
                message=f"Got it, {selected_name}. Anything else?",
                order=order,
            )
        else:
            # Needs configuration - apply stored modifiers from original order
            # Build sweeteners list from stored modifier
            sweeteners_list = []
            if stored_sweetener:
                sweeteners_list.append({
                    "type": stored_sweetener,
                    "quantity": stored_sweetener_qty or 1,
                })

            # Build flavor syrups list from stored modifier
            syrups_list = []
            if stored_syrup:
                syrups_list.append({
                    "flavor": stored_syrup,
                    "quantity": stored_syrup_qty or 1,
                })

            # Create drinks with stored modifiers
            for _ in range(stored_quantity):
                drink = CoffeeItemTask(
                    drink_type=selected_name,
                    size=stored_size,
                    iced=stored_iced,
                    decaf=stored_decaf,
                    milk=stored_milk,
                    cream_level=stored_cream,
                    sweeteners=sweeteners_list.copy(),
                    flavor_syrups=syrups_list.copy(),
                    extra_shots=stored_shots,
                    unit_price=selected_price,
                    special_instructions=stored_instructions,
                )

                # Calculate price with modifiers
                if self.pricing:
                    self.pricing.recalculate_coffee_price(drink)

                # Check if fully configured (size and hot/iced specified)
                if drink.size is not None and drink.iced is not None:
                    drink.mark_complete()
                else:
                    drink.mark_in_progress()

                order.items.add_item(drink)

            # If still needs configuration, ask the next question
            if any(d.status == TaskStatus.IN_PROGRESS for d in order.items.items if isinstance(d, CoffeeItemTask)):
                return self.configure_next_incomplete_coffee(order)
            else:
                # Build summary for confirmation
                summary = drink.get_summary() if stored_quantity == 1 else f"{stored_quantity} {selected_name}s"
                return StateMachineResult(
                    message=f"Got it, {summary}. Anything else?",
                    order=order,
                )

    def handle_drink_type_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user specifying a drink type after asking for a generic 'drink'.

        This is called when the user said something like "drink" and we asked
        "What type of drink would you like?" and now they're responding.
        """
        user_lower = user_input.lower().strip()

        # Check for "what else" / "more options" pagination requests
        show_more_phrases = [
            "what else", "any other", "more options", "other options",
            "what other", "anything else", "show more", "more drinks",
            "other drinks", "different",
        ]
        if any(phrase in user_lower for phrase in show_more_phrases):
            pagination = order.get_menu_pagination()
            if pagination and pagination.get("category") == "drink":
                offset = pagination.get("offset", 0)
                # Get drink items again
                items_by_type = self.menu_lookup.menu_data.get("items_by_type", {}) if self.menu_lookup else {}
                sized_items = items_by_type.get("sized_beverage", [])
                cold_items = items_by_type.get("beverage", [])
                all_drinks = sized_items + cold_items

                if offset < len(all_drinks):
                    batch_size = 5
                    batch = all_drinks[offset:offset + batch_size]
                    remaining = len(all_drinks) - (offset + len(batch))

                    drink_names = [item.get("name", "Unknown") for item in batch]

                    if remaining > 0:
                        if len(drink_names) == 1:
                            drinks_str = drink_names[0]
                        else:
                            drinks_str = ", ".join(drink_names[:-1]) + f", {drink_names[-1]}"
                        message = f"We also have {drinks_str}, and more."
                        order.set_menu_pagination("drink", offset + batch_size, len(all_drinks))
                    else:
                        if len(drink_names) == 1:
                            drinks_str = drink_names[0]
                        elif len(drink_names) == 2:
                            drinks_str = f"{drink_names[0]} and {drink_names[1]}"
                        else:
                            drinks_str = ", ".join(drink_names[:-1]) + f", and {drink_names[-1]}"
                        message = f"We also have {drinks_str}. That's all our drinks."
                        order.clear_menu_pagination()

                    return StateMachineResult(message=message, order=order)
                else:
                    order.clear_menu_pagination()
                    return StateMachineResult(
                        message="That's all our drinks. Which would you like?",
                        order=order,
                    )
            # No pagination state - just re-ask
            return StateMachineResult(
                message="Which drink would you like?",
                order=order,
            )

        # FIRST: Check if we have pending drink options (from disambiguation like "latte" matching multiple items)
        # If so, try to match the user's input against those options before doing anything else
        if order.pending_drink_options:
            options = order.pending_drink_options
            selected_item = None

            # Try to match by number (1, 2, 3, "first", "second", etc.)
            number_map = {
                "1": 0, "one": 0, "first": 0, "the first": 0, "number 1": 0, "number one": 0,
                "2": 1, "two": 1, "second": 1, "the second": 1, "number 2": 1, "number two": 1,
                "3": 2, "three": 2, "third": 2, "the third": 2, "number 3": 2, "number three": 2,
                "4": 3, "four": 3, "fourth": 3, "the fourth": 3, "number 4": 3, "number four": 3,
            }

            for key, idx in number_map.items():
                if key in user_lower:
                    if idx < len(options):
                        selected_item = options[idx]
                        break

            # If not found by number, try to match by name
            if not selected_item:
                for option in options:
                    option_name = option.get("name", "").lower()
                    # Check if the option name is in user input or vice versa
                    if len(user_lower) > 3 and (option_name in user_lower or user_lower in option_name):
                        selected_item = option
                        break
                    # Also try matching individual words
                    for word in user_lower.split():
                        if len(word) > 3 and word in option_name:
                            selected_item = option
                            break
                    if selected_item:
                        break

            if selected_item:
                # Found the selection - retrieve stored modifiers before clearing pending state
                selected_name = selected_item.get("name", "drink")
                selected_price = selected_item.get("base_price", 0)

                # Retrieve stored modifiers from disambiguation (e.g., "large iced oat milk latte")
                stored_mods = order.pending_coffee_modifiers or {}
                stored_size = stored_mods.get("size")
                stored_iced = stored_mods.get("iced")
                stored_milk = stored_mods.get("milk")
                stored_sweetener = stored_mods.get("sweetener")
                stored_sweetener_qty = stored_mods.get("sweetener_quantity", 1)
                stored_syrup = stored_mods.get("flavor_syrup")
                stored_syrup_qty = stored_mods.get("syrup_quantity", 1)
                stored_decaf = stored_mods.get("decaf")
                stored_cream = stored_mods.get("cream_level")
                stored_shots = stored_mods.get("extra_shots", 0)
                stored_instructions = stored_mods.get("special_instructions")
                stored_quantity = stored_mods.get("quantity", 1)

                logger.info(
                    "DRINK TYPE SELECTION: User chose '%s' (price: $%.2f), applying stored modifiers: size=%s, iced=%s, milk=%s, syrup=%s",
                    selected_name, selected_price, stored_size, stored_iced, stored_milk, stored_syrup
                )

                order.pending_drink_options = []
                order.clear_pending()

                # Check if this drink should skip configuration
                is_configurable_coffee = any(
                    bev in selected_name.lower() for bev in get_coffee_types()
                )
                should_skip_config = selected_item.get("skip_config", False) or is_soda_drink(selected_name)

                if should_skip_config or not is_configurable_coffee:
                    # Add directly as complete (no size/iced questions)
                    drink = CoffeeItemTask(
                        drink_type=selected_name,
                        size=None,
                        iced=None,
                        milk=None,
                        sweeteners=[],
                        flavor_syrups=[],
                        unit_price=selected_price,
                    )
                    drink.mark_complete()
                    order.items.add_item(drink)

                    return StateMachineResult(
                        message=f"Got it, {selected_name}. Anything else?",
                        order=order,
                    )
                else:
                    # Needs configuration - apply stored modifiers from original order
                    # Build sweeteners list from stored modifier
                    sweeteners_list = []
                    if stored_sweetener:
                        sweeteners_list.append({
                            "sweetener": stored_sweetener,
                            "quantity": stored_sweetener_qty or 1,
                        })

                    # Build flavor syrups list from stored modifier
                    syrups_list = []
                    if stored_syrup:
                        syrups_list.append({
                            "flavor": stored_syrup,
                            "quantity": stored_syrup_qty or 1,
                        })

                    drink = CoffeeItemTask(
                        drink_type=selected_name,
                        size=stored_size,
                        iced=stored_iced,
                        milk=stored_milk,
                        sweeteners=sweeteners_list,
                        flavor_syrups=syrups_list,
                        decaf=stored_decaf,
                        cream_level=stored_cream,
                        extra_shots=stored_shots,
                        special_instructions=stored_instructions,
                        unit_price=selected_price,
                    )
                    drink.mark_in_progress()
                    order.items.add_item(drink)

                    # Add multiple drinks if quantity > 1
                    for _ in range(stored_quantity - 1):
                        extra_drink = CoffeeItemTask(
                            drink_type=selected_name,
                            size=stored_size,
                            iced=stored_iced,
                            milk=stored_milk,
                            sweeteners=sweeteners_list.copy(),
                            flavor_syrups=syrups_list.copy(),
                            decaf=stored_decaf,
                            cream_level=stored_cream,
                            extra_shots=stored_shots,
                            special_instructions=stored_instructions,
                            unit_price=selected_price,
                        )
                        extra_drink.mark_in_progress()
                        order.items.add_item(extra_drink)

                    # Use _get_next_question which checks for incomplete bagels first
                    # This ensures bagels are configured before coffees when both are ordered together
                    return self._get_next_question(order)

        # Clear pending state and pagination
        order.clear_pending()
        order.clear_menu_pagination()

        # Try to parse the drink type from the user's input
        # Use the deterministic parser to extract coffee type
        from .parsers.deterministic import parse_open_input_deterministic
        parsed = parse_open_input_deterministic(user_input)

        # Check if they specified a coffee/drink
        if parsed and (parsed.new_coffee or parsed.new_coffee_type):
            coffee_type = parsed.new_coffee_type
            # Call add_coffee with the parsed values
            return self.add_coffee(
                coffee_type=coffee_type,
                size=parsed.new_coffee_size,
                iced=parsed.new_coffee_iced,
                milk=parsed.new_coffee_milk,
                sweetener=parsed.new_coffee_sweetener,
                sweetener_quantity=parsed.new_coffee_sweetener_quantity or 1,
                flavor_syrup=parsed.new_coffee_flavor_syrup,
                quantity=parsed.new_coffee_quantity or 1,
                order=order,
                special_instructions=parsed.new_coffee_special_instructions,
                decaf=parsed.new_coffee_decaf,
                syrup_quantity=parsed.new_coffee_syrup_quantity or 1,
                cream_level=parsed.new_coffee_cream_level,
            )

        # Try direct matching with known drink types
        for bev_type in get_coffee_types():
            if bev_type in user_lower:
                return self.add_coffee(
                    coffee_type=bev_type,
                    size=None,
                    iced=None,
                    milk=None,
                    sweetener=None,
                    sweetener_quantity=1,
                    flavor_syrup=None,
                    quantity=1,
                    order=order,
                )

        # Try to look up in menu
        if self.menu_lookup:
            matching_items = self.menu_lookup.lookup_menu_items(user_input)
            if matching_items:
                # Use the first match
                item_name = matching_items[0].get("name", user_input)
                return self.add_coffee(
                    coffee_type=item_name,
                    size=None,
                    iced=None,
                    milk=None,
                    sweetener=None,
                    sweetener_quantity=1,
                    flavor_syrup=None,
                    quantity=1,
                    order=order,
                )

        # Couldn't parse - ask again
        logger.info("DRINK TYPE SELECTION: Couldn't parse '%s', asking again", user_input[:50])
        order.pending_field = "drink_type"
        order.phase = OrderPhase.CONFIGURING_ITEM.value
        return StateMachineResult(
            message="I didn't catch that. What type of drink would you like - coffee, latte, tea, or something else?",
            order=order,
        )
