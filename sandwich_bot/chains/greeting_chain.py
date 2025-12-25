"""
GreetingChain - handles greetings, store info, and initial routing.

This chain handles:
- Initial greetings
- Store hours inquiries
- Location/directions
- Help requests
"""

import re
from typing import Optional, Any

from .base import BaseChain
from .state import OrderState, ChainResult, ChainName


class GreetingChain(BaseChain):
    """
    Chain for handling greetings and general inquiries.

    This is typically the entry point for new conversations.
    After greeting, it routes to either AddressChain (for delivery/pickup)
    or directly to ordering chains.
    """

    chain_name = ChainName.GREETING

    def __init__(
        self,
        menu_data: Optional[dict] = None,
        llm: Optional[Any] = None,
        store_info: Optional[dict] = None,
    ):
        """
        Initialize GreetingChain.

        Args:
            menu_data: Menu data
            llm: Optional LLM client
            store_info: Store information (hours, location, etc.)
        """
        super().__init__(menu_data=menu_data, llm=llm)
        self.store_info = store_info or {
            "name": "The Bagel Shop",
            "hours": "7am - 3pm, Monday through Sunday",
            "address": "123 Main Street",
            "phone": "(555) 123-4567",
        }

    def invoke(self, state: OrderState, user_input: str) -> ChainResult:
        """Process greeting/inquiry and route appropriately."""
        input_lower = user_input.lower().strip()

        # Check for specific inquiries
        if self._is_hours_inquiry(input_lower):
            return self._handle_hours(state)

        if self._is_location_inquiry(input_lower):
            return self._handle_location(state)

        if self._is_help_request(input_lower):
            return self._handle_help(state)

        # Check if user is already stating order preference
        if self._mentions_delivery(input_lower):
            state.address.order_type = "delivery"
            return ChainResult(
                message="Great, delivery it is! What's your delivery address?",
                state=state,
                chain_complete=True,
                next_chain=ChainName.ADDRESS,
            )

        if self._mentions_pickup(input_lower):
            state.address.order_type = "pickup"
            state.address.store_location_confirmed = True
            return ChainResult(
                message=f"Perfect, pickup at {self.store_info.get('address', 'our store')}. What can I get started for you?",
                state=state,
                chain_complete=True,
                next_chain=ChainName.BAGEL,
            )

        # Check if user is already ordering something
        if self._mentions_ordering(input_lower):
            # Track if user mentioned coffee for later
            if self._mentions_coffee(input_lower):
                state.pending_coffee = True
            return ChainResult(
                message="I'd be happy to help with your order! Is this for pickup or delivery?",
                state=state,
                chain_complete=True,
                next_chain=ChainName.ADDRESS,
            )

        # Default greeting response
        return self._handle_greeting(state)

    def _is_hours_inquiry(self, text: str) -> bool:
        """Check if user is asking about hours."""
        patterns = [
            r"\b(hours?|open|close|when.*open|what time)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def _is_location_inquiry(self, text: str) -> bool:
        """Check if user is asking about location."""
        patterns = [
            r"\b(where|location|address|directions?|find you)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def _is_help_request(self, text: str) -> bool:
        """Check if user is asking for help."""
        patterns = [
            r"\b(help|how (do|does|can)|what can|menu)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def _mentions_delivery(self, text: str) -> bool:
        """Check if user mentions delivery."""
        patterns = [
            r"\b(deliver(y)?|for delivery)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def _mentions_pickup(self, text: str) -> bool:
        """Check if user mentions pickup."""
        patterns = [
            r"\b(pick\s*up|pickup|for pickup|i.ll (pick|come)|come get)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def _mentions_ordering(self, text: str) -> bool:
        """Check if user mentions wanting to order."""
        patterns = [
            r"\b(order|want|get|like|need)\b.*\b(bagel|coffee|food|something)\b",
            r"\b(bagel|coffee)\b",
            r"\bi.d like\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def _mentions_coffee(self, text: str) -> bool:
        """Check if user mentions coffee/drinks."""
        patterns = [
            r"\b(coffee|latte|espresso|cappuccino|tea|drink)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def _handle_greeting(self, state: OrderState) -> ChainResult:
        """Handle standard greeting."""
        store_name = self.store_info.get("name", "The Bagel Shop")

        message = (
            f"Hey there! Welcome to {store_name}. "
            "Will this be for pickup or delivery?"
        )

        return ChainResult(
            message=message,
            state=state,
            chain_complete=True,
            next_chain=ChainName.ADDRESS,
        )

    def _handle_hours(self, state: OrderState) -> ChainResult:
        """Handle hours inquiry."""
        hours = self.store_info.get("hours", "7am - 3pm daily")

        message = f"We're open {hours}. Would you like to place an order?"

        return ChainResult(
            message=message,
            state=state,
            chain_complete=False,  # Stay in greeting to see if they want to order
        )

    def _handle_location(self, state: OrderState) -> ChainResult:
        """Handle location inquiry."""
        address = self.store_info.get("address", "123 Main Street")
        phone = self.store_info.get("phone", "")

        message = f"We're located at {address}."
        if phone:
            message += f" You can also reach us at {phone}."
        message += " Would you like to place an order?"

        return ChainResult(
            message=message,
            state=state,
            chain_complete=False,
        )

    def _handle_help(self, state: OrderState) -> ChainResult:
        """Handle help request."""
        message = (
            "I can help you order bagels, coffee, and more! "
            "Just tell me what you'd like, or say 'pickup' or 'delivery' to get started. "
            "You can also ask about our hours or location."
        )

        return ChainResult(
            message=message,
            state=state,
            chain_complete=False,
        )

    def get_awaiting_field(self, state: OrderState) -> Optional[str]:
        """This chain waits for order type decision."""
        if state.address.order_type is None:
            return "order_type"
        return None
