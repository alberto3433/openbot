"""
Bagel Configuration Handler for Order State Machine.

This module handles all bagel configuration flow including:
- Bagel type selection
- Spread selection
- Toasted preference
- Cheese type clarification
- Multi-bagel configuration orchestration

Extracted from state_machine.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING, Callable, Union

from .models import (
    OrderTask,
    BagelItemTask,
    MenuItemTask,
    CoffeeItemTask,
    ItemTask,
    TaskStatus,
)
from .schemas import OrderPhase, StateMachineResult, ExtractedModifiers
from .parsers import (
    parse_toasted_deterministic,
)
from .parsers.llm_parsers import (
    parse_bagel_choice,
    parse_spread_choice,
    parse_toasted_choice,
)
from .parsers.deterministic import (
    extract_modifiers_from_input,
    _extract_spread,
    extract_spread_with_disambiguation,
)
from .parsers.constants import (
    DEFAULT_PAGINATION_SIZE,
    MORE_MENU_ITEMS_PATTERNS,
    get_spread_types,
    get_bagel_types,
    get_bagel_types_list,
)
from .message_builder import MessageBuilder
from .handler_config import HandlerConfig
from ..menu_data_cache import menu_cache

if TYPE_CHECKING:
    from .pricing import PricingEngine

logger = logging.getLogger(__name__)

# NOTE: Pagination uses DEFAULT_PAGINATION_SIZE from parsers.constants (uniform at 5)

# NOTE: get_bagel_types_list() is now loaded from the database via get_bagel_types_list()
# from parsers.constants, which delegates to menu_data_cache.

# NOTE: Cream cheese flavors are now loaded from the database via get_spread_types()
# from parsers.constants. Use _get_cream_cheese_types_list() to get them.


def _get_cream_cheese_types_list() -> list[str]:
    """
    Get cream cheese flavors from the database.

    Returns a sorted list of cream cheese flavor types (e.g., "plain", "scallion").
    Falls back to a minimal set if database is not loaded.
    """
    try:
        spread_types = get_spread_types()
        # Add "plain" which may not be in spread_types (it's the default)
        flavors = sorted(spread_types | {"plain"})
        return flavors if flavors else ["plain", "scallion", "veggie"]
    except RuntimeError:
        # Database not loaded, return minimal fallback
        return ["plain", "scallion", "veggie"]


def _is_pagination_request(user_input: str) -> bool:
    """Check if user input is asking for more options (pagination)."""
    for pattern in MORE_MENU_ITEMS_PATTERNS:
        if pattern.search(user_input):
            return True
    return False


def _build_modifier_acknowledgment(modifiers: ExtractedModifiers) -> str:
    """
    Build an acknowledgment message for modifiers that were added.

    Args:
        modifiers: Extracted modifiers from user input

    Returns:
        Acknowledgment string like "Got it, I've added bacon and cheese! " or empty string
    """
    added_items = []
    if modifiers.proteins:
        added_items.extend(modifiers.proteins)
    # For cheese: if needs clarification, say "cheese" generically; otherwise list specific types
    if modifiers.needs_cheese_clarification:
        added_items.append("cheese")
    elif modifiers.cheeses:
        added_items.extend(modifiers.cheeses)
    if modifiers.toppings:
        added_items.extend(modifiers.toppings)
    if modifiers.spreads:
        added_items.extend(modifiers.spreads)

    if not added_items:
        return ""

    if len(added_items) == 1:
        return f"Got it, I've added {added_items[0]}! "
    else:
        items_str = ", ".join(added_items[:-1]) + f" and {added_items[-1]}"
        return f"Got it, I've added {items_str}! "


def apply_modifiers_to_bagel(
    item: BagelItemTask,
    modifiers: ExtractedModifiers,
    skip_cheeses: bool = False,
) -> None:
    """
    Apply extracted modifiers to a bagel item.

    This consolidates the repeated modifier application logic used in
    multiple handlers (handle_bagel_choice, handle_toasted_choice, etc.).

    Args:
        item: The BagelItemTask to modify
        modifiers: Extracted modifiers from user input
        skip_cheeses: If True, don't add cheeses to extras (used when
                      cheese was already handled, e.g., in cheese choice handler)
    """
    # Proteins: first one goes to sandwich_protein if not set, rest to extras
    if modifiers.proteins:
        if not item.sandwich_protein:
            item.sandwich_protein = modifiers.proteins[0]
            item.extras.extend(modifiers.proteins[1:])
        else:
            item.extras.extend(modifiers.proteins)

    # Cheeses go to extras (unless we're skipping them)
    if not skip_cheeses:
        if modifiers.needs_cheese_clarification:
            # Add generic "cheese" - will be replaced with specific type later
            if "cheese" not in item.extras:
                item.extras.append("cheese")
            item.needs_cheese_clarification = True
        elif modifiers.cheeses:
            item.extras.extend(modifiers.cheeses)

    # Toppings go to extras
    if modifiers.toppings:
        item.extras.extend(modifiers.toppings)

    # Spreads: set if not already set
    if modifiers.spreads and not item.spread:
        item.spread = modifiers.spreads[0]

    # Append special instructions
    if modifiers.has_special_instructions():
        existing_instructions = item.special_instructions or ""
        new_instructions = modifiers.get_special_instructions_string()
        item.special_instructions = f"{existing_instructions}, {new_instructions}".strip(", ") if existing_instructions else new_instructions


class BagelConfigHandler:
    """
    Handles bagel configuration flow for orders.

    Manages bagel type selection, spread choice, toasted preference,
    cheese clarification, and multi-bagel configuration orchestration.
    """

    def __init__(
        self,
        config: HandlerConfig | None = None,
        get_item_by_id: Callable[[OrderTask, str], ItemTask | None] | None = None,
        configure_coffee: Callable[[OrderTask], StateMachineResult] | None = None,
        **kwargs,
    ):
        """
        Initialize the bagel configuration handler.

        Args:
            config: HandlerConfig with shared dependencies.
            get_item_by_id: Callback to find an item by ID.
            configure_coffee: Callback to configure next incomplete coffee.
            **kwargs: Legacy parameter support.
        """
        if config:
            self.model = config.model
            self.pricing = config.pricing
            self._get_next_question = config.get_next_question
            self._check_redirect = config.check_redirect
        else:
            # Legacy support for direct parameters
            self.model = kwargs.get("model", "gpt-4o-mini")
            self.pricing = kwargs.get("pricing")
            self._get_next_question = kwargs.get("get_next_question")
            self._check_redirect = kwargs.get("check_redirect")

        # Handler-specific callbacks (not in HandlerConfig)
        self._get_item_by_id = get_item_by_id or kwargs.get("get_item_by_id")
        self._configure_coffee = configure_coffee or kwargs.get("configure_coffee")

    def _map_field_name_to_db(self, field_name: str) -> str:
        """
        Map code field names to database attribute slugs.

        The code uses 'bagel_type' but the database attribute is now 'bread'
        to match deli_sandwich item type.

        Args:
            field_name: The code field name (e.g., "bagel_type", "toasted")

        Returns:
            The database attribute slug (e.g., "bread", "toasted")
        """
        # Map code field names to database attribute slugs
        field_mapping = {
            "bagel_type": "bread",  # Code uses bagel_type, DB uses bread
        }
        return field_mapping.get(field_name, field_name)

    def _get_bagel_question(self, field_name: str, fallback: str) -> str:
        """
        Get the question text for a bagel field from the database configuration.

        Uses the item_type_attributes table (via menu_cache) to get the question
        configured in the admin UI. Falls back to the provided default if not found.

        Args:
            field_name: The attribute slug (e.g., "bagel_type", "toasted", "spread")
            fallback: Default question text if not found in database

        Returns:
            The question text from the database, or the fallback if not found.
        """
        db_field_name = self._map_field_name_to_db(field_name)
        question = menu_cache.get_question_for_field("bagel", db_field_name)
        if question and question.strip():
            return question
        return fallback

    def _should_ask_bagel_field(self, field_name: str) -> bool:
        """
        Check if a bagel field should be asked based on database configuration.

        Checks the ask_in_conversation flag from item_type_attributes table.

        Args:
            field_name: The attribute slug (e.g., "bagel_type", "toasted", "spread")

        Returns:
            True if the field should be asked, False otherwise.
            Returns True by default if field not found (fail-safe).
        """
        db_field_name = self._map_field_name_to_db(field_name)
        fields = menu_cache.get_item_type_fields("bagel")
        for field in fields:
            if field["field_name"] == db_field_name:
                return field.get("ask", True)
        # Field not found in DB - default to asking (fail-safe)
        return True

    def _resolve_spread_disambiguation(
        self,
        user_input: str,
        options: list[str],
    ) -> str | None:
        """
        Resolve user's selection from disambiguation options.

        Args:
            user_input: User's response (e.g., "honey walnut", "the first one", "maple")
            options: List of spread type options (e.g., ["honey walnut", "maple raisin walnut"])

        Returns:
            Selected spread type if matched, None if no match found.
        """
        input_lower = user_input.lower().strip()

        # Remove common filler words
        input_lower = input_lower.replace("cream cheese", "").strip()
        input_lower = input_lower.replace("the ", "").strip()
        input_lower = input_lower.replace("please", "").strip()

        # Try exact match first
        for option in options:
            if option == input_lower:
                return option

        # Try if user said just the first word (e.g., "honey" for "honey walnut")
        for option in options:
            first_word = option.split()[0] if option else ""
            if first_word and first_word == input_lower:
                return option

        # Try substring match (e.g., "maple" matches "maple raisin walnut")
        for option in options:
            if input_lower in option:
                return option

        # Try if option is a substring of input (e.g., "honey walnut please")
        for option in options:
            if option in input_lower:
                return option

        # Handle ordinal selections ("first one", "second one", "1", "2")
        ordinal_map = {
            "first": 0, "1": 0, "one": 0,
            "second": 1, "2": 1, "two": 1,
            "third": 2, "3": 2, "three": 2,
            "fourth": 3, "4": 3, "four": 3,
        }
        for word, index in ordinal_map.items():
            if word in input_lower and index < len(options):
                return options[index]

        return None

    def handle_bagel_choice(
        self,
        user_input: str,
        item: ItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle bagel type selection for the CURRENT pending item only.

        This handles one item at a time. After configuring this item,
        configure_next_incomplete_bagel will move to the next item.
        """
        input_lower = user_input.lower().strip()

        # Check for pagination request ("what else", "more", etc.)
        if _is_pagination_request(user_input):
            pagination = order.get_menu_pagination()
            if pagination and pagination.get("category") == "bagel_types":
                offset = pagination.get("offset", 0)
                # Get next batch of bagel types
                batch = get_bagel_types_list()[offset:offset + DEFAULT_PAGINATION_SIZE]
                if batch:
                    new_offset = offset + DEFAULT_PAGINATION_SIZE
                    has_more = new_offset < len(get_bagel_types_list())
                    if has_more:
                        order.set_menu_pagination("bagel_types", new_offset, len(get_bagel_types_list()))
                        types_str = ", ".join(batch)
                        return StateMachineResult(
                            message=f"We also have {types_str}, and more.",
                            order=order,
                        )
                    else:
                        order.clear_menu_pagination()
                        types_str = ", ".join(batch)
                        return StateMachineResult(
                            message=f"We also have {types_str}. That's all our bagel types!",
                            order=order,
                        )
                else:
                    order.clear_menu_pagination()
                    return StateMachineResult(
                        message="That's all our bagel types. Which would you like?",
                        order=order,
                    )
            # No pagination state - show first batch
            else:
                batch = get_bagel_types_list()[:DEFAULT_PAGINATION_SIZE]
                types_str = ", ".join(batch)
                order.set_menu_pagination("bagel_types", DEFAULT_PAGINATION_SIZE, len(get_bagel_types_list()))
                return StateMachineResult(
                    message=f"We have {types_str}, and more.",
                    order=order,
                )

        # Try deterministic parsing first - check if input matches a known bagel type
        # Do this BEFORE redirect check so "do you have everything bagel" works
        bagel_type = None

        # Check for exact match or "[type] bagel" pattern
        for bt in get_bagel_types():
            if input_lower == bt or input_lower == f"{bt} bagel":
                bagel_type = bt
                break
            # Also check if type is contained in the input
            if bt in input_lower:
                bagel_type = bt
                break

        # Before redirect check, see if user is adding modifiers to the current item
        # e.g., "add american cheese" or "and cheese" should acknowledge and stay on track
        modifiers_for_acknowledgment = None
        if not bagel_type and isinstance(item, BagelItemTask):
            modifiers_for_acknowledgment = extract_modifiers_from_input(user_input)

        # If no bagel type found AND no modifiers detected, check if user is trying to order a new item
        has_modifiers = modifiers_for_acknowledgment and modifiers_for_acknowledgment.has_modifiers()
        if not bagel_type and not has_modifiers and self._check_redirect:
            redirect = self._check_redirect(
                user_input, item, order, "What kind of bagel would you like?"
            )
            if redirect:
                return redirect

        # Fall back to LLM parser only if deterministic parsing failed
        # BUT skip LLM if user is asking for options (e.g., "what kind do you have?")
        option_request_patterns = [
            "what do you have", "what kind do you have", "what kinds do you have",
            "what type do you have", "what types do you have", "what are my options",
            "what are the options", "what options", "what flavors",
        ]
        is_option_request = any(p in input_lower for p in option_request_patterns)

        if not bagel_type and not is_option_request:
            parsed = parse_bagel_choice(user_input, num_pending_bagels=1, model=self.model)
            if not parsed.unclear and parsed.bagel_type:
                bagel_type = parsed.bagel_type

        if not bagel_type:
            # Check if the user added modifiers - acknowledge them before re-asking
            acknowledgment = ""
            if has_modifiers:
                # Apply modifiers to the bagel
                apply_modifiers_to_bagel(item, modifiers_for_acknowledgment)
                if self.pricing:
                    self.pricing.recalculate_bagel_price(item)
                acknowledgment = _build_modifier_acknowledgment(modifiers_for_acknowledgment)
                if acknowledgment:
                    logger.info("Acknowledged modifiers during bagel type question")

            # Show first batch of bagel types and set up pagination
            batch = get_bagel_types_list()[:DEFAULT_PAGINATION_SIZE]
            types_str = ", ".join(batch)
            order.set_menu_pagination("bagel_types", DEFAULT_PAGINATION_SIZE, len(get_bagel_types_list()))
            return StateMachineResult(
                message=f"{acknowledgment}What kind of bagel? We have {types_str}, and more.",
                order=order,
            )

        logger.info("Parsed bagel type '%s' for item %s", bagel_type, type(item).__name__)

        # Extract any additional modifiers from the input (e.g., "plain with salt pepper and ketchup")
        extracted_modifiers = extract_modifiers_from_input(user_input)

        # IMPORTANT: Remove the bagel type from extracted modifiers to avoid ambiguity
        # e.g., "blueberry" is both a bagel type AND a cream cheese flavor
        # e.g., "onion" is both a bagel type AND a topping
        # If user said the bagel type, don't also add it as a spread/topping
        if bagel_type:
            input_lower = user_input.lower()

            # Filter spreads: only if user didn't explicitly say "cream cheese"
            if extracted_modifiers.spreads:
                user_explicitly_said_cream_cheese = "cream cheese" in input_lower

                if not user_explicitly_said_cream_cheese:
                    spreads_to_remove = []
                    for spread in extracted_modifiers.spreads:
                        spread_lower = spread.lower()
                        # Remove if spread matches bagel type or is "[bagel_type] cream cheese"
                        if spread_lower == bagel_type or spread_lower == f"{bagel_type} cream cheese":
                            spreads_to_remove.append(spread)
                            logger.info("Removing ambiguous spread '%s' (matches bagel type '%s')", spread, bagel_type)
                    for spread in spreads_to_remove:
                        extracted_modifiers.spreads.remove(spread)

            # Filter toppings: remove if topping matches the bagel type
            # e.g., "onion" bagel shouldn't also add "onion" as a topping
            if extracted_modifiers.toppings:
                toppings_to_remove = []
                for topping in extracted_modifiers.toppings:
                    topping_lower = topping.lower()
                    # Remove if topping matches bagel type (including plural forms)
                    if topping_lower == bagel_type or topping_lower == f"{bagel_type}s":
                        toppings_to_remove.append(topping)
                        logger.info("Removing ambiguous topping '%s' (matches bagel type '%s')", topping, bagel_type)
                for topping in toppings_to_remove:
                    extracted_modifiers.toppings.remove(topping)

        if extracted_modifiers.has_modifiers() or extracted_modifiers.has_special_instructions():
            logger.info("Extracted additional modifiers from bagel choice: %s", extracted_modifiers)

        # Apply to the current pending item
        if isinstance(item, MenuItemTask):
            item.bagel_choice = bagel_type

            # For omelettes with bagel side, use unified config flow for toasted/spread questions
            if item.side_choice == "bagel":
                order.clear_pending()
                return self.configure_next_incomplete_bagel(order)

            # For other menu items, mark complete
            item.mark_complete()
            order.clear_pending()
            return self._get_next_question(order)

        elif isinstance(item, BagelItemTask):
            item.bagel_type = bagel_type

            # Apply any additional modifiers from the input
            apply_modifiers_to_bagel(item, extracted_modifiers)

            if self.pricing:
                self.pricing.recalculate_bagel_price(item)

            # Clear pending and configure next incomplete item
            order.clear_pending()
            return self.configure_next_incomplete_bagel(order)

        return self._get_next_question(order)

    def handle_spread_choice(
        self,
        user_input: str,
        item: Union[BagelItemTask, MenuItemTask],
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle spread selection for bagel or omelette side bagel."""
        input_lower = user_input.lower().strip()

        # Check if user is asking for cream cheese options
        # e.g., "what kind of cream cheese do you have?", "what flavors?"
        cream_cheese_option_patterns = [
            "what kind", "what kinds", "what type", "what types",
            "what flavors", "what options", "what do you have",
            "what cream cheese", "which cream cheese",
        ]
        is_asking_for_options = any(p in input_lower for p in cream_cheese_option_patterns)

        if is_asking_for_options:
            # Show cream cheese options with pagination
            batch = _get_cream_cheese_types_list()[:DEFAULT_PAGINATION_SIZE]
            types_str = ", ".join(batch)
            has_more = len(_get_cream_cheese_types_list()) > DEFAULT_PAGINATION_SIZE
            if has_more:
                order.set_menu_pagination("cream_cheese_types", DEFAULT_PAGINATION_SIZE, len(_get_cream_cheese_types_list()))
                return StateMachineResult(
                    message=f"We have {types_str}, and more. Which would you like?",
                    order=order,
                )
            else:
                return StateMachineResult(
                    message=f"We have {types_str}. Which would you like?",
                    order=order,
                )

        # Check for pagination request for cream cheese types
        if _is_pagination_request(user_input):
            pagination = order.get_menu_pagination()
            if pagination and pagination.get("category") == "cream_cheese_types":
                offset = pagination.get("offset", 0)
                batch = _get_cream_cheese_types_list()[offset:offset + DEFAULT_PAGINATION_SIZE]
                if batch:
                    new_offset = offset + DEFAULT_PAGINATION_SIZE
                    has_more = new_offset < len(_get_cream_cheese_types_list())
                    if has_more:
                        order.set_menu_pagination("cream_cheese_types", new_offset, len(_get_cream_cheese_types_list()))
                        types_str = ", ".join(batch)
                        return StateMachineResult(
                            message=f"We also have {types_str}, and more.",
                            order=order,
                        )
                    else:
                        order.clear_menu_pagination()
                        types_str = ", ".join(batch)
                        return StateMachineResult(
                            message=f"We also have {types_str}. That's all our cream cheese flavors!",
                            order=order,
                        )
                else:
                    order.clear_menu_pagination()
                    return StateMachineResult(
                        message="That's all our cream cheese flavors. Which would you like?",
                        order=order,
                    )

        # Check if we're handling a disambiguation response
        if order.pending_spread_options:
            # User is responding to "We have honey walnut cream cheese or maple raisin walnut cream cheese"
            selected_spread_type = self._resolve_spread_disambiguation(
                user_input, order.pending_spread_options
            )
            if selected_spread_type:
                logger.info("Spread disambiguation resolved: '%s' -> '%s'", user_input, selected_spread_type)
                item.spread = "cream cheese"
                item.spread_type = selected_spread_type
                order.pending_spread_options = []  # Clear pending options

                # Recalculate price with spread
                if self.pricing:
                    self.pricing.recalculate_bagel_price(item)

                # Complete the bagel
                item.mark_complete()
                order.clear_pending()
                return self.configure_next_incomplete_bagel(order)
            else:
                # User's response didn't match any option - re-ask
                logger.info("Spread disambiguation failed: '%s' not in options", user_input)
                options_display = [f"{opt} cream cheese" for opt in order.pending_spread_options]
                if len(options_display) == 2:
                    options_str = f"{options_display[0]} or {options_display[1]}"
                else:
                    options_str = ", ".join(options_display[:-1]) + f", or {options_display[-1]}"
                return StateMachineResult(
                    message=f"Sorry, I didn't catch that. We have {options_str}. Which would you like?",
                    order=order,
                )

        # For MenuItemTask (omelette side bagels), use simpler handling
        if isinstance(item, MenuItemTask):
            # Try deterministic spread parsing first
            # Check for explicit no-spread responses
            # Note: "plain" should only mean "no spread" when NOT followed by "cream cheese" or "cc"
            # e.g., "plain" = no spread, but "plain cream cheese" = cream cheese spread
            no_spread_patterns = ["nothing", "no spread", "none", "no thanks", "nope", "nah"]
            is_plain_only = "plain" in input_lower and "cream cheese" not in input_lower and " cc" not in input_lower
            if any(p in input_lower for p in no_spread_patterns) or is_plain_only:
                item.spread = "none"
            else:
                det_spread, det_spread_type = _extract_spread(user_input)

                if det_spread or det_spread_type:
                    # Deterministic parsing found a spread
                    logger.info("Deterministic spread parsing (MenuItemTask): spread=%s, spread_type=%s", det_spread, det_spread_type)
                    spread = det_spread or "cream cheese"
                    spread_type = det_spread_type

                    # Build spread description (e.g., "scallion cream cheese")
                    if spread_type and spread_type != "plain":
                        item.spread = f"{spread_type} {spread}"
                    else:
                        item.spread = spread

                    # Add spread price to omelette (same as standalone bagel)
                    if self.pricing:
                        spread_price = self.pricing.lookup_spread_price(spread, spread_type)
                        if spread_price > 0 and item.unit_price is not None:
                            item.spread_price = spread_price  # Store for itemized display
                            item.unit_price += spread_price
                            logger.info(
                                "Added spread price to omelette: %s ($%.2f) -> new total $%.2f",
                                item.spread, spread_price, item.unit_price
                            )
                else:
                    # Fall back to LLM parser
                    parsed = parse_spread_choice(user_input, model=self.model)

                    if parsed.no_spread:
                        # Only trust no_spread if input looks like an explicit decline
                        decline_indicators = [
                            "no", "none", "nothing", "plain", "nah", "nope",
                            "skip", "pass", "without", "dry", "bare", "empty",
                            "just", "only", "that's it", "that's all", "i'm good",
                        ]
                        looks_like_decline = any(ind in input_lower for ind in decline_indicators)
                        if looks_like_decline:
                            item.spread = "none"
                        else:
                            # Unclear response - re-ask
                            logger.info("Unclear spread response (MenuItemTask): '%s' - re-asking", user_input)
                            return StateMachineResult(
                                message="Sorry, I didn't catch that. Would you like butter or cream cheese on the bagel?",
                                order=order,
                            )
                    elif parsed.spread:
                        # Validate LLM response - check if spread_type is actually valid
                        if parsed.spread_type and parsed.spread_type.lower() not in get_spread_types():
                            # LLM hallucinated an invalid spread type - re-ask
                            logger.info("LLM returned invalid spread_type '%s' (MenuItemTask) - re-asking", parsed.spread_type)
                            return StateMachineResult(
                                message="Sorry, I didn't catch that. Would you like butter or cream cheese on the bagel?",
                                order=order,
                            )
                        # Build spread description (e.g., "scallion cream cheese")
                        if parsed.spread_type and parsed.spread_type != "plain":
                            item.spread = f"{parsed.spread_type} {parsed.spread}"
                        else:
                            item.spread = parsed.spread

                        # Add spread price to omelette (same as standalone bagel)
                        if self.pricing:
                            spread_price = self.pricing.lookup_spread_price(parsed.spread, parsed.spread_type)
                            if spread_price > 0 and item.unit_price is not None:
                                item.spread_price = spread_price  # Store for itemized display
                                item.unit_price += spread_price
                                logger.info(
                                    "Added spread price to omelette: %s ($%.2f) -> new total $%.2f",
                                    item.spread, spread_price, item.unit_price
                                )
                    else:
                        return StateMachineResult(
                            message="Would you like butter or cream cheese on the bagel?",
                            order=order,
                        )

            # Omelette side bagel is complete
            item.mark_complete()
            order.clear_pending()
            return self.configure_next_incomplete_bagel(order)

        # For BagelItemTask - full handling with modifiers
        # First check if the user is requesting modifiers instead of a spread
        # e.g., "make it bacon egg and cheese" when asked about spread
        modifiers = extract_modifiers_from_input(user_input)

        # Filter out cream cheese variants from cheeses - these are spreads, not sliced cheeses
        # This prevents "Honey Walnut Cream Cheese" from being treated as a cheese (like American)
        # and added to extras when user is answering a spread question
        if modifiers.cheeses:
            modifiers.cheeses = [c for c in modifiers.cheeses if "cream cheese" not in c.lower()]

        has_modifiers = (
            modifiers.proteins or modifiers.cheeses or modifiers.toppings
        )

        if has_modifiers:
            # User wants modifiers instead of spread - apply them
            logger.info(f"Spread question answered with modifiers: {modifiers}")

            apply_modifiers_to_bagel(item, modifiers)

            # If no spread was specified with the modifiers, mark as none
            if not modifiers.spreads:
                item.spread = "none"
        else:
            # Try deterministic spread parsing first
            # This handles cases like "kalamata olive" -> "kalamata olive cream cheese"
            # Note: "plain" should only mean "no spread" when NOT followed by "cream cheese" or "cc"
            # e.g., "plain" = no spread, but "plain cream cheese" = cream cheese spread
            no_spread_patterns = ["nothing", "no spread", "none", "no thanks", "nope", "nah"]
            is_plain_only = "plain" in input_lower and "cream cheese" not in input_lower and " cc" not in input_lower
            if any(p in input_lower for p in no_spread_patterns) or is_plain_only:
                item.spread = "none"
            else:
                # Use disambiguation-aware spread extraction
                det_spread, det_spread_type, disambiguation_options = extract_spread_with_disambiguation(user_input)

                if disambiguation_options and len(disambiguation_options) > 1:
                    # Multiple potential matches - ask user to clarify
                    logger.info(
                        "Spread disambiguation needed: input='%s', options=%s",
                        user_input, disambiguation_options
                    )
                    # Store disambiguation options on the order for handling the response
                    order.pending_spread_options = disambiguation_options

                    # Build a friendly disambiguation message
                    options_display = [f"{opt} cream cheese" for opt in disambiguation_options]
                    if len(options_display) == 2:
                        options_str = f"{options_display[0]} or {options_display[1]}"
                    else:
                        options_str = ", ".join(options_display[:-1]) + f", or {options_display[-1]}"

                    return StateMachineResult(
                        message=f"We have {options_str}. Which would you like?",
                        order=order,
                    )

                if det_spread or det_spread_type:
                    # Deterministic parsing found a spread
                    logger.info("Deterministic spread parsing: spread=%s, spread_type=%s", det_spread, det_spread_type)
                    item.spread = det_spread or "cream cheese"
                    item.spread_type = det_spread_type
                else:
                    # Fall back to LLM parser
                    parsed = parse_spread_choice(user_input, model=self.model)

                    if parsed.no_spread:
                        # Only trust no_spread if input looks like an explicit decline
                        # This prevents gibberish like "yellow" being treated as "no spread"
                        decline_indicators = [
                            "no", "none", "nothing", "plain", "nah", "nope",
                            "skip", "pass", "without", "dry", "bare", "empty",
                            "just", "only", "that's it", "that's all", "i'm good",
                        ]
                        looks_like_decline = any(ind in input_lower for ind in decline_indicators)
                        if looks_like_decline:
                            item.spread = "none"  # Mark as explicitly no spread
                        else:
                            # Unclear response - re-ask
                            logger.info("Unclear spread response: '%s' - re-asking", user_input)
                            return StateMachineResult(
                                message="Sorry, I didn't catch that. Would you like cream cheese, butter, or nothing on that?",
                                order=order,
                            )
                    elif parsed.spread:
                        # Validate LLM response - check if spread_type is actually valid
                        # This prevents hallucinated types like "house cream cheese"
                        valid_spread_types = get_spread_types()
                        if parsed.spread_type and parsed.spread_type.lower() not in valid_spread_types:
                            # LLM hallucinated an invalid spread type - re-ask
                            logger.info("LLM returned invalid spread_type '%s' - re-asking", parsed.spread_type)
                            return StateMachineResult(
                                message="Sorry, I didn't catch that. Would you like cream cheese, butter, or nothing on that?",
                                order=order,
                            )
                        item.spread = parsed.spread
                        item.spread_type = parsed.spread_type
                        # Capture special instructions like "a little", "extra", etc.
                        if parsed.special_instructions:
                            # Build full spread description for special_instructions
                            spread_desc = parsed.spread
                            if parsed.spread_type and parsed.spread_type != "plain":
                                spread_desc = f"{parsed.spread_type} {parsed.spread}"
                            # Combine modifier with spread (e.g., "a little cream cheese")
                            item.special_instructions = f"{parsed.special_instructions} {spread_desc}"
                    else:
                        return StateMachineResult(
                            message="Would you like cream cheese, butter, or nothing on that?",
                            order=order,
                        )

        # Recalculate price to include spread modifier
        if self.pricing:
            self.pricing.recalculate_bagel_price(item)

        # This bagel is complete
        item.mark_complete()
        order.clear_pending()

        # Check for more incomplete bagels
        return self.configure_next_incomplete_bagel(order)

    def handle_toasted_choice(
        self,
        user_input: str,
        item: Union[BagelItemTask, MenuItemTask],
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle toasted preference for bagel or sandwich."""
        # Before redirect check, see if user is adding modifiers to the current item
        # e.g., "add blueberry cream cheese" should acknowledge and stay on track
        modifiers_for_acknowledgment = None
        if isinstance(item, BagelItemTask):
            modifiers_for_acknowledgment = extract_modifiers_from_input(user_input)

        # If no modifiers detected, check if user is trying to order a new item
        has_modifiers = modifiers_for_acknowledgment and modifiers_for_acknowledgment.has_modifiers()
        if not has_modifiers and self._check_redirect:
            redirect = self._check_redirect(
                user_input, item, order, "Would you like it toasted?"
            )
            if redirect:
                return redirect

        # Try deterministic parsing first, fall back to LLM
        toasted = parse_toasted_deterministic(user_input)
        if toasted is None:
            parsed = parse_toasted_choice(user_input, model=self.model)
            toasted = parsed.toasted

        if toasted is None:
            # Check if the user added modifiers - acknowledge them before re-asking
            acknowledgment = ""
            if has_modifiers:
                apply_modifiers_to_bagel(item, modifiers_for_acknowledgment)
                if self.pricing:
                    self.pricing.recalculate_bagel_price(item)
                acknowledgment = _build_modifier_acknowledgment(modifiers_for_acknowledgment)
                if acknowledgment:
                    logger.info("Acknowledged modifiers during toasted question")

            return StateMachineResult(
                message=f"{acknowledgment}Would you like that toasted? Yes or no?",
                order=order,
            )

        item.toasted = toasted

        # Extract any additional modifiers from the input (e.g., "yes with extra cheese")
        if isinstance(item, BagelItemTask):
            extracted_modifiers = extract_modifiers_from_input(user_input)
            if extracted_modifiers.has_modifiers() or extracted_modifiers.has_special_instructions():
                logger.info("Extracted additional modifiers from toasted choice: %s", extracted_modifiers)
                apply_modifiers_to_bagel(item, extracted_modifiers)

            # If a spread was detected, use disambiguation-aware extraction
            # to properly handle spread types like "walnut cream cheese"
            if extracted_modifiers.spreads:
                det_spread, det_spread_type, disambiguation_options = extract_spread_with_disambiguation(user_input)

                if disambiguation_options and len(disambiguation_options) > 1:
                    # Multiple potential matches - need to ask for clarification
                    logger.info(
                        "Spread disambiguation needed in toasted handler: input='%s', options=%s",
                        user_input, disambiguation_options
                    )
                    order.pending_spread_options = disambiguation_options
                    options_display = [f"{opt} cream cheese" for opt in disambiguation_options]
                    if len(options_display) == 2:
                        options_str = f"{options_display[0]} or {options_display[1]}"
                    else:
                        options_str = ", ".join(options_display[:-1]) + f", or {options_display[-1]}"

                    order.pending_field = "spread"
                    return StateMachineResult(
                        message=f"Got it, toasted. We have {options_str}. Which would you like?",
                        order=order,
                    )

                # Apply the spread type if detected
                if det_spread_type:
                    item.spread_type = det_spread_type
                    logger.info("Set spread_type from toasted handler: %s", det_spread_type)

        # For MenuItemTask, handle based on type
        if isinstance(item, MenuItemTask):
            # For omelette side bagels, continue to spread question
            if item.side_choice == "bagel":
                order.clear_pending()
                return self.configure_next_incomplete_bagel(order)
            # For spread/salad sandwiches, mark complete after toasted
            item.mark_complete()
            order.clear_pending()

            # Build summary for this completed item
            item_summary = item.menu_item_name
            if item.bagel_choice:
                item_summary += f" on {item.bagel_choice}"
            if item.toasted:
                item_summary += " toasted"

            # Check if we're in a multi-item flow (items queued for config)
            # If so, use the abbreviated question format from get_next_question
            if order.has_queued_config_items() and self._get_next_question:
                next_result = self._get_next_question(order)
                if next_result and next_result.message:
                    return StateMachineResult(
                        message=f"Got it, {item_summary}. {next_result.message}",
                        order=next_result.order,
                    )

            # Fall back to old behavior for non-multi-item flows
            next_config = self.configure_next_incomplete_bagel(order)
            if next_config and next_config.message and "toasted" in next_config.message.lower():
                # More items need config - include this item's name in the response
                return StateMachineResult(
                    message=f"Got it, {item_summary}. {next_config.message}",
                    order=next_config.order,
                )
            elif next_config and next_config.message:
                return next_config

            # No more config needed - return with this item's summary
            order.phase = OrderPhase.TAKING_ITEMS.value
            return StateMachineResult(
                message=f"Got it, {item_summary}. Anything else?",
                order=order,
            )

        # For BagelItemTask, check if spread is already set or has sandwich toppings
        if item.spread is not None:
            # Spread already specified, bagel is complete
            if self.pricing:
                self.pricing.recalculate_bagel_price(item)
            item.mark_complete()
            order.clear_pending()
            return self.configure_next_incomplete_bagel(order)

        # Skip spread question if bagel already has sandwich toppings (ham, egg, cheese, etc.)
        # But continue to cheese clarification if needed
        if item.extras or item.sandwich_protein:
            logger.info("Skipping spread question - bagel has toppings: extras=%s, protein=%s", item.extras, item.sandwich_protein)
            # If cheese clarification still needed, don't mark complete yet
            if not item.needs_cheese_clarification:
                if self.pricing:
                    self.pricing.recalculate_bagel_price(item)
                item.mark_complete()
            order.clear_pending()
            return self.configure_next_incomplete_bagel(order)

        # Move to spread question
        order.pending_field = "spread"
        return StateMachineResult(
            message="Would you like cream cheese or butter on that?",
            order=order,
        )

    def handle_cheese_choice(
        self,
        user_input: str,
        item: BagelItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle cheese type selection when user said generic 'cheese'."""
        # Before redirect check, see if user is adding modifiers to the current item
        modifiers_for_acknowledgment = extract_modifiers_from_input(user_input)

        # If no modifiers detected, check if user is trying to order a new item
        has_modifiers = modifiers_for_acknowledgment and modifiers_for_acknowledgment.has_modifiers()
        if not has_modifiers and self._check_redirect:
            redirect = self._check_redirect(
                user_input, item, order, "What kind of cheese would you like?"
            )
            if redirect:
                return redirect

        input_lower = user_input.lower().strip()

        # Try to extract cheese type from input
        cheese_types = {
            "american": ["american", "america"],
            "cheddar": ["cheddar", "ched"],
            "swiss": ["swiss"],
            "muenster": ["muenster", "munster"],
            "provolone": ["provolone", "prov"],
        }

        selected_cheese = None
        for cheese, patterns in cheese_types.items():
            for pattern in patterns:
                if pattern in input_lower:
                    selected_cheese = cheese
                    break
            if selected_cheese:
                break

        if not selected_cheese:
            # Check if the user added modifiers - acknowledge them before re-asking
            acknowledgment = ""
            if has_modifiers:
                # Apply non-cheese modifiers (skip cheeses since we're asking about cheese)
                apply_modifiers_to_bagel(item, modifiers_for_acknowledgment, skip_cheeses=True)
                if self.pricing:
                    self.pricing.recalculate_bagel_price(item)
                # Build acknowledgment for non-cheese modifiers only
                non_cheese_modifiers = ExtractedModifiers(
                    proteins=modifiers_for_acknowledgment.proteins,
                    cheeses=[],  # Skip cheese in acknowledgment since we're asking about it
                    toppings=modifiers_for_acknowledgment.toppings,
                    spreads=modifiers_for_acknowledgment.spreads,
                )
                acknowledgment = _build_modifier_acknowledgment(non_cheese_modifiers)
                if acknowledgment:
                    logger.info("Acknowledged modifiers during cheese question")

            return StateMachineResult(
                message=f"{acknowledgment}What kind of cheese? We have American, cheddar, Swiss, and muenster.",
                order=order,
            )

        # Remove generic "cheese" from extras (we're replacing it with the specific type)
        if "cheese" in item.extras:
            item.extras.remove("cheese")

        # Add the specific cheese type to extras
        item.extras.append(selected_cheese)
        item.needs_cheese_clarification = False

        # Extract any additional modifiers from the input (e.g., "cheddar with extra bacon")
        extracted_modifiers = extract_modifiers_from_input(user_input)
        if extracted_modifiers.has_modifiers() or extracted_modifiers.has_special_instructions():
            logger.info("Extracted additional modifiers from cheese choice: %s", extracted_modifiers)
            # Apply modifiers (skip cheeses since we already handled cheese above)
            apply_modifiers_to_bagel(item, extracted_modifiers, skip_cheeses=True)

        # Recalculate price with the new cheese
        if self.pricing:
            self.pricing.recalculate_bagel_price(item)

        logger.info("Cheese choice '%s' applied to bagel", selected_cheese)

        # Clear pending and continue configuration
        order.clear_pending()
        return self.configure_next_incomplete_bagel(order)

    def get_bagel_descriptions(self, order: OrderTask, bagel_ids: list[str]) -> list[str]:
        """Get descriptions for a list of bagel IDs (e.g., ['plain bagel', 'everything bagel'])."""
        descriptions = []
        for bagel_id in bagel_ids:
            bagel = self._get_item_by_id(order, bagel_id) if self._get_item_by_id else None
            if bagel and isinstance(bagel, BagelItemTask):
                if bagel.bagel_type:
                    descriptions.append(f"{bagel.bagel_type} bagel")
                else:
                    descriptions.append("bagel")
        return descriptions

    def configure_next_incomplete_bagel(
        self,
        order: OrderTask,
    ) -> StateMachineResult:
        """
        Find the next incomplete bagel item and configure it fully before moving on.

        This handles:
        - BagelItemTask (bagels with spreads/toppings)
        - MenuItemTask for omelettes with side_choice == "bagel"

        Each item is fully configured (type -> toasted -> spread) before
        moving to the next item.
        """
        # Collect all items that need bagel configuration (both types)
        all_bagel_items = []
        for item in order.items.items:
            if isinstance(item, BagelItemTask):
                all_bagel_items.append(item)
            elif isinstance(item, MenuItemTask) and item.side_choice == "bagel":
                # Omelettes with bagel side need bagel configuration
                all_bagel_items.append(item)

        total_items = len(all_bagel_items)

        # Find the first incomplete item and ask about its next missing field
        for idx, item in enumerate(all_bagel_items):
            if item.status != TaskStatus.IN_PROGRESS:
                continue

            item_num = idx + 1

            # Build ordinal descriptor if multiple items
            if total_items > 1:
                ordinal = MessageBuilder.get_ordinal(item_num)
                bagel_desc = f"the {ordinal} bagel"
                your_bagel_desc = f"your {ordinal} bagel"
            else:
                bagel_desc = "your bagel"
                your_bagel_desc = "your bagel"

            # Handle MenuItemTask (omelette with bagel side)
            if isinstance(item, MenuItemTask):
                is_omelette_side = item.side_choice == "bagel"

                # Ask about bagel type first
                if not item.bagel_choice:
                    order.phase = OrderPhase.CONFIGURING_ITEM
                    order.pending_item_id = item.id
                    order.pending_field = "bagel_choice"
                    if total_items > 1:
                        return StateMachineResult(
                            message=f"For {bagel_desc}, what kind of bagel would you like that on?",
                            order=order,
                        )
                    else:
                        return StateMachineResult(
                            message="What kind of bagel would you like that on?",
                            order=order,
                        )

                # Then ask about toasted (with bagel type confirmation)
                if item.toasted is None:
                    order.phase = OrderPhase.CONFIGURING_ITEM
                    order.pending_item_id = item.id
                    order.pending_field = "toasted"
                    bagel_type_desc = f"{item.bagel_choice} bagel" if item.bagel_choice else "bagel"
                    if is_omelette_side:
                        return StateMachineResult(
                            message=f"Ok, {bagel_type_desc}. Would you like that toasted?",
                            order=order,
                        )
                    elif total_items > 1:
                        return StateMachineResult(
                            message=f"Ok, {bagel_type_desc}. For {bagel_desc}, would you like that toasted?",
                            order=order,
                        )
                    else:
                        return StateMachineResult(
                            message=f"Ok, {bagel_type_desc}. Would you like that toasted?",
                            order=order,
                        )

                # For omelette side bagels, ask about spread (butter/cream cheese)
                if is_omelette_side and item.spread is None:
                    order.phase = OrderPhase.CONFIGURING_ITEM
                    order.pending_item_id = item.id
                    order.pending_field = "spread"
                    return StateMachineResult(
                        message="Would you like butter or cream cheese on the bagel?",
                        order=order,
                    )

                # If spread is set but price hasn't been calculated yet (from one-shot answer),
                # calculate and add the spread price now
                if is_omelette_side and item.spread and item.spread != "none" and not item.spread_price:
                    if self.pricing and item.unit_price is not None:
                        spread_price = self.pricing.lookup_spread_price(item.spread)
                        if spread_price > 0:
                            item.spread_price = spread_price
                            item.unit_price += spread_price
                            logger.info(
                                "Added spread price (one-shot): %s ($%.2f) -> new total $%.2f",
                                item.spread, spread_price, item.unit_price
                            )

                # MenuItemTask is complete
                item.mark_complete()
                continue

            # Handle BagelItemTask
            bagel = item

            # Ask about type first (if configured to ask in conversation)
            if not bagel.bagel_type and self._should_ask_bagel_field("bagel_type"):
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = bagel.id
                order.pending_field = "bagel_choice"
                # Get question from database, with fallback
                base_question = self._get_bagel_question(
                    "bagel_type",
                    "What kind of bagel would you like?"
                )
                if total_items > 1:
                    return StateMachineResult(
                        message=f"For {bagel_desc}, {base_question.lower()}",
                        order=order,
                    )
                else:
                    return StateMachineResult(
                        message=base_question,
                        order=order,
                    )

            # Then ask about toasted (if configured to ask in conversation)
            if bagel.toasted is None and self._should_ask_bagel_field("toasted"):
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = bagel.id
                order.pending_field = "toasted"
                bagel_type_desc = f"{bagel.bagel_type} bagel" if bagel.bagel_type else "bagel"
                # Get question from database, with fallback
                base_question = self._get_bagel_question(
                    "toasted",
                    "Would you like it toasted?"
                )
                if total_items > 1:
                    return StateMachineResult(
                        message=f"Ok, {bagel_type_desc}. For {bagel_desc}, {base_question.lower()}",
                        order=order,
                    )
                else:
                    return StateMachineResult(
                        message=f"Ok, {bagel_type_desc}. {base_question}",
                        order=order,
                    )

            # Then ask about cheese type if user said generic "cheese"
            if bagel.needs_cheese_clarification:
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = bagel.id
                order.pending_field = "cheese_choice"
                if total_items > 1:
                    return StateMachineResult(
                        message=f"For {bagel_desc}, what kind of cheese would you like? We have American, cheddar, Swiss, and muenster.",
                        order=order,
                    )
                else:
                    return StateMachineResult(
                        message="What kind of cheese would you like? We have American, cheddar, Swiss, and muenster.",
                        order=order,
                    )

            # Then ask about spread (skip if bagel already has toppings)
            # Business rule: skip spread if bagel has extras or protein (still in code)
            if (bagel.spread is None and not bagel.extras and not bagel.sandwich_protein
                    and self._should_ask_bagel_field("spread")):
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = bagel.id
                order.pending_field = "spread"
                # Get question from database, with fallback
                base_question = self._get_bagel_question(
                    "spread",
                    "Any spread on that?"
                )
                if total_items > 1:
                    return StateMachineResult(
                        message=f"For {bagel_desc}, {base_question.lower()}",
                        order=order,
                    )
                else:
                    return StateMachineResult(
                        message=base_question,
                        order=order,
                    )

            # This bagel is complete, mark it and continue to next
            bagel.mark_complete()

        # No incomplete bagels - generate confirmation message for the bagels
        # Get all completed bagels to summarize
        completed_bagels = [item for item in order.items.items
                          if isinstance(item, BagelItemTask) and item.status == TaskStatus.COMPLETE]

        if completed_bagels:
            # Get the most recently completed bagel(s) summary
            last_bagel = completed_bagels[-1]
            bagel_summary = last_bagel.get_summary()

            # Count identical bagels at the end
            count = 0
            for bagel in reversed(completed_bagels):
                if bagel.get_summary() == bagel_summary:
                    count += 1
                else:
                    break

            if count > 1:
                summary = f"{count} {bagel_summary}s" if not bagel_summary.endswith("s") else f"{count} {bagel_summary}"
            else:
                summary = bagel_summary

            order.clear_pending()

            # Check if there are items queued for configuration (e.g., coffee after bagel)
            # Loop until we find an incomplete item or queue is empty (defensive safeguard)
            while order.has_queued_config_items():
                next_config = order.pop_next_config_item()
                if not next_config:
                    break

                item_id = next_config.get("item_id")
                item_type = next_config.get("item_type")
                logger.info("Bagel complete, processing queued config item: id=%s, type=%s", item_id[:8] if item_id else None, item_type)

                # Handle coffee disambiguation (when "coffee" matched multiple items like Coffee, Latte, etc.)
                if item_type == "coffee_disambiguation" and order.pending_drink_options:
                    logger.info("Bagel complete, asking coffee disambiguation question")
                    order.pending_field = "drink_selection"
                    order.phase = OrderPhase.CONFIGURING_ITEM.value
                    # Build the clarification message
                    option_list = []
                    for i, option_item in enumerate(order.pending_drink_options, 1):
                        name = option_item.get("name", "Unknown")
                        price = option_item.get("base_price", 0)
                        if price > 0:
                            option_list.append(f"{i}. {name} (${price:.2f})")
                        else:
                            option_list.append(f"{i}. {name}")
                    options_str = "\n".join(option_list)
                    return StateMachineResult(
                        message=f"Got it, {summary}. Now for your coffee - we have a few options:\n{options_str}\nWhich would you like?",
                        order=order,
                    )

                # Find the item by ID and check if it still needs configuration
                target_item = None
                for item in order.items.items:
                    if item.id == item_id:
                        target_item = item
                        break

                if target_item:
                    # Defensive check: skip if item is already complete
                    if target_item.status == TaskStatus.COMPLETE:
                        logger.info("Skipping already-complete item in queue: id=%s, type=%s", item_id[:8] if item_id else None, item_type)
                        continue  # Pop next item from queue

                    # Handle coffee items
                    if item_type == "coffee" and isinstance(target_item, CoffeeItemTask):
                        if self._configure_coffee:
                            return self._configure_coffee(order)

                    # Handle bagel items (shouldn't normally be in queue due to grouping fix, but defensive)
                    if item_type == "bagel" and isinstance(target_item, BagelItemTask):
                        return self.configure_next_incomplete_bagel(order)

                # If we get here, item wasn't handled - log and continue to next
                logger.warning("Queued config item not handled: id=%s, type=%s", item_id[:8] if item_id else None, item_type)

            # Before returning "Anything else?", check for incomplete items (e.g., coffee added via disambiguation)
            if self._get_next_question:
                next_result = self._get_next_question(order)
                # If an item was found that needs configuration (pending_field is set), return with bagel summary
                if order.pending_field:
                    return StateMachineResult(
                        message=f"Got it, {summary}. {next_result.message}",
                        order=order,
                    )

            # Explicitly set to TAKING_ITEMS - we're asking for more items
            order.phase = OrderPhase.TAKING_ITEMS.value
            return StateMachineResult(
                message=f"Got it, {summary}. Anything else?",
                order=order,
            )

        # Fallback to generic next question
        return self._get_next_question(order)
