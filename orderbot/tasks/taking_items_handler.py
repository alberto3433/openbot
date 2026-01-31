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

from .models import (
    OrderTask,
    MenuItemTask,
)
from .pending_fields import PendingField
from .schemas import (
    StateMachineResult,
    Selection,
    ParsedItem,
    ParsedItemEntry,
)
from .parsers import parse_open_input, extract_special_instructions_from_input
from .item_cancellation_handler import ItemCancellationHandler
from .item_replacement_handler import ItemReplacementHandler
from .item_modification_handler import ItemModificationHandler
from .unrecognized_item_handler import UnrecognizedItemHandler
from .parsers.constants import ADD_MODIFIER_PATTERNS
from .parsers.quantity_utils import parse_make_it_n_quantity
from .mixins import MenuDataMixin
from .utils.text import format_english_list
from .handler_utils import (
    is_configurable_menu_item,
    get_last_item,
    recalculate_and_summarize,
)

# Import new sub-handlers
from .order_detection import (
    looks_like_order_attempt,
    extract_order_item_name,
)
from .modifier_input_handler import (
    ModifierInputHandler,
    get_all_modifier_patterns_for_item,
    add_modifiers_from_input,
)
from .parsed_item_processor import ParsedItemProcessor
from .inquiry_router import InquiryRouter
from .duplicate_handler import DuplicateHandler
from .response_utils import is_affirmative

if TYPE_CHECKING:
    from .handler_config import HandlerConfig
    from .context import OrderContext

