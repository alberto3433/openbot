"""
Taking Items Handler for Order State Machine.

This module handles the taking items phase of the order flow including
greeting, processing new item orders, and multi-item order coordination.

This is a facade module that coordinates several specialized sub-handlers:
- ModifierInputHandler: Modifier detection and application
- ParsedItemProcessor: ParsedItemEntry processing
- InquiryRouter: Inquiry routing logic
- DuplicateHandler: Duplicate/repeat item handling
- SuggestedItemHandler: Suggested item/ingredient/dietary confirmation flows
- IngredientSearchHandler: Ingredient search and category extraction

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

# Import sub-handlers
from .modifier_input_handler import ModifierInputHandler
from .parsed_item_processor import ParsedItemProcessor
from .inquiry_router import InquiryRouter
from .duplicate_handler import DuplicateHandler
from .early_pattern_handler import EarlyPatternHandler
from .dietary_inquiry_handler import DietaryInquiryHandler
from .suggested_item_handler import SuggestedItemHandler
from .ingredient_search_handler import IngredientSearchHandler

if TYPE_CHECKING:
    from .handler_config import HandlerConfig
    from .context import OrderContext

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
    - SuggestedItemHandler: For suggested item/ingredient/dietary confirmations
    - IngredientSearchHandler: For ingredient search and category extraction

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

        # Sub-handlers extracted in Workstream D
        self._suggested_item_handler = SuggestedItemHandler(parent=self)
        self._ingredient_search_handler = IngredientSearchHandler(parent=self)

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

    # =========================================================================
    # Ingredient Search Delegation (delegates to IngredientSearchHandler)
    # =========================================================================

    def _handle_category_inquiry_response(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle category inquiry response - delegates to IngredientSearchHandler."""
        return self._ingredient_search_handler.handle_category_inquiry_response(user_input, order)

    def _handle_ingredient_search(
        self,
        parsed: "OpenInputResponse",
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle ingredient-based menu search - delegates to IngredientSearchHandler."""
        return self._ingredient_search_handler.handle_ingredient_search(parsed, order)

    def _try_extract_category_from_input(
        self,
        raw_input: str | None,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Try to extract category from input - delegates to IngredientSearchHandler."""
        return self._ingredient_search_handler.try_extract_category_from_input(raw_input, order)

    def _handle_unrecognized_order_attempt(
        self,
        parsed: "OpenInputResponse",
        order: OrderTask,
        raw_user_input: str | None,
    ) -> StateMachineResult | None:
        """Handle unrecognized order attempt - delegates to IngredientSearchHandler."""
        return self._ingredient_search_handler.handle_unrecognized_order_attempt(parsed, order, raw_user_input)

    def _is_known_unrecognized_item(self, text: str) -> bool:
        """Check if text matches a known unrecognized item - delegates to IngredientSearchHandler."""
        return self._ingredient_search_handler._is_known_unrecognized_item(text)

    # =========================================================================
    # Suggested Item Confirmation (delegates to SuggestedItemHandler)
    # =========================================================================

    def handle_confirm_suggested_item(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle suggested item confirmation - delegates to SuggestedItemHandler."""
        return self._suggested_item_handler.handle_confirm_suggested_item(user_input, order)

    def handle_confirm_ingredient_suggestion(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle ingredient suggestion confirmation - delegates to SuggestedItemHandler."""
        return self._suggested_item_handler.handle_confirm_ingredient_suggestion(user_input, order)

    def handle_confirm_dietary_followup(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle dietary followup confirmation - delegates to SuggestedItemHandler."""
        return self._suggested_item_handler.handle_confirm_dietary_followup(user_input, order)

    def _handle_standalone_ingredient(
        self,
        parsed: "OpenInputResponse",
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle standalone ingredient order - delegates to SuggestedItemHandler."""
        return self._suggested_item_handler.handle_standalone_ingredient(parsed, order)

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
