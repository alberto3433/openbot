"""
Checkout Handler for Order State Machine.

This module handles the checkout flow including delivery method selection,
customer name collection, payment method choice, and contact info collection.

Extracted from state_machine.py for better separation of concerns.
"""

import logging

from .models import OrderTask
from .schemas import OrderPhase, StateMachineResult
from .slot_orchestrator import SlotOrchestrator, SlotCategory
from .parsers import (
    validate_email_address,
    validate_phone_number,
)
from .parsers.llm_parsers import (
    parse_delivery_choice,
    parse_name,
    parse_payment_method,
    parse_phone,
    parse_email,
)
from ..address_service import complete_address

logger = logging.getLogger(__name__)


class CheckoutHandler:
    """
    Handles the checkout flow for orders.

    Manages delivery method selection, address collection, customer name,
    payment method choice, and contact information collection.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        message_builder=None,
        transition_callback=None,
    ):
        """
        Initialize the checkout handler.

        Args:
            model: LLM model to use for parsing.
            message_builder: MessageBuilder instance for generating messages.
            transition_callback: Callback function to transition order to next slot.
        """
        self.model = model
        self.message_builder = message_builder
        self._transition_to_next_slot = transition_callback

        # Context set per-request
        self._store_info: dict | None = None
        self._returning_customer: dict | None = None
        self._is_repeat_order: bool = False
        self._last_order_type: str | None = None

    def set_context(
        self,
        store_info: dict | None = None,
        returning_customer: dict | None = None,
        is_repeat_order: bool = False,
        last_order_type: str | None = None,
    ) -> None:
        """Set per-request context for checkout handling."""
        self._store_info = store_info
        self._returning_customer = returning_customer
        self._is_repeat_order = is_repeat_order
        self._last_order_type = last_order_type

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
            message="Can I get a name for the order?",
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
                    message="What email address should I send it to?",
                    order=order,
                )

        return StateMachineResult(
            message="Would you like that sent by text or email?",
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
        if self._transition_to_next_slot:
            self._transition_to_next_slot(order)  # Should be COMPLETE

        return StateMachineResult(
            message=f"Your order number is {order.checkout.short_order_number}. "
                   f"We'll send the confirmation to {validated_email}. "
                   f"Thank you, {order.customer_info.name}!",
            order=order,
            is_complete=True,
        )
