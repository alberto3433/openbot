"""
CoffeeChain - handles coffee/beverage ordering flow.

This chain handles:
- Drink type selection
- Size selection
- Hot or iced preference
- Milk preference
- Sweetener/extras
"""

import re
from typing import Optional, Any, Dict, List

from .base import BaseChain
from .state import OrderState, ChainResult, ChainName, CoffeeItem


# Default coffee menu data (used when no menu_index is provided)
DEFAULT_DRINK_TYPES = [
    "drip coffee", "cold brew", "latte", "cappuccino", "americano",
    "espresso", "macchiato", "mocha", "tea", "hot chocolate"
]

DEFAULT_MILK_OPTIONS = [
    "whole", "skim", "2%", "oat", "almond", "soy", "coconut", "none"
]

DEFAULT_SWEETENERS = [
    "sugar", "honey", "stevia", "splenda", "vanilla", "caramel", "hazelnut"
]

DEFAULT_BASE_PRICES = {
    "drip coffee": {"small": 2.00, "medium": 2.50, "large": 3.00},
    "cold brew": {"small": 3.50, "medium": 4.00, "large": 4.50},
    "latte": {"small": 4.00, "medium": 4.75, "large": 5.50},
    "cappuccino": {"small": 4.00, "medium": 4.50, "large": 5.00},
    "americano": {"small": 2.50, "medium": 3.00, "large": 3.50},
    "espresso": {"small": 2.50, "medium": 2.50, "large": 2.50},
    "macchiato": {"small": 3.50, "medium": 3.50, "large": 3.50},
    "mocha": {"small": 4.50, "medium": 5.25, "large": 6.00},
    "tea": {"small": 2.00, "medium": 2.50, "large": 3.00},
    "hot chocolate": {"small": 3.00, "medium": 3.50, "large": 4.00},
}


def _extract_coffee_menu_data(menu_index: Optional[Dict]) -> Dict[str, Any]:
    """
    Extract coffee/beverage-relevant data from the menu_index.

    The menu_index contains:
    - drinks: List of drink menu items with name, base_price, item_type
    - item_types: Dict with configurable item type attributes including:
        - size: Options with price_modifier
        - milk: Options with price_modifier (oat, almond, etc.)
        - syrup: Options with price_modifier (vanilla, caramel, etc.)
    """
    if not menu_index:
        return {
            "drink_types": DEFAULT_DRINK_TYPES,
            "milk_options": DEFAULT_MILK_OPTIONS,
            "sweeteners": DEFAULT_SWEETENERS,
            "drink_items": [],
            "size_prices": {},
            "milk_prices": {},
            "syrup_prices": {},
        }

    # Extract drink names from the drinks category
    drink_items = menu_index.get("drinks", [])
    drink_types = [item.get("name") for item in drink_items if item.get("name")]

    # If no drinks in menu, use defaults
    if not drink_types:
        drink_types = DEFAULT_DRINK_TYPES

    # Extract configurable attributes from item_types
    item_types = menu_index.get("item_types", {})
    coffee_type = item_types.get("coffee", {}) or item_types.get("drink", {}) or {}
    attributes = coffee_type.get("attributes", [])

    # Extract size prices
    size_prices = {}
    milk_options = list(DEFAULT_MILK_OPTIONS)
    milk_prices = {}
    sweeteners = list(DEFAULT_SWEETENERS)
    syrup_prices = {}

    for attr in attributes:
        attr_slug = attr.get("slug", "")

        if attr_slug == "size":
            for opt in attr.get("options", []):
                size_slug = opt.get("slug", "")
                price_mod = opt.get("price_modifier", 0)
                size_prices[size_slug] = price_mod

        elif attr_slug == "milk":
            milk_options = []
            for opt in attr.get("options", []):
                milk_name = opt.get("display_name", opt.get("slug", ""))
                milk_options.append(milk_name)
                milk_prices[opt.get("slug", "")] = opt.get("price_modifier", 0)

        elif attr_slug == "syrup":
            sweeteners = []
            for opt in attr.get("options", []):
                syrup_name = opt.get("display_name", opt.get("slug", ""))
                sweeteners.append(syrup_name)
                syrup_prices[opt.get("slug", "")] = opt.get("price_modifier", 0)

    # Use defaults if nothing found
    if not milk_options:
        milk_options = DEFAULT_MILK_OPTIONS
    if not sweeteners:
        sweeteners = DEFAULT_SWEETENERS

    return {
        "drink_types": drink_types,
        "milk_options": milk_options,
        "sweeteners": sweeteners,
        "drink_items": drink_items,
        "size_prices": size_prices,
        "milk_prices": milk_prices,
        "syrup_prices": syrup_prices,
    }


