"""
BagelChain - handles bagel ordering flow.

This chain handles:
- Bagel type selection
- Quantity
- Toasted preference
- Spread selection (cream cheese, butter, etc.)
- Extras (lox, bacon, tomato, etc.)
- Sandwich builds
"""

import re
from typing import Optional, Any, Dict, List

from .base import BaseChain
from .state import OrderState, ChainResult, ChainName, BagelItem, BagelOrderState


# Default bagel menu data (used when no menu_index is provided)
DEFAULT_BAGEL_TYPES = [
    "plain", "everything", "sesame", "poppy", "onion", "garlic",
    "cinnamon raisin", "whole wheat", "pumpernickel", "salt", "egg"
]

DEFAULT_SPREADS = [
    "plain cream cheese", "scallion cream cheese", "vegetable cream cheese",
    "lox spread", "butter", "peanut butter"
]

DEFAULT_EXTRAS = [
    "lox", "bacon", "egg", "tomato", "onion", "capers", "avocado"
]

DEFAULT_PRICES = {
    "bagel_base": 2.50,
    "spread": 1.50,
    "extras": {
        "lox": 5.00,
        "bacon": 2.00,
        "egg": 1.50,
        "avocado": 2.00,
    }
}


def _extract_menu_data(menu_index: Optional[Dict]) -> Dict[str, Any]:
    """
    Extract bagel-relevant data from the menu_index.

    The menu_index contains:
    - bread_types: List of bread types (may include bagels)
    - bread_prices: Dict of bread name -> price
    - cheese_types: List of cheese types (used for spreads like cream cheese)
    - protein_types: List of proteins (lox, bacon, etc.)
    - protein_prices: Dict of protein name -> price
    - topping_types: List of toppings
    - signature_sandwiches/signature_bagels: Menu items with pricing
    - item_types: Configurable item type attributes
    """
    if not menu_index:
        return {
            "bagel_types": DEFAULT_BAGEL_TYPES,
            "spreads": DEFAULT_SPREADS,
            "extras": DEFAULT_EXTRAS,
            "prices": DEFAULT_PRICES,
            "menu_items": [],
        }

    # Extract bagel types from bread_types (filter for bagels)
    bread_types = menu_index.get("bread_types", [])
    bagel_types = [b for b in bread_types if "bagel" in b.lower()]

    # If no specific bagels found, use all bread types or defaults
    if not bagel_types:
        bagel_types = bread_types if bread_types else DEFAULT_BAGEL_TYPES

    # Extract spreads from cheese_types (cream cheese, etc.)
    cheese_types = menu_index.get("cheese_types", [])
    # Also include butter which might not be in cheese
    spreads = cheese_types if cheese_types else DEFAULT_SPREADS

    # Extract extras from proteins and toppings
    protein_types = menu_index.get("protein_types", [])
    topping_types = menu_index.get("topping_types", [])
    extras = list(set(protein_types + topping_types)) if (protein_types or topping_types) else DEFAULT_EXTRAS

    # Build prices from menu data
    bread_prices = menu_index.get("bread_prices", {})
    protein_prices = menu_index.get("protein_prices", {})

    # Find base bagel price from bread_prices or signature items
    bagel_base = 2.50  # Default
    for bread, price in bread_prices.items():
        if "bagel" in bread.lower():
            bagel_base = price
            break

    # Check signature_sandwiches or signature_bagels for pricing
    menu_items = []
    for key in ["signature_bagels", "signature_sandwiches", "custom_bagels", "custom_sandwiches"]:
        items = menu_index.get(key, [])
        menu_items.extend(items)
        for item in items:
            name = item.get("name", "").lower()
            if "bagel" in name and item.get("base_price"):
                bagel_base = item["base_price"]
                break

    # Build extras prices from protein_prices
    extras_prices = {k.lower(): v for k, v in protein_prices.items()}
    # Add default prices for items not in menu
    for extra in DEFAULT_EXTRAS:
        if extra.lower() not in extras_prices:
            extras_prices[extra.lower()] = DEFAULT_PRICES["extras"].get(extra.lower(), 0.50)

    prices = {
        "bagel_base": bagel_base,
        "spread": 1.50,  # Could be extracted from cheese prices if available
        "extras": extras_prices,
    }

    return {
        "bagel_types": bagel_types,
        "spreads": spreads,
        "extras": extras,
        "prices": prices,
        "menu_items": menu_items,
    }


