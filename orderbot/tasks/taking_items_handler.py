"""
Taking Items Handler for Order State Machine.

This module handles the taking items phase of the order flow including
greeting, processing new item orders, and multi-item order coordination.

This is a facade module that coordinates several specialized sub-handlers:
- ModifierInputHandler: Modifier detection and application
- ParsedItemProcessor: ParsedItemEntry processing
- InquiryRouter: Inquiry routing logic
- DuplicateHandler: Duplicate/repeat item handling

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import re
from typing import Callable, TYPE_CHECKING

from orderbot.cache import menu_cache

from .models import OrderTask
from .pending_fields import PendingField
from .schemas import (
    StateMachineResult,
    Selection,
    ParsedItem,
    ParsedItemEntry,
)
from .parsers import parse_open_input
from .parsers.deterministic import get_pipeline
from .item_cancellation_handler import ItemCancellationHandler
from .item_replacement_handler import ItemReplacementHandler
from .item_modification_handler import ItemModificationHandler
from .unrecognized_item_handler import UnrecognizedItemHandler
from .modifier_change_handler import ModifierChangeHandler
from .mixins import MenuDataMixin
from .models.pending_states import PendingDietaryFollowup, PendingIngredientSearch, PendingIngredientSuggestion
from .utils.text import format_english_list, normalize_text

# Import new sub-handlers
from .order_detection import (
    looks_like_order_attempt,
    extract_order_item_name,
    looks_like_availability_question,
    extract_availability_item_name,
)
from .modifier_input_handler import ModifierInputHandler
from .parsed_item_processor import ParsedItemProcessor
from .inquiry_router import InquiryRouter
from .duplicate_handler import DuplicateHandler
from .early_pattern_handler import EarlyPatternHandler
from .response_utils import is_affirmative
from .dietary_inquiry_handler import DietaryInquiryHandler

if TYPE_CHECKING:
    from .handler_config import HandlerConfig
    from .context import OrderContext

# Pattern for ordering-intent phrases that implicitly confirm a suggested item.
# Matches "I'll take one", "let me get that", "give me one", etc.
_IMPLICIT_ACCEPT_PATTERN = re.compile(
    r"(?:i'll|i\s+will)\s+(?:take|have|try|get|order)\s+(?:one|that|it|some)"
    r"|(?:let\s+me|can\s+i|could\s+i)\s+(?:get|have|try)\s+(?:one|that|it|some)"
    r"|(?:give|get)\s+me\s+(?:one|that|it|some)",
    re.IGNORECASE,
)


def _is_implicit_accept(text: str) -> bool:
    """Check if text contains ordering-intent phrases that implicitly accept a suggestion."""
    return bool(_IMPLICIT_ACCEPT_PATTERN.search(text))

logger = logging.getLogger(__name__)

# Pattern to strip a leading negative word + optional punctuation from user input
# e.g., "no nothing else" -> "nothing else", "nah, I'm good" -> "I'm good"
_LEADING_NEGATIVE_RE = re.compile(
    r"^(?:no|nah|nope|naw)[,.\s]+",
    re.IGNORECASE,
)


def _is_negative_done(text: str) -> bool:
    """Check if user input is a negative response meaning 'done ordering'.

    Handles direct done signals ("that's it"), negative responses ("no", "nope"),
    and combinations like "no nothing else", "nah I'm good", "no that's it".

    Args:
        text: Raw user input.

    Returns:
        True if the input means the user is done ordering.
    """
    if menu_cache.is_done(text) or menu_cache.is_negative(text):
        return True

    # Strip leading negative word and check if the remainder is a done signal
    # e.g., "no nothing else" -> "nothing else" (matches done pattern)
    remainder = _LEADING_NEGATIVE_RE.sub("", text.strip())
    if remainder and remainder != text.strip() and menu_cache.is_done(remainder):
        return True

    return False

# Get shared pipeline instance
_pipeline = get_pipeline()


class TakingItemsHandler(MenuDataMixin):
    """
    Handles the taking items phase of order flow.

    This is a facade that coordinates several specialized sub-handlers:
    - ModifierInputHandler: For "add vanilla" type requests
    - ParsedItemProcessor: For adding parsed items to orders
    - InquiryRouter: For menu/store info inquiries
    - DuplicateHandler: For "another one" / "same thing" requests

    Manages greeting, processing new item orders, and
    multi-item order coordination.
    """

    # Type annotations for instance variables
    model: str
    pricing: "PricingEngine | None"
    _menu_data: dict
    item_adder_handler: "ItemAdderHandler | None"
    menu_inquiry_handler: "MenuInquiryHandler | None"
    store_info_handler: "StoreInfoHandler | None"
    checkout_utils_handler: "CheckoutUtilsHandler | None"
    checkout_handler: "CheckoutHandler | None"
    _returning_customer: dict | None
    _set_repeat_info_callback: Callable[[bool, str | None], None] | None

    def __init__(
        self,
        config: "HandlerConfig",
        item_adder_handler: "ItemAdderHandler | None" = None,
        menu_inquiry_handler: "MenuInquiryHandler | None" = None,
        store_info_handler: "StoreInfoHandler | None" = None,
        checkout_utils_handler: "CheckoutUtilsHandler | None" = None,
        checkout_handler: "CheckoutHandler | None" = None,
        configure_next_incomplete_item: Callable[["OrderTask"], "StateMachineResult"] | None = None,
    ) -> None:
        """
        Initialize the taking items handler.

        Args:
            config: HandlerConfig with shared dependencies.
            item_adder_handler: Handler for adding items.
            menu_inquiry_handler: Handler for menu inquiries.
            store_info_handler: Handler for store info inquiries.
            checkout_utils_handler: Handler for checkout utilities.
            checkout_handler: Handler for checkout flow including confirmation/repeat orders.
            configure_next_incomplete_item: Callback to get config question for incomplete items.
        """
        self.model = config.model
        self.pricing = config.pricing
        self._menu_data = config.menu_data or {}

        # Handler-specific dependencies
        self.item_adder_handler = item_adder_handler
        self.menu_inquiry_handler = menu_inquiry_handler
        self.store_info_handler = store_info_handler
        self.checkout_utils_handler = checkout_utils_handler
        self.checkout_handler = checkout_handler

        # Extracted sub-handlers (existing)
        self.item_cancellation_handler = ItemCancellationHandler(
            pricing=config.pricing,
            configure_next_incomplete_item=configure_next_incomplete_item,
        )
        self.item_replacement_handler = ItemReplacementHandler(pricing=config.pricing)
        self.item_modification_handler = ItemModificationHandler(
            pricing=config.pricing,
            item_adder_handler=item_adder_handler,
        )

        # Unrecognized item handler - reuse from item_adder_handler which has db_session
        self._unrecognized_handler: UnrecognizedItemHandler | None = None
        if item_adder_handler and hasattr(item_adder_handler, '_unrecognized_handler'):
            self._unrecognized_handler = item_adder_handler._unrecognized_handler

        # New sub-handlers (extracted from this file)
        self._modifier_input_handler = ModifierInputHandler(pricing=config.pricing)
        self._parsed_item_processor = ParsedItemProcessor(
            item_adder_handler=item_adder_handler,
            pricing=config.pricing,
        )
        self._dietary_inquiry_handler = DietaryInquiryHandler(
            config=config,
            unrecognized_handler=self._unrecognized_handler,
        )
        self._inquiry_router = InquiryRouter(
            menu_inquiry_handler=menu_inquiry_handler,
            store_info_handler=store_info_handler,
            dietary_inquiry_handler=self._dietary_inquiry_handler,
        )
        self._duplicate_handler = DuplicateHandler(
            pricing=config.pricing,
            checkout_handler=checkout_handler,
        )
        self._modifier_change_handler = ModifierChangeHandler(config=config)
        self._early_pattern_handler = EarlyPatternHandler(
            pricing=config.pricing,
            modifier_change_handler=self._modifier_change_handler,
        )

        # Context set per-request
        self._returning_customer: dict | None = None
        self._set_repeat_info_callback: Callable[[bool, str | None], None] | None = None

    # Note: _modifier_category_keywords and _modifier_item_keywords are
    # inherited from MenuDataMixin via BaseHandler

    @property
    def _ingredient_to_items(self) -> dict[str, list[dict]]:
        """Get ingredient-to-items mapping for ingredient-based menu search."""
        return self._menu_data.get("ingredient_to_items", {})

    def set_context(
        self,
        ctx: "OrderContext | None" = None,
        # Legacy kwargs for backward compatibility
        returning_customer: dict | None = None,
        set_repeat_info_callback: Callable[[bool, str | None], None] | None = None,
    ) -> None:
        """Set per-request context from unified OrderContext."""
        if ctx is not None:
            self._returning_customer = ctx.returning_customer
            self._set_repeat_info_callback = ctx.set_repeat_info_callback
        else:
            self._returning_customer = returning_customer
            self._set_repeat_info_callback = set_repeat_info_callback

        # Propagate context to sub-handlers that need it
        self._duplicate_handler.set_context(
            returning_customer=self._returning_customer,
            set_repeat_info_callback=self._set_repeat_info_callback,
        )

    def handle_greeting(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle greeting phase."""
        parsed = parse_open_input(
            user_input,
            model=self.model,
            modifier_category_keywords=self._modifier_category_keywords,
            modifier_item_keywords=self._modifier_item_keywords,
            ingredient_to_items=self._ingredient_to_items,
        )

        logger.info(
            "Greeting phase parsed: is_greeting=%s, unclear=%s, parsed_items=%d",
            parsed.is_greeting,
            parsed.unclear,
            len(parsed.parsed_items),
        )

        if parsed.is_small_talk:
            from .parsers.constants import get_order_redirect
            response = parsed.small_talk_response or "Thanks for chatting!"
            redirect = get_order_redirect(has_items=False)
            return StateMachineResult(
                message=f"{response} {redirect}",
                order=order,
            )

        if parsed.is_greeting or parsed.unclear:
            # Check if user selected a delivery method (e.g., from greeting quick reply)
            from .parsers.validators import parse_delivery_choice_deterministic
            delivery_choice = parse_delivery_choice_deterministic(user_input)
            if delivery_choice.choice in ("pickup", "delivery"):
                order.delivery_method.order_type = delivery_choice.choice
                return StateMachineResult(
                    message="What can I get for you?",
                    order=order,
                )
            # Phase will be derived as TAKING_ITEMS by orchestrator on next turn
            return StateMachineResult(
                message="Hi! Welcome to Zucker's. What can I get for you today?",
                order=order,
            )

        # User might have ordered something directly - pass the already parsed result
        # Selections are already extracted in the parsed items during parsing
        extracted_selections: list[Selection] | None = None
        if parsed.parsed_items and parsed.parsed_items[0].selections:
            extracted_selections = list(parsed.parsed_items[0].selections)
            if extracted_selections:
                logger.info("Selections from greeting input: %s", extracted_selections)

        # Phase is derived from orchestrator, no need to set explicitly
        return self.handle_taking_items_with_parsed(parsed, order, extracted_selections, user_input)

    def handle_taking_items(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle taking new item orders."""
        # Check for category inquiry follow-up (e.g., "yes" to "Would you like to hear more?")
        result = self._handle_category_inquiry_response(user_input, order)
        if result:
            return result

        # Check for early patterns (before LLM parsing) - delegates to EarlyPatternHandler
        result = self._early_pattern_handler.handle_all_early_patterns(user_input, order)
        if result:
            return result

        # Check for standalone cancel/abandon phrases: "I changed my mind", "never mind",
        # "forget it", "cancel", etc. During TAKING_ITEMS these clear the entire order.
        result = self._check_cancel_order(user_input, order)
        if result:
            return result

        # When items are in the cart and user gives a negative response
        # to "Anything else?", treat it as done ordering.
        # Handles: "no", "nope", "no nothing else", "nah I'm good", etc.
        if order.items.get_active_items() and _is_negative_done(user_input):
            return self.checkout_utils_handler.transition_to_checkout(order)

        parsed = parse_open_input(
            user_input,
            model=self.model,
            modifier_category_keywords=self._modifier_category_keywords,
            modifier_item_keywords=self._modifier_item_keywords,
            ingredient_to_items=self._ingredient_to_items,
        )

        # Selections are already extracted in the parsed items during parsing
        extracted_selections: list[Selection] | None = None
        if parsed.parsed_items and parsed.parsed_items[0].selections:
            extracted_selections = list(parsed.parsed_items[0].selections)
            if extracted_selections:
                logger.info("Selections from input: %s", extracted_selections)

        # Extract order-level special instructions from user input
        instructions_result = _pipeline.extract_special_instructions(user_input)
        if instructions_result and instructions_result.instructions:
            # Filter out instructions already captured as item-level selections
            # (e.g., "cheese on the side" when blueberry_cream_cheese is a selection)
            filtered_instructions = self._filter_order_level_instructions(
                instructions_result.instructions, parsed,
            )
            if filtered_instructions:
                new_instructions = "; ".join(filtered_instructions)
                if order.special_instructions:
                    order.special_instructions += f"; {new_instructions}"
                else:
                    order.special_instructions = new_instructions
                logger.info("Order-level special instructions: %s", order.special_instructions)

        return self.handle_taking_items_with_parsed(parsed, order, extracted_selections, user_input)

    @staticmethod
    def _filter_order_level_instructions(
        instructions: list[str],
        parsed: "OpenInputResponse",
    ) -> list[str]:
        """Filter order-level instructions already captured as item-level selections.

        Removes instructions like "cheese on the side" when a parsed item already has
        a selection covering that modifier (e.g., blueberry_cream_cheese with an
        "on the side" qualifier in its display_name).

        Args:
            instructions: Raw special instructions extracted from user input
            parsed: The parsed open input response containing parsed items

        Returns:
            Filtered list with redundant instructions removed.
        """
        if not parsed.parsed_items:
            return instructions

        # Collect all selection slugs from all parsed items
        all_slugs: set[str] = set()
        for item in parsed.parsed_items:
            for sel in item.selections:
                all_slugs.add(sel.slug.lower())

        # Strip position qualifiers from instructions to get the base word,
        # then check if it matches any selection slug (exact or suffix)
        qualifier_patterns = menu_cache.get_qualifier_patterns()
        position_patterns = []
        for pattern in qualifier_patterns:
            info = menu_cache.get_qualifier_info(pattern)
            if info and info.get("category") == "position":
                position_patterns.append(pattern)

        # Collect amount qualifier patterns (non-position) for prefix stripping
        amount_patterns = []
        for pattern in qualifier_patterns:
            info = menu_cache.get_qualifier_info(pattern)
            if info and info.get("category") != "position":
                amount_patterns.append(pattern)

        filtered = []
        for instr in instructions:
            instr_lower = instr.lower()
            # Strip position qualifier suffix to get the base item word
            base_word = instr_lower
            for pattern in position_patterns:
                suffix = f" {pattern}"
                if base_word.endswith(suffix):
                    base_word = base_word[:-len(suffix)].strip()
                    break

            # Strip amount qualifier prefixes (data-driven)
            for pattern in amount_patterns:
                prefix = f"{pattern} "
                if base_word.startswith(prefix):
                    base_word = base_word[len(prefix):].strip()
                    break

            # Check if base_word matches any slug exactly or as a suffix component
            if base_word in all_slugs or any(s.endswith(f"_{base_word}") for s in all_slugs):
                logger.debug(
                    "Filtering order-level instruction '%s' - covered by item selection",
                    instr,
                )
                continue
            filtered.append(instr)
        return filtered

    def handle_taking_items_with_parsed(
        self,
        parsed: "OpenInputResponse",
        order: OrderTask,
        extracted_selections: list[Selection] | None = None,
        raw_user_input: str | None = None,
    ) -> StateMachineResult:
        """Handle taking new item orders with already-parsed input."""
        logger.info(
            "Parsed open input: parsed_items=%d, done_ordering=%s",
            len(parsed.parsed_items),
            parsed.done_ordering,
        )

        # Reset menu pagination on any non-"more items" request
        if not parsed.wants_more_menu_items:
            order.clear_menu_pagination()
            order.pending_ingredient_search = None

        if parsed.done_ordering:
            return self.checkout_utils_handler.transition_to_checkout(order)

        # Handle cart item reference duplication ("more chips", "another bag of chips")
        # This must run BEFORE wants_more_menu_items to catch cart references first
        result = self._duplicate_handler.handle_duplicate_by_reference(parsed, order)
        if result:
            return result

        # Handle ingredient-based menu search
        result = self._handle_ingredient_search(parsed, order)
        if result:
            return result

        # Fallback: handle single_select attribute modifications not caught by EarlyPatternHandler
        result = self._handle_single_select_attribute_fallback(raw_user_input, order)
        if result:
            return result

        # Handle modification to an existing item in the cart
        result = self._handle_modify_existing_item(parsed, order, raw_user_input)
        if result:
            return result

        # Handle item replacement: "make it a coke instead", "change it to X", etc.
        result, replaced_item_name = self._handle_item_replacement(parsed, order, raw_user_input)
        if result:
            return result

        # Handle item/modifier cancellation: "cancel the coke", "remove bacon", etc.
        result = self._handle_item_cancellation(parsed, order)
        if result:
            return result

        # Handle "another bagel" / "one more coffee" - treat as new item of that type
        if parsed.duplicate_new_item_type:
            item_type = parsed.duplicate_new_item_type
            logger.info("Adding new %s (from 'another %s' pattern)", item_type, item_type)

            # Use data-driven lookup from ItemType aliases
            category_info = menu_cache.get_category_keyword_mapping(item_type)
            mapped_type = category_info.get("slug") if category_info else None

            if mapped_type:
                # Use unified add_item() dispatcher (routes based on attributes)
                return self.item_adder_handler.add_item(
                    item_type=mapped_type,
                    order=order,
                    quantity=1,
                )
            else:
                # Generic drink or unknown type - ask what they'd like
                return StateMachineResult(
                    message=f"Sure, what kind of {item_type} would you like?",
                    order=order,
                )

        # Handle "make it 2" / "another one" / "one more" - delegate to DuplicateHandler
        result = self._duplicate_handler.handle_duplicate_request(parsed, order)
        if result:
            return result

        # Handle "all items" duplicate request - delegate to DuplicateHandler
        result = self._duplicate_handler.handle_wants_duplicate_all(parsed, order)
        if result:
            return result

        # Handle repeat order / "same thing" request - delegate to DuplicateHandler
        result = self._duplicate_handler.handle_repeat_order_request(
            parsed, order, raw_user_input=raw_user_input
        )
        if result:
            return result

        # Check if user specified order type upfront (e.g., "I'd like to place a pickup order")
        if parsed.order_type:
            order.delivery_method.order_type = parsed.order_type
            logger.info("Order type set from upfront mention: %s", parsed.order_type)
            order_type_display = "pickup" if parsed.order_type == "pickup" else "delivery"
            # Check if they also ordered items in the same message
            has_items = bool(parsed.parsed_items)
            if not has_items:
                # Just the order type, no items yet - acknowledge and ask what they want
                return StateMachineResult(
                    message=f"Great, I'll set this up for {order_type_display}. What can I get for you?",
                    order=order,
                )
            # If they also ordered items, continue processing below

        # Process all items via parsed_items list - delegate to ParsedItemProcessor
        if parsed.parsed_items:
            result = self._process_items(parsed, order)
            if result:
                return result

        # Handle category clarification
        category_result = self._inquiry_router.route_category_clarification(parsed, order)
        if isinstance(category_result, str):
            # Single item in category - add directly to cart
            return self.item_adder_handler.add_menu_item(category_result, 1, order)
        if category_result:
            return category_result

        # Route all inquiry types through InquiryRouter
        result = self._inquiry_router.route_inquiry(parsed, order, raw_user_input)
        if result:
            return result

        # Handle standalone ingredient (e.g., "I want caramel syrup") - suggest items
        result = self._handle_standalone_ingredient(parsed, order)
        if result:
            return result

        if parsed.unclear or parsed.is_greeting:
            result = self._handle_unrecognized_order_attempt(parsed, order, raw_user_input)
            if result:
                return result

            # Try to extract a category reference from desire/mood phrases
            # e.g., "I am in the mood for a sandwich" -> "sandwich" -> show sandwich items
            result = self._try_extract_category_from_input(raw_user_input, order)
            if result:
                return result

            return StateMachineResult(
                message="What can I get for you?",
                order=order,
            )

        return StateMachineResult(
            message="I didn't catch that. What would you like to order?",
            order=order,
        )

    def _handle_unrecognized_order_attempt(
        self,
        parsed: "OpenInputResponse",
        order: OrderTask,
        raw_user_input: str | None,
    ) -> StateMachineResult | None:
        """Check if user is trying to order something we don't recognize.

        Handles inputs like "I want home fries", "can I have a croissant",
        or bare item names like "pepsi".

        Returns:
            StateMachineResult if an unrecognized item was detected, None otherwise.
        """
        if not parsed.unclear or not raw_user_input or not self._unrecognized_handler:
            return None

        text_stripped = raw_user_input.strip()
        is_order_attempt = looks_like_order_attempt(raw_user_input)
        is_known_unrecognized = self._is_known_unrecognized_item(text_stripped)
        is_availability = looks_like_availability_question(raw_user_input)

        if not (is_order_attempt or is_known_unrecognized or is_availability):
            return None

        # Extract item name based on detected pattern type
        if is_order_attempt:
            item_name = extract_order_item_name(raw_user_input)
        elif is_availability:
            item_name = extract_availability_item_name(raw_user_input)
        else:
            item_name = text_stripped
        if not item_name:
            return None

        logger.info("Detected order attempt for unrecognized item: '%s'", item_name)
        message, category_for_followup, qr = self._unrecognized_handler.get_not_found_response(
            item_name, order=order
        )
        if category_for_followup:
            # Track state so "yes" response can list items in this category
            order.pending_field = PendingField.CATEGORY_INQUIRY
            order.pending_config_queue = [category_for_followup]
        return StateMachineResult(
            message=message,
            order=order,
            quick_replies=qr or None,
        )

    def _is_known_unrecognized_item(self, text: str) -> bool:
        """Check if text matches a known unrecognized item pattern.

        This allows bare item names like "pepsi" to trigger the unrecognized
        item handler even without ordering language like "I want".

        Args:
            text: User input text (should be stripped)

        Returns:
            True if the text matches a curated unrecognized item suggestion.
        """
        if not self._unrecognized_handler or not self._unrecognized_handler._db_session:
            return False
        curated = self._unrecognized_handler._check_curated_suggestions(text.lower().strip())
        return curated is not None

    # Pattern to strip desire/mood phrases that wrap a category reference
    # e.g., "I am in the mood for a sandwich" -> "sandwich"
    _DESIRE_MOOD_PATTERN = re.compile(
        r"^(?:i(?:'?m| am)\s+(?:in the mood for|craving|feeling like)|"
        r"how about|what about)\s+",
        re.IGNORECASE,
    )

    def _try_extract_category_from_input(
        self,
        raw_input: str | None,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Try to extract a category reference from desire/mood phrases.

        Handles inputs like "I am in the mood for a sandwich" by stripping
        desire/mood prefixes, ordering prefixes, and articles, then checking
        if the remainder is a category reference.

        Args:
            raw_input: The raw user input string.
            order: The current order task.

        Returns:
            StateMachineResult if a category was found and routed, None otherwise.
        """
        if not raw_input or not self.menu_inquiry_handler:
            return None

        from .normalization import strip_ordering_prefix

        text = raw_input.strip()

        # Strip desire/mood phrases first
        text = self._DESIRE_MOOD_PATTERN.sub("", text).strip()

        # Also apply existing ordering prefix stripping ("I want", "can I get", etc.)
        text = strip_ordering_prefix(text)

        # Strip articles and trailing punctuation/please
        text = re.sub(r"^(?:a|an|some|the)\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*(?:please|thanks?)[.!?]*\s*$", "", text, flags=re.IGNORECASE)
        text = text.strip().rstrip("?.!")

        if not text:
            return None

        category_slug = menu_cache.is_category_reference(text)
        if not category_slug:
            return None

        logger.info(
            "Extracted category '%s' from desire/mood phrase: '%s'",
            category_slug, raw_input,
        )
        result = self.menu_inquiry_handler.handle_category_clarification(category_slug, order)
        # handle_category_clarification returns str when a single item matched
        if isinstance(result, str):
            return self.item_adder_handler.add_menu_item(result, 1, order)
        return result

    # =========================================================================
    # Extracted Handler Methods (delegate to sub-handlers)
    # =========================================================================

    def _check_cancel_order(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Check for standalone cancel phrases that abandon the entire order.

        Matches "I changed my mind", "never mind", "forget it", "cancel", etc.
        Only clears the cart when there are active items; otherwise ignored
        so the input can be handled by downstream parsers.
        """
        from .config_cancellation_handler import CANCEL_ORDER_PATTERN, START_OVER_PATTERN
        from .handler_utils import remove_item_from_order
        from .schemas import OrderPhase

        stripped = user_input.strip()
        is_cancel = CANCEL_ORDER_PATTERN.match(stripped)
        is_start_over = not is_cancel and START_OVER_PATTERN.match(stripped)

        if not is_cancel and not is_start_over:
            return None

        active_items = order.items.get_active_items()
        if not active_items:
            return None

        num_items = len(active_items)
        for item in active_items:
            remove_item_from_order(order, item)
        order.clear_pending()
        order.set_phase(OrderPhase.TAKING_ITEMS)

        if is_start_over:
            logger.info("Start over during TAKING_ITEMS: cleared %d items", num_items)
            return StateMachineResult(
                message="OK, let's start over. What would you like to order?",
                order=order,
            )
        logger.info("Cancel order during TAKING_ITEMS: cleared %d items", num_items)
        return StateMachineResult(
            message="OK, I've cleared your order. What would you like to order?",
            order=order,
        )

    def _handle_item_cancellation(
        self,
        parsed: "OpenInputResponse",
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle item/modifier cancellation - delegates to ItemCancellationHandler."""
        return self.item_cancellation_handler.handle_item_cancellation(parsed, order)

    def _handle_item_replacement(
        self,
        parsed: "OpenInputResponse",
        order: OrderTask,
        raw_user_input: str | None,
    ) -> tuple[StateMachineResult | None, str | None]:
        """Handle item replacement - delegates to ItemReplacementHandler."""
        return self.item_replacement_handler.handle_item_replacement(parsed, order, raw_user_input)

    def _handle_modify_existing_item(
        self,
        parsed: "OpenInputResponse",
        order: OrderTask,
        raw_user_input: str | None,
    ) -> StateMachineResult | None:
        """Handle modification to existing item - delegates to ItemModificationHandler."""
        return self.item_modification_handler.handle_modify_existing_item(parsed, order, raw_user_input)

    def _handle_single_select_attribute_fallback(
        self,
        raw_user_input: str | None,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Fallback for single_select attribute modifications not caught by EarlyPatternHandler."""
        return self._modifier_input_handler.handle_single_select_attribute_fallback(raw_user_input, order)

    def _handle_category_inquiry_response(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle affirmative response to category inquiry (e.g., 'Would you like to hear more?').

        When pending_field is CATEGORY_INQUIRY and user says 'yes', show more items
        from the display group pagination or list items from the pending category.

        Returns:
            StateMachineResult if handled, None otherwise.
        """
        logger.info(
            "CATEGORY_INQUIRY_RESPONSE: pending_field=%s, user_input='%s'",
            order.pending_field, user_input
        )

        if order.pending_field != PendingField.CATEGORY_INQUIRY:
            return None

        logger.info("CATEGORY_INQUIRY_RESPONSE: Matched CATEGORY_INQUIRY pending field")

        if not is_affirmative(user_input):
            # Not an affirmative response - clear pending state and continue ordering
            logger.info("CATEGORY_INQUIRY_RESPONSE: Not affirmative, clearing state")
            order.pending_field = None
            order.pending_config_queue = []
            order.menu_query_pagination = None
            return StateMachineResult(
                message="Sure! What can I get for you?",
                order=order,
            )

        logger.info("CATEGORY_INQUIRY_RESPONSE: Affirmative response detected")

        # Clear the pending field since we're handling this now
        order.pending_field = None

        # Check if there's display group pagination to continue
        pagination = order.get_menu_pagination()
        logger.info("CATEGORY_INQUIRY_RESPONSE: pagination=%s", pagination)

        if pagination and pagination.get("type") == "display_group_items":
            # Use menu_inquiry_handler to show more items
            logger.info("CATEGORY_INQUIRY_RESPONSE: Calling handle_more_menu_items")
            if self.menu_inquiry_handler:
                try:
                    return self.menu_inquiry_handler.handle_more_menu_items(order)
                except (ValueError, KeyError, TypeError, AttributeError) as e:
                    logger.error("CATEGORY_INQUIRY_RESPONSE: handle_more_menu_items failed: %s", e, exc_info=True)

        # Check if there's a pending category to list items from
        pending_category = None
        if order.pending_config_queue:
            pending_category = order.pending_config_queue[0]
            order.pending_config_queue = []
            logger.info("CATEGORY_INQUIRY_RESPONSE: pending_category=%s", pending_category)

        if pending_category and isinstance(pending_category, str):
            # List items from this category
            logger.info("CATEGORY_INQUIRY_RESPONSE: Calling handle_menu_query for %s", pending_category)
            if self.menu_inquiry_handler:
                try:
                    return self.menu_inquiry_handler.handle_menu_query(pending_category, order)
                except (ValueError, KeyError, TypeError, AttributeError) as e:
                    logger.error("CATEGORY_INQUIRY_RESPONSE: handle_menu_query failed: %s", e, exc_info=True)

        # Fallback: no pagination or category found
        logger.info("CATEGORY_INQUIRY_RESPONSE: Fallback - no pagination or category")
        return StateMachineResult(
            message="What would you like to order?",
            order=order,
        )

    def _handle_ingredient_search(
        self,
        parsed: "OpenInputResponse",
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle ingredient-based menu search.

        When user says "chicken" or "something with bacon", show matching items.

        Returns:
            StateMachineResult if handled, None otherwise.
        """
        if not parsed.ingredient_search_matches:
            return None

        ingredient = parsed.ingredient_search_query or "that ingredient"
        matches = parsed.ingredient_search_matches
        logger.info(
            "INGREDIENT SEARCH: showing %d items with '%s'",
            len(matches), ingredient
        )

        # Build a nice response showing the matching items
        if len(matches) == 1:
            item = matches[0]
            item_name = item.get("name", "that item")
            desc = item.get("description", "")
            msg = f"For {ingredient}, we have the {item_name}"
            if desc:
                msg += f" ({desc})"
            msg += ". Would you like one?"

            # Store context so "yes" / "give me one" adds this item
            order.pending_suggested_item = item_name
            order.pending_field = PendingField.CONFIRM_SUGGESTED_ITEM
        else:
            # Multiple items - list them (cap at 6 for initial display)
            display_count = min(6, len(matches))
            item_names = [m.get("name", "item") for m in matches[:display_count]]
            has_more = len(matches) > display_count

            # Format the list properly
            if len(item_names) == 1:
                items_list = item_names[0]
            elif len(item_names) == 2:
                items_list = f"{item_names[0]} or {item_names[1]}"
            elif has_more:
                # "Item1, Item2, ..., Item6, and X more" (no "or" before "and")
                items_list = ", ".join(item_names)
                items_list += f", and {len(matches) - display_count} more"
            else:
                # "Item1, Item2, Item3, Item4, Item5, or Item6"
                items_list = format_english_list(item_names, conjunction="or")

            msg = f"For items with {ingredient}, we have: {items_list}. Which would you like?"

            # Store pagination state for "what else" follow-up
            if has_more:
                order.pending_ingredient_search = PendingIngredientSearch(
                    ingredient=ingredient,
                    matches=matches,
                    offset=display_count,
                )

        # Build quick replies for inline clickable text
        if len(matches) == 1:
            qr = [{"label": item_name, "value": item_name}]
        else:
            qr = [{"label": name, "value": name} for name in item_names]
            if has_more:
                qr.append({"label": f"{len(matches) - display_count} more", "value": "what else?"})
        return StateMachineResult(
            message=msg,
            order=order,
            quick_replies=qr,
        )

    def _handle_standalone_ingredient(
        self,
        parsed: "OpenInputResponse",
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle standalone ingredient order (e.g., "I want caramel syrup").

        When user orders just an ingredient/modifier without specifying an item,
        suggest items that can have this modifier.

        Returns:
            StateMachineResult if handled, None otherwise.
        """
        if not parsed.found_ingredient_without_item or not parsed.found_ingredient_name:
            return None

        ingredient = parsed.found_ingredient_name
        logger.info(
            "STANDALONE INGREDIENT: suggesting items for '%s'",
            ingredient
        )

        # Get item types that can have this ingredient as a modifier
        item_types = menu_cache.get_item_types_for_ingredient(ingredient)
        if not item_types:
            return None

        # Get sample menu items for those item types
        sample_items = []
        seen_names = set()
        for item_type_info in item_types[:3]:  # Limit to 3 item types
            item_type_slug = item_type_info.get("slug")
            if not item_type_slug:
                continue

            items = menu_cache.get_items_by_item_type(item_type_slug)
            for item in items[:2]:  # Get up to 2 items per type
                item_name = item.get("name")
                if item_name and item_name not in seen_names:
                    seen_names.add(item_name)
                    sample_items.append(item_name)
                    if len(sample_items) >= 4:  # Cap at 4 total items
                        break
            if len(sample_items) >= 4:
                break

        if not sample_items:
            return None

        # Format the suggestion message
        items_list = format_english_list(sample_items, conjunction="or")
        msg = f"We could make you a {items_list} with {ingredient}. Would you like one of those?"

        # Store context for follow-up confirmation
        order.pending_ingredient_suggestion = PendingIngredientSuggestion(
            ingredient=ingredient,
            suggested_items=sample_items,
        )
        order.pending_field = PendingField.CONFIRM_INGREDIENT_SUGGESTION

        return StateMachineResult(
            message=msg,
            order=order,
        )

    # =========================================================================
    # ParsedItem Processing (delegates to ParsedItemProcessor)
    # =========================================================================

    def _add_parsed_item_entry(
        self, item: ParsedItemEntry, order: OrderTask
    ) -> tuple[OrderTask, str, StateMachineResult | None]:
        """Handle ParsedItemEntry - delegates to ParsedItemProcessor."""
        return self._parsed_item_processor.add_parsed_item_entry(item, order)

    def _add_parsed_item(
        self, item: ParsedItem, order: OrderTask
    ) -> tuple[OrderTask, str, StateMachineResult | None]:
        """Dispatch a parsed item - delegates to ParsedItemProcessor."""
        return self._parsed_item_processor.add_parsed_item(item, order)

    def _process_items(
        self,
        parsed: "OpenInputResponse",
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Process all items from parsed_items list - delegates to ParsedItemProcessor."""
        return self._parsed_item_processor.process_items(parsed, order)

    # =========================================================================
    # Duplicate/Repeat Handling (delegates to DuplicateHandler)
    # =========================================================================

    def handle_duplicate_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user's response to duplicate clarification - delegates to DuplicateHandler."""
        return self._duplicate_handler.handle_duplicate_selection(user_input, order)

    def handle_same_thing_clarification(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user's response to 'same thing' clarification - delegates to DuplicateHandler."""
        return self._duplicate_handler.handle_same_thing_clarification(user_input, order)

    def _duplicate_all_items(
        self,
        order: OrderTask,
        active_items: list,
    ) -> StateMachineResult:
        """Duplicate all items in the cart - delegates to DuplicateHandler."""
        return self._duplicate_handler._duplicate_all_items(order, active_items)

    # =========================================================================
    # Quantity Addition Selection (delegates to EarlyPatternHandler)
    # =========================================================================

    def handle_quantity_addition_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user's response to 'Which item would you like to add N more of?'

        Called when user said 'add 3' with multiple item types in cart.
        Delegates to EarlyPatternHandler.handle_quantity_addition_disambiguation.
        """
        return self._early_pattern_handler.handle_quantity_addition_disambiguation(
            user_input, order
        )

    # =========================================================================
    # Suggested Item Confirmation
    # =========================================================================

    def handle_confirm_suggested_item(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user's response to 'Would you like to order one?' after item description.

        Called when user asked about an item (e.g., 'what's in the Lexington?'),
        bot described it and asked 'Would you like to order one?'.
        """
        suggested_item = order.pending_suggested_item
        user_lower = normalize_text(user_input)

        # Clear context first (will be processed either way)
        order.pending_suggested_item = None
        order.pending_field = None

        if is_affirmative(user_input) and suggested_item:
            logger.info(
                "User confirmed suggested item '%s' with response: '%s'",
                suggested_item, user_input
            )
            # Use existing add_menu_item to add the suggested item
            return self.item_adder_handler.add_menu_item(
                suggested_item,
                quantity=1,
                order=order,
            )

        # Check for ordering-intent phrases that implicitly accept the suggestion
        # e.g., "I'll take one", "I'll try that", "sounds good, I'll have one"
        if suggested_item and _is_implicit_accept(user_lower):
            logger.info(
                "User implicitly confirmed suggested item '%s' with ordering intent: '%s'",
                suggested_item, user_input
            )
            return self.item_adder_handler.add_menu_item(
                suggested_item,
                quantity=1,
                order=order,
            )

        # Not affirmative - process as normal taking_items input
        # User might be ordering something else or saying no
        logger.info(
            "User did not confirm suggested item '%s', processing as normal input: '%s'",
            suggested_item, user_input
        )
        return self.handle_taking_items(user_input, order)

    def handle_confirm_ingredient_suggestion(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user's response to ingredient suggestion.

        Called when user ordered just a modifier (e.g., 'I want caramel syrup'),
        bot suggested items that can have it, and now user responds.

        Handles three cases:
        1. User says "yes" → ask which item they want
        2. User directly picks an item (e.g., "iced latte") → add item with ingredient
        3. User says "no" or something unrelated → process without ingredient
        """
        suggestion = order.pending_ingredient_suggestion
        ingredient = suggestion.ingredient if suggestion else ""
        suggested_items = suggestion.suggested_items if suggestion else []

        # Clear suggestion context
        order.pending_ingredient_suggestion = None
        order.pending_field = None

        # Check if user explicitly declined
        user_lower = normalize_text(user_input)
        is_negative = user_lower in ("no", "nope", "nah", "no thanks", "never mind", "nevermind")

        if is_negative:
            logger.info(
                "User declined ingredient suggestion for '%s', processing without ingredient: '%s'",
                ingredient, user_input
            )
            return self.handle_taking_items(user_input, order)

        if is_affirmative(user_input) and suggested_items:
            logger.info(
                "User confirmed ingredient suggestion for '%s', asking which item",
                ingredient
            )
            # Store the ingredient to apply when user picks an item
            order.pending_ingredient_to_apply = ingredient
            # Ask which item they'd like
            items_list = format_english_list(suggested_items, conjunction="or")
            return StateMachineResult(
                message=f"Great! Which would you like - {items_list}?",
                order=order,
            )

        # User might be directly picking an item (e.g., "iced latte" instead of "yes")
        # Set the ingredient to apply and process the input as a normal order
        logger.info(
            "User responded to ingredient suggestion for '%s' with '%s', applying ingredient to next item",
            ingredient, user_input
        )
        order.pending_ingredient_to_apply = ingredient
        return self.handle_taking_items(user_input, order)

    def handle_confirm_dietary_followup(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user's response to dietary follow-up offer.

        Called when user asked about a specific item's dietary property (e.g., 'is the classic vegan?'),
        got a negative answer, and was offered to see dietary options instead.

        Handles two cases:
        1. User says "yes" → show the dietary options
        2. User says "no" or something else → process as normal taking_items input
        """
        followup = order.pending_dietary_followup
        dietary_type = followup.dietary_type if followup else ""
        category = followup.category if followup else None

        # Clear follow-up context
        order.pending_dietary_followup = None
        order.pending_field = None

        if is_affirmative(user_input) and dietary_type:
            logger.info(
                "User confirmed dietary follow-up for '%s', showing options",
                dietary_type
            )
            # Call the dietary handler to show the options
            return self._dietary_inquiry_handler.handle_dietary_options_inquiry(
                dietary_type, order, category=category
            )

        # Not affirmative - process as normal taking_items input
        logger.info(
            "User did not confirm dietary follow-up for '%s', processing as normal input: '%s'",
            dietary_type, user_input
        )
        return self.handle_taking_items(user_input, order)
