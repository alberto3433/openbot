"""
Checkout Handler for Order State Machine.

This module handles the entire checkout flow including:
- Delivery method selection and address collection
- Customer name collection
- Order confirmation
- Payment method choice
- Contact info collection
- Repeat order processing

Consolidated from checkout_handler.py and confirmation_handler.py.
"""

import logging
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .context import OrderContext

from .checkout_messages import CheckoutMessages
from .models import (
    OrderTask,
    MenuItemTask,
)
from .schemas import OrderPhase, StateMachineResult, OpenInputResponse, Selection
from .slot_orchestrator import SlotOrchestrator, SlotCategory
from ..cache import menu_cache
from .parsers import (
    validate_email_address,
    validate_phone_number,
    parse_open_input,
    TAX_QUESTION_PATTERN,
)
from .parsers.deterministic import MAKE_IT_N_PATTERN
from .parsers.quantity_utils import extract_make_it_n_target
from .parsers.validators import (
    parse_name_deterministic as parse_name,
    parse_phone_deterministic as parse_phone,
    parse_email_deterministic as parse_email,
)
from .parsers.validators import (
    parse_confirmation_deterministic,
)
from .handler_config import BaseStateHandler
from .handler_utils import get_last_item, duplicate_last_item_to_qty
from .normalization import format_slug_for_display
from .utils.text import normalize_text, number_to_word
from .delivery_handler import DeliveryHandler

if TYPE_CHECKING:
    from .handler_config import HandlerConfig

logger = logging.getLogger(__name__)


