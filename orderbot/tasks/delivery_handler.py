"""
Delivery Handler for Order State Machine.

This module handles delivery method selection and address collection,
extracted from checkout_handler.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from .checkout_messages import CheckoutMessages
from .pending_fields import PendingField
from .models import OrderTask
from .schemas import OrderPhase, StateMachineResult
from .slot_orchestrator import SlotOrchestrator, SlotCategory
from .parsers.llm_parsers import parse_delivery_choice
from ..address_service import complete_address
from .handler_config import BaseHandler

if TYPE_CHECKING:
    from .handler_config import HandlerConfig
    from .context import OrderContext
    from .message_builder import MessageBuilder

logger = logging.getLogger(__name__)


class DeliveryHandler(BaseHandler):
    """
    Handles delivery method selection and address collection.

    Manages pickup/delivery choice, address validation, and address confirmation
    for repeat orders.
    """

    def __init__(
        self,
        config: "HandlerConfig",
        message_builder: "MessageBuilder | None" = None,
    ):
        """
        Initialize the delivery handler.

        Args:
            config: HandlerConfig with shared dependencies.
            message_builder: MessageBuilder for building response messages.
        """
        super().__init__(config)
        self._message_builder = message_builder

        # Context set per-request
        self._store_info: dict | None = None
        self._returning_customer: dict | None = None
        self._is_repeat_order: bool = False
        self._last_order_type: str | None = None

    def set_context(self, ctx: "OrderContext") -> None:
        """Set per-request context for delivery handling."""
        self._store_info = ctx.store_info
        self._returning_customer = ctx.returning_customer
        self._is_repeat_order = ctx.is_repeat_order
        self._last_order_type = ctx.last_order_type
        self._menu_data = ctx.menu_data

    def set_message_builder(self, message_builder: "MessageBuilder") -> None:
        """Set the message builder (allows late binding)."""
        self._message_builder = message_builder

    def handle_delivery(
        self,
        user_input: str,
        order: OrderTask,
        transition_callback=None,
    ) -> StateMachineResult:
        """Handle pickup/delivery selection and address collection.

        Args:
            user_input: User's input text.
            order: Current order state.
            transition_callback: Optional callback to transition to next slot.

        Returns:
            StateMachineResult with response message.
        """
        # Handle address confirmation for repeat orders
        if order.pending_field == PendingField.ADDRESS_CONFIRMATION:
            return self._handle_address_confirmation(user_input, order, transition_callback)

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
                    return self._proceed_after_address(order, transition_callback)
                return StateMachineResult(
                    message=CheckoutMessages.DELIVERY_ADDRESS,
                    order=order,
                )
            return StateMachineResult(
                message=self._message_builder.get_delivery_question(
                    self._is_repeat_order,
                    self._last_order_type,
                ) if self._message_builder else CheckoutMessages.PICKUP_OR_DELIVERY,
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
                    order.pending_field = PendingField.ADDRESS_CONFIRMATION
                    return StateMachineResult(
                        message=f"I have {last_address}. Is that correct?",
                        order=order,
                    )
            # Need to collect address fresh
            return StateMachineResult(
                message=CheckoutMessages.DELIVERY_ADDRESS,
                order=order,
            )

        # Transition to next slot - check if we already have name from returning customer
        return self._proceed_after_address(order, transition_callback)

    def _handle_address_confirmation(
        self,
        user_input: str,
        order: OrderTask,
        transition_callback=None,
    ) -> StateMachineResult:
        """Handle user response to address confirmation prompt.

        Called when order.pending_field == ADDRESS_CONFIRMATION.
        """
        lower_input = user_input.lower().strip()

        # Check for affirmative response
        if lower_input in ("yes", "yeah", "yep", "correct", "that's right", "thats right", "right", "yes please", "yea"):
            order.pending_field = None
            return self._proceed_after_address(order, transition_callback)

        # Check for negative response - ask for new address
        if lower_input in ("no", "nope", "different address", "new address", "wrong", "not quite"):
            order.pending_field = None
            order.delivery_method.address.street = None
            return StateMachineResult(message=CheckoutMessages.DELIVERY_ADDRESS, order=order)

        # Otherwise treat as a new address
        order.pending_field = None
        order.delivery_method.address.street = None
        parsed = parse_delivery_choice(user_input, model=self.model)
        if parsed.address:
            result = self._complete_delivery_address(parsed.address, order)
            if result:
                return result
            return self._proceed_after_address(order, transition_callback)
        return StateMachineResult(message=CheckoutMessages.DELIVERY_ADDRESS, order=order)

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

    def _proceed_after_address(
        self,
        order: OrderTask,
        transition_callback=None,
    ) -> StateMachineResult:
        """Handle transition after delivery address is captured.

        Checks if we already have customer info and skips to confirmation if so.
        """
        if transition_callback:
            transition_callback(order)

        # If we already have the customer name, skip to confirmation
        if order.customer_info.name:
            order.set_phase(OrderPhase.CHECKOUT_CONFIRM)
            if self._message_builder:
                summary = self._message_builder.build_order_summary(order)
                return StateMachineResult(
                    message=f"{summary}\n\nDoes that look right?",
                    order=order,
                )

        return StateMachineResult(
            message=CheckoutMessages.NAME,
            order=order,
        )