logger = logging.getLogger(__name__)


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
        self.item_cancellation_handler = ItemCancellationHandler(pricing=config.pricing)
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
        self._inquiry_router = InquiryRouter(
            menu_inquiry_handler=menu_inquiry_handler,
            store_info_handler=store_info_handler,
        )
        self._duplicate_handler = DuplicateHandler(
            pricing=config.pricing,
            checkout_handler=checkout_handler,
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
        if parsed.parsed_items and parsed.parsed_items[0].modifiers:
            extracted_selections = list(parsed.parsed_items[0].modifiers)
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
        # Check for "make it 2" pattern early (before LLM parsing)
        from .parsers.deterministic import MAKE_IT_N_PATTERN
        make_it_n_match = MAKE_IT_N_PATTERN.match(user_input.strip())
        if make_it_n_match:
            num_str = None
            for i in range(1, 8):
                if make_it_n_match.group(i):
                    num_str = make_it_n_match.group(i).lower()
                    break
            if num_str:
                target_qty = parse_make_it_n_quantity(num_str)
                if target_qty:
                    active_items = order.items.get_active_items()
                    if active_items:
                        last_item = get_last_item(active_items)
                        last_item_name = last_item.get_summary()
                        added_count = target_qty - 1

                        for _ in range(added_count):
                            order.items.add_item(last_item.duplicate())

                        logger.info("TAKING_ITEMS: Added %d more of '%s'", added_count, last_item_name)

                        if added_count == 1:
                            return StateMachineResult(
                                message=f"I've added a second {last_item_name}. Anything else?",
                                order=order,
                            )
                        else:
                            return StateMachineResult(
                                message=f"I've added {added_count} more {last_item_name}. Anything else?",
                                order=order,
                            )

        # Check for "add [modifier]" patterns early (before LLM parsing)
        # This allows "add vanilla syrup" to be handled without LLM
        input_lower = user_input.lower().strip()
        active_items = order.items.get_active_items()

        is_add_modifier_request = any(
            re.search(pattern, input_lower) for pattern in ADD_MODIFIER_PATTERNS
        )

        # Check if this is a pure modifier input for the last item (data-driven)
        # Get modifier patterns based on the last item's type
        is_pure_modifier_input = False
        has_item_modifier = False
        item_modifier_patterns: set[str] = set()

        if active_items:
            last_item = get_last_item(active_items)
            if is_configurable_menu_item(last_item):
                # Get modifier patterns for this specific item type (data-driven)
                item_modifier_patterns = get_all_modifier_patterns_for_item(last_item.menu_item_type)
                has_item_modifier = any(mod in input_lower for mod in item_modifier_patterns)

        logger.info("EARLY_MOD_DETECT: has_item_modifier=%s, active_items=%d", has_item_modifier, len(active_items))

        if has_item_modifier and active_items:
            last_item = get_last_item(active_items)
            # Check if item accepts input modifiers (data-driven)
            accepts_modifiers = (
                isinstance(last_item, MenuItemTask) and
                last_item.menu_item_type and
                menu_cache.item_accepts_input_modifiers(last_item.menu_item_type)
            )
            logger.info("EARLY_MOD_DETECT: accepts_modifiers=%s", accepts_modifiers)
            if accepts_modifiers:
                # Check if input is ONLY a modifier (no other item keywords)
                # Use item keywords from database (menu item names + item type slugs)
                # Exclude modifier patterns from the check since "vanilla" is both
                # a modifier pattern AND might be an item keyword (e.g., "Vanilla Latte")
                item_keywords = menu_cache.get_item_keywords()
                # Filter out words that are also modifiers for this item type
                non_modifier_keywords = {kw for kw in item_keywords if kw not in item_modifier_patterns}
                has_other_item = any(kw in input_lower for kw in non_modifier_keywords)
                logger.info("EARLY_MOD_DETECT: has_other_item=%s", has_other_item)
                if not has_other_item:
                    is_pure_modifier_input = True
                    logger.info("EARLY_MOD_DETECT: Setting is_pure_modifier_input=True")

        # If it's an "add modifier" pattern OR pure modifier input, modify the last item
        if (is_add_modifier_request or is_pure_modifier_input) and has_item_modifier and active_items:
            last_item = get_last_item(active_items)
            # Check if item accepts input modifiers (data-driven)
            accepts_modifiers = (
                is_configurable_menu_item(last_item) and
                menu_cache.item_accepts_input_modifiers(last_item.menu_item_type)
            )
            if accepts_modifiers:
                made_change = add_modifiers_from_input(last_item, input_lower)

                if made_change:
                    updated_summary = recalculate_and_summarize(last_item, self.pricing)
                    return StateMachineResult(
                        message=f"Sure, I've added that to your {updated_summary}. Anything else?",
                        order=order,
                    )

        parsed = parse_open_input(
            user_input,
            model=self.model,
            modifier_category_keywords=self._modifier_category_keywords,
            modifier_item_keywords=self._modifier_item_keywords,
            ingredient_to_items=self._ingredient_to_items,
        )

        # Selections are already extracted in the parsed items during parsing
        extracted_selections: list[Selection] | None = None
        if parsed.parsed_items and parsed.parsed_items[0].modifiers:
            extracted_selections = list(parsed.parsed_items[0].modifiers)
            if extracted_selections:
                logger.info("Selections from input: %s", extracted_selections)

        # Extract order-level special instructions from user input
        instructions_list = extract_special_instructions_from_input(user_input)
        if instructions_list:
            new_instructions = "; ".join(instructions_list)
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

        # Handle "add [modifier]" patterns that modify the last item
        result = self._handle_add_modifier_to_last_item(raw_user_input, order)
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
        result = self._duplicate_handler.handle_repeat_order_request(parsed, order)
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

        if parsed.unclear or parsed.is_greeting:
            # Check if user is trying to order something we don't recognize
            # e.g., "I want home fries", "can I have a croissant"
            if parsed.unclear and raw_user_input and self._unrecognized_handler:
                if looks_like_order_attempt(raw_user_input):
                    item_name = extract_order_item_name(raw_user_input)
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

    def _handle_add_modifier_to_last_item(
        self,
        raw_user_input: str | None,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle 'add [modifier]' patterns - delegates to ModifierInputHandler."""
        return self._modifier_input_handler.handle_add_modifier_to_last_item(raw_user_input, order)

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
