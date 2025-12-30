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
from typing import Any, Literal, Union
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
from ..address_service import complete_address, AddressCompletionResult

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
    parse_delivery_choice,
    parse_name,
    parse_confirmation,
    parse_payment_method,
    parse_email,
    parse_phone,
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


def apply_modifiers_to_bagel(
    item: "BagelItemTask",
    modifiers: "ExtractedModifiers",
    skip_cheeses: bool = False,
) -> None:
    """
    Apply extracted modifiers to a bagel item.

    This consolidates the repeated modifier application logic used in
    multiple handlers (_handle_bagel_choice, _handle_toasted_choice, etc.).

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
    if not skip_cheeses and modifiers.cheeses:
        item.extras.extend(modifiers.cheeses)

    # Toppings go to extras
    if modifiers.toppings:
        item.extras.extend(modifiers.toppings)

    # Spreads: set if not already set
    if modifiers.spreads and not item.spread:
        item.spread = modifiers.spreads[0]

    # Append notes
    if modifiers.has_notes():
        existing_notes = item.notes or ""
        new_notes = modifiers.get_notes_string()
        item.notes = f"{existing_notes}, {new_notes}".strip(", ") if existing_notes else new_notes

    # Check if user said generic "cheese" without specifying type
    if modifiers.needs_cheese_clarification:
        item.needs_cheese_clarification = True


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
            result = self._handle_order_status(order)
            order.add_message("assistant", result.message)
            return result

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
            result = self._handle_delivery(user_input, order)
        elif order.phase == OrderPhase.CHECKOUT_NAME.value:
            result = self._handle_name(user_input, order)
        elif order.phase == OrderPhase.CHECKOUT_CONFIRM.value:
            result = self._handle_confirmation(user_input, order)
        elif order.phase == OrderPhase.CHECKOUT_PAYMENT_METHOD.value:
            result = self._handle_payment_method(user_input, order)
        elif order.phase == OrderPhase.CHECKOUT_PHONE.value:
            result = self._handle_phone(user_input, order)
        elif order.phase == OrderPhase.CHECKOUT_EMAIL.value:
            result = self._handle_email(user_input, order)
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
            return self._transition_to_checkout(order)

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
                        self.recalculate_bagel_price(last_item)

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
                # Find the item to cancel by matching the description
                item_to_remove = None
                item_index = None
                for item in reversed(active_items):  # Search from most recent
                    item_summary = item.get_summary().lower()
                    item_name = getattr(item, 'menu_item_name', '') or ''
                    item_name_lower = item_name.lower()
                    # Match if the cancel description appears in the item summary or name
                    if (cancel_item_desc in item_summary or
                        cancel_item_desc in item_name_lower or
                        item_name_lower in cancel_item_desc or
                        # Also check for partial matches like "coke" matching "diet coke"
                        any(word in item_summary for word in cancel_item_desc.split())):
                        item_to_remove = item
                        item_index = order.items.items.index(item)
                        break

                if item_to_remove:
                    removed_name = item_to_remove.get_summary()
                    order.items.remove_item(item_index)
                    logger.info("Cancellation: removed item '%s' from cart", removed_name)
                    # Check if cart is now empty
                    remaining_items = order.items.get_active_items()
                    if remaining_items:
                        return StateMachineResult(
                            message=f"OK, I've removed the {removed_name}. Anything else?",
                            order=order,
                        )
                    else:
                        return StateMachineResult(
                            message=f"OK, I've removed the {removed_name}. What would you like to order?",
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
            return self._handle_repeat_order(order)

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
                last_result = self._add_coffee(
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
                last_result = self._add_menu_item(parsed.new_menu_item, parsed.new_menu_item_quantity, order, parsed.new_menu_item_toasted, parsed.new_menu_item_bagel_choice)
                items_added.append(parsed.new_menu_item)
                # If there's also a side item, add it too
                if parsed.new_side_item:
                    side_name, side_error = self._add_side_item(parsed.new_side_item, parsed.new_side_item_quantity, order)
                    if side_name:
                        items_added.append(side_name)
                    elif side_error:
                        # Side item not found - return error with main item still added
                        return StateMachineResult(
                            message=f"I've added {parsed.new_menu_item} to your order. {side_error}",
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
                bagel_result = self._add_bagels(
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
                    coffee_result = self._add_coffee(
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
            return self._add_side_item_with_response(parsed.new_side_item, parsed.new_side_item_quantity, order)

        if parsed.new_bagel:
            # Check if we have multiple bagels with different configs
            if parsed.bagel_details and len(parsed.bagel_details) > 0:
                # Multiple bagels with different configurations
                # Pass extracted_modifiers to apply to the first bagel
                result = self._add_bagels_from_details(
                    parsed.bagel_details, order, extracted_modifiers
                )
            elif parsed.new_bagel_quantity > 1:
                # Multiple bagels with same (or no) configuration
                # Pass extracted_modifiers to apply to the first bagel
                result = self._add_bagels(
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
                result = self._add_bagel(
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
                side_name, side_error = self._add_side_item(parsed.new_side_item, parsed.new_side_item_quantity, order)

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
                    coffee_result = self._add_coffee(
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

        if parsed.new_coffee:
            coffee_result = self._add_coffee(
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

            # Check if there's ALSO a menu item in the same message
            if parsed.new_menu_item:
                menu_result = self._add_menu_item(parsed.new_menu_item, parsed.new_menu_item_quantity, order, parsed.new_menu_item_toasted, parsed.new_menu_item_bagel_choice)
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
            speed_result = self._add_speed_menu_bagel(
                parsed.new_speed_menu_bagel_name,
                parsed.new_speed_menu_bagel_quantity,
                parsed.new_speed_menu_bagel_toasted,
                order,
                bagel_choice=parsed.new_speed_menu_bagel_bagel_choice,
            )
            items_added.append(parsed.new_speed_menu_bagel_name)

            # Check if there's ALSO a coffee in the same message
            if parsed.new_coffee:
                coffee_result = self._add_coffee(
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
            return self._handle_soda_clarification(order)

        # Handle price inquiries for specific items
        if parsed.asks_about_price and parsed.price_query_item:
            return self._handle_price_inquiry(parsed.price_query_item, order)

        # Handle store info inquiries
        if parsed.asks_store_hours:
            return self._handle_store_hours_inquiry(order)

        if parsed.asks_store_location:
            return self._handle_store_location_inquiry(order)

        if parsed.asks_delivery_zone:
            return self._handle_delivery_zone_inquiry(parsed.delivery_zone_query, order)

        if parsed.asks_recommendation:
            return self._handle_recommendation_inquiry(parsed.recommendation_category, order)

        if parsed.asks_item_description:
            return self._handle_item_description_inquiry(parsed.item_description_query, order)

        if parsed.menu_query:
            return self._handle_menu_query(parsed.menu_query_type, order, show_prices=parsed.asks_about_price)

        if parsed.asking_signature_menu:
            return self._handle_signature_menu_inquiry(parsed.signature_menu_type, order)

        if parsed.asking_by_pound:
            return self._handle_by_pound_inquiry(parsed.by_pound_category, order)

        if parsed.by_pound_items:
            return self._add_by_pound_items(parsed.by_pound_items, order)

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
            return self._handle_by_pound_category_selection(user_input, order)

        # Handle drink selection when multiple options were presented
        if order.pending_field == "drink_selection":
            return self._handle_drink_selection(user_input, order)

        item = self._get_item_by_id(order, order.pending_item_id)
        if item is None:
            order.clear_pending()
            return StateMachineResult(
                message="Something went wrong. What would you like to order?",
                order=order,
            )

        # Route to field-specific handler
        if order.pending_field == "side_choice":
            return self._handle_side_choice(user_input, item, order)
        elif order.pending_field == "bagel_choice":
            return self._handle_bagel_choice(user_input, item, order)
        elif order.pending_field == "spread":
            return self._handle_spread_choice(user_input, item, order)
        elif order.pending_field == "toasted":
            return self._handle_toasted_choice(user_input, item, order)
        elif order.pending_field == "cheese_choice":
            return self._handle_cheese_choice(user_input, item, order)
        elif order.pending_field == "coffee_size":
            return self._handle_coffee_size(user_input, item, order)
        elif order.pending_field == "coffee_style":
            return self._handle_coffee_style(user_input, item, order)
        elif order.pending_field == "speed_menu_bagel_toasted":
            return self._handle_speed_menu_bagel_toasted(user_input, item, order)
        elif order.pending_field == "spread_sandwich_toasted":
            return self._handle_toasted_choice(user_input, item, order)
        else:
            order.clear_pending()
            return self._get_next_question(order)

    def _handle_side_choice(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle side choice for omelette - uses constrained parser."""
        # "bagel" and "fruit salad" are valid answers, not new order attempts
        redirect = _check_redirect_to_pending_item(
            user_input, item, order, "Would you like a bagel or fruit salad with it?",
            valid_answers={"bagel", "fruit", "fruit salad"}
        )
        if redirect:
            return redirect

        # This parser can ONLY return side choice - no new items possible!
        parsed = parse_side_choice(user_input, item.menu_item_name, model=self.model)

        if parsed.wants_cancel:
            item.mark_skipped()
            order.clear_pending()
            order.phase = OrderPhase.TAKING_ITEMS.value
            return StateMachineResult(
                message="No problem, I've removed that. Anything else?",
                order=order,
            )

        if parsed.choice == "unclear":
            return StateMachineResult(
                message=f"Would you like a bagel or fruit salad with your {item.menu_item_name}?",
                order=order,
            )

        # Apply the choice
        item.side_choice = parsed.choice

        if parsed.choice == "bagel":
            if parsed.bagel_type:
                # User specified bagel type upfront (e.g., "plain bagel")
                item.bagel_choice = parsed.bagel_type
                order.clear_pending()
                item.mark_complete()
                return self._get_next_question(order)
            else:
                # Need to ask for bagel type
                order.pending_field = "bagel_choice"
                return StateMachineResult(
                    message="What kind of bagel would you like?",
                    order=order,
                )
        else:
            # Fruit salad - omelette is complete
            order.clear_pending()
            item.mark_complete()
            return self._get_next_question(order)

    def _handle_bagel_choice(
        self,
        user_input: str,
        item: ItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle bagel type selection for the CURRENT pending item only.

        This handles one item at a time. After configuring this item,
        _configure_next_incomplete_bagel will move to the next item.
        """
        # Try deterministic parsing first - check if input matches a known bagel type
        # Do this BEFORE redirect check so "do you have everything bagel" works
        input_lower = user_input.lower().strip()
        bagel_type = None

        # Check for exact match or "[type] bagel" pattern
        for bt in BAGEL_TYPES:
            if input_lower == bt or input_lower == f"{bt} bagel":
                bagel_type = bt
                break
            # Also check if type is contained in the input
            if bt in input_lower:
                bagel_type = bt
                break

        # If no bagel type found, check if user is trying to order a new item
        if not bagel_type:
            redirect = _check_redirect_to_pending_item(
                user_input, item, order, "What kind of bagel would you like?"
            )
            if redirect:
                return redirect

        # Fall back to LLM parser only if deterministic parsing failed
        if not bagel_type:
            parsed = parse_bagel_choice(user_input, num_pending_bagels=1, model=self.model)
            if not parsed.unclear and parsed.bagel_type:
                bagel_type = parsed.bagel_type

        if not bagel_type:
            return StateMachineResult(
                message="What kind of bagel? We have plain, everything, sesame, and more.",
                order=order,
            )

        logger.info("Parsed bagel type '%s' for item %s", bagel_type, type(item).__name__)

        # Extract any additional modifiers from the input (e.g., "plain with salt pepper and ketchup")
        extracted_modifiers = extract_modifiers_from_input(user_input)
        if extracted_modifiers.has_modifiers() or extracted_modifiers.has_notes():
            logger.info("Extracted additional modifiers from bagel choice: %s", extracted_modifiers)

        # Apply to the current pending item
        if isinstance(item, MenuItemTask):
            item.bagel_choice = bagel_type

            # For spread/salad sandwiches, use unified config flow for toasted question
            if item.menu_item_type in ("spread_sandwich", "salad_sandwich"):
                order.clear_pending()
                return self._configure_next_incomplete_bagel(order)

            # For omelettes with bagel side, use unified config flow for toasted/spread questions
            if item.side_choice == "bagel":
                order.clear_pending()
                return self._configure_next_incomplete_bagel(order)

            # For other menu items, mark complete
            item.mark_complete()
            order.clear_pending()
            return self._get_next_question(order)

        elif isinstance(item, BagelItemTask):
            item.bagel_type = bagel_type

            # Apply any additional modifiers from the input
            apply_modifiers_to_bagel(item, extracted_modifiers)

            self.recalculate_bagel_price(item)

            # Clear pending and configure next incomplete item
            order.clear_pending()
            return self._configure_next_incomplete_bagel(order)

        return self._get_next_question(order)

    def _handle_spread_choice(
        self,
        user_input: str,
        item: Union[BagelItemTask, MenuItemTask],
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle spread selection for bagel or omelette side bagel."""
        # For MenuItemTask (omelette side bagels), use simpler handling
        if isinstance(item, MenuItemTask):
            parsed = parse_spread_choice(user_input, model=self.model)

            if parsed.no_spread:
                item.spread = "none"
            elif parsed.spread:
                # Build spread description (e.g., "scallion cream cheese")
                if parsed.spread_type and parsed.spread_type != "plain":
                    item.spread = f"{parsed.spread_type} {parsed.spread}"
                else:
                    item.spread = parsed.spread

                # Add spread price to omelette (same as standalone bagel)
                spread_price = self._lookup_spread_price(parsed.spread, parsed.spread_type)
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
            return self._configure_next_incomplete_bagel(order)

        # For BagelItemTask - full handling with modifiers
        # First check if the user is requesting modifiers instead of a spread
        # e.g., "make it bacon egg and cheese" when asked about spread
        modifiers = extract_modifiers_from_input(user_input)
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
            # Standard spread choice parsing
            parsed = parse_spread_choice(user_input, model=self.model)

            if parsed.no_spread:
                item.spread = "none"  # Mark as explicitly no spread
            elif parsed.spread:
                item.spread = parsed.spread
                item.spread_type = parsed.spread_type
                # Capture special instructions like "a little", "extra", etc.
                if parsed.notes:
                    # Build full spread description for notes
                    spread_desc = parsed.spread
                    if parsed.spread_type and parsed.spread_type != "plain":
                        spread_desc = f"{parsed.spread_type} {parsed.spread}"
                    # Combine modifier with spread (e.g., "a little cream cheese")
                    item.notes = f"{parsed.notes} {spread_desc}"
            else:
                return StateMachineResult(
                    message="Would you like cream cheese, butter, or nothing on that?",
                    order=order,
                )

        # Recalculate price to include spread modifier
        self.recalculate_bagel_price(item)

        # This bagel is complete
        item.mark_complete()
        order.clear_pending()

        # Check for more incomplete bagels
        return self._configure_next_incomplete_bagel(order)

    def _handle_toasted_choice(
        self,
        user_input: str,
        item: Union[BagelItemTask, MenuItemTask],
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle toasted preference for bagel or sandwich."""
        redirect = _check_redirect_to_pending_item(
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
            return StateMachineResult(
                message="Would you like that toasted? Yes or no?",
                order=order,
            )

        item.toasted = toasted

        # Extract any additional modifiers from the input (e.g., "yes with extra cheese")
        if isinstance(item, BagelItemTask):
            extracted_modifiers = extract_modifiers_from_input(user_input)
            if extracted_modifiers.has_modifiers() or extracted_modifiers.has_notes():
                logger.info("Extracted additional modifiers from toasted choice: %s", extracted_modifiers)
                apply_modifiers_to_bagel(item, extracted_modifiers)

        # For MenuItemTask, handle based on type
        if isinstance(item, MenuItemTask):
            # For omelette side bagels, continue to spread question
            if item.side_choice == "bagel":
                order.clear_pending()
                return self._configure_next_incomplete_bagel(order)
            # For spread/salad sandwiches, mark complete after toasted
            item.mark_complete()
            order.clear_pending()
            return self._get_next_question(order)

        # For BagelItemTask, check if spread is already set or has sandwich toppings
        if item.spread is not None:
            # Spread already specified, bagel is complete
            self.recalculate_bagel_price(item)
            item.mark_complete()
            order.clear_pending()
            return self._configure_next_incomplete_bagel(order)

        # Skip spread question if bagel already has sandwich toppings (ham, egg, cheese, etc.)
        # But continue to cheese clarification if needed
        if item.extras or item.sandwich_protein:
            logger.info("Skipping spread question - bagel has toppings: extras=%s, protein=%s", item.extras, item.sandwich_protein)
            # If cheese clarification still needed, don't mark complete yet
            if not item.needs_cheese_clarification:
                self.recalculate_bagel_price(item)
                item.mark_complete()
            order.clear_pending()
            return self._configure_next_incomplete_bagel(order)

        # Move to spread question
        order.pending_field = "spread"
        return StateMachineResult(
            message="Would you like cream cheese or butter on that?",
            order=order,
        )

    def _handle_cheese_choice(
        self,
        user_input: str,
        item: BagelItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle cheese type selection when user said generic 'cheese'."""
        redirect = _check_redirect_to_pending_item(
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
            return StateMachineResult(
                message="What kind of cheese? We have American, cheddar, Swiss, and muenster.",
                order=order,
            )

        # Add the cheese to extras
        item.extras.append(selected_cheese)
        item.needs_cheese_clarification = False

        # Extract any additional modifiers from the input (e.g., "cheddar with extra bacon")
        extracted_modifiers = extract_modifiers_from_input(user_input)
        if extracted_modifiers.has_modifiers() or extracted_modifiers.has_notes():
            logger.info("Extracted additional modifiers from cheese choice: %s", extracted_modifiers)
            # Apply modifiers (skip cheeses since we already handled cheese above)
            apply_modifiers_to_bagel(item, extracted_modifiers, skip_cheeses=True)

        # Recalculate price with the new cheese
        self.recalculate_bagel_price(item)

        logger.info("Cheese choice '%s' applied to bagel", selected_cheese)

        # Clear pending and continue configuration
        order.clear_pending()
        return self._configure_next_incomplete_bagel(order)

    def _handle_delivery(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle pickup/delivery selection and address collection."""
        # Handle address confirmation for repeat orders
        if order.pending_field == "address_confirmation":
            lower_input = user_input.lower().strip()
            # Check for affirmative response
            if lower_input in ("yes", "yeah", "yep", "correct", "that's right", "thats right", "right", "yes please", "yea"):
                order.pending_field = None
                return self._proceed_after_address(order)
            # Check for negative response - ask for new address
            elif lower_input in ("no", "nope", "different address", "new address", "wrong", "not quite"):
                order.pending_field = None
                order.delivery_method.address.street = None
                return StateMachineResult(
                    message="What's the delivery address?",
                    order=order,
                )
            # Otherwise treat as a new address
            else:
                order.pending_field = None
                order.delivery_method.address.street = None
                # Fall through to parse as new address
                parsed = parse_delivery_choice(user_input, model=self.model)
                if parsed.address:
                    result = self._complete_delivery_address(parsed.address, order)
                    if result:
                        return result
                    return self._proceed_after_address(order)
                return StateMachineResult(
                    message="What's the delivery address?",
                    order=order,
                )

        parsed = parse_delivery_choice(user_input, model=self.model)

        if parsed.choice == "unclear":
            # Check if we're waiting for an address (delivery selected but no address yet)
            if order.delivery_method.order_type == "delivery" and not order.delivery_method.address.street:
                # Try to extract address from input
                if parsed.address:
                    # Complete and validate the delivery address
                    result = self._complete_delivery_address(parsed.address, order)
                    if result:
                        return result
                    # Address was set successfully, continue
                    return self._proceed_after_address(order)
                return StateMachineResult(
                    message="What's the delivery address?",
                    order=order,
                )
            return StateMachineResult(
                message=self._get_delivery_question(),
                order=order,
            )

        order.delivery_method.order_type = parsed.choice
        if parsed.address and parsed.choice == "delivery":
            # Complete and validate the delivery address
            result = self._complete_delivery_address(parsed.address, order)
            if result:
                # Clear order type if we got an error (not clarification)
                if not result.order.delivery_method.address.street:
                    order.delivery_method.order_type = None
                return result
        elif parsed.address:
            order.delivery_method.address.street = parsed.address

        # Use orchestrator to determine next phase
        # If delivery without address, orchestrator will keep us in delivery phase
        orchestrator = SlotOrchestrator(order)
        next_slot = orchestrator.get_next_slot()

        if next_slot and next_slot.category == SlotCategory.DELIVERY_ADDRESS:
            # Check for previous delivery address from repeat order
            returning_customer = getattr(self, "_returning_customer", None)
            is_repeat = getattr(self, "_is_repeat_order", False)
            if is_repeat and returning_customer:
                last_address = returning_customer.get("last_order_address")
                if last_address:
                    # Pre-fill the address and ask for confirmation
                    order.delivery_method.address.street = last_address
                    order.pending_field = "address_confirmation"
                    return StateMachineResult(
                        message=f"I have {last_address}. Is that correct?",
                        order=order,
                    )
            # Need to collect address fresh
            return StateMachineResult(
                message="What's the delivery address?",
                order=order,
            )

        # Transition to next slot - check if we already have name from returning customer
        return self._proceed_after_address(order)

    def _complete_delivery_address(
        self,
        partial_address: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """
        Complete and validate a delivery address using Nominatim.

        Returns:
            StateMachineResult if there's an error or need clarification,
            None if address was successfully set on the order.
        """
        allowed_zips = getattr(self, '_store_info', {}).get('delivery_zip_codes', [])

        # Use address completion service
        result = complete_address(partial_address, allowed_zips)

        if not result.success:
            # Error occurred - return error message
            return StateMachineResult(
                message=result.error_message or "I couldn't validate that address. Could you try again with the ZIP code?",
                order=order,
            )

        if result.needs_clarification and len(result.addresses) > 1:
            # Multiple matches with different ZIP codes - ask for ZIP to disambiguate
            zip_codes = [addr.zip_code for addr in result.addresses[:3]]
            message = f"I found that address in a few areas. What's the ZIP code? It should be one of: {', '.join(zip_codes)}"
            return StateMachineResult(
                message=message,
                order=order,
            )

        if result.single_match:
            # Single match - use the completed address
            completed = result.single_match
            order.delivery_method.address.street = completed.format_full()
            logger.info("Address completed: %s -> %s", partial_address, completed.format_short())
            return None  # Success - address set

        # Fallback: no matches
        return StateMachineResult(
            message="I couldn't find that address in our delivery area. Could you provide the full address with ZIP code?",
            order=order,
        )

    def _handle_name(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle customer name."""
        parsed = parse_name(user_input, model=self.model)

        if not parsed.name:
            return StateMachineResult(
                message="What name should I put on the order?",
                order=order,
            )

        order.customer_info.name = parsed.name
        self._transition_to_next_slot(order)

        # Build order summary
        summary = self._build_order_summary(order)
        return StateMachineResult(
            message=f"{summary}\n\nDoes that look right?",
            order=order,
        )

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
            return self._handle_tax_question(order)

        # Check for quantity change patterns (e.g., "make it two orange juices")
        quantity_result = self._handle_quantity_change(user_input, order)
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
                        summary = self._build_order_summary(order)
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
            return self._handle_tax_question(order)

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
                    summary = self._build_order_summary(result.order)
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

    def _handle_payment_method(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle text or email choice for order details."""
        parsed = parse_payment_method(user_input, model=self.model)

        if parsed.choice == "unclear":
            return StateMachineResult(
                message="Would you like your order confirmation sent by text message or email?",
                order=order,
            )

        if parsed.choice == "text":
            # Text selected - set payment method and check for phone
            order.payment.method = "card_link"
            phone = parsed.phone_number or order.customer_info.phone
            if phone:
                # Validate the phone number
                validated_phone, error_message = validate_phone_number(phone)
                if error_message:
                    logger.info("Phone validation failed for '%s': %s", phone, error_message)
                    # Ask for phone again with the error message
                    self._transition_to_next_slot(order)
                    return StateMachineResult(
                        message=error_message,
                        order=order,
                    )
                order.customer_info.phone = validated_phone
                order.payment.payment_link_destination = validated_phone
                order.checkout.generate_order_number()
                order.checkout.confirmed = True  # Now fully confirmed
                self._transition_to_next_slot(order)  # Should be COMPLETE
                return StateMachineResult(
                    message=f"Your order number is {order.checkout.short_order_number}. "
                           f"We'll text you when it's ready. Thank you, {order.customer_info.name}!",
                    order=order,
                    is_complete=True,
                )
            else:
                # Need to ask for phone number - orchestrator will say NOTIFICATION
                self._transition_to_next_slot(order)
                return StateMachineResult(
                    message="What phone number should I text the confirmation to?",
                    order=order,
                )

        if parsed.choice == "email":
            # Email selected - set payment method and check for email
            order.payment.method = "card_link"
            if parsed.email_address:
                # Validate the email address
                validated_email, error_message = validate_email_address(parsed.email_address)
                if error_message:
                    logger.info("Email validation failed for '%s': %s", parsed.email_address, error_message)
                    # Ask for email again with the error message
                    order.phase = OrderPhase.CHECKOUT_EMAIL.value
                    return StateMachineResult(
                        message=error_message,
                        order=order,
                    )
                order.customer_info.email = validated_email
                order.payment.payment_link_destination = validated_email
                order.checkout.generate_order_number()
                order.checkout.confirmed = True  # Now fully confirmed
                self._transition_to_next_slot(order)  # Should be COMPLETE
                return StateMachineResult(
                    message=f"Your order number is {order.checkout.short_order_number}. "
                           f"We'll send the confirmation to {validated_email}. "
                           f"Thank you, {order.customer_info.name}!",
                    order=order,
                    is_complete=True,
                )
            else:
                # Need to ask for email - explicitly set CHECKOUT_EMAIL phase
                # (orchestrator maps NOTIFICATION to CHECKOUT_PHONE by default)
                order.phase = OrderPhase.CHECKOUT_EMAIL.value
                return StateMachineResult(
                    message="What email address should I send it to?",
                    order=order,
                )

        return StateMachineResult(
            message="Would you like that sent by text or email?",
            order=order,
        )

    def _handle_phone(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle phone number collection for text confirmation."""
        parsed = parse_phone(user_input, model=self.model)

        if not parsed.phone:
            return StateMachineResult(
                message="What's the best phone number to text the order confirmation to?",
                order=order,
            )

        # Validate the phone number
        validated_phone, error_message = validate_phone_number(parsed.phone)
        if error_message:
            logger.info("Phone validation failed for '%s': %s", parsed.phone, error_message)
            return StateMachineResult(
                message=error_message,
                order=order,
            )

        # Store validated phone and complete the order
        order.customer_info.phone = validated_phone
        order.payment.payment_link_destination = validated_phone
        order.checkout.generate_order_number()
        order.checkout.confirmed = True  # Now fully confirmed
        self._transition_to_next_slot(order)  # Should be COMPLETE

        return StateMachineResult(
            message=f"Your order number is {order.checkout.short_order_number}. "
                   f"We'll text you when it's ready. Thank you, {order.customer_info.name}!",
            order=order,
            is_complete=True,
        )

    def _handle_email(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle email address collection."""
        parsed = parse_email(user_input, model=self.model)

        if not parsed.email:
            return StateMachineResult(
                message="What's the best email address to send the order confirmation to?",
                order=order,
            )

        # Validate the email address
        validated_email, error_message = validate_email_address(parsed.email)
        if error_message:
            logger.info("Email validation failed for '%s': %s", parsed.email, error_message)
            return StateMachineResult(
                message=error_message,
                order=order,
            )

        # Store validated/normalized email and complete the order
        order.customer_info.email = validated_email
        order.payment.payment_link_destination = validated_email
        order.checkout.generate_order_number()
        order.checkout.confirmed = True  # Now fully confirmed
        self._transition_to_next_slot(order)  # Should be COMPLETE

        return StateMachineResult(
            message=f"Your order number is {order.checkout.short_order_number}. "
                   f"We'll send the confirmation to {validated_email}. "
                   f"Thank you, {order.customer_info.name}!",
            order=order,
            is_complete=True,
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

    def _add_menu_item(
        self,
        item_name: str,
        quantity: int,
        order: OrderTask,
        toasted: bool | None = None,
        bagel_choice: str | None = None,
    ) -> StateMachineResult:
        """Add a menu item and determine next question."""
        # Ensure quantity is at least 1
        quantity = max(1, quantity)

        # Look up item in menu to get price and other details
        menu_item = self._lookup_menu_item(item_name)

        # Log omelette items in menu for debugging
        omelette_items = self.menu_data.get("items_by_type", {}).get("omelette", [])
        logger.info(
            "Menu lookup for '%s': found=%s, omelette_items=%s",
            item_name,
            menu_item is not None,
            [i.get("name") for i in omelette_items],
        )

        # If item not found in menu, provide helpful suggestions
        if not menu_item:
            logger.warning("Menu item not found: '%s' - suggesting alternatives", item_name)
            return StateMachineResult(
                message=self._get_not_found_message(item_name),
                order=order,
            )

        # Use the canonical name from menu if found
        canonical_name = menu_item.get("name", item_name)
        price = menu_item.get("base_price", 0.0)
        menu_item_id = menu_item.get("id")
        category = menu_item.get("item_type", "")  # item_type slug like "spread_sandwich"

        # Check if it's an omelette (requires side choice)
        is_omelette = "omelette" in canonical_name.lower() or "omelet" in canonical_name.lower()

        # Check if it's a spread or salad sandwich (requires toasted question)
        is_spread_or_salad_sandwich = category in ("spread_sandwich", "salad_sandwich")

        logger.info(
            "Menu item check: canonical_name='%s', category='%s', is_omelette=%s, is_spread_salad=%s, quantity=%d",
            canonical_name,
            category,
            is_omelette,
            is_spread_or_salad_sandwich,
            quantity,
        )

        # Determine the menu item type for tracking
        if is_omelette:
            item_type = "omelette"
        elif is_spread_or_salad_sandwich:
            item_type = category  # "spread_sandwich" or "salad_sandwich"
        else:
            item_type = None

        # Create the requested quantity of items
        first_item = None
        for i in range(quantity):
            item = MenuItemTask(
                menu_item_name=canonical_name,
                menu_item_id=menu_item_id,
                unit_price=price,
                requires_side_choice=is_omelette,
                menu_item_type=item_type,
                toasted=toasted,  # Set toasted if specified upfront
                bagel_choice=bagel_choice,  # Set bagel choice if specified upfront
            )
            item.mark_in_progress()
            order.items.add_item(item)
            if first_item is None:
                first_item = item

        logger.info("Added %d menu item(s): %s (price: $%.2f each, id: %s, toasted=%s, bagel=%s)", quantity, canonical_name, price, menu_item_id, toasted, bagel_choice)

        if is_omelette:
            # Set state to wait for side choice (applies to first item, others will be configured after)
            order.phase = OrderPhase.CONFIGURING_ITEM
            order.pending_item_id = first_item.id
            order.pending_field = "side_choice"
            return StateMachineResult(
                message=f"Would you like a bagel or fruit salad with your {canonical_name}?",
                order=order,
            )
        elif is_spread_or_salad_sandwich:
            # For spread/salad sandwiches, ask for bagel choice first, then toasted
            if bagel_choice and toasted is not None:
                # Both bagel and toasted specified - mark complete
                first_item.mark_complete()
                return self._get_next_question(order)
            else:
                # Use unified configuration flow (handles ordinals for multiple items)
                return self._configure_next_incomplete_bagel(order)
        else:
            # Mark all items complete (non-omelettes don't need configuration)
            for item in order.items.items:
                if item.menu_item_name == canonical_name and item.status == TaskStatus.IN_PROGRESS:
                    item.mark_complete()
            return self._get_next_question(order)

    def _add_side_item(
        self,
        side_item_name: str,
        quantity: int,
        order: OrderTask,
    ) -> tuple[str | None, str | None]:
        """Add a side item to the order without returning a response.

        Used when a side item is ordered alongside another item (e.g., "bagel with a side of sausage").

        Returns:
            Tuple of (canonical_name, error_message).
            If successful: (canonical_name, None)
            If item not found: (None, error_message)
        """
        quantity = max(1, quantity)

        # Look up the side item in the menu
        menu_item = self._lookup_menu_item(side_item_name)

        # If item not found, return error message
        if not menu_item:
            logger.warning("Side item not found: '%s' - rejecting", side_item_name)
            return (None, self._get_not_found_message(side_item_name))

        # Use canonical name and price from menu
        canonical_name = menu_item.get("name", side_item_name)
        price = menu_item.get("base_price", 0.0)
        menu_item_id = menu_item.get("id")

        # Create the side item(s)
        for _ in range(quantity):
            item = MenuItemTask(
                menu_item_name=canonical_name,
                menu_item_id=menu_item_id,
                unit_price=price,
                menu_item_type="side",
            )
            item.mark_complete()  # Side items don't need configuration
            order.items.add_item(item)

        logger.info("Added %d side item(s): %s (price: $%.2f each)", quantity, canonical_name, price)
        return (canonical_name, None)

    def _add_side_item_with_response(
        self,
        side_item_name: str,
        quantity: int,
        order: OrderTask,
    ) -> StateMachineResult:
        """Add a side item to the order and return an appropriate response.

        Used when a side item is ordered on its own (e.g., "I'll have a side of bacon").
        """
        canonical_name, error_message = self._add_side_item(side_item_name, quantity, order)

        # If item wasn't found, return the error message
        if error_message:
            return StateMachineResult(
                message=error_message,
                order=order,
            )

        # Pluralize if quantity > 1
        if quantity > 1:
            item_display = f"{quantity} {canonical_name}s"
        else:
            item_display = canonical_name

        order.phase = OrderPhase.TAKING_ITEMS.value
        return StateMachineResult(
            message=f"I've added {item_display} to your order. Anything else?",
            order=order,
        )

    def _add_bagel(
        self,
        bagel_type: str | None,
        order: OrderTask,
        toasted: bool | None = None,
        spread: str | None = None,
        spread_type: str | None = None,
        extracted_modifiers: ExtractedModifiers | None = None,
    ) -> StateMachineResult:
        """Add a bagel and start configuration, pre-filling any provided details."""
        # Look up base bagel price from menu
        base_price = self._lookup_bagel_price(bagel_type)

        # Build extras list from extracted modifiers
        extras: list[str] = []
        sandwich_protein: str | None = None

        if extracted_modifiers and extracted_modifiers.has_modifiers():
            # First protein goes to sandwich_protein field
            if extracted_modifiers.proteins:
                sandwich_protein = extracted_modifiers.proteins[0]
                # Additional proteins go to extras
                extras.extend(extracted_modifiers.proteins[1:])

            # Cheeses go to extras
            extras.extend(extracted_modifiers.cheeses)

            # Toppings go to extras
            extras.extend(extracted_modifiers.toppings)

            # If modifiers include a spread, use it (unless already specified)
            if not spread and extracted_modifiers.spreads:
                spread = extracted_modifiers.spreads[0]

            logger.info(
                "Extracted modifiers: protein=%s, extras=%s, spread=%s",
                sandwich_protein, extras, spread
            )

        # Calculate total price including modifiers
        price = self._calculate_bagel_price_with_modifiers(
            base_price, sandwich_protein, extras, spread, spread_type
        )
        logger.info(
            "Bagel price: base=$%.2f, total=$%.2f (with modifiers)",
            base_price, price
        )

        # Extract notes from modifiers
        notes: str | None = None
        if extracted_modifiers and extracted_modifiers.has_notes():
            notes = extracted_modifiers.get_notes_string()
            logger.info("Applying notes to bagel: %s", notes)

        # Check if bagel needs cheese clarification
        needs_cheese = False
        if extracted_modifiers and extracted_modifiers.needs_cheese_clarification:
            needs_cheese = True
            logger.info("Bagel needs cheese clarification (user said 'cheese' without type)")

        # Create bagel with all provided details
        bagel = BagelItemTask(
            bagel_type=bagel_type,
            toasted=toasted,
            spread=spread,
            spread_type=spread_type,
            sandwich_protein=sandwich_protein,
            extras=extras,
            unit_price=price,
            notes=notes,
            needs_cheese_clarification=needs_cheese,
        )
        bagel.mark_in_progress()
        order.items.add_item(bagel)

        logger.info(
            "Adding bagel: type=%s, toasted=%s, spread=%s, spread_type=%s, protein=%s, extras=%s, notes=%s",
            bagel_type, toasted, spread, spread_type, sandwich_protein, extras, notes
        )

        # Determine what question to ask based on what's missing
        # Flow: bagel_type -> toasted -> spread

        if not bagel_type:
            # Need bagel type
            order.phase = OrderPhase.CONFIGURING_ITEM
            order.pending_item_id = bagel.id
            order.pending_field = "bagel_choice"
            return StateMachineResult(
                message="What kind of bagel would you like?",
                order=order,
            )

        if toasted is None:
            # Need toasted preference
            order.phase = OrderPhase.CONFIGURING_ITEM
            order.pending_item_id = bagel.id
            order.pending_field = "toasted"
            return StateMachineResult(
                message="Would you like that toasted?",
                order=order,
            )

        # Check if user said "cheese" without specifying type
        if needs_cheese:
            order.phase = OrderPhase.CONFIGURING_ITEM
            order.pending_item_id = bagel.id
            order.pending_field = "cheese_choice"
            return StateMachineResult(
                message="What kind of cheese would you like? We have American, cheddar, Swiss, and muenster.",
                order=order,
            )

        if spread is None:
            # Skip spread question if bagel already has sandwich toppings (ham, egg, cheese, etc.)
            if extras or sandwich_protein:
                logger.info("Skipping spread question - bagel has toppings: extras=%s, protein=%s", extras, sandwich_protein)
            else:
                # Need spread choice
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = bagel.id
                order.pending_field = "spread"
                return StateMachineResult(
                    message="Would you like cream cheese or butter on that?",
                    order=order,
                )

        # All details provided - bagel is complete!
        bagel.mark_complete()
        return self._get_next_question(order)

    def _add_bagels(
        self,
        quantity: int,
        bagel_type: str | None,
        toasted: bool | None,
        spread: str | None,
        spread_type: str | None,
        order: OrderTask,
        extracted_modifiers: ExtractedModifiers | None = None,
    ) -> StateMachineResult:
        """
        Add multiple bagels with the same configuration.

        Creates all bagels upfront, then configures them one at a time.
        Extracted modifiers are applied to the first bagel.
        """
        logger.info(
            "Adding %d bagels: type=%s, toasted=%s, spread=%s, spread_type=%s",
            quantity, bagel_type, toasted, spread, spread_type
        )

        # Look up base bagel price from menu
        base_price = self._lookup_bagel_price(bagel_type)

        # Create all the bagels
        for i in range(quantity):
            # Build extras list from extracted modifiers (apply to first bagel only)
            extras: list[str] = []
            sandwich_protein: str | None = None
            bagel_spread = spread

            # Extract notes for first bagel
            notes: str | None = None

            if i == 0 and extracted_modifiers and extracted_modifiers.has_modifiers():
                # First protein goes to sandwich_protein field
                if extracted_modifiers.proteins:
                    sandwich_protein = extracted_modifiers.proteins[0]
                    # Additional proteins go to extras
                    extras.extend(extracted_modifiers.proteins[1:])

                # Cheeses go to extras
                extras.extend(extracted_modifiers.cheeses)

                # Toppings go to extras
                extras.extend(extracted_modifiers.toppings)

                # If modifiers include a spread, use it (unless already specified)
                if not bagel_spread and extracted_modifiers.spreads:
                    bagel_spread = extracted_modifiers.spreads[0]

                logger.info(
                    "Applying extracted modifiers to first bagel: protein=%s, extras=%s, spread=%s",
                    sandwich_protein, extras, bagel_spread
                )

            # Apply notes to first bagel
            if i == 0 and extracted_modifiers and extracted_modifiers.has_notes():
                notes = extracted_modifiers.get_notes_string()
                logger.info("Applying notes to first bagel: %s", notes)

            # Check if first bagel needs cheese clarification
            needs_cheese = False
            if i == 0 and extracted_modifiers and extracted_modifiers.needs_cheese_clarification:
                needs_cheese = True
                logger.info("Bagel needs cheese clarification (user said 'cheese' without type)")

            # Calculate total price including modifiers (for first bagel with modifiers)
            price = self._calculate_bagel_price_with_modifiers(
                base_price, sandwich_protein, extras, bagel_spread, spread_type
            )

            bagel = BagelItemTask(
                bagel_type=bagel_type,
                toasted=toasted,
                spread=bagel_spread,
                spread_type=spread_type,
                sandwich_protein=sandwich_protein,
                extras=extras,
                unit_price=price,
                notes=notes,
                needs_cheese_clarification=needs_cheese,
            )
            # Mark complete if all fields provided (and no cheese clarification needed), otherwise in_progress
            if bagel_type and toasted is not None and bagel_spread is not None and not needs_cheese:
                bagel.mark_complete()
            else:
                bagel.mark_in_progress()
            order.items.add_item(bagel)

        # Find first incomplete bagel and start configuring it
        return self._configure_next_incomplete_bagel(order)

    def _add_bagels_from_details(
        self,
        bagel_details: list[BagelOrderDetails],
        order: OrderTask,
        extracted_modifiers: ExtractedModifiers | None = None,
    ) -> StateMachineResult:
        """
        Add multiple bagels with different configurations.

        Creates all bagels upfront, then configures incomplete ones one at a time.
        Extracted modifiers are applied to the first bagel.
        """
        logger.info("Adding %d bagels from details", len(bagel_details))

        for i, details in enumerate(bagel_details):
            # Look up base price
            base_price = 2.50
            if details.bagel_type:
                bagel_name = f"{details.bagel_type.title()} Bagel" if "bagel" not in details.bagel_type.lower() else details.bagel_type
                menu_item = self._lookup_menu_item(bagel_name)
                if menu_item:
                    base_price = menu_item.get("base_price", 2.50)

            # Build extras list from extracted modifiers (apply to first bagel only)
            extras: list[str] = []
            sandwich_protein: str | None = None
            spread = details.spread

            # Extract notes for first bagel
            notes: str | None = None

            if i == 0 and extracted_modifiers and extracted_modifiers.has_modifiers():
                # First protein goes to sandwich_protein field
                if extracted_modifiers.proteins:
                    sandwich_protein = extracted_modifiers.proteins[0]
                    # Additional proteins go to extras
                    extras.extend(extracted_modifiers.proteins[1:])

                # Cheeses go to extras
                extras.extend(extracted_modifiers.cheeses)

                # Toppings go to extras
                extras.extend(extracted_modifiers.toppings)

                # If modifiers include a spread, use it (unless already specified)
                if not spread and extracted_modifiers.spreads:
                    spread = extracted_modifiers.spreads[0]

                logger.info(
                    "Applying extracted modifiers to first bagel: protein=%s, extras=%s, spread=%s",
                    sandwich_protein, extras, spread
                )

            # Apply notes to first bagel
            if i == 0 and extracted_modifiers and extracted_modifiers.has_notes():
                notes = extracted_modifiers.get_notes_string()
                logger.info("Applying notes to first bagel: %s", notes)

            # Check if first bagel needs cheese clarification
            needs_cheese = False
            if i == 0 and extracted_modifiers and extracted_modifiers.needs_cheese_clarification:
                needs_cheese = True
                logger.info("Bagel needs cheese clarification (user said 'cheese' without type)")

            # Calculate total price including modifiers
            price = self._calculate_bagel_price_with_modifiers(
                base_price, sandwich_protein, extras, spread, details.spread_type
            )

            bagel = BagelItemTask(
                bagel_type=details.bagel_type,
                toasted=details.toasted,
                spread=spread,
                spread_type=details.spread_type,
                sandwich_protein=sandwich_protein,
                extras=extras,
                unit_price=price,
                notes=notes,
                needs_cheese_clarification=needs_cheese,
            )

            # Mark complete if all fields provided (and no cheese clarification needed)
            if details.bagel_type and details.toasted is not None and details.spread is not None and not needs_cheese:
                bagel.mark_complete()
            else:
                bagel.mark_in_progress()

            order.items.add_item(bagel)

            logger.info(
                "Bagel %d: type=%s, toasted=%s, spread=%s (status=%s)",
                i + 1, details.bagel_type, details.toasted, details.spread,
                bagel.status.value
            )

        # Find first incomplete bagel and start configuring it
        return self._configure_next_incomplete_bagel(order)

    def _get_bagel_descriptions(self, order: OrderTask, bagel_ids: list[str]) -> list[str]:
        """Get descriptions for a list of bagel IDs (e.g., ['plain bagel', 'everything bagel'])."""
        descriptions = []
        for bagel_id in bagel_ids:
            bagel = self._get_item_by_id(order, bagel_id)
            if bagel and isinstance(bagel, BagelItemTask):
                if bagel.bagel_type:
                    descriptions.append(f"{bagel.bagel_type} bagel")
                else:
                    descriptions.append("bagel")
        return descriptions

    def _configure_next_incomplete_bagel(
        self,
        order: OrderTask,
    ) -> StateMachineResult:
        """
        Find the next incomplete bagel item and configure it fully before moving on.

        This handles:
        - BagelItemTask (bagels with spreads/toppings)
        - MenuItemTask for spread_sandwich/salad_sandwich (Butter Sandwich, etc.)
        - MenuItemTask for omelettes with side_choice == "bagel"

        Each item is fully configured (type → toasted → spread) before
        moving to the next item.
        """
        # Collect all items that need bagel configuration (both types)
        all_bagel_items = []
        for item in order.items.items:
            if isinstance(item, BagelItemTask):
                all_bagel_items.append(item)
            elif isinstance(item, MenuItemTask) and item.menu_item_type in ("spread_sandwich", "salad_sandwich"):
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
                ordinal = self._get_ordinal(item_num)
                bagel_desc = f"the {ordinal} bagel"
                your_bagel_desc = f"your {ordinal} bagel"
            else:
                bagel_desc = "your bagel"
                your_bagel_desc = "your bagel"

            # Handle MenuItemTask (spread_sandwich, salad_sandwich, omelette with bagel side)
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

                # Then ask about toasted
                if item.toasted is None:
                    order.phase = OrderPhase.CONFIGURING_ITEM
                    order.pending_item_id = item.id
                    order.pending_field = "toasted"
                    if is_omelette_side:
                        return StateMachineResult(
                            message=f"Would you like the {item.bagel_choice} bagel toasted?",
                            order=order,
                        )
                    elif total_items > 1:
                        return StateMachineResult(
                            message=f"For {bagel_desc}, would you like that toasted?",
                            order=order,
                        )
                    else:
                        return StateMachineResult(
                            message="Would you like that toasted?",
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

                # MenuItemTask is complete
                item.mark_complete()
                continue

            # Handle BagelItemTask
            bagel = item

            # Ask about type first
            if not bagel.bagel_type:
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = bagel.id
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

            # Then ask about toasted
            if bagel.toasted is None:
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = bagel.id
                order.pending_field = "toasted"
                if total_items > 1:
                    return StateMachineResult(
                        message=f"For {bagel_desc}, would you like that toasted?",
                        order=order,
                    )
                else:
                    return StateMachineResult(
                        message="Would you like that toasted?",
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
            if bagel.spread is None and not bagel.extras and not bagel.sandwich_protein:
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = bagel.id
                order.pending_field = "spread"
                if total_items > 1:
                    return StateMachineResult(
                        message=f"For {bagel_desc}, would you like cream cheese or butter?",
                        order=order,
                    )
                else:
                    return StateMachineResult(
                        message="Would you like cream cheese or butter on that?",
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
            if order.has_queued_config_items():
                next_config = order.pop_next_config_item()
                if next_config:
                    item_id = next_config.get("item_id")
                    item_type = next_config.get("item_type")
                    logger.info("Bagel complete, processing queued config item: id=%s, type=%s", item_id[:8] if item_id else None, item_type)

                    # Find the item by ID and start its configuration
                    for item in order.items.items:
                        if item.id == item_id:
                            if item_type == "coffee" and isinstance(item, CoffeeItemTask):
                                return self._configure_next_incomplete_coffee(order)

            # Explicitly set to TAKING_ITEMS - we're asking for more items
            order.phase = OrderPhase.TAKING_ITEMS.value
            return StateMachineResult(
                message=f"Got it, {summary}. Anything else?",
                order=order,
            )

        # Fallback to generic next question
        return self._get_next_question(order)

    def _get_ordinal(self, n: int) -> str:
        """Convert number to ordinal (1 -> 'first', 2 -> 'second', etc.)."""
        ordinals = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}
        return ordinals.get(n, f"#{n}")

    def _add_coffee(
        self,
        coffee_type: str | None,
        size: str | None,
        iced: bool | None,
        milk: str | None,
        sweetener: str | None,
        sweetener_quantity: int,
        flavor_syrup: str | None,
        quantity: int,
        order: OrderTask,
        notes: str | None = None,
    ) -> StateMachineResult:
        """Add coffee/drink(s) and start configuration flow if needed."""
        logger.info(
            "ADD COFFEE: type=%s, size=%s, iced=%s, sweetener=%s (qty=%d), syrup=%s, notes=%s",
            coffee_type, size, iced, sweetener, sweetener_quantity, flavor_syrup, notes
        )
        # Ensure quantity is at least 1
        quantity = max(1, quantity)

        # Check for multiple matching items - ask user to clarify if ambiguous
        if coffee_type:
            matching_items = self._lookup_menu_items(coffee_type)
            if len(matching_items) > 1:
                # Before asking for clarification, check if user already has a matching
                # drink in their cart - if so, add another of the same type
                coffee_type_lower = coffee_type.lower()
                for cart_item in order.items.items:
                    # Use drink_type for CoffeeItemTask, get_display_name() for others
                    if hasattr(cart_item, 'drink_type') and cart_item.drink_type:
                        cart_name = cart_item.drink_type.lower()
                    elif hasattr(cart_item, 'get_display_name'):
                        cart_name = cart_item.get_display_name().lower()
                    else:
                        continue
                    # Check if any matching item matches something in the cart
                    for match_item in matching_items:
                        match_name = match_item.get("name", "").lower()
                        if cart_name == match_name or match_name in cart_name or cart_name in match_name:
                            logger.info(
                                "ADD COFFEE: User already has '%s' in cart, adding another",
                                match_item.get("name")
                            )
                            # Use the exact menu item name
                            coffee_type = match_item.get("name")
                            matching_items = []  # Clear to skip clarification
                            break
                    if not matching_items:
                        break

            if len(matching_items) > 1:
                # Multiple matches - need to ask user which one they want
                logger.info(
                    "ADD COFFEE: Multiple matches for '%s': %s",
                    coffee_type,
                    [item.get("name") for item in matching_items]
                )
                # Store the options and pending state
                order.pending_drink_options = matching_items
                order.pending_field = "drink_selection"
                order.phase = OrderPhase.CONFIGURING_ITEM.value

                # Build the clarification message
                option_list = []
                for i, item in enumerate(matching_items, 1):
                    name = item.get("name", "Unknown")
                    price = item.get("base_price", 0)
                    if price > 0:
                        option_list.append(f"{i}. {name} (${price:.2f})")
                    else:
                        option_list.append(f"{i}. {name}")

                options_str = "\n".join(option_list)
                return StateMachineResult(
                    message=f"We have a few options for {coffee_type}:\n{options_str}\nWhich would you like?",
                    order=order,
                )

        # Look up item from menu to get price and skip_config flag
        menu_item = self._lookup_menu_item(coffee_type) if coffee_type else None
        price = menu_item.get("base_price", 2.50) if menu_item else self._lookup_coffee_price(coffee_type)

        # Check if this drink should skip configuration questions
        # Coffee beverages (cappuccino, latte, etc.) ALWAYS need configuration regardless of database flag
        # This overrides the menu_item skip_config because item_type "beverage" has skip_config=1
        # but that's intended for sodas/bottled drinks, not coffee drinks
        coffee_type_lower = (coffee_type or "").lower()
        is_configurable_coffee = coffee_type_lower in COFFEE_BEVERAGE_TYPES or any(
            bev in coffee_type_lower for bev in COFFEE_BEVERAGE_TYPES
        )

        should_skip_config = False
        if is_configurable_coffee:
            # Coffee/tea drinks always need size and hot/iced configuration
            logger.info("ADD COFFEE: skip_config=False (configurable coffee beverage: %s)", coffee_type)
            should_skip_config = False
        elif menu_item and menu_item.get("skip_config"):
            logger.info("ADD COFFEE: skip_config=True (from menu_item)")
            should_skip_config = True
        elif is_soda_drink(coffee_type):
            # Fallback for items not in database
            logger.info("ADD COFFEE: skip_config=True (soda drink)")
            should_skip_config = True
        else:
            logger.info("ADD COFFEE: skip_config=False, will need configuration")

        if should_skip_config:
            # This drink doesn't need size or hot/iced questions - add directly as complete
            # Create the requested quantity of drinks
            for _ in range(quantity):
                drink = CoffeeItemTask(
                    drink_type=coffee_type,
                    size=None,  # No size options for skip_config drinks
                    iced=None,  # No hot/iced label needed for sodas/bottled drinks
                    milk=None,
                    sweetener=None,
                    sweetener_quantity=0,
                    flavor_syrup=None,
                    unit_price=price,
                    notes=notes,
                )
                drink.mark_complete()  # No configuration needed
                order.items.add_item(drink)

            # Return to taking items
            order.clear_pending()
            return self._get_next_question(order)

        # Regular coffee/tea - needs configuration
        # Create the requested quantity of drinks
        for _ in range(quantity):
            coffee = CoffeeItemTask(
                drink_type=coffee_type or "coffee",
                size=size,
                iced=iced,
                milk=milk,
                sweetener=sweetener,
                sweetener_quantity=sweetener_quantity,
                flavor_syrup=flavor_syrup,
                unit_price=price,
                notes=notes,
            )
            coffee.mark_in_progress()
            order.items.add_item(coffee)

        # Start configuration flow
        return self._configure_next_incomplete_coffee(order)

    def _configure_next_incomplete_coffee(
        self,
        order: OrderTask,
    ) -> StateMachineResult:
        """Configure the next incomplete coffee item."""
        # Find all coffee items (both complete and incomplete) to determine total count
        all_coffees = [
            item for item in order.items.items
            if isinstance(item, CoffeeItemTask)
        ]
        total_coffees = len(all_coffees)

        logger.info(
            "CONFIGURE COFFEE: Found %d total coffee items (total items: %d)",
            total_coffees, len(order.items.items)
        )

        # Configure coffees one at a time (fully configure each before moving to next)
        for coffee in all_coffees:
            if coffee.status != TaskStatus.IN_PROGRESS:
                continue

            logger.info(
                "CONFIGURE COFFEE: Checking coffee id=%s, size=%s, iced=%s, status=%s",
                coffee.id, coffee.size, coffee.iced, coffee.status
            )

            # Get drink name for the question
            drink_name = coffee.drink_type or "coffee"

            # Ask about size first
            if not coffee.size:
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = coffee.id
                order.pending_field = "coffee_size"
                message = f"What size would you like for the {drink_name}? Small, medium, or large?"
                return StateMachineResult(
                    message=message,
                    order=order,
                )

            # Then ask about hot/iced
            if coffee.iced is None:
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = coffee.id
                order.pending_field = "coffee_style"
                return StateMachineResult(
                    message="Would you like that hot or iced?",
                    order=order,
                )

            # This coffee is complete - recalculate price with modifiers
            self.recalculate_coffee_price(coffee)
            coffee.mark_complete()

        # All coffees configured - no incomplete ones found
        logger.info("CONFIGURE COFFEE: No incomplete coffees, going to next question")
        order.clear_pending()
        return self._get_next_question(order)

    def _handle_coffee_size(
        self,
        user_input: str,
        item: CoffeeItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle coffee size selection."""
        redirect = _check_redirect_to_pending_item(
            user_input, item, order, "What size would you like? Small, medium, or large?"
        )
        if redirect:
            return redirect

        parsed = parse_coffee_size(user_input, model=self.model)

        if not parsed.size:
            drink_name = item.drink_type or "drink"
            return StateMachineResult(
                message=f"What size would you like for your {drink_name}? Small, medium, or large?",
                order=order,
            )

        item.size = parsed.size

        # Move to hot/iced question
        order.pending_field = "coffee_style"
        return StateMachineResult(
            message="Would you like that hot or iced?",
            order=order,
        )

    def _handle_coffee_style(
        self,
        user_input: str,
        item: CoffeeItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle hot/iced preference for coffee."""
        redirect = _check_redirect_to_pending_item(
            user_input, item, order, "Would you like it hot or iced?"
        )
        if redirect:
            return redirect

        # Try deterministic parsing first for hot/iced, fall back to LLM
        iced = parse_hot_iced_deterministic(user_input)
        if iced is None:
            parsed = parse_coffee_style(user_input, model=self.model)
            iced = parsed.iced

        if iced is None:
            return StateMachineResult(
                message="Would you like that hot or iced?",
                order=order,
            )

        item.iced = iced

        # Also extract any sweetener/syrup mentioned with the hot/iced response
        # e.g., "hot with 2 splenda" or "iced with vanilla"
        coffee_mods = extract_coffee_modifiers_from_input(user_input)
        if coffee_mods.sweetener and not item.sweetener:
            item.sweetener = coffee_mods.sweetener
            item.sweetener_quantity = coffee_mods.sweetener_quantity
            logger.info(f"Extracted sweetener from style response: {coffee_mods.sweetener_quantity} {coffee_mods.sweetener}")
        if coffee_mods.flavor_syrup and not item.flavor_syrup:
            item.flavor_syrup = coffee_mods.flavor_syrup
            logger.info(f"Extracted syrup from style response: {coffee_mods.flavor_syrup}")

        # Coffee is now complete - recalculate price with modifiers
        self.recalculate_coffee_price(item)
        item.mark_complete()
        order.clear_pending()

        # Check for more incomplete coffees before moving on
        return self._configure_next_incomplete_coffee(order)

    def _lookup_coffee_price(self, coffee_type: str | None) -> float:
        """Look up price for a coffee type."""
        if not coffee_type:
            return 2.50  # Default drip coffee price

        # Look up from menu
        menu_item = self._lookup_menu_item(coffee_type)
        if menu_item:
            return menu_item.get("base_price", 2.50)

        # Default prices by type
        coffee_type_lower = coffee_type.lower()
        if "latte" in coffee_type_lower or "cappuccino" in coffee_type_lower:
            return 4.50
        if "espresso" in coffee_type_lower:
            return 3.00

        return 2.50  # Default

    # =========================================================================
    # Speed Menu Bagel Handlers
    # =========================================================================

    def _add_speed_menu_bagel(
        self,
        item_name: str | None,
        quantity: int,
        toasted: bool | None,
        order: OrderTask,
        bagel_choice: str | None = None,
    ) -> StateMachineResult:
        """Add speed menu bagel(s) to the order."""
        if not item_name:
            return StateMachineResult(
                message="Which speed menu item would you like?",
                order=order,
            )

        # Ensure quantity is at least 1
        quantity = max(1, quantity)

        # Look up item from menu to get price
        menu_item = self._lookup_menu_item(item_name)
        price = menu_item.get("base_price", 10.00) if menu_item else 10.00
        menu_item_id = menu_item.get("id") if menu_item else None

        # Create the requested quantity of items
        for _ in range(quantity):
            item = SpeedMenuBagelItemTask(
                menu_item_name=item_name,
                menu_item_id=menu_item_id,
                toasted=toasted,
                bagel_choice=bagel_choice,
                unit_price=price,
            )
            if toasted is not None:
                # Toasted preference already specified - mark complete
                item.mark_complete()
            else:
                # Need to ask about toasting
                item.mark_in_progress()
            order.items.add_item(item)

        # If toasted was specified, we're done
        if toasted is not None:
            order.clear_pending()
            return self._get_next_question(order)

        # Need to configure toasted preference
        return self._configure_next_incomplete_speed_menu_bagel(order)

    def _configure_next_incomplete_speed_menu_bagel(
        self,
        order: OrderTask,
    ) -> StateMachineResult:
        """Configure the next incomplete speed menu bagel item."""
        # Find incomplete speed menu bagel items
        incomplete_items = [
            item for item in order.items.items
            if isinstance(item, SpeedMenuBagelItemTask) and item.status == TaskStatus.IN_PROGRESS
        ]

        if not incomplete_items:
            order.clear_pending()
            return self._get_next_question(order)

        # Configure items one at a time
        for item in incomplete_items:
            if item.toasted is None:
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = item.id
                order.pending_field = "speed_menu_bagel_toasted"
                return StateMachineResult(
                    message="Would you like that toasted?",
                    order=order,
                )

            # This item is complete
            item.mark_complete()

        # All items configured
        order.clear_pending()
        return self._get_next_question(order)

    def _handle_speed_menu_bagel_toasted(
        self,
        user_input: str,
        item: SpeedMenuBagelItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle toasted preference for speed menu bagel."""
        # Try deterministic parsing first, fall back to LLM
        toasted = parse_toasted_deterministic(user_input)
        if toasted is None:
            parsed = parse_toasted_choice(user_input, model=self.model)
            toasted = parsed.toasted

        if toasted is None:
            return StateMachineResult(
                message="Would you like that toasted?",
                order=order,
            )

        item.toasted = toasted
        item.mark_complete()
        order.clear_pending()

        return self._get_next_question(order)

    # =========================================================================
    # Menu Query Handlers
    # =========================================================================

    def _handle_menu_query(
        self,
        menu_query_type: str | None,
        order: OrderTask,
        show_prices: bool = False,
    ) -> StateMachineResult:
        """Handle inquiry about menu items by type.

        Args:
            menu_query_type: Type of item being queried (e.g., 'beverage', 'bagel', 'sandwich')
            show_prices: If True, include prices in the listing (for price inquiries)
        """
        items_by_type = self.menu_data.get("items_by_type", {}) if self.menu_data else {}

        if not menu_query_type:
            # Generic "what do you have?" - list available types
            available_types = [t.replace("_", " ") for t, items in items_by_type.items() if items]
            if available_types:
                return StateMachineResult(
                    message=f"We have: {', '.join(available_types)}. What would you like?",
                    order=order,
                )
            return StateMachineResult(
                message="What can I get for you?",
                order=order,
            )

        # Handle spread/cream cheese queries as by-the-pound category
        if menu_query_type in ("spread", "cream_cheese", "cream cheese"):
            return self._list_by_pound_category("spread", order)

        # Map common query types to actual item_type slugs
        # - "soda", "water", "juice" -> "beverage" (cold-only drinks)
        # - "coffee", "tea", "latte" -> "sized_beverage" (hot/iced drinks)
        # - "beverage", "drink" -> combine both types
        type_aliases = {
            "coffee": "sized_beverage",
            "tea": "sized_beverage",
            "latte": "sized_beverage",
            "espresso": "sized_beverage",
            "soda": "beverage",
            "water": "beverage",
            "juice": "beverage",
        }

        # Handle "beverage" or "drink" queries by combining both types
        if menu_query_type in ("beverage", "drink"):
            sized_items = items_by_type.get("sized_beverage", [])
            cold_items = items_by_type.get("beverage", [])
            items = sized_items + cold_items
            if items:
                # Conditionally show prices based on show_prices flag
                if show_prices:
                    item_list = [
                        f"{item.get('name', 'Unknown')} (${item.get('price') or item.get('base_price') or 0:.2f})"
                        for item in items[:15]
                    ]
                else:
                    item_list = [item.get("name", "Unknown") for item in items[:15]]
                if len(items) > 15:
                    item_list.append(f"...and {len(items) - 15} more")
                if len(item_list) == 1:
                    items_str = item_list[0]
                elif len(item_list) == 2:
                    items_str = f"{item_list[0]} and {item_list[1]}"
                else:
                    items_str = ", ".join(item_list[:-1]) + f", and {item_list[-1]}"
                return StateMachineResult(
                    message=f"Our beverages include: {items_str}. Would you like any of these?",
                    order=order,
                )
            return StateMachineResult(
                message="I don't have any beverages on the menu right now. Is there anything else I can help you with?",
                order=order,
            )

        # Handle "sandwich" specially - too broad, need to ask what kind
        if menu_query_type == "sandwich":
            return StateMachineResult(
                message="We have egg sandwiches, fish sandwiches, cream cheese sandwiches, signature sandwiches, deli sandwiches, and more. What kind of sandwich would you like?",
                order=order,
            )

        lookup_type = type_aliases.get(menu_query_type, menu_query_type)

        # Look up items for the specific type
        items = items_by_type.get(lookup_type, [])

        if not items:
            # Try to suggest what we do have
            available_types = [t.replace("_", " ") for t, i in items_by_type.items() if i]
            type_display = menu_query_type.replace("_", " ")
            if available_types:
                return StateMachineResult(
                    message=f"I don't have any {type_display}s on the menu. We do have: {', '.join(available_types)}. What would you like?",
                    order=order,
                )
            return StateMachineResult(
                message=f"I'm sorry, I don't have any {type_display}s on the menu. What else can I help you with?",
                order=order,
            )

        # Format the items list (conditionally show prices)
        type_name = menu_query_type.replace("_", " ")
        # Proper pluralization
        if type_name.endswith("ch") or type_name.endswith("s"):
            type_display = type_name + "es"
        else:
            type_display = type_name + "s"

        # Conditionally show prices based on show_prices flag
        if show_prices:
            item_list = []
            for item in items[:15]:
                name = item.get('name', 'Unknown')
                # Bagels use _lookup_bagel_price since they don't store price in items_by_type
                if lookup_type == "bagel":
                    # Extract bagel type from name (e.g., "Plain Bagel" -> "plain")
                    bagel_type = name.lower().replace(" bagel", "").strip()
                    price = self._lookup_bagel_price(bagel_type)
                else:
                    price = item.get('price') or item.get('base_price') or 0
                item_list.append(f"{name} (${price:.2f})")
        else:
            item_list = [item.get("name", "Unknown") for item in items[:15]]

        if len(items) > 15:
            item_list.append(f"...and {len(items) - 15} more")

        # Format the response
        if len(item_list) == 1:
            items_str = item_list[0]
        elif len(item_list) == 2:
            items_str = f"{item_list[0]} and {item_list[1]}"
        else:
            items_str = ", ".join(item_list[:-1]) + f", and {item_list[-1]}"

        return StateMachineResult(
            message=f"Our {type_display} include: {items_str}. Would you like any of these?",
            order=order,
        )

    def _handle_soda_clarification(
        self,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle when user orders a generic 'soda' without specifying type.

        Asks what kind of soda they want, listing available options.
        """
        # Get beverages from menu data
        items_by_type = self.menu_data.get("items_by_type", {}) if self.menu_data else {}
        beverages = items_by_type.get("beverage", [])

        if beverages:
            # Get just the names of a few common sodas
            soda_names = [item.get("name", "") for item in beverages[:6]]
            # Filter out empty names and format nicely
            soda_names = [name for name in soda_names if name]
            if len(soda_names) > 3:
                soda_list = ", ".join(soda_names[:3]) + ", and others"
            elif len(soda_names) > 1:
                soda_list = ", ".join(soda_names[:-1]) + f", and {soda_names[-1]}"
            else:
                soda_list = soda_names[0] if soda_names else "Coke, Diet Coke, Sprite"

            return StateMachineResult(
                message=f"What kind? We have {soda_list}.",
                order=order,
            )

        # Fallback if no beverages in menu data
        return StateMachineResult(
            message="What kind? We have Coke, Diet Coke, Sprite, and others.",
            order=order,
        )

    def _handle_price_inquiry(
        self,
        item_query: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle price inquiry for a specific item.

        Args:
            item_query: The item the user is asking about (e.g., 'sesame bagel', 'large latte')

        Returns:
            StateMachineResult with the price information
        """
        if not self.menu_data:
            return StateMachineResult(
                message="I'm sorry, I don't have pricing information available. What can I get for you?",
                order=order,
            )

        items_by_type = self.menu_data.get("items_by_type", {})
        query_lower = item_query.lower().strip()

        # Strip leading "a " or "an " from the query
        query_lower = re.sub(r"^(?:a|an)\s+", "", query_lower)

        # Check if this is a generic category inquiry (e.g., "a bagel", "coffee", "sandwich")
        # Map generic terms to their item_type and display name
        generic_category_map = {
            "bagel": ("bagel", "bagels"),
            "coffee": ("sized_beverage", "coffees"),
            "latte": ("sized_beverage", "lattes"),
            "cappuccino": ("sized_beverage", "cappuccinos"),
            "espresso": ("sized_beverage", "espressos"),
            "tea": ("sized_beverage", "teas"),
            "drink": ("beverage", "drinks"),
            "beverage": ("beverage", "beverages"),
            "soda": ("beverage", "sodas"),
            "omelette": ("omelette", "omelettes"),
            "side": ("side", "sides"),
        }

        # Special handling for "sandwich" - too broad, need to ask what kind
        if query_lower == "sandwich":
            return StateMachineResult(
                message="We have egg sandwiches, fish sandwiches, cream cheese sandwiches, signature sandwiches, deli sandwiches, and more. What kind of sandwich would you like?",
                order=order,
            )

        # Handle specific sandwich types
        sandwich_type_map = {
            "egg sandwich": ("egg_sandwich", "egg sandwiches"),
            "fish sandwich": ("fish_sandwich", "fish sandwiches"),
            "cream cheese sandwich": ("spread_sandwich", "cream cheese sandwiches"),
            "spread sandwich": ("spread_sandwich", "spread sandwiches"),
            "salad sandwich": ("salad_sandwich", "salad sandwiches"),
            "deli sandwich": ("deli_sandwich", "deli sandwiches"),
            "signature sandwich": ("signature_sandwich", "signature sandwiches"),
        }

        if query_lower in sandwich_type_map:
            item_type, display_name = sandwich_type_map[query_lower]
            min_price = self._get_min_price_for_category(item_type)
            if min_price > 0:
                return StateMachineResult(
                    message=f"Our {display_name} start at ${min_price:.2f}. Would you like one?",
                    order=order,
                )

        if query_lower in generic_category_map:
            item_type, display_name = generic_category_map[query_lower]
            min_price = self._get_min_price_for_category(item_type)
            if min_price > 0:
                return StateMachineResult(
                    message=f"Our {display_name} start at ${min_price:.2f}. Would you like one?",
                    order=order,
                )

        # Search all menu items for a match
        best_match = None
        best_match_score = 0

        for item_type, items in items_by_type.items():
            for item in items:
                item_name = item.get("name", "").lower()
                item_price = item.get("price", 0)

                # Exact match
                if item_name == query_lower:
                    best_match = item
                    best_match_score = 100
                    break

                # Check if query is contained in item name
                if query_lower in item_name:
                    score = len(query_lower) / len(item_name) * 80
                    if score > best_match_score:
                        best_match = item
                        best_match_score = score

                # Check if item name is contained in query
                if item_name in query_lower:
                    score = len(item_name) / len(query_lower) * 70
                    if score > best_match_score:
                        best_match = item
                        best_match_score = score

            if best_match_score == 100:
                break

        # Check bagels specifically (they may not be in items_by_type with prices)
        bagel_items = items_by_type.get("bagel", [])
        is_bagel_query = "bagel" in query_lower
        if is_bagel_query and not best_match:
            # Try to find a matching bagel
            for bagel in bagel_items:
                bagel_name = bagel.get("name", "").lower()
                if query_lower in bagel_name or bagel_name in query_lower:
                    best_match = bagel
                    best_match_score = 75
                    break

            # If they asked about a specific bagel type but we didn't find it,
            # give the general bagel price if available
            if not best_match and bagel_items:
                # Use the first bagel price as the general price
                best_match = bagel_items[0]
                best_match_score = 50

        if best_match and best_match_score >= 50:
            name = best_match.get("name", "Unknown")
            # Bagels use _lookup_bagel_price since they don't store price in items_by_type
            if is_bagel_query or "bagel" in name.lower():
                bagel_type = name.lower().replace(" bagel", "").strip()
                price = self._lookup_bagel_price(bagel_type)
            else:
                price = best_match.get("price") or best_match.get("base_price") or 0
            return StateMachineResult(
                message=f"{name} is ${price:.2f}. Would you like one?",
                order=order,
            )

        # No match found - give helpful response
        return StateMachineResult(
            message=f"I'm not sure about the price for '{item_query}'. Is there something else I can help you with?",
            order=order,
        )

    # =========================================================================
    # Store Info Handlers
    # =========================================================================

    def _handle_store_hours_inquiry(self, order: OrderTask) -> StateMachineResult:
        """Handle inquiry about store hours.

        Uses store_info from the process() call to get hours.
        If store_info is not available (no store context), asks the user which store.
        """
        store_info = getattr(self, '_store_info', {}) or {}
        hours = store_info.get("hours")
        store_name = store_info.get("name")

        if hours:
            # We have hours info - return it
            if store_name:
                message = f"Our hours at {store_name} are {hours}. Can I help you with an order?"
            else:
                message = f"Our hours are {hours}. Can I help you with an order?"
            return StateMachineResult(message=message, order=order)

        # No hours info available
        if store_name:
            # We know the store but don't have hours configured
            return StateMachineResult(
                message=f"I don't have the hours for {store_name} right now. Is there anything else I can help you with?",
                order=order,
            )

        # No store context at all - we can't determine which store
        return StateMachineResult(
            message="Which location would you like the hours for?",
            order=order,
        )

    def _handle_store_location_inquiry(self, order: OrderTask) -> StateMachineResult:
        """Handle inquiry about store location/address.

        Uses store_info from the process() call to get address.
        If store_info is not available (no store context), asks the user which store.
        """
        store_info = getattr(self, '_store_info', {}) or {}
        address = store_info.get("address")
        city = store_info.get("city")
        state = store_info.get("state")
        zip_code = store_info.get("zip_code")
        store_name = store_info.get("name")

        # Build full address if we have the parts
        if address:
            address_parts = [address]
            if city:
                city_state_zip = city
                if state:
                    city_state_zip += f", {state}"
                if zip_code:
                    city_state_zip += f" {zip_code}"
                address_parts.append(city_state_zip)
            full_address = ", ".join(address_parts)

            if store_name:
                message = f"{store_name} is located at {full_address}. Can I help you with an order?"
            else:
                message = f"We're located at {full_address}. Can I help you with an order?"
            return StateMachineResult(message=message, order=order)

        # No address info available
        if store_name:
            # We know the store but don't have address configured
            return StateMachineResult(
                message=f"I don't have the address for {store_name} right now. Is there anything else I can help you with?",
                order=order,
            )

        # No store context at all - we can't determine which store
        return StateMachineResult(
            message="Which location would you like the address for?",
            order=order,
        )

    def _handle_delivery_zone_inquiry(self, query: str | None, order: OrderTask) -> StateMachineResult:
        """Handle inquiry about whether we deliver to a specific location.

        Process:
        1. If query is a zip code (5 digits), check directly
        2. If query is a neighborhood, look up zip codes in NYC_NEIGHBORHOOD_ZIPS
        3. If it looks like an address, geocode it to get the zip code
        4. Do reverse lookup across all stores to find which deliver to that zip

        Args:
            query: The location they're asking about (zip, neighborhood, or address)
            order: Current order state
        """
        store_info = getattr(self, '_store_info', {}) or {}
        all_stores = store_info.get("all_stores", [])

        if not query:
            return StateMachineResult(
                message="What area would you like to check for delivery? You can give me a zip code or neighborhood.",
                order=order,
            )

        query_clean = query.lower().strip()

        # Check if it's a zip code (5 digits)
        zip_match = re.match(r'^(\d{5})$', query_clean)
        if zip_match:
            zip_code = zip_match.group(1)
            return self._check_delivery_for_zip(zip_code, all_stores, order)

        # Check if it's a known neighborhood
        neighborhood_key = query_clean.replace("'", "'").strip()
        if neighborhood_key in NYC_NEIGHBORHOOD_ZIPS:
            zip_codes = NYC_NEIGHBORHOOD_ZIPS[neighborhood_key]
            # Check if any of these zip codes are in delivery zones
            return self._check_delivery_for_neighborhood(query, zip_codes, all_stores, order)

        # Try fuzzy matching for neighborhoods (common variations)
        for key in NYC_NEIGHBORHOOD_ZIPS:
            if key in query_clean or query_clean in key:
                zip_codes = NYC_NEIGHBORHOOD_ZIPS[key]
                return self._check_delivery_for_neighborhood(query, zip_codes, all_stores, order)

        # Check if it looks like an address (has numbers suggesting a street address)
        if re.search(r'\d+\s+\w+', query):
            # Try to geocode the address to get a zip code
            from ..address_service import geocode_to_zip
            zip_code = geocode_to_zip(query)
            if zip_code:
                logger.info("Geocoded '%s' to zip code: %s", query, zip_code)
                return self._check_delivery_for_zip(zip_code, all_stores, order, original_query=query)

        # Unknown location - ask for more specific info
        return StateMachineResult(
            message=f"I'm not sure about {query}. Could you give me a zip code or street address so I can check our delivery area?",
            order=order,
        )

    def _check_delivery_for_zip(
        self, zip_code: str, all_stores: list, order: OrderTask, original_query: str | None = None
    ) -> StateMachineResult:
        """Check which stores deliver to a specific zip code.

        Args:
            zip_code: The zip code to check
            all_stores: List of all stores with delivery zones
            order: Current order state
            original_query: Original address/location query (for nicer messages)
        """
        delivering_stores = []
        # Use original query in messages if provided, otherwise use zip code
        location_display = original_query or zip_code

        for store in all_stores:
            delivery_zips = store.get("delivery_zip_codes", [])
            if zip_code in delivery_zips:
                delivering_stores.append(store)

        if delivering_stores:
            if len(delivering_stores) == 1:
                store = delivering_stores[0]
                store_name = store.get("name", "our store")
                message = f"Yes! {store_name} delivers to {location_display}. Would you like to place a delivery order?"
            else:
                store_names = [s.get("name", "Store") for s in delivering_stores]
                if len(store_names) == 2:
                    stores_str = f"{store_names[0]} and {store_names[1]}"
                else:
                    stores_str = ", ".join(store_names[:-1]) + f", and {store_names[-1]}"
                message = f"Yes! We can deliver to {location_display} from {stores_str}. Would you like to place a delivery order?"
            return StateMachineResult(message=message, order=order)

        # No stores deliver to this zip
        return StateMachineResult(
            message=f"Unfortunately, we don't currently deliver to {location_display}. You're welcome to place a pickup order instead. Would you like to do that?",
            order=order,
        )

    def _check_delivery_for_neighborhood(
        self, neighborhood: str, zip_codes: list, all_stores: list, order: OrderTask
    ) -> StateMachineResult:
        """Check which stores deliver to any of the neighborhood's zip codes."""
        delivering_stores = []
        covered_zips = []

        for store in all_stores:
            delivery_zips = store.get("delivery_zip_codes", [])
            matching_zips = [z for z in zip_codes if z in delivery_zips]
            if matching_zips:
                if store not in delivering_stores:
                    delivering_stores.append(store)
                covered_zips.extend(matching_zips)

        covered_zips = list(set(covered_zips))  # Remove duplicates

        if delivering_stores:
            if len(delivering_stores) == 1:
                store = delivering_stores[0]
                store_name = store.get("name", "our store")
                message = f"Yes! {store_name} delivers to {neighborhood}. Would you like to place a delivery order?"
            else:
                store_names = [s.get("name", "Store") for s in delivering_stores]
                if len(store_names) == 2:
                    stores_str = f"{store_names[0]} and {store_names[1]}"
                else:
                    stores_str = ", ".join(store_names[:-1]) + f", and {store_names[-1]}"
                message = f"Yes! We can deliver to {neighborhood} from {stores_str}. Would you like to place a delivery order?"
            return StateMachineResult(message=message, order=order)

        # No stores deliver to this neighborhood
        return StateMachineResult(
            message=f"Unfortunately, we don't currently deliver to {neighborhood}. You're welcome to place a pickup order instead. Would you like to do that?",
            order=order,
        )

    # =========================================================================
    # Recommendation Handlers
    # =========================================================================

    def _handle_recommendation_inquiry(
        self,
        category: str | None,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle recommendation questions like 'what do you recommend?' or 'what's your best bagel?'

        IMPORTANT: This should NOT add anything to the cart. It's just answering a question.
        The user needs to explicitly order something after getting the recommendation.

        Args:
            category: Type of recommendation asked - 'bagel', 'sandwich', 'coffee', 'breakfast', 'lunch', or None
            order: Current order state (unchanged)
        """
        items_by_type = self.menu_data.get("items_by_type", {}) if self.menu_data else {}

        if category == "bagel":
            return self._recommend_bagels(order)
        elif category == "sandwich":
            return self._recommend_sandwiches(items_by_type, order)
        elif category == "coffee":
            return self._recommend_coffee(items_by_type, order)
        elif category == "breakfast":
            return self._recommend_breakfast(items_by_type, order)
        elif category == "lunch":
            return self._recommend_lunch(items_by_type, order)
        else:
            # General recommendation - suggest popular items
            return self._recommend_general(items_by_type, order)

    def _recommend_bagels(self, order: OrderTask) -> StateMachineResult:
        """Recommend popular bagel options."""
        message = (
            "Our most popular bagels are everything and plain! "
            "The everything bagel with scallion cream cheese is a customer favorite. "
            "We also have sesame, cinnamon raisin, and pumpernickel if you're feeling adventurous. "
            "Would you like to try one?"
        )
        return StateMachineResult(message=message, order=order)

    def _recommend_sandwiches(self, items_by_type: dict, order: OrderTask) -> StateMachineResult:
        """Recommend popular sandwich options from the menu."""
        # Look for signature sandwiches or egg sandwiches
        signature = items_by_type.get("signature_sandwich", [])
        egg_sandwiches = items_by_type.get("egg_sandwich", [])

        recommendations = []

        # Get up to 2 signature sandwiches
        for item in signature[:2]:
            name = item.get("name", "")
            if name:
                recommendations.append(name)

        # Get 1 egg sandwich if we have room
        if len(recommendations) < 3 and egg_sandwiches:
            name = egg_sandwiches[0].get("name", "")
            if name:
                recommendations.append(name)

        if recommendations:
            if len(recommendations) == 1:
                message = f"I'd recommend {recommendations[0]} - it's one of our favorites! Would you like to try it?"
            else:
                items_str = ", ".join(recommendations[:-1]) + f", or {recommendations[-1]}"
                message = f"Some of our most popular are {items_str}. Would you like to try one?"
        else:
            message = "Our egg sandwiches are really popular! Would you like to hear about them?"

        return StateMachineResult(message=message, order=order)

    def _recommend_coffee(self, items_by_type: dict, order: OrderTask) -> StateMachineResult:
        """Recommend popular coffee options."""
        message = (
            "Our lattes are really popular - you can get them hot or iced! "
            "We also have great drip coffee if you want something simple. "
            "Would you like a coffee?"
        )
        return StateMachineResult(message=message, order=order)

    def _recommend_breakfast(self, items_by_type: dict, order: OrderTask) -> StateMachineResult:
        """Recommend breakfast options."""
        # Look for speed menu bagels and egg items
        speed_menu = items_by_type.get("speed_menu_bagel", [])
        omelettes = items_by_type.get("omelette", [])

        recommendations = []

        # Get a speed menu bagel
        for item in speed_menu[:1]:
            name = item.get("name", "")
            if name:
                recommendations.append(name)

        # Add a classic suggestion
        recommendations.append("an everything bagel with cream cheese")

        if omelettes:
            name = omelettes[0].get("name", "")
            if name:
                recommendations.append(name)

        if len(recommendations) >= 2:
            items_str = ", ".join(recommendations[:-1]) + f", or {recommendations[-1]}"
            message = f"For breakfast, I'd suggest {items_str}. What sounds good?"
        else:
            message = "For breakfast, our bagels with cream cheese are always a hit, or try one of our egg sandwiches! What sounds good?"

        return StateMachineResult(message=message, order=order)

    def _recommend_lunch(self, items_by_type: dict, order: OrderTask) -> StateMachineResult:
        """Recommend lunch options."""
        signature = items_by_type.get("signature_sandwich", [])
        salad = items_by_type.get("salad_sandwich", [])

        recommendations = []

        for item in signature[:2]:
            name = item.get("name", "")
            if name:
                recommendations.append(name)

        for item in salad[:1]:
            name = item.get("name", "")
            if name:
                recommendations.append(name)

        if recommendations:
            items_str = ", ".join(recommendations[:-1]) + f", or {recommendations[-1]}" if len(recommendations) > 1 else recommendations[0]
            message = f"For lunch, I'd recommend {items_str}. What sounds good?"
        else:
            message = "For lunch, our sandwiches are great! We have egg sandwiches, signature sandwiches, and salad sandwiches. What sounds good?"

        return StateMachineResult(message=message, order=order)

    def _recommend_general(self, items_by_type: dict, order: OrderTask) -> StateMachineResult:
        """General recommendation when no specific category is asked."""
        speed_menu = items_by_type.get("speed_menu_bagel", [])

        # Get a speed menu item name if available
        speed_item = None
        if speed_menu:
            speed_item = speed_menu[0].get("name", "")

        if speed_item:
            message = (
                f"Our {speed_item} is really popular! "
                "We're also known for our everything bagels with cream cheese, and our lattes are great too. "
                "What are you in the mood for?"
            )
        else:
            message = (
                "Our everything bagel with scallion cream cheese is a customer favorite! "
                "We also have great egg sandwiches and lattes. "
                "What are you in the mood for?"
            )

        return StateMachineResult(message=message, order=order)

    # =========================================================================
    # Item Description Handlers
    # =========================================================================

    # Item descriptions from Zucker's menu (what's on each item)
    ITEM_DESCRIPTIONS = {
        # Egg Sandwiches
        "the classic bec": "Two Eggs, Applewood Smoked Bacon, and Cheddar",
        "classic bec": "Two Eggs, Applewood Smoked Bacon, and Cheddar",
        "the latke bec": "Two Eggs, Applewood Smoked Bacon, Cheddar, and a Breakfast Potato Latke",
        "latke bec": "Two Eggs, Applewood Smoked Bacon, Cheddar, and a Breakfast Potato Latke",
        "the leo": "Smoked Nova Scotia Salmon, Eggs, and Sautéed Onions",
        "leo": "Smoked Nova Scotia Salmon, Eggs, and Sautéed Onions",
        "the delancey": "Two Eggs, Corned Beef or Pastrami, Breakfast Potato Latke, Sautéed Onions, and Swiss",
        "delancey": "Two Eggs, Corned Beef or Pastrami, Breakfast Potato Latke, Sautéed Onions, and Swiss",
        "the mulberry": "Two Eggs, Esposito's Sausage, Green & Red Peppers, and Sautéed Onions",
        "mulberry": "Two Eggs, Esposito's Sausage, Green & Red Peppers, and Sautéed Onions",
        "the truffled egg": "Two Eggs, Swiss, Truffle Cream Cheese, and Sautéed Mushrooms",
        "truffled egg": "Two Eggs, Swiss, Truffle Cream Cheese, and Sautéed Mushrooms",
        "the lexington": "Egg Whites, Swiss, and Spinach",
        "lexington": "Egg Whites, Swiss, and Spinach",
        "the columbus": "Three Egg Whites, Turkey Bacon, Avocado, and Swiss Cheese",
        "columbus": "Three Egg Whites, Turkey Bacon, Avocado, and Swiss Cheese",
        "the health nut": "Three Egg Whites, Mushrooms, Spinach, Green & Red Peppers, and Tomatoes",
        "health nut": "Three Egg Whites, Mushrooms, Spinach, Green & Red Peppers, and Tomatoes",
        # Signature Sandwiches
        "the zucker's traditional": "Nova Scotia Salmon, Plain Cream Cheese, Beefsteak Tomatoes, Red Onions, and Capers",
        "zucker's traditional": "Nova Scotia Salmon, Plain Cream Cheese, Beefsteak Tomatoes, Red Onions, and Capers",
        "the traditional": "Nova Scotia Salmon, Plain Cream Cheese, Beefsteak Tomatoes, Red Onions, and Capers",
        "traditional": "Nova Scotia Salmon, Plain Cream Cheese, Beefsteak Tomatoes, Red Onions, and Capers",
        "the flatiron": "Everything-seeded Salmon with Scallion Cream Cheese and Fresh Avocado",
        "flatiron": "Everything-seeded Salmon with Scallion Cream Cheese and Fresh Avocado",
        "the alton brown": "Smoked Trout with Plain Cream Cheese, Avocado Horseradish, and Tobiko",
        "alton brown": "Smoked Trout with Plain Cream Cheese, Avocado Horseradish, and Tobiko",
        "the old-school tuna": "Fresh Tuna Salad with Lettuce and Beefsteak Tomatoes",
        "old-school tuna": "Fresh Tuna Salad with Lettuce and Beefsteak Tomatoes",
        "old school tuna": "Fresh Tuna Salad with Lettuce and Beefsteak Tomatoes",
        "the max zucker": "Smoked Whitefish Salad with Beefsteak Tomatoes and Red Onions",
        "max zucker": "Smoked Whitefish Salad with Beefsteak Tomatoes and Red Onions",
        "the chelsea club": "Chicken Salad, Cheddar, Smoked Bacon, Beefsteak Tomatoes, Lettuce, and Red Onions",
        "chelsea club": "Chicken Salad, Cheddar, Smoked Bacon, Beefsteak Tomatoes, Lettuce, and Red Onions",
        "the grand central": "Grilled Chicken, Smoked Bacon, Beefsteak Tomatoes, Romaine, and Dijon Mayo",
        "grand central": "Grilled Chicken, Smoked Bacon, Beefsteak Tomatoes, Romaine, and Dijon Mayo",
        "the tribeca": "Roast Turkey, Havarti, Romaine, Beefsteak Tomatoes, Basil Mayo, and Cracked Black Pepper",
        "tribeca": "Roast Turkey, Havarti, Romaine, Beefsteak Tomatoes, Basil Mayo, and Cracked Black Pepper",
        "the natural": "Smoked Turkey, Brie, Beefsteak Tomatoes, Lettuce, and Dijon Dill Sauce",
        "natural": "Smoked Turkey, Brie, Beefsteak Tomatoes, Lettuce, and Dijon Dill Sauce",
        "the blt": "Applewood Smoked Bacon, Lettuce, Beefsteak Tomatoes, and Mayo",
        "blt": "Applewood Smoked Bacon, Lettuce, Beefsteak Tomatoes, and Mayo",
        "the reuben": "Corned Beef, Pastrami, or Roast Turkey with Sauerkraut, Swiss Cheese, and Russian Dressing",
        "reuben": "Corned Beef, Pastrami, or Roast Turkey with Sauerkraut, Swiss Cheese, and Russian Dressing",
        # Speed Menu Bagels
        "the classic": "Two Eggs, Applewood Smoked Bacon, and Cheddar on a Bagel",
        "classic": "Two Eggs, Applewood Smoked Bacon, and Cheddar on a Bagel",
        # Omelettes
        "the chipotle egg omelette": "Three Eggs with Pepper Jack Cheese, Jalapeños, and Chipotle Cream Cheese",
        "chipotle egg omelette": "Three Eggs with Pepper Jack Cheese, Jalapeños, and Chipotle Cream Cheese",
        "chipotle omelette": "Three Eggs with Pepper Jack Cheese, Jalapeños, and Chipotle Cream Cheese",
        "the health nut omelette": "Three Egg Whites with Mushrooms, Spinach, Green & Red Peppers, and Tomatoes",
        "health nut omelette": "Three Egg Whites with Mushrooms, Spinach, Green & Red Peppers, and Tomatoes",
        "the delancey omelette": "Three Eggs with Corned Beef or Pastrami, Onions, and Swiss Cheese",
        "delancey omelette": "Three Eggs with Corned Beef or Pastrami, Onions, and Swiss Cheese",
        # Avocado Toast
        "the avocado toast": "Crushed Avocado with Diced Tomatoes, Lemon Everything Seeds, Salt and Pepper",
        "avocado toast": "Crushed Avocado with Diced Tomatoes, Lemon Everything Seeds, Salt and Pepper",
    }

    def _handle_item_description_inquiry(
        self,
        item_query: str | None,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle item description questions like 'what's on the health nut?'

        IMPORTANT: This should NOT add anything to the cart. It's just answering a question.
        The user needs to explicitly order something after getting the description.

        Args:
            item_query: The item name the user is asking about
            order: Current order state (unchanged)
        """
        if not item_query:
            return StateMachineResult(
                message="Which item would you like to know about?",
                order=order,
            )

        item_query_lower = item_query.lower().strip()

        # Try to find an exact match or close match in descriptions
        description = self.ITEM_DESCRIPTIONS.get(item_query_lower)

        if not description:
            # Try partial matching - look for item_query in keys
            for key, desc in self.ITEM_DESCRIPTIONS.items():
                if item_query_lower in key or key in item_query_lower:
                    description = desc
                    break

        if not description:
            # Also search menu_data for item names
            if self.menu_data:
                items_by_type = self.menu_data.get("items_by_type", {})
                for item_type, items in items_by_type.items():
                    for item in items:
                        item_name = item.get("name", "").lower()
                        if item_query_lower in item_name or item_name in item_query_lower:
                            # Found the item in menu but no description - check ITEM_DESCRIPTIONS again
                            item_key = item.get("name", "").lower()
                            description = self.ITEM_DESCRIPTIONS.get(item_key)
                            if description:
                                break
                    if description:
                        break

        if description:
            # Format with proper capitalization
            formatted_name = item_query.title()
            message = f"{formatted_name} has {description}. Would you like to order one?"
        else:
            # Item not found - offer to help find it
            message = (
                f"I don't have detailed information about \"{item_query}\" right now. "
                "Would you like me to tell you what sandwiches or egg dishes we have?"
            )

        return StateMachineResult(message=message, order=order)

    # =========================================================================
    # Signature/Speed Menu Handlers
    # =========================================================================

    def _handle_signature_menu_inquiry(
        self,
        menu_type: str | None,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle inquiry about signature/speed menu items.

        Args:
            menu_type: Specific type like 'signature_sandwich' or 'speed_menu_bagel',
                      or None for all signature items
        """
        items_by_type = self.menu_data.get("items_by_type", {}) if self.menu_data else {}

        # If a specific type is requested, look it up directly
        if menu_type:
            items = items_by_type.get(menu_type, [])
            # Get the display name from the type slug (proper pluralization)
            type_name = menu_type.replace("_", " ")
            if type_name.endswith("ch") or type_name.endswith("s"):
                type_display_name = type_name + "es"
            else:
                type_display_name = type_name + "s"
        else:
            # No specific type - combine signature_sandwich and speed_menu_bagel items
            items = []
            items.extend(items_by_type.get("signature_sandwich", []))
            items.extend(items_by_type.get("speed_menu_bagel", []))
            type_display_name = "signature menu options"

        if not items:
            return StateMachineResult(
                message="We don't have any pre-made signature items on the menu right now. Would you like to build your own?",
                order=order,
            )

        # Build a nice list of items (without prices - prices only shown when specifically asked)
        item_descriptions = [item.get("name", "Unknown") for item in items]

        # Format the response
        if len(item_descriptions) == 1:
            items_list = item_descriptions[0]
        elif len(item_descriptions) == 2:
            items_list = f"{item_descriptions[0]} and {item_descriptions[1]}"
        else:
            items_list = ", ".join(item_descriptions[:-1]) + f", and {item_descriptions[-1]}"

        message = f"Our {type_display_name} are: {items_list}. Would you like any of these?"

        return StateMachineResult(
            message=message,
            order=order,
        )

    # =========================================================================
    # By-the-Pound Handlers
    # =========================================================================

    def _handle_by_pound_inquiry(
        self,
        category: str | None,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle initial by-the-pound inquiry."""
        if category:
            # User asked about a specific category directly
            return self._list_by_pound_category(category, order)

        # General inquiry - list all categories and ask which they're interested in
        order.phase = OrderPhase.CONFIGURING_ITEM
        order.pending_field = "by_pound_category"
        return StateMachineResult(
            message="We sell cheeses, spreads, cold cuts, fish, and salads by the pound. Which are you interested in?",
            order=order,
        )

    def _handle_by_pound_category_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user selecting a by-the-pound category."""
        parsed = parse_by_pound_category(user_input, model=self.model)

        if parsed.unclear:
            return StateMachineResult(
                message="Which would you like to hear about? Cheeses, spreads, cold cuts, fish, or salads?",
                order=order,
            )

        if not parsed.category:
            # User declined or said never mind
            order.clear_pending()
            # Phase derived by orchestrator
            return StateMachineResult(
                message="No problem! What else can I get for you?",
                order=order,
            )

        # List the items in the selected category
        return self._list_by_pound_category(parsed.category, order)

    def _list_by_pound_category(
        self,
        category: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """List items in a specific by-the-pound category."""
        # For spreads, fetch from menu_data (cheese_types contains cream cheese options)
        if category == "spread" and self.menu_data:
            cheese_types = self.menu_data.get("cheese_types", [])
            # Filter to only cream cheese, spreads, and butter
            items = [
                name for name in cheese_types
                if any(kw in name.lower() for kw in ["cream cheese", "spread", "butter"])
            ]
        else:
            items = BY_POUND_ITEMS.get(category, [])
        category_name = BY_POUND_CATEGORY_NAMES.get(category, category)

        if not items:
            order.clear_pending()
            # Phase derived by orchestrator
            return StateMachineResult(
                message=f"I don't have information on {category_name} right now. What else can I get for you?",
                order=order,
            )

        # Format the items list nicely for voice
        if len(items) <= 3:
            items_list = ", ".join(items)
        else:
            items_list = ", ".join(items[:-1]) + f", and {items[-1]}"

        order.clear_pending()
        # Phase derived by orchestrator

        # For spreads, don't say "by the pound" since they're also used on bagels
        if category == "spread":
            message = f"Our {category_name} include: {items_list}. Would you like any of these, or something else?"
        else:
            message = f"Our {category_name} by the pound include: {items_list}. Would you like any of these, or something else?"

        return StateMachineResult(
            message=message,
            order=order,
        )

    def _handle_drink_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user selecting from multiple drink options."""
        if not order.pending_drink_options:
            order.clear_pending()
            return StateMachineResult(
                message="What would you like to order?",
                order=order,
            )

        user_lower = user_input.lower().strip()
        options = order.pending_drink_options

        # Reject negative numbers or other invalid input early
        if user_lower.startswith('-') or user_lower.startswith('−'):
            option_list = []
            for i, item in enumerate(options, 1):
                name = item.get("name", "Unknown")
                price = item.get("base_price", 0)
                if price > 0:
                    option_list.append(f"{i}. {name} (${price:.2f})")
                else:
                    option_list.append(f"{i}. {name}")
            options_str = "\n".join(option_list)
            return StateMachineResult(
                message=f"Please choose a number from 1 to {len(options)}:\n{options_str}",
                order=order,
            )

        # Try to match by number (1, 2, 3, "first", "second", etc.)
        number_map = {
            "1": 0, "one": 0, "first": 0, "the first": 0, "number 1": 0, "number one": 0,
            "2": 1, "two": 1, "second": 1, "the second": 1, "number 2": 1, "number two": 1,
            "3": 2, "three": 2, "third": 2, "the third": 2, "number 3": 2, "number three": 2,
            "4": 3, "four": 3, "fourth": 3, "the fourth": 3, "number 4": 3, "number four": 3,
        }

        selected_item = None

        # Check for number/ordinal selection
        for key, idx in number_map.items():
            if key in user_lower:
                if idx < len(options):
                    selected_item = options[idx]
                    break
                else:
                    # User selected a number that's out of range - ask again
                    logger.info("DRINK SELECTION: User selected %s but only %d options available", key, len(options))
                    option_list = []
                    for i, item in enumerate(options, 1):
                        name = item.get("name", "Unknown")
                        price = item.get("base_price", 0)
                        if price > 0:
                            option_list.append(f"{i}. {name} (${price:.2f})")
                        else:
                            option_list.append(f"{i}. {name}")
                    options_str = "\n".join(option_list)
                    return StateMachineResult(
                        message=f"I only have {len(options)} options. Please choose:\n{options_str}",
                        order=order,
                    )

        # If not found by number, try to match by name
        if not selected_item:
            for option in options:
                option_name = option.get("name", "").lower()
                # Check if the option name is in user input or vice versa
                # But require minimum length to avoid false matches like "4" in "46 oz"
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
            option_list = []
            for i, item in enumerate(options, 1):
                name = item.get("name", "Unknown")
                price = item.get("base_price", 0)
                if price > 0:
                    option_list.append(f"{i}. {name} (${price:.2f})")
                else:
                    option_list.append(f"{i}. {name}")
            options_str = "\n".join(option_list)
            return StateMachineResult(
                message=f"I didn't catch which one. Please choose:\n{options_str}",
                order=order,
            )

        # Found the selection - clear pending state and add the drink
        selected_name = selected_item.get("name", "drink")
        selected_price = selected_item.get("base_price", 2.50)
        order.pending_drink_options = []
        order.clear_pending()

        logger.info("DRINK SELECTION: User chose '%s' (price: $%.2f)", selected_name, selected_price)

        # Check if this drink should skip configuration
        is_configurable_coffee = any(
            bev in selected_name.lower() for bev in COFFEE_BEVERAGE_TYPES
        )
        should_skip_config = selected_item.get("skip_config", False) or is_soda_drink(selected_name)

        if should_skip_config or not is_configurable_coffee:
            # Add directly as complete (no size/iced questions)
            drink = CoffeeItemTask(
                drink_type=selected_name,
                size=None,
                iced=None,
                milk=None,
                sweetener=None,
                sweetener_quantity=0,
                flavor_syrup=None,
                unit_price=selected_price,
            )
            drink.mark_complete()
            order.items.add_item(drink)

            return StateMachineResult(
                message=f"Got it, {selected_name}. Anything else?",
                order=order,
            )
        else:
            # Needs configuration - add as in_progress
            drink = CoffeeItemTask(
                drink_type=selected_name,
                size=None,
                iced=None,
                milk=None,
                sweetener=None,
                sweetener_quantity=0,
                flavor_syrup=None,
                unit_price=selected_price,
            )
            drink.mark_in_progress()
            order.items.add_item(drink)
            return self._configure_next_incomplete_coffee(order)

    def _parse_quantity_to_pounds(self, quantity_str: str) -> float:
        """Parse a quantity string to pounds.

        Examples:
            "1 lb" -> 1.0
            "2 lbs" -> 2.0
            "half lb" -> 0.5
            "half pound" -> 0.5
            "quarter lb" -> 0.25
            "1/2 lb" -> 0.5
            "1/4 lb" -> 0.25
            "3/4 lb" -> 0.75
        """
        quantity_lower = quantity_str.lower().strip()

        # Handle fractional words
        if "half" in quantity_lower:
            return 0.5
        if "quarter" in quantity_lower:
            return 0.25
        if "three quarter" in quantity_lower or "3/4" in quantity_lower:
            return 0.75
        if "1/2" in quantity_lower:
            return 0.5
        if "1/4" in quantity_lower:
            return 0.25

        # Try to extract a number
        match = re.search(r"(\d+(?:\.\d+)?)", quantity_lower)
        if match:
            return float(match.group(1))

        # Default to 1 pound
        return 1.0

    def _lookup_by_pound_price(self, item_name: str) -> float:
        """Look up the per-pound price for a by-the-pound item.

        Args:
            item_name: Name of the item (e.g., "Muenster", "Nova", "Tuna Salad")

        Returns:
            Price per pound, or 0.0 if not found
        """
        item_lower = item_name.lower().strip()

        # Direct lookup
        if item_lower in BY_POUND_PRICES:
            return BY_POUND_PRICES[item_lower]

        # Try partial matching for items like "Nova" -> "nova scotia salmon"
        for price_key, price in BY_POUND_PRICES.items():
            if item_lower in price_key or price_key in item_lower:
                return price

        # Not found
        logger.warning(f"No price found for by-pound item: {item_name}")
        return 0.0

    def _add_by_pound_items(
        self,
        by_pound_items: list[ByPoundOrderItem],
        order: OrderTask,
    ) -> StateMachineResult:
        """Add by-the-pound items to the order."""
        from sandwich_bot.tasks.models import MenuItemTask

        added_items = []
        for item in by_pound_items:
            # Format the item name with quantity (e.g., "1 lb Muenster Cheese")
            category_name = BY_POUND_CATEGORY_NAMES.get(item.category, "")
            if category_name:
                # Use singular form for category (remove trailing 's' if present)
                category_singular = category_name.rstrip("s") if category_name.endswith("s") else category_name
                item_name = f"{item.quantity} {item.item_name} {category_singular}"
            else:
                item_name = f"{item.quantity} {item.item_name}"

            # Calculate price based on quantity and per-pound price
            pounds = self._parse_quantity_to_pounds(item.quantity)
            per_pound_price = self._lookup_by_pound_price(item.item_name)
            total_price = round(pounds * per_pound_price, 2)

            # Create menu item task with price
            menu_item = MenuItemTask(
                menu_item_name=item_name.strip(),
                menu_item_type="by_pound",
                unit_price=total_price,
            )
            menu_item.mark_in_progress()
            menu_item.mark_complete()  # By-pound items don't need configuration
            order.items.add_item(menu_item)
            added_items.append(item_name.strip())

        # Format confirmation message
        if len(added_items) == 1:
            confirmation = f"Got it, {added_items[0]}."
        elif len(added_items) == 2:
            confirmation = f"Got it, {added_items[0]} and {added_items[1]}."
        else:
            items_list = ", ".join(added_items[:-1]) + f", and {added_items[-1]}"
            confirmation = f"Got it, {items_list}."

        order.clear_pending()
        # Explicitly set to TAKING_ITEMS - we're asking for more items
        order.phase = OrderPhase.TAKING_ITEMS.value
        return StateMachineResult(
            message=f"{confirmation} Anything else?",
            order=order,
        )

    def _get_next_question(
        self,
        order: OrderTask,
    ) -> StateMachineResult:
        """Determine the next question to ask."""
        # Check for incomplete items
        for item in order.items.items:
            if item.status == TaskStatus.IN_PROGRESS:
                # This shouldn't happen if we're tracking state correctly
                logger.warning(f"Found in-progress item without pending state: {item}")

        # Check if there are items queued for configuration
        if order.has_queued_config_items():
            next_config = order.pop_next_config_item()
            if next_config:
                item_id = next_config.get("item_id")
                item_type = next_config.get("item_type")
                logger.info("Processing queued config item: id=%s, type=%s", item_id[:8] if item_id else None, item_type)

                # Find the item by ID
                for item in order.items.items:
                    if item.id == item_id:
                        if item_type == "coffee" and isinstance(item, CoffeeItemTask):
                            # Start coffee configuration
                            return self._configure_next_incomplete_coffee(order)

        # Ask if they want anything else
        items = order.items.get_active_items()
        if items:
            # Count consecutive identical items at the end of the list
            last_item = items[-1]
            last_summary = last_item.get_summary()
            count = 0
            for item in reversed(items):
                if item.get_summary() == last_summary:
                    count += 1
                else:
                    break

            # Show quantity if more than 1 identical item
            if count > 1:
                summary = f"{count} {last_summary}s" if not last_summary.endswith("s") else f"{count} {last_summary}"
            else:
                summary = last_summary

            # Explicitly set to TAKING_ITEMS - we're asking for more items
            order.phase = OrderPhase.TAKING_ITEMS.value
            return StateMachineResult(
                message=f"Got it, {summary}. Anything else?",
                order=order,
            )

        return StateMachineResult(
            message="What can I get for you?",
            order=order,
        )

    def _transition_to_checkout(
        self,
        order: OrderTask,
    ) -> StateMachineResult:
        """Transition to checkout phase.

        Uses the slot orchestrator to determine what to ask next.
        """
        order.clear_pending()

        # Use orchestrator to determine next step in checkout
        self._transition_to_next_slot(order)

        # Return appropriate message based on phase set by orchestrator
        if order.phase == OrderPhase.CHECKOUT_NAME.value:
            logger.info("CHECKOUT: Asking for name (delivery=%s)", order.delivery_method.order_type)
            return StateMachineResult(
                message="Can I get a name for the order?",
                order=order,
            )
        elif order.phase == OrderPhase.CHECKOUT_CONFIRM.value:
            # We have both delivery type and customer name
            logger.info("CHECKOUT: Skipping to confirmation (already have name=%s, delivery=%s)",
                       order.customer_info.name, order.delivery_method.order_type)
            summary = self._build_order_summary(order)
            return StateMachineResult(
                message=f"{summary}\n\nDoes that look right?",
                order=order,
            )
        else:
            # Default: ask for delivery method
            return StateMachineResult(
                message=self._get_delivery_question(),
                order=order,
            )

    def _get_delivery_question(self) -> str:
        """Get the delivery/pickup question, personalized for repeat orders."""
        # Only say "again" if this is actually a repeat order
        is_repeat = getattr(self, "_is_repeat_order", False)
        last_order_type = getattr(self, "_last_order_type", None)

        if is_repeat and last_order_type == "pickup":
            return "Is this for pickup again, or delivery?"
        elif is_repeat and last_order_type == "delivery":
            return "Is this for delivery again, or pickup?"
        else:
            return "Is this for pickup or delivery?"

    def _proceed_after_address(self, order: OrderTask) -> StateMachineResult:
        """Handle transition after delivery address is captured.

        Checks if we already have customer info and skips to confirmation if so.
        """
        self._transition_to_next_slot(order)

        # If we already have the customer name, skip to confirmation
        if order.customer_info.name:
            order.phase = OrderPhase.CHECKOUT_CONFIRM.value
            summary = self._build_order_summary(order)
            return StateMachineResult(
                message=f"{summary}\n\nDoes that look right?",
                order=order,
            )

        return StateMachineResult(
            message="Can I get a name for the order?",
            order=order,
        )

    def _get_item_by_id(self, order: OrderTask, item_id: str) -> ItemTask | None:
        """Find an item by its ID."""
        for item in order.items.items:
            if item.id == item_id:
                return item
        return None

    def _build_order_summary(self, order: OrderTask) -> str:
        """Build order summary string with consolidated identical items and total."""
        lines = ["Here's your order:"]

        # Group items by their summary string to consolidate identical items
        from collections import defaultdict
        item_data: dict[str, dict] = defaultdict(lambda: {"count": 0, "total_price": 0.0})
        for item in order.items.get_active_items():
            summary = item.get_summary()
            price = item.unit_price * getattr(item, 'quantity', 1)
            item_data[summary]["count"] += 1
            item_data[summary]["total_price"] += price

        # Build consolidated lines (no individual prices, just total at end)
        for summary, data in item_data.items():
            count = data["count"]
            if count > 1:
                # Pluralize: "3 cokes" instead of "3× coke"
                plural = f"{summary}s" if not summary.endswith("s") else summary
                lines.append(f"• {count} {plural}")
            else:
                lines.append(f"• {summary}")

        # Add "plus tax" note
        subtotal = order.items.get_subtotal()
        if subtotal > 0:
            lines.append(f"\nThat's ${subtotal:.2f} plus tax.")

        return "\n".join(lines)

    def _handle_quantity_change(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle quantity change requests like 'make it two orange juices'.

        Returns StateMachineResult if handled, None otherwise.
        """
        user_lower = user_input.lower().strip()

        # Patterns for quantity changes
        # "make it two X", "can you make it 2 X", "two X instead", "change to two X"
        quantity_patterns = [
            r"make\s+it\s+(\w+)\s+(.+)",
            r"change\s+(?:it\s+)?to\s+(\w+)\s+(.+)",
            r"(\w+)\s+(.+?)\s+instead",
            r"can\s+(?:i\s+)?(?:you\s+)?(?:get|have|make\s+it)\s+(\w+)\s+(.+)",
            r"i(?:'d)?\s+(?:like|want)\s+(\w+)\s+(.+?)(?:\s+instead)?$",
        ]

        # Number word to int mapping
        number_map = {
            "two": 2, "2": 2,
            "three": 3, "3": 3,
            "four": 4, "4": 4,
            "five": 5, "5": 5,
        }

        target_quantity = None
        item_name = None

        for pattern in quantity_patterns:
            match = re.search(pattern, user_lower)
            if match:
                num_word = match.group(1)
                item_desc = match.group(2).strip()
                if num_word in number_map:
                    target_quantity = number_map[num_word]
                    item_name = item_desc
                    logger.info("QUANTITY_CHANGE: Detected pattern '%s' -> qty=%d, item='%s'",
                               pattern, target_quantity, item_name)
                    break

        if not target_quantity or not item_name:
            return None

        # Find matching items in the order
        active_items = order.items.get_active_items()
        matching_items = []

        # Build search terms including synonyms
        # (e.g., "orange juice" should also match "tropicana")
        drink_synonyms = {
            "orange juice": ["tropicana", "fresh squeezed"],
            "oj": ["orange juice", "tropicana", "fresh squeezed"],
            "apple juice": ["martinelli"],
            "lemonade": ["minute maid"],
        }
        search_terms = [item_name]
        for generic_term, synonyms in drink_synonyms.items():
            if generic_term in item_name:
                search_terms.extend(synonyms)

        for item in active_items:
            item_summary = item.get_summary().lower()
            item_type = getattr(item, 'drink_type', '') or getattr(item, 'menu_item_name', '') or ''
            item_type_lower = item_type.lower()

            # Check if any search term matches
            for search_term in search_terms:
                if (search_term in item_summary or
                    search_term in item_type_lower or
                    item_type_lower in search_term or
                    # Handle partial matches
                    any(word in item_summary for word in search_term.split() if len(word) > 3)):
                    matching_items.append(item)
                    break  # Don't add same item multiple times

        if not matching_items:
            logger.info("QUANTITY_CHANGE: No matching items found for '%s'", item_name)
            return None

        # Calculate how many to add
        current_count = len(matching_items)
        to_add = target_quantity - current_count

        if to_add <= 0:
            # Already have enough or more
            logger.info("QUANTITY_CHANGE: Already have %d items, target is %d", current_count, target_quantity)
            summary = self._build_order_summary(order)
            return StateMachineResult(
                message=f"You already have {current_count} in your order.\n\n{summary}\n\nDoes that look right?",
                order=order,
            )

        # Add copies of the first matching item
        template_item = matching_items[0]
        for _ in range(to_add):
            # Create a copy of the item
            if isinstance(template_item, CoffeeItemTask):
                new_item = CoffeeItemTask(
                    drink_type=template_item.drink_type,
                    size=template_item.size,
                    iced=template_item.iced,
                    milk=template_item.milk,
                    sweetener=template_item.sweetener,
                    sweetener_quantity=template_item.sweetener_quantity,
                    flavor_syrup=template_item.flavor_syrup,
                    unit_price=template_item.unit_price,
                    notes=template_item.notes,
                )
                new_item.mark_complete()
                order.items.add_item(new_item)
                logger.info("QUANTITY_CHANGE: Added copy of '%s'", template_item.drink_type)
            elif isinstance(template_item, BagelItemTask):
                new_item = BagelItemTask(
                    bagel_type=template_item.bagel_type,
                    toasted=template_item.toasted,
                    spread=template_item.spread,
                    spread_type=template_item.spread_type,
                    sandwich_protein=template_item.sandwich_protein,
                    extras=list(template_item.extras) if template_item.extras else [],
                    unit_price=template_item.unit_price,
                )
                new_item.mark_complete()
                order.items.add_item(new_item)
                logger.info("QUANTITY_CHANGE: Added copy of bagel")
            elif isinstance(template_item, MenuItemTask):
                new_item = MenuItemTask(
                    menu_item_name=template_item.menu_item_name,
                    unit_price=template_item.unit_price,
                    toasted=template_item.toasted,
                    bagel_choice=template_item.bagel_choice,
                    side_choice=template_item.side_choice,
                )
                new_item.mark_complete()
                order.items.add_item(new_item)
                logger.info("QUANTITY_CHANGE: Added copy of '%s'", template_item.menu_item_name)
            elif isinstance(template_item, SpeedMenuBagelItemTask):
                new_item = SpeedMenuBagelItemTask(
                    speed_menu_name=template_item.speed_menu_name,
                    toasted=template_item.toasted,
                    bagel_choice=template_item.bagel_choice,
                    unit_price=template_item.unit_price,
                )
                new_item.mark_complete()
                order.items.add_item(new_item)
                logger.info("QUANTITY_CHANGE: Added copy of '%s'", template_item.speed_menu_name)

        # Build updated summary
        summary = self._build_order_summary(order)
        item_display = template_item.drink_type if isinstance(template_item, CoffeeItemTask) else template_item.get_summary()
        return StateMachineResult(
            message=f"Got it, {target_quantity} {item_display}.\n\n{summary}\n\nDoes that look right?",
            order=order,
        )

    def _handle_tax_question(self, order: OrderTask) -> StateMachineResult:
        """Handle user asking about total with tax."""
        subtotal = order.items.get_subtotal()

        # Get tax rates from store_info
        city_tax_rate = getattr(self, '_store_info', {}).get('city_tax_rate', 0.0) or 0.0
        state_tax_rate = getattr(self, '_store_info', {}).get('state_tax_rate', 0.0) or 0.0

        # Calculate taxes
        city_tax = subtotal * city_tax_rate
        state_tax = subtotal * state_tax_rate
        total_tax = city_tax + state_tax
        total_with_tax = subtotal + total_tax

        # Format response
        if total_tax > 0:
            message = f"Your subtotal is ${subtotal:.2f}. With tax, that comes to ${total_with_tax:.2f}. Does that look right?"
        else:
            # No tax configured - just show the subtotal
            message = f"Your total is ${subtotal:.2f}. Does that look right?"

        logger.info("TAX_QUESTION: subtotal=%.2f, city_tax=%.2f, state_tax=%.2f, total=%.2f",
                   subtotal, city_tax, state_tax, total_with_tax)

        return StateMachineResult(
            message=message,
            order=order,
        )

    def _handle_order_status(self, order: OrderTask) -> StateMachineResult:
        """Handle user asking about their current order status."""
        items = order.items.get_active_items()

        if not items:
            message = "You haven't ordered anything yet. What can I get for you?"
            return StateMachineResult(
                message=message,
                order=order,
            )

        # Build item list with consolidated identical items
        from collections import defaultdict
        item_counts: dict[str, int] = defaultdict(int)
        for item in items:
            summary = item.get_summary()
            item_counts[summary] += 1

        lines = ["So far you have:"]
        for summary, count in item_counts.items():
            if count > 1:
                plural = f"{summary}s" if not summary.endswith("s") else summary
                lines.append(f"• {count} {plural}")
            else:
                lines.append(f"• {summary}")

        # Add total
        subtotal = order.items.get_subtotal()
        if subtotal > 0:
            lines.append(f"\nThat's ${subtotal:.2f} plus tax.")

        # Add phase-appropriate follow-up question
        follow_up = self._get_phase_follow_up(order)
        lines.append(f"\n{follow_up}")

        message = "\n".join(lines)
        logger.info("ORDER_STATUS: %d items, subtotal=%.2f, phase=%s", len(items), subtotal, order.phase)

        return StateMachineResult(
            message=message,
            order=order,
        )

    def _get_phase_follow_up(self, order: OrderTask) -> str:
        """Get the appropriate follow-up question based on current order phase."""
        phase = order.phase

        if phase == OrderPhase.GREETING.value or phase == OrderPhase.TAKING_ITEMS.value:
            return "Anything else?"
        elif phase == OrderPhase.CONFIGURING_ITEM.value:
            # If configuring an item, ask about the pending field
            return "Anything else?"  # Will return to item config after this
        elif phase == OrderPhase.CHECKOUT_DELIVERY.value:
            return "Is this for pickup or delivery?"
        elif phase == OrderPhase.CHECKOUT_NAME.value:
            return "Can I get a name for the order?"
        elif phase == OrderPhase.CHECKOUT_CONFIRM.value:
            return "Does that look right?"
        elif phase == OrderPhase.CHECKOUT_PAYMENT_METHOD.value:
            return "Would you like your order details sent by text or email?"
        elif phase == OrderPhase.CHECKOUT_PHONE.value:
            return "What's the best phone number to reach you?"
        elif phase == OrderPhase.CHECKOUT_EMAIL.value:
            return "What's your email address?"
        else:
            return "Anything else?"

    def _get_min_price_for_category(self, item_type: str) -> float:
        """
        Get the minimum (starting) price for a category of items.

        Args:
            item_type: The item type slug (e.g., 'bagel', 'sized_beverage', 'egg_sandwich')

        Returns:
            Minimum price found for the category, or 0 if not found
        """
        if not self.menu_data:
            # Return sensible defaults for common categories
            defaults = {
                "bagel": 2.50,
                "sized_beverage": 2.50,
                "beverage": 2.00,
                "egg_sandwich": 6.95,
                "omelette": 8.95,
                "side": 1.50,
            }
            return defaults.get(item_type, 0)

        items_by_type = self.menu_data.get("items_by_type", {})

        # Special handling for bagels - use _lookup_bagel_price
        if item_type == "bagel":
            return self._lookup_bagel_price(None)

        # Get items for this category
        items = items_by_type.get(item_type, [])
        if not items:
            return 0

        # Find minimum price
        prices = []
        for item in items:
            price = item.get("price") or item.get("base_price") or 0
            if price > 0:
                prices.append(price)

        return min(prices) if prices else 0

    def _lookup_bagel_price(self, bagel_type: str | None) -> float:
        """
        Look up price for a bagel type.

        For regular bagel types (plain, everything, sesame, etc.), returns the
        generic "Bagel" price from the menu. Only specialty bagels like
        "Gluten Free" get their specific price.

        Args:
            bagel_type: The bagel type (e.g., "plain", "everything", "gluten free")

        Returns:
            Price for the bagel (defaults to 2.50 if not found)
        """
        if not bagel_type:
            return 2.50

        bagel_type_lower = bagel_type.lower()

        # Specialty bagels that have their own menu items
        specialty_bagels = ["gluten free", "gluten-free"]

        if any(specialty in bagel_type_lower for specialty in specialty_bagels):
            # Look for specific specialty bagel as menu item first
            bagel_name = f"{bagel_type.title()} Bagel" if "bagel" not in bagel_type_lower else bagel_type
            menu_item = self._lookup_menu_item(bagel_name)
            if menu_item:
                logger.info("Found specialty bagel: %s ($%.2f)", menu_item.get("name"), menu_item.get("base_price"))
                return menu_item.get("base_price", 2.50)

            # Try bread_prices from menu_data (ingredients table)
            if self.menu_data:
                bread_prices = self.menu_data.get("bread_prices", {})
                # Try exact match
                bagel_key = bagel_name.lower()
                if bagel_key in bread_prices:
                    price = bread_prices[bagel_key]
                    logger.info("Found specialty bagel in bread_prices: %s ($%.2f)", bagel_name, price)
                    return price
                # Try partial match for specialty type (e.g., "gluten free bagel")
                for bread_name, price in bread_prices.items():
                    if any(specialty in bread_name for specialty in specialty_bagels):
                        logger.info("Found specialty bagel in bread_prices (partial): %s ($%.2f)", bread_name, price)
                        return price

        # For regular bagels, look for the generic "Bagel" item
        menu_item = self._lookup_menu_item("Bagel")
        if menu_item:
            logger.info("Using generic bagel price: $%.2f", menu_item.get("base_price"))
            return menu_item.get("base_price", 2.50)

        # Default fallback
        return 2.50

    def _lookup_menu_item(self, item_name: str) -> dict | None:
        """
        Look up a menu item by name from the menu data.

        Args:
            item_name: Name of the item to find (case-insensitive fuzzy match)

        Returns:
            Menu item dict with id, name, base_price, etc. or None if not found
        """
        if not self.menu_data:
            return None

        item_name_lower = item_name.lower()

        # Collect all items from all categories
        all_items = []
        categories_to_search = [
            "signature_sandwiches", "signature_bagels", "signature_omelettes",
            "sides", "drinks", "desserts", "other",
            "custom_sandwiches", "custom_bagels",
        ]

        for category in categories_to_search:
            all_items.extend(self.menu_data.get(category, []))

        # Also include items_by_type
        items_by_type = self.menu_data.get("items_by_type", {})
        for type_slug, items in items_by_type.items():
            all_items.extend(items)

        # Pass 1: Exact match (highest priority)
        for item in all_items:
            if item.get("name", "").lower() == item_name_lower:
                return item

        # Pass 2: Search term is contained in item name (e.g., searching "chipotle" finds "The Chipotle Egg Omelette")
        # Prefer shorter item names (more specific match)
        matches = []
        for item in all_items:
            item_name_db = item.get("name", "").lower()
            if item_name_lower in item_name_db:
                matches.append(item)
        if matches:
            # Return the shortest matching name (most specific)
            return min(matches, key=lambda x: len(x.get("name", "")))

        # Pass 3: Item name is contained in search term (e.g., searching "The Chipotle Egg Omelette" finds item named "Chipotle Egg Omelette")
        # Prefer LONGER item names (more complete match)
        matches = []
        for item in all_items:
            item_name_db = item.get("name", "").lower()
            if item_name_db in item_name_lower:
                matches.append(item)
        if matches:
            # Return the longest matching name (most complete)
            return max(matches, key=lambda x: len(x.get("name", "")))

        return None

    def _lookup_menu_items(self, item_name: str) -> list[dict]:
        """
        Look up ALL menu items matching a name from the menu data.

        Unlike _lookup_menu_item which returns only the best match, this returns
        ALL items that match the search term. Used for disambiguation when
        multiple items match (e.g., "orange juice" matches 3 different OJ types).

        Args:
            item_name: Name of the item to find (case-insensitive fuzzy match)

        Returns:
            List of menu item dicts with id, name, base_price, etc.
        """
        if not self.menu_data:
            return []

        item_name_lower = item_name.lower()

        # Known drink synonyms/brands - map generic terms to brand keywords
        # This helps find "Tropicana No Pulp" when searching "orange juice"
        drink_synonyms = {
            "orange juice": ["tropicana", "fresh squeezed"],
            "oj": ["orange juice", "tropicana", "fresh squeezed"],
            "apple juice": ["martinelli"],
            "lemonade": ["minute maid"],
        }

        # Build list of search terms (original + any synonyms)
        search_terms = [item_name_lower]
        for generic_term, synonyms in drink_synonyms.items():
            if generic_term in item_name_lower:
                search_terms.extend(synonyms)

        # Collect all items from all categories
        all_items = []
        categories_to_search = [
            "signature_sandwiches", "signature_bagels", "signature_omelettes",
            "sides", "drinks", "desserts", "other",
            "custom_sandwiches", "custom_bagels",
        ]

        for category in categories_to_search:
            all_items.extend(self.menu_data.get(category, []))

        # Also include items_by_type
        items_by_type = self.menu_data.get("items_by_type", {})
        for type_slug, items in items_by_type.items():
            all_items.extend(items)

        # Deduplicate by item name (some items appear in multiple categories)
        seen_names = set()
        unique_items = []
        for item in all_items:
            name = item.get("name", "").lower()
            if name not in seen_names:
                seen_names.add(name)
                unique_items.append(item)
        all_items = unique_items

        # Pass 1: Exact match - if found, return only that
        for item in all_items:
            if item.get("name", "").lower() == item_name_lower:
                return [item]

        # Pass 2: Search term (or synonyms) is contained in item name
        # e.g., "orange juice" finds "Tropicana Orange Juice", "Fresh Squeezed Orange Juice"
        # Also "tropicana" (synonym) finds "Tropicana No Pulp"
        matches = []
        matched_names = set()
        for item in all_items:
            item_name_db = item.get("name", "").lower()
            for search_term in search_terms:
                if search_term in item_name_db and item_name_db not in matched_names:
                    matches.append(item)
                    matched_names.add(item_name_db)
                    break
        if matches:
            # Sort by name length (shortest first = more specific)
            return sorted(matches, key=lambda x: len(x.get("name", "")))

        # Pass 3: Item name is contained in search term
        # e.g., "tropicana orange juice" finds "Tropicana"
        matches = []
        for item in all_items:
            item_name_db = item.get("name", "").lower()
            if item_name_db in item_name_lower:
                matches.append(item)
        if matches:
            # Sort by name length (longest first = more complete match)
            return sorted(matches, key=lambda x: len(x.get("name", "")), reverse=True)

        return []

    def _infer_item_category(self, item_name: str) -> str | None:
        """
        Infer the likely category of an unknown item based on keywords.

        Args:
            item_name: The name of the item the user requested

        Returns:
            Category key like "drinks", "sides", "signature_bagels", or None if unclear
        """
        name_lower = item_name.lower()

        # Drink keywords
        drink_keywords = [
            "juice", "coffee", "tea", "latte", "cappuccino", "espresso",
            "soda", "coke", "pepsi", "sprite", "water", "smoothie",
            "milk", "chocolate milk", "hot chocolate", "mocha",
            "drink", "beverage", "lemonade", "iced", "frappe",
        ]
        if any(kw in name_lower for kw in drink_keywords):
            return "drinks"

        # Side keywords
        side_keywords = [
            "hash", "hashbrown", "fries", "tots", "bacon", "sausage",
            "egg", "eggs", "fruit", "salad", "side", "toast",
            "home fries", "potatoes", "pancake", "waffle",
        ]
        if any(kw in name_lower for kw in side_keywords):
            return "sides"

        # Bagel keywords
        bagel_keywords = [
            "bagel", "everything", "plain", "sesame", "poppy",
            "cinnamon", "raisin", "onion", "pumpernickel", "whole wheat",
        ]
        if any(kw in name_lower for kw in bagel_keywords):
            return "signature_bagels"

        # Sandwich/omelette keywords
        sandwich_keywords = [
            "sandwich", "omelette", "omelet", "wrap", "panini",
            "club", "blt", "reuben",
        ]
        if any(kw in name_lower for kw in sandwich_keywords):
            return "signature_omelettes"

        # Dessert keywords
        dessert_keywords = [
            "cookie", "brownie", "muffin", "cake", "pastry",
            "donut", "doughnut", "dessert", "sweet",
        ]
        if any(kw in name_lower for kw in dessert_keywords):
            return "desserts"

        return None

    def _get_category_suggestions(self, category: str, limit: int = 5) -> str:
        """
        Get a formatted string of menu suggestions from a category.

        Args:
            category: The menu category key (e.g., "drinks", "sides")
            limit: Maximum number of suggestions to include

        Returns:
            Formatted string like "home fries, fruit cup, or a side of bacon"
        """
        if not self.menu_data:
            return ""

        items = self.menu_data.get(category, [])

        # If no items in direct category, try items_by_type
        if not items and category in ["sides", "drinks", "desserts"]:
            # Map category to potential item_type slugs
            type_map = {
                "sides": ["side"],
                "drinks": ["drink", "coffee", "soda"],
                "desserts": ["dessert"],
            }
            items_by_type = self.menu_data.get("items_by_type", {})
            for type_slug in type_map.get(category, []):
                items.extend(items_by_type.get(type_slug, []))

        if not items:
            return ""

        # Get unique item names, limited to the specified count
        item_names = []
        seen = set()
        for item in items:
            name = item.get("name", "")
            if name and name.lower() not in seen:
                seen.add(name.lower())
                item_names.append(name)
                if len(item_names) >= limit:
                    break

        if not item_names:
            return ""

        # Format as natural language list
        if len(item_names) == 1:
            return item_names[0]
        elif len(item_names) == 2:
            return f"{item_names[0]} or {item_names[1]}"
        else:
            return ", ".join(item_names[:-1]) + f", or {item_names[-1]}"

    def _get_not_found_message(self, item_name: str) -> str:
        """
        Generate a helpful message when an item isn't found on the menu.

        Infers the category and suggests alternatives.

        Args:
            item_name: The name of the item the user requested

        Returns:
            A helpful error message with suggestions
        """
        category = self._infer_item_category(item_name)

        if category:
            suggestions = self._get_category_suggestions(category, limit=4)
            category_name = {
                "drinks": "drinks",
                "sides": "sides",
                "signature_bagels": "bagels",
                "signature_omelettes": "sandwiches and omelettes",
                "desserts": "desserts",
            }.get(category, "items")

            if suggestions:
                return (
                    f"I'm sorry, we don't have {item_name}. "
                    f"For {category_name}, we have {suggestions}. "
                    f"Would any of those work?"
                )
            else:
                return (
                    f"I'm sorry, we don't have {item_name}. "
                    f"Would you like to hear what {category_name} we have?"
                )
        else:
            # Generic fallback
            return (
                f"I'm sorry, I couldn't find '{item_name}' on our menu. "
                f"Could you try again or ask what we have available?"
            )

    # Default modifier prices - used as fallback when menu_data lookup fails
    DEFAULT_MODIFIER_PRICES = {
        # Proteins
        "ham": 2.00,
        "bacon": 2.00,
        "egg": 1.50,
        "lox": 5.00,
        "turkey": 2.50,
        "pastrami": 3.00,
        "sausage": 2.00,
        # Cheeses
        "american": 0.75,
        "swiss": 0.75,
        "cheddar": 0.75,
        "muenster": 0.75,
        "provolone": 0.75,
        # Spreads
        "cream cheese": 1.50,
        "butter": 0.50,
        "scallion cream cheese": 1.75,
        "vegetable cream cheese": 1.75,
        # Extras
        "avocado": 2.00,
        "tomato": 0.50,
        "onion": 0.50,
        "capers": 0.75,
    }

    def _lookup_modifier_price(self, modifier_name: str, item_type: str = "bagel") -> float:
        """
        Look up price modifier for a bagel add-on (protein, cheese, topping).

        Searches the item_types attribute options for matching modifier prices.
        Falls back to DEFAULT_MODIFIER_PRICES if not found in menu_data.

        Args:
            modifier_name: Name of the modifier (e.g., "ham", "egg", "american")
            item_type: Item type to look up (default "bagel", falls back to "sandwich")

        Returns:
            Price modifier (e.g., 2.00 for ham) or 0.0 if not found
        """
        modifier_lower = modifier_name.lower()

        # Try menu_data first if available
        if self.menu_data:
            item_types = self.menu_data.get("item_types", {})

            # Try the specified item type first, then fall back to sandwich
            types_to_check = [item_type, "sandwich"] if item_type != "sandwich" else ["sandwich"]

            for type_slug in types_to_check:
                type_data = item_types.get(type_slug, {})
                attributes = type_data.get("attributes", [])

                # Search through all attributes (protein, cheese, toppings, etc.)
                for attr in attributes:
                    options = attr.get("options", [])
                    for opt in options:
                        # Match by slug or display_name
                        if opt.get("slug", "").lower() == modifier_lower or \
                           opt.get("display_name", "").lower() == modifier_lower:
                            price = opt.get("price_modifier", 0.0)
                            if price > 0:
                                logger.debug(
                                    "Found modifier price: %s = $%.2f (from %s.%s)",
                                    modifier_name, price, type_slug, attr.get("slug")
                                )
                                return price

        # Fall back to default prices
        default_price = self.DEFAULT_MODIFIER_PRICES.get(modifier_lower, 0.0)
        if default_price > 0:
            logger.debug(
                "Using default modifier price: %s = $%.2f",
                modifier_name, default_price
            )
        return default_price

    def _lookup_spread_price(self, spread: str, spread_type: str | None = None) -> float:
        """
        Look up price for a spread, considering the spread type/flavor.

        First tries the full spread name (e.g., "Tofu Cream Cheese") from cheese_prices,
        then falls back to DEFAULT_MODIFIER_PRICES for generic spread.

        Args:
            spread: Base spread name (e.g., "cream cheese")
            spread_type: Spread flavor/variant (e.g., "tofu", "scallion")

        Returns:
            Price for the spread
        """
        # Build full spread name by combining type + spread (e.g., "tofu cream cheese")
        if spread_type:
            full_spread_name = f"{spread_type} {spread}".lower()
        else:
            full_spread_name = spread.lower()

        # Try cheese_prices from menu_data first
        if self.menu_data:
            cheese_prices = self.menu_data.get("cheese_prices", {})

            # Try full name first (e.g., "tofu cream cheese")
            if full_spread_name in cheese_prices:
                price = cheese_prices[full_spread_name]
                logger.debug(
                    "Found spread price from cheese_prices: %s = $%.2f",
                    full_spread_name, price
                )
                return price

            # Try without type as fallback (e.g., "plain cream cheese" or just "cream cheese")
            spread_lower = spread.lower()
            plain_spread = f"plain {spread_lower}"
            if plain_spread in cheese_prices:
                price = cheese_prices[plain_spread]
                logger.debug(
                    "Found spread price from cheese_prices (plain): %s = $%.2f",
                    plain_spread, price
                )
                return price

        # Fall back to DEFAULT_MODIFIER_PRICES
        default_price = self.DEFAULT_MODIFIER_PRICES.get(spread.lower(), 0.0)
        if default_price > 0:
            logger.debug(
                "Using default spread price: %s = $%.2f",
                spread, default_price
            )
        return default_price

    def _calculate_bagel_price_with_modifiers(
        self,
        base_price: float,
        sandwich_protein: str | None,
        extras: list[str] | None,
        spread: str | None,
        spread_type: str | None = None,
    ) -> float:
        """
        Calculate total bagel price including modifiers.

        Args:
            base_price: Base bagel price
            sandwich_protein: Primary protein (e.g., "ham")
            extras: Additional modifiers (e.g., ["egg", "american"])
            spread: Spread choice (e.g., "cream cheese")
            spread_type: Spread flavor/variant (e.g., "tofu", "scallion")

        Returns:
            Total price including all modifiers
        """
        total = base_price

        # Add protein price
        if sandwich_protein:
            total += self._lookup_modifier_price(sandwich_protein)

        # Add extras prices
        if extras:
            for extra in extras:
                total += self._lookup_modifier_price(extra)

        # Add spread price (if not "none")
        if spread and spread.lower() != "none":
            total += self._lookup_spread_price(spread, spread_type)

        return round(total, 2)

    def recalculate_bagel_price(self, item: BagelItemTask) -> float:
        """
        Recalculate and update a bagel item's price based on its current modifiers.

        This should be called whenever a bagel's modifiers change (spread, protein, extras)
        to ensure price is always in sync with the item's state.

        Args:
            item: The bagel item to update

        Returns:
            The new calculated price
        """
        # Get base price from bagel type
        base_price = self._lookup_bagel_price(item.bagel_type)

        # Calculate total with all current modifiers
        new_price = self._calculate_bagel_price_with_modifiers(
            base_price,
            item.sandwich_protein,
            item.extras,
            item.spread,
            item.spread_type,
        )

        # Update the item's price
        item.unit_price = new_price

        logger.debug(
            "Recalculated bagel price: base=%.2f, protein=%s, extras=%s, spread=%s (%s) -> total=%.2f",
            base_price, item.sandwich_protein, item.extras, item.spread, item.spread_type, new_price
        )

        return new_price

    def _lookup_coffee_modifier_price(self, modifier_name: str, modifier_type: str = "syrup") -> float:
        """
        Look up price modifier for a coffee add-on (syrup, milk, size).

        Searches the attribute_options for matching modifier prices.
        """
        if not modifier_name:
            return 0.0

        modifier_lower = modifier_name.lower().strip()

        # Try to find in item_types attribute options
        if self.menu_data:
            item_types = self.menu_data.get("item_types", {})
            # item_types is a dict with type slugs as keys
            for type_slug, type_data in item_types.items():
                if not isinstance(type_data, dict):
                    continue
                attrs = type_data.get("attributes", [])
                for attr in attrs:
                    if not isinstance(attr, dict):
                        continue
                    attr_slug = attr.get("slug", "")
                    # Match by modifier type (syrup, milk, size)
                    if modifier_type in attr_slug or attr_slug == modifier_type:
                        options = attr.get("options", [])
                        for opt in options:
                            if not isinstance(opt, dict):
                                continue
                            opt_slug = opt.get("slug", "").lower()
                            opt_name = opt.get("display_name", "").lower()
                            if modifier_lower in opt_slug or modifier_lower in opt_name or opt_slug in modifier_lower:
                                price = opt.get("price_modifier", 0.0)
                                if price > 0:
                                    logger.debug(
                                        "Found coffee modifier price: %s = $%.2f (from %s)",
                                        modifier_name, price, attr_slug
                                    )
                                    return price

        # Default coffee modifier prices
        default_prices = {
            # Size upcharges (relative to small)
            "medium": 0.50,
            "large": 1.00,
            # Milk alternatives
            "oat": 0.50,
            "oat milk": 0.50,
            "almond": 0.50,
            "almond milk": 0.50,
            "soy": 0.50,
            "soy milk": 0.50,
            # Flavor syrups
            "vanilla": 0.65,
            "vanilla syrup": 0.65,
            "hazelnut": 0.65,
            "hazelnut syrup": 0.65,
            "caramel": 0.65,
            "caramel syrup": 0.65,
            "peppermint": 1.00,
            "peppermint syrup": 1.00,
        }

        return default_prices.get(modifier_lower, 0.0)

    def _calculate_coffee_price_with_modifiers(
        self,
        base_price: float,
        size: str | None,
        milk: str | None,
        flavor_syrup: str | None,
    ) -> float:
        """
        Calculate total coffee price including modifiers.

        Args:
            base_price: Base coffee price (usually for small size)
            size: Size selection (small, medium, large)
            milk: Milk choice (regular, oat, almond, soy)
            flavor_syrup: Flavor syrup (vanilla, hazelnut, etc.)

        Returns:
            Total price including all modifiers
        """
        total = base_price

        # Add size upcharge (small is base price, medium/large have upcharges)
        if size and size.lower() not in ("small", "s"):
            size_upcharge = self._lookup_coffee_modifier_price(size, "size")
            total += size_upcharge
            if size_upcharge > 0:
                logger.debug("Coffee size upcharge: %s = +$%.2f", size, size_upcharge)

        # Add milk alternative upcharge (regular milk is free)
        if milk and milk.lower() not in ("regular", "whole", "2%", "skim", "none", "no milk"):
            milk_upcharge = self._lookup_coffee_modifier_price(milk, "milk")
            total += milk_upcharge
            if milk_upcharge > 0:
                logger.debug("Coffee milk upcharge: %s = +$%.2f", milk, milk_upcharge)

        # Add flavor syrup upcharge
        if flavor_syrup:
            syrup_upcharge = self._lookup_coffee_modifier_price(flavor_syrup, "syrup")
            total += syrup_upcharge
            if syrup_upcharge > 0:
                logger.debug("Coffee syrup upcharge: %s = +$%.2f", flavor_syrup, syrup_upcharge)

        return total

    def recalculate_coffee_price(self, item: CoffeeItemTask) -> float:
        """
        Recalculate and update a coffee item's price based on its current modifiers.

        Args:
            item: The CoffeeItemTask to recalculate

        Returns:
            The new calculated price
        """
        # Get base price from drink type
        base_price = self._lookup_coffee_price(item.drink_type)
        total = base_price

        # Calculate and store individual upcharges
        # Size upcharge (small is base price)
        size_upcharge = 0.0
        if item.size and item.size.lower() not in ("small", "s"):
            size_upcharge = self._lookup_coffee_modifier_price(item.size, "size")
            total += size_upcharge
        item.size_upcharge = size_upcharge

        # Milk alternative upcharge (regular milk is free)
        milk_upcharge = 0.0
        if item.milk and item.milk.lower() not in ("regular", "whole", "2%", "skim", "none", "no milk"):
            milk_upcharge = self._lookup_coffee_modifier_price(item.milk, "milk")
            total += milk_upcharge
        item.milk_upcharge = milk_upcharge

        # Flavor syrup upcharge
        syrup_upcharge = 0.0
        if item.flavor_syrup:
            syrup_upcharge = self._lookup_coffee_modifier_price(item.flavor_syrup, "syrup")
            total += syrup_upcharge
        item.syrup_upcharge = syrup_upcharge

        # Update the item's price
        item.unit_price = total

        logger.info(
            "Recalculated coffee price: base=$%.2f + size=$%.2f + milk=$%.2f + syrup=$%.2f -> total=$%.2f",
            base_price, size_upcharge, milk_upcharge, syrup_upcharge, total
        )

        return total
