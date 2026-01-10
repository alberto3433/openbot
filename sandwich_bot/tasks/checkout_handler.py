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
import uuid
from typing import Callable, TYPE_CHECKING

from .checkout_messages import CheckoutMessages
from .models import (
    OrderTask,
    MenuItemTask,
    BagelItemTask,
    TaskStatus,
)
from .schemas import OrderPhase, StateMachineResult, ExtractedModifiers, OpenInputResponse
from .slot_orchestrator import SlotOrchestrator, SlotCategory
from .parsers import (
    validate_email_address,
    validate_phone_number,
    parse_confirmation,
    parse_open_input,
    extract_modifiers_from_input,
    TAX_QUESTION_PATTERN,
)
from .parsers.deterministic import MAKE_IT_N_PATTERN
from .parsers.llm_parsers import (
    parse_delivery_choice,
    parse_name,
    parse_payment_method,
    parse_phone,
    parse_email,
)
from ..address_service import complete_address

if TYPE_CHECKING:
    from .handler_config import HandlerConfig
    from .order_utils_handler import OrderUtilsHandler
    from .checkout_utils_handler import CheckoutUtilsHandler

logger = logging.getLogger(__name__)


class CheckoutHandler:
    """
    Handles the entire checkout flow for orders.

    Manages delivery method selection, address collection, customer name,
    order confirmation, payment method choice, contact information collection,
    and repeat order processing.
    """

    def __init__(
        self,
        config: "HandlerConfig | None" = None,
        order_utils_handler: "OrderUtilsHandler | None" = None,
        checkout_utils_handler: "CheckoutUtilsHandler | None" = None,
        transition_callback: Callable[[OrderTask], None] | None = None,
        handle_taking_items_with_parsed: Callable[
            [OpenInputResponse, OrderTask, ExtractedModifiers, str], StateMachineResult
        ] | None = None,
        **kwargs,
    ):
        """
        Initialize the checkout handler.

        Args:
            config: HandlerConfig with shared dependencies.
            order_utils_handler: Handler for order utilities (tax, quantity changes).
            checkout_utils_handler: Handler for checkout utilities (order summary).
            transition_callback: Callback function to transition order to next slot.
            handle_taking_items_with_parsed: Callback to handle parsed items during confirmation.
            **kwargs: Legacy parameter support.
        """
        if config:
            self.model = config.model
            self.message_builder = config.message_builder
            self._store_info = config.store_info
            self._menu_data = config.menu_data or {}
        else:
            # Legacy support for direct parameters
            self.model = kwargs.get("model", "gpt-4o-mini")
            self.message_builder = kwargs.get("message_builder")
            self._store_info = None
            self._menu_data = {}

        # Handler-specific dependencies and callbacks
        self.order_utils_handler = order_utils_handler or kwargs.get("order_utils_handler")
        self.checkout_utils_handler = checkout_utils_handler or kwargs.get("checkout_utils_handler")
        self._transition_to_next_slot = transition_callback or kwargs.get("transition_callback")
        self._handle_taking_items_with_parsed = handle_taking_items_with_parsed or kwargs.get("handle_taking_items_with_parsed")

        # Context set per-request
        self._returning_customer: dict | None = None
        self._is_repeat_order: bool = False
        self._last_order_type: str | None = None
        self._spread_types: list[str] = []

    @property
    def _modifier_category_keywords(self) -> dict[str, str]:
        """Get modifier category keyword mapping from menu data."""
        modifier_cats = self._menu_data.get("modifier_categories", {})
        return modifier_cats.get("keyword_to_category", {})

    @property
    def _modifier_item_keywords(self) -> dict[str, str]:
        """Get item keyword to item type slug mapping from menu data."""
        return self._menu_data.get("item_keywords", {})

    def set_context(
        self,
        store_info: dict | None = None,
        returning_customer: dict | None = None,
        is_repeat_order: bool = False,
        last_order_type: str | None = None,
        spread_types: list[str] | None = None,
        menu_data: dict | None = None,
    ) -> None:
        """Set per-request context for checkout handling."""
        self._store_info = store_info
        self._returning_customer = returning_customer
        self._is_repeat_order = is_repeat_order
        self._last_order_type = last_order_type
        self._spread_types = spread_types or []
        self._menu_data = menu_data or {}

    def handle_delivery(
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
                message=self.message_builder.get_delivery_question(
                    self._is_repeat_order,
                    self._last_order_type,
                ),
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
            if self._is_repeat_order and self._returning_customer:
                last_address = self._returning_customer.get("last_order_address")
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
        allowed_zips = (self._store_info or {}).get('delivery_zip_codes', [])

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

    def _proceed_after_address(self, order: OrderTask) -> StateMachineResult:
        """Handle transition after delivery address is captured.

        Checks if we already have customer info and skips to confirmation if so.
        """
        if self._transition_to_next_slot:
            self._transition_to_next_slot(order)

        # If we already have the customer name, skip to confirmation
        if order.customer_info.name:
            order.phase = OrderPhase.CHECKOUT_CONFIRM.value
            summary = self.message_builder.build_order_summary(order)
            return StateMachineResult(
                message=f"{summary}\n\nDoes that look right?",
                order=order,
            )

        return StateMachineResult(
            message=CheckoutMessages.NAME,
            order=order,
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
        order.phase = OrderPhase.CHECKOUT_CONFIRM.value
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
                # Validate the phone number
                validated_phone, error_message = validate_phone_number(phone)
                if error_message:
                    logger.info("Phone validation failed for '%s': %s", phone, error_message)
                    # Ask for phone again with the error message
                    if self._transition_to_next_slot:
                        self._transition_to_next_slot(order)
                    return StateMachineResult(
                        message=error_message,
                        order=order,
                    )
                order.customer_info.phone = validated_phone
                order.payment.payment_link_destination = validated_phone
                order.checkout.generate_order_number()
                order.checkout.confirmed = True  # Now fully confirmed
                if self._transition_to_next_slot:
                    self._transition_to_next_slot(order)  # Should be COMPLETE
                return StateMachineResult(
                    message=f"Your order number is {order.checkout.short_order_number}. "
                           f"We'll text you when it's ready. Thank you, {order.customer_info.name}!",
                    order=order,
                    is_complete=True,
                )
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
                if self._transition_to_next_slot:
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
                    message=CheckoutMessages.EMAIL_FOR_SEND,
                    order=order,
                )

        return StateMachineResult(
            message=CheckoutMessages.PAYMENT_METHOD,
            order=order,
        )

    def handle_phone(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle phone number collection for text confirmation."""
        parsed = parse_phone(user_input, model=self.model)

        if not parsed.phone:
            return StateMachineResult(
                message=CheckoutMessages.PHONE_RETRY,
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
        if self._transition_to_next_slot:
            self._transition_to_next_slot(order)  # Should be COMPLETE

        return StateMachineResult(
            message=f"Your order number is {order.checkout.short_order_number}. "
                   f"We'll text you when it's ready. Thank you, {order.customer_info.name}!",
            order=order,
            is_complete=True,
        )

    def handle_email(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle email address collection."""
        parsed = parse_email(user_input, model=self.model)

        if not parsed.email:
            return StateMachineResult(
                message=CheckoutMessages.EMAIL_RETRY,
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
        if self._transition_to_next_slot:
            self._transition_to_next_slot(order)  # Should be COMPLETE

        return StateMachineResult(
            message=f"Your order number is {order.checkout.short_order_number}. "
                   f"We'll send the confirmation to {validated_email}. "
                   f"Thank you, {order.customer_info.name}!",
            order=order,
            is_complete=True,
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
        num_str = None
        for i in range(1, 8):
            if match.group(i):
                num_str = match.group(i).lower()
                break

        if not num_str:
            return None

        word_to_num = {
            "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
        }
        if num_str.isdigit():
            target_qty = int(num_str)
        else:
            target_qty = word_to_num.get(num_str, 0)

        if target_qty < 2:
            return None

        active_items = order.items.get_active_items()
        if not active_items:
            return None

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
        summary = ""
        if self.checkout_utils_handler:
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
            spread_types=self._spread_types,
            modifier_category_keywords=self._modifier_category_keywords,
            modifier_item_keywords=self._modifier_item_keywords,
        )
        logger.info("CONFIRMATION: parse_open_input result - new_menu_item=%s, new_bagel=%s, new_coffee=%s, new_coffee_type=%s, new_signature_item=%s",
                   item_parsed.new_menu_item, item_parsed.new_bagel, item_parsed.new_coffee, item_parsed.new_coffee_type, item_parsed.new_signature_item)

        # If they mentioned a new item, process it
        if item_parsed.new_menu_item or item_parsed.new_bagel or item_parsed.new_coffee or item_parsed.new_signature_item:
            logger.info("CONFIRMATION: Detected new item! Processing via _handle_taking_items_with_parsed")
            extracted_modifiers = extract_modifiers_from_input(user_input)

            # Use orchestrator to determine phase before processing
            if self._transition_to_next_slot:
                self._transition_to_next_slot(order)

            if self._handle_taking_items_with_parsed:
                result = self._handle_taking_items_with_parsed(item_parsed, order, extracted_modifiers, user_input)

                # Log items in result.order vs original order
                logger.info("CONFIRMATION: result.order items = %s", [i.get_summary() for i in result.order.items.items])
                logger.info("CONFIRMATION: original order items = %s", [i.get_summary() for i in order.items.items])
                logger.info("CONFIRMATION: result.order.phase = %s", result.order.phase)

                # If there are pending drink options awaiting clarification, return that result
                if result.order.pending_drink_options:
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
                    summary = ""
                    if self.checkout_utils_handler:
                        summary = self.checkout_utils_handler.build_order_summary(result.order)
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
                order.payment.method = "card_link"
                order.customer_info.email = email
                order.payment.payment_link_destination = email
                order.checkout.generate_order_number()
                order.checkout.confirmed = True
                if self._transition_to_next_slot:
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
                if self._transition_to_next_slot:
                    self._transition_to_next_slot(order)
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
            item_type = prev_item.get("item_type", "sandwich")
            menu_item_name = prev_item.get("menu_item_name")
            quantity = prev_item.get("quantity", 1)
            qty_word = self._quantity_to_words(quantity)

            # Add each item based on type
            if item_type == "bagel":
                self._add_repeat_bagel(prev_item, order, quantity, qty_word, items_added)
            elif item_type in ("coffee", "drink"):
                self._add_repeat_coffee(prev_item, order, quantity, qty_word, items_added)
            elif menu_item_name:
                self._add_repeat_menu_item(prev_item, order, quantity, qty_word, items_added)

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

    def _add_repeat_bagel(
        self,
        prev_item: dict,
        order: OrderTask,
        quantity: int,
        qty_word: str,
        items_added: list[str],
    ) -> None:
        """Add a repeated bagel item to the order."""
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

    def _add_repeat_coffee(
        self,
        prev_item: dict,
        order: OrderTask,
        quantity: int,
        qty_word: str,
        items_added: list[str],
    ) -> None:
        """Add a repeated coffee/drink item to the order."""
        menu_item_name = prev_item.get("menu_item_name")
        drink_type = prev_item.get("coffee_type") or prev_item.get("drink_type") or menu_item_name

        # Convert style ("iced"/"hot") to iced boolean
        style = prev_item.get("style")
        if style == "iced":
            iced = True
        elif style == "hot":
            iced = False
        else:
            iced = prev_item.get("iced")

        size = prev_item.get("size")
        milk = prev_item.get("milk")
        sweetener = prev_item.get("sweetener")
        flavor_syrup = prev_item.get("flavor_syrup")
        price = prev_item.get("price", 0)

        # Create MenuItemTask with sized_beverage type
        coffee = MenuItemTask(
            menu_item_name=drink_type or "coffee",
            menu_item_type="sized_beverage",
            unit_price=price,
        )
        if size:
            coffee.size = size
        if iced is not None:
            coffee.iced = iced
        if milk:
            coffee.milk = milk
        if sweetener:
            coffee.attribute_values["sweetener_selections"] = [{
                "type": sweetener,
                "quantity": prev_item.get("sweetener_quantity", 1)
            }]
        if flavor_syrup:
            coffee.attribute_values["syrup_selections"] = [{
                "flavor": flavor_syrup,
                "quantity": 1
            }]

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

    def _add_repeat_menu_item(
        self,
        prev_item: dict,
        order: OrderTask,
        quantity: int,
        qty_word: str,
        items_added: list[str],
    ) -> None:
        """Add a repeated generic menu item to the order."""
        menu_item_name = prev_item.get("menu_item_name")
        price = prev_item.get("price", 0)

        item = MenuItemTask(
            menu_item_name=menu_item_name,
            unit_price=price,
        )
        item.status = TaskStatus.COMPLETE
        for _ in range(quantity):
            order.items.add_item(item)
        items_added.append(f"{qty_word} {menu_item_name}")

    @staticmethod
    def _quantity_to_words(n: int) -> str:
        """Convert quantity to words for natural speech."""
        words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
                 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}
        return words.get(n, str(n))
