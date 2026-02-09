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
from .parsers.deterministic import ExtractionPipeline
from .item_cancellation_handler import ItemCancellationHandler
from .item_replacement_handler import ItemReplacementHandler
from .item_modification_handler import ItemModificationHandler
from .unrecognized_item_handler import UnrecognizedItemHandler
from .modifier_change_handler import ModifierChangeHandler
from .mixins import MenuDataMixin
from .utils.text import format_english_list

# Import new sub-handlers
from .order_detection import (
    looks_like_order_attempt,
    extract_order_item_name,
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

logger = logging.getLogger(__name__)

# Module-level pipeline instance for reuse
_pipeline = ExtractionPipeline()


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
        self._dietary_inquiry_handler = DietaryInquiryHandler(config=config)
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

        if parsed.is_greeting or parsed.unclear:
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
        # Check for early patterns (before LLM parsing) - delegates to EarlyPatternHandler
        result = self._early_pattern_handler.handle_all_early_patterns(user_input, order)
        if result:
            return result

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
        if instructions_result:
            new_instructions = "; ".join(instructions_result.instructions)
            if order.special_instructions:
                order.special_instructions += f"; {new_instructions}"
            else:
                order.special_instructions = new_instructions
            logger.info("Order-level special instructions: %s", order.special_instructions)

        return self.handle_taking_items_with_parsed(parsed, order, extracted_selections, user_input)

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
        result = self._inquiry_router.route_category_clarification(parsed, order)
        if result:
            return result

        # Route all inquiry types through InquiryRouter
        result = self._inquiry_router.route_inquiry(parsed, order, raw_user_input)
        if result:
            return result

        # Handle standalone ingredient (e.g., "I want caramel syrup") - suggest items
        result = self._handle_standalone_ingredient(parsed, order)
        if result:
            return result

        if parsed.unclear or parsed.is_greeting:
            # Check if user is trying to order something we don't recognize
            # e.g., "I want home fries", "can I have a croissant", or just "pepsi"
            if parsed.unclear and raw_user_input and self._unrecognized_handler:
                text_stripped = raw_user_input.strip()
                is_order_attempt = looks_like_order_attempt(raw_user_input)
                is_known_unrecognized = self._is_known_unrecognized_item(text_stripped)

                if is_order_attempt or is_known_unrecognized:
                    # For order attempts with phrases, extract item name; for bare items, use text directly
                    item_name = extract_order_item_name(raw_user_input) if is_order_attempt else text_stripped
                    if item_name:
                        logger.info("Detected order attempt for unrecognized item: '%s'", item_name)
                        message, category_for_followup = self._unrecognized_handler.get_not_found_response(
                            item_name, order=order
                        )
                        if category_for_followup:
                            # Track state so "yes" response can list items in this category
                            order.pending_field = PendingField.CATEGORY_INQUIRY
                            order.pending_config_queue = [category_for_followup]
                        return StateMachineResult(
                            message=message,
                            order=order,
                        )

            return StateMachineResult(
                message="What can I get for you?",
                order=order,
            )

        return StateMachineResult(
            message="I didn't catch that. What would you like to order?",
            order=order,
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

    # =========================================================================
    # Extracted Handler Methods (delegate to sub-handlers)
    # =========================================================================

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
                order.pending_ingredient_search = {
                    "ingredient": ingredient,
                    "matches": matches,
                    "offset": display_count,
                }

        return StateMachineResult(
            message=msg,
            order=order,
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
        order.pending_ingredient_suggestion = {
            "ingredient": ingredient,
            "suggested_items": sample_items,
        }
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
        user_lower = user_input.lower().strip()

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
        ingredient = suggestion.get("ingredient", "") if suggestion else ""
        suggested_items = suggestion.get("suggested_items", []) if suggestion else []

        # Clear suggestion context
        order.pending_ingredient_suggestion = None
        order.pending_field = None

        # Check if user explicitly declined
        user_lower = user_input.lower().strip()
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
        dietary_type = followup.get("dietary_type", "") if followup else ""
        category = followup.get("category") if followup else None

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
