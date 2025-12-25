"""
AddressChain - handles delivery/pickup selection and address collection.

This chain handles:
- Pickup vs delivery selection
- Address collection for delivery orders
- Address validation
- Delivery zone checking
"""

import re
from typing import Optional, Any, Callable

from .base import BaseChain
from .state import OrderState, ChainResult, ChainName, AddressState


class AddressChain(BaseChain):
    """
    Chain for collecting delivery/pickup information.

    Flow:
    1. Ask delivery or pickup (if not already known)
    2. If pickup: confirm store location -> complete
    3. If delivery: collect street -> city -> zip -> (optional) apt/instructions
    4. Validate address (optional: geocoding API)
    5. Confirm with user -> complete
    """

    chain_name = ChainName.ADDRESS

    def __init__(
        self,
        menu_data: Optional[dict] = None,
        llm: Optional[Any] = None,
        store_info: Optional[dict] = None,
        validate_address_fn: Optional[Callable[[str], bool]] = None,
        check_delivery_zone_fn: Optional[Callable[[str], bool]] = None,
    ):
        """
        Initialize AddressChain.

        Args:
            menu_data: Menu data
            llm: Optional LLM client
            store_info: Store information
            validate_address_fn: Optional function to validate addresses
            check_delivery_zone_fn: Optional function to check delivery zones
        """
        super().__init__(menu_data=menu_data, llm=llm)
        self.store_info = store_info or {
            "address": "123 Main Street",
        }
        self.validate_address_fn = validate_address_fn
        self.check_delivery_zone_fn = check_delivery_zone_fn

    def invoke(self, state: OrderState, user_input: str) -> ChainResult:
        """Process address-related input."""
        input_lower = user_input.lower().strip()
        address_state = state.address

        # Step 1: Determine order type if not set
        if address_state.order_type is None:
            return self._handle_order_type_selection(state, input_lower)

        # Step 2: Handle pickup flow
        if address_state.order_type == "pickup":
            return self._handle_pickup(state, input_lower)

        # Step 3: Handle delivery flow
        return self._handle_delivery(state, input_lower, user_input)

    def _handle_order_type_selection(
        self, state: OrderState, input_lower: str
    ) -> ChainResult:
        """Handle initial order type selection."""
        if self._mentions_pickup(input_lower):
            state.address.order_type = "pickup"
            state.address.store_location_confirmed = True
            store_address = self.store_info.get("address", "our store")

            # If user already has items, go to checkout (not back to ordering)
            if state.has_items():
                return ChainResult(
                    message=f"Great, pickup at {store_address}.",
                    state=state,
                    chain_complete=True,
                    next_chain=ChainName.CHECKOUT,
                    needs_user_input=False,
                )

            return ChainResult(
                message=f"Great, pickup at {store_address}. What can I get for you?",
                state=state,
                chain_complete=True,
                next_chain=ChainName.BAGEL,
            )

        if self._mentions_delivery(input_lower):
            state.address.order_type = "delivery"
            return ChainResult(
                message="Perfect, delivery it is! What's your delivery address?",
                state=state,
                chain_complete=False,
            )

        # Check if they provided an address directly (implies delivery)
        parsed_address = self._parse_address(input_lower)
        if parsed_address.get("street"):
            state.address.order_type = "delivery"
            state.address.street = parsed_address.get("street")
            state.address.city = parsed_address.get("city")
            state.address.state = parsed_address.get("state")
            state.address.zip_code = parsed_address.get("zip_code")
            return self._continue_address_collection(state)

        # Ask for clarification
        return ChainResult(
            message="Is this order for pickup or delivery?",
            state=state,
            chain_complete=False,
        )

    def _handle_pickup(self, state: OrderState, input_lower: str) -> ChainResult:
        """Handle pickup confirmation."""
        if not state.address.store_location_confirmed:
            # Confirm the store location
            if self._is_affirmative(input_lower):
                state.address.store_location_confirmed = True

                # If user already has items, go to checkout
                if state.has_items():
                    return ChainResult(
                        message="Perfect!",
                        state=state,
                        chain_complete=True,
                        next_chain=ChainName.CHECKOUT,
                        needs_user_input=False,
                    )

                return ChainResult(
                    message="Perfect! What can I get for you?",
                    state=state,
                    chain_complete=True,
                    next_chain=ChainName.BAGEL,
                )
            elif self._is_negative(input_lower):
                # They don't want pickup - switch to delivery
                state.address.order_type = "delivery"
                return ChainResult(
                    message="No problem, let's do delivery instead. What's your address?",
                    state=state,
                    chain_complete=False,
                )
            else:
                store_address = self.store_info.get("address", "our store")
                return ChainResult(
                    message=f"Just to confirm, you'll be picking up at {store_address}, right?",
                    state=state,
                    chain_complete=False,
                )

        # Pickup is confirmed - if user has items go to checkout, otherwise ordering
        if state.has_items():
            return ChainResult(
                message="",
                state=state,
                chain_complete=True,
                next_chain=ChainName.CHECKOUT,
                needs_user_input=False,
            )

        return ChainResult(
            message="What can I get for you?",
            state=state,
            chain_complete=True,
            next_chain=ChainName.BAGEL,
        )

    def _handle_delivery(
        self, state: OrderState, input_lower: str, user_input: str
    ) -> ChainResult:
        """Handle delivery address collection."""
        address_state = state.address

        # Try to parse address from input
        parsed = self._parse_address(user_input)

        # Update state with parsed values
        if parsed.get("street") and not address_state.street:
            address_state.street = parsed["street"]
        if parsed.get("city") and not address_state.city:
            address_state.city = parsed["city"]
        if parsed.get("state") and not address_state.state:
            address_state.state = parsed["state"]
        if parsed.get("zip_code") and not address_state.zip_code:
            address_state.zip_code = parsed["zip_code"]
        if parsed.get("apt_unit"):
            address_state.apt_unit = parsed["apt_unit"]

        # Check if we have enough for a complete address
        if address_state.street and address_state.zip_code:
            # Ask for apartment/instructions if not in confirmation mode
            if not address_state.is_validated:
                return self._confirm_address(state)

        return self._continue_address_collection(state)

    def _continue_address_collection(self, state: OrderState) -> ChainResult:
        """Continue collecting missing address fields."""
        address_state = state.address

        if not address_state.street:
            return ChainResult(
                message="What's your street address?",
                state=state,
                chain_complete=False,
            )

        if not address_state.city:
            return ChainResult(
                message="What city?",
                state=state,
                chain_complete=False,
            )

        if not address_state.zip_code:
            return ChainResult(
                message="And the zip code?",
                state=state,
                chain_complete=False,
            )

        # We have all required fields
        return self._confirm_address(state)

    def _confirm_address(self, state: OrderState) -> ChainResult:
        """Confirm the collected address with user."""
        address_state = state.address
        formatted = address_state.get_formatted_address()

        # Validate address if function provided
        if self.validate_address_fn and not address_state.is_validated:
            if not self.validate_address_fn(formatted):
                return ChainResult(
                    message="I couldn't verify that address. Could you double-check it?",
                    state=state,
                    chain_complete=False,
                )

        # Check delivery zone if function provided
        if self.check_delivery_zone_fn:
            if not self.check_delivery_zone_fn(formatted):
                return ChainResult(
                    message="Sorry, that address is outside our delivery area. Would you like to do pickup instead?",
                    state=state,
                    chain_complete=False,
                )

        # Mark as validated
        address_state.is_validated = True

        # If user already has items, go to checkout
        if state.has_items():
            return ChainResult(
                message=f"Got it - delivering to {formatted}.",
                state=state,
                chain_complete=True,
                next_chain=ChainName.CHECKOUT,
                needs_user_input=False,
            )

        # No items yet - ready to take order
        apt_prompt = ""
        if not address_state.apt_unit:
            apt_prompt = " Any apartment number or delivery instructions?"

        return ChainResult(
            message=f"Got it - {formatted}.{apt_prompt} Ready to take your order!",
            state=state,
            chain_complete=True,
            next_chain=ChainName.BAGEL,
        )

    def _parse_address(self, text: str) -> dict:
        """
        Parse address components from text.

        This is a simple pattern-based parser. In production,
        you'd want to use a proper address parsing library or API.
        """
        result = {}

        # Try to find street address (number + street name)
        street_pattern = r"(\d+\s+[\w\s]+(?:st(?:reet)?|ave(?:nue)?|rd|road|blvd|dr(?:ive)?|ln|lane|way|ct|court|pl(?:ace)?|cir(?:cle)?))"
        street_match = re.search(street_pattern, text, re.IGNORECASE)
        if street_match:
            result["street"] = street_match.group(1).strip()

        # Try to find zip code
        zip_pattern = r"\b(\d{5})(?:-\d{4})?\b"
        zip_match = re.search(zip_pattern, text)
        if zip_match:
            result["zip_code"] = zip_match.group(1)

        # Try to find apartment/unit
        apt_pattern = r"(?:apt|apartment|unit|#)\s*(\w+)"
        apt_match = re.search(apt_pattern, text, re.IGNORECASE)
        if apt_match:
            result["apt_unit"] = apt_match.group(1)

        # Try to find city (common cities or anything before state/zip)
        city_pattern = r"(?:,\s*)?([A-Za-z\s]+?)(?:,\s*)?(?:[A-Z]{2})?\s*\d{5}"
        city_match = re.search(city_pattern, text)
        if city_match:
            city = city_match.group(1).strip().rstrip(",")
            if city and len(city) > 2:
                result["city"] = city

        # Try to find state (2-letter abbreviation)
        state_pattern = r"\b([A-Z]{2})\b\s*\d{5}"
        state_match = re.search(state_pattern, text)
        if state_match:
            result["state"] = state_match.group(1)

        return result

    def _mentions_pickup(self, text: str) -> bool:
        """Check if user mentions pickup."""
        patterns = [
            r"\b(pick\s*up|pickup|i.ll (pick|come)|come get|in store)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def _mentions_delivery(self, text: str) -> bool:
        """Check if user mentions delivery."""
        patterns = [
            r"\b(deliver(y)?|for delivery|to my)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def _is_affirmative(self, text: str) -> bool:
        """Check for affirmative response."""
        patterns = [
            r"^(yes|yeah|yep|yup|sure|ok|okay|correct|right|that.s (right|correct))[\s!.]*$",
        ]
        return any(re.search(p, text) for p in patterns)

    def _is_negative(self, text: str) -> bool:
        """Check for negative response."""
        patterns = [
            r"^(no|nope|nah|wrong|incorrect)[\s!.]*$",
        ]
        return any(re.search(p, text) for p in patterns)

    def get_awaiting_field(self, state: OrderState) -> Optional[str]:
        """Get the field this chain is currently waiting for."""
        address_state = state.address

        if address_state.order_type is None:
            return "order_type"
        if address_state.order_type == "pickup":
            if not address_state.store_location_confirmed:
                return "store_confirmation"
            return None
        if address_state.order_type == "delivery":
            if not address_state.street:
                return "street"
            if not address_state.city:
                return "city"
            if not address_state.zip_code:
                return "zip_code"
            if not address_state.is_validated:
                return "confirmation"
        return None
