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
from .parsers.constants import COFFEE_BEVERAGE_TYPES, is_soda_drink
from .message_builder import MessageBuilder

if TYPE_CHECKING:
    from .pricing_engine import PricingEngine
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

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        pricing: "PricingEngine | None" = None,
        menu_lookup: "MenuLookup | None" = None,
        get_next_question: Callable[[OrderTask], StateMachineResult] | None = None,
        check_redirect: Callable[[str, ItemTask, OrderTask, str], StateMachineResult | None] | None = None,
    ):
        """
        Initialize the coffee config handler.

        Args:
            model: LLM model to use for parsing.
            pricing: PricingEngine instance for price lookups.
            menu_lookup: MenuLookup instance for menu item lookups.
            get_next_question: Callback to get the next question in the flow.
            check_redirect: Callback to check if user is ordering a new item.
        """
        self.model = model
        self.pricing = pricing
        self.menu_lookup = menu_lookup
        self._get_next_question = get_next_question
        self._check_redirect = check_redirect

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
        notes: str | None = None,
        decaf: bool | None = None,
    ) -> StateMachineResult:
        """Add coffee/drink(s) and start configuration flow if needed."""
        logger.info(
            "ADD COFFEE: type=%s, size=%s, iced=%s, decaf=%s, QUANTITY=%d, sweetener=%s (sweetener_qty=%d), syrup=%s, notes=%s",
            coffee_type, size, iced, decaf, quantity, sweetener, sweetener_quantity, flavor_syrup, notes
        )
        # Ensure quantity is at least 1
        quantity = max(1, quantity)

        # Check for multiple matching items - ask user to clarify if ambiguous
        if coffee_type and self.menu_lookup:
            matching_items = self.menu_lookup.lookup_menu_items(coffee_type)
            if len(matching_items) > 1:
                # Before asking for clarification, check if user already has a matching
                # drink in their cart - if so, add another of the same type
                coffee_type_lower = coffee_type.lower()
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
        price = menu_item.get("base_price", 2.50) if menu_item else (self.pricing.lookup_coffee_price(coffee_type) if self.pricing else 2.50)

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
            is_configurable_coffee = coffee_type_lower in COFFEE_BEVERAGE_TYPES or any(
                bev in coffee_type_lower for bev in COFFEE_BEVERAGE_TYPES
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
                    sweetener=None,
                    sweetener_quantity=0,
                    flavor_syrup=None,
                    unit_price=price,
                    notes=notes,
                )
                drink.mark_complete()  # No configuration needed
                order.items.add_item(drink)

            # Return to taking items
            order.clear_pending()
            return self._get_next_question(order)

        # Regular coffee/tea - needs configuration
        # Create the requested quantity of drinks
        for _ in range(quantity):
            coffee = CoffeeItemTask(
                drink_type=coffee_type or "coffee",
                size=size,
                iced=iced,
                decaf=decaf,
                milk=milk,
                sweetener=sweetener,
                sweetener_quantity=sweetener_quantity,
                flavor_syrup=flavor_syrup,
                unit_price=price,
                notes=notes,
            )
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

            # Ask about size first
            if not coffee.size:
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = coffee.id
                order.pending_field = "coffee_size"
                message = f"What size would you like for {drink_desc}? Small or large?"
                return StateMachineResult(
                    message=message,
                    order=order,
                )

            # Then ask about hot/iced
            if coffee.iced is None:
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

            # Ask about milk/sugar/syrup if none specified yet (optional question)
            if (coffee.milk is None and coffee.sweetener is None
                    and coffee.flavor_syrup is None):
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
        if coffee_mods.sweetener and not item.sweetener:
            item.sweetener = coffee_mods.sweetener
            item.sweetener_quantity = coffee_mods.sweetener_quantity
            logger.info(f"Extracted sweetener from size response: {coffee_mods.sweetener_quantity} {coffee_mods.sweetener}")
        if coffee_mods.flavor_syrup and not item.flavor_syrup:
            item.flavor_syrup = coffee_mods.flavor_syrup
            logger.info(f"Extracted syrup from size response: {coffee_mods.flavor_syrup}")

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
        if coffee_mods.sweetener and not item.sweetener:
            item.sweetener = coffee_mods.sweetener
            item.sweetener_quantity = coffee_mods.sweetener_quantity
            logger.info(f"Extracted sweetener from style response: {coffee_mods.sweetener_quantity} {coffee_mods.sweetener}")
        if coffee_mods.flavor_syrup and not item.flavor_syrup:
            item.flavor_syrup = coffee_mods.flavor_syrup
            logger.info(f"Extracted syrup from style response: {coffee_mods.flavor_syrup}")

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

        # If negative response and no modifiers extracted, skip
        if is_negative and not (coffee_mods.milk or coffee_mods.sweetener or coffee_mods.flavor_syrup):
            logger.info("User declined coffee modifiers")
        else:
            # Apply any extracted modifiers
            if coffee_mods.milk and not item.milk:
                item.milk = coffee_mods.milk
                logger.info(f"Set coffee milk: {coffee_mods.milk}")
            if coffee_mods.sweetener and not item.sweetener:
                item.sweetener = coffee_mods.sweetener
                item.sweetener_quantity = coffee_mods.sweetener_quantity
                logger.info(f"Set coffee sweetener: {coffee_mods.sweetener_quantity} {coffee_mods.sweetener}")
            if coffee_mods.flavor_syrup and not item.flavor_syrup:
                item.flavor_syrup = coffee_mods.flavor_syrup
                logger.info(f"Set coffee syrup: {coffee_mods.flavor_syrup}")

        # Coffee is now complete - recalculate price with modifiers
        if self.pricing:
            self.pricing.recalculate_coffee_price(item)
        item.mark_complete()
        order.clear_pending()

        # Check for more incomplete coffees before moving on
        return self.configure_next_incomplete_coffee(order)

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

        # Found the selection - clear pending state and add the drink
        selected_name = selected_item.get("name", "drink")
        selected_price = selected_item.get("base_price", 2.50)
        order.pending_drink_options = []
        order.clear_pending()

        logger.info("DRINK SELECTION: User chose '%s' (price: $%.2f)", selected_name, selected_price)

        # Check if this drink should skip configuration
        is_configurable_coffee = any(
            bev in selected_name.lower() for bev in COFFEE_BEVERAGE_TYPES
        )
        should_skip_config = selected_item.get("skip_config", False) or is_soda_drink(selected_name)

        if should_skip_config or not is_configurable_coffee:
            # Add directly as complete (no size/iced questions)
            drink = CoffeeItemTask(
                drink_type=selected_name,
                size=None,
                iced=None,
                milk=None,
                sweetener=None,
                sweetener_quantity=0,
                flavor_syrup=None,
                unit_price=selected_price,
            )
            drink.mark_complete()
            order.items.add_item(drink)

            return StateMachineResult(
                message=f"Got it, {selected_name}. Anything else?",
                order=order,
            )
        else:
            # Needs configuration - add as in_progress
            drink = CoffeeItemTask(
                drink_type=selected_name,
                size=None,
                iced=None,
                milk=None,
                sweetener=None,
                sweetener_quantity=0,
                flavor_syrup=None,
                unit_price=selected_price,
            )
            drink.mark_in_progress()
            order.items.add_item(drink)
            return self.configure_next_incomplete_coffee(order)
