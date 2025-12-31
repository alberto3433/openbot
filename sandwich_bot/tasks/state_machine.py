"""
State Machine for Order Flow.

This module provides a deterministic state machine approach to order capture.
Instead of one large parser trying to interpret everything, each state has
its own focused parser that can only produce valid outputs for that state.

Key insight: When pending_item_id points to an incomplete item, ALL input
is interpreted in the context of that item - no new items can be created.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Optional, Union
import logging
import re
import uuid

from .models import (
    OrderTask,
    MenuItemTask,
    BagelItemTask,
    CoffeeItemTask,
    SpeedMenuBagelItemTask,
    ItemTask,
    TaskStatus,
)
from .slot_orchestrator import SlotOrchestrator, SlotCategory
from .pricing import PricingEngine
from .menu_lookup import MenuLookup
from .query_handler import QueryHandler
from .message_builder import MessageBuilder
from .checkout_handler import CheckoutHandler
from .bagel_config_handler import BagelConfigHandler
from .coffee_config_handler import CoffeeConfigHandler
from .speed_menu_handler import SpeedMenuBagelHandler
from .store_info_handler import StoreInfoHandler
from .menu_inquiry_handler import MenuInquiryHandler
from .by_pound_handler import ByPoundHandler
from .order_utils_handler import OrderUtilsHandler
from .item_adder_handler import ItemAdderHandler
from .checkout_utils_handler import CheckoutUtilsHandler
from .config_helper_handler import ConfigHelperHandler
from .confirmation_handler import ConfirmationHandler
from .modifier_change_handler import ModifierChangeHandler, ModifierCategory
from .slot_orchestration_handler import SlotOrchestrationHandler
from .configuring_item_handler import ConfiguringItemHandler
from .taking_items_handler import TakingItemsHandler

# Import from new modular structure
from .schemas import (
    OrderPhase,
    StateMachineResult,
    BagelOrderDetails,
    CoffeeOrderDetails,
    ByPoundOrderItem,
    OpenInputResponse,
    ExtractedModifiers,
    ExtractedCoffeeModifiers,
    # Re-export for backwards compatibility with tests
    BagelChoiceResponse,
    SpreadChoiceResponse,
    MultiBagelChoiceResponse,
    MultiSpreadResponse,
    MultiToastedResponse,
    ToastedChoiceResponse,
)
from .parsers import (
    # Validators
    validate_email_address,
    validate_phone_number,
    extract_zip_code,
    validate_delivery_zip_code,
    # Deterministic yes/no parsing
    parse_toasted_deterministic,
    parse_hot_iced_deterministic,
    # Constants - Drink categories
    SODA_DRINK_TYPES,
    COFFEE_BEVERAGE_TYPES,
    is_soda_drink,
    # Constants - Number mapping
    WORD_TO_NUM,
    # Constants - Bagel and spread types
    BAGEL_TYPES,
    SPREADS,
    SPREAD_TYPES,
    # Constants - Speed menu items
    SPEED_MENU_BAGELS,
    # Constants - By-the-pound items and prices
    BY_POUND_ITEMS,
    BY_POUND_CATEGORY_NAMES,
    BY_POUND_PRICES,
    # Constants - Bagel modifiers
    BAGEL_PROTEINS,
    BAGEL_CHEESES,
    BAGEL_TOPPINGS,
    BAGEL_SPREADS,
    MODIFIER_NORMALIZATIONS,
    # Constants - Regex patterns (basic)
    QUALIFIER_PATTERNS,
    GREETING_PATTERNS,
    DONE_PATTERNS,
    REPEAT_ORDER_PATTERNS,
    # Constants - Side items
    SIDE_ITEM_MAP,
    SIDE_ITEM_TYPES,
    # Constants - Menu item recognition
    KNOWN_MENU_ITEMS,
    NO_THE_PREFIX_ITEMS,
    MENU_ITEM_CANONICAL_NAMES,
    # Constants - Coffee typos
    COFFEE_TYPO_MAP,
    # Constants - Price inquiry patterns
    PRICE_INQUIRY_PATTERNS,
    MENU_CATEGORY_KEYWORDS,
    # Constants - Store info patterns
    STORE_HOURS_PATTERNS,
    STORE_LOCATION_PATTERNS,
    DELIVERY_ZONE_PATTERNS,
    NYC_NEIGHBORHOOD_ZIPS,
    # Constants - Recommendation patterns
    RECOMMENDATION_PATTERNS,
    # Constants - Item description patterns
    ITEM_DESCRIPTION_PATTERNS,
    # String normalization utilities
    normalize_for_match,
    # Deterministic parsers - Compiled patterns
    REPLACE_ITEM_PATTERN,
    CANCEL_ITEM_PATTERN,
    TAX_QUESTION_PATTERN,
    ORDER_STATUS_PATTERN,
    BAGEL_QUANTITY_PATTERN,
    SIMPLE_BAGEL_PATTERN,
    COFFEE_ORDER_PATTERN,
    # Deterministic parsers - Modifier extraction
    extract_modifiers_from_input,
    extract_coffee_modifiers_from_input,
    extract_notes_from_input,
    # Deterministic parsers - Internal helpers
    _build_spread_types_from_menu,
    parse_open_input_deterministic,
    _parse_multi_item_order,
    _parse_recommendation_inquiry,
    _parse_item_description_inquiry,
    _parse_speed_menu_bagel_deterministic,
    _parse_store_info_inquiry,
    _parse_price_inquiry_deterministic,
    _parse_soda_deterministic,
    _parse_coffee_deterministic,
    # LLM parsers
    parse_side_choice,
    parse_bagel_choice,
    parse_multi_bagel_choice,
    parse_multi_toasted,
    parse_multi_spread,
    parse_spread_choice,
    parse_toasted_choice,
    parse_coffee_size,
    parse_coffee_style,
    parse_by_pound_category,
    parse_open_input,
    parse_confirmation,
)

logger = logging.getLogger(__name__)

# Logger for slot orchestrator comparison (can be enabled/disabled independently)
slot_logger = logging.getLogger(__name__ + ".slot_comparison")


# =============================================================================
# State Machine
# =============================================================================
# Note: Parsing functions have been moved to:
# - parsers/deterministic.py (regex-based parsing)
# - parsers/llm_parsers.py (LLM-based parsing)

def _looks_like_new_order_attempt(user_input: str) -> bool:
    """
    Detect if user input looks like an attempt to order a new item
    rather than answer a pending configuration question.

    This helps redirect users who say "bagel with cream cheese" when
    asked "What kind of bagel?" for their ham, egg, and cheese bagel.
    """
    text = user_input.lower().strip()

    # First, check if this looks like a simple answer rather than a new order
    # "[type] bagel" or just "[type]" are valid answers, not new orders
    # e.g., "plain bagel", "everything", "sesame bagel"
    bagel_type_pattern = r'^(' + '|'.join(re.escape(bt) for bt in BAGEL_TYPES) + r')(?:\s+bagel)?s?(?:\s+please)?$'
    if re.search(bagel_type_pattern, text):
        return False

    # Pattern: "bagel with X" (ordering a new item with modifiers)
    if re.search(r'\bbagel\s+with\s+\w+', text):
        return True

    # Pattern: quantity-based ordering ("2 bagels", "a bagel")
    if BAGEL_QUANTITY_PATTERN.search(text):
        return True

    # Pattern: simple bagel ordering ("a bagel please", "bagel please")
    if SIMPLE_BAGEL_PATTERN.search(text):
        return True

    # Pattern: coffee ordering
    if COFFEE_ORDER_PATTERN.search(text):
        return True

    # Pattern: explicit ordering language ("I'd like", "can I get", "I want")
    if re.search(r"(?:i(?:'?d|\s*would)?\s*(?:like|want|need|take|have|get)|(?:can|could|may)\s+i\s+(?:get|have))", text):
        return True

    return False


def _get_pending_item_description(item: "ItemTask") -> str:
    """Get a short description of the pending item for redirect messages."""
    if isinstance(item, BagelItemTask):
        # Describe based on what's been specified
        parts = []
        if item.sandwich_protein:
            parts.append(item.sandwich_protein)
        if item.extras:
            parts.extend(item.extras[:2])  # Limit to avoid long descriptions
        if parts:
            return " ".join(parts) + " bagel"
        return "bagel"
    elif isinstance(item, MenuItemTask):
        return item.menu_item_name or "item"
    elif isinstance(item, CoffeeItemTask):
        return item.beverage_type or "coffee"
    elif isinstance(item, SpeedMenuBagelItemTask):
        return item.speed_menu_name or "bagel"
    return "item"


def _check_redirect_to_pending_item(
    user_input: str,
    item: "ItemTask",
    order: "OrderTask",
    question: str,
    valid_answers: set[str] | None = None,
) -> "StateMachineResult | None":
    """
    Check if user is trying to order a new item instead of answering a pending question.

    If the user appears to be ordering something new (e.g., "bagel with cream cheese"
    when asked "What kind of bagel?"), returns a redirect message asking them to
    complete the current item first.

    Args:
        user_input: The user's input text
        item: The pending item being configured
        order: The current order
        question: The question to re-ask (e.g., "Would you like it toasted?")
        valid_answers: Optional set of valid answer keywords that should NOT be
                       considered new order attempts (e.g., {"bagel", "fruit salad"}
                       for side_choice questions)

    Returns:
        StateMachineResult with redirect message if user is ordering new item,
        None if user is answering the pending question normally.
    """
    # If user input matches a valid answer for this question, don't redirect
    if valid_answers:
        text_lower = user_input.lower().strip()
        for answer in valid_answers:
            if answer in text_lower:
                return None

    if _looks_like_new_order_attempt(user_input):
        item_desc = _get_pending_item_description(item)
        return StateMachineResult(
            message=f"Let's finish up your {item_desc} first. {question}",
            order=order,
        )
    return None


class OrderStateMachine:
    """
    State machine for order capture.

    The key principle: when we're waiting for input on a specific item
    (pending_item_id is set), we use a constrained parser that can ONLY
    interpret input as answers for that item. No new items can be created.
    """

    def __init__(self, menu_data: dict | None = None, model: str = "gpt-4o-mini"):
        self._menu_data = menu_data or {}
        self.model = model
        # Build spread types from database cheese_types
        self._spread_types = _build_spread_types_from_menu(
            self._menu_data.get("cheese_types", [])
        )
        # Initialize slot orchestration handler early (needed for callbacks)
        self.slot_orchestration_handler = SlotOrchestrationHandler()
        # Initialize menu lookup engine
        self.menu_lookup = MenuLookup(self._menu_data)
        # Initialize pricing engine with menu lookup callback
        self.pricing = PricingEngine(self._menu_data, self.menu_lookup.lookup_menu_item)
        # Initialize query handler (store_info set per-request in process())
        self.query_handler = QueryHandler(self._menu_data, None, self.pricing)
        # Initialize message builder
        self.message_builder = MessageBuilder()
        # Initialize checkout handler (context set per-request in process())
        self.checkout_handler = CheckoutHandler(
            model=self.model,
            message_builder=self.message_builder,
            transition_callback=self._transition_to_next_slot,
        )
        # Initialize checkout utils handler early (coffee callback set below)
        self.checkout_utils_handler = CheckoutUtilsHandler(
            transition_to_next_slot=self._transition_to_next_slot,
            configure_next_incomplete_coffee=None,  # Set after coffee_handler init
        )
        # Initialize coffee config handler
        self.coffee_handler = CoffeeConfigHandler(
            model=self.model,
            pricing=self.pricing,
            menu_lookup=self.menu_lookup,
            get_next_question=self.checkout_utils_handler.get_next_question,
            check_redirect=_check_redirect_to_pending_item,
        )
        # Now set the coffee callback on checkout_utils_handler
        self.checkout_utils_handler._configure_next_incomplete_coffee = self.coffee_handler.configure_next_incomplete_coffee
        # Initialize bagel config handler
        self.bagel_handler = BagelConfigHandler(
            model=self.model,
            pricing=self.pricing,
            get_next_question=self.checkout_utils_handler.get_next_question,
            get_item_by_id=self.checkout_utils_handler.get_item_by_id,
            configure_coffee=self.coffee_handler.configure_next_incomplete_coffee,
            check_redirect=_check_redirect_to_pending_item,
        )
        # Initialize speed menu bagel handler
        self.speed_menu_handler = SpeedMenuBagelHandler(
            model=self.model,
            menu_lookup=self.menu_lookup,
            get_next_question=self.checkout_utils_handler.get_next_question,
        )
        # Now set the speed menu bagel callback on checkout_utils_handler
        self.checkout_utils_handler._configure_next_incomplete_speed_menu_bagel = self.speed_menu_handler.configure_next_incomplete_speed_menu_bagel
        # Initialize store info handler
        self.store_info_handler = StoreInfoHandler(menu_data=self._menu_data)
        # Initialize by-the-pound handler
        self.by_pound_handler = ByPoundHandler(
            model=self.model,
            menu_data=self._menu_data,
            pricing=self.pricing,
            process_taking_items_input=self._handle_taking_items,
        )
        # Initialize menu inquiry handler
        self.menu_inquiry_handler = MenuInquiryHandler(
            menu_data=self._menu_data,
            pricing=self.pricing,
            list_by_pound_category=self.by_pound_handler.list_by_pound_category,
        )
        # Initialize order utils handler
        self.order_utils_handler = OrderUtilsHandler(
            build_order_summary=self.checkout_utils_handler.build_order_summary,
        )
        # Initialize item adder handler
        self.item_adder_handler = ItemAdderHandler(
            menu_lookup=self.menu_lookup,
            pricing=self.pricing,
            get_next_question=self.checkout_utils_handler.get_next_question,
            configure_next_incomplete_bagel=self.bagel_handler.configure_next_incomplete_bagel,
        )
        self.item_adder_handler.menu_data = self._menu_data
        # Initialize modifier change handler
        self.modifier_change_handler = ModifierChangeHandler(pricing=self.pricing)
        # Initialize config helper handler
        self.config_helper_handler = ConfigHelperHandler(
            model=self.model,
            modifier_change_handler=self.modifier_change_handler,
            get_next_question=self.checkout_utils_handler.get_next_question,
        )
        # Initialize confirmation handler
        self.confirmation_handler = ConfirmationHandler(
            model=self.model,
            order_utils_handler=self.order_utils_handler,
            checkout_utils_handler=self.checkout_utils_handler,
            transition_to_next_slot=self._transition_to_next_slot,
            handle_taking_items_with_parsed=self._handle_taking_items_with_parsed,
        )
        # Initialize configuring item handler
        self.configuring_item_handler = ConfiguringItemHandler(
            by_pound_handler=self.by_pound_handler,
            coffee_handler=self.coffee_handler,
            bagel_handler=self.bagel_handler,
            speed_menu_handler=self.speed_menu_handler,
            config_helper_handler=self.config_helper_handler,
            checkout_utils_handler=self.checkout_utils_handler,
            modifier_change_handler=self.modifier_change_handler,
            item_adder_handler=self.item_adder_handler,
        )
        # Initialize taking items handler
        self.taking_items_handler = TakingItemsHandler(
            model=self.model,
            pricing=self.pricing,
            coffee_handler=self.coffee_handler,
            item_adder_handler=self.item_adder_handler,
            speed_menu_handler=self.speed_menu_handler,
            menu_inquiry_handler=self.menu_inquiry_handler,
            store_info_handler=self.store_info_handler,
            by_pound_handler=self.by_pound_handler,
            checkout_utils_handler=self.checkout_utils_handler,
            confirmation_handler=self.confirmation_handler,
        )

    @property
    def menu_data(self) -> dict:
        return self._menu_data

    @menu_data.setter
    def menu_data(self, value: dict) -> None:
        self._menu_data = value or {}
        # Rebuild spread types when menu_data changes
        self._spread_types = _build_spread_types_from_menu(
            self._menu_data.get("cheese_types", [])
        )
        # Update menu lookup engine menu data
        self.menu_lookup.menu_data = self._menu_data
        # Update pricing engine menu data
        self.pricing.menu_data = self._menu_data
        # Update query handler menu data
        self.query_handler.menu_data = self._menu_data
        # Update store info handler menu data
        self.store_info_handler.menu_data = self._menu_data
        # Update by-the-pound handler menu data
        self.by_pound_handler.menu_data = self._menu_data
        # Update menu inquiry handler menu data
        self.menu_inquiry_handler.menu_data = self._menu_data
        # Update item adder handler menu data
        self.item_adder_handler.menu_data = self._menu_data

    def process(
        self,
        user_input: str,
        order: OrderTask | None = None,
        returning_customer: dict | None = None,
        store_info: dict | None = None,
    ) -> StateMachineResult:
        """
        Process user input through the state machine.

        Args:
            user_input: What the user said
            order: Current order (None for new conversation)
            returning_customer: Returning customer data (name, phone, last_order_items)
            store_info: Store configuration (delivery_zip_codes, tax rates, etc.)

        Returns:
            StateMachineResult with response message and updated order
        """
        if order is None:
            order = OrderTask()

        # Store returning customer data for repeat order handling
        self._returning_customer = returning_customer
        # Store store info for delivery validation
        self._store_info = store_info or {}
        # Update query handler with current store info
        self.query_handler.store_info = self._store_info
        # Update checkout handler with current context
        self.checkout_handler.set_context(
            store_info=self._store_info,
            returning_customer=returning_customer,
            is_repeat_order=getattr(self, '_is_repeat_order', False),
            last_order_type=getattr(self, '_last_order_type', None),
        )
        # Update store info handler with current store info
        self.store_info_handler.set_store_info(self._store_info)
        # Update order utils handler with current store info
        self.order_utils_handler.set_store_info(self._store_info)
        # Update checkout utils handler with repeat order info
        self.checkout_utils_handler.set_repeat_order_info(
            is_repeat=getattr(self, '_is_repeat_order', False),
            last_order_type=getattr(self, '_last_order_type', None),
        )
        # Update confirmation handler with context
        self.confirmation_handler.set_context(
            spread_types=self._spread_types,
            returning_customer=returning_customer,
        )
        # Update taking items handler with context
        def set_repeat_info(is_repeat: bool, last_order_type: str | None) -> None:
            self._is_repeat_order = is_repeat
            self._last_order_type = last_order_type
            self.checkout_utils_handler.set_repeat_order_info(is_repeat, last_order_type)
        self.taking_items_handler.set_context(
            spread_types=self._spread_types,
            returning_customer=returning_customer,
            set_repeat_info_callback=set_repeat_info,
        )

        # Reset repeat order flag - only set when user explicitly requests repeat order
        # This prevents the flag from persisting across different sessions on the singleton
        if not hasattr(self, '_is_repeat_order') or order.items.get_item_count() == 0:
            self._is_repeat_order = False
            self._last_order_type = None

        # Add user message to history
        order.add_message("user", user_input)

        # Check for order status request (works from any state)
        if ORDER_STATUS_PATTERN.search(user_input):
            logger.info("ORDER STATUS: User asked for order status")
            result = self.order_utils_handler.handle_order_status(order)
            order.add_message("assistant", result.message)
            return result

        # Check for pending change clarification response
        if order.pending_change_clarification:
            result = self.config_helper_handler.handle_change_clarification_response(user_input, order)
            if result:
                order.add_message("assistant", result.message)
                return result
            # If no result, the response wasn't understood - fall through to normal processing

        # Check for modifier change requests (works when not mid-configuration)
        if order.items.get_item_count() > 0 and not order.is_configuring_item():
            change_result = self.config_helper_handler.handle_modifier_change_request(user_input, order)
            if change_result:
                order.add_message("assistant", change_result.message)
                return change_result

        # Check for "make it 2" pattern early (works from any state with items)
        # This must be before phase routing to catch it no matter what phase we're in
        from .parsers.deterministic import MAKE_IT_N_PATTERN
        make_it_n_match = MAKE_IT_N_PATTERN.match(user_input.strip())
        if make_it_n_match and order.items.get_item_count() > 0:
            num_str = None
            for i in range(1, 8):
                if make_it_n_match.group(i):
                    num_str = make_it_n_match.group(i).lower()
                    break
            if num_str:
                word_to_num = {
                    "two": 2, "three": 3, "four": 4, "five": 5,
                    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
                }
                if num_str.isdigit():
                    target_qty = int(num_str)
                else:
                    target_qty = word_to_num.get(num_str, 0)

                if target_qty >= 2:
                    active_items = order.items.get_active_items()
                    if active_items:
                        last_item = active_items[-1]
                        last_item_name = last_item.get_summary()

                        # Count how many of this same item are already in the order
                        current_count = sum(
                            1 for item in active_items
                            if item.get_summary() == last_item_name
                        )

                        # Only add enough to reach the target
                        added_count = target_qty - current_count

                        if added_count <= 0:
                            # Already have enough or more
                            msg = f"You already have {current_count} {last_item_name}. Anything else?"
                            order.add_message("assistant", msg)
                            return StateMachineResult(message=msg, order=order)

                        for _ in range(added_count):
                            new_item = last_item.model_copy(deep=True)
                            new_item.id = str(uuid.uuid4())
                            new_item.mark_complete()
                            order.items.add_item(new_item)

                        logger.info("GLOBAL: Added %d more of '%s' (now %d total)", added_count, last_item_name, target_qty)

                        if added_count == 1:
                            msg = f"I've added another {last_item_name}, so that's {target_qty} total. Anything else?"
                        else:
                            msg = f"I've added {added_count} more {last_item_name}, so that's {target_qty} total. Anything else?"

                        order.add_message("assistant", msg)
                        return StateMachineResult(message=msg, order=order)

        # Derive phase from OrderTask state via orchestrator
        # Note: is_configuring_item() takes precedence (based on pending_item_ids)
        # Also: Don't overwrite checkout phases that are explicitly set by handlers
        # The orchestrator shouldn't override these - we're already in a specific checkout flow
        phases_to_preserve = {
            OrderPhase.CHECKOUT_DELIVERY.value,
            OrderPhase.CHECKOUT_NAME.value,
            OrderPhase.CHECKOUT_CONFIRM.value,
            OrderPhase.CHECKOUT_PAYMENT_METHOD.value,
            OrderPhase.CHECKOUT_EMAIL.value,
            OrderPhase.CHECKOUT_PHONE.value,
        }
        # CRITICAL: Don't transition from TAKING_ITEMS at the start of processing!
        # We need to parse the user's input first to see if they're adding more items.
        # The ITEMS slot being "complete" (all items configured) doesn't mean the user
        # is done ordering - they might say "and also a latte" after completing a bagel.
        # The transition to checkout should only happen in _handle_taking_items when
        # the user explicitly says they're done (done_ordering=True).
        if order.phase == OrderPhase.TAKING_ITEMS.value and order.items.get_item_count() > 0:
            # Stay in TAKING_ITEMS until user says they're done
            pass
        elif not order.is_configuring_item() and order.phase not in phases_to_preserve:
            self._transition_to_next_slot(order)

        logger.info("STATE MACHINE: Processing '%s' in phase %s (pending_field=%s, pending_items=%s)",
                   user_input[:50], order.phase, order.pending_field, order.pending_item_ids)

        # Route to appropriate handler based on phase
        if order.is_configuring_item():
            result = self._handle_configuring_item(user_input, order)
        elif order.phase == OrderPhase.GREETING.value:
            result = self._handle_greeting(user_input, order)
        elif order.phase == OrderPhase.TAKING_ITEMS.value:
            result = self._handle_taking_items(user_input, order)
        elif order.phase == OrderPhase.CHECKOUT_DELIVERY.value:
            result = self.checkout_handler.handle_delivery(user_input, order)
        elif order.phase == OrderPhase.CHECKOUT_NAME.value:
            result = self.checkout_handler.handle_name(user_input, order)
        elif order.phase == OrderPhase.CHECKOUT_CONFIRM.value:
            result = self.confirmation_handler.handle_confirmation(user_input, order)
        elif order.phase == OrderPhase.CHECKOUT_PAYMENT_METHOD.value:
            result = self.checkout_handler.handle_payment_method(user_input, order)
        elif order.phase == OrderPhase.CHECKOUT_PHONE.value:
            result = self.checkout_handler.handle_phone(user_input, order)
        elif order.phase == OrderPhase.CHECKOUT_EMAIL.value:
            result = self.checkout_handler.handle_email(user_input, order)
        else:
            result = StateMachineResult(
                message="I'm not sure what to do. Can you try again?",
                order=order,
            )

        # Add bot message to history
        order.add_message("assistant", result.message)

        # Log slot comparison for debugging
        self._log_slot_comparison(order)

        return result

    def _log_slot_comparison(self, order: OrderTask) -> None:
        """Delegate to slot orchestration handler."""
        self.slot_orchestration_handler.log_slot_comparison(order)

    def _derive_next_phase_from_slots(self, order: OrderTask) -> OrderPhase:
        """Delegate to slot orchestration handler."""
        return self.slot_orchestration_handler.derive_next_phase_from_slots(order)

    def _transition_to_next_slot(self, order: OrderTask) -> None:
        """Delegate to slot orchestration handler."""
        self.slot_orchestration_handler.transition_to_next_slot(order)

    def _handle_greeting(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Delegate to taking items handler."""
        return self.taking_items_handler.handle_greeting(user_input, order)

    def _handle_taking_items(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Delegate to taking items handler."""
        return self.taking_items_handler.handle_taking_items(user_input, order)

    def _handle_taking_items_with_parsed(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        extracted_modifiers: ExtractedModifiers | None = None,
        raw_user_input: str | None = None,
    ) -> StateMachineResult:
        """Delegate to taking items handler."""
        return self.taking_items_handler.handle_taking_items_with_parsed(parsed, order, extracted_modifiers, raw_user_input)

    def _handle_configuring_item(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Delegate to configuring item handler."""
        return self.configuring_item_handler.handle_configuring_item(user_input, order)

    # =========================================================================
    # NOTE: Confirmation and repeat order methods have been extracted to
    # confirmation_handler.py
    # NOTE: By-the-Pound handlers have been extracted to by_pound_handler.py
    # NOTE: Menu Query, Price Inquiry, Item Description, and Signature Menu
    # handlers have been extracted to menu_inquiry_handler.py
    # NOTE: Drink selection handler has been extracted to coffee_config_handler.py
    # NOTE: Checkout utilities (_get_next_question, _transition_to_checkout,
    # _build_order_summary, etc.) have been extracted to checkout_utils_handler.py
    # NOTE: Item adding methods (_add_menu_item, _add_side_item, _add_bagel, etc.)
    # have been extracted to item_adder_handler.py
    # =========================================================================