class CheckoutHandler(BaseStateHandler):
    """
    Handles the entire checkout flow for orders.

    Manages delivery method selection, address collection, customer name,
    order confirmation, payment method choice, contact information collection,
    and repeat order processing.
    """

    def __init__(
        self,
        config: "HandlerConfig",
        order_utils_handler: "OrderUtilsHandler | None" = None,
        transition_callback: Callable[[OrderTask], None] | None = None,
        handle_taking_items_with_parsed: Callable[
            [OpenInputResponse, OrderTask, list[Selection] | None, str], StateMachineResult
        ] | None = None,
    ):
        """
        Initialize the checkout handler.

        Args:
            config: HandlerConfig with shared dependencies.
            order_utils_handler: Handler for order utilities (tax, quantity changes).
            transition_callback: Callback function to transition order to next slot.
            handle_taking_items_with_parsed: Callback to handle parsed items during confirmation.
        """
        super().__init__(config, transition_callback=transition_callback)

        # Handler-specific dependencies and callbacks
        self.order_utils_handler = order_utils_handler
        self._handle_taking_items_with_parsed = handle_taking_items_with_parsed

        # Sub-handlers
        self._delivery_handler = DeliveryHandler(config)

    # Note: _modifier_category_keywords and _modifier_item_keywords are
    # inherited from MenuDataMixin via BaseHandler

    def _propagate_context(self, ctx: "OrderContext") -> None:
        """Propagate context to sub-handlers."""
        self._delivery_handler.set_context(ctx)
        self._delivery_handler.set_message_builder(self.message_builder)

    def _finalize_order(self, order: OrderTask) -> None:
        """Finalize order: generate order number, mark confirmed.

        Does NOT set payment method — that is chosen by the user in the
        CHECKOUT_PAYMENT_METHOD phase.

        Args:
            order: The order to finalize.
        """
        # Set payment link destination to email (preferred) or phone
        destination = order.customer_info.email or order.customer_info.phone
        if destination:
            order.payment.payment_link_destination = destination
        order.checkout.generate_order_number()
        order.checkout.confirmed = True
        if self._transition_to_next_slot:
            self._transition_to_next_slot(order)

    def handle_delivery(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle pickup/delivery selection and address collection.

        Delegates to DeliveryHandler for all delivery-related logic.
        """
        return self._delivery_handler.handle_delivery(
            user_input, order, self._transition_to_next_slot
        )

    def handle_name(
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
        if self._transition_to_next_slot:
            self._transition_to_next_slot(order)

        return StateMachineResult(
            message=CheckoutMessages.EMAIL,
            order=order,
        )

    def _validate_contact(
        self, value: str, validator_func: Callable, contact_type: str
    ) -> tuple[str | None, str | None]:
        """Validate contact value and log on error.

        Args:
            value: The contact value to validate
            validator_func: Validation function (validate_phone_number or validate_email_address)
            contact_type: Type for logging ('phone' or 'email')

        Returns:
            Tuple of (validated_value, error_message). If validation fails,
            validated_value is None and error_message contains the error.
        """
        validated, error = validator_func(value)
        if error:
            logger.info("%s validation failed for '%s': %s", contact_type.capitalize(), value, error)
        return validated, error

    def handle_email(self, user_input: str, order: OrderTask) -> StateMachineResult:
        """Handle email address collection."""
        parsed = parse_email(user_input, model=self.model)
        parsed_value = getattr(parsed, "email", None)

        if not parsed_value:
            return StateMachineResult(
                message=CheckoutMessages.EMAIL_RETRY,
                order=order,
            )

        validated_value, error = self._validate_contact(
            parsed_value, validate_email_address, "email",
        )
        if error:
            return StateMachineResult(message=error, order=order)

        order.customer_info.email = validated_value
        if self._transition_to_next_slot:
            self._transition_to_next_slot(order)

        # Orchestrator will determine next phase (phone if needed, or confirm)
        orchestrator = SlotOrchestrator(order)
        next_slot = orchestrator.get_next_slot()

        if next_slot and next_slot.category == SlotCategory.CUSTOMER_PHONE:
            return StateMachineResult(
                message=CheckoutMessages.PHONE,
                order=order,
            )

        # Phone already known — go to confirmation
        summary = self.message_builder.build_order_summary(order)
        return StateMachineResult(
            message=f"{summary}\n\nDoes that look right?",
            order=order,
        )

    def handle_phone(self, user_input: str, order: OrderTask) -> StateMachineResult:
        """Handle phone number collection."""
        parsed = parse_phone(user_input, model=self.model)
        parsed_value = getattr(parsed, "phone", None)

        if not parsed_value:
            return StateMachineResult(
                message=CheckoutMessages.PHONE_RETRY,
                order=order,
            )

        validated_value, error = self._validate_contact(
            parsed_value, validate_phone_number, "phone",
        )
        if error:
            return StateMachineResult(message=error, order=order)

        order.customer_info.phone = validated_value
        if self._transition_to_next_slot:
            self._transition_to_next_slot(order)

        # After phone, go to confirmation
        summary = self.message_builder.build_order_summary(order)
        return StateMachineResult(
            message=f"{summary}\n\nDoes that look right?",
            order=order,
        )

    # =========================================================================
    # Order Confirmation Methods (consolidated from confirmation_handler.py)
    # =========================================================================

    def handle_confirmation(
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
            if self.order_utils_handler:
                return self.order_utils_handler.handle_tax_question(order)

        # Check for quantity change patterns (e.g., "make it two orange juices")
        if self.order_utils_handler:
            quantity_result = self.order_utils_handler.handle_quantity_change(user_input, order)
            if quantity_result:
                return quantity_result

        # Check for "make it 2" pattern (duplicate last item) - deterministic, no LLM needed
        make_it_n_match = MAKE_IT_N_PATTERN.match(user_input.strip())
        if make_it_n_match:
            result = self._handle_make_it_n(make_it_n_match, order)
            if result:
                return result

        parsed = parse_confirmation_deterministic(user_input)
        logger.info("CONFIRMATION: parse result - wants_changes=%s, confirmed=%s, asks_about_tax=%s",
                   parsed.wants_changes, parsed.confirmed, parsed.asks_about_tax)

        # Handle tax question from LLM parse as fallback
        if parsed.asks_about_tax:
            logger.info("CONFIRMATION: Tax question detected (LLM)")
            if self.order_utils_handler:
                return self.order_utils_handler.handle_tax_question(order)

        if parsed.wants_changes:
            return self._handle_wants_changes(user_input, order)

        if parsed.confirmed:
            return self._handle_confirmed(order)

        return StateMachineResult(
            message="Does the order look correct?",
            order=order,
        )

    def _handle_make_it_n(self, match, order: OrderTask) -> StateMachineResult | None:
        """Handle 'make it N' pattern to duplicate items."""
        target_qty = extract_make_it_n_target(match)
        if not target_qty:
            return None

        result = duplicate_last_item_to_qty(
            order, target_qty, mark_complete=True, count_existing=False,
        )
        if result is None:
            return None

        target_qty, _, _ = result

        # Return to confirmation with updated summary
        summary = self.message_builder.build_order_summary(order)

        return StateMachineResult(
            message=f"Sure, that's {target_qty} total.\n\n{summary}\n\nDoes that look right?",
            order=order,
        )

    def _handle_wants_changes(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user wanting to make changes during confirmation."""
        # User wants to make changes - reset order_reviewed so orchestrator knows
        order.checkout.order_reviewed = False

        # Try to parse the input for new items
        item_parsed = parse_open_input(
            user_input,
            model=self.model,
            modifier_category_keywords=self._modifier_category_keywords,
            modifier_item_keywords=self._modifier_item_keywords,
        )
        logger.info("CONFIRMATION: parse_open_input result - parsed_items=%d",
                   len(item_parsed.parsed_items))

        # If they mentioned a new item, process it
        if item_parsed.parsed_items:
            logger.info("CONFIRMATION: Detected new item! Processing via _handle_taking_items_with_parsed")
            # Get selections directly from the parsed item
            first_item = item_parsed.parsed_items[0]
            extracted_selections = list(first_item.selections) if first_item.selections else None

            # Use orchestrator to determine phase before processing
            if self._transition_to_next_slot:
                self._transition_to_next_slot(order)

            if self._handle_taking_items_with_parsed:
                result = self._handle_taking_items_with_parsed(item_parsed, order, extracted_selections, user_input)

                # Log items in result.order vs original order
                logger.info("CONFIRMATION: result.order items = %s", [i.get_summary() for i in result.order.items.items])
                logger.info("CONFIRMATION: original order items = %s", [i.get_summary() for i in order.items.items])
                logger.info("CONFIRMATION: result.order.phase = %s", result.order.phase)

                # If there are pending drink options awaiting clarification, return that result
                if result.order.pending_item_options:
                    logger.info("CONFIRMATION: Pending drink options, returning clarification message")
                    return result

                # Use orchestrator to determine if we should go back to confirmation
                orchestrator = SlotOrchestrator(result.order)
                next_slot = orchestrator.get_next_slot()

                if (next_slot and next_slot.category == SlotCategory.ORDER_CONFIRM and
                    result.order.customer_info.name and
                    result.order.delivery_method.order_type):
                    logger.info("CONFIRMATION: Item added, returning to confirmation (orchestrator says ORDER_CONFIRM)")
                    if self._transition_to_next_slot:
                        self._transition_to_next_slot(result.order)
                    summary = self.message_builder.build_order_summary(result.order)
                    logger.info("CONFIRMATION: Built summary, items count = %d", len(result.order.items.items))
                    return StateMachineResult(
                        message=f"{summary}\n\nDoes that look right?",
                        order=result.order,
                    )

                return result

        # No new item detected, use orchestrator to determine phase
        if self._transition_to_next_slot:
            self._transition_to_next_slot(order)
        return StateMachineResult(
            message="No problem. What would you like to change?",
            order=order,
        )

    def _handle_confirmed(self, order: OrderTask) -> StateMachineResult:
        """Handle user confirming the order.

        Verifies all required slots are filled before finalizing.
        If email or phone is missing, redirects to collect them first.
        """
        # Guard: ensure required customer info is collected before finalizing
        if not order.customer_info.email:
            order.set_phase(OrderPhase.CHECKOUT_EMAIL)
            return StateMachineResult(
                message=CheckoutMessages.EMAIL,
                order=order,
            )
        if not order.customer_info.phone:
            order.set_phase(OrderPhase.CHECKOUT_PHONE)
            return StateMachineResult(
                message=CheckoutMessages.PHONE,
                order=order,
            )

        order.checkout.order_reviewed = True
        self._finalize_order(order)

        # Transition to payment method choice
        order.set_phase(OrderPhase.CHECKOUT_PAYMENT_METHOD)

        return StateMachineResult(
            message="Thank you! Would you like to pay online or pay in store?",
            order=order,
            is_complete=False,
            quick_replies=[
                {"label": "Pay online", "value": "pay online", "url": "__PAYMENT_URL__"},
                {"label": "Pay in store", "value": "pay in store"},
            ],
        )

    def handle_payment_choice(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user's payment method choice (pay online vs pay in store).

        Args:
            user_input: User's input text
            order: The current order task
        """
        text = normalize_text(user_input)

        # "Pay in store" patterns
        in_store_patterns = [
            "in store", "in-store", "in person", "at the store",
            "at pickup", "at the counter", "when i get there",
            "pay later", "pay there", "pay when",
        ]
        # "Pay online" patterns
        online_patterns = [
            "online", "pay now", "card", "credit", "debit",
            "stripe", "pay online",
        ]

        is_in_store = any(p in text for p in in_store_patterns)
        is_online = any(p in text for p in online_patterns)

        if is_in_store and not is_online:
            order.payment.method = "card_in_store"
            return StateMachineResult(
                message=f"Your order number is {order.checkout.short_order_number}. "
                       f"Thank you, {order.customer_info.name}!",
                order=order,
                is_complete=True,
            )

        if is_online and not is_in_store:
            order.payment.method = "card_link"
            return StateMachineResult(
                message=f"Your order number is {order.checkout.short_order_number}. "
                       f"Thank you, {order.customer_info.name}!",
                order=order,
                is_complete=True,
                quick_replies=[
                    {"label": "Pay online", "value": "pay online", "url": "__PAYMENT_URL__"},
                ],
            )

        # Unrecognized — re-ask
        return StateMachineResult(
            message="Would you like to pay online or pay in store?",
            order=order,
            is_complete=False,
            quick_replies=[
                {"label": "Pay online", "value": "pay online", "url": "__PAYMENT_URL__"},
                {"label": "Pay in store", "value": "pay in store"},
            ],
        )

    def handle_repeat_order(
        self,
        order: OrderTask,
        returning_customer: dict | None = None,
        set_repeat_info_callback: Callable[[bool, str | None], None] | None = None,
    ) -> StateMachineResult:
        """
        Handle a request to repeat the customer's previous order.

        Copies items from returning_customer.last_order_items to the current order.
        """
        customer = returning_customer or self._returning_customer

        if not customer:
            logger.info("Repeat order requested but no returning customer data")
            return StateMachineResult(
                message="I don't have a previous order on file for you. What can I get for you today?",
                order=order,
            )

        last_order_items = customer.get("last_order_items", [])
        if not last_order_items:
            logger.info("Repeat order requested but no last_order_items in returning_customer")
            return StateMachineResult(
                message="I don't have a previous order on file for you. What can I get for you today?",
                order=order,
            )

        # Copy items from previous order
        items_added = []
        for prev_item in last_order_items:
            item_type = prev_item.get("item_type")
            if not item_type:
                logger.error(
                    "Previous order item missing required 'item_type' field. "
                    "Item data: %s",
                    prev_item
                )
                continue

            menu_item_name = prev_item.get("menu_item_name")
            quantity = prev_item.get("quantity", 1)
            qty_word = number_to_word(quantity)

            # Add item using generic data-driven method
            self._add_repeat_item(prev_item, order, quantity, qty_word, items_added)

        # Copy customer info if available (name, phone, email)
        if customer.get("name") and not order.customer_info.name:
            order.customer_info.name = customer["name"]
        if customer.get("phone") and not order.customer_info.phone:
            order.customer_info.phone = customer["phone"]
        if customer.get("email") and not order.customer_info.email:
            order.customer_info.email = customer["email"]

        # Store last order type for "pickup again?" / "delivery again?" prompt
        if customer.get("last_order_type") and set_repeat_info_callback:
            set_repeat_info_callback(True, customer["last_order_type"])

        logger.info("Repeat order: added %d item types from previous order", len(items_added))

        # Build confirmation message
        if items_added:
            items_str = ", ".join(items_added)
            order.set_phase(OrderPhase.TAKING_ITEMS)
            return StateMachineResult(
                message=f"Got it, I've added your previous order: {items_str}. Anything else?",
                order=order,
            )
        else:
            return StateMachineResult(
                message="I couldn't find any items in your previous order. What can I get for you today?",
                order=order,
            )

    def _add_repeat_item(
        self,
        prev_item: dict,
        order: OrderTask,
        quantity: int,
        qty_word: str,
        items_added: list[str],
    ) -> None:
        """Add a repeated item to the order (generic, data-driven).

        This method handles all item types by copying attribute_values from
        the previous order's item_config. It replaces the type-specific methods
        (_add_repeat_bagel, _add_repeat_coffee, _add_repeat_menu_item) with a
        single data-driven implementation.
        """
        # Get item type and name
        item_type = prev_item.get("menu_item_type") or prev_item.get("item_type")
        menu_item_name = prev_item.get("menu_item_name")
        # Derive name from item_type if not provided
        if not menu_item_name and item_type:
            menu_item_name = menu_cache.get_item_type_display_name(item_type) or format_slug_for_display(item_type, check_cache=False)
        menu_item_name = menu_item_name or "Item"
        price = prev_item.get("price", 0)

        # Create MenuItemTask
        item = MenuItemTask(
            menu_item_name=menu_item_name,
            menu_item_type=item_type,
            unit_price=price,
        )

        # Copy attribute_values if present (contains full nested structure)
        # This preserves all configuration from the original order
        if "attribute_values" in prev_item and prev_item["attribute_values"]:
            item.attribute_values = prev_item["attribute_values"].copy()
        else:
            # Fallback: copy individual top-level keys that match known attributes
            # This handles older orders that may not have attribute_values
            known_attrs = set()
            if item_type:
                known_attrs = set(menu_cache.get_item_type_attributes(item_type).keys())

            # Also include common attribute keys that might be in legacy data
            # These are keys that aren't metadata (quantity, price, etc.)
            metadata_keys = {
                "item_type", "menu_item_type", "menu_item_name", "menu_item_id",
                "quantity", "price", "modifiers", "attribute_values", "base_price",
                "display_name", "free_details", "customization_offered",
            }

            for key, value in prev_item.items():
                if key in metadata_keys:
                    continue
                # Copy if it's a known attribute OR if we don't have known attrs
                # (i.e., item_type not in DB, so accept all keys)
                if value is not None and (key in known_attrs or not known_attrs):
                    item[key] = value

        # Mark complete and add to order
        item.mark_complete()
        for _ in range(quantity):
            order.items.add_item(item.duplicate())

        # Build description using the item's data-driven get_summary() method
        items_added.append(f"{qty_word} {item.get_summary()}")

    # Note: _quantity_to_words() has been consolidated into utils/text.py as number_to_word().