class BagelChain(BaseChain):
    """
    Chain for handling bagel orders.

    Flow:
    1. What kind of bagel?
    2. How many?
    3. Toasted?
    4. Any spread? -> What type?
    5. Anything else on it? (sandwich fixings)
    6. Confirm item -> Add to order
    7. Another bagel? -> Loop or complete
    """

    chain_name = ChainName.BAGEL

    def __init__(
        self,
        menu_data: Optional[dict] = None,
        llm: Optional[Any] = None,
    ):
        """
        Initialize BagelChain.

        Args:
            menu_data: The menu_index dict from build_menu_index(), containing:
                - bread_types, cheese_types, protein_types, topping_types
                - bread_prices, protein_prices
                - signature_sandwiches/bagels with pricing
            llm: Optional LLM for complex parsing (not currently used)
        """
        super().__init__(menu_data=menu_data, llm=llm)

        # Extract and normalize menu data
        extracted = _extract_menu_data(menu_data)
        self.bagel_types = extracted["bagel_types"]
        self.spreads = extracted["spreads"]
        self.extras = extracted["extras"]
        self.prices = extracted["prices"]
        self.menu_items = extracted["menu_items"]

        # Keep reference to full menu for advanced lookups
        self._menu_index = menu_data

    def invoke(self, state: OrderState, user_input: str) -> ChainResult:
        """Process bagel ordering input."""
        input_lower = user_input.lower().strip()
        bagel_state = state.bagels

        # Check if user is done ordering
        if self._is_done_ordering(input_lower):
            return self._finish_bagel_ordering(state)

        # Check if user mentions both bagel and coffee (e.g., "I want a bagel and a coffee")
        mentions_coffee = self._mentions_coffee(input_lower)
        mentions_bagel = self._mentions_bagel(input_lower)

        if mentions_coffee and mentions_bagel:
            # User wants both - track coffee for later and continue with bagel
            state.pending_coffee = True
            # Fall through to bagel ordering below

        # Check if user wants ONLY coffee (not bagel)
        elif mentions_coffee and not mentions_bagel:
            # Finalize any current item first
            if bagel_state.current_item:
                bagel_state.add_current_item()
            return ChainResult(
                message="Sure! What kind of coffee would you like?",
                state=state,
                chain_complete=True,
                next_chain=ChainName.COFFEE,
            )

        # Check if user wants to checkout
        if self._wants_checkout(input_lower):
            if bagel_state.current_item:
                bagel_state.add_current_item()
            return ChainResult(
                message="",
                state=state,
                chain_complete=True,
                next_chain=ChainName.CHECKOUT,
                needs_user_input=False,
            )

        # If awaiting a response (like "another?"), handle it even if current_item is None
        if bagel_state.awaiting:
            return self._continue_current_item(state, input_lower, user_input)

        # If no current item and not awaiting, start a new one
        if bagel_state.current_item is None:
            return self._start_new_item(state, input_lower, user_input)

        # Continue building current item based on awaiting field
        return self._continue_current_item(state, input_lower, user_input)

    def _start_new_item(
        self, state: OrderState, input_lower: str, user_input: str
    ) -> ChainResult:
        """Start building a new bagel item."""
        bagel_state = state.bagels

        # Try to parse bagel details from input
        parsed = self._parse_bagel_order(user_input)

        if parsed.get("bagel_type"):
            # Create new item with parsed data
            bagel_state.current_item = BagelItem(
                bagel_type=parsed["bagel_type"],
                quantity=parsed.get("quantity", 1),
                toasted=parsed.get("toasted"),  # None if not explicitly mentioned
                spread=parsed.get("spread"),
                spread_type=parsed.get("spread_type"),
                extras=parsed.get("extras", []),
            )

            # Calculate price
            bagel_state.current_item.unit_price = self._calculate_price(
                bagel_state.current_item
            )

            # Determine what to ask next
            return self._determine_next_question(state)

        # Couldn't parse bagel type - create a placeholder item with any parsed info
        # and ask for bagel type
        bagel_state.current_item = BagelItem(
            bagel_type="",  # Will be filled in when user responds
            quantity=parsed.get("quantity", 1),
            toasted=parsed.get("toasted"),  # None if not explicitly mentioned
            spread=parsed.get("spread"),
            spread_type=parsed.get("spread_type"),
            extras=parsed.get("extras", []),
        )
        bagel_state.awaiting = "bagel_type"
        return ChainResult(
            message="What kind of bagel would you like?",
            state=state,
            chain_complete=False,
        )

    def _continue_current_item(
        self, state: OrderState, input_lower: str, user_input: str
    ) -> ChainResult:
        """Continue building the current bagel item."""
        bagel_state = state.bagels
        current = bagel_state.current_item
        awaiting = bagel_state.awaiting

        if awaiting == "bagel_type":
            bagel_type = self._extract_bagel_type(input_lower)
            if bagel_type:
                current.bagel_type = bagel_type
                return self._determine_next_question(state)
            return ChainResult(
                message="I didn't catch that. What kind of bagel - plain, everything, sesame?",
                state=state,
                chain_complete=False,
            )

        if awaiting == "quantity":
            quantity = self._extract_quantity(input_lower)
            current.quantity = quantity
            return self._determine_next_question(state)

        if awaiting == "toasted":
            if self._is_affirmative(input_lower):
                current.toasted = True
            elif self._is_negative(input_lower):
                current.toasted = False
            return self._determine_next_question(state)

        if awaiting == "spread":
            if self._is_negative(input_lower):
                current.spread = None
                return self._determine_next_question(state)

            spread = self._extract_spread(input_lower)
            if spread:
                current.spread = spread.get("spread")
                current.spread_type = spread.get("spread_type")
                return self._determine_next_question(state)

            if self._is_affirmative(input_lower):
                bagel_state.awaiting = "spread_type"
                return ChainResult(
                    message="What kind of spread - cream cheese, butter?",
                    state=state,
                    chain_complete=False,
                )

            return ChainResult(
                message="Would you like any spread on that?",
                state=state,
                chain_complete=False,
            )

        if awaiting == "spread_type":
            spread = self._extract_spread(input_lower)
            if spread:
                current.spread = spread.get("spread")
                current.spread_type = spread.get("spread_type")
            return self._determine_next_question(state)

        if awaiting == "extras":
            if self._is_negative(input_lower):
                return self._confirm_item(state)

            extras = self._extract_extras(input_lower)
            if extras:
                current.extras.extend(extras)

            return self._confirm_item(state)

        if awaiting == "confirm":
            if self._is_affirmative(input_lower):
                bagel_state.add_current_item()
                return self._ask_for_another(state)
            elif self._is_negative(input_lower):
                # Let them modify - what would they like to change?
                return ChainResult(
                    message="What would you like to change?",
                    state=state,
                    chain_complete=False,
                )
            # Try to parse as a modification
            return self._handle_modification(state, input_lower, user_input)

        if awaiting == "another":
            if self._is_affirmative(input_lower):
                return self._start_new_item(state, "", "")
            return self._finish_bagel_ordering(state)

        # Default: try to parse as new order details
        return self._start_new_item(state, input_lower, user_input)

    def _determine_next_question(self, state: OrderState) -> ChainResult:
        """Determine what to ask next based on current item state."""
        bagel_state = state.bagels
        current = bagel_state.current_item

        if not current:
            bagel_state.awaiting = "bagel_type"
            return ChainResult(
                message="What kind of bagel would you like?",
                state=state,
                chain_complete=False,
            )

        # Check what's missing
        # We'll ask about toasted, spread, and extras in sequence

        # Only ask about toasted if not already set (None = not asked yet)
        if current.toasted is None and bagel_state.awaiting != "toasted":
            bagel_state.awaiting = "toasted"
            return ChainResult(
                message=f"Would you like the {current.bagel_type} bagel toasted?",
                state=state,
                chain_complete=False,
            )

        # Ask about spread if not set
        if current.spread is None and bagel_state.awaiting not in ("spread", "spread_type", "extras", "confirm"):
            bagel_state.awaiting = "spread"
            return ChainResult(
                message="Any spread - cream cheese, butter?",
                state=state,
                chain_complete=False,
            )

        # Ask about extras/toppings
        if not current.extras and bagel_state.awaiting not in ("extras", "confirm"):
            bagel_state.awaiting = "extras"
            return ChainResult(
                message="Anything else on it - lox, bacon, tomato?",
                state=state,
                chain_complete=False,
            )

        # Ready to confirm
        return self._confirm_item(state)

    def _confirm_item(self, state: OrderState) -> ChainResult:
        """Confirm the current item with user."""
        bagel_state = state.bagels
        current = bagel_state.current_item

        # Update price
        current.unit_price = self._calculate_price(current)

        description = current.get_description()
        price = current.unit_price * current.quantity

        bagel_state.awaiting = "confirm"
        return ChainResult(
            message=f"Got it - {description} (${price:.2f}). Sound good?",
            state=state,
            chain_complete=False,
        )

    def _ask_for_another(self, state: OrderState) -> ChainResult:
        """Ask if they want another bagel."""
        state.bagels.awaiting = "another"
        return ChainResult(
            message="Would you like another bagel?",
            state=state,
            chain_complete=False,
        )

    def _finish_bagel_ordering(self, state: OrderState) -> ChainResult:
        """Finish bagel ordering and transition to next chain."""
        bagel_state = state.bagels

        # Add any pending item
        if bagel_state.current_item:
            bagel_state.add_current_item()

        bagel_state.awaiting = None

        # If user already mentioned coffee, go directly to coffee ordering
        if state.pending_coffee:
            state.pending_coffee = False  # Clear the flag
            return ChainResult(
                message="Now for your coffee - what would you like?",
                state=state,
                chain_complete=True,
                next_chain=ChainName.COFFEE,
            )

        if state.coffee.items or self._should_suggest_coffee():
            return ChainResult(
                message="Would you like any coffee or other drinks?",
                state=state,
                chain_complete=True,
                next_chain=ChainName.COFFEE,
            )

        return ChainResult(
            message="",
            state=state,
            chain_complete=True,
            next_chain=ChainName.CHECKOUT,
            needs_user_input=False,
        )

    def _handle_modification(
        self, state: OrderState, input_lower: str, user_input: str
    ) -> ChainResult:
        """Handle modification requests for current item."""
        current = state.bagels.current_item

        # Check for toasted modification
        if "toast" in input_lower:
            if "not" in input_lower or "no" in input_lower:
                current.toasted = False
            else:
                current.toasted = True
            return self._confirm_item(state)

        # Check for spread modification
        spread = self._extract_spread(input_lower)
        if spread:
            current.spread = spread.get("spread")
            current.spread_type = spread.get("spread_type")
            return self._confirm_item(state)

        # Check for bagel type change
        bagel_type = self._extract_bagel_type(input_lower)
        if bagel_type:
            current.bagel_type = bagel_type
            return self._confirm_item(state)

        return ChainResult(
            message="What would you like to change about your order?",
            state=state,
            chain_complete=False,
        )

    # --- Parsing helpers ---

    def _parse_bagel_order(self, text: str) -> dict:
        """Parse a complete bagel order from text."""
        result = {}
        text_lower = text.lower()

        # Extract bagel type
        bagel_type = self._extract_bagel_type(text_lower)
        if bagel_type:
            result["bagel_type"] = bagel_type

        # Extract quantity
        result["quantity"] = self._extract_quantity(text_lower)

        # Check for toasted
        if "toast" in text_lower:
            result["toasted"] = "not toast" not in text_lower and "no toast" not in text_lower

        # Extract spread
        spread = self._extract_spread(text_lower)
        if spread:
            result["spread"] = spread.get("spread")
            result["spread_type"] = spread.get("spread_type")

        # Extract extras
        extras = self._extract_extras(text_lower)
        if extras:
            result["extras"] = extras

        return result

    def _extract_bagel_type(self, text: str) -> Optional[str]:
        """Extract bagel type from text."""
        for bagel in self.bagel_types:
            if bagel.lower() in text:
                return bagel
        return None

    def _extract_quantity(self, text: str) -> int:
        """Extract quantity from text."""
        # Check for number words
        word_to_num = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "a": 1, "an": 1, "dozen": 12, "half dozen": 6,
        }
        for word, num in word_to_num.items():
            if word in text:
                return num

        # Check for digits
        match = re.search(r"\b(\d+)\b", text)
        if match:
            return int(match.group(1))

        return 1

    def _extract_spread(self, text: str) -> Optional[dict]:
        """Extract spread information from text."""
        result = {}

        # Check for specific spreads
        if "cream cheese" in text or "schmear" in text:
            result["spread"] = "cream cheese"
            # Check for type
            if "scallion" in text or "chive" in text:
                result["spread_type"] = "scallion"
            elif "vegetable" in text or "veggie" in text:
                result["spread_type"] = "vegetable"
            elif "lox" in text:
                result["spread_type"] = "lox"
            elif "plain" in text:
                result["spread_type"] = "plain"
            else:
                result["spread_type"] = "plain"
        elif "butter" in text:
            result["spread"] = "butter"
        elif "peanut butter" in text:
            result["spread"] = "peanut butter"

        return result if result else None

    def _extract_extras(self, text: str) -> list[str]:
        """Extract extras/toppings from text."""
        found = []
        for extra in self.extras:
            if extra.lower() in text:
                found.append(extra)
        return found

    def _is_affirmative(self, text: str) -> bool:
        """Check for affirmative response."""
        patterns = [
            r"^(yes|yeah|yep|yup|sure|ok|okay|please|sounds? good)[\s!.]*$",
        ]
        return any(re.search(p, text) for p in patterns)

    def _is_negative(self, text: str) -> bool:
        """Check for negative response."""
        patterns = [
            r"^(no|nope|nah|i.m good|nothing|none|no thanks?)[\s!.]*$",
        ]
        return any(re.search(p, text) for p in patterns)

    def _is_done_ordering(self, text: str) -> bool:
        """Check if user is done ordering bagels."""
        patterns = [
            r"\b(that.s (it|all|everything)|i.m (done|good|finished)|nothing else|all set)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def _mentions_coffee(self, text: str) -> bool:
        """Check if user mentions coffee."""
        patterns = [
            r"\b(coffee|latte|espresso|cappuccino|tea|drink)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def _mentions_bagel(self, text: str) -> bool:
        """Check if user mentions bagel or sandwich."""
        patterns = [
            r"\b(bagel|sandwich|cream cheese|lox|toasted)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def _wants_checkout(self, text: str) -> bool:
        """Check if user wants to checkout."""
        patterns = [
            r"\b(check\s*out|pay|done|ready to pay|that.s all)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def _should_suggest_coffee(self) -> bool:
        """Determine if we should suggest coffee."""
        # Could be based on time of day, menu data, etc.
        return True

    def _calculate_price(self, item: BagelItem) -> float:
        """
        Calculate price for a bagel item using menu data.

        Price = base bagel + spread (if any) + extras
        """
        base_price = self.prices.get("bagel_base", 2.50)
        spread_price = self.prices.get("spread", 1.50) if item.spread else 0

        # Get extras prices from menu data
        extras_prices = self.prices.get("extras", {})
        extras_total = sum(extras_prices.get(e.lower(), 0.50) for e in item.extras)

        # Check if there's a matching signature item with specific pricing
        if self._menu_index:
            for menu_item in self.menu_items:
                item_name = menu_item.get("name", "").lower()
                # Match on bagel type
                if item.bagel_type.lower() in item_name:
                    base_price = menu_item.get("base_price", base_price)
                    break

        return base_price + spread_price + extras_total

    def get_awaiting_field(self, state: OrderState) -> Optional[str]:
        """Get the field this chain is waiting for."""
        return state.bagels.awaiting
