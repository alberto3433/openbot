"""
State Machine for Order Flow.

This module provides a deterministic state machine approach to order capture.
Instead of one large parser trying to interpret everything, each state has
its own focused parser that can only produce valid outputs for that state.

Key insight: When pending_item_ids points to an incomplete item, ALL input
is interpreted in the context of that item - no new items can be created.
"""

import logging
import re

from .models import (
    OrderTask,
    MenuItemTask,
    ItemTask,
    TaskStatus,
)
from .context import OrderContext
from .pricing import PricingEngine
from .menu_lookup import MenuLookup
from .message_builder import MessageBuilder
from .handler_config import HandlerConfig
from .handler_registry import HandlerRegistry

# Import from new modular structure
from .schemas import (
    OrderPhase,
    StateMachineResult,
    OpenInputResponse,
    Selection,
)
from .parsers import (
    # Deterministic parsers - Compiled patterns
    ORDER_STATUS_PATTERN,
    # Unified data-driven pattern for detecting new item orders
    _get_configurable_item_pattern,
    ORDERING_LANGUAGE_PATTERN,
    # Scheduling patterns
    PICKUP_LATER_PATTERN,
    TIME_UPDATE_PATTERN,
    TIME_SELECTION_PATTERN,
    # Order management patterns
    STORE_CHANGE_PATTERN,
    ORDER_TYPE_CHANGE_PATTERN,
)
from .parsers.quantity_utils import extract_make_it_n_target
from .parsers.time_parser import parse_time_expression
from .handler_utils import (
    get_last_item,
    duplicate_last_item_to_qty,
    handle_make_it_one,
    handle_already_at_target,
)
from .checkout_messages import (
    CheckoutMessages,
    already_have_n_anything_else,
    thats_n_total_anything_else,
)
from .utils.text import normalize_text

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

    Uses a unified data-driven pattern that matches:
    - Item type triggers from database (bagel, latte, sandwich, etc.)
    - Attribute option words from database (small, large, iced, hot, etc.)
    - Ordering language phrases (I'd like, can I get, etc.)
    """
    text = normalize_text(user_input)

    # Pattern: explicit ordering language ("I'd like", "can I get", "I want")
    if ORDERING_LANGUAGE_PATTERN.search(text):
        return True

    # Pattern: any configurable item keyword from database
    if _get_configurable_item_pattern().search(text):
        return True

    return False


def _get_pending_item_description(item: "ItemTask") -> str:
    """Get a short description of the pending item for redirect messages.

    Uses the item's display name - no domain-specific logic.
    """
    if isinstance(item, MenuItemTask):
        # Use menu_item_name for all item types (data-driven)
        return item.menu_item_name or "item"
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
        text_lower = normalize_text(user_input)
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


# Global menu data for tests - set by conftest.py fixture
_global_menu_data: dict | None = None


def set_global_menu_data(menu_data: dict | None) -> None:
    """Set global menu data for use when OrderStateMachine is created without menu_data.

    This is primarily used by test fixtures to provide menu data without
    requiring each test to explicitly pass it.
    """
    global _global_menu_data
    _global_menu_data = menu_data


class OrderStateMachine:
    """
    State machine for order capture.

    The key principle: when we're waiting for input on a specific item
    (pending_item_ids is set), we use a constrained parser that can ONLY
    interpret input as answers for that item. No new items can be created.
    """

    def __init__(self, menu_data: dict | None = None, model: str = "gpt-4o-mini"):
        # Use provided menu_data, fall back to global, then empty dict
        self._menu_data = menu_data if menu_data is not None else (_global_menu_data or {})
        self.model = model

        # Initialize core components
        self.menu_lookup = MenuLookup(self._menu_data)
        self.pricing = PricingEngine(self._menu_data, self.menu_lookup.lookup_menu_item)
        self.message_builder = MessageBuilder()

        # Create shared handler configuration
        self._handler_config = HandlerConfig(
            model=self.model,
            pricing=self.pricing,
            menu_lookup=self.menu_lookup,
            menu_data=self._menu_data,
            message_builder=self.message_builder,
            check_redirect=_check_redirect_to_pending_item,
        )

        # Initialize all handlers via registry
        self._registry = HandlerRegistry(
            config=self._handler_config,
            transition_callback=self._transition_to_next_slot,
            handle_taking_items_with_parsed=self._handle_taking_items_with_parsed,
            configure_next_incomplete_item=self._configure_next_incomplete_item,
        )

        # Phase → handler dispatch (built once, not per-call)
        self._phase_dispatch = {
            OrderPhase.GREETING.value: self._handle_greeting,
            OrderPhase.TAKING_ITEMS.value: self._handle_taking_items,
            OrderPhase.CHECKOUT_DELIVERY.value: self.checkout_handler.handle_delivery,
            OrderPhase.CHECKOUT_NAME.value: self.checkout_handler.handle_name,
            OrderPhase.CHECKOUT_EMAIL.value: self.checkout_handler.handle_email,
            OrderPhase.CHECKOUT_PHONE.value: self.checkout_handler.handle_phone,
            OrderPhase.CHECKOUT_CONFIRM.value: self.checkout_handler.handle_confirmation,
            OrderPhase.CHECKOUT_PAYMENT_METHOD.value: self.checkout_handler.handle_payment_choice,
        }

    # Handler accessors via registry
    @property
    def slot_orchestration_handler(self):
        return self._registry.slot_orchestration

    @property
    def checkout_handler(self):
        return self._registry.checkout

    @property
    def checkout_utils_handler(self):
        return self._registry.checkout_utils

    @property
    def store_info_handler(self):
        return self._registry.store_info

    @property
    def menu_inquiry_handler(self):
        return self._registry.menu_inquiry

    @property
    def order_utils_handler(self):
        return self._registry.order_utils

    @property
    def item_adder_handler(self):
        return self._registry.item_adder

    @property
    def modifier_change_handler(self):
        return self._registry.modifier_change

    @property
    def config_helper_handler(self):
        return self._registry.config_helper

    @property
    def menu_item_handler(self):
        return self._registry.menu_item

    @property
    def configuring_item_handler(self):
        return self._registry.configuring_item

    @property
    def taking_items_handler(self):
        return self._registry.taking_items

    @property
    def order_history_handler(self):
        return self._registry.order_history

    @property
    def menu_data(self) -> dict:
        return self._menu_data

    @menu_data.setter
    def menu_data(self, value: dict) -> None:
        self._menu_data = value or {}
        # Propagate to all menu_data-dependent components
        for handler in self._get_menu_data_handlers():
            handler.menu_data = self._menu_data

    def _get_menu_data_handlers(self) -> list:
        """Return all handlers/components that need menu_data updates."""
        return [
            self._handler_config,
            self.menu_lookup,
            self.pricing,
        ] + self._registry.get_menu_data_handlers()

    def _update_handler_context(
        self,
        store_info: dict | None,
        returning_customer: dict | None,
        db_session=None,
    ) -> OrderContext:
        """
        Create and distribute context to all handlers.

        This centralizes context distribution that was previously scattered
        across multiple set_context/set_store_info/set_repeat_order_info calls.

        Args:
            store_info: Store configuration (delivery zones, tax rates, etc.)
            returning_customer: Returning customer data if available
            db_session: SQLAlchemy session for database operations (request-scoped)

        Returns:
            The created OrderContext for reference
        """
        # Create callback for repeat order info updates
        def set_repeat_info(is_repeat: bool, last_order_type: str | None) -> None:
            self._is_repeat_order = is_repeat
            self._last_order_type = last_order_type
            # Also update checkout_utils_handler when repeat info changes
            self.checkout_utils_handler.set_context(OrderContext(
                is_repeat_order=is_repeat,
                last_order_type=last_order_type,
            ))

        # Create unified context
        ctx = OrderContext(
            store_info=store_info or {},
            returning_customer=returning_customer,
            is_repeat_order=getattr(self, '_is_repeat_order', False),
            last_order_type=getattr(self, '_last_order_type', None),
            menu_data=self._menu_data,
            set_repeat_info_callback=set_repeat_info,
            db_session=db_session,
        )

        # Store on instance for reference
        self._returning_customer = returning_customer
        self._store_info = store_info or {}

        # Distribute to all handlers via registry
        self._registry.distribute_context(ctx)

        return ctx

    def _dispatch_pending_states(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        """Check pending state flags and dispatch to appropriate handler.

        Returns a result if a pending state handled the input, None to
        fall through to normal processing.
        """
        if order.pending_order_history:
            result = self.order_history_handler.handle_order_history_selection(
                user_input, order
            )
            if result:
                order.add_message("assistant", result.message)
                return result

        if order.pending_reorder_items:
            result = self.order_history_handler.handle_reorder_item_selection(
                user_input, order
            )
            if result:
                order.add_message("assistant", result.message)
                return result

        if order.pending_reorder_offer_items:
            result = self.order_history_handler.handle_reorder_offer_response(
                user_input, order
            )
            if result:
                order.add_message("assistant", result.message)
                return result

        if order.pending_change_clarification:
            result = self.config_helper_handler.handle_change_clarification_response(
                user_input, order
            )
            if result:
                order.add_message("assistant", result.message)
                return result
            # If no result, the response wasn't understood - fall through to normal processing

        if order.pending_store_change:
            store_result = self._handle_store_selection(user_input, order)
            if store_result:
                order.add_message("assistant", store_result.message)
                return store_result

        if order.pending_store_hours_inquiry:
            hours_result = self.store_info_handler.handle_store_hours_followup(user_input, order)
            if hours_result:
                order.add_message("assistant", hours_result.message)
                return hours_result

        if order.pending_scheduling:
            order.pending_scheduling = False
            scheduling_result = self._handle_scheduling_expression(user_input, order)
            if scheduling_result:
                order.add_message("assistant", scheduling_result.message)
                return scheduling_result
            # Input wasn't a valid time expression — give a hint
            hint = (
                "I didn't catch that. You can say something like "
                '"3pm", "in 30 minutes", or "tomorrow at noon".'
            )
            order.add_message("assistant", hint)
            return StateMachineResult(message=hint, order=order)

        return None

    def process(
        self,
        user_input: str,
        order: OrderTask | None = None,
        returning_customer: dict | None = None,
        store_info: dict | None = None,
        db_session=None,
        item_id: str | None = None,
    ) -> StateMachineResult:
        """
        Process user input through the state machine.

        Args:
            user_input: What the user said
            order: Current order (None for new conversation)
            returning_customer: Returning customer data (name, phone, last_order_items)
            store_info: Store configuration (delivery_zip_codes, tax rates, etc.)
            db_session: SQLAlchemy session for database operations (request-scoped)
            item_id: Optional item ID for targeted cart operations (e.g., remove by ID)

        Returns:
            StateMachineResult with response message and updated order
        """
        order = self._initialize_order(order, returning_customer, store_info, db_session)

        # ID-based removal: bypass parsing entirely when item_id is provided
        id_result = self._handle_id_removal(item_id, user_input, order)
        if id_result:
            return id_result

        # Add user message to history
        order.add_message("user", user_input)

        # Run global pattern checks (order status, history, pending states, make-it-N, modifier change)
        global_result = self._check_global_patterns(user_input, order)
        if global_result:
            return global_result

        self._derive_phase(order)

        logger.info("STATE MACHINE: Processing '%s' in phase %s (pending_field=%s, pending_items=%s)",
                   user_input[:50], order.phase, order.pending_field, order.pending_item_ids)

        result = self._dispatch_to_handler(user_input, order)

        # Add bot message to history
        order.add_message("assistant", result.message)

        # Log slot comparison for debugging
        self._log_slot_comparison(order)

        return result

    def _initialize_order(
        self,
        order: OrderTask | None,
        returning_customer: dict | None,
        store_info: dict | None,
        db_session: object,
    ) -> OrderTask:
        """Set up order, reset flags, update context, and pre-fill customer info."""
        if order is None:
            order = OrderTask()

        # Reset repeat order flag - only set when user explicitly requests repeat order
        # This prevents the flag from persisting across different sessions on the singleton
        if not hasattr(self, '_is_repeat_order') or order.items.get_item_count() == 0:
            self._is_repeat_order = False
            self._last_order_type = None

        # Update all handlers with unified context
        self._update_handler_context(store_info, returning_customer, db_session)

        # Pre-fill customer info from returning customer data (name, phone, email)
        if returning_customer:
            if returning_customer.get("name") and not order.customer_info.name:
                order.customer_info.name = returning_customer["name"]
            if returning_customer.get("phone") and not order.customer_info.phone:
                order.customer_info.phone = returning_customer["phone"]
            if returning_customer.get("email") and not order.customer_info.email:
                order.customer_info.email = returning_customer["email"]

        return order

    def _handle_id_removal(
        self,
        item_id: str | None,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle ID-based item removal, bypassing parsing."""
        if not item_id:
            return None
        result = self._handle_id_based_removal(item_id, order)
        if result:
            order.add_message("user", user_input)
            order.add_message("assistant", result.message)
            return result
        return None

    def _derive_phase(self, order: OrderTask) -> None:
        """Derive the current phase from OrderTask state via orchestrator."""
        # Don't overwrite checkout phases that are explicitly set by handlers
        phases_to_preserve = {
            OrderPhase.CHECKOUT_DELIVERY.value,
            OrderPhase.CHECKOUT_NAME.value,
            OrderPhase.CHECKOUT_EMAIL.value,
            OrderPhase.CHECKOUT_PHONE.value,
            OrderPhase.CHECKOUT_CONFIRM.value,
            OrderPhase.CHECKOUT_PAYMENT_METHOD.value,
        }
        # CRITICAL: Don't transition from TAKING_ITEMS at the start of processing!
        # We need to parse the user's input first to see if they're adding more items.
        # The ITEMS slot being "complete" (all items configured) doesn't mean the user
        # is done ordering - they might say "and also a latte" after completing a bagel.
        # The transition to checkout should only happen in _handle_taking_items when
        # the user explicitly says they're done (done_ordering=True).
        if order.phase == OrderPhase.TAKING_ITEMS.value and order.items.get_item_count() > 0:
            pass  # Intentionally stay in TAKING_ITEMS
        elif not order.is_configuring_item() and order.phase not in phases_to_preserve:
            self._transition_to_next_slot(order)

    def _dispatch_to_handler(
        self, user_input: str, order: OrderTask
    ) -> StateMachineResult:
        """Route to the appropriate handler based on current phase."""
        if order.is_configuring_item():
            return self._handle_configuring_item(user_input, order)

        handler = self._phase_dispatch.get(order.phase)
        if handler:
            return handler(user_input, order)

        return StateMachineResult(
            message="I'm not sure what to do. Can you try again?",
            order=order,
        )

    def _check_global_patterns(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Check global patterns that apply regardless of current phase.

        Order matters — e.g. make-it-N must precede modifier change,
        store change must precede modifier change, etc.

        Returns:
            StateMachineResult if a global pattern matched, None otherwise.
        """
        return (
            self._check_order_status_inquiry(user_input, order)
            or self._check_order_history_inquiry(user_input, order)
            or self._check_view_last_order(user_input, order)
            or self._dispatch_pending_states(user_input, order)
            or self._check_make_it_n_pattern(user_input, order)
            or self._check_store_change_pattern(user_input, order)
            or self._check_order_type_change_pattern(user_input, order)
            or self._check_modifier_change_pattern(user_input, order)
            or self._check_scheduling_patterns(user_input, order)
            or self._check_customer_info_change_pattern(user_input, order)
        )

    # ── Extracted global-pattern helpers ─────────────────────────────

    def _check_order_status_inquiry(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        if not ORDER_STATUS_PATTERN.search(user_input):
            return None
        logger.info("ORDER STATUS: User asked for order status")
        result = self.order_utils_handler.handle_order_status(order)
        order.add_message("assistant", result.message)
        return result

    def _check_order_history_inquiry(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        if not self.order_history_handler.is_order_history_inquiry(user_input):
            return None
        logger.info("ORDER HISTORY: User asked for order history")
        result = self.order_history_handler.handle_order_history_inquiry(order)
        if result:
            order.add_message("assistant", result.message)
        return result

    def _check_view_last_order(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        if not self.order_history_handler.is_view_last_order(user_input):
            return None
        logger.info("ORDER HISTORY: User asked for last order details")
        result = self.order_history_handler.handle_view_last_order(order)
        if result:
            order.add_message("assistant", result.message)
        return result

    def _check_make_it_n_pattern(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        """Must precede modifier change to avoid 'make that two' being parsed as a modifier."""
        result = self._handle_make_it_n(user_input, order)
        if result:
            order.add_message("assistant", result.message)
        return result

    def _check_store_change_pattern(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        """Must precede modifier change handler which would interpret 'change store' as a modifier."""
        if not STORE_CHANGE_PATTERN.search(user_input):
            return None
        logger.info("STORE CHANGE: User requested store change")
        return self._handle_store_change_request(order)

    def _check_order_type_change_pattern(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        """Must precede modifier change to avoid 'delivery' being treated as a modifier."""
        if not order.delivery_method.order_type:
            return None
        result = self._handle_order_type_change(user_input, order)
        if result:
            order.add_message("assistant", result.message)
        return result

    def _check_modifier_change_pattern(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        if order.items.get_item_count() == 0 or order.is_configuring_item():
            return None
        result = self.config_helper_handler.handle_modifier_change_request(user_input, order)
        if result:
            order.add_message("assistant", result.message)
        return result

    def _check_scheduling_patterns(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        # Early scheduling intent (e.g., "can I pickup my order later?")
        if PICKUP_LATER_PATTERN.search(user_input):
            order.delivery_method.order_type = "pickup"
            return self._handle_scheduling_change_request(order)

        # Scheduling change request (e.g., "change pickup time")
        if TIME_UPDATE_PATTERN.search(user_input):
            return self._handle_scheduling_change_request(order)

        # "Choose a time" response from scheduling quick replies
        if TIME_SELECTION_PATTERN.search(user_input):
            msg = (
                'Sure! Just tell me the time \u2014 for example, '
                '"3pm", "tomorrow at noon", or "in 2 hours".'
            )
            order.pending_scheduling = True
            order.add_message("assistant", msg)
            return StateMachineResult(message=msg, order=order)

        # Time/scheduling expressions (e.g., "pickup at 3pm") — only when
        # input doesn't look like an item order
        if not _looks_like_new_order_attempt(user_input):
            result = self._handle_scheduling_expression(user_input, order)
            if result:
                order.add_message("assistant", result.message)
                return result

        return None

    def _check_customer_info_change_pattern(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        result = self._handle_customer_info_change(user_input, order)
        if result:
            order.add_message("assistant", result.message)
        return result

    def _handle_order_type_change(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle order type change requests (e.g., 'change it to delivery').

        Detects patterns like "change/switch/make it to delivery/pickup" and
        applies the order type change. If switching to delivery, transitions to
        address collection. If switching to pickup, re-shows confirmation.

        Returns:
            StateMachineResult if an order type change was handled, None otherwise.
        """
        match = ORDER_TYPE_CHANGE_PATTERN.search(user_input)
        if not match:
            return None

        new_type = "delivery" if "deliv" in match.group(1).lower() else "pickup"

        if order.delivery_method.order_type == new_type:
            return None  # Already that type, let other handlers process

        old_type = order.delivery_method.order_type
        order.delivery_method.order_type = new_type
        logger.info("ORDER TYPE CHANGE: %s -> %s", old_type, new_type)

        if new_type == "delivery":
            # Need to collect delivery address
            order.set_phase(OrderPhase.CHECKOUT_DELIVERY)
            return StateMachineResult(
                message="Changed to delivery. What's the delivery address?",
                order=order,
            )
        else:
            # Switching to pickup — clear any delivery address
            from .models.order_flow import AddressTask
            order.delivery_method.address = AddressTask()
            # Re-show order confirmation
            order.set_phase(OrderPhase.CHECKOUT_CONFIRM)
            summary = self.message_builder.build_order_summary(order)
            return StateMachineResult(
                message=f"Changed to pickup. {summary} Does that look right?",
                order=order,
            )

    def _log_slot_comparison(self, order: OrderTask) -> None:
        """Delegate to slot orchestration handler."""
        self.slot_orchestration_handler.log_slot_comparison(order)

    def _transition_to_next_slot(self, order: OrderTask) -> None:
        """Delegate to slot orchestration handler."""
        self.slot_orchestration_handler.transition_to_next_slot(order)

    def _configure_next_incomplete_item(self, order: OrderTask, item: "MenuItemTask | None" = None) -> StateMachineResult:
        """
        Unified callback to configure any incomplete item using data-driven logic.

        Uses item type attributes from database to determine configuration flow,
        rather than hardcoded item type checks.

        Args:
            order: The current order task
            item: Optional specific item to configure. If None, finds first incomplete item.

        Returns:
            StateMachineResult with next question or confirmation
        """
        from .models import MenuItemTask

        # Find the target item if not provided
        # PRIORITY: Configure child items (bundle children) before their parents.
        # This ensures side choices (e.g., bagel with omelette) are fully configured
        # before returning to the parent's remaining questions.
        if item is None:
            # First pass: find child items (items with bundle_parent_item_id)
            for i in order.items.items:
                if isinstance(i, MenuItemTask) and i.status == TaskStatus.IN_PROGRESS:
                    if i.bundle_parent_item_id is not None:
                        item = i
                        break
            # Second pass: if no child found, find any incomplete item
            if item is None:
                for i in order.items.items:
                    if isinstance(i, MenuItemTask) and i.status == TaskStatus.IN_PROGRESS:
                        item = i
                        break

        if item is None or not isinstance(item, MenuItemTask):
            # No incomplete item found - return to checkout flow
            return self.checkout_utils_handler.get_next_question(order)

        # Use menu_item_handler for all item types - it handles data-driven configuration
        return self.menu_item_handler.get_first_question(item, order)

    def _handle_make_it_n(
        self, user_input: str, order: OrderTask
    ) -> StateMachineResult | None:
        """Handle 'make it N' quantity duplication pattern.

        Detects patterns like "make it 2", "actually make that three" and
        duplicates the last item to reach the target quantity.

        Returns:
            StateMachineResult if handled, None otherwise.
        """
        from .parsers.deterministic import MAKE_IT_N_PATTERN

        make_it_n_match = MAKE_IT_N_PATTERN.match(user_input.strip())
        if not make_it_n_match or order.items.get_item_count() == 0:
            return None

        target_qty = extract_make_it_n_target(make_it_n_match)
        if not target_qty:
            return handle_make_it_one(make_it_n_match, order)

        result = duplicate_last_item_to_qty(order, target_qty, count_existing=True)
        if result is None:
            return None

        target_qty, last_item_name, added_count = result

        already = handle_already_at_target(order, target_qty, added_count, last_item_name)
        if already:
            return already

        # If mid-configuration, re-ask the pending config question
        suffix = "Anything else?"
        if order.is_configuring_item() and order.first_pending_item_id:
            config_item = order.items.get_item_by_id(order.first_pending_item_id)
            if config_item:
                question = self.config_helper_handler.get_current_config_question(order, config_item)
                if question:
                    suffix = question

        return StateMachineResult(
            message=f"Sure, that's {target_qty} total. {suffix}",
            order=order,
        )

    def _handle_scheduling_expression(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle time/scheduling expressions like 'pickup at 3pm'.

        Parses time expressions from user input and validates against
        store hours. Sets pickup_time on the delivery method task.

        Returns:
            StateMachineResult if a time expression was handled, None otherwise.
        """
        store_info = getattr(self, '_store_info', {})
        timezone_str = store_info.get("timezone", "America/New_York")

        parsed_time = parse_time_expression(user_input, timezone_str)
        if parsed_time is None:
            return None

        if parsed_time.is_asap:
            order.delivery_method.pickup_time = None
            return StateMachineResult(
                message="Got it, your order will be ready as soon as possible!",
                order=order,
            )

        # Validate against store hours
        from ..services.store_hours import validate_scheduled_time
        hours_config = store_info.get("hours_config")
        is_valid, error_msg = validate_scheduled_time(
            parsed_time.time_value, hours_config, timezone_str,
        )

        if not is_valid:
            return StateMachineResult(
                message=error_msg,
                order=order,
            )

        # Set the pickup time
        order.delivery_method.pickup_time = parsed_time.time_value.isoformat()

        # Format a friendly confirmation
        try:
            display_time = parsed_time.time_value.strftime("%I:%M %p").lstrip("0")
        except ValueError:
            display_time = parsed_time.time_value.strftime("%I:%M %p").lstrip("0")

        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(timezone_str))
        days_ahead = (parsed_time.time_value.date() - now.date()).days
        if days_ahead == 0:
            day_part = "today"
        elif days_ahead == 1:
            day_part = "tomorrow"
        else:
            day_part = parsed_time.time_value.strftime("%A")

        return StateMachineResult(
            message=f"Got it, your order will be scheduled for {day_part} at {display_time}. What can I get you?",
            order=order,
        )

    def _handle_scheduling_change_request(
        self,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle a request to change pickup/delivery time.

        Returns a question with quick reply options for scheduling.
        """
        msg = "When would you like your order ready?"
        order.pending_scheduling = True
        order.add_message("assistant", msg)
        return StateMachineResult(
            message=msg,
            order=order,
            quick_replies=[
                {"label": "As soon as possible", "value": "as soon as possible"},
                {"label": "In 30 minutes", "value": "in 30 minutes"},
                {"label": "In 1 hour", "value": "in 1 hour"},
                {"label": "Choose a time", "value": "I'd like to choose a specific time"},
            ],
        )

    def _handle_store_change_request(
        self,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle a request to change the ordering store.

        Shows "from" as a linkified word. Clicking it triggers the paginated
        store list via _handle_store_selection.
        """
        all_stores = self._store_info.get("all_stores", [])
        if not all_stores or len(all_stores) <= 1:
            msg = "There's only one store available right now."
            order.add_message("assistant", msg)
            return StateMachineResult(message=msg, order=order)

        order.pending_store_change = True
        order.pending_store_page = 0
        msg = "Which store would you like to order from?"
        order.add_message("assistant", msg)
        return StateMachineResult(
            message=msg,
            order=order,
            quick_replies=[{"label": "from", "value": "show stores"}],
        )

    def _handle_store_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle the user's store selection after a pending_store_change prompt.

        Handles three input types:
        1. "show stores" (from clicking the "from" link) — show first page
        2. "what else?" / "show more" — show next page
        3. Store name or ID — change the store

        Sets a transient ``_new_store_id`` key on the order so the message
        processor can update the session.
        """
        from .parsers.constants import DEFAULT_PAGINATION_SIZE

        all_stores = self._store_info.get("all_stores", [])
        text_lower = user_input.strip().lower()

        # --- Show stores / show more ---
        is_show = text_lower == "show stores"
        is_more = text_lower in ("what else?", "what else", "show more", "more")

        if is_show or is_more:
            if is_show:
                order.pending_store_page = 0
            page = order.pending_store_page
            page_size = DEFAULT_PAGINATION_SIZE
            start = page * page_size
            end = start + page_size
            page_stores = all_stores[start:end]
            has_more = end < len(all_stores)

            if not page_stores:
                order.pending_store_page = 0
                msg = "That's all the stores."
                order.pending_store_change = True
                return StateMachineResult(message=msg, order=order)

            # Build short names
            names = []
            for s in page_stores:
                raw = s.get("name", "")
                short = raw.split(" - ")[-1] if " - " in raw else raw
                names.append(short)

            # Format message
            if page == 0:
                if has_more:
                    names_str = ", ".join(names) + ", and more"
                    msg = f"We have {names_str} — want to see more?"
                else:
                    if len(names) > 1:
                        msg = "We have " + ", ".join(names[:-1]) + " or " + names[-1] + "."
                    else:
                        msg = f"We have {names[0]}."
            else:
                if has_more:
                    msg = "We also have " + ", ".join(names) + ", and more."
                else:
                    msg = "And finally, " + ", ".join(names) + ". That's all of them."

            # Build quick replies — each store name linkified + "more" if paginated
            # Use short name as value so it displays nicely as the user message
            qr = []
            for s, short in zip(page_stores, names):
                qr.append({"label": short, "value": short})
            if has_more:
                qr.append({"label": "more", "value": "what else?"})

            order.pending_store_page = page + 1
            order.pending_store_change = True
            return StateMachineResult(message=msg, order=order, quick_replies=qr)

        # --- Store selection by ID or name ---
        matched_store = None
        for s in all_stores:
            if s["store_id"] == user_input.strip():
                matched_store = s
                break
        if not matched_store:
            for s in all_stores:
                name_lower = s.get("name", "").lower()
                short_lower = (
                    name_lower.split(" - ")[-1] if " - " in name_lower else name_lower
                )
                if text_lower in name_lower or text_lower == short_lower:
                    matched_store = s
                    break

        if matched_store:
            order.pending_store_change = False
            order._new_store_id = matched_store["store_id"]
            raw = matched_store.get("name", "")
            short = raw.split(" - ")[-1] if " - " in raw else raw
            return StateMachineResult(
                message=f"Switched to {short}. What can I get you?",
                order=order,
            )

        # No match — re-prompt with "from" link
        order.pending_store_change = True
        msg = "I didn't catch that store. Which store would you like to order from?"
        return StateMachineResult(
            message=msg,
            order=order,
            quick_replies=[{"label": "from", "value": "show stores"}],
        )

    # Compiled pattern for customer info change requests
    _CUSTOMER_INFO_CHANGE_RE = re.compile(
        r'\b(?:change|update|edit)\s+(?:my\s+)?'
        r'(name|phone(?:\s+number)?|email(?:\s+address)?)\b',
        re.IGNORECASE,
    )

    def _handle_customer_info_change(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle requests to change customer name, phone, or email.

        Detects patterns like "change my name", "update my email", etc.
        Clears the relevant field and transitions to the appropriate checkout phase
        so the orchestrator re-collects it.

        Args:
            user_input: The user's input text.
            order: The current order task.

        Returns:
            StateMachineResult if a change was requested, None otherwise.
        """
        match = self._CUSTOMER_INFO_CHANGE_RE.search(user_input)
        if not match:
            return None

        field = match.group(1).lower()

        # Map matched field to (customer_info attr, checkout phase, re-ask message)
        field_map = {
            "name": ("name", OrderPhase.CHECKOUT_NAME, "Sure! What name should I put on the order?"),
            "phone": ("phone", OrderPhase.CHECKOUT_PHONE, CheckoutMessages.PHONE),
            "email": ("email", OrderPhase.CHECKOUT_EMAIL, CheckoutMessages.EMAIL),
        }

        # Normalize "phone number" → "phone", "email address" → "email"
        key = "phone" if field.startswith("phone") else "email" if field.startswith("email") else field
        if key not in field_map:
            return None

        attr, phase, msg = field_map[key]
        if not getattr(order.customer_info, attr):
            return None

        # Save current phase so checkout handlers can restore it after re-collection
        order.return_to_phase = order.phase
        setattr(order.customer_info, attr, None)
        order.checkout.order_reviewed = False
        order.set_phase(phase)
        return StateMachineResult(message=msg, order=order)

    def _handle_id_based_removal(
        self,
        item_id: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle removal of a specific item by its unique ID.

        Called when the frontend passes an item_id (e.g., from the cart X button).
        Bypasses text-based parsing entirely for exact item targeting.

        Args:
            item_id: The unique ID of the item to remove
            order: The current order task

        Returns:
            StateMachineResult if handled, None if item_id is invalid
        """
        from .handler_utils import build_removal_response

        item = order.items.get_active_item_by_id(item_id)
        if item is None:
            return StateMachineResult(
                message="That item has already been removed. Anything else?",
                order=order,
            )

        removed_name = item.get_summary()

        # If the item being removed is currently being configured, clear pending state
        if order.first_pending_item_id == item_id:
            order.clear_pending()
            order.set_phase(OrderPhase.TAKING_ITEMS)

        # Also remove from pending config queue if present
        order.pending_config_queue = [
            entry for entry in order.pending_config_queue
            if not (isinstance(entry, dict) and entry.get("item_id") == item_id)
        ]

        order.items.remove_item_with_bundle(item_id)

        return build_removal_response(
            order,
            removed_name,
            configure_next_incomplete=self._configure_next_incomplete_item,
        )

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
        extracted_modifiers: list[Selection] | None = None,
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