class CoffeeChain(BaseChain):
    """
    Chain for handling coffee/beverage orders.

    Flow:
    1. What drink?
    2. Size?
    3. Hot or iced?
    4. Milk preference? (for applicable drinks)
    5. Any sweetener?
    6. Confirm item -> Add to order
    7. Another drink? -> Loop or complete
    """

    chain_name = ChainName.COFFEE

    def __init__(
        self,
        menu_data: Optional[dict] = None,
        llm: Optional[Any] = None,
    ):
        """
        Initialize CoffeeChain.

        Args:
            menu_data: The menu_index dict from build_menu_index(), containing:
                - drinks: List of drink menu items with pricing
                - item_types: Configurable attributes (size, milk, syrup) with price modifiers
            llm: Optional LLM for complex parsing (not currently used)
        """
        super().__init__(menu_data=menu_data, llm=llm)

        # Extract and normalize menu data
        extracted = _extract_coffee_menu_data(menu_data)
        self.drink_types = extracted["drink_types"]
        self.milk_options = extracted["milk_options"]
        self.sweeteners = extracted["sweeteners"]
        self.drink_items = extracted["drink_items"]
        self.size_prices = extracted["size_prices"]
        self.milk_prices = extracted["milk_prices"]
        self.syrup_prices = extracted["syrup_prices"]

        # Keep reference to full menu for advanced lookups
        self._menu_index = menu_data

    def invoke(self, state: OrderState, user_input: str) -> ChainResult:
        """Process coffee ordering input."""
        input_lower = user_input.lower().strip()
        coffee_state = state.coffee

        # Check if user doesn't want coffee
        if self._is_negative(input_lower) and coffee_state.current_item is None:
            return self._finish_coffee_ordering(state, skipped=True)

        # Check if user is done ordering
        if self._is_done_ordering(input_lower):
            return self._finish_coffee_ordering(state)

        # Check if user wants to go back to bagels
        if self._mentions_bagels(input_lower):
            if coffee_state.current_item:
                coffee_state.add_current_item()
            return ChainResult(
                message="Sure! What kind of bagel would you like?",
                state=state,
                chain_complete=True,
                next_chain=ChainName.BAGEL,
            )

        # Check if user wants to checkout
        if self._wants_checkout(input_lower):
            if coffee_state.current_item:
                coffee_state.add_current_item()
            return ChainResult(
                message="",
                state=state,
                chain_complete=True,
                next_chain=ChainName.CHECKOUT,
                needs_user_input=False,
            )

        # If no current item, start a new one
        if coffee_state.current_item is None:
            return self._start_new_item(state, input_lower)

        # Continue building current item based on awaiting field
        return self._continue_current_item(state, input_lower)

    def _start_new_item(self, state: OrderState, input_lower: str) -> ChainResult:
        """Start building a new coffee item."""
        coffee_state = state.coffee

        # Try to parse coffee details from input
        parsed = self._parse_coffee_order(input_lower)

        if parsed.get("drink_type"):
            # Create new item with parsed data
            coffee_state.current_item = CoffeeItem(
                drink_type=parsed["drink_type"],
                size=parsed.get("size"),
                iced=parsed.get("iced", False),
                milk=parsed.get("milk"),
                sweetener=parsed.get("sweetener"),
                sweetener_quantity=parsed.get("sweetener_quantity", 1),
                flavor_syrup=parsed.get("flavor_syrup"),
            )

            # Calculate price
            coffee_state.current_item.unit_price = self._calculate_price(
                coffee_state.current_item
            )

            # Determine what to ask next
            return self._determine_next_question(state)

        # Couldn't parse - ask if they want anything else
        coffee_state.awaiting = "drink_type"
        return ChainResult(
            message="Anything else?",
            state=state,
            chain_complete=False,
        )

    def _continue_current_item(self, state: OrderState, input_lower: str) -> ChainResult:
        """Continue building the current coffee item."""
        coffee_state = state.coffee
        current = coffee_state.current_item
        awaiting = coffee_state.awaiting

        if awaiting == "drink_type":
            drink_type = self._extract_drink_type(input_lower)
            if drink_type:
                current.drink_type = drink_type
                return self._determine_next_question(state)
            return ChainResult(
                message="Anything else?",
                state=state,
                chain_complete=False,
            )

        if awaiting == "size":
            size = self._extract_size(input_lower)
            if size:
                current.size = size
                return self._determine_next_question(state)
            # If they just say yes/confirm, default to medium
            if self._is_affirmative(input_lower):
                current.size = "medium"
                return self._determine_next_question(state)
            return ChainResult(
                message="What size - small, medium, or large?",
                state=state,
                chain_complete=False,
            )

        if awaiting == "iced":
            if self._is_affirmative(input_lower) or "iced" in input_lower or "cold" in input_lower:
                current.iced = True
            else:
                current.iced = False
            return self._determine_next_question(state)

        if awaiting == "milk":
            if self._is_negative(input_lower) or "black" in input_lower or "none" in input_lower:
                current.milk = None
                return self._determine_next_question(state)
            milk = self._extract_milk(input_lower)
            if milk:
                current.milk = milk
                return self._determine_next_question(state)
            # Couldn't extract milk - list available options
            milk_list = ", ".join(self.milk_options[:5]) if self.milk_options else "whole, oat, almond, skim, 2%"
            return ChainResult(
                message=f"We have {milk_list}. Which would you like?",
                state=state,
                chain_complete=False,
            )

        if awaiting == "sweetener":
            if self._is_negative(input_lower):
                current.sweetener = None
            else:
                sweetener = self._extract_sweetener(input_lower)
                current.sweetener = sweetener
            return self._confirm_item(state)

        if awaiting == "confirm":
            if self._is_affirmative(input_lower):
                coffee_state.add_current_item()
                return self._ask_for_another(state)
            elif self._is_negative(input_lower):
                return ChainResult(
                    message="What would you like to change?",
                    state=state,
                    chain_complete=False,
                )
            # Try to parse as modification
            return self._handle_modification(state, input_lower)

        if awaiting == "another":
            if self._is_affirmative(input_lower):
                return self._start_new_item(state, "")
            return self._finish_coffee_ordering(state)

        # Default: try to parse as new order details
        return self._start_new_item(state, input_lower)

    def _determine_next_question(self, state: OrderState) -> ChainResult:
        """Determine what to ask next based on current item state."""
        coffee_state = state.coffee
        current = coffee_state.current_item

        if not current:
            coffee_state.awaiting = "drink_type"
            return ChainResult(
                message="Anything else?",
                state=state,
                chain_complete=False,
            )

        # Check for size (skip for espresso shots which are standard)
        if current.size is None and current.drink_type not in ("espresso", "macchiato"):
            coffee_state.awaiting = "size"
            return ChainResult(
                message="What size - small, medium, or large?",
                state=state,
                chain_complete=False,
            )

        # Check for hot/iced preference for applicable drinks (only if not already answered)
        if current.iced is None and current.drink_type in ("coffee", "drip coffee", "latte", "americano", "mocha"):
            coffee_state.awaiting = "iced"
            return ChainResult(
                message="Hot or iced?",
                state=state,
                chain_complete=False,
            )

        # Check for milk preference for applicable drinks
        milk_drinks = ("latte", "cappuccino", "macchiato", "mocha", "hot chocolate")
        if current.milk is None and current.drink_type in milk_drinks:
            if coffee_state.awaiting != "milk":
                coffee_state.awaiting = "milk"
                return ChainResult(
                    message="What kind of milk - whole, oat, almond?",
                    state=state,
                    chain_complete=False,
                )

        # Check for sweetener
        if current.sweetener is None and coffee_state.awaiting not in ("sweetener", "confirm"):
            coffee_state.awaiting = "sweetener"
            return ChainResult(
                message="Any sweetener or flavor?",
                state=state,
                chain_complete=False,
            )

        # Ready to confirm
        return self._confirm_item(state)

    def _confirm_item(self, state: OrderState) -> ChainResult:
        """Confirm the current drink with user."""
        coffee_state = state.coffee
        current = coffee_state.current_item

        # Update price
        current.unit_price = self._calculate_price(current)

        description = current.get_description()
        price = current.unit_price

        coffee_state.awaiting = "confirm"
        return ChainResult(
            message=f"Got it - {description} (${price:.2f}). Sound good?",
            state=state,
            chain_complete=False,
        )

    def _ask_for_another(self, state: OrderState) -> ChainResult:
        """Ask if they want another drink."""
        state.coffee.awaiting = "another"
        return ChainResult(
            message="Would you like another drink?",
            state=state,
            chain_complete=False,
        )

    def _finish_coffee_ordering(self, state: OrderState, skipped: bool = False) -> ChainResult:
        """Finish coffee ordering and transition to checkout."""
        coffee_state = state.coffee

        # Add any pending item
        if coffee_state.current_item:
            coffee_state.add_current_item()

        coffee_state.awaiting = None

        if skipped and not state.has_items():
            return ChainResult(
                message="No problem! What can I get for you then?",
                state=state,
                chain_complete=True,
                next_chain=ChainName.BAGEL,
            )

        return ChainResult(
            message="",
            state=state,
            chain_complete=True,
            next_chain=ChainName.CHECKOUT,
            needs_user_input=False,
        )

    def _handle_modification(self, state: OrderState, input_lower: str) -> ChainResult:
        """Handle modification requests for current item."""
        current = state.coffee.current_item

        # Check for size modification
        size = self._extract_size(input_lower)
        if size:
            current.size = size
            return self._confirm_item(state)

        # Check for iced/hot modification
        if "iced" in input_lower or "cold" in input_lower:
            current.iced = True
            return self._confirm_item(state)
        if "hot" in input_lower:
            current.iced = False
            return self._confirm_item(state)

        # Check for milk modification
        milk = self._extract_milk(input_lower)
        if milk:
            current.milk = milk
            return self._confirm_item(state)

        # Check for flavor syrup modification
        flavor_syrup = self._extract_flavor_syrup(input_lower)
        if flavor_syrup:
            current.flavor_syrup = flavor_syrup
            return self._confirm_item(state)

        # Check for sweetener modification with quantity
        sweetener, quantity = self._extract_sweetener_with_quantity(input_lower)
        if sweetener:
            current.sweetener = sweetener
            current.sweetener_quantity = quantity
            return self._confirm_item(state)

        return ChainResult(
            message="What would you like to change?",
            state=state,
            chain_complete=False,
        )

    # --- Parsing helpers ---

    def _parse_coffee_order(self, text: str) -> dict:
        """Parse a complete coffee order from text."""
        result = {}

        # Extract drink type
        drink_type = self._extract_drink_type(text)
        if drink_type:
            result["drink_type"] = drink_type

        # Extract size
        size = self._extract_size(text)
        if size:
            result["size"] = size

        # Check for iced
        if "iced" in text or "cold" in text:
            result["iced"] = True
        elif "hot" in text:
            result["iced"] = False

        # Extract milk
        milk = self._extract_milk(text)
        if milk:
            result["milk"] = milk

        # Extract flavor syrup (vanilla, caramel, hazelnut, etc.)
        flavor_syrup = self._extract_flavor_syrup(text)
        if flavor_syrup:
            result["flavor_syrup"] = flavor_syrup

        # Extract sweetener and quantity (sugar, splenda, stevia, etc.)
        sweetener, quantity = self._extract_sweetener_with_quantity(text)
        if sweetener:
            result["sweetener"] = sweetener
            result["sweetener_quantity"] = quantity

        return result

    def _extract_drink_type(self, text: str) -> Optional[str]:
        """Extract drink type from text."""
        # Normalize text
        text = text.lower()

        # Map common variations to standard names
        type_aliases = {
            "drip": "drip coffee",
            "regular coffee": "drip coffee",
            "just coffee": "drip coffee",
            "black coffee": "drip coffee",
            "dark roast": "drip coffee",
            "dark": "drip coffee",
            "light roast": "drip coffee",
            "medium roast": "drip coffee",
            "house coffee": "drip coffee",
            "coldbrew": "cold brew",
            "cap": "cappuccino",
            "capp": "cappuccino",
            "espresso shot": "espresso",
        }

        for alias, standard in type_aliases.items():
            if alias in text:
                return standard

        for drink in self.drink_types:
            if drink.lower() in text:
                return drink

        # Simple coffee mention
        if "coffee" in text and "cold" not in text:
            return "drip coffee"

        return None

    def _extract_size(self, text: str) -> Optional[str]:
        """Extract size from text."""
        if "small" in text:
            return "small"
        if "medium" in text or "regular" in text:
            return "medium"
        if "large" in text or "big" in text:
            return "large"
        return None

    def _extract_milk(self, text: str) -> Optional[str]:
        """Extract milk preference from text."""
        milk_aliases = {
            "oat milk": "oat",
            "oatmilk": "oat",
            "almond milk": "almond",
            "soy milk": "soy",
            "coconut milk": "coconut",
            "skim milk": "skim",
            "whole milk": "whole",
            "2 percent": "2%",
            "two percent": "2%",
        }

        for alias, milk in milk_aliases.items():
            if alias in text:
                return milk

        for milk in self.milk_options:
            if milk.lower() in text:
                return milk

        return None

    def _extract_sweetener(self, text: str) -> Optional[str]:
        """Extract sweetener from text."""
        for sweetener in self.sweeteners:
            if sweetener.lower() in text:
                return sweetener
        return None

    def _extract_flavor_syrup(self, text: str) -> Optional[str]:
        """Extract flavor syrup from text (vanilla, caramel, hazelnut, etc.)."""
        text_lower = text.lower()
        # Flavor syrups - these are liquid flavoring additions
        flavor_syrups = ["vanilla", "caramel", "hazelnut", "mocha", "pumpkin spice", "lavender", "cinnamon"]
        for syrup in flavor_syrups:
            # Check for "vanilla syrup", "with vanilla", just "vanilla" when in coffee context
            if syrup in text_lower:
                return syrup
        return None

    def _extract_sweetener_with_quantity(self, text: str) -> tuple[Optional[str], int]:
        """Extract sweetener type and quantity from text.

        Examples:
        - "2 splendas" -> ("splenda", 2)
        - "splenda" -> ("splenda", 1)
        - "three sugars" -> ("sugar", 3)
        """
        text_lower = text.lower()
        # Sweeteners are packets/portions (NOT syrups)
        packet_sweeteners = ["splenda", "sugar", "stevia", "equal", "sweet n low", "honey"]

        # Number word mappings
        number_words = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "a": 1, "an": 1
        }

        for sweetener in packet_sweeteners:
            if sweetener in text_lower:
                quantity = 1
                # Look for quantity patterns like "2 splendas", "two splendas"
                import re
                # Check for digit before sweetener
                digit_match = re.search(rf'(\d+)\s*{sweetener}', text_lower)
                if digit_match:
                    quantity = int(digit_match.group(1))
                else:
                    # Check for word number before sweetener
                    for word, num in number_words.items():
                        if re.search(rf'\b{word}\s+{sweetener}', text_lower):
                            quantity = num
                            break
                return (sweetener, quantity)

        return (None, 1)

    def _extract_all_sweeteners(self, text: str) -> List[str]:
        """Extract all sweeteners/syrups from text."""
        found = []
        text_lower = text.lower()
        for sweetener in self.sweeteners:
            if sweetener.lower() in text_lower:
                found.append(sweetener)
        # Also check for "syrup" variations
        syrup_map = {
            "vanilla syrup": "vanilla",
            "caramel syrup": "caramel",
            "hazelnut syrup": "hazelnut",
        }
        for phrase, sweetener in syrup_map.items():
            if phrase in text_lower and sweetener not in found:
                found.append(sweetener)
        return found

    def _is_affirmative(self, text: str) -> bool:
        """Check for affirmative response."""
        patterns = [
            r"^(yes|yeah|yep|yup|sure|ok|okay|please|sounds? good|perfect)[\s!.]*$",
        ]
        return any(re.search(p, text) for p in patterns)

    def _is_negative(self, text: str) -> bool:
        """Check for negative response."""
        patterns = [
            r"^(no|nope|nah|i.m good|nothing|none|no thanks?|skip)[\s!.]*$",
        ]
        return any(re.search(p, text) for p in patterns)

    def _is_done_ordering(self, text: str) -> bool:
        """Check if user is done ordering."""
        patterns = [
            r"\b(that.s (it|all|everything)|i.m (done|good|finished)|nothing else|all set)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def _mentions_bagels(self, text: str) -> bool:
        """Check if user mentions bagels."""
        patterns = [
            r"\b(bagel|cream cheese|toasted)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def _wants_checkout(self, text: str) -> bool:
        """Check if user wants to checkout."""
        patterns = [
            r"\b(check\s*out|pay|done|ready to pay)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def _calculate_price(self, item: CoffeeItem) -> float:
        """Calculate price for a coffee item using menu data."""
        # Find base price from menu drink_items
        base_price = None
        if self.drink_items:
            drink_type_lower = item.drink_type.lower() if item.drink_type else ""
            for drink in self.drink_items:
                drink_name = drink.get("name", "").lower()
                if drink_name == drink_type_lower or drink_type_lower in drink_name:
                    base_price = drink.get("base_price")
                    break

        # Fall back to hardcoded defaults if menu data not available
        if base_price is None:
            default_prices = {
                "drip coffee": {"small": 2.00, "medium": 2.50, "large": 3.00},
                "cold brew": {"small": 3.50, "medium": 4.00, "large": 4.50},
                "latte": {"small": 4.00, "medium": 4.75, "large": 5.50},
                "cappuccino": {"small": 4.00, "medium": 4.50, "large": 5.00},
                "americano": {"small": 2.50, "medium": 3.00, "large": 3.50},
                "espresso": {"small": 2.50, "medium": 2.50, "large": 2.50},
                "macchiato": {"small": 3.50, "medium": 3.50, "large": 3.50},
                "mocha": {"small": 4.50, "medium": 5.25, "large": 6.00},
                "tea": {"small": 2.00, "medium": 2.50, "large": 3.00},
                "hot chocolate": {"small": 3.00, "medium": 3.50, "large": 4.00},
            }
            drink_prices = default_prices.get(
                item.drink_type, {"small": 3.00, "medium": 3.50, "large": 4.00}
            )
            size = item.size or "medium"
            base_price = drink_prices.get(size, 3.50)

        # Add size modifier from menu data
        size_modifier = 0.0
        if item.size and self.size_prices:
            size_modifier = self.size_prices.get(item.size, 0)

        # Add milk modifier from menu data or fallback
        milk_modifier = 0.0
        if item.milk:
            if self.milk_prices:
                milk_modifier = self.milk_prices.get(item.milk, 0)
            else:
                # Fallback: premium milk prices
                premium_milks = {"oat": 0.75, "almond": 0.75, "coconut": 0.75, "soy": 0.50}
                milk_modifier = premium_milks.get(item.milk, 0)

        # Add sweetener/syrup modifier from menu data or fallback
        syrup_modifier = 0.0
        if item.sweetener:
            if self.syrup_prices:
                syrup_modifier = self.syrup_prices.get(item.sweetener, 0)
            else:
                # Fallback: flavor syrups
                if item.sweetener in ("vanilla", "caramel", "hazelnut"):
                    syrup_modifier = 0.75

        return base_price + size_modifier + milk_modifier + syrup_modifier

    def get_awaiting_field(self, state: OrderState) -> Optional[str]:
        """Get the field this chain is waiting for."""
        return state.coffee.awaiting
