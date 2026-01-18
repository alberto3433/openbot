"""
Configuring Item Handler for Order State Machine.

This module handles the configuration of items (answering questions about
items being configured like size, style, toasted, spread, etc.).

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import re

from .models import OrderTask, MenuItemTask
from .schemas import StateMachineResult, OrderPhase
from orderbot.menu_data_cache import menu_cache

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

# Truly generic words that are always valid answers to configuration questions
# These are universal affirmative/negative responses, not menu-item-specific values.
# All menu-item-specific values (toasted, hot, small, etc.) come from the database.
_GENERIC_AFFIRMATIVE_ANSWERS = {
    "yes", "no", "yeah", "nope", "sure", "please", "ok", "okay",
    "yep", "yup", "nah", "definitely", "absolutely", "of course",
}


def _get_valid_config_answers() -> set[str]:
    """Get the set of valid configuration answers from the database.

    Combines truly generic affirmative/negative answers with all attribute options
    from the database. This is fully data-driven - no hardcoded menu item values.

    Returns:
        Set of lowercase answer words that are valid responses to config questions

    Raises:
        MenuDataNotLoadedError: If menu cache is not loaded or configuration data is missing
    """
    from orderbot.menu_data_cache import menu_cache

    # Start with truly generic affirmative/negative answers
    answers = _GENERIC_AFFIRMATIVE_ANSWERS.copy()

    # Get all attribute option words from database (includes negation variants)
    # This covers: size, temperature, toasted/not toasted, bagel types, side items, etc.
    db_answers = menu_cache.get_all_config_answer_words()
    answers.update(db_answers)

    return answers


# Cache the config answers to avoid repeated database calls
_cached_config_answers: set[str] | None = None


def _get_cached_config_answers() -> set[str]:
    """Get cached valid config answers, loading from database if needed."""
    global _cached_config_answers
    if _cached_config_answers is None:
        _cached_config_answers = _get_valid_config_answers()
    return _cached_config_answers


def _parse_pending_field(pending_field: str | None) -> tuple[str | None, str | None]:
    """Parse pending_field to extract item_type and attribute slug.

    The pending_field format is "item_type:attr_slug" (e.g., "bagel:spread_type").
    For flow-control fields without a colon, returns (None, pending_field).

    Args:
        pending_field: The pending field string (e.g., "bagel:spread_type" or "drink_selection")

    Returns:
        Tuple of (item_type_slug, attr_slug). Both may be None if pending_field is None.
        For flow-control fields (no colon), item_type_slug will be None.

    Examples:
        >>> _parse_pending_field("bagel:spread_type")
        ("bagel", "spread_type")
        >>> _parse_pending_field("drink_selection")
        (None, "drink_selection")
        >>> _parse_pending_field(None)
        (None, None)
    """
    if not pending_field:
        return None, None
    if ":" in pending_field:
        parts = pending_field.split(":", 1)
        return parts[0], parts[1]
    return None, pending_field


def _is_off_topic_request(user_input: str, pending_field: str | None = None) -> bool:
    """Check if user input is an off-topic request during configuration.

    This function determines if the user is asking about something unrelated to
    the current configuration question. It's data-driven - keywords are loaded
    from the database based on the attribute being configured.

    Args:
        user_input: The user's input text
        pending_field: The current configuration field in "item_type:attr_slug" format
                      (e.g., "bagel:spread_type", "sized_beverage:size")

    Returns:
        True if the request is off-topic and should trigger a redirect
    """
    from orderbot.menu_data_cache import menu_cache

    input_lower = user_input.lower().strip()

    # Get valid config answers from database (cached)
    valid_config_answers = _get_cached_config_answers()

    # First check if this looks like a valid config answer
    # Simple answers like "small", "large", "hot", "iced", etc.
    if input_lower in valid_config_answers:
        return False

    # Check for valid answers with minor variations
    for answer in valid_config_answers:
        if input_lower == answer or input_lower == f"{answer} please":
            return False

    # Check if the question is RELEVANT to the current config question
    if pending_field:
        # Parse the pending_field to get item_type and attr_slug
        item_type_slug, attr_slug = _parse_pending_field(pending_field)

        # Generic "what do you have?" / "what kind do you have?" / "what are my options?"
        # These are always relevant when asked during configuration (truly universal patterns)
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
        ]
        if any(pattern in input_lower for pattern in generic_option_patterns):
            return False  # Let them ask about options

        # Data-driven keyword matching: if this is an attribute config field,
        # get relevant keywords from the database
        if item_type_slug and attr_slug:
            try:
                relevant_keywords = menu_cache.get_relevant_keywords_for_attribute(
                    item_type_slug, attr_slug
                )
                if any(kw in input_lower for kw in relevant_keywords):
                    return False  # Question is relevant to the current attribute
            except Exception:
                # If DB lookup fails, fall through to off-topic check
                pass

            # Also allow templatized questions: "what {attr} do you have?"
            # e.g., "what spreads do you have?" when configuring spread
            attr_display = attr_slug.replace("_", " ")
            if attr_display in input_lower:
                return False
            # Check for plural form
            if f"{attr_display}s" in input_lower:
                return False

        # During customization_checkpoint or customization_selection, "add X" commands are valid
        # The bot is specifically offering options like "Add Egg, Extra Cheese, Toppings"
        if attr_slug in ("customization_checkpoint", "customization_selection"):
            # Allow "add X" commands since the bot offered these as valid choices
            if input_lower.startswith("add "):
                return False
            # Get customization keywords from database (available modifier categories)
            try:
                # Load customization options from the item type's modifiable attributes
                if item_type_slug:
                    attrs = menu_cache.get_item_type_attributes(item_type_slug)
                    for attr_config in attrs.values():
                        for opt in attr_config.get("options", []):
                            opt_name = opt.get("display_name", "").lower()
                            if opt_name and opt_name in input_lower:
                                return False
            except Exception:
                pass
            # Allow ingredient category names (data-driven from database)
            try:
                category_names = menu_cache.get_all_ingredient_categories()
                if any(cat in input_lower for cat in category_names):
                    return False
            except Exception:
                pass

    # Check if it matches any off-topic pattern
    for pattern in OFF_TOPIC_PATTERNS:
        if pattern.search(user_input):
            # Special case: "make it X" where X is a valid config answer
            if pattern.pattern.startswith("^make"):
                # Check against all valid config answers (database-driven)
                for answer in valid_config_answers:
                    if answer in input_lower:
                        return False
            return True

    return False


class ConfiguringItemHandler:
    """
    Handles configuring items (answering configuration questions).

    Routes user input to the appropriate field-specific handler based
    on the pending_field in the order. The pending_field format is
    "item_type:attr_slug" (e.g., "bagel:toasted", "sized_beverage:size").
    """

    def __init__(
        self,
        config_helper_handler: "ConfigHelperHandler | None" = None,
        checkout_utils_handler: "CheckoutUtilsHandler | None" = None,
        modifier_change_handler: "ModifierChangeHandler | None" = None,
        item_adder_handler: "ItemAdderHandler | None" = None,
        menu_item_handler: "MenuItemConfigHandler | None" = None,
    ) -> None:
        """
        Initialize the configuring item handler.

        Args:
            config_helper_handler: Handler for config helpers (side choice, etc.).
            checkout_utils_handler: Handler for checkout utilities.
            modifier_change_handler: Handler for modifier changes.
            item_adder_handler: Handler for adding items.
            menu_item_handler: Handler for menu item configuration (deli sandwiches, espresso, etc.).
        """
        self.config_helper_handler = config_helper_handler
        self.checkout_utils_handler = checkout_utils_handler
        self.modifier_change_handler = modifier_change_handler
        self.item_adder_handler = item_adder_handler
        self.menu_item_handler = menu_item_handler
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
        # Handle generic item selection when multiple options were presented
        if order.pending_field == "item_selection":
            return self._handle_item_selection(user_input, order)

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

        # Handle bread_choice for menu items with bread-based sides (e.g., omelettes, salads)
        # Data-driven: check if side_choice references an item type that has bread attribute
        # bread_choice is canonical; bagel_choice is legacy
        if order.pending_field in ("bread_choice", "bagel_choice") and isinstance(item, MenuItemTask):
            side_choice = getattr(item, 'side_choice', None)
            if side_choice:
                # Check if the side choice item type has a bread attribute (data-driven)
                side_attrs = menu_cache.get_item_type_attributes(side_choice)
                if "bread" in side_attrs:
                    return self.config_helper_handler.handle_bagel_choice_for_side(
                        user_input, item, order
                    )

        # Handle espresso legacy fields - route to menu_item_handler
        if order.pending_field in ("espresso_modifiers", "espresso_syrup_flavor"):
            if isinstance(item, MenuItemTask) and self.menu_item_handler:
                return self.menu_item_handler.get_first_question(item, order)
            order.clear_pending()
            return self.checkout_utils_handler.get_next_question(order)

        # Handle menu item configuration (deli sandwiches, etc.)
        if order.pending_field == "customization_checkpoint":
            if isinstance(item, MenuItemTask) and self.menu_item_handler:
                return self.menu_item_handler.handle_customization_checkpoint(user_input, item, order)
        elif order.pending_field == "customization_selection":
            if isinstance(item, MenuItemTask) and self.menu_item_handler:
                return self.menu_item_handler.handle_customization_selection(user_input, item, order)

        # Data-driven routing: pending_field format is "item_type:attr_slug"
        # Parse the pending_field and route to the appropriate handler
        item_type_slug, attr_slug = _parse_pending_field(order.pending_field)
        if item_type_slug and attr_slug and isinstance(item, MenuItemTask) and self.menu_item_handler:
            logger.debug(
                "Routing '%s' through unified handler for %s attr=%s",
                order.pending_field, item_type_slug, attr_slug
            )
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
        selected_item_type = selected_item.get("item_type")

        order.pending_item_options = []
        order.pending_item_quantity = 1
        order.clear_pending()

        logger.info("ITEM SELECTION: User chose '%s' (type=%s), adding %d item(s)",
                    selected_name, selected_item_type, quantity)

        # Check if item type requires side choice (data-driven from database)
        requires_side_choice = (
            menu_cache.item_type_has_side_choice(selected_item_type)
            if selected_item_type else False
        )

        # Directly create the MenuItemTask(s) - no need to go through add_menu_item
        # since we already have all the item details from pending_item_options
        first_item = None
        for _ in range(quantity):
            item = MenuItemTask(
                menu_item_name=selected_name,
                menu_item_id=selected_id,
                unit_price=selected_price,
                requires_side_choice=requires_side_choice,
                menu_item_type=selected_item_type,
            )
            # Infer attributes from item name (data-driven)
            if self.item_adder_handler:
                self.item_adder_handler._infer_attributes_from_item_name(item)
            if requires_side_choice:
                item.mark_in_progress()  # Items with side choice need configuration
            else:
                item.mark_complete()  # Simple items don't need configuration
            order.items.add_item(item)
            if first_item is None:
                first_item = item

        if requires_side_choice:
            # Get the side choice attribute question from database
            side_choice_attr = menu_cache.get_side_choice_attribute(selected_item_type)
            question = (
                side_choice_attr.get("question_text") if side_choice_attr
                else f"Would you like a bagel or fruit salad with your {selected_name}?"
            )
            # Set state to wait for side choice
            order.phase = OrderPhase.CONFIGURING_ITEM.value
            order.pending_item_id = first_item.id
            order.pending_field = "side_choice"
            return StateMachineResult(
                message=question,
                order=order,
            )

        # Return to taking items phase for items not requiring side choice
        order.phase = OrderPhase.TAKING_ITEMS.value
        return StateMachineResult(
            message=f"Got it, {quantity} {selected_name}{'s' if quantity > 1 and not selected_name.endswith('s') else ''}. Anything else?",
            order=order,
        )
