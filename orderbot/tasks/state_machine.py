"""
State Machine for Order Flow.

This module provides a deterministic state machine approach to order capture.
Instead of one large parser trying to interpret everything, each state has
its own focused parser that can only produce valid outputs for that state.

Key insight: When pending_item_ids points to an incomplete item, ALL input
is interpreted in the context of that item - no new items can be created.
"""

import logging

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
)
from .utils.text import normalize_text, name_with_prefix
from .parsers.deterministic.text_cleaning import _collapse_repeated_words

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
            message=f"Let's finish up {name_with_prefix('your', item_desc)} first. {question}",
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

        # Phase -> handler dispatch (built once, not per-call)
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
    def store_and_scheduling_handler(self):
        return self._registry.store_and_scheduling

    @property
    def order_modification_handler(self):
        return self._registry.order_modification

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

    def _record_result(
        self, order: OrderTask, result: StateMachineResult | None,
    ) -> StateMachineResult | None:
        """Record an assistant message if result is truthy, then return it.

        Centralizes the common pattern of:
            if result:
                order.add_message("assistant", result.message)
            return result
        """
        if result:
            order.add_message("assistant", result.message)
        return result

    # Standard pending-state dispatchers. Each entry maps (field_name, handler_getter).
    # The loop checks the field, calls the handler, records the message, and returns.
    _PENDING_DISPATCHERS: list[tuple[str, str, str]] = [
        ("pending_order_history", "order_history_handler", "handle_order_history_selection"),
        ("pending_reorder_items", "order_history_handler", "handle_reorder_item_selection"),
        ("pending_reorder_offer_items", "order_history_handler", "handle_reorder_offer_response"),
        ("pending_change_clarification", "config_helper_handler", "handle_change_clarification_response"),
        ("pending_store_hours_inquiry", "store_info_handler", "handle_store_hours_followup"),
    ]

    def _dispatch_pending_states(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        """Check pending state flags and dispatch to appropriate handler.

        Returns a result if a pending state handled the input, None to
        fall through to normal processing.
        """
        for field_name, handler_attr, method_name in self._PENDING_DISPATCHERS:
            if getattr(order, field_name):
                handler = getattr(self, handler_attr)
                result = self._record_result(
                    order, getattr(handler, method_name)(user_input, order)
                )
                if result:
                    return result

        # Special case: store change with replay logic
        if order.pending_store_change:
            return self._handle_pending_store_change(user_input, order)

        # Special case: scheduling with fallback hint
        if order.pending_scheduling:
            return self._handle_pending_scheduling(user_input, order)

        return None

    def _handle_pending_store_change(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle pending store change with order-text replay after confirmation."""
        store_result = self.store_and_scheduling_handler.handle_store_selection(user_input, order)
        if not store_result:
            return None
        order.add_message("assistant", store_result.message)
        # After first-time store confirmation, replay the saved item order
        if order.store_confirmed and order.pending_store_order_text:
            saved_text = order.pending_store_order_text
            order.pending_store_order_text = None
            logger.info("Replaying saved order text after store selection: '%s'", saved_text)
            replay_result = self.taking_items_handler.handle_taking_items(saved_text, order)
            order.add_message("assistant", replay_result.message)
            combined_msg = f"{store_result.message}\n\n{replay_result.message}"
            return StateMachineResult(
                message=combined_msg,
                order=replay_result.order,
                quick_replies=replay_result.quick_replies,
            )
        return store_result

    def _handle_pending_scheduling(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle pending scheduling with fallback hint on invalid input."""
        order.pending_scheduling = False
        scheduling_result = self.store_and_scheduling_handler.handle_scheduling_expression(user_input, order)
        if scheduling_result:
            order.add_message("assistant", scheduling_result.message)
            return scheduling_result
        hint = (
            "I didn't catch that. You can say something like "
            '"3pm", "in 30 minutes", or "tomorrow at noon".'
        )
        order.add_message("assistant", hint)
        return StateMachineResult(message=hint, order=order)

    def process(
        self,
        user_input: str,
        order: OrderTask | None = None,
        returning_customer: dict | None = None,
        store_info: dict | None = None,
        db_session=None,
        item_id: str | None = None,
        add_item: bool = False,
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
        # Collapse stuttered words (e.g., "no no changes" → "no changes")
        user_input = _collapse_repeated_words(user_input)

        order = self._initialize_order(order, returning_customer, store_info, db_session)

        # Store add_item flag on order for dispatch routing
        order._add_item_flag = add_item

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
        result = self.order_modification_handler.handle_id_based_removal(item_id, order)
        if result:
            order.add_message("user", user_input)
            order.add_message("assistant", result.message)
            return result
        return None

    def _derive_phase(self, order: OrderTask) -> None:
        """Derive the current phase from OrderTask state via orchestrator."""
        # Don't overwrite checkout phases that are explicitly set by handlers
        phases_to_preserve = {p.value for p in OrderPhase if p.value.startswith("checkout_")}
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
            if getattr(order, '_add_item_flag', False):
                # Menu item click during config: route to taking_items to add the new item
                return self._handle_taking_items(user_input, order)
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

        Order matters -- e.g. make-it-N must precede modifier change,
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

    # -- Extracted global-pattern helpers --

    def _check_order_status_inquiry(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        if not ORDER_STATUS_PATTERN.search(user_input):
            return None
        logger.info("ORDER STATUS: User asked for order status")
        return self._record_result(order, self.order_utils_handler.handle_order_status(order))

    def _check_order_history_inquiry(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        if not self.order_history_handler.is_order_history_inquiry(user_input):
            return None
        logger.info("ORDER HISTORY: User asked for order history")
        return self._record_result(order, self.order_history_handler.handle_order_history_inquiry(order))

    def _check_view_last_order(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        if not self.order_history_handler.is_view_last_order(user_input):
            return None
        logger.info("ORDER HISTORY: User asked for last order details")
        return self._record_result(order, self.order_history_handler.handle_view_last_order(order))

    def _check_make_it_n_pattern(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        """Must precede modifier change to avoid 'make that two' being parsed as a modifier."""
        return self._record_result(order, self.order_modification_handler.handle_make_it_n(user_input, order))

    def _check_store_change_pattern(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        """Must precede modifier change handler which would interpret 'change store' as a modifier."""
        if not STORE_CHANGE_PATTERN.search(user_input):
            return None
        logger.info("STORE CHANGE: User requested store change")
        return self.store_and_scheduling_handler.handle_store_change_request(order)

    def _check_order_type_change_pattern(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        """Must precede modifier change to avoid 'delivery' being treated as a modifier."""
        if not order.delivery_method.order_type:
            return None
        return self._record_result(
            order, self.order_modification_handler.handle_order_type_change(user_input, order)
        )

    def _check_modifier_change_pattern(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        if order.items.get_item_count() == 0 or order.is_configuring_item():
            return None
        return self._record_result(
            order, self.config_helper_handler.handle_modifier_change_request(user_input, order)
        )

    def _check_scheduling_patterns(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        # Early scheduling intent (e.g., "can I pickup my order later?")
        if PICKUP_LATER_PATTERN.search(user_input):
            order.delivery_method.order_type = "pickup"
            return self.store_and_scheduling_handler.handle_scheduling_change_request(order)

        # Scheduling change request (e.g., "change pickup time")
        if TIME_UPDATE_PATTERN.search(user_input):
            return self.store_and_scheduling_handler.handle_scheduling_change_request(order)

        # "Choose a time" response from scheduling quick replies
        if TIME_SELECTION_PATTERN.search(user_input):
            msg = (
                'Sure! Just tell me the time \u2014 for example, '
                '"3pm", "tomorrow at noon", or "in 2 hours".'
            )
            order.pending_scheduling = True
            order.add_message("assistant", msg)
            return StateMachineResult(message=msg, order=order)

        # Time/scheduling expressions (e.g., "pickup at 3pm") -- only when
        # input doesn't look like an item order and we're not configuring an item
        if not _looks_like_new_order_attempt(user_input) and not order.is_configuring_item():
            result = self._record_result(
                order, self.store_and_scheduling_handler.handle_scheduling_expression(user_input, order)
            )
            if result:
                return result

        return None

    def _check_customer_info_change_pattern(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        return self._record_result(
            order, self.order_modification_handler.handle_customer_info_change(user_input, order)
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
