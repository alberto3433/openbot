"""
Configuring Item Handler for Order State Machine.

This module handles the configuration of items (answering questions about
items being configured like size, style, toasted, spread, etc.).

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import re

from .models import OrderTask, MenuItemTask, parse_pending_field
from .schemas import StateMachineResult, OrderPhase, Selection
from .parsers.constants import extract_selection_index, _SELECTION_PATTERNS
from .parsers.deterministic.patterns import parse_can_you_make_it
from .modifier_change_handler import ChangeRequest
from orderbot.menu_data_cache import menu_cache
from orderbot.cache.base import pluralize

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

# Patterns to strip common ordering prefixes to extract the actual value
# e.g., "I want avocado" -> "avocado", "give me tomatoes" -> "tomatoes"
_ORDERING_PREFIX_PATTERN = re.compile(
    r"^(?:i(?:'?d)?\s*(?:want|like|need|have)|"
    r"(?:can\s+i\s+(?:get|have))|"
    r"(?:give\s+me)|"
    r"(?:make\s+it(?:\s+a)?)|"
    r"(?:let(?:'?s)?\s+(?:do|go\s+with))|"
    r"(?:i(?:'?ll)?\s+(?:take|have|get)))\s+",
    re.IGNORECASE
)

# Pattern to detect modifier inquiries like "what toppings do you have?"
# Captures the category (e.g., "toppings", "sweeteners", "spreads")
_MODIFIER_INQUIRY_PATTERN = re.compile(
    r"what (\w+(?:\s+\w+)?)\s+do\s+you\s+(?:have|offer|carry)",
    re.IGNORECASE
)


def _extract_answer_value(user_input: str) -> str:
    """Extract the actual answer value by stripping common ordering prefixes.

    Args:
        user_input: The user's raw input

    Returns:
        The input with ordering prefixes stripped, or the original if no prefix found
    """
    stripped = _ORDERING_PREFIX_PATTERN.sub("", user_input.strip())
    # Also strip trailing "please"
    stripped = re.sub(r"\s+please\s*$", "", stripped, flags=re.IGNORECASE)
    return stripped.strip()


def _detect_modifier_inquiry(user_input: str) -> str | None:
    """Detect modifier inquiry requests like 'what toppings do you have?'

    Args:
        user_input: The user's input text

    Returns:
        The extracted category (e.g., "toppings", "sweeteners") or None if not a modifier inquiry
    """
    match = _MODIFIER_INQUIRY_PATTERN.search(user_input)
    if match:
        category = match.group(1).strip().lower()
        logger.debug("Detected modifier inquiry for category: %s", category)
        return category
    return None


def _is_valid_answer_for_pending_field(user_input: str, pending_field: str | None) -> bool:
    """Check if user input could be a valid answer to the current configuration question.

    This is used to prevent false positive change request detection. If the user says
    "I want avocado" when asked about toppings, we should treat it as an answer,
    not as a modifier change request.

    Args:
        user_input: The user's input text
        pending_field: The current configuration field in "item_type:attr_slug" format

    Returns:
        True if the input appears to be a valid answer for the pending field
    """
    if not pending_field:
        return False

    # Extract the potential answer value
    answer_value = _extract_answer_value(user_input).lower()
    if not answer_value:
        return False

    # Parse the pending_field to get item_type and attr_slug
    item_type_slug, attr_slug = parse_pending_field(pending_field)

    # Handle customization_checkpoint and customization_selection specially
    # These are open-ended fields where any valid ingredient is a valid answer
    if attr_slug in ("customization_checkpoint", "customization_selection"):
        # Check if this is a known ingredient (toppings, proteins, cheeses, etc.)
        try:
            if menu_cache.is_known_modifier(answer_value):
                logger.debug("Found known modifier '%s' during customization", answer_value)
                return True
        except Exception as e:
            logger.debug("Error checking ingredient for customization: %s", e)
        return False

    # For standard "item_type:attr_slug" format, need both parts
    if not item_type_slug or not attr_slug:
        return False

    # Check if this value is valid for the current attribute
    try:
        # Get the valid options for this attribute
        attrs = menu_cache.get_item_type_attributes(item_type_slug)
        if attr_slug in attrs:
            attr_config = attrs[attr_slug]
            # Check if the value matches any option
            for opt in attr_config.get("options", []):
                opt_name = opt.get("display_name", "").lower()
                opt_slug = opt.get("slug", "").lower()
                if answer_value == opt_name or answer_value == opt_slug:
                    return True
                # Also check if answer_value is contained in option name
                if opt_name and answer_value in opt_name:
                    return True

            # For ingredient-based attributes, check against ingredients
            if attr_config.get("loads_from_ingredients"):
                # Check if this is a known ingredient
                if menu_cache.is_known_modifier(answer_value):
                    return True
    except Exception as e:
        logger.debug("Error checking valid answer for %s: %s", pending_field, e)

    return False


def _get_valid_config_answers() -> set[str]:
    """Get the set of valid configuration answers from the database.

    Combines affirmative/negative response patterns with all attribute options
    from the database. This is fully data-driven - no hardcoded values.

    Returns:
        Set of lowercase answer words that are valid responses to config questions

    Raises:
        MenuDataNotLoadedError: If menu cache is not loaded or configuration data is missing
    """
    from orderbot.menu_data_cache import menu_cache

    # Start with affirmative/negative response patterns from database
    answers = menu_cache.get_response_patterns("affirmative")
    answers.update(menu_cache.get_response_patterns("negative"))

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


def _is_off_topic_request(user_input: str, pending_field: str | None = None) -> bool:
    """Check if user input is an off-topic request during configuration.

    This function determines if the user is asking about something unrelated to
    the current configuration question. It's data-driven - keywords are loaded
    from the database based on the attribute being configured.

    Args:
        user_input: The user's input text
        pending_field: The current configuration field in "item_type:attr_slug" format
                      (e.g., "bagel:spread", "sized_beverage:size")

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
        item_type_slug, attr_slug = parse_pending_field(pending_field)

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

        # Allow "what X do you have?" for any ingredient category (e.g., "what toppings do you have?")
        # This allows users to inquire about menu options even during item configuration
        if re.search(r"what \w+ do you have", input_lower):
            return False  # Let them ask about any category

        # Data-driven keyword matching: if this is an attribute config field,
        # get relevant keywords from the database
        if item_type_slug and attr_slug:
            try:
                relevant_keywords = menu_cache.get_relevant_keywords_for_attribute(
                    item_type_slug, attr_slug
                )
                if any(kw in input_lower for kw in relevant_keywords):
                    return False  # Question is relevant to the current attribute
            except Exception as e:
                logger.debug("Keyword lookup failed for %s.%s: %s", item_type_slug, attr_slug, e)

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
            # Allow "what X do you have?" questions - user is asking about offered options
            if re.search(r"what \w+ do you have", input_lower):
                return False
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
            except Exception as e:
                logger.debug("Customization options lookup failed for %s: %s", item_type_slug, e)
            # Allow ingredient category names (data-driven from database)
            try:
                category_names = menu_cache.get_all_ingredient_categories()
                if any(cat in input_lower for cat in category_names):
                    return False
            except Exception as e:
                logger.debug("Ingredient category lookup failed: %s", e)

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

        # Handle modifier selection (disambiguation for modifiers like "cream cheese")
        if order.pending_field == "modifier_selection":
            return self._handle_modifier_selection(user_input, order)

        # Handle duplicate selection when user said "another one" with multiple items in cart
        if order.pending_field == "duplicate_selection":
            return self.taking_items_handler.handle_duplicate_selection(user_input, order)

        # Handle "same thing" clarification when user has both previous order AND cart items
        if order.pending_field == "same_thing_clarification":
            return self.taking_items_handler.handle_same_thing_clarification(user_input, order)

        # Handle suggested item confirmation ("Would you like to order one?" -> "yes" / "give me one")
        if order.pending_field == "confirm_suggested_item":
            return self.taking_items_handler.handle_confirm_suggested_item(user_input, order)

        # Handle item switch confirmation ("can you make it X?" -> similar item found)
        if order.pending_field == "confirm_item_switch":
            return self._handle_confirm_item_switch(user_input, order)

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

        # Context-aware check: if input could be a valid answer to the current question,
        # skip change request and off-topic detection. This prevents "I want avocado" from
        # being misinterpreted as a change request or off-topic when asked about toppings.
        is_valid_answer = _is_valid_answer_for_pending_field(user_input, order.pending_field)
        if is_valid_answer:
            logger.debug("Input is valid answer for %s - skipping change/off-topic detection", order.pending_field)

        # Check for modifier change requests during configuration
        # If detected, try to apply immediately instead of deferring
        change_request = None if is_valid_answer else self.modifier_change_handler.detect_change_request(user_input)
        if change_request and isinstance(item, MenuItemTask):
            result = self._apply_modification_during_config(change_request, item, order)
            if result:
                return result
            # If couldn't apply, fall through to normal processing

        # Check for "can you make it X?" style requests (e.g., "can you make it iced?")
        # This handles users asking to modify an aspect of the item being configured
        if not is_valid_answer and isinstance(item, MenuItemTask):
            can_you_make_it_result = self._handle_can_you_make_it(user_input, item, order)
            if can_you_make_it_result:
                return can_you_make_it_result

        # Check for off-topic requests during configuration (e.g., "what syrups do you have?", "add vanilla syrup")
        # If detected, politely redirect back to the current configuration question
        # Note: Questions relevant to the current config (e.g., "what cream cheese do you have?" when asked about spread) are allowed
        # Skip this check if we already determined the input is a valid answer
        if not is_valid_answer and _is_off_topic_request(user_input, order.pending_field):
            logger.info("OFF-TOPIC REQUEST: Detected during config: '%s'", user_input[:50])
            # Get a friendly description of the item being configured
            item_name = item.get_summary() if hasattr(item, 'get_summary') else "your item"
            current_question = self.config_helper_handler.get_current_config_question(order, item)
            if current_question:
                msg = f"Let's finish with your {item_name} first. {current_question}"
            else:
                msg = f"Let's finish with your {item_name} first."
            return StateMachineResult(message=msg, order=order)

        # Check for modifier inquiries like "what toppings do you have?" that passed the off-topic check
        # These should be routed to the store_info_handler for proper pagination support
        # EXCEPT when at customization_checkpoint or in attribute configuration (item_type:attr_slug)
        # - customization_checkpoint: handle_customization_checkpoint() has proper options inquiry handling
        # - item_type:attr_slug: handle_attribute_input() has _detect_different_attribute_inquiry()
        modifier_category = _detect_modifier_inquiry(user_input)
        pending_is_attr_config = order.pending_field and ":" in order.pending_field
        if (modifier_category
            and self.taking_items_handler
            and self.taking_items_handler.store_info_handler
            and order.pending_field != "customization_checkpoint"
            and not pending_is_attr_config):
            logger.info("MODIFIER INQUIRY during config: category='%s'", modifier_category)
            return self.taking_items_handler.store_info_handler.handle_modifier_inquiry(
                None,  # item_type - not specified
                modifier_category,  # category extracted from query
                order,
            )

        # Route to field-specific handler
        if order.pending_field == "side_choice":
            return self.config_helper_handler.handle_side_choice(user_input, item, order)

        # Handle menu item configuration (deli sandwiches, etc.)
        if order.pending_field == "customization_checkpoint":
            if isinstance(item, MenuItemTask) and self.menu_item_handler:
                return self.menu_item_handler.handle_customization_checkpoint(user_input, item, order)
        elif order.pending_field == "customization_selection":
            if isinstance(item, MenuItemTask) and self.menu_item_handler:
                return self.menu_item_handler.handle_customization_selection(user_input, item, order)

        # Data-driven routing: pending_field format is "item_type:attr_slug"
        # Parse the pending_field and route to the appropriate handler
        item_type_slug, attr_slug = parse_pending_field(order.pending_field)
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
        # Uses shared _SELECTION_PATTERNS from constants (sorted by length descending)
        selected_item = None

        # Check for number/ordinal selection (longer patterns first)
        for key, idx in _SELECTION_PATTERNS:
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

        # Found the selection - clear pending state
        selected_name = selected_item.get("name", "item")
        selected_price = selected_item.get("base_price", 0.0)
        selected_id = selected_item.get("id")
        selected_item_type = selected_item.get("item_type")

        # Get any pre-filled modifiers from disambiguation (size, milk, etc.)
        # Filter out structural keys that aren't actual item attributes
        raw_pre_filled = order.pending_item_modifiers or {}
        non_attribute_keys = {"item_name", "quantity", "original_input", "item_type", "extracted_selections"}
        pre_filled = {k: v for k, v in raw_pre_filled.items() if k not in non_attribute_keys}

        # Extract and convert selections (stored as dicts for JSON serialization)
        stored_selections = raw_pre_filled.get("extracted_selections")
        extracted_selections = None
        if stored_selections:
            extracted_selections = [
                Selection(**s) if isinstance(s, dict) else s
                for s in stored_selections
            ]

        order.pending_item_options = []
        order.pending_item_quantity = 1
        order.pending_item_modifiers = None
        order.clear_pending()

        logger.info("ITEM SELECTION: User chose '%s' (type=%s), adding %d item(s)",
                    selected_name, selected_item_type, quantity)

        # Check if item type is configurable (has conversation attributes like size, temperature)
        configurable_types = menu_cache.get_configurable_item_types()
        is_configurable = selected_item_type in configurable_types if selected_item_type else False

        # For configurable items (sized_beverage, bagel, etc.), route through proper config flow
        if is_configurable and self.item_adder_handler:
            menu_item = {
                "name": selected_name,
                "id": selected_id,
                "base_price": selected_price,
                "item_type": selected_item_type,
            }
            return self.item_adder_handler._create_configurable_item(
                menu_item=menu_item,
                order=order,
                quantity=quantity,
                pre_filled_attributes=pre_filled if pre_filled else None,
                extracted_selections=extracted_selections,
            )

        # For non-configurable items, use direct creation
        # Check if item type requires side choice (data-driven from database)
        requires_side_choice = (
            menu_cache.item_type_has_side_choice(selected_item_type)
            if selected_item_type else False
        )

        # Directly create the MenuItemTask(s) for non-configurable items
        first_item = None
        for _ in range(quantity):
            item = MenuItemTask(
                menu_item_name=selected_name,
                menu_item_id=selected_id,
                unit_price=selected_price,
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
            order.set_phase(OrderPhase.CONFIGURING_ITEM)
            order.pending_item_id = first_item.id
            order.pending_field = "side_choice"
            return StateMachineResult(
                message=question,
                order=order,
            )

        # Return to taking items phase for items not requiring side choice
        order.set_phase(OrderPhase.TAKING_ITEMS)
        return StateMachineResult(
            message=f"Got it, {quantity} {pluralize(selected_name) if quantity > 1 else selected_name}. Anything else?",
            order=order,
        )

    def _handle_modifier_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user selecting from multiple modifier options (e.g., cream cheese types)."""
        if not order.pending_item_options:
            order.clear_pending()
            order.pending_modifier_target_item_index = None
            order.pending_modifier_quantity = None
            return StateMachineResult(
                message="What would you like to order?",
                order=order,
            )

        # Get the disambiguation handler through taking_items_handler
        disambiguation = self.taking_items_handler.item_adder_handler.disambiguation_handler

        # Use existing disambiguation resolution
        selected = disambiguation.resolve_disambiguation(user_input, order)

        if not selected:
            # Couldn't match - re-ask
            return StateMachineResult(
                message=disambiguation.get_reask_message(order),
                order=order,
            )

        # Get the target item and add the modifier
        target_idx = order.pending_modifier_target_item_index
        if target_idx is None or target_idx >= len(order.items.items):
            disambiguation.clear_disambiguation_state(order)
            order.pending_modifier_target_item_index = None
            order.pending_modifier_quantity = None
            return StateMachineResult(
                message="Something went wrong. What else can I help with?",
                order=order,
            )

        target_item = order.items.items[target_idx]
        quantity = order.pending_modifier_quantity or 1

        # Add the selected modifier to the item
        if isinstance(target_item, MenuItemTask):
            target_item.add_selection(
                slug=selected["slug"],
                category=selected["category"],
                display_name=selected["name"],
                quantity=quantity,
            )

            # Recalculate price
            if self.taking_items_handler and self.taking_items_handler.pricing:
                self.taking_items_handler.pricing.recalculate_item_price(target_item)

        # Clear disambiguation state
        disambiguation.clear_disambiguation_state(order)
        order.pending_modifier_target_item_index = None
        order.pending_modifier_quantity = None

        logger.info("MODIFIER SELECTION: User chose '%s', added to item", selected["name"])

        # Return to taking items phase
        order.set_phase(OrderPhase.TAKING_ITEMS)
        return StateMachineResult(
            message=f"Added {selected['name']}. Anything else?",
            order=order,
        )

    def _handle_can_you_make_it(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """
        Handle 'can you make it X?' requests during item configuration.

        When user asks "can you make it iced?" while being asked about size:
        1. Check if the current item has an attribute option matching "iced"
        2. If yes, apply it and continue with normal configuration
        3. If not, search for a similar menu item with that modifier
        4. Offer to switch or report "Sorry, we don't have that option"

        Args:
            user_input: The user's input text
            item: The item being configured
            order: The current order state

        Returns:
            StateMachineResult if handled, None if not a "can you make it X?" request
        """
        modifier = parse_can_you_make_it(user_input)
        if not modifier:
            return None

        logger.info("CAN_YOU_MAKE_IT: Detected modifier request '%s' for %s", modifier, item.menu_item_name)
        modifier_lower = modifier.lower()

        # 1. Check if current item has an attribute option matching this modifier
        item_type = item.menu_item_type
        if item_type:
            try:
                attrs = menu_cache.get_item_type_attributes(item_type)
                for attr_slug, attr_config in attrs.items():
                    for opt in attr_config.get("options", []):
                        opt_slug = opt.get("slug", "").lower()
                        opt_display = opt.get("display_name", "").lower()
                        if modifier_lower == opt_slug or modifier_lower == opt_display:
                            # Found matching attribute option - apply it
                            logger.info("CAN_YOU_MAKE_IT: Found matching attr %s=%s", attr_slug, opt_slug)
                            item.set_attribute(attr_slug, opt.get("slug"))
                            # Re-ask current question (the one we were on)
                            current_question = self.config_helper_handler.get_current_config_question(order, item)
                            if current_question:
                                return StateMachineResult(
                                    message=f"Sure! {current_question}",
                                    order=order,
                                )
                            return None  # Continue with normal flow
            except Exception as e:
                logger.debug("Error checking attributes for 'can you make it': %s", e)

        # 2. Check if it's an ingredient/modifier (spread, topping, syrup, etc.)
        matches = menu_cache.find_matching_ingredients(modifier_lower)
        if len(matches) == 1:
            match = matches[0]
            self._replace_or_add_modifier(item, match)
            logger.info("CAN_YOU_MAKE_IT: Applied modifier %s (%s)", match['name'], match['category'])
            return self._continue_config_with_message(
                f"Sure, I've changed the {match['category']} to {match['name']}.", item, order
            )
        elif len(matches) > 1:
            # Multiple matches - need disambiguation
            logger.info("CAN_YOU_MAKE_IT: Multiple matches for '%s', starting disambiguation", modifier)
            return self._start_modifier_disambiguation(modifier, matches, item, order)

        # 3. Search for similar menu item with the modifier
        if self.item_adder_handler and self.item_adder_handler.menu_lookup:
            similar_item = self.item_adder_handler.menu_lookup.find_similar_item_with_modifier(
                item.menu_item_name or "",
                modifier,
            )
            if similar_item:
                logger.info(
                    "CAN_YOU_MAKE_IT: Found similar item '%s' for '%s' + '%s'",
                    similar_item.get("name"),
                    item.menu_item_name,
                    modifier,
                )
                # Offer to switch
                order.pending_switch_item = similar_item
                order.pending_field = "confirm_item_switch"
                return StateMachineResult(
                    message=(
                        f"{item.menu_item_name} isn't available {modifier}, "
                        f"but we have {similar_item.get('name')}. Would you like that instead?"
                    ),
                    order=order,
                )

        # 4. Not found - report and re-ask
        logger.info("CAN_YOU_MAKE_IT: No matching attribute, ingredient, or similar item found for '%s'", modifier)
        current_question = self.config_helper_handler.get_current_config_question(order, item)
        if current_question:
            return StateMachineResult(
                message=f"Sorry, we don't have that option. {current_question}",
                order=order,
            )
        return StateMachineResult(
            message="Sorry, we don't have that option.",
            order=order,
        )

    def _handle_confirm_item_switch(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """
        Handle user confirmation for item switch (from "can you make it X?").

        Args:
            user_input: The user's response (yes/no)
            order: The current order state

        Returns:
            StateMachineResult with next action
        """
        switch_item = order.pending_switch_item
        if not switch_item:
            order.clear_pending()
            return StateMachineResult(
                message="What would you like to order?",
                order=order,
            )

        user_lower = user_input.lower().strip()

        # Check for affirmative response
        affirmative_patterns = menu_cache.get_response_patterns("affirmative")
        is_affirmative = any(p in user_lower for p in affirmative_patterns) or user_lower in ("yes", "yeah", "sure", "ok", "okay", "yep", "yup")

        if is_affirmative:
            # Get the current item being configured and remove it
            current_item = self.checkout_utils_handler.get_item_by_id(order, order.pending_item_id)
            if current_item:
                order.items.remove_item(current_item)

            # Clear switch state
            order.pending_switch_item = None
            order.clear_pending()

            # Add the new item via item_adder_handler
            if self.item_adder_handler:
                return self.item_adder_handler.add_menu_item(
                    switch_item.get("name", "item"),
                    order,
                    quantity=1,
                )

            # Fallback - just acknowledge
            order.set_phase(OrderPhase.TAKING_ITEMS)
            return StateMachineResult(
                message=f"Got it, {switch_item.get('name')}. Anything else?",
                order=order,
            )
        else:
            # User declined - continue with original item
            order.pending_switch_item = None
            # Get the original item and continue configuration
            original_item = self.checkout_utils_handler.get_item_by_id(order, order.pending_item_id)
            if original_item:
                # Clear the confirm_item_switch field and restore previous config state
                # Get the next question for the original item
                if isinstance(original_item, MenuItemTask) and self.menu_item_handler:
                    order.pending_field = None  # Clear to let get_first_question set it
                    return self.menu_item_handler.get_first_question(original_item, order)

            order.clear_pending()
            return StateMachineResult(
                message="No problem. What else can I help you with?",
                order=order,
            )

    def _apply_modification_during_config(
        self,
        change_request: ChangeRequest,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Apply a modification to the item being configured, then continue config.

        This handles the case where a user says something like "make it veggie cream cheese"
        during item configuration. Instead of deferring the change, we apply it immediately
        and continue with the remaining configuration questions.

        Args:
            change_request: The detected change request
            item: The item being configured
            order: The current order state

        Returns:
            StateMachineResult if the change was applied, None if we couldn't apply it
        """
        new_value = change_request.new_value
        logger.info("APPLY_MOD_DURING_CONFIG: Attempting to apply '%s' to item being configured", new_value)

        # Case 1: Unambiguous attribute change (bread, size, toasted, temperature)
        if not change_request.is_ambiguous and change_request.possible_attributes:
            attr_slug = change_request.possible_attributes[0]
            if attr_slug != "unknown":
                result = self.modifier_change_handler.apply_change(
                    order, item.id, attr_slug, new_value
                )
                if result.success:
                    logger.info("APPLY_MOD_DURING_CONFIG: Applied attribute change %s=%s", attr_slug, new_value)
                    return self._continue_config_with_message(
                        f"Sure, I've changed that to {new_value}.", item, order
                    )

        # Case 2: Try as modifier (spread, topping, syrup, etc.)
        matches = menu_cache.find_matching_ingredients(new_value.lower())

        if len(matches) == 1:
            match = matches[0]
            # Replace or add the modifier
            self._replace_or_add_modifier(item, match)
            logger.info("APPLY_MOD_DURING_CONFIG: Applied modifier change %s (%s)", match['name'], match['category'])
            return self._continue_config_with_message(
                f"Sure, I've changed the {match['category']} to {match['name']}.", item, order
            )

        if len(matches) > 1:
            # Multiple matches - need disambiguation
            logger.info("APPLY_MOD_DURING_CONFIG: Multiple matches for '%s', starting disambiguation", new_value)
            return self._start_modifier_disambiguation(new_value, matches, item, order)

        # Couldn't apply - fall through to normal processing
        logger.debug("APPLY_MOD_DURING_CONFIG: Could not apply change for '%s'", new_value)
        return None

    def _replace_or_add_modifier(self, item: MenuItemTask, match: dict) -> None:
        """Replace existing modifier of same category, or add if none exists.

        Args:
            item: The item to modify
            match: Dict with slug, name, category, base_price from find_matching_ingredients()
        """
        category = match["category"]

        # Remove existing modifier of same category (if any)
        item.modifiers = [m for m in item.modifiers if m.get("category") != category]

        # Add new one
        item.add_selection(
            slug=match["slug"],
            category=category,
            display_name=match["name"],
            quantity=1,
            price=match.get("base_price", 0.0),
        )

        # Recalculate price
        if self.modifier_change_handler and self.modifier_change_handler.pricing:
            self.modifier_change_handler.pricing.recalculate_item_price(item)

    def _continue_config_with_message(
        self, message: str, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult:
        """Return message + next config question, or proceed if item complete.

        Args:
            message: The feedback message about the change that was applied
            item: The item being configured
            order: The current order state

        Returns:
            StateMachineResult with the message and next question, or checkout transition
        """
        current_question = self.config_helper_handler.get_current_config_question(order, item)
        if current_question:
            return StateMachineResult(message=f"{message} {current_question}", order=order)

        # Item configuration complete - proceed to next question or checkout
        return self.checkout_utils_handler.get_next_question(order)

    def _start_modifier_disambiguation(
        self,
        new_value: str,
        matches: list[dict],
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Start disambiguation flow for a modifier with multiple matches.

        Args:
            new_value: The modifier value that has multiple matches
            matches: List of matching ingredient dicts
            item: The item being configured
            order: The current order state

        Returns:
            StateMachineResult asking user to select which modifier they want
        """
        # Store the modifier options for disambiguation
        order.pending_item_options = matches
        order.pending_field = "modifier_selection"
        order.pending_modifier_target_item_index = order.items.items.index(item)

        # Build disambiguation message
        option_lines = []
        for i, match in enumerate(matches[:6], 1):
            price_str = ""
            if match.get("base_price", 0) > 0:
                price_str = f" (+${match['base_price']:.2f})"
            option_lines.append(f"{i}. {match['name']}{price_str}")

        options_str = "\n".join(option_lines)
        return StateMachineResult(
            message=f"Which {new_value} would you like?\n{options_str}",
            order=order,
        )
