"""
State Machine for Order Flow.

This module provides a deterministic state machine approach to order capture.
Instead of one large parser trying to interpret everything, each state has
its own focused parser that can only produce valid outputs for that state.

Key insight: When pending_item_id points to an incomplete item, ALL input
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
from .checkout_handler import CheckoutHandler
from .menu_item_config_handler import MenuItemConfigHandler
from .store_info_handler import StoreInfoHandler
from .menu_inquiry_handler import MenuInquiryHandler
from .order_utils_handler import OrderUtilsHandler
from .item_adder_handler import ItemAdderHandler
from .checkout_utils_handler import CheckoutUtilsHandler
from .config_helper_handler import ConfigHelperHandler
from .modifier_change_handler import ModifierChangeHandler
from .slot_orchestration_handler import SlotOrchestrationHandler
from .configuring_item_handler import ConfiguringItemHandler
from .taking_items_handler import TakingItemsHandler
from .handler_config import HandlerConfig

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
)
from .parsers.quantity_utils import extract_make_it_n_target
from .handler_utils import get_last_item

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
    text = user_input.lower().strip()

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
    (pending_item_id is set), we use a constrained parser that can ONLY
    interpret input as answers for that item. No new items can be created.
    """

    def __init__(self, menu_data: dict | None = None, model: str = "gpt-4o-mini"):
        # Use provided menu_data, fall back to global, then empty dict
        self._menu_data = menu_data if menu_data is not None else (_global_menu_data or {})
        self.model = model
        # Initialize slot orchestration handler early (needed for callbacks)
        self.slot_orchestration_handler = SlotOrchestrationHandler()
        # Initialize menu lookup engine
        self.menu_lookup = MenuLookup(self._menu_data)
        # Initialize pricing engine with menu lookup callback
        self.pricing = PricingEngine(self._menu_data, self.menu_lookup.lookup_menu_item)
        # Initialize message builder
        self.message_builder = MessageBuilder()
        # =====================================================================
        # Handler Initialization Order
        # =====================================================================
        # Handlers are initialized in dependency order. Some callbacks must be
        # set post-init due to circular dependencies:
        #   1. checkout_utils_handler.get_next_question -> HandlerConfig
        #   2. checkout_handler needs order_utils, checkout_utils, taking_items
        #   3. checkout_utils_handler needs _configure_next_incomplete_item
        #   4. configuring_item_handler needs taking_items_handler
        # =====================================================================

        # Create shared handler configuration (callbacks added incrementally)
        self._handler_config = HandlerConfig(
            model=self.model,
            pricing=self.pricing,
            menu_lookup=self.menu_lookup,
            menu_data=self._menu_data,
            message_builder=self.message_builder,
            check_redirect=_check_redirect_to_pending_item,
        )

        # Phase 1: Core utility handlers
        self.checkout_handler = CheckoutHandler(
            config=self._handler_config,
            transition_callback=self._transition_to_next_slot,
        )
        self.checkout_utils_handler = CheckoutUtilsHandler(
            config=self._handler_config,
            transition_to_next_slot=self._transition_to_next_slot,
        )
        # Wire: get_next_question callback (required by other handlers)
        self._handler_config.get_next_question = self.checkout_utils_handler.get_next_question

        # Phase 2: Independent handlers (no cross-dependencies)
        self.store_info_handler = StoreInfoHandler(menu_data=self._menu_data)
        self.menu_inquiry_handler = MenuInquiryHandler(config=self._handler_config)
        self.order_utils_handler = OrderUtilsHandler(
            config=self._handler_config,
            build_order_summary=self.checkout_utils_handler.build_order_summary,
        )
        self.item_adder_handler = ItemAdderHandler(config=self._handler_config)
        self.modifier_change_handler = ModifierChangeHandler(config=self._handler_config)
        self.config_helper_handler = ConfigHelperHandler(
            config=self._handler_config,
            modifier_change_handler=self.modifier_change_handler,
        )

        # Phase 3: Wire cross-handler callbacks (circular dependencies)
        self.checkout_handler.order_utils_handler = self.order_utils_handler
        self.checkout_handler._handle_taking_items_with_parsed = self._handle_taking_items_with_parsed

        # Phase 4: Handlers that depend on Phase 2 handlers
        self.menu_item_handler = MenuItemConfigHandler(config=self._handler_config)
        self.item_adder_handler.menu_item_handler = self.menu_item_handler
        self.checkout_utils_handler._configure_next_incomplete_item = self._configure_next_incomplete_item

        self.configuring_item_handler = ConfiguringItemHandler(
            config_helper_handler=self.config_helper_handler,
            checkout_utils_handler=self.checkout_utils_handler,
            modifier_change_handler=self.modifier_change_handler,
            item_adder_handler=self.item_adder_handler,
            menu_item_handler=self.menu_item_handler,
        )
        self.taking_items_handler = TakingItemsHandler(
            config=self._handler_config,
            item_adder_handler=self.item_adder_handler,
            menu_inquiry_handler=self.menu_inquiry_handler,
            store_info_handler=self.store_info_handler,
            checkout_utils_handler=self.checkout_utils_handler,
            checkout_handler=self.checkout_handler,
        )

        # Phase 5: Final cross-handler wiring
        self.configuring_item_handler.taking_items_handler = self.taking_items_handler
        # Wire up callback for processing pending parsed items after disambiguation
        # This enables MenuItemConfigHandler to process items that were stored during
        # multi-item order disambiguation (e.g., "latte and bagel" where bagel is stored
        # while we disambiguate and configure the latte)
        self.menu_item_handler.process_pending_parsed_items = (
            self.configuring_item_handler._process_pending_parsed_items
        )

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
            self.store_info_handler,
            self.menu_inquiry_handler,
            self.item_adder_handler,
            self.taking_items_handler,
        ]

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

        # Distribute to all handlers
        self.checkout_handler.set_context(ctx)
        self.store_info_handler.set_context(ctx)
        self.order_utils_handler.set_context(ctx)
        self.checkout_utils_handler.set_context(ctx)
        self.taking_items_handler.set_context(ctx)
        self.item_adder_handler.set_context(ctx)

        return ctx

    def process(
        self,
        user_input: str,
        order: OrderTask | None = None,
        returning_customer: dict | None = None,
        store_info: dict | None = None,
        db_session=None,
    ) -> StateMachineResult:
        """
        Process user input through the state machine.

        Args:
            user_input: What the user said
            order: Current order (None for new conversation)
            returning_customer: Returning customer data (name, phone, last_order_items)
            store_info: Store configuration (delivery_zip_codes, tax rates, etc.)
            db_session: SQLAlchemy session for database operations (request-scoped)

        Returns:
            StateMachineResult with response message and updated order
        """
        if order is None:
            order = OrderTask()

        # Reset repeat order flag - only set when user explicitly requests repeat order
        # This prevents the flag from persisting across different sessions on the singleton
        if not hasattr(self, '_is_repeat_order') or order.items.get_item_count() == 0:
            self._is_repeat_order = False
            self._last_order_type = None

        # Update all handlers with unified context
        self._update_handler_context(store_info, returning_customer, db_session)

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
            target_qty = extract_make_it_n_target(make_it_n_match)
            if target_qty:
                active_items = order.items.get_active_items()
                if active_items:
                    last_item = get_last_item(active_items)
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
                        order.items.add_item(last_item.duplicate())

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
            # Intentionally stay in TAKING_ITEMS - don't auto-transition to checkout
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
            result = self.checkout_handler.handle_confirmation(user_input, order)
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


