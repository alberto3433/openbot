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

# Import from new modular structure
from .schemas import (
    OrderPhase,
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

@dataclass
class StateMachineResult:
    """Result from state machine processing."""
    message: str
    order: OrderTask
    is_complete: bool = False


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
        self.modifier_change_handler = ModifierChangeHandler()
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
        """
        Log slot orchestrator state for debugging.
        """
        try:
            orchestrator = SlotOrchestrator(order)
            orch_phase = orchestrator.get_current_phase()

            # Get next slot for additional context
            next_slot = orchestrator.get_next_slot()
            next_slot_info = f"{next_slot.category.value}" if next_slot else "none"

            slot_logger.debug(
                "SLOT STATE: phase=%s, orch_phase=%s, next_slot=%s",
                order.phase, orch_phase, next_slot_info
            )

            # Log slot progress for visibility
            progress = orchestrator.get_progress()
            filled_slots = [k for k, v in progress.items() if v]
            empty_slots = [k for k, v in progress.items() if not v]
            slot_logger.debug(
                "SLOT PROGRESS: filled=%s, empty=%s",
                filled_slots, empty_slots
            )

        except Exception as e:
            slot_logger.error("SLOT COMPARISON ERROR: %s", e)

    def _derive_next_phase_from_slots(self, order: OrderTask) -> OrderPhase:
        """
        Use SlotOrchestrator to determine the next phase.

        This is Phase 2 of the migration - using the orchestrator to drive
        phase transitions instead of hardcoded assignments.
        """
        orchestrator = SlotOrchestrator(order)

        # Check if any items are being configured
        current_item = order.items.get_current_item()
        if current_item is not None:
            return OrderPhase.CONFIGURING_ITEM

        next_slot = orchestrator.get_next_slot()
        if next_slot is None:
            return OrderPhase.COMPLETE

        # Map slot categories to OrderPhase values
        phase_map = {
            SlotCategory.ITEMS: OrderPhase.TAKING_ITEMS,
            SlotCategory.DELIVERY_METHOD: OrderPhase.CHECKOUT_DELIVERY,
            SlotCategory.DELIVERY_ADDRESS: OrderPhase.CHECKOUT_DELIVERY,  # Address is part of delivery
            SlotCategory.CUSTOMER_NAME: OrderPhase.CHECKOUT_NAME,
            SlotCategory.ORDER_CONFIRM: OrderPhase.CHECKOUT_CONFIRM,
            SlotCategory.PAYMENT_METHOD: OrderPhase.CHECKOUT_PAYMENT_METHOD,
            SlotCategory.NOTIFICATION: OrderPhase.CHECKOUT_PHONE,  # Will be refined later
        }
        return phase_map.get(next_slot.category, OrderPhase.TAKING_ITEMS)

    def _transition_to_next_slot(self, order: OrderTask) -> None:
        """
        Update order.phase based on SlotOrchestrator.

        This replaces hardcoded phase transitions with orchestrator-driven
        transitions that look at what's actually filled in the order.
        """
        next_phase = self._derive_next_phase_from_slots(order)
        if order.phase != next_phase.value:
            logger.info("SLOT TRANSITION: %s -> %s", order.phase, next_phase.value)
        order.phase = next_phase.value

    def _handle_greeting(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle greeting phase."""
        parsed = parse_open_input(user_input, model=self.model, spread_types=self._spread_types)

        logger.info(
            "Greeting phase parsed: is_greeting=%s, unclear=%s, new_bagel=%s, quantity=%d",
            parsed.is_greeting,
            parsed.unclear,
            parsed.new_bagel,
            parsed.new_bagel_quantity,
        )

        if parsed.is_greeting or parsed.unclear:
            # Phase will be derived as TAKING_ITEMS by orchestrator on next turn
            return StateMachineResult(
                message="Hi! Welcome to Zucker's. What can I get for you today?",
                order=order,
            )

        # User might have ordered something directly - pass the already parsed result
        # Also extract modifiers from the raw input
        extracted_modifiers = extract_modifiers_from_input(user_input)
        if extracted_modifiers.has_modifiers():
            logger.info("Extracted modifiers from greeting input: %s", extracted_modifiers)

        # Phase is derived from orchestrator, no need to set explicitly
        return self._handle_taking_items_with_parsed(parsed, order, extracted_modifiers, user_input)

    def _handle_taking_items(
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
                        added_count = target_qty - 1

                        for _ in range(added_count):
                            new_item = last_item.model_copy(deep=True)
                            new_item.id = str(uuid.uuid4())
                            new_item.mark_complete()
                            order.items.add_item(new_item)

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

        parsed = parse_open_input(user_input, model=self.model, spread_types=self._spread_types)

        # Extract modifiers from raw input (keyword-based, no LLM)
        extracted_modifiers = extract_modifiers_from_input(user_input)
        if extracted_modifiers.has_modifiers():
            logger.info("Extracted modifiers from input: %s", extracted_modifiers)

        return self._handle_taking_items_with_parsed(parsed, order, extracted_modifiers, user_input)

    def _handle_taking_items_with_parsed(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        extracted_modifiers: ExtractedModifiers | None = None,
        raw_user_input: str | None = None,
    ) -> StateMachineResult:
        """Handle taking new item orders with already-parsed input."""
        logger.info(
            "Parsed open input: new_menu_item='%s', new_bagel=%s, quantity=%d, bagel_details=%d, done_ordering=%s",
            parsed.new_menu_item,
            parsed.new_bagel,
            parsed.new_bagel_quantity,
            len(parsed.bagel_details),
            parsed.done_ordering,
        )

        if parsed.done_ordering:
            return self.checkout_utils_handler.transition_to_checkout(order)

        # Handle item replacement: "make it a coke instead", "change it to X", etc.
        replaced_item_name = None
        if parsed.replace_last_item:
            active_items = order.items.get_active_items()
            if active_items:
                last_item = active_items[-1]

                # Check if parsed result has any valid new items
                has_new_items = (
                    parsed.new_bagel or parsed.new_coffee or parsed.new_menu_item or
                    parsed.new_speed_menu_bagel or parsed.new_side_item or parsed.by_pound_items
                )

                # If no new items parsed and last item is a bagel, try applying as modifiers
                if not has_new_items and isinstance(last_item, BagelItemTask) and raw_user_input:
                    modifiers = extract_modifiers_from_input(raw_user_input)
                    has_modifiers = modifiers.proteins or modifiers.cheeses or modifiers.toppings

                    if has_modifiers:
                        # Apply modifiers to existing bagel instead of replacing
                        logger.info("Replacement: applying modifiers to existing bagel: %s", modifiers)

                        # Update protein - replace existing
                        if modifiers.proteins:
                            last_item.sandwich_protein = modifiers.proteins[0]
                            # Additional proteins go to extras (replace existing extras)
                            last_item.extras = list(modifiers.proteins[1:])
                        else:
                            # Clear protein if not in new modifiers
                            last_item.sandwich_protein = None
                            last_item.extras = []

                        # Add cheeses and toppings to extras
                        last_item.extras.extend(modifiers.cheeses)
                        last_item.extras.extend(modifiers.toppings)

                        # Update spread if specified
                        if modifiers.spreads:
                            last_item.spread = modifiers.spreads[0]
                        else:
                            last_item.spread = "none"

                        # Recalculate price with new modifiers
                        self.pricing.recalculate_bagel_price(last_item)

                        # Return confirmation with updated item
                        updated_summary = last_item.get_summary()
                        return StateMachineResult(
                            message=f"Sure, I've changed that to {updated_summary}. Anything else?",
                            order=order,
                        )

                # Normal replacement: remove old item, new item will be added below
                replaced_item_name = last_item.get_summary()
                last_item_index = order.items.items.index(last_item)
                order.items.remove_item(last_item_index)
                logger.info("Replacement: removed last item '%s' from cart", replaced_item_name)
            else:
                logger.info("Replacement requested but no items in cart to replace")

        # Handle item cancellation: "cancel the coke", "remove the bagel", etc.
        if parsed.cancel_item:
            cancel_item_desc = parsed.cancel_item.lower()
            active_items = order.items.get_active_items()
            if active_items:
                # Check if plural removal (e.g., "coffees", "bagels")
                is_plural = cancel_item_desc.endswith('s') and len(cancel_item_desc) > 2
                singular_desc = cancel_item_desc[:-1] if is_plural else cancel_item_desc

                # Find matching items
                items_to_remove = []
                for item in reversed(active_items):  # Search from most recent
                    item_summary = item.get_summary().lower()
                    item_name = getattr(item, 'menu_item_name', '') or ''
                    item_name_lower = item_name.lower()
                    item_type = getattr(item, 'item_type', '') or ''

                    # Check for matches - be careful with empty strings
                    matches = False
                    if cancel_item_desc in item_summary:
                        matches = True
                    elif singular_desc in item_summary:
                        matches = True
                    elif item_name_lower and cancel_item_desc in item_name_lower:
                        matches = True
                    elif item_name_lower and singular_desc in item_name_lower:
                        matches = True
                    elif item_name_lower and item_name_lower in cancel_item_desc:
                        matches = True
                    # Check item_type for "coffees" -> item_type="coffee"
                    elif item_type and (cancel_item_desc == item_type or singular_desc == item_type):
                        matches = True
                    elif any(word in item_summary for word in cancel_item_desc.split() if word):
                        matches = True

                    if matches:
                        items_to_remove.append(item)
                        # If not plural, only remove one item
                        if not is_plural:
                            break

                if items_to_remove:
                    # Remove all matching items
                    removed_names = []
                    for item in items_to_remove:
                        removed_names.append(item.get_summary())
                        idx = order.items.items.index(item)
                        order.items.remove_item(idx)

                    # Build response message
                    if len(removed_names) == 1:
                        removed_str = f"the {removed_names[0]}"
                    else:
                        removed_str = f"the {len(removed_names)} {singular_desc}s"

                    logger.info("Cancellation: removed %d item(s) from cart: %s", len(removed_names), removed_names)

                    remaining_items = order.items.get_active_items()
                    if remaining_items:
                        return StateMachineResult(
                            message=f"OK, I've removed {removed_str}. Anything else?",
                            order=order,
                        )
                    else:
                        return StateMachineResult(
                            message=f"OK, I've removed {removed_str}. What would you like to order?",
                            order=order,
                        )
                else:
                    # Item not found - let them know
                    logger.info("Cancellation: couldn't find item matching '%s'", cancel_item_desc)
                    return StateMachineResult(
                        message=f"I couldn't find {parsed.cancel_item} in your order. What would you like to do?",
                        order=order,
                    )
            else:
                # No items to cancel
                logger.info("Cancellation requested but no items in cart")
                return StateMachineResult(
                    message="There's nothing in your order yet. What can I get for you?",
                    order=order,
                )

        # Handle "make it 2" - add more of the last item
        if parsed.duplicate_last_item > 0:
            active_items = order.items.get_active_items()
            if active_items:
                last_item = active_items[-1]
                last_item_name = last_item.get_summary()
                added_count = parsed.duplicate_last_item

                # Add copies of the last item
                for _ in range(added_count):
                    # Create a copy of the item
                    new_item = last_item.model_copy(deep=True)
                    # Generate a new ID for the copy
                    new_item.id = str(uuid.uuid4())
                    new_item.mark_complete()
                    order.items.add_item(new_item)

                if added_count == 1:
                    logger.info("Added 1 more of '%s' to order", last_item_name)
                    return StateMachineResult(
                        message=f"I've added a second {last_item_name}. Anything else?",
                        order=order,
                    )
                else:
                    logger.info("Added %d more of '%s' to order", added_count, last_item_name)
                    return StateMachineResult(
                        message=f"I've added {added_count} more {last_item_name}. Anything else?",
                        order=order,
                    )
            else:
                logger.info("'Make it N' requested but no items in cart")
                return StateMachineResult(
                    message="There's nothing in your order yet. What can I get for you?",
                    order=order,
                )

        # Handle repeat order request
        if parsed.wants_repeat_order:
            def set_repeat_info(is_repeat: bool, last_order_type: str | None) -> None:
                self._is_repeat_order = is_repeat
                self._last_order_type = last_order_type
                self.checkout_utils_handler.set_repeat_order_info(is_repeat, last_order_type)
            return self.confirmation_handler.handle_repeat_order(
                order,
                returning_customer=self._returning_customer,
                set_repeat_info_callback=set_repeat_info,
            )

        # Check if user specified order type upfront (e.g., "I'd like to place a pickup order")
        if parsed.order_type:
            order.delivery_method.order_type = parsed.order_type
            logger.info("Order type set from upfront mention: %s", parsed.order_type)
            order_type_display = "pickup" if parsed.order_type == "pickup" else "delivery"
            # Check if they also ordered items in the same message
            has_items = (parsed.new_bagel or parsed.new_coffee or parsed.new_menu_item or
                        parsed.new_speed_menu_bagel or parsed.new_side_item or parsed.by_pound_items)
            if not has_items:
                # Just the order type, no items yet - acknowledge and ask what they want
                return StateMachineResult(
                    message=f"Great, I'll set this up for {order_type_display}. What can I get for you?",
                    order=order,
                )
            # If they also ordered items, continue processing below

        # Track items added for multi-item orders
        items_added = []
        last_result = None

        # Helper to build confirmation message (normal vs replacement)
        def make_confirmation(item_name: str) -> str:
            if replaced_item_name:
                return f"Sure, I've changed that to {item_name}. Anything else?"
            return f"Got it, {item_name}. Anything else?"

        if parsed.new_menu_item:
            # Check if this "menu item" is actually a coffee/beverage that was misparsed
            menu_item_lower = parsed.new_menu_item.lower()
            coffee_beverage_types = {
                "coffee", "latte", "cappuccino", "espresso", "americano", "macchiato",
                "mocha", "cold brew", "tea", "chai", "matcha", "hot chocolate",
                "iced coffee", "iced latte", "iced cappuccino", "iced americano",
            }
            if menu_item_lower in coffee_beverage_types or any(bev in menu_item_lower for bev in coffee_beverage_types):
                # Redirect to coffee handling
                # Extract coffee modifiers deterministically from raw input since LLM may have missed them
                coffee_mods = ExtractedCoffeeModifiers()
                if raw_user_input:
                    coffee_mods = extract_coffee_modifiers_from_input(raw_user_input)
                    logger.info("Extracted coffee modifiers from raw input: sweetener=%s (qty=%d), syrup=%s",
                               coffee_mods.sweetener, coffee_mods.sweetener_quantity, coffee_mods.flavor_syrup)

                # Use LLM-parsed values if available, otherwise use deterministically extracted values
                sweetener = parsed.new_coffee_sweetener or coffee_mods.sweetener
                sweetener_qty = parsed.new_coffee_sweetener_quantity if parsed.new_coffee_sweetener else coffee_mods.sweetener_quantity
                flavor_syrup = parsed.new_coffee_flavor_syrup or coffee_mods.flavor_syrup

                logger.info("Redirecting misparsed menu item '%s' to coffee handler (sweetener=%s, qty=%d, syrup=%s)",
                           parsed.new_menu_item, sweetener, sweetener_qty, flavor_syrup)
                last_result = self.coffee_handler.add_coffee(
                    parsed.new_menu_item,  # Use as coffee type
                    parsed.new_coffee_size,
                    parsed.new_coffee_iced,
                    parsed.new_coffee_milk,
                    sweetener,
                    sweetener_qty,
                    flavor_syrup,
                    parsed.new_menu_item_quantity,
                    order,
                    notes=parsed.new_coffee_notes,
                )
                items_added.append(parsed.new_menu_item)
            else:
                last_result = self.item_adder_handler.add_menu_item(parsed.new_menu_item, parsed.new_menu_item_quantity, order, parsed.new_menu_item_toasted, parsed.new_menu_item_bagel_choice, parsed.new_menu_item_modifications)
                items_added.append(parsed.new_menu_item)
                # If there's also a side item, add it too
                if parsed.new_side_item:
                    side_name, side_error = self.item_adder_handler.add_side_item(parsed.new_side_item, parsed.new_side_item_quantity, order)
                    if side_name:
                        items_added.append(side_name)
                    elif side_error:
                        # Side item not found - return error with main item still added
                        return StateMachineResult(
                            message=f"I've added {parsed.new_menu_item} to your order. {side_error}",
                            order=order,
                        )

            # Add any additional menu items (from multi-item orders like "A Lexington and a BLT")
            if parsed.additional_menu_items:
                # Save whether primary item needs configuration BEFORE adding additional items
                primary_item_needs_config = order.is_configuring_item()
                primary_item_result = last_result
                saved_pending_item_id = order.pending_item_id
                saved_pending_field = order.pending_field
                saved_phase = order.phase

                for extra_item in parsed.additional_menu_items:
                    extra_result = self.item_adder_handler.add_menu_item(
                        extra_item.name,
                        extra_item.quantity,
                        order,
                        extra_item.toasted,
                        extra_item.bagel_choice,
                        extra_item.modifications,
                    )
                    items_added.append(extra_item.name)
                    logger.info("Multi-item order: added additional menu item '%s' (qty=%d)",
                                extra_item.name, extra_item.quantity)
                    # Use the last result to capture any configuration questions
                    if extra_result:
                        last_result = extra_result

                # If primary item needs configuration (e.g., spread sandwich toasted question),
                # ask primary item questions first (additional items were still added to cart)
                if primary_item_needs_config:
                    # Restore pending state for primary item
                    order.pending_item_id = saved_pending_item_id
                    order.pending_field = saved_pending_field
                    order.phase = saved_phase
                    logger.info("Multi-item order: primary item needs config, returning config question")
                    # Build combined confirmation with all items, then ask config question
                    combined_items = ", ".join(items_added)
                    config_question = primary_item_result.message if primary_item_result else "Would you like that toasted?"
                    return StateMachineResult(
                        message=f"Got it, {combined_items}. {config_question}",
                        order=order,
                    )

            # Check if there's ALSO a bagel order in the same message
            if parsed.new_bagel:
                # Save whether menu item needs configuration BEFORE adding bagel
                menu_item_needs_config = order.is_configuring_item()
                menu_item_result = last_result

                # Save pending state - _add_bagel may change it
                saved_pending_item_id = order.pending_item_id
                saved_pending_field = order.pending_field
                saved_phase = order.phase

                # Extract modifiers from raw input for bagel
                bagel_extracted_modifiers = None
                if raw_user_input:
                    bagel_extracted_modifiers = extract_modifiers_from_input(raw_user_input)

                # Add bagel(s) using _add_bagels for quantity support
                bagel_result = self.item_adder_handler.add_bagels(
                    quantity=parsed.new_bagel_quantity,
                    bagel_type=parsed.new_bagel_type,
                    toasted=parsed.new_bagel_toasted,
                    spread=parsed.new_bagel_spread,
                    spread_type=parsed.new_bagel_spread_type,
                    order=order,
                    extracted_modifiers=bagel_extracted_modifiers,
                )
                bagel_desc = f"{parsed.new_bagel_quantity} bagel{'s' if parsed.new_bagel_quantity > 1 else ''}"
                items_added.append(bagel_desc)
                logger.info("Multi-item order: added bagel (type=%s, qty=%d)", parsed.new_bagel_type, parsed.new_bagel_quantity)

                # If menu item needs configuration (e.g., spread sandwich toasted question),
                # ask menu item questions first (bagels were still added to cart)
                if menu_item_needs_config:
                    # Queue bagel for configuration after menu item is done
                    for item in order.items.items:
                        if isinstance(item, BagelItemTask) and item.status == TaskStatus.IN_PROGRESS:
                            order.queue_item_for_config(item.id, "bagel")
                            logger.info("Multi-item order: queued bagel %s for config after menu item", item.id[:8])

                    # Restore pending state
                    order.pending_item_id = saved_pending_item_id
                    order.pending_field = saved_pending_field
                    order.phase = saved_phase
                    logger.info("Multi-item order: menu item needs config, returning menu item config question")
                    return menu_item_result

                # If bagel needs configuration, ask bagel questions first
                if order.is_configuring_item():
                    # If menu item is in progress too, queue it for later
                    for item in order.items.items:
                        if isinstance(item, MenuItemTask) and item.status == TaskStatus.IN_PROGRESS:
                            order.queue_item_for_config(item.id, "menu_item")
                            logger.info("Multi-item order: queued menu item %s for config after bagel", item.id[:8])
                    logger.info("Multi-item order: bagel needs config, returning bagel config question")
                    return bagel_result

                # Neither needs config - combine the messages
                combined_items = ", ".join(items_added)
                last_result = StateMachineResult(
                    message=f"Got it, {combined_items}. Anything else?",
                    order=order,
                )

            # Check if there's ALSO a coffee order in the same message
            if parsed.new_coffee or parsed.coffee_details:
                # Save whether menu item needs configuration BEFORE adding coffee
                # (coffee might change pending_item_id)
                menu_item_needs_config = order.is_configuring_item()
                menu_item_result = last_result  # Save menu item's configuration result

                # Save pending state - _add_coffee may clear it for sodas
                saved_pending_item_id = order.pending_item_id
                saved_pending_field = order.pending_field
                saved_phase = order.phase

                # Add all coffees from coffee_details (or just the single one)
                coffee_result = None
                coffees_to_add = parsed.coffee_details if parsed.coffee_details else []
                if not coffees_to_add and parsed.new_coffee:
                    # Fallback to single coffee if no coffee_details
                    coffees_to_add = [CoffeeOrderDetails(
                        drink_type=parsed.new_coffee_type or "coffee",
                        size=parsed.new_coffee_size,
                        iced=parsed.new_coffee_iced,
                        quantity=parsed.new_coffee_quantity,
                    )]

                for coffee_detail in coffees_to_add:
                    # Use milk/notes from coffee_detail if available, otherwise fall back to parsed values
                    coffee_milk = coffee_detail.milk if coffee_detail.milk else parsed.new_coffee_milk
                    coffee_notes = coffee_detail.notes if coffee_detail.notes else parsed.new_coffee_notes
                    coffee_result = self.coffee_handler.add_coffee(
                        coffee_detail.drink_type,
                        coffee_detail.size,
                        coffee_detail.iced,
                        coffee_milk,
                        parsed.new_coffee_sweetener,  # Use shared sweetener
                        parsed.new_coffee_sweetener_quantity,
                        parsed.new_coffee_flavor_syrup,
                        coffee_detail.quantity,
                        order,
                        notes=coffee_notes,
                    )
                    items_added.append(coffee_detail.drink_type)
                    logger.info("Multi-item order: added coffee '%s' (qty=%d, milk=%s, notes=%s)", coffee_detail.drink_type, coffee_detail.quantity, coffee_milk, coffee_notes)

                # If menu item needs configuration (e.g., spread sandwich toasted question),
                # ask menu item questions first (coffees were still added to cart)
                if menu_item_needs_config:
                    # Check if coffees also need configuration (not sodas)
                    # If so, queue them for configuration after menu item is done
                    for item in order.items.items:
                        if isinstance(item, CoffeeItemTask) and item.status == TaskStatus.IN_PROGRESS:
                            order.queue_item_for_config(item.id, "coffee")
                            logger.info("Multi-item order: queued coffee %s for config after menu item", item.id[:8])

                    # Restore pending state that _add_coffee may have cleared
                    order.pending_item_id = saved_pending_item_id
                    order.pending_field = saved_pending_field
                    order.phase = saved_phase
                    logger.info("Multi-item order: menu item needs config, returning menu item config question")
                    return menu_item_result

                # If coffee needs configuration (not a soda), ask coffee questions
                if order.is_configuring_item():
                    logger.info("Multi-item order: coffee needs config, returning coffee config question")
                    return coffee_result

                # Neither needs config - combine the messages
                if last_result and coffee_result:
                    combined_items = ", ".join(items_added)
                    last_result = StateMachineResult(
                        message=f"Got it, {combined_items}. Anything else?",
                        order=order,
                    )

            if last_result:
                # If this was a replacement, modify the message
                if replaced_item_name and "Got it" in last_result.message:
                    last_result = StateMachineResult(
                        message=last_result.message.replace("Got it", "Sure, I've changed that to").rstrip(". Anything else?") + ". Anything else?",
                        order=last_result.order,
                    )
                return last_result

        if parsed.new_side_item and not parsed.new_bagel:
            # Standalone side item order (no bagel)
            return self.item_adder_handler.add_side_item_with_response(parsed.new_side_item, parsed.new_side_item_quantity, order)

        if parsed.new_bagel:
            # Check if we have multiple bagels with different configs
            if parsed.bagel_details and len(parsed.bagel_details) > 0:
                # Multiple bagels with different configurations
                # Pass extracted_modifiers to apply to the first bagel
                result = self.item_adder_handler.add_bagels_from_details(
                    parsed.bagel_details, order, extracted_modifiers
                )
            elif parsed.new_bagel_quantity > 1:
                # Multiple bagels with same (or no) configuration
                # Pass extracted_modifiers to apply to the first bagel
                result = self.item_adder_handler.add_bagels(
                    quantity=parsed.new_bagel_quantity,
                    bagel_type=parsed.new_bagel_type,
                    toasted=parsed.new_bagel_toasted,
                    spread=parsed.new_bagel_spread,
                    spread_type=parsed.new_bagel_spread_type,
                    order=order,
                    extracted_modifiers=extracted_modifiers,
                )
            else:
                # Single bagel
                result = self.item_adder_handler.add_bagel(
                    bagel_type=parsed.new_bagel_type,
                    toasted=parsed.new_bagel_toasted,
                    spread=parsed.new_bagel_spread,
                    spread_type=parsed.new_bagel_spread_type,
                    order=order,
                    extracted_modifiers=extracted_modifiers,
                )
            # If there's also a side item, add it too
            side_name = None
            side_error = None
            if parsed.new_side_item:
                side_name, side_error = self.item_adder_handler.add_side_item(parsed.new_side_item, parsed.new_side_item_quantity, order)

            # Check if there's ALSO a coffee in the same message
            if parsed.new_coffee or parsed.coffee_details:
                # Save whether bagel needs configuration BEFORE adding coffee
                # (coffee might change pending_item_id)
                bagel_needs_config = order.is_configuring_item()
                bagel_result = result  # Save bagel's configuration result

                # Save pending state - _add_coffee may clear it for sodas
                saved_pending_item_id = order.pending_item_id
                saved_pending_field = order.pending_field
                saved_phase = order.phase

                # Add all coffees from coffee_details (or just the single one)
                coffee_result = None
                coffees_to_add = parsed.coffee_details if parsed.coffee_details else []
                if not coffees_to_add and parsed.new_coffee:
                    # Fallback to single coffee if no coffee_details
                    coffees_to_add = [CoffeeOrderDetails(
                        drink_type=parsed.new_coffee_type or "coffee",
                        size=parsed.new_coffee_size,
                        iced=parsed.new_coffee_iced,
                        quantity=parsed.new_coffee_quantity,
                    )]

                for coffee_detail in coffees_to_add:
                    # Use milk/notes from coffee_detail if available, otherwise fall back to parsed values
                    coffee_milk = coffee_detail.milk if coffee_detail.milk else parsed.new_coffee_milk
                    coffee_notes = coffee_detail.notes if coffee_detail.notes else parsed.new_coffee_notes
                    coffee_result = self.coffee_handler.add_coffee(
                        coffee_detail.drink_type,
                        coffee_detail.size,
                        coffee_detail.iced,
                        coffee_milk,
                        parsed.new_coffee_sweetener,  # Use shared sweetener
                        parsed.new_coffee_sweetener_quantity,
                        parsed.new_coffee_flavor_syrup,
                        coffee_detail.quantity,
                        order,
                        notes=coffee_notes,
                    )
                    logger.info("Multi-item order: added coffee '%s' (qty=%d, milk=%s, notes=%s)", coffee_detail.drink_type, coffee_detail.quantity, coffee_milk, coffee_notes)

                # If bagel needs configuration, ask bagel questions first
                # (coffees were still added to cart, we'll configure them after bagel)
                if bagel_needs_config:
                    # Check if coffees also need configuration (not sodas)
                    # If so, queue them for configuration after bagel is done
                    for item in order.items.items:
                        if isinstance(item, CoffeeItemTask) and item.status == TaskStatus.IN_PROGRESS:
                            order.queue_item_for_config(item.id, "coffee")
                            logger.info("Multi-item order: queued coffee %s for config after bagel", item.id[:8])

                    # Restore pending state that _add_coffee may have cleared
                    order.pending_item_id = saved_pending_item_id
                    order.pending_field = saved_pending_field
                    order.phase = saved_phase
                    logger.info("Multi-item order: bagel needs config, returning bagel config question")
                    return bagel_result

                # If coffee needs configuration (not a soda), ask coffee questions
                # Check if coffee set up pending configuration
                if order.is_configuring_item():
                    logger.info("Multi-item order: coffee needs config, returning coffee config question")
                    return coffee_result

                # Neither needs config - return combined confirmation
                bagel_desc = f"{parsed.new_bagel_quantity} bagel{'s' if parsed.new_bagel_quantity > 1 else ''}"
                coffee_descs = [c.drink_type for c in coffees_to_add] if coffees_to_add else [parsed.new_coffee_type or "drink"]
                items_list = [bagel_desc]
                if side_name:
                    items_list.append(side_name)
                items_list.extend(coffee_descs)
                combined_items = ", ".join(items_list)
                # If side item was requested but not found, report the error
                if side_error:
                    return StateMachineResult(
                        message=f"Got it, {combined_items}. {side_error}",
                        order=order,
                    )
                return StateMachineResult(
                    message=f"Got it, {combined_items}. Anything else?",
                    order=order,
                )

            # If there's a side item but no coffee, update the result message to include it
            if side_name:
                bagel_desc = f"{parsed.new_bagel_quantity} bagel{'s' if parsed.new_bagel_quantity > 1 else ''}"
                return StateMachineResult(
                    message=f"Got it, {bagel_desc} and {side_name}. Anything else?",
                    order=order,
                )
            # If side item was requested but not found, report the error while keeping the bagel
            if side_error:
                return StateMachineResult(
                    message=side_error,
                    order=order,
                )
            return result

        if parsed.new_coffee or parsed.coffee_details:
            # Handle multiple coffees from coffee_details, or fall back to single coffee
            coffees_to_add = parsed.coffee_details if parsed.coffee_details else []
            if not coffees_to_add and parsed.new_coffee:
                # Fallback to single coffee if no coffee_details
                coffees_to_add = [CoffeeOrderDetails(
                    drink_type=parsed.new_coffee_type or "coffee",
                    size=parsed.new_coffee_size,
                    iced=parsed.new_coffee_iced,
                    quantity=parsed.new_coffee_quantity,
                    milk=parsed.new_coffee_milk,
                    notes=parsed.new_coffee_notes,
                )]

            coffee_result = None
            for coffee_detail in coffees_to_add:
                logger.info(
                    "PARSED COFFEE: type=%s, size=%s, QUANTITY=%d",
                    coffee_detail.drink_type, coffee_detail.size, coffee_detail.quantity or 1
                )
                # Use milk/notes from coffee_detail if available, otherwise fall back to parsed values
                coffee_milk = coffee_detail.milk if coffee_detail.milk else parsed.new_coffee_milk
                coffee_notes = coffee_detail.notes if coffee_detail.notes else parsed.new_coffee_notes
                coffee_result = self.coffee_handler.add_coffee(
                    coffee_detail.drink_type,
                    coffee_detail.size,
                    coffee_detail.iced,
                    coffee_milk,
                    parsed.new_coffee_sweetener,
                    parsed.new_coffee_sweetener_quantity,
                    parsed.new_coffee_flavor_syrup,
                    coffee_detail.quantity or 1,
                    order,
                    notes=coffee_notes,
                )
                items_added.append(coffee_detail.drink_type or "drink")

            # Check if there's ALSO a menu item in the same message
            if parsed.new_menu_item:
                menu_result = self.item_adder_handler.add_menu_item(parsed.new_menu_item, parsed.new_menu_item_quantity, order, parsed.new_menu_item_toasted, parsed.new_menu_item_bagel_choice, parsed.new_menu_item_modifications)
                items_added.append(parsed.new_menu_item)
                # Combine the messages
                combined_items = ", ".join(items_added)
                return StateMachineResult(
                    message=f"Got it, {combined_items}. Anything else?",
                    order=order,
                )
            # If this was a replacement, modify the message
            if replaced_item_name and coffee_result and "Got it" in coffee_result.message:
                coffee_result = StateMachineResult(
                    message=coffee_result.message.replace("Got it", "Sure, I've changed that to"),
                    order=coffee_result.order,
                )
            return coffee_result

        if parsed.new_speed_menu_bagel:
            speed_result = self.speed_menu_handler.add_speed_menu_bagel(
                parsed.new_speed_menu_bagel_name,
                parsed.new_speed_menu_bagel_quantity,
                parsed.new_speed_menu_bagel_toasted,
                order,
                bagel_choice=parsed.new_speed_menu_bagel_bagel_choice,
                modifications=parsed.new_speed_menu_bagel_modifications,
            )
            items_added.append(parsed.new_speed_menu_bagel_name)

            # Check if there's ALSO a coffee in the same message
            if parsed.new_coffee:
                coffee_result = self.coffee_handler.add_coffee(
                    parsed.new_coffee_type,
                    parsed.new_coffee_size,
                    parsed.new_coffee_iced,
                    parsed.new_coffee_milk,
                    parsed.new_coffee_sweetener,
                    parsed.new_coffee_sweetener_quantity,
                    parsed.new_coffee_flavor_syrup,
                    parsed.new_coffee_quantity,
                    order,
                    notes=parsed.new_coffee_notes,
                )
                items_added.append(parsed.new_coffee_type or "drink")
                # Combine the messages
                combined_items = ", ".join(items_added)
                return StateMachineResult(
                    message=f"Got it, {combined_items}. Anything else?",
                    order=order,
                )
            return speed_result

        if parsed.needs_soda_clarification:
            return self.menu_inquiry_handler.handle_soda_clarification(order)

        # Handle price inquiries for specific items
        if parsed.asks_about_price and parsed.price_query_item:
            return self.menu_inquiry_handler.handle_price_inquiry(parsed.price_query_item, order)

        # Handle store info inquiries
        if parsed.asks_store_hours:
            return self.store_info_handler.handle_store_hours_inquiry(order)

        if parsed.asks_store_location:
            return self.store_info_handler.handle_store_location_inquiry(order)

        if parsed.asks_delivery_zone:
            return self.store_info_handler.handle_delivery_zone_inquiry(parsed.delivery_zone_query, order)

        if parsed.asks_recommendation:
            return self.store_info_handler.handle_recommendation_inquiry(parsed.recommendation_category, order)

        if parsed.asks_item_description:
            return self.menu_inquiry_handler.handle_item_description_inquiry(parsed.item_description_query, order)

        if parsed.menu_query:
            return self.menu_inquiry_handler.handle_menu_query(parsed.menu_query_type, order, show_prices=parsed.asks_about_price)

        if parsed.asking_signature_menu:
            return self.menu_inquiry_handler.handle_signature_menu_inquiry(parsed.signature_menu_type, order)

        if parsed.asking_by_pound:
            return self.by_pound_handler.handle_by_pound_inquiry(parsed.by_pound_category, order)

        if parsed.by_pound_items:
            return self.by_pound_handler.add_by_pound_items(parsed.by_pound_items, order)

        if parsed.unclear or parsed.is_greeting:
            return StateMachineResult(
                message="What can I get for you?",
                order=order,
            )

        return StateMachineResult(
            message="I didn't catch that. What would you like to order?",
            order=order,
        )

    def _handle_configuring_item(
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

        # Handle category inquiry follow-up ("Would you like to hear what X we have?" -> "yes")
        if order.pending_field == "category_inquiry":
            return self.by_pound_handler.handle_category_inquiry_response(user_input, order)

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

        # Route to field-specific handler
        if order.pending_field == "side_choice":
            return self.config_helper_handler.handle_side_choice(user_input, item, order)
        elif order.pending_field == "bagel_choice":
            return self.bagel_handler.handle_bagel_choice(user_input, item, order)
        elif order.pending_field == "spread":
            return self.bagel_handler.handle_spread_choice(user_input, item, order)
        elif order.pending_field == "toasted":
            return self.bagel_handler.handle_toasted_choice(user_input, item, order)
        elif order.pending_field == "cheese_choice":
            return self.bagel_handler.handle_cheese_choice(user_input, item, order)
        elif order.pending_field == "coffee_size":
            return self.coffee_handler.handle_coffee_size(user_input, item, order)
        elif order.pending_field == "coffee_style":
            return self.coffee_handler.handle_coffee_style(user_input, item, order)
        elif order.pending_field == "speed_menu_bagel_toasted":
            return self.speed_menu_handler.handle_speed_menu_bagel_toasted(user_input, item, order)
        elif order.pending_field == "spread_sandwich_toasted":
            return self.bagel_handler.handle_toasted_choice(user_input, item, order)
        else:
            order.clear_pending()
            return self.checkout_utils_handler.get_next_question(order)

    def _handle_confirmation(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle order confirmation."""
        logger.info("CONFIRMATION: handling input '%s', current items: %s",
                   user_input[:50], [i.get_summary() for i in order.items.items])

        # Check for tax question first (deterministic pattern match)
        if TAX_QUESTION_PATTERN.search(user_input):
            logger.info("CONFIRMATION: Tax question detected")
            return self.order_utils_handler.handle_tax_question(order)

        # Check for quantity change patterns (e.g., "make it two orange juices")
        quantity_result = self.order_utils_handler.handle_quantity_change(user_input, order)
        if quantity_result:
            return quantity_result

        # Check for "make it 2" pattern (duplicate last item) - deterministic, no LLM needed
        from .parsers.deterministic import MAKE_IT_N_PATTERN
        make_it_n_match = MAKE_IT_N_PATTERN.match(user_input.strip())
        if make_it_n_match:
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
                        added_count = target_qty - 1

                        for _ in range(added_count):
                            new_item = last_item.model_copy(deep=True)
                            new_item.id = str(uuid.uuid4())
                            new_item.mark_complete()
                            order.items.add_item(new_item)

                        logger.info("CONFIRMATION: Added %d more of '%s'", added_count, last_item_name)

                        # Return to confirmation with updated summary
                        summary = self.checkout_utils_handler.build_order_summary(order)
                        if added_count == 1:
                            return StateMachineResult(
                                message=f"I've added a second {last_item_name}.\n\n{summary}\n\nDoes that look right?",
                                order=order,
                            )
                        else:
                            return StateMachineResult(
                                message=f"I've added {added_count} more {last_item_name}.\n\n{summary}\n\nDoes that look right?",
                                order=order,
                            )

        parsed = parse_confirmation(user_input, model=self.model)
        logger.info("CONFIRMATION: parse result - wants_changes=%s, confirmed=%s, asks_about_tax=%s",
                   parsed.wants_changes, parsed.confirmed, parsed.asks_about_tax)

        # Handle tax question from LLM parse as fallback
        if parsed.asks_about_tax:
            logger.info("CONFIRMATION: Tax question detected (LLM)")
            return self.order_utils_handler.handle_tax_question(order)

        if parsed.wants_changes:
            # User wants to make changes - reset order_reviewed so orchestrator knows
            order.checkout.order_reviewed = False

            # Try to parse the input for new items
            # e.g., "can I also get a coke?" should add the coke
            item_parsed = parse_open_input(user_input, model=self.model, spread_types=self._spread_types)
            logger.info("CONFIRMATION: parse_open_input result - new_menu_item=%s, new_bagel=%s, new_coffee=%s, new_coffee_type=%s, new_speed_menu_bagel=%s",
                       item_parsed.new_menu_item, item_parsed.new_bagel, item_parsed.new_coffee, item_parsed.new_coffee_type, item_parsed.new_speed_menu_bagel)

            # If they mentioned a new item, process it
            if item_parsed.new_menu_item or item_parsed.new_bagel or item_parsed.new_coffee or item_parsed.new_speed_menu_bagel:
                logger.info("CONFIRMATION: Detected new item! Processing via _handle_taking_items_with_parsed")
                extracted_modifiers = extract_modifiers_from_input(user_input)
                # Use orchestrator to determine phase before processing
                self._transition_to_next_slot(order)
                result = self._handle_taking_items_with_parsed(item_parsed, order, extracted_modifiers, user_input)

                # Log items in result.order vs original order
                logger.info("CONFIRMATION: result.order items = %s", [i.get_summary() for i in result.order.items.items])
                logger.info("CONFIRMATION: original order items = %s", [i.get_summary() for i in order.items.items])
                logger.info("CONFIRMATION: result.order.phase = %s", result.order.phase)

                # If there are pending drink options awaiting clarification, return that result
                # Don't override the clarification message with order summary
                if result.order.pending_drink_options:
                    logger.info("CONFIRMATION: Pending drink options, returning clarification message")
                    return result

                # Use orchestrator to determine if we should go back to confirmation
                # If all items complete and we have name and delivery, orchestrator will say ORDER_CONFIRM
                orchestrator = SlotOrchestrator(result.order)
                next_slot = orchestrator.get_next_slot()

                if (next_slot and next_slot.category == SlotCategory.ORDER_CONFIRM and
                    result.order.customer_info.name and
                    result.order.delivery_method.order_type):
                    logger.info("CONFIRMATION: Item added, returning to confirmation (orchestrator says ORDER_CONFIRM)")
                    self._transition_to_next_slot(result.order)
                    summary = self.checkout_utils_handler.build_order_summary(result.order)
                    logger.info("CONFIRMATION: Built summary, items count = %d", len(result.order.items.items))
                    return StateMachineResult(
                        message=f"{summary}\n\nDoes that look right?",
                        order=result.order,
                    )

                return result

            # No new item detected, use orchestrator to determine phase
            self._transition_to_next_slot(order)
            return StateMachineResult(
                message="No problem. What would you like to change?",
                order=order,
            )

        if parsed.confirmed:
            # Mark order as reviewed but not yet fully confirmed
            # (confirmed=True is set only when order is complete with email/text choice)
            order.checkout.order_reviewed = True

            # For returning customers, auto-send to their last used contact method
            returning_customer = getattr(self, "_returning_customer", None)
            if returning_customer:
                # Prefer email if available, otherwise use phone
                email = returning_customer.get("email") or order.customer_info.email
                phone = returning_customer.get("phone") or order.customer_info.phone

                if email:
                    # Auto-send to email
                    order.payment.method = "card_link"
                    order.customer_info.email = email
                    order.payment.payment_link_destination = email
                    order.checkout.generate_order_number()
                    order.checkout.confirmed = True
                    self._transition_to_next_slot(order)
                    return StateMachineResult(
                        message=f"An email with a payment link has been sent to {email}. "
                               f"Your order number is {order.checkout.short_order_number}. "
                               f"Thank you, {order.customer_info.name}!",
                        order=order,
                        is_complete=True,
                    )
                elif phone:
                    # Auto-send to phone
                    order.payment.method = "card_link"
                    order.customer_info.phone = phone
                    order.payment.payment_link_destination = phone
                    order.checkout.generate_order_number()
                    order.checkout.confirmed = True
                    self._transition_to_next_slot(order)
                    return StateMachineResult(
                        message=f"A text with a payment link has been sent to {phone}. "
                               f"Your order number is {order.checkout.short_order_number}. "
                               f"Thank you, {order.customer_info.name}!",
                        order=order,
                        is_complete=True,
                    )

            # Use orchestrator to determine next phase (should be PAYMENT_METHOD)
            self._transition_to_next_slot(order)
            return StateMachineResult(
                message="Would you like your order details sent by text or email?",
                order=order,
            )

        return StateMachineResult(
            message="Does the order look correct?",
            order=order,
        )

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _handle_repeat_order(self, order: OrderTask) -> StateMachineResult:
        """
        Handle a request to repeat the customer's previous order.

        Copies items from returning_customer.last_order_items to the current order.
        """
        returning_customer = getattr(self, "_returning_customer", None)

        if not returning_customer:
            logger.info("Repeat order requested but no returning customer data")
            return StateMachineResult(
                message="I don't have a previous order on file for you. What can I get for you today?",
                order=order,
            )

        last_order_items = returning_customer.get("last_order_items", [])
        if not last_order_items:
            logger.info("Repeat order requested but no last_order_items in returning_customer")
            return StateMachineResult(
                message="I don't have a previous order on file for you. What can I get for you today?",
                order=order,
            )

        # Helper to convert quantity to words for natural speech
        def quantity_to_words(n: int) -> str:
            words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
                     6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}
            return words.get(n, str(n))

        # Copy items from previous order
        items_added = []
        for prev_item in last_order_items:
            item_type = prev_item.get("item_type", "sandwich")
            menu_item_name = prev_item.get("menu_item_name")
            quantity = prev_item.get("quantity", 1)
            qty_word = quantity_to_words(quantity)

            # Add each item based on type
            if item_type == "bagel":
                bagel_type = prev_item.get("bread")
                toasted = prev_item.get("toasted")
                spread = prev_item.get("spread")
                spread_type = prev_item.get("spread_type")
                price = prev_item.get("price", 0)

                bagel = BagelItemTask(
                    bagel_type=bagel_type,
                    toasted=toasted,
                    spread=spread,
                    spread_type=spread_type,
                    unit_price=price,
                )
                bagel.status = TaskStatus.COMPLETE
                for _ in range(quantity):
                    order.items.add_item(bagel)

                # Build descriptive name with modifiers
                desc_parts = [bagel_type or "bagel"]
                if toasted is True:
                    desc_parts.append("toasted")
                if spread:
                    desc_parts.append(f"with {spread}")
                items_added.append(f"{qty_word} {' '.join(desc_parts)}")

            elif item_type in ("coffee", "drink"):
                # Handle both coffee and drink item types
                drink_type = prev_item.get("coffee_type") or prev_item.get("drink_type") or menu_item_name

                # Convert style ("iced"/"hot") to iced boolean
                # item_config stores style as string, but CoffeeItemTask uses iced as bool
                style = prev_item.get("style")
                if style == "iced":
                    iced = True
                elif style == "hot":
                    iced = False
                else:
                    iced = prev_item.get("iced")  # Fallback to direct iced field

                size = prev_item.get("size")
                milk = prev_item.get("milk")
                sweetener = prev_item.get("sweetener")
                flavor_syrup = prev_item.get("flavor_syrup")
                price = prev_item.get("price", 0)

                coffee = CoffeeItemTask(
                    drink_type=drink_type,
                    size=size,
                    iced=iced,
                    milk=milk,
                    sweetener=sweetener,
                    sweetener_quantity=prev_item.get("sweetener_quantity", 1),
                    flavor_syrup=flavor_syrup,
                    unit_price=price,
                )
                coffee.status = TaskStatus.COMPLETE
                for _ in range(quantity):
                    order.items.add_item(coffee)

                # Build descriptive name with modifiers
                desc_parts = []
                if size:
                    desc_parts.append(size)
                if iced is True:
                    desc_parts.append("iced")
                elif iced is False:
                    desc_parts.append("hot")
                desc_parts.append(drink_type or "coffee")
                if milk:
                    desc_parts.append(f"with {milk} milk")
                if flavor_syrup:
                    desc_parts.append(f"with {flavor_syrup}")

                items_added.append(f"{qty_word} {' '.join(desc_parts)}")

            elif menu_item_name:
                # Generic menu item (sandwich, omelette, etc.)
                price = prev_item.get("price", 0)
                item = MenuItemTask(
                    menu_item_name=menu_item_name,
                    unit_price=price,
                )
                item.status = TaskStatus.COMPLETE
                for _ in range(quantity):
                    order.items.add_item(item)
                items_added.append(f"{qty_word} {menu_item_name}")

        # Copy customer info if available (name, phone, email)
        if returning_customer.get("name") and not order.customer_info.name:
            order.customer_info.name = returning_customer["name"]
        if returning_customer.get("phone") and not order.customer_info.phone:
            order.customer_info.phone = returning_customer["phone"]
        if returning_customer.get("email") and not order.customer_info.email:
            order.customer_info.email = returning_customer["email"]

        # Store last order type for "pickup again?" / "delivery again?" prompt
        # Only used when this is actually a repeat order
        if returning_customer.get("last_order_type"):
            self._last_order_type = returning_customer["last_order_type"]
            self._is_repeat_order = True
            # Update checkout utils handler with repeat order info
            self.checkout_utils_handler.set_repeat_order_info(
                is_repeat=True,
                last_order_type=self._last_order_type,
            )

        logger.info("Repeat order: added %d item types from previous order", len(items_added))

        # Build confirmation message
        if items_added:
            items_str = ", ".join(items_added)
            order.phase = OrderPhase.TAKING_ITEMS.value
            return StateMachineResult(
                message=f"Got it, I've added your previous order: {items_str}. Anything else?",
                order=order,
            )
        else:
            return StateMachineResult(
                message="I couldn't find any items in your previous order. What can I get for you today?",
                order=order,
            )

    # NOTE: Item adding methods (_add_menu_item, _add_side_item, _add_bagel, etc.)
    # have been extracted to item_adder_handler.py


    def _get_ordinal(self, n: int) -> str:
        """Convert number to ordinal (1 -> 'first', 2 -> 'second', etc.)."""
        ordinals = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}
        return ordinals.get(n, f"#{n}")

    # =========================================================================
    # NOTE: By-the-Pound handlers have been extracted to by_pound_handler.py
    # NOTE: Menu Query, Price Inquiry, Item Description, and Signature Menu
    # handlers have been extracted to menu_inquiry_handler.py
    # NOTE: Drink selection handler has been extracted to coffee_config_handler.py
    # NOTE: Checkout utilities (_get_next_question, _transition_to_checkout,
    # _build_order_summary, etc.) have been extracted to checkout_utils_handler.py
    # =========================================================================


