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
    r"^(?:no|nah|nope|naw|no thanks|no thank you|not really)[,.\s]+",
    re.IGNORECASE,
)


_DONT_WANT_DONE_RE = re.compile(
    r"(?:i\s+)?don'?t\s+(?:want|need)\s+(?:anything|nothing|any\s*more)\s*(?:else|more)?",
    re.IGNORECASE,
)


def _is_negative_done(text: str) -> bool:
    """Check if user input is a negative response meaning 'done ordering'.

    Handles direct done signals ("that's it"), negative responses ("no", "nope"),
    combinations like "no nothing else", "nah I'm good", "no that's it",
    and negation phrases like "I don't want anything else".

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

    # Check for "I don't want anything else" style negation
    if _DONT_WANT_DONE_RE.search(text):
        return True

    return False

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

        # Sub-handlers (public for direct access by configuring_item_handler, etc.)
        self.modifier_input_handler = ModifierInputHandler(pricing=config.pricing)
        self.parsed_item_processor = ParsedItemProcessor(
            item_adder_handler=item_adder_handler,
            pricing=config.pricing,
        )
        self._dietary_inquiry_handler = DietaryInquiryHandler(
            config=config,
            unrecognized_handler=self._unrecognized_handler,
        )
        self.inquiry_router = InquiryRouter(
            menu_inquiry_handler=menu_inquiry_handler,
            store_info_handler=store_info_handler,
            dietary_inquiry_handler=self._dietary_inquiry_handler,
        )
        self.duplicate_handler = DuplicateHandler(
            pricing=config.pricing,
            checkout_handler=checkout_handler,
        )
        self._modifier_change_handler = ModifierChangeHandler(config=config)
        self.early_pattern_handler = EarlyPatternHandler(
            pricing=config.pricing,
            modifier_change_handler=self._modifier_change_handler,
        )
        self.suggested_item_handler = SuggestedItemHandler(parent=self)
        self.ingredient_search_handler = IngredientSearchHandler(parent=self)

        # Context set per-request
        self._returning_customer: dict | None = None
        self._set_repeat_info_callback: Callable[[bool, str | None], None] | None = None
        self._store_info: dict = {}

    # Note: _modifier_category_keywords and _modifier_item_keywords are
    # inherited from MenuDataMixin via BaseHandler

    @property
    def _ingredient_to_items(self) -> dict[str, list[dict]]:
        """Get ingredient-to-items mapping for ingredient-based menu search."""
        return self._menu_data.get("ingredient_to_items", {})

    def set_context(
        self,
        ctx: "OrderContext | None" = None,
    ) -> None:
        """Set per-request context from unified OrderContext."""
        if ctx is not None:
            self._returning_customer = ctx.returning_customer
            self._set_repeat_info_callback = ctx.set_repeat_info_callback
            self._store_info = ctx.store_info

        # Propagate context to sub-handlers that need it
        self.duplicate_handler.set_context(ctx)

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

        # After-hours: if store is closed and user confirms ordering
        if not self._store_info.get("is_open", True):
            if menu_cache.is_affirmative(user_input) or "order for then" in user_input.lower():
                # Auto-schedule for next open time
                from ..services.store_hours import get_next_open_time
                timezone_str = self._store_info.get("timezone", "America/New_York")
                hours_config = self._store_info.get("hours_config")
                next_open = get_next_open_time(hours_config, timezone_str)
                if next_open:
                    order.delivery_method.pickup_time = next_open.isoformat()
                    display = self._store_info.get("next_open_time", "when we reopen")
                    return StateMachineResult(
                        message=f"Great! Your order will be scheduled for {display}. What can I get you?",
                        order=order,
                    )

        if parsed.is_small_talk:
            from .parsers.constants import get_order_redirect
            response = parsed.small_talk_response or "Thanks for chatting!"
            redirect = get_order_redirect(has_items=False)
            return StateMachineResult(
                message=f"{response} {redirect}",
                order=order,
            )

        # Check for order type even when greeting/unclear (e.g., "I'd like to do a pickup order")
        if parsed.order_type:
            return self.handle_taking_items_with_parsed(parsed, order, None, user_input)

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
                message="Hi! Welcome to Borough Bagels. What can I get for you today?",
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
        result = self.ingredient_search_handler.handle_category_inquiry_response(user_input, order)
        if result:
            return result

        # Check for early patterns (before LLM parsing)
        # Skip when add_item flag is set (user clicked a menu item) — always treat as new item
        if not getattr(order, '_add_item_flag', False):
            result = self.early_pattern_handler.handle_all_early_patterns(user_input, order)
            if result:
                return result

        # Check for standalone cancel/abandon phrases: "I changed my mind", "never mind",
        # "forget it", "cancel", etc. During TAKING_ITEMS these clear the entire order.
        result = self._check_cancel_order(user_input, order)
        if result:
            return result

        # When no items in cart and user gives an affirmative response
        # (e.g., "sure" to "Do you want to see the menu?"), show the menu
        if not order.items.get_active_items() and menu_cache.is_affirmative(user_input):
            return StateMachineResult(
                message="Here's our menu! Let me know what catches your eye.",
                order=order,
                quick_replies=[{"label": "menu", "value": "show menu", "url": "/static/menu.html"}],
            )

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

        return self.handle_taking_items_with_parsed(parsed, order, extracted_selections, user_input)

    def _intercept_for_store_selection(
        self,
        parsed: "OpenInputResponse",
        order: OrderTask,
    ) -> StateMachineResult:
        """Prompt user to select a store before adding items.

        Called when ``store_confirmed`` is False and the user tries to add
        items. Single-store companies are auto-confirmed.

        The user's original input is saved in ``pending_store_order_text``
        so it can be replayed after the store is confirmed.

        Args:
            parsed: The parsed open input (may contain order_type).
            order: The current order task.

        Returns:
            StateMachineResult with store selection prompt or, for
            single-store companies, re-invokes item processing.
        """
        all_stores = self._store_info.get("all_stores", [])

        # Single store → auto-confirm, process items normally
        if len(all_stores) <= 1:
            order.store_confirmed = True
            if all_stores:
                order._new_store_id = all_stores[0]["store_id"]
            return self.handle_taking_items_with_parsed(parsed, order)

        # Save the user's original item request so it can be replayed
        # after store selection. Pull from conversation history (last user msg).
        for msg_entry in reversed(order.conversation_history):
            if msg_entry.get("role") == "user":
                order.pending_store_order_text = msg_entry["content"]
                break

        # Capture order type if mentioned ("I'd like a pickup order for a bagel")
        if parsed.order_type:
            order.delivery_method.order_type = parsed.order_type

        # Customize prompt based on delivery method
        order_type = order.delivery_method.order_type
        if order_type == "pickup":
            msg = "Before we get started, which location would you like to pick up from?"
        elif order_type == "delivery":
            msg = "Before we get started, which store should we deliver from?"
        else:
            msg = "Before we get started, which location would you like to order from?"

        order.pending_store_change = True
        order.pending_store_page = 0
        return StateMachineResult(
            message=msg,
            order=order,
            quick_replies=[{"label": "from", "value": "show stores"}],
        )

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

        # Require store selection before adding items (new customers only)
        if not order.store_confirmed and parsed.parsed_items:
            return self._intercept_for_store_selection(parsed, order)

        if parsed.done_ordering:
            return self.checkout_utils_handler.transition_to_checkout(order)

        # Check if user specified order type upfront (e.g., "I'd like to place a pickup order")
        # Must run early, before item search handlers interpret "pickup order" as an item.
        if parsed.order_type:
            order.delivery_method.order_type = parsed.order_type
            logger.info("Order type set from upfront mention: %s", parsed.order_type)
            order_type_display = "pickup" if parsed.order_type == "pickup" else "delivery"
            has_items = bool(parsed.parsed_items)
            if not has_items:
                return StateMachineResult(
                    message=f"Great, I'll set this up for {order_type_display}. What can I get for you? Do you want to see the menu?",
                    order=order,
                    quick_replies=[{"label": "menu", "value": "show menu", "url": "/static/menu.html"}],
                )
            # If they also ordered items, continue processing below

        # Handle cart item reference duplication ("more chips", "another bag of chips")
        # This must run BEFORE wants_more_menu_items to catch cart references first
        result = self.duplicate_handler.handle_duplicate_by_reference(parsed, order)
        if result:
            return result

        # Handle ingredient-based menu search
        result = self.ingredient_search_handler.handle_ingredient_search(parsed, order)
        if result:
            return result

        # Fallback: handle single_select attribute modifications not caught by EarlyPatternHandler
        result = self.modifier_input_handler.handle_single_select_attribute_fallback(raw_user_input, order)
        if result:
            return result

        # Handle modification to an existing item in the cart
        result = self.item_modification_handler.handle_modify_existing_item(parsed, order, raw_user_input)
        if result:
            return result

        # Handle item replacement: "make it a coke instead", "change it to X", etc.
        result, replaced_item_name = self.item_replacement_handler.handle_item_replacement(
            parsed, order, raw_user_input
        )
        if result:
            return result

        # Handle item/modifier cancellation: "cancel the coke", "remove bacon", etc.
        result = self.item_cancellation_handler.handle_item_cancellation(parsed, order)
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

        # Handle "make it 2" / "another one" / "one more"
        result = self.duplicate_handler.handle_duplicate_request(parsed, order)
        if result:
            return result

        # Handle "all items" duplicate request
        result = self.duplicate_handler.handle_wants_duplicate_all(parsed, order)
        if result:
            return result

        # Handle repeat order / "same thing" request
        result = self.duplicate_handler.handle_repeat_order_request(
            parsed, order, raw_user_input=raw_user_input
        )
        if result:
            return result

        # Capture unsupported dining option for acknowledgment
        dining_option = parsed.unsupported_dining_option

        # Process all items via parsed_items list
        if parsed.parsed_items:
            result = self.parsed_item_processor.process_items(parsed, order)
            if result:
                if dining_option:
                    note = f"We don't currently support '{dining_option}' orders."
                    result = StateMachineResult(
                        message=f"{note} {result.message}",
                        order=result.order,
                        quick_replies=result.quick_replies,
                    )
                return result

        # If only a dining option was detected with no items, acknowledge it
        if dining_option and not parsed.parsed_items:
            return StateMachineResult(
                message=f"We don't currently support '{dining_option}' orders. What can I get for you?",
                order=order,
            )

        # Handle category clarification
        category_result = self.inquiry_router.route_category_clarification(parsed, order)
        if isinstance(category_result, str):
            # Single item in category - add directly to cart
            return self.item_adder_handler.add_menu_item(category_result, 1, order)
        if category_result:
            return category_result

        # Route all inquiry types through InquiryRouter
        result = self.inquiry_router.route_inquiry(parsed, order, raw_user_input)
        if result:
            return result

        # Handle standalone ingredient (e.g., "I want caramel syrup") - suggest items
        result = self.suggested_item_handler.handle_standalone_ingredient(parsed, order)
        if result:
            return result

        if parsed.unclear or parsed.is_greeting:
            result = self.ingredient_search_handler.handle_unrecognized_order_attempt(
                parsed, order, raw_user_input
            )
            if result:
                return result

            # Try to extract a category reference from desire/mood phrases
            # e.g., "I am in the mood for a sandwich" -> "sandwich" -> show sandwich items
            result = self.ingredient_search_handler.try_extract_category_from_input(raw_user_input, order)
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

