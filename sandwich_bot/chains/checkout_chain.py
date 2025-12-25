"""
CheckoutChain - handles order review and checkout flow.

This chain handles:
- Order summary/review
- Total calculation
- Order confirmation
- Payment method collection
- Final confirmation and order number generation
"""

import re
from typing import Optional, Any, Callable

from .base import BaseChain
from .state import OrderState, ChainResult, ChainName, OrderStatus


class CheckoutChain(BaseChain):
    """
    Chain for handling checkout flow.

    Flow:
    1. Summarize full order
    2. Calculate total + tax
    3. Confirm order correct?
    4. (if changes needed) -> Route to appropriate chain
    5. Collect payment method
    6. (optional) Add tip?
    7. Final confirmation
    8. Generate order number -> Complete
    """

    chain_name = ChainName.CHECKOUT

    def __init__(
        self,
        menu_data: Optional[dict] = None,
        llm: Optional[Any] = None,
        tax_rate: float = None,  # Deprecated: use city_tax_rate and state_tax_rate
        city_tax_rate: float = None,
        state_tax_rate: float = None,
        delivery_fee: float = None,
        submit_order_fn: Optional[Callable[[OrderState], str]] = None,
        send_confirmation_fn: Optional[Callable[[OrderState], bool]] = None,
    ):
        """
        Initialize CheckoutChain.

        Args:
            menu_data: Menu data (may contain tax rates and delivery_fee)
            llm: Optional LLM client
            tax_rate: Deprecated - combined tax rate for backward compatibility
            city_tax_rate: City/local tax rate (overrides menu_data)
            state_tax_rate: State tax rate (overrides menu_data)
            delivery_fee: Delivery fee to apply (overrides menu_data; default $2.99)
            submit_order_fn: Function to submit order to POS/kitchen
            send_confirmation_fn: Function to send confirmation SMS/email
        """
        super().__init__(menu_data=menu_data, llm=llm)

        # Extract config from menu_data if available
        config = self._extract_checkout_config(menu_data)

        # Allow explicit parameters to override menu_data values
        # Support both old-style tax_rate and new city/state rates
        if city_tax_rate is not None:
            self.city_tax_rate = city_tax_rate
        else:
            self.city_tax_rate = config["city_tax_rate"]

        if state_tax_rate is not None:
            self.state_tax_rate = state_tax_rate
        else:
            self.state_tax_rate = config["state_tax_rate"]

        # Backward compatibility: if tax_rate provided and no separate rates
        if tax_rate is not None and city_tax_rate is None and state_tax_rate is None:
            # Use the old-style combined rate as state tax (arbitrary choice)
            self.city_tax_rate = 0.0
            self.state_tax_rate = tax_rate

        self.delivery_fee = delivery_fee if delivery_fee is not None else config["delivery_fee"]

        self.submit_order_fn = submit_order_fn
        self.send_confirmation_fn = send_confirmation_fn

    def _extract_checkout_config(self, menu_data: Optional[dict]) -> dict:
        """Extract checkout configuration from menu_data."""
        defaults = {
            "city_tax_rate": 0.0,
            "state_tax_rate": 0.0,
            "delivery_fee": 2.99,
        }

        if not menu_data:
            return defaults

        # Check for store_info or config sections in menu_data
        store_info = menu_data.get("store_info", {})
        config = menu_data.get("config", {})

        # Try to get city_tax_rate from various possible locations
        city_tax_rate = (
            store_info.get("city_tax_rate")
            or config.get("city_tax_rate")
            or menu_data.get("city_tax_rate")
        )
        if city_tax_rate is not None:
            defaults["city_tax_rate"] = float(city_tax_rate)

        # Try to get state_tax_rate from various possible locations
        state_tax_rate = (
            store_info.get("state_tax_rate")
            or config.get("state_tax_rate")
            or menu_data.get("state_tax_rate")
        )
        if state_tax_rate is not None:
            defaults["state_tax_rate"] = float(state_tax_rate)

        # Backward compatibility: if old-style tax_rate is provided
        tax_rate = (
            store_info.get("tax_rate")
            or config.get("tax_rate")
            or menu_data.get("tax_rate")
        )
        if tax_rate is not None and defaults["city_tax_rate"] == 0.0 and defaults["state_tax_rate"] == 0.0:
            # Use old-style rate as state tax for backward compatibility
            defaults["state_tax_rate"] = float(tax_rate)

        # Try to get delivery_fee from various possible locations
        delivery_fee = (
            store_info.get("delivery_fee")
            or config.get("delivery_fee")
            or menu_data.get("delivery_fee")
        )
        if delivery_fee is not None:
            defaults["delivery_fee"] = float(delivery_fee)

        return defaults

    def invoke(self, state: OrderState, user_input: str) -> ChainResult:
        """Process checkout-related input."""
        input_lower = user_input.lower().strip()
        checkout_state = state.checkout

        # Check for cancellation
        if self._wants_to_cancel(input_lower):
            return self._handle_cancel(state)

        # Check if user wants to add more items
        if self._wants_to_add_more(input_lower):
            return self._route_to_ordering(state, input_lower)

        # If cart is empty, redirect to ordering
        if not state.has_items():
            return ChainResult(
                message="You don't have any items in your order yet. What would you like?",
                state=state,
                chain_complete=True,
                next_chain=ChainName.BAGEL,
            )

        # If order type not set, ask for pickup/delivery first
        if not state.address.order_type:
            return self._ask_order_type(state)

        # If order not yet reviewed, show summary first
        if not checkout_state.order_reviewed:
            return self._show_order_summary(state)

        # Handle based on what we're awaiting
        if checkout_state.awaiting == "name":
            return self._handle_name_input(state, user_input)

        if checkout_state.awaiting == "contact":
            return self._handle_contact_input(state, user_input)

        # If waiting for order confirmation
        if not checkout_state.confirmed:
            return self._handle_confirmation(state, input_lower)

        # Order is confirmed - we're done
        return self._complete_order(state)

    def _ask_order_type(self, state: OrderState) -> ChainResult:
        """Ask user for pickup or delivery before proceeding with checkout."""
        return ChainResult(
            message="Would you like this for pickup or delivery?",
            state=state,
            chain_complete=True,
            next_chain=ChainName.ADDRESS,
            needs_user_input=True,
        )

    def _show_order_summary(self, state: OrderState) -> ChainResult:
        """Show order summary to user."""
        checkout_state = state.checkout

        # Calculate totals using menu-based configuration
        subtotal = state.get_subtotal()
        is_delivery = state.address.order_type == "delivery"
        checkout_state.calculate_total(
            subtotal=subtotal,
            is_delivery=is_delivery,
            city_tax_rate=self.city_tax_rate,
            state_tax_rate=self.state_tax_rate,
            delivery_fee=self.delivery_fee,
        )
        checkout_state.order_reviewed = True

        # Build summary message
        summary = self._build_order_summary(state)

        return ChainResult(
            message=f"{summary}\n\nDoes everything look good?",
            state=state,
            chain_complete=False,
        )

    def _build_order_summary(self, state: OrderState) -> str:
        """Build a formatted order summary string."""
        lines = ["Here's your order:"]

        # Add bagel items
        for item in state.bagels.items:
            price = item.unit_price * item.quantity
            lines.append(f"  - {item.get_description()} — ${price:.2f}")

        # Add coffee items
        for item in state.coffee.items:
            lines.append(f"  - {item.get_description()} — ${item.unit_price:.2f}")

        # Add totals
        checkout = state.checkout
        lines.append("")
        lines.append(f"Subtotal: ${checkout.subtotal:.2f}")

        # Show tax breakdown (only non-zero taxes)
        if checkout.city_tax > 0 and checkout.state_tax > 0:
            # Both taxes - show breakdown
            lines.append(f"City tax: ${checkout.city_tax:.2f}")
            lines.append(f"State tax: ${checkout.state_tax:.2f}")
        elif checkout.city_tax > 0:
            # Only city tax
            lines.append(f"Tax: ${checkout.city_tax:.2f}")
        elif checkout.state_tax > 0:
            # Only state tax
            lines.append(f"Tax: ${checkout.state_tax:.2f}")
        elif checkout.tax > 0:
            # Backward compatibility: combined tax from old-style rate
            lines.append(f"Tax: ${checkout.tax:.2f}")
        # If all taxes are zero, don't show tax line at all

        if checkout.delivery_fee > 0:
            lines.append(f"Delivery fee: ${checkout.delivery_fee:.2f}")

        lines.append(f"**Total: ${checkout.total:.2f}**")

        # Add delivery/pickup info
        if state.address.order_type == "delivery":
            addr = state.address.get_formatted_address()
            lines.append(f"\nDelivering to: {addr}")
        else:
            lines.append("\nFor pickup")

        return "\n".join(lines)

    def _handle_confirmation(self, state: OrderState, input_lower: str) -> ChainResult:
        """Handle order confirmation response."""
        checkout_state = state.checkout

        if self._is_affirmative(input_lower):
            # Order approved - now collect name if we don't have it
            if not state.customer_name and not checkout_state.name_collected:
                checkout_state.awaiting = "name"
                return ChainResult(
                    message="Great! Can I get a name for the order?",
                    state=state,
                    chain_complete=False,
                )

            # We have the name, now collect contact for payment link
            if not state.customer_email and not state.customer_phone and not checkout_state.contact_collected:
                checkout_state.awaiting = "contact"
                return ChainResult(
                    message="Would you like me to send a payment link? I can text or email it to you.",
                    state=state,
                    chain_complete=False,
                )

            # We have everything - confirm the order
            return self._finalize_order(state)

        elif self._is_negative(input_lower):
            # They want to change something
            return ChainResult(
                message="No problem! What would you like to change?",
                state=state,
                chain_complete=False,
            )

        elif self._wants_to_modify(input_lower):
            # Specific modification request
            return self._handle_modification_request(state, input_lower)

        else:
            # Unclear response
            return ChainResult(
                message="Does the order look correct? Say 'yes' to confirm or tell me what you'd like to change.",
                state=state,
                chain_complete=False,
            )

    def _handle_name_input(self, state: OrderState, user_input: str) -> ChainResult:
        """Handle customer name input."""
        checkout_state = state.checkout

        # Extract name from input (clean up common prefixes)
        name = user_input.strip()
        name = re.sub(r"^(my name is|i'm|it's|name is|call me)\s+", "", name, flags=re.IGNORECASE)
        name = name.strip().title()

        if len(name) < 2:
            return ChainResult(
                message="I didn't catch that. What name should I put on the order?",
                state=state,
                chain_complete=False,
            )

        state.customer_name = name
        checkout_state.name_collected = True
        checkout_state.awaiting = "contact"

        return ChainResult(
            message=f"Thanks {name}! Would you like me to send a payment link? I can text or email it to you.",
            state=state,
            chain_complete=False,
        )

    def _handle_contact_input(self, state: OrderState, user_input: str) -> ChainResult:
        """Handle contact info (email/phone) input."""
        checkout_state = state.checkout
        input_text = user_input.strip()

        # Check for email
        email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', input_text)
        if email_match:
            state.customer_email = email_match.group()
            checkout_state.contact_collected = True
            checkout_state.awaiting = None
            return self._finalize_order(state, contact_method="email")

        # Check for phone number (10+ digits)
        phone_match = re.search(r'[\d\-\(\)\s]{10,}', input_text)
        if phone_match:
            # Clean up phone number
            phone = re.sub(r'[^\d]', '', phone_match.group())
            if len(phone) >= 10:
                state.customer_phone = phone
                checkout_state.contact_collected = True
                checkout_state.awaiting = None
                return self._finalize_order(state, contact_method="text")

        # Check if they declined payment link
        if self._is_negative(user_input.lower()) or "cash" in user_input.lower() or "pay here" in user_input.lower():
            checkout_state.contact_collected = True
            checkout_state.awaiting = None
            checkout_state.payment_method = "cash"
            return self._finalize_order(state)

        return ChainResult(
            message="I can send the payment link to your email or phone. What would you prefer?",
            state=state,
            chain_complete=False,
        )

    def _finalize_order(self, state: OrderState, contact_method: str = None) -> ChainResult:
        """Finalize and confirm the order."""
        checkout_state = state.checkout

        # Generate order number
        checkout_state.confirmed = True
        order_number = checkout_state.generate_order_number()
        # Use last 2 digits for voice readout (easier to remember)
        short_order_number = order_number[-2:] if order_number else "00"

        # Submit order if function provided
        if self.submit_order_fn:
            try:
                self.submit_order_fn(state)
            except Exception:
                pass  # Log but don't fail

        # Send confirmation if function provided
        if self.send_confirmation_fn:
            try:
                self.send_confirmation_fn(state)
            except Exception:
                pass  # Log but don't fail

        # Update order status
        state.status = OrderStatus.CONFIRMED

        # Build confirmation message
        name = state.customer_name or "friend"

        if contact_method == "email":
            contact_msg = f"I'll email a payment link to {state.customer_email}."
        elif contact_method == "text":
            contact_msg = f"I'll text a payment link to {state.customer_phone}."
        else:
            contact_msg = ""

        if state.address.order_type == "delivery":
            eta = "30-45 minutes"
            message = f"Your order is confirmed, {name}! Order number {short_order_number}. {contact_msg} It'll be delivered in about {eta}. Thanks for your order!"
        else:
            message = f"Your order is confirmed, {name}! Order number {short_order_number}. {contact_msg} It'll be ready for pickup in about 10-15 minutes. Thanks!"

        return ChainResult(
            message=message,
            state=state,
            chain_complete=True,
        )

    def _handle_modification_request(
        self, state: OrderState, input_lower: str
    ) -> ChainResult:
        """Handle specific modification requests."""
        # Reset order_reviewed so they see updated summary
        state.checkout.order_reviewed = False

        if "bagel" in input_lower:
            return ChainResult(
                message="What would you like to change about your bagel order?",
                state=state,
                chain_complete=True,
                next_chain=ChainName.BAGEL,
            )

        if "coffee" in input_lower or "drink" in input_lower:
            return ChainResult(
                message="What would you like to change about your drink order?",
                state=state,
                chain_complete=True,
                next_chain=ChainName.COFFEE,
            )

        if "address" in input_lower or "delivery" in input_lower:
            return ChainResult(
                message="What's the correct address?",
                state=state,
                chain_complete=True,
                next_chain=ChainName.ADDRESS,
            )

        if "remove" in input_lower:
            return self._handle_remove_item(state, input_lower)

        if "add" in input_lower:
            return ChainResult(
                message="What would you like to add?",
                state=state,
                chain_complete=True,
                next_chain=ChainName.BAGEL,
            )

        return ChainResult(
            message="What would you like to change?",
            state=state,
            chain_complete=False,
        )

    def _handle_remove_item(self, state: OrderState, input_lower: str) -> ChainResult:
        """Handle item removal requests."""
        # Try to identify which item to remove
        removed = False

        if "bagel" in input_lower and state.bagels.items:
            state.bagels.items.pop()
            removed = True
        elif ("coffee" in input_lower or "drink" in input_lower) and state.coffee.items:
            state.coffee.items.pop()
            removed = True

        if removed:
            # Recalculate totals
            state.checkout.order_reviewed = False
            return self._show_order_summary(state)

        return ChainResult(
            message="Which item would you like to remove?",
            state=state,
            chain_complete=False,
        )

    def _handle_cancel(self, state: OrderState) -> ChainResult:
        """Handle order cancellation."""
        state.status = OrderStatus.CANCELLED
        return ChainResult(
            message="No problem, your order has been cancelled. Feel free to start a new order anytime!",
            state=state,
            chain_complete=True,
        )

    def _route_to_ordering(self, state: OrderState, input_lower: str) -> ChainResult:
        """Route back to ordering chains."""
        state.checkout.order_reviewed = False

        if "coffee" in input_lower or "drink" in input_lower:
            return ChainResult(
                message="What drink would you like to add?",
                state=state,
                chain_complete=True,
                next_chain=ChainName.COFFEE,
            )

        return ChainResult(
            message="What would you like to add?",
            state=state,
            chain_complete=True,
            next_chain=ChainName.BAGEL,
        )

    def _complete_order(self, state: OrderState) -> ChainResult:
        """Complete the order (already confirmed)."""
        order_number = state.checkout.order_number or "00"
        short_order_number = order_number[-2:]
        return ChainResult(
            message=f"Your order number {short_order_number} is already confirmed. Is there anything else I can help with?",
            state=state,
            chain_complete=True,
        )

    # --- Helper methods ---

    def _is_affirmative(self, text: str) -> bool:
        """Check for affirmative response."""
        patterns = [
            r"^(yes|yeah|yep|yup|sure|ok|okay|correct|right|looks? good|perfect|confirm|submit|place.*(order)?)[\s!.]*$",
            r"\b(yes|correct|confirm|good|perfect)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def _is_negative(self, text: str) -> bool:
        """Check for negative response."""
        patterns = [
            r"^(no|nope|nah|wrong|wait|hold on|not quite)[\s!.]*$",
        ]
        return any(re.search(p, text) for p in patterns)

    def _wants_to_cancel(self, text: str) -> bool:
        """Check if user wants to cancel."""
        patterns = [
            r"\b(cancel|nevermind|never mind|forget it)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def _wants_to_add_more(self, text: str) -> bool:
        """Check if user wants to add more items."""
        patterns = [
            r"\b(add|another|more|also|wait)\b.*\b(bagel|coffee|drink|item)\b",
            r"^(add|actually)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def _wants_to_modify(self, text: str) -> bool:
        """Check if user wants to modify order."""
        patterns = [
            r"\b(change|modify|update|remove|delete|switch)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def get_awaiting_field(self, state: OrderState) -> Optional[str]:
        """Get the field this chain is waiting for."""
        if not state.checkout.order_reviewed:
            return None  # Will show summary
        if not state.checkout.confirmed:
            return "confirmation"
        return None
