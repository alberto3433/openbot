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
from .pending_fields import PendingField
from .models import (
    OrderTask,
    MenuItemTask,
)
from .schemas import OrderPhase, StateMachineResult, OpenInputResponse, Selection
from .slot_orchestrator import SlotOrchestrator, SlotCategory
from ..menu_data_cache import menu_cache
from .parsers import (
    validate_email_address,
    validate_phone_number,
    parse_confirmation,
    parse_open_input,
    TAX_QUESTION_PATTERN,
)
from .parsers.deterministic import MAKE_IT_N_PATTERN
from .parsers.quantity_utils import extract_make_it_n_target
from .parsers.llm_parsers import (
    parse_name,
    parse_payment_method,
    parse_phone,
    parse_email,
)
from .handler_config import BaseHandler
from .handler_utils import get_last_item
from .normalization import format_slug_for_display
from .utils.text import number_to_word
from .delivery_handler import DeliveryHandler

if TYPE_CHECKING:
    from .handler_config import HandlerConfig

logger = logging.getLogger(__name__)


class CheckoutHandler(BaseHandler):
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
        super().__init__(config)

        # Handler-specific dependencies and callbacks
        self.order_utils_handler = order_utils_handler
        self._transition_to_next_slot = transition_callback
        self._handle_taking_items_with_parsed = handle_taking_items_with_parsed

        # Sub-handlers
        self._delivery_handler = DeliveryHandler(config)

        # Context set per-request
        self._returning_customer: dict | None = None
        self._is_repeat_order: bool = False
        self._last_order_type: str | None = None

    # Note: _modifier_category_keywords and _modifier_item_keywords are
    # inherited from MenuDataMixin via BaseHandler

    def set_context(self, ctx: "OrderContext") -> None:
        """Set per-request context for checkout handling."""
        self._store_info = ctx.store_info
        self._returning_customer = ctx.returning_customer
        self._is_repeat_order = ctx.is_repeat_order
        self._last_order_type = ctx.last_order_type
        self._menu_data = ctx.menu_data
        # Pass context to sub-handlers
        self._delivery_handler.set_context(ctx)
        self._delivery_handler.set_message_builder(self.message_builder)

    def _finalize_order(
        self,
        order: OrderTask,
        contact_value: str,
        contact_type: str,
    ) -> None:
        """Finalize order: set payment, store contact, generate order number.

        Args:
            order: The order to finalize.
            contact_value: Validated phone number or email address.
            contact_type: Either "phone" or "email".
        """
        order.payment.method = "card_link"
        if contact_type == "phone":
            order.customer_info.phone = contact_value
        else:
            order.customer_info.email = contact_value
        order.payment.payment_link_destination = contact_value
        order.checkout.generate_order_number()
        order.checkout.confirmed = True
        if self._transition_to_next_slot:
            self._transition_to_next_slot(order)

    def _complete_order_with_contact(
        self,
        order: OrderTask,
        contact_value: str,
        contact_type: str,
    ) -> StateMachineResult:
        """Finalize order and return completion result with appropriate message.

        Args:
            order: The order to finalize.
            contact_value: Validated phone number or email address.
            contact_type: Either "phone" or "email".

        Returns:
            StateMachineResult with completion message.
        """
        self._finalize_order(order, contact_value, contact_type)

        if contact_type == "phone":
            confirmation_text = "We'll text you when it's ready."
        else:
            confirmation_text = f"We'll send the confirmation to {contact_value}."

        return StateMachineResult(
            message=f"Your order number is {order.checkout.short_order_number}. "
                   f"{confirmation_text} Thank you, {order.customer_info.name}!",
            order=order,
            is_complete=True,
        )

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

        # After collecting name, show order summary and ask for confirmation
        order.set_phase(OrderPhase.CHECKOUT_CONFIRM)
        summary = self.message_builder.build_order_summary(order)
        return StateMachineResult(
            message=f"{summary}\n\nDoes that look right?",
            order=order,
        )

    def handle_payment_method(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle text or email choice for order details."""
        parsed = parse_payment_method(user_input, model=self.model)

        if parsed.choice == "unclear":
            return StateMachineResult(
                message=CheckoutMessages.PAYMENT_METHOD,
                order=order,
            )

        if parsed.choice == "text":
            # Text selected - set payment method and check for phone
            order.payment.method = "card_link"
            phone = parsed.phone_number or order.customer_info.phone
            if phone:
                validated_phone, error = self._validate_contact(phone, validate_phone_number, "phone")
                if error:
                    if self._transition_to_next_slot:
                        self._transition_to_next_slot(order)
                    return StateMachineResult(message=error, order=order)
                return self._complete_order_with_contact(order, validated_phone, "phone")
            else:
                # Need to ask for phone number - orchestrator will say NOTIFICATION
                if self._transition_to_next_slot:
                    self._transition_to_next_slot(order)
                return StateMachineResult(
                    message=CheckoutMessages.PHONE_FOR_TEXT,
                    order=order,
                )

        if parsed.choice == "email":
            # Email selected - set payment method and check for email
            order.payment.method = "card_link"
            if parsed.email_address:
                validated_email, error = self._validate_contact(parsed.email_address, validate_email_address, "email")
                if error:
                    order.set_phase(OrderPhase.CHECKOUT_EMAIL)
                    return StateMachineResult(message=error, order=order)
                return self._complete_order_with_contact(order, validated_email, "email")
            else:
                # Need to ask for email - explicitly set CHECKOUT_EMAIL phase
                # (orchestrator maps NOTIFICATION to CHECKOUT_PHONE by default)
                order.set_phase(OrderPhase.CHECKOUT_EMAIL)
                return StateMachineResult(
                    message=CheckoutMessages.EMAIL_FOR_SEND,
                    order=order,
                )

        return StateMachineResult(
            message=CheckoutMessages.PAYMENT_METHOD,
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

    def _handle_contact_input(
        self,
        user_input: str,
        order: OrderTask,
        parser_func: Callable,
        field_name: str,
        validator_func: Callable,
        contact_type: str,
        retry_message: str,
    ) -> StateMachineResult:
        """Generic handler for contact info (phone/email) collection.

        Args:
            user_input: User's raw input
            order: Current order state
            parser_func: Parser function (parse_phone or parse_email)
            field_name: Attribute name on parsed result ('phone' or 'email')
            validator_func: Validation function for the contact type
            contact_type: Type string for logging and completion ('phone' or 'email')
            retry_message: Message to show if parsing fails

        Returns:
            StateMachineResult with validation error or completed order
        """
        parsed = parser_func(user_input, model=self.model)
        parsed_value = getattr(parsed, field_name, None)

        if not parsed_value:
            return StateMachineResult(message=retry_message, order=order)

        validated_value, error = self._validate_contact(parsed_value, validator_func, contact_type)
        if error:
            return StateMachineResult(message=error, order=order)

        return self._complete_order_with_contact(order, validated_value, contact_type)

    def handle_phone(self, user_input: str, order: OrderTask) -> StateMachineResult:
        """Handle phone number collection for text confirmation."""
        return self._handle_contact_input(
            user_input, order,
            parser_func=parse_phone,
            field_name="phone",
            validator_func=validate_phone_number,
            contact_type="phone",
            retry_message=CheckoutMessages.PHONE_RETRY,
        )

    def handle_email(self, user_input: str, order: OrderTask) -> StateMachineResult:
        """Handle email address collection."""
        return self._handle_contact_input(
            user_input, order,
            parser_func=parse_email,
            field_name="email",
            validator_func=validate_email_address,
            contact_type="email",
            retry_message=CheckoutMessages.EMAIL_RETRY,
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

        parsed = parse_confirmation(user_input, model=self.model)
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

        active_items = order.items.get_active_items()
        if not active_items:
            return None

        last_item = get_last_item(active_items)
        last_item_name = last_item.get_summary()
        added_count = target_qty - 1

        for _ in range(added_count):
            order.items.add_item(last_item.duplicate())

        logger.info("CONFIRMATION: Added %d more of '%s'", added_count, last_item_name)

        # Return to confirmation with updated summary
        summary = self.message_builder.build_order_summary(order)

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
            extracted_selections = list(first_item.modifiers) if first_item.modifiers else None

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
        """Handle user confirming the order."""
        # Mark order as reviewed but not yet fully confirmed
        order.checkout.order_reviewed = True

        # For returning customers, auto-send to their last used contact method
        if self._returning_customer:
            # Prefer email if available, otherwise use phone
            email = self._returning_customer.get("email") or order.customer_info.email
            phone = self._returning_customer.get("phone") or order.customer_info.phone

            if email:
                # Auto-send to email
                self._finalize_order(order, email, "email")
                return StateMachineResult(
                    message=f"An email with a payment link has been sent to {email}. "
                           f"Your order number is {order.checkout.short_order_number}. "
                           f"Thank you, {order.customer_info.name}!",
                    order=order,
                    is_complete=True,
                )
            elif phone:
                # Auto-send to phone
                self._finalize_order(order, phone, "phone")
                return StateMachineResult(
                    message=f"A text with a payment link has been sent to {phone}. "
                           f"Your order number is {order.checkout.short_order_number}. "
                           f"Thank you, {order.customer_info.name}!",
                    order=order,
                    is_complete=True,
                )

        # Use orchestrator to determine next phase (should be PAYMENT_METHOD)
        if self._transition_to_next_slot:
            self._transition_to_next_slot(order)
        return StateMachineResult(
            message=CheckoutMessages.PAYMENT_METHOD,
            order=order,
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
