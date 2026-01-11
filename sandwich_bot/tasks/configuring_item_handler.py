"""
Configuring Item Handler for Order State Machine.

This module handles the configuration of items (answering questions about
items being configured like size, style, toasted, spread, etc.).

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import re
from typing import TYPE_CHECKING

from .models import OrderTask, MenuItemTask
from .schemas import StateMachineResult, OrderPhase

if TYPE_CHECKING:
    from .handler_config import HandlerConfig
    from .by_pound_handler import ByPoundHandler
    from .coffee_config_handler import CoffeeConfigHandler
    from .bagel_config_handler import BagelConfigHandler
    from .config_helper_handler import ConfigHelperHandler
    from .checkout_utils_handler import CheckoutUtilsHandler
    from .modifier_change_handler import ModifierChangeHandler
    from .item_adder_handler import ItemAdderHandler
    from .taking_items_handler import TakingItemsHandler
    from .menu_item_config_handler import MenuItemConfigHandler

logger = logging.getLogger(__name__)


# Patterns to detect off-topic requests during configuration
# These are questions or requests that aren't answers to the current config question
OFF_TOPIC_PATTERNS = [
    # Menu inquiries: "what syrups do you have?" / "what sweeteners do you have?"
    re.compile(r"what (\w+(?:\s+\w+)?)\s+do\s+you\s+(?:have|offer|carry)", re.IGNORECASE),
    # "what options do you have?" / "what are my options?"
    re.compile(r"what (?:are (?:my|the) )?options", re.IGNORECASE),
    # "what can I add?" / "what can I get?"
    re.compile(r"what (?:can|could)\s+(?:i|you)\s+(?:add|get|put)", re.IGNORECASE),
    # "do you have vanilla?" / "do you have oat milk?"
    re.compile(r"do you (?:have|offer|carry)\s+(?:any\s+)?(\w+)", re.IGNORECASE),
    # "what flavors do you have?" / "what sizes are there?"
    re.compile(r"what (\w+)\s+(?:are there|do you offer)", re.IGNORECASE),
    # "can I get vanilla?" / "can I add sugar?"
    re.compile(r"can\s+(?:i|you)\s+(?:get|add|have)\s+\w+\?", re.IGNORECASE),
    # "what kinds of X do you have?"
    re.compile(r"what (?:kind|type|kinds|types)\s+of\s+\w+", re.IGNORECASE),
    # Modifier additions: "add vanilla syrup" / "add oat milk"
    re.compile(r"^add\s+\w+", re.IGNORECASE),
    # "with vanilla" / "with caramel syrup"
    re.compile(r"^with\s+\w+", re.IGNORECASE),
    # "put vanilla in it" / "put some sugar"
    re.compile(r"^put\s+\w+", re.IGNORECASE),
    # "I want vanilla" / "I'd like oat milk"
    re.compile(r"^i(?:'?d)?\s*(?:want|like|need)\s+(?:to\s+add\s+)?\w+", re.IGNORECASE),
    # "make it with vanilla" / "make it iced" (but not "make it small/large")
    re.compile(r"^make\s+it\s+(?:with\s+)?\w+", re.IGNORECASE),
]

# Words that are valid answers to configuration questions (should not trigger redirect)
VALID_CONFIG_ANSWERS = {
    # Size answers
    "small", "large", "medium", "regular",
    # Style answers
    "hot", "iced", "cold",
    # Toasted answers
    "yes", "no", "yeah", "nope", "sure", "please", "toasted", "not toasted", "untoasted",
    # Bagel types (common ones)
    "plain", "everything", "sesame", "poppy", "wheat", "whole wheat", "onion",
    "cinnamon", "cinnamon raisin", "pumpernickel", "salt", "garlic",
    # Side choices
    "bagel", "fruit", "fruit salad",
}


def _is_off_topic_request(user_input: str, pending_field: str | None = None) -> bool:
    """Check if user input is an off-topic request during configuration.

    Args:
        user_input: The user's input text
        pending_field: The current configuration field being asked about

    Returns:
        True if the request is off-topic and should trigger a redirect
    """
    input_lower = user_input.lower().strip()

    # First check if this looks like a valid config answer
    # Simple answers like "small", "large", "hot", "iced", etc.
    if input_lower in VALID_CONFIG_ANSWERS:
        return False

    # Check for valid answers with minor variations
    for answer in VALID_CONFIG_ANSWERS:
        if input_lower == answer or input_lower == f"{answer} please":
            return False

    # Check if the question is RELEVANT to the current config question
    # These are valid questions to help the user answer the config question
    if pending_field:
        # Generic "what do you have?" / "what kind do you have?" / "what are my options?"
        # These are always relevant when asked during configuration
        generic_option_patterns = [
            "what do you have",
            "what kind do you have",
            "what kinds do you have",
            "what type do you have",
            "what types do you have",
            "what are my options",
            "what are the options",
            "what options do you have",
            "what choices",
            "what flavors",  # For spread question
        ]
        if any(pattern in input_lower for pattern in generic_option_patterns):
            return False  # Let them ask about options

        # Asking about cream cheese/spreads when being asked about spread → relevant
        if pending_field == "spread":
            spread_keywords = ["cream cheese", "spread", "butter", "schmear"]
            if any(kw in input_lower for kw in spread_keywords):
                return False  # Let them ask about cream cheese options

        # Asking about cheese types when being asked about cheese choice → relevant
        if pending_field in ("cheese_choice", "signature_item_cheese_choice"):
            cheese_keywords = ["cheese", "cheeses"]
            if any(kw in input_lower for kw in cheese_keywords):
                return False  # Let them ask about cheese options

        # Asking about bagel types when being asked about bagel choice → relevant
        if pending_field in ("bagel_choice", "signature_item_bagel_type"):
            bagel_keywords = ["bagel", "bagels"]
            if any(kw in input_lower for kw in bagel_keywords):
                return False  # Let them ask about bagel options

        # Asking about sizes when being asked about size → relevant
        if pending_field == "coffee_size":
            size_keywords = ["size", "sizes"]
            if any(kw in input_lower for kw in size_keywords):
                return False  # Let them ask about size options

        # Asking about hot/iced when being asked about style → relevant
        if pending_field == "coffee_style":
            style_keywords = ["hot", "iced", "cold", "style"]
            if any(kw in input_lower for kw in style_keywords):
                return False  # Let them ask about style options

        # Asking about milk/sugar/syrup when being asked about coffee/espresso modifiers → relevant
        if pending_field in ("coffee_modifiers", "espresso_modifiers"):
            modifier_keywords = ["milk", "sugar", "syrup", "sweetener", "cream", "flavor"]
            if any(kw in input_lower for kw in modifier_keywords):
                return False  # Let them ask about modifier options

        # Asking about menu item attributes (menu_item_attr_*) → check if question is about that attribute
        # e.g., pending_field="menu_item_attr_bread" should allow "what kind of bread do you have?"
        if pending_field and pending_field.startswith("menu_item_attr_"):
            attr_name = pending_field.replace("menu_item_attr_", "").replace("_", " ")
            # Allow questions containing the attribute name or generic "what" questions
            if attr_name in input_lower:
                return False  # Question is about the current attribute
            # Also allow generic "what kind" questions for any menu item attribute
            if "what kind" in input_lower or "what type" in input_lower:
                return False

        # During customization_checkpoint or customization_selection, "add X" commands are valid
        # The bot is specifically offering options like "Add Egg, Extra Cheese, Toppings"
        if pending_field in ("customization_checkpoint", "customization_selection"):
            # Allow "add X" commands since the bot offered these as valid choices
            if input_lower.startswith("add "):
                return False
            # Allow standalone attribute names like "egg", "cheese", "toppings"
            customization_keywords = [
                "scooped", "spread", "egg", "cheese", "topping", "toppings",
                "condiment", "condiments", "extra", "protein",
            ]
            if any(kw in input_lower for kw in customization_keywords):
                return False

    # Check if it matches any off-topic pattern
    for pattern in OFF_TOPIC_PATTERNS:
        if pattern.search(user_input):
            # Special case: "make it small/large" is a valid size answer
            if pattern.pattern.startswith("^make"):
                if any(size in input_lower for size in ["small", "large", "medium"]):
                    return False
            return True

    return False


class ConfiguringItemHandler:
    """
    Handles configuring items (answering configuration questions).

    Routes user input to the appropriate field-specific handler based
    on the pending_field in the order.
    """

    def __init__(
        self,
        config: "HandlerConfig | None" = None,
        by_pound_handler: "ByPoundHandler | None" = None,
        coffee_handler: "CoffeeConfigHandler | None" = None,
        bagel_handler: "BagelConfigHandler | None" = None,
        config_helper_handler: "ConfigHelperHandler | None" = None,
        checkout_utils_handler: "CheckoutUtilsHandler | None" = None,
        modifier_change_handler: "ModifierChangeHandler | None" = None,
        item_adder_handler: "ItemAdderHandler | None" = None,
        menu_item_handler: "MenuItemConfigHandler | None" = None,
        **kwargs,
    ) -> None:
        """
        Initialize the configuring item handler.

        Args:
            config: HandlerConfig with shared dependencies (currently unused,
                    but accepted for consistency with other handlers).
            by_pound_handler: Handler for by-pound items.
            coffee_handler: Handler for coffee configuration.
            bagel_handler: Handler for bagel configuration.
            config_helper_handler: Handler for config helpers (side choice, etc.).
            checkout_utils_handler: Handler for checkout utilities.
            modifier_change_handler: Handler for modifier changes.
            item_adder_handler: Handler for adding items.
            menu_item_handler: Handler for menu item configuration (deli sandwiches, espresso, etc.).
            **kwargs: Legacy parameter support.
        """
        # This handler primarily composes other handlers, so config is not directly used
        # but we accept it for consistency with the HandlerConfig pattern
        _ = config  # Unused but accepted for API consistency

        self.by_pound_handler = by_pound_handler or kwargs.get("by_pound_handler")
        self.coffee_handler = coffee_handler or kwargs.get("coffee_handler")
        self.bagel_handler = bagel_handler or kwargs.get("bagel_handler")
        self.config_helper_handler = config_helper_handler or kwargs.get("config_helper_handler")
        self.checkout_utils_handler = checkout_utils_handler or kwargs.get("checkout_utils_handler")
        self.modifier_change_handler = modifier_change_handler or kwargs.get("modifier_change_handler")
        self.item_adder_handler = item_adder_handler or kwargs.get("item_adder_handler")
        self.menu_item_handler = menu_item_handler or kwargs.get("menu_item_handler")
        # Set via setter after TakingItemsHandler is created (to avoid circular dependency)
        self.taking_items_handler: "TakingItemsHandler | None" = None

    def handle_configuring_item(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """
        Handle input when configuring a specific item.

        THIS IS THE KEY: we use state-specific parsers that can ONLY
        interpret input as answers for the pending field. No new items.
        """
        # Handle by-pound category selection (no item required)
        if order.pending_field == "by_pound_category":
            return self.by_pound_handler.handle_by_pound_category_selection(user_input, order)

        # Handle drink selection when multiple options were presented
        if order.pending_field == "drink_selection":
            return self.coffee_handler.handle_drink_selection(user_input, order)

        # Handle drink type selection when user asked for a generic "drink"
        if order.pending_field == "drink_type":
            return self.coffee_handler.handle_drink_type_selection(user_input, order)

        # Handle generic item selection when multiple options were presented (cookies, muffins, etc.)
        if order.pending_field == "item_selection":
            return self._handle_item_selection(user_input, order)

        # Handle category inquiry follow-up ("Would you like to hear what X we have?" -> "yes")
        if order.pending_field == "category_inquiry":
            return self.by_pound_handler.handle_category_inquiry_response(user_input, order)

        # Handle duplicate selection when user said "another one" with multiple items in cart
        if order.pending_field == "duplicate_selection":
            return self.taking_items_handler.handle_duplicate_selection(user_input, order)

        # Handle "same thing" clarification when user has both previous order AND cart items
        if order.pending_field == "same_thing_clarification":
            return self.taking_items_handler.handle_same_thing_clarification(user_input, order)

        # Handle suggested item confirmation ("Would you like to order one?" -> "yes" / "give me one")
        if order.pending_field == "confirm_suggested_item":
            return self.taking_items_handler.handle_confirm_suggested_item(user_input, order)

        item = self.checkout_utils_handler.get_item_by_id(order, order.pending_item_id)
        if item is None:
            order.clear_pending()
            return StateMachineResult(
                message="Something went wrong. What would you like to order?",
                order=order,
            )

        # Check for cancellation requests BEFORE routing to field-specific handlers
        # This allows "remove the coffee", "cancel this", "remove the coffees" etc. during configuration
        cancel_result = self.config_helper_handler.check_cancellation_during_config(user_input, item, order)
        if cancel_result:
            return cancel_result

        # Check for modifier change requests during configuration
        # If detected, tell user to wait until config is complete
        change_request = self.modifier_change_handler.detect_change_request(user_input)
        if change_request:
            logger.info("CHANGE REQUEST: Detected during config, deferring: %s", change_request)
            msg = self.modifier_change_handler.generate_mid_config_message()
            # Re-ask the current question
            current_question = self.config_helper_handler.get_current_config_question(order, item)
            if current_question:
                msg = f"{msg} {current_question}"
            return StateMachineResult(message=msg, order=order)

        # Check for off-topic requests during configuration (e.g., "what syrups do you have?", "add vanilla syrup")
        # If detected, politely redirect back to the current configuration question
        # Note: Questions relevant to the current config (e.g., "what cream cheese do you have?" when asked about spread) are allowed
        if _is_off_topic_request(user_input, order.pending_field):
            logger.info("OFF-TOPIC REQUEST: Detected during config: '%s'", user_input[:50])
            # Get a friendly description of the item being configured
            item_name = item.get_summary() if hasattr(item, 'get_summary') else "your item"
            current_question = self.config_helper_handler.get_current_config_question(order, item)
            if current_question:
                msg = f"Let's finish with your {item_name} first. {current_question}"
            else:
                msg = f"Let's finish with your {item_name} first."
            return StateMachineResult(message=msg, order=order)

        # Route to field-specific handler
        if order.pending_field == "side_choice":
            return self.config_helper_handler.handle_side_choice(user_input, item, order)
        # Bagel configuration fields - use specialized handler for now
        # (Phase 6 migration: these will eventually route through MenuItemConfigHandler)
        elif order.pending_field == "bagel_choice":
            return self.bagel_handler.handle_bagel_choice(user_input, item, order)
        elif order.pending_field == "spread":
            return self.bagel_handler.handle_spread_choice(user_input, item, order)
        elif order.pending_field == "toasted":
            return self.bagel_handler.handle_toasted_choice(user_input, item, order)
        elif order.pending_field == "cheese_choice":
            return self.bagel_handler.handle_cheese_choice(user_input, item, order)
        # Coffee configuration fields - use specialized handler for now
        # (Phase 6 migration: these will eventually route through MenuItemConfigHandler)
        elif order.pending_field == "coffee_size":
            return self.coffee_handler.handle_coffee_size(user_input, item, order)
        elif order.pending_field == "coffee_style":
            return self.coffee_handler.handle_coffee_style(user_input, item, order)
        elif order.pending_field == "coffee_modifiers":
            return self.coffee_handler.handle_coffee_modifiers(user_input, item, order)
        elif order.pending_field == "syrup_flavor":
            return self.coffee_handler.handle_syrup_flavor(user_input, item, order)
        # Note: espresso_modifiers and espresso_syrup_flavor are legacy fields
        # Espresso now uses menu_item_handler with global attributes (shots, milk_sweetener_syrup)
        elif order.pending_field in ("espresso_modifiers", "espresso_syrup_flavor"):
            # Route to menu_item_handler for espresso configuration
            if isinstance(item, MenuItemTask) and self.menu_item_handler:
                return self.menu_item_handler.get_first_question(item, order)
            # Fallback: advance to next question
            order.clear_pending()
            return self.checkout_utils_handler.get_next_question(order)
        elif order.pending_field == "spread_sandwich_toasted":
            return self.bagel_handler.handle_toasted_choice(user_input, item, order)
        elif order.pending_field == "menu_item_bagel_toasted":
            return self.bagel_handler.handle_toasted_choice(user_input, item, order)

        # Handle menu item configuration (deli sandwiches, etc.)
        elif order.pending_field == "customization_checkpoint":
            if isinstance(item, MenuItemTask) and self.menu_item_handler:
                return self.menu_item_handler.handle_customization_checkpoint(user_input, item, order)
        elif order.pending_field == "customization_selection":
            if isinstance(item, MenuItemTask) and self.menu_item_handler:
                return self.menu_item_handler.handle_customization_selection(user_input, item, order)
        elif order.pending_field and order.pending_field.startswith("menu_item_attr_"):
            if isinstance(item, MenuItemTask) and self.menu_item_handler:
                attr_slug = order.pending_field.replace("menu_item_attr_", "")
                return self.menu_item_handler.handle_attribute_input(user_input, item, order, attr_slug)

        # Handle queued menu item configuration (abbreviated flow from checkout_utils_handler)
        # This is set when a menu item is in the config queue and asked an abbreviated question
        # like "And what type of bread for the {item_name}?" - we need to capture the answer
        # and continue with the full configuration flow
        elif order.pending_field == "menu_item_config":
            if isinstance(item, MenuItemTask) and self.menu_item_handler:
                # Capture any attributes mentioned in user input (e.g., bread type)
                self.menu_item_handler.capture_attributes_from_input(user_input, item)
                # Continue with full configuration flow - this will ask the next
                # unanswered mandatory attribute (e.g., toasted) or move to checkout
                return self.menu_item_handler.get_first_question(item, order)

        # Default: unknown pending_field, advance to next question
        order.clear_pending()
        return self.checkout_utils_handler.get_next_question(order)

    def _handle_item_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user selecting from multiple generic item options (cookies, muffins, etc.)."""
        if not order.pending_item_options:
            order.clear_pending()
            return StateMachineResult(
                message="What would you like to order?",
                order=order,
            )

        user_lower = user_input.lower().strip()
        options = order.pending_item_options
        quantity = order.pending_item_quantity or 1

        # Reject negative numbers or other invalid input early
        if user_lower.startswith('-') or user_lower.startswith('−'):
            option_list = [f"{i}. {item.get('name', 'Unknown')}" for i, item in enumerate(options[:6], 1)]
            options_str = "\n".join(option_list)
            return StateMachineResult(
                message=f"Please choose a number from 1 to {len(options[:6])}:\n{options_str}",
                order=order,
            )

        # Try to match by number (1, 2, 3, "first", "second", etc.)
        # IMPORTANT: Sorted by length descending so longer matches are checked first
        # (e.g., "the second one" should match "the second" not "one")
        number_patterns = sorted([
            ("the first", 0), ("number one", 0), ("number 1", 0), ("first", 0), ("one", 0), ("1", 0),
            ("the second", 1), ("number two", 1), ("number 2", 1), ("second", 1), ("two", 1), ("2", 1),
            ("the third", 2), ("number three", 2), ("number 3", 2), ("third", 2), ("three", 2), ("3", 2),
            ("the fourth", 3), ("number four", 3), ("number 4", 3), ("fourth", 3), ("four", 3), ("4", 3),
            ("the fifth", 4), ("number five", 4), ("number 5", 4), ("fifth", 4), ("five", 4), ("5", 4),
            ("the sixth", 5), ("number six", 5), ("number 6", 5), ("sixth", 5), ("six", 5), ("6", 5),
        ], key=lambda x: len(x[0]), reverse=True)

        selected_item = None

        # Check for number/ordinal selection (longer patterns first)
        for key, idx in number_patterns:
            if key in user_lower:
                if idx < len(options):
                    selected_item = options[idx]
                    break
                else:
                    # User selected a number that's out of range - ask again
                    logger.info("ITEM SELECTION: User selected %s but only %d options available", key, len(options))
                    option_list = [f"{i}. {item.get('name', 'Unknown')}" for i, item in enumerate(options[:6], 1)]
                    options_str = "\n".join(option_list)
                    return StateMachineResult(
                        message=f"I only have {len(options[:6])} options. Please choose:\n{options_str}",
                        order=order,
                    )

        # If not found by number, try to match by name
        if not selected_item:
            for option in options:
                option_name = option.get("name", "").lower()
                # Check if the option name is in user input or vice versa
                # Require minimum length to avoid false matches
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
            option_list = [f"{i}. {item.get('name', 'Unknown')}" for i, item in enumerate(options[:6], 1)]
            options_str = "\n".join(option_list)
            return StateMachineResult(
                message=f"I didn't catch which one. Please choose:\n{options_str}",
                order=order,
            )

        # Found the selection - clear pending state and add the item directly
        selected_name = selected_item.get("name", "item")
        selected_price = selected_item.get("base_price", 0.0)
        selected_id = selected_item.get("id")

        order.pending_item_options = []
        order.pending_item_quantity = 1
        order.clear_pending()

        logger.info("ITEM SELECTION: User chose '%s', adding %d item(s)", selected_name, quantity)

        # Check if it's an omelette (requires side choice configuration)
        is_omelette = "omelette" in selected_name.lower() or "omelet" in selected_name.lower()

        # Directly create the MenuItemTask(s) - no need to go through add_menu_item
        # since we already have all the item details from pending_item_options
        first_item = None
        for _ in range(quantity):
            item = MenuItemTask(
                menu_item_name=selected_name,
                menu_item_id=selected_id,
                unit_price=selected_price,
                requires_side_choice=is_omelette,
                menu_item_type="omelette" if is_omelette else None,
            )
            if is_omelette:
                item.mark_in_progress()  # Omelettes need side choice configuration
            else:
                item.mark_complete()  # Desserts/simple items don't need configuration
            order.items.add_item(item)
            if first_item is None:
                first_item = item

        if is_omelette:
            # Set state to wait for side choice
            order.phase = OrderPhase.CONFIGURING_ITEM.value
            order.pending_item_id = first_item.id
            order.pending_field = "side_choice"
            return StateMachineResult(
                message=f"Would you like a bagel or fruit salad with your {selected_name}?",
                order=order,
            )

        # Return to taking items phase for non-omelette items
        order.phase = OrderPhase.TAKING_ITEMS.value
        return StateMachineResult(
            message=f"Got it, {quantity} {selected_name}{'s' if quantity > 1 and not selected_name.endswith('s') else ''}. Anything else?",
            order=order,
        )
