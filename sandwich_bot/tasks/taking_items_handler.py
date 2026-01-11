"""
Taking Items Handler for Order State Machine.

This module handles the taking items phase of the order flow including
greeting, processing new item orders, and multi-item order coordination.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import re
import uuid
from typing import Callable, TYPE_CHECKING

from sandwich_bot.menu_data_cache import menu_cache

from .models import (
    OrderTask,
    BagelItemTask,
    CoffeeItemTask,
    MenuItemTask,
    TaskStatus,
)
from .schemas.phases import OrderPhase
from .schemas import (
    StateMachineResult,
    OpenInputResponse,
    ExtractedModifiers,
    ExtractedCoffeeModifiers,
    CoffeeOrderDetails,
    # ParsedItem types for multi-item handling
    ParsedMenuItemEntry,
    ParsedBagelEntry,
    ParsedCoffeeEntry,
    ParsedSideItemEntry,
    ParsedItem,
)
from .parsers import parse_open_input, extract_modifiers_from_input
from .modifier_operations import (
    find_modifier_on_any_item,
    remove_modifier_from_item,
    find_default_ingredient_on_any_item,
    remove_default_ingredient_from_item,
)
from .parsers.constants import (
    DEFAULT_PAGINATION_SIZE,
    get_bagel_types,
    get_bagel_spreads,
    get_proteins,
    get_cheeses,
    get_toppings,
    resolve_soda_alias,
    resolve_coffee_alias,
    resolve_side_alias,
    resolve_menu_item_alias,
)

if TYPE_CHECKING:
    from .handler_config import HandlerConfig
    from .pricing import PricingEngine
    from .coffee_config_handler import CoffeeConfigHandler
    from .item_adder_handler import ItemAdderHandler
    from .menu_inquiry_handler import MenuInquiryHandler
    from .store_info_handler import StoreInfoHandler
    from .by_pound_handler import ByPoundHandler
    from .checkout_utils_handler import CheckoutUtilsHandler
    from .checkout_handler import CheckoutHandler

logger = logging.getLogger(__name__)


# Ordinal reference mapping for "remove the second bagel", "cancel the 3rd coffee", etc.
ORDINAL_WORDS = {
    "first": 1, "1st": 1,
    "second": 2, "2nd": 2,
    "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4,
    "fifth": 5, "5th": 5,
    "sixth": 6, "6th": 6,
    "seventh": 7, "7th": 7,
    "eighth": 8, "8th": 8,
    "ninth": 9, "9th": 9,
    "tenth": 10, "10th": 10,
}


def _get_syrup_options() -> list[str]:
    """Get syrup options from database, converted to lowercase for matching.

    Returns list of syrup names like ["vanilla", "caramel", "hazelnut", ...].
    Falls back to hardcoded list if database not loaded.
    """
    db_syrups = menu_cache.get_beverage_syrups()
    if db_syrups:
        # Convert display names like "Vanilla Syrup" -> "vanilla"
        return [s.lower().replace(" syrup", "").strip() for s in db_syrups]
    # Fallback if database not loaded
    return ["vanilla", "caramel", "hazelnut", "mocha", "pumpkin spice",
            "cinnamon", "lavender", "almond"]


def _get_milk_options_coffee() -> list[tuple[str, str]]:
    """Get milk options for sized_beverage MenuItemTask from database.

    Returns list of (pattern, value) tuples like [("oat milk", "oat"), ...].
    Falls back to hardcoded list if database not loaded.
    """
    db_milks = menu_cache.get_beverage_milks()
    if db_milks:
        options = []
        for milk in db_milks:
            milk_lower = milk.lower()
            # Create value: "Oat Milk" -> "oat", "Half & Half" -> "half and half"
            value = milk_lower.replace(" milk", "").replace("&", "and").strip()
            # Add full pattern first ("oat milk"), then short form ("oat")
            options.append((milk_lower.replace("&", "and"), value))
            short_form = value.replace(" and ", " ").strip()
            if short_form != milk_lower.replace("&", "and"):
                options.append((short_form, value))
        # Add generic "milk" at the end to default to whole milk
        options.append(("milk", "whole"))
        return options
    # Fallback if database not loaded
    return [
        ("oat milk", "oat"), ("almond milk", "almond"),
        ("soy milk", "soy"), ("coconut milk", "coconut"),
        ("whole milk", "whole"), ("skim milk", "skim"),
        ("2% milk", "2%"), ("half and half", "half and half"),
        ("oat", "oat"), ("almond", "almond"),
        ("soy", "soy"), ("coconut", "coconut"),
        ("milk", "whole"),
    ]


def _get_milk_options_espresso() -> list[tuple[str, str, str]]:
    """Get milk options for espresso-type MenuItemTask from database.

    Returns list of (pattern, slug, display_name) tuples.
    Falls back to hardcoded list if database not loaded.
    """
    db_milks = menu_cache.get_beverage_milks()
    if db_milks:
        options = []
        for milk in db_milks:
            milk_lower = milk.lower()
            # Create slug: "Oat Milk" -> "oat_milk", "Half & Half" -> "half_n_half"
            slug = milk_lower.replace(" ", "_").replace("&", "n").replace("__", "_")
            display = milk  # Keep original display name
            # Add full pattern first
            pattern = milk_lower.replace("&", "and")
            options.append((pattern, slug, display))
            # Add short form (without "milk")
            short_form = milk_lower.replace(" milk", "").replace("&", "and").strip()
            if short_form != pattern:
                options.append((short_form, slug, display))
        return options
    # Fallback if database not loaded
    return [
        ("oat milk", "oat_milk", "Oat Milk"), ("almond milk", "almond_milk", "Almond Milk"),
        ("soy milk", "soy_milk", "Soy Milk"), ("coconut milk", "coconut_milk", "Coconut Milk"),
        ("whole milk", "whole_milk", "Whole Milk"), ("skim milk", "skim_milk", "Skim Milk"),
        ("half and half", "half_n_half", "Half & Half"),
        ("oat", "oat_milk", "Oat Milk"), ("almond", "almond_milk", "Almond Milk"),
        ("soy", "soy_milk", "Soy Milk"), ("coconut", "coconut_milk", "Coconut Milk"),
    ]


def _get_sweetener_options() -> list[str]:
    """Get sweetener options from database, converted to lowercase for matching.

    Returns list of sweetener names like ["sugar", "splenda", ...].
    Falls back to hardcoded list if database not loaded.
    """
    db_sweeteners = menu_cache.get_beverage_sweeteners()
    if db_sweeteners:
        # Convert display names to lowercase patterns
        # Handle special cases like "Sweet N Low" -> "sweet n low"
        return [s.lower().replace("'", "").strip() for s in db_sweeteners]
    # Fallback if database not loaded
    return ["sugar", "splenda", "stevia", "honey", "equal", "sweet n low"]


def _get_sweetener_options_espresso() -> list[tuple[str, str, str]]:
    """Get sweetener options for espresso-type MenuItemTask from database.

    Returns list of (name, slug, display_name) tuples.
    Falls back to hardcoded list if database not loaded.
    """
    db_sweeteners = menu_cache.get_beverage_sweeteners()
    if db_sweeteners:
        options = []
        for sweetener in db_sweeteners:
            name = sweetener.lower().replace("'", "").strip()
            # Create slug: "Sweet N Low" -> "sweet_n_low"
            slug = name.replace(" ", "_")
            display = sweetener
            options.append((name, slug, display))
        return options
    # Fallback if database not loaded
    return [
        ("sugar", "sugar", "Sugar"), ("splenda", "splenda", "Splenda"),
        ("stevia", "stevia", "Stevia"), ("honey", "honey", "Honey"),
        ("equal", "equal", "Equal"), ("sweet n low", "sweet_n_low", "Sweet N Low"),
    ]


def extract_ordinal_reference(cancel_desc: str) -> tuple[int | None, str]:
    """
    Extract ordinal reference from a cancellation description.

    Args:
        cancel_desc: The cancellation description (e.g., "second bagel", "3rd coffee")

    Returns:
        Tuple of (ordinal_index, item_type) where ordinal_index is 1-based (or None if no ordinal),
        and item_type is the cleaned item type string (e.g., "bagel", "coffee").
    """
    words = cancel_desc.lower().split()

    # Check if first word is an ordinal
    if words and words[0] in ORDINAL_WORDS:
        ordinal_index = ORDINAL_WORDS[words[0]]
        item_type = " ".join(words[1:])  # e.g., "second bagel" -> "bagel"
        return ordinal_index, item_type

    # Check for patterns like "bagel 2" or "coffee #3"
    if len(words) >= 2:
        last_word = words[-1].lstrip("#")
        if last_word.isdigit():
            ordinal_index = int(last_word)
            item_type = " ".join(words[:-1])  # e.g., "bagel 2" -> "bagel"
            return ordinal_index, item_type

    return None, cancel_desc


def find_nth_item_of_type(
    items: list,
    item_type_keyword: str,
    n: int,
) -> tuple | None:
    """
    Find the Nth item of a given type from a list.

    Args:
        items: List of items to search
        item_type_keyword: The type keyword to match (e.g., "bagel", "coffee", "item")
        n: 1-based index (1 = first, 2 = second, etc.)

    Returns:
        Tuple of (item, original_index) if found, None otherwise.

    Special cases:
        - "item" matches any item (position-based removal)
        - Synonyms are resolved (e.g., "coke" -> "Coca-Cola")
    """
    if n < 1:
        return None

    # Handle generic "item" keyword - match any item by position
    if item_type_keyword.lower() in ("item", "items", "one", "thing"):
        if n <= len(items):
            return (items[n - 1], n - 1)
        return None

    # Resolve synonyms to canonical names
    keyword_lower = item_type_keyword.lower()
    canonical_soda = resolve_soda_alias(keyword_lower)
    canonical_coffee = resolve_coffee_alias(keyword_lower)

    matching_items = []
    for idx, item in enumerate(items):
        item_summary = item.get_summary().lower()
        item_type = getattr(item, 'item_type', '') or ''
        item_name = getattr(item, 'menu_item_name', '') or ''
        item_name_lower = item_name.lower()

        # Check if this item matches the type keyword
        matches = False

        # Direct keyword match in summary or type
        if (keyword_lower in item_summary or
            keyword_lower == item_type or
            (item_type and item_type in keyword_lower)):
            matches = True
        # Check canonical soda name match (e.g., "coke" -> "Coca-Cola")
        elif canonical_soda != keyword_lower and canonical_soda.lower() in item_name_lower:
            matches = True
        # Check canonical coffee name match
        elif canonical_coffee != keyword_lower and canonical_coffee.lower() in item_name_lower:
            matches = True
        # Check if menu_item_name contains keyword
        elif keyword_lower in item_name_lower:
            matches = True

        if matches:
            matching_items.append((item, idx))

    # Return the Nth match (1-based index)
    if n <= len(matching_items):
        return matching_items[n - 1]

    return None


class TakingItemsHandler:
    """
    Handles the taking items phase of order flow.

    Manages greeting, processing new item orders, and
    multi-item order coordination.
    """

    def __init__(
        self,
        config: "HandlerConfig | None" = None,
        coffee_handler: "CoffeeConfigHandler | None" = None,
        item_adder_handler: "ItemAdderHandler | None" = None,
        menu_inquiry_handler: "MenuInquiryHandler | None" = None,
        store_info_handler: "StoreInfoHandler | None" = None,
        by_pound_handler: "ByPoundHandler | None" = None,
        checkout_utils_handler: "CheckoutUtilsHandler | None" = None,
        checkout_handler: "CheckoutHandler | None" = None,
        **kwargs,
    ) -> None:
        """
        Initialize the taking items handler.

        Args:
            config: HandlerConfig with shared dependencies.
            coffee_handler: Handler for coffee items.
            item_adder_handler: Handler for adding items.
            menu_inquiry_handler: Handler for menu inquiries.
            store_info_handler: Handler for store info inquiries.
            by_pound_handler: Handler for by-pound items.
            checkout_utils_handler: Handler for checkout utilities.
            checkout_handler: Handler for checkout flow including confirmation/repeat orders.
            **kwargs: Legacy parameter support.
        """
        if config:
            self.model = config.model
            self.pricing = config.pricing
            self._menu_data = config.menu_data or {}
        else:
            # Legacy support for direct parameters
            self.model = kwargs.get("model", "gpt-4o-mini")
            self.pricing = kwargs.get("pricing")
            self._menu_data = {}

        # Handler-specific dependencies
        self.coffee_handler = coffee_handler or kwargs.get("coffee_handler")
        self.item_adder_handler = item_adder_handler or kwargs.get("item_adder_handler")
        self.menu_inquiry_handler = menu_inquiry_handler or kwargs.get("menu_inquiry_handler")
        self.store_info_handler = store_info_handler or kwargs.get("store_info_handler")
        self.by_pound_handler = by_pound_handler or kwargs.get("by_pound_handler")
        self.checkout_utils_handler = checkout_utils_handler or kwargs.get("checkout_utils_handler")
        self.checkout_handler = checkout_handler or kwargs.get("checkout_handler")

        # Context set per-request
        self._spread_types: list[str] = []
        self._returning_customer: dict | None = None
        self._set_repeat_info_callback: Callable[[bool, str | None], None] | None = None

    @property
    def menu_data(self) -> dict:
        """Get menu data for configuration checks."""
        return self._menu_data

    @menu_data.setter
    def menu_data(self, value: dict) -> None:
        """Set menu data for configuration checks."""
        self._menu_data = value or {}

    @property
    def _modifier_category_keywords(self) -> dict[str, str]:
        """Get modifier category keyword mapping from menu data."""
        modifier_cats = self._menu_data.get("modifier_categories", {})
        return modifier_cats.get("keyword_to_category", {})

    @property
    def _modifier_item_keywords(self) -> dict[str, str]:
        """Get item keyword to item type slug mapping from menu data."""
        return self._menu_data.get("item_keywords", {})

    @property
    def _ingredient_to_items(self) -> dict[str, list[dict]]:
        """Get ingredient-to-items mapping for ingredient-based menu search."""
        return self._menu_data.get("ingredient_to_items", {})

    def _get_bagel_menu_item_info(self, menu_item_name: str) -> dict | None:
        """
        Check if a menu item contains a bagel and get its configuration info.

        Args:
            menu_item_name: The name of the menu item to check.

        Returns:
            Dict with {id, name, default_bagel_type} if item contains bagel,
            None otherwise.
        """
        if not menu_item_name:
            return None

        bagel_menu_items = self._menu_data.get("bagel_menu_items", [])
        menu_item_lower = menu_item_name.lower().strip()

        for item in bagel_menu_items:
            item_name = item.get("name", "")
            if item_name.lower().strip() == menu_item_lower:
                return item

        return None

    def set_context(
        self,
        spread_types: list[str],
        returning_customer: dict | None,
        set_repeat_info_callback: Callable[[bool, str | None], None] | None = None,
    ) -> None:
        """Set per-request context."""
        self._spread_types = spread_types
        self._returning_customer = returning_customer
        self._set_repeat_info_callback = set_repeat_info_callback

    def handle_greeting(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle greeting phase."""
        parsed = parse_open_input(
            user_input,
            model=self.model,
            spread_types=self._spread_types,
            modifier_category_keywords=self._modifier_category_keywords,
            modifier_item_keywords=self._modifier_item_keywords,
            ingredient_to_items=self._ingredient_to_items,
        )

        logger.info(
            "Greeting phase parsed: is_greeting=%s, unclear=%s, parsed_items=%d",
            parsed.is_greeting,
            parsed.unclear,
            len(parsed.parsed_items),
        )

        if parsed.is_greeting or parsed.unclear:
            # Phase will be derived as TAKING_ITEMS by orchestrator on next turn
            return StateMachineResult(
                message="Hi! Welcome to Zucker's. What can I get for you today?",
                order=order,
            )

        # User might have ordered something directly - pass the already parsed result
        # Also extract modifiers from the raw input
        extracted_modifiers = extract_modifiers_from_input(user_input)
        if extracted_modifiers.has_modifiers():
            logger.info("Extracted modifiers from greeting input: %s", extracted_modifiers)

        # Phase is derived from orchestrator, no need to set explicitly
        return self.handle_taking_items_with_parsed(parsed, order, extracted_modifiers, user_input)

    def handle_taking_items(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle taking new item orders."""
        # Check for "make it 2" pattern early (before LLM parsing)
        from .parsers.deterministic import MAKE_IT_N_PATTERN
        make_it_n_match = MAKE_IT_N_PATTERN.match(user_input.strip())
        if make_it_n_match:
            num_str = None
            for i in range(1, 8):
                if make_it_n_match.group(i):
                    num_str = make_it_n_match.group(i).lower()
                    break
            if num_str:
                word_to_num = {
                    "two": 2, "three": 3, "four": 4, "five": 5,
                    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
                }
                if num_str.isdigit():
                    target_qty = int(num_str)
                else:
                    target_qty = word_to_num.get(num_str, 0)

                if target_qty >= 2:
                    active_items = order.items.get_active_items()
                    if active_items:
                        last_item = active_items[-1]
                        last_item_name = last_item.get_summary()
                        added_count = target_qty - 1

                        for _ in range(added_count):
                            new_item = last_item.model_copy(deep=True)
                            new_item.id = str(uuid.uuid4())
                            new_item.mark_complete()
                            order.items.add_item(new_item)

                        logger.info("TAKING_ITEMS: Added %d more of '%s'", added_count, last_item_name)

                        if added_count == 1:
                            return StateMachineResult(
                                message=f"I've added a second {last_item_name}. Anything else?",
                                order=order,
                            )
                        else:
                            return StateMachineResult(
                                message=f"I've added {added_count} more {last_item_name}. Anything else?",
                                order=order,
                            )

        # Check for "add [modifier]" patterns early (before LLM parsing)
        # This allows "add vanilla syrup" to be handled without LLM
        input_lower = user_input.lower().strip()
        active_items = order.items.get_active_items()

        add_modifier_patterns = [
            r"^add\s+",  # "add vanilla syrup"
            r"^with\s+",  # "with caramel"
            r"^can\s+(?:i|you)\s+(?:get|add)\s+",  # "can I get vanilla"
            r"^(?:i'?d?\s+)?like\s+(?:to\s+)?add\s+",  # "I'd like to add vanilla"
            r"^put\s+",  # "put vanilla in it"
            r"^can\s+you\s+put\s+",  # "can you put milk in that"
            r"put\s+.+?\s+in\s+(?:it|that|the|my)",  # "put milk in that"
        ]

        is_add_modifier_request = any(
            re.search(pattern, input_lower) for pattern in add_modifier_patterns
        )

        # Coffee modifiers that should trigger modification instead of new item
        # Build from database-driven helper functions
        coffee_modifiers = set(_get_syrup_options()) | {"syrup"}
        coffee_modifiers |= {pattern for pattern, _ in _get_milk_options_coffee()}
        coffee_modifiers |= set(_get_sweetener_options()) | {"sweetener"}

        has_coffee_modifier = any(mod in input_lower for mod in coffee_modifiers)

        # Check if this is a pure modifier input (e.g., "2 vanilla syrups", "vanilla syrup")
        # that should be added to an existing beverage
        is_pure_modifier_input = False
        if has_coffee_modifier and active_items:
            last_item = active_items[-1]
            is_beverage = (
                isinstance(last_item, MenuItemTask) and
                (last_item.is_sized_beverage or last_item.menu_item_type == "espresso")
            )
            if is_beverage:
                # Check if input is ONLY a modifier (no other item keywords)
                non_modifier_keywords = {
                    "bagel", "coffee", "latte", "espresso", "cappuccino", "americano",
                    "tea", "chai", "matcha", "sandwich", "croissant", "muffin",
                    "juice", "soda", "water", "cold brew", "drip",
                }
                has_other_item = any(kw in input_lower for kw in non_modifier_keywords)
                if not has_other_item:
                    is_pure_modifier_input = True

        # If it's an "add modifier" pattern OR pure modifier input, and the last item is a beverage, modify it
        if (is_add_modifier_request or is_pure_modifier_input) and has_coffee_modifier and active_items:
            last_item = active_items[-1]
            if getattr(last_item, 'is_sized_beverage', False):
                made_change = False

                # Check for syrup - add to array if not already present
                syrup_options = _get_syrup_options()
                for syrup in syrup_options:
                    if syrup in input_lower:
                        # Check if this syrup is already in the list
                        existing_syrups = [s.get("flavor") for s in last_item.flavor_syrups]
                        if syrup not in existing_syrups:
                            # Extract quantity: "2 vanilla syrups", "double vanilla"
                            quantity = 1
                            qty_match = re.search(rf'(\d+|one|two|three|four|five|double|triple)\s+{syrup}', input_lower)
                            if qty_match:
                                qty_str = qty_match.group(1)
                                word_to_num = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "double": 2, "triple": 3}
                                quantity = int(qty_str) if qty_str.isdigit() else word_to_num.get(qty_str, 1)
                            last_item.flavor_syrups.append({"flavor": syrup, "quantity": quantity})
                            logger.info("Early add modifier: added syrup '%s' (qty=%d) to coffee (now has %d syrups)",
                                      syrup, quantity, len(last_item.flavor_syrups))
                            made_change = True
                        break

                # Check for milk options (alternatives and regular)
                milk_options = _get_milk_options_coffee()
                for pattern, milk_value in milk_options:
                    if pattern in input_lower:
                        if last_item.milk != milk_value:
                            old_milk = last_item.milk or "none"
                            last_item.milk = milk_value
                            logger.info("Early add modifier: added milk '%s' to coffee (was '%s')", milk_value, old_milk)
                            made_change = True
                        break

                # Check for sweeteners - add to array if not already present
                sweetener_options = _get_sweetener_options()
                for sweetener in sweetener_options:
                    if sweetener in input_lower:
                        # Check if this sweetener type is already in the list
                        existing_sweeteners = [s.get("type") for s in last_item.sweeteners]
                        if sweetener not in existing_sweeteners:
                            quantity = 1
                            # Check for quantity: "two sugars", "2 splenda"
                            qty_match = re.search(rf'(\d+|one|two|three|four|five)\s+{sweetener}', input_lower)
                            if qty_match:
                                qty_str = qty_match.group(1)
                                word_to_num = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
                                quantity = int(qty_str) if qty_str.isdigit() else word_to_num.get(qty_str, 1)
                            last_item.sweeteners.append({"type": sweetener, "quantity": quantity})
                            logger.info("Early add modifier: added sweetener '%s' (qty=%d) to coffee",
                                      sweetener, quantity)
                            made_change = True
                        break

                if made_change:
                    self.pricing.recalculate_coffee_price(last_item)
                    updated_summary = last_item.get_summary()
                    return StateMachineResult(
                        message=f"Sure, I've added that to your {updated_summary}. Anything else?",
                        order=order,
                    )

            # Also handle espresso MenuItemTask
            elif isinstance(last_item, MenuItemTask) and last_item.menu_item_type == "espresso":
                made_change = False

                # Get current milk_sweetener_syrup selections
                mss_slugs = last_item.attribute_values.get("milk_sweetener_syrup", [])
                mss_selections = last_item.attribute_values.get("milk_sweetener_syrup_selections", [])

                # Check for syrup - add to attribute_values
                syrup_options = _get_syrup_options()
                for syrup in syrup_options:
                    if syrup in input_lower:
                        syrup_slug = syrup.lower().replace(" ", "_")
                        if syrup_slug not in mss_slugs:
                            # Extract quantity
                            quantity = 1
                            qty_match = re.search(rf'(\d+|one|two|three|four|five|double|triple)\s+{syrup}', input_lower)
                            if qty_match:
                                qty_str = qty_match.group(1)
                                word_to_num = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "double": 2, "triple": 3}
                                quantity = int(qty_str) if qty_str.isdigit() else word_to_num.get(qty_str, 1)
                            mss_slugs.append(syrup_slug)
                            mss_selections.append({
                                "slug": syrup_slug,
                                "display_name": syrup.title(),
                                "quantity": quantity,
                            })
                            logger.info("Early add modifier: added syrup '%s' (qty=%d) to espresso",
                                      syrup, quantity)
                            made_change = True
                        break

                # Check for milk options
                milk_options = _get_milk_options_espresso()
                for pattern, milk_slug, milk_display in milk_options:
                    if pattern in input_lower:
                        if milk_slug not in mss_slugs:
                            mss_slugs.append(milk_slug)
                            mss_selections.append({
                                "slug": milk_slug,
                                "display_name": milk_display,
                                "quantity": 1,
                            })
                            logger.info("Early add modifier: added milk '%s' to espresso", milk_slug)
                            made_change = True
                        break

                # Check for sweeteners
                sweetener_options = _get_sweetener_options_espresso()
                for sweetener_name, sweetener_slug, sweetener_display in sweetener_options:
                    if sweetener_name in input_lower:
                        if sweetener_slug not in mss_slugs:
                            quantity = 1
                            qty_match = re.search(rf'(\d+|one|two|three|four|five)\s+{sweetener_name}', input_lower)
                            if qty_match:
                                qty_str = qty_match.group(1)
                                word_to_num = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
                                quantity = int(qty_str) if qty_str.isdigit() else word_to_num.get(qty_str, 1)
                            mss_slugs.append(sweetener_slug)
                            mss_selections.append({
                                "slug": sweetener_slug,
                                "display_name": sweetener_display,
                                "quantity": quantity,
                            })
                            logger.info("Early add modifier: added sweetener '%s' (qty=%d) to espresso",
                                      sweetener_name, quantity)
                            made_change = True
                        break

                if made_change:
                    # Update attribute_values
                    last_item.attribute_values["milk_sweetener_syrup"] = mss_slugs
                    last_item.attribute_values["milk_sweetener_syrup_selections"] = mss_selections
                    updated_summary = last_item.get_summary()
                    return StateMachineResult(
                        message=f"Sure, I've added that to your {updated_summary}. Anything else?",
                        order=order,
                    )

        parsed = parse_open_input(
            user_input,
            model=self.model,
            spread_types=self._spread_types,
            modifier_category_keywords=self._modifier_category_keywords,
            modifier_item_keywords=self._modifier_item_keywords,
            ingredient_to_items=self._ingredient_to_items,
        )

        # Extract modifiers from raw input (keyword-based, no LLM)
        extracted_modifiers = extract_modifiers_from_input(user_input)
        if extracted_modifiers.has_modifiers():
            logger.info("Extracted modifiers from input: %s", extracted_modifiers)

        return self.handle_taking_items_with_parsed(parsed, order, extracted_modifiers, user_input)

    def handle_taking_items_with_parsed(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        extracted_modifiers: ExtractedModifiers | None = None,
        raw_user_input: str | None = None,
    ) -> StateMachineResult:
        """Handle taking new item orders with already-parsed input."""
        logger.info(
            "Parsed open input: parsed_items=%d, done_ordering=%s",
            len(parsed.parsed_items),
            parsed.done_ordering,
        )

        # Reset menu pagination on any non-"more items" request
        if not parsed.wants_more_menu_items:
            order.clear_menu_pagination()
            order.pending_ingredient_search = None

        if parsed.done_ordering:
            return self.checkout_utils_handler.transition_to_checkout(order)

        # Handle ingredient-based menu search
        # When user says "chicken" or "something with bacon", show matching items
        if parsed.ingredient_search_matches:
            ingredient = parsed.ingredient_search_query or "that ingredient"
            matches = parsed.ingredient_search_matches
            logger.info(
                "INGREDIENT SEARCH: showing %d items with '%s'",
                len(matches), ingredient
            )

            # Build a nice response showing the matching items
            if len(matches) == 1:
                item = matches[0]
                item_name = item.get("name", "that item")
                desc = item.get("description", "")
                msg = f"For {ingredient}, we have the {item_name}"
                if desc:
                    msg += f" ({desc})"
                msg += ". Would you like one?"
            else:
                # Multiple items - list them (cap at 6 for initial display)
                display_count = min(6, len(matches))
                item_names = [m.get("name", "item") for m in matches[:display_count]]
                has_more = len(matches) > display_count

                # Format the list properly
                if len(item_names) == 1:
                    items_list = item_names[0]
                elif len(item_names) == 2:
                    items_list = f"{item_names[0]} or {item_names[1]}"
                elif has_more:
                    # "Item1, Item2, ..., Item6, and X more" (no "or" before "and")
                    items_list = ", ".join(item_names)
                    items_list += f", and {len(matches) - display_count} more"
                else:
                    # "Item1, Item2, Item3, Item4, Item5, or Item6"
                    items_list = ", ".join(item_names[:-1]) + f", or {item_names[-1]}"

                msg = f"For items with {ingredient}, we have: {items_list}. Which would you like?"

                # Store pagination state for "what else" follow-up
                if has_more:
                    order.pending_ingredient_search = {
                        "ingredient": ingredient,
                        "matches": matches,
                        "offset": display_count,
                    }

            return StateMachineResult(
                message=msg,
                order=order,
            )

        # Handle "add [modifier]" patterns that should modify the last coffee
        # e.g., "add vanilla syrup", "add oat milk", "with caramel"
        if raw_user_input:
            input_lower = raw_user_input.lower().strip()
            active_items = order.items.get_active_items()

            # Check if this looks like a modifier addition for the last coffee
            # Patterns: "add X", "with X", "can I get X", "I'd like X added"
            add_modifier_patterns = [
                r"^add\s+",  # "add vanilla syrup"
                r"^with\s+",  # "with caramel"
                r"^can\s+(?:i|you)\s+(?:get|add)\s+",  # "can I get vanilla"
                r"^(?:i'?d?\s+)?like\s+(?:to\s+)?add\s+",  # "I'd like to add vanilla"
                r"^put\s+",  # "put vanilla in it"
                r"^can\s+you\s+put\s+",  # "can you put milk in that"
                r"put\s+.+?\s+in\s+(?:it|that|the|my)",  # "put milk in that"
            ]

            is_add_modifier_request = any(
                re.search(pattern, input_lower) for pattern in add_modifier_patterns
            )

            # Coffee modifiers that should trigger modification instead of new item
            # Build from database-driven helper functions
            coffee_modifiers = set(_get_syrup_options()) | {"syrup"}
            coffee_modifiers |= {pattern for pattern, _ in _get_milk_options_coffee()}
            coffee_modifiers |= set(_get_sweetener_options()) | {"sweetener"}

            has_coffee_modifier = any(mod in input_lower for mod in coffee_modifiers)

            # Check if this is a pure modifier input (e.g., "2 vanilla syrups", "vanilla syrup")
            # that should be added to an existing beverage
            is_pure_modifier_input = False
            if has_coffee_modifier and active_items:
                last_item_check = active_items[-1]
                is_beverage = (
                    isinstance(last_item_check, MenuItemTask) and
                    (last_item_check.is_sized_beverage or last_item_check.menu_item_type == "espresso")
                )
                if is_beverage:
                    # Check if input is ONLY a modifier (no other item keywords)
                    non_modifier_keywords = {
                        "bagel", "coffee", "latte", "espresso", "cappuccino", "americano",
                        "tea", "chai", "matcha", "sandwich", "croissant", "muffin",
                        "juice", "soda", "water", "cold brew", "drip",
                    }
                    has_other_item = any(kw in input_lower for kw in non_modifier_keywords)
                    if not has_other_item:
                        is_pure_modifier_input = True

            # If it's an "add modifier" pattern OR pure modifier input, and the last item is a beverage, modify it
            if (is_add_modifier_request or is_pure_modifier_input) and has_coffee_modifier and active_items:
                last_item = active_items[-1]
                if getattr(last_item, 'is_sized_beverage', False):
                    made_change = False

                    # Check for syrup - add to array if not already present
                    syrup_options = _get_syrup_options()
                    for syrup in syrup_options:
                        if syrup in input_lower:
                            # Check if this syrup is already in the list
                            existing_syrups = [s.get("flavor") for s in last_item.flavor_syrups]
                            if syrup not in existing_syrups:
                                # Extract quantity: "2 vanilla syrups", "double vanilla"
                                quantity = 1
                                qty_match = re.search(rf'(\d+|one|two|three|four|five|double|triple)\s+{syrup}', input_lower)
                                if qty_match:
                                    qty_str = qty_match.group(1)
                                    word_to_num = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "double": 2, "triple": 3}
                                    quantity = int(qty_str) if qty_str.isdigit() else word_to_num.get(qty_str, 1)
                                last_item.flavor_syrups.append({"flavor": syrup, "quantity": quantity})
                                logger.info("Add modifier: added syrup '%s' (qty=%d) to coffee (now has %d syrups)",
                                          syrup, quantity, len(last_item.flavor_syrups))
                                made_change = True
                            break

                    # Check for milk options (alternatives and regular)
                    milk_options = _get_milk_options_coffee()
                    for pattern, milk_value in milk_options:
                        if pattern in input_lower:
                            if last_item.milk != milk_value:
                                old_milk = last_item.milk or "none"
                                last_item.milk = milk_value
                                logger.info("Add modifier: added milk '%s' to coffee (was '%s')", milk_value, old_milk)
                                made_change = True
                            break

                    # Check for sweeteners - add to array if not already present
                    sweetener_options = _get_sweetener_options()
                    for sweetener in sweetener_options:
                        if sweetener in input_lower:
                            # Check if this sweetener type is already in the list
                            existing_sweeteners = [s.get("type") for s in last_item.sweeteners]
                            if sweetener not in existing_sweeteners:
                                quantity = 1
                                # Check for quantity: "two sugars", "2 splenda"
                                qty_match = re.search(rf'(\d+|one|two|three|four|five)\s+{sweetener}', input_lower)
                                if qty_match:
                                    qty_str = qty_match.group(1)
                                    word_to_num = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
                                    quantity = int(qty_str) if qty_str.isdigit() else word_to_num.get(qty_str, 1)
                                last_item.sweeteners.append({"type": sweetener, "quantity": quantity})
                                logger.info("Add modifier: added sweetener '%s' (qty=%d) to coffee",
                                          sweetener, quantity)
                                made_change = True
                            break

                    if made_change:
                        self.pricing.recalculate_coffee_price(last_item)
                        updated_summary = last_item.get_summary()
                        return StateMachineResult(
                            message=f"Sure, I've added that to your {updated_summary}. Anything else?",
                            order=order,
                        )

                # Also handle espresso MenuItemTask
                elif isinstance(last_item, MenuItemTask) and last_item.menu_item_type == "espresso":
                    made_change = False

                    # Get current milk_sweetener_syrup selections
                    mss_slugs = last_item.attribute_values.get("milk_sweetener_syrup", [])
                    mss_selections = last_item.attribute_values.get("milk_sweetener_syrup_selections", [])

                    # Check for syrup - add to attribute_values
                    syrup_options = _get_syrup_options()
                    for syrup in syrup_options:
                        if syrup in input_lower:
                            syrup_slug = syrup.lower().replace(" ", "_")
                            if syrup_slug not in mss_slugs:
                                # Extract quantity
                                quantity = 1
                                qty_match = re.search(rf'(\d+|one|two|three|four|five|double|triple)\s+{syrup}', input_lower)
                                if qty_match:
                                    qty_str = qty_match.group(1)
                                    word_to_num = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "double": 2, "triple": 3}
                                    quantity = int(qty_str) if qty_str.isdigit() else word_to_num.get(qty_str, 1)
                                mss_slugs.append(syrup_slug)
                                mss_selections.append({
                                    "slug": syrup_slug,
                                    "display_name": syrup.title(),
                                    "quantity": quantity,
                                })
                                logger.info("Add modifier: added syrup '%s' (qty=%d) to espresso",
                                          syrup, quantity)
                                made_change = True
                            break

                    # Check for milk options
                    milk_options = _get_milk_options_espresso()
                    for pattern, milk_slug, milk_display in milk_options:
                        if pattern in input_lower:
                            if milk_slug not in mss_slugs:
                                mss_slugs.append(milk_slug)
                                mss_selections.append({
                                    "slug": milk_slug,
                                    "display_name": milk_display,
                                    "quantity": 1,
                                })
                                logger.info("Add modifier: added milk '%s' to espresso", milk_slug)
                                made_change = True
                            break

                    # Check for sweeteners
                    sweetener_options = _get_sweetener_options_espresso()
                    for sweetener_name, sweetener_slug, sweetener_display in sweetener_options:
                        if sweetener_name in input_lower:
                            if sweetener_slug not in mss_slugs:
                                quantity = 1
                                qty_match = re.search(rf'(\d+|one|two|three|four|five)\s+{sweetener_name}', input_lower)
                                if qty_match:
                                    qty_str = qty_match.group(1)
                                    word_to_num = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
                                    quantity = int(qty_str) if qty_str.isdigit() else word_to_num.get(qty_str, 1)
                                mss_slugs.append(sweetener_slug)
                                mss_selections.append({
                                    "slug": sweetener_slug,
                                    "display_name": sweetener_display,
                                    "quantity": quantity,
                                })
                                logger.info("Add modifier: added sweetener '%s' (qty=%d) to espresso",
                                          sweetener_name, quantity)
                                made_change = True
                            break

                    if made_change:
                        # Update attribute_values
                        last_item.attribute_values["milk_sweetener_syrup"] = mss_slugs
                        last_item.attribute_values["milk_sweetener_syrup_selections"] = mss_selections
                        updated_summary = last_item.get_summary()
                        return StateMachineResult(
                            message=f"Sure, I've added that to your {updated_summary}. Anything else?",
                            order=order,
                        )

            # Handle "add [spread]" for bagels - e.g., "add scallion cream cheese"
            # This should modify an existing bagel, not add a new "Scallion Cream Cheese Sandwich"
            if is_add_modifier_request and active_items:
                # Check if input contains a spread pattern (longer matches first)
                detected_spread = None
                for spread in sorted(get_bagel_spreads(), key=len, reverse=True):
                    if spread in input_lower:
                        detected_spread = spread
                        break

                if detected_spread:
                    # Find a bagel to add the spread to
                    # Prefer: 1) bagel without spread, 2) most recent bagel
                    bagels_in_cart = [i for i in active_items if isinstance(i, BagelItemTask)]
                    target_bagel = None

                    # First, look for a bagel without a spread
                    for bagel in reversed(bagels_in_cart):
                        if bagel.spread is None:
                            target_bagel = bagel
                            break

                    # If all bagels have spreads, use the most recent one
                    if target_bagel is None and bagels_in_cart:
                        target_bagel = bagels_in_cart[-1]

                    if target_bagel:
                        # Normalize the spread name
                        normalized_spread = menu_cache.normalize_modifier(detected_spread)
                        old_spread = target_bagel.spread

                        # Set the spread on the bagel
                        target_bagel.spread = normalized_spread

                        # Recalculate price
                        self.pricing.recalculate_bagel_price(target_bagel)
                        updated_summary = target_bagel.get_summary()

                        if old_spread:
                            logger.info("Add spread: changed spread from '%s' to '%s' on bagel", old_spread, normalized_spread)
                            return StateMachineResult(
                                message=f"Sure, I've changed the spread to {normalized_spread}. Your order is now {updated_summary}. Anything else?",
                                order=order,
                            )
                        else:
                            logger.info("Add spread: added '%s' to bagel", normalized_spread)
                            return StateMachineResult(
                                message=f"Sure, I've added {normalized_spread} to your bagel. Your order is now {updated_summary}. Anything else?",
                                order=order,
                            )

        # Handle modification to an existing item in the cart
        # e.g., "can I have scallion cream cheese on the cinnamon raisin bagel"
        # or "make the bagel with scallion cream cheese" (implicit target)
        # or "add mayo and mustard" (applies to last item in cart)
        if parsed.modify_existing_item:
            # Check for qualifier conflicts (e.g., "light extra mayo")
            # If conflicts exist, ask user for clarification
            if parsed.modify_qualifier_conflicts:
                conflict_messages = []
                for conflict in parsed.modify_qualifier_conflicts:
                    conflict_messages.append(
                        f"I heard both '{conflict.qualifier1}' and '{conflict.qualifier2}' for the {conflict.modifier}. "
                        f"Did you want {conflict.qualifier1} {conflict.modifier} or {conflict.qualifier2} {conflict.modifier}?"
                    )
                # Return first conflict for user to resolve
                logger.info("QUALIFIER CONFLICT: %s", parsed.modify_qualifier_conflicts)
                return StateMachineResult(
                    message=conflict_messages[0],
                    order=order,
                )

            target_desc = (parsed.modify_target_description or "").lower()
            active_items = order.items.get_active_items()

            # Find the item that matches the target description
            target_item = None
            bagels_in_cart = [i for i in active_items if isinstance(i, BagelItemTask)]
            menu_items_in_cart = [i for i in active_items if isinstance(i, MenuItemTask)]

            if target_desc:
                # Explicit target - find matching bagel by type
                for item in bagels_in_cart:
                    item_bagel_type = (item.bagel_type or "").lower()
                    # Match if the target description contains the bagel type
                    # e.g., "cinnamon raisin" matches a cinnamon raisin bagel
                    if item_bagel_type and item_bagel_type in target_desc:
                        target_item = item
                        break
                    # Also match if target is just "bagel" and there's only one bagel
                    if target_desc == "bagel" and len(bagels_in_cart) == 1:
                        target_item = item
                        break
                # Also check menu items by name if no bagel matched
                if not target_item:
                    for item in menu_items_in_cart:
                        item_name = (item.menu_item_name or "").lower()
                        if item_name and item_name in target_desc:
                            target_item = item
                            break
            else:
                # Implicit target ("add mayo", "add mustard", etc.)
                # Use the last item in the cart regardless of type
                if active_items:
                    target_item = active_items[-1]

            if target_item:
                # Handle MenuItemTask differently from BagelItemTask
                if isinstance(target_item, MenuItemTask):
                    # For MenuItemTask, add modifiers to attribute_values
                    if parsed.modify_add_modifiers:
                        # Determine which attribute to add to based on modifier type
                        known_condiments = {"mayo", "mustard", "russian dressing", "olive oil", "hot sauce",
                                           "ketchup", "honey mustard", "chipotle mayo", "sriracha"}
                        known_proteins = {p.lower() for p in get_proteins()}
                        known_cheeses = {c.lower() for c in get_cheeses()}
                        known_toppings = {t.lower() for t in get_toppings()}

                        for modifier in parsed.modify_add_modifiers:
                            # Handle qualified modifiers: "mayo (extra)" -> base="mayo", full="mayo_(extra)"
                            # Extract base modifier name for categorization
                            modifier_lower = modifier.lower()
                            base_modifier = modifier_lower.split(" (")[0].strip()  # "mayo (extra)" -> "mayo"
                            modifier_slug = modifier_lower.replace(" ", "_")  # Keep full "mayo_(extra)"

                            # Determine which attribute this modifier belongs to (using base name)
                            if base_modifier in known_condiments:
                                attr_key = "condiments"
                            elif base_modifier in known_proteins:
                                attr_key = "extra_protein"
                            elif base_modifier in known_cheeses:
                                attr_key = "extra_cheese"
                            elif base_modifier in known_toppings:
                                attr_key = "toppings"
                            else:
                                # Default to condiments for unknown modifiers
                                attr_key = "condiments"

                            # Get or create the list for this attribute
                            existing = target_item.attribute_values.get(attr_key)
                            if existing is None:
                                target_item.attribute_values[attr_key] = [modifier_slug]
                            elif isinstance(existing, list):
                                if modifier_slug not in existing:
                                    existing.append(modifier_slug)
                            else:
                                # Convert single value to list
                                target_item.attribute_values[attr_key] = [existing, modifier_slug]

                            logger.info("MODIFY ADD (MenuItemTask): Added '%s' to '%s' attribute",
                                       modifier, attr_key)

                    # Recalculate price for menu item
                    self.pricing.recalculate_menu_item_price(target_item)

                    updated_summary = target_item.get_summary()
                    item_name = target_item.menu_item_name
                    logger.info("MODIFY EXISTING (MenuItemTask): Updated '%s' with add_modifiers=%s",
                               item_name, parsed.modify_add_modifiers)
                    return StateMachineResult(
                        message=f"Sure, I've updated your {updated_summary}. Anything else?",
                        order=order,
                    )

                # BagelItemTask handling (original logic)
                # Apply the spread modification
                if parsed.modify_new_spread:
                    target_item.spread = parsed.modify_new_spread
                if parsed.modify_new_spread_type:
                    target_item.spread_type = parsed.modify_new_spread_type

                # Apply add-modifier modifications ("add bacon", "extra cheese", etc.)
                if parsed.modify_add_modifiers:
                    known_proteins = get_proteins()
                    known_cheeses = get_cheeses()
                    known_toppings = get_toppings()

                    for modifier in parsed.modify_add_modifiers:
                        # Handle qualified modifiers: "bacon (extra)" -> base="bacon"
                        # Extract base modifier name for categorization
                        modifier_lower = modifier.lower()
                        base_modifier = modifier_lower.split(" (")[0].strip()  # "bacon (extra)" -> "bacon"

                        # Check if the base modifier is a protein
                        if base_modifier in {p.lower() for p in known_proteins}:
                            # If no sandwich_protein set, use that field
                            if not target_item.sandwich_protein:
                                target_item.sandwich_protein = modifier  # Store full qualified modifier
                            else:
                                # Already have a protein, add to extras
                                if modifier not in target_item.extras:
                                    target_item.extras.append(modifier)
                        # Check if the base modifier is a cheese
                        elif base_modifier in {c.lower() for c in known_cheeses}:
                            if modifier not in target_item.extras:
                                target_item.extras.append(modifier)
                        # Check if the base modifier is a topping
                        elif base_modifier in {t.lower() for t in known_toppings}:
                            if modifier not in target_item.extras:
                                target_item.extras.append(modifier)
                        else:
                            # Unknown modifier type, add to extras anyway
                            if modifier not in target_item.extras:
                                target_item.extras.append(modifier)
                        logger.info("MODIFY ADD: Added '%s' to '%s'", modifier, target_item.bagel_type)

                # Recalculate price
                self.pricing.recalculate_bagel_price(target_item)

                updated_summary = target_item.get_summary()
                logger.info(
                    "MODIFY EXISTING: Updated '%s' with spread=%s, spread_type=%s, add_modifiers=%s",
                    target_item.bagel_type, parsed.modify_new_spread, parsed.modify_new_spread_type,
                    parsed.modify_add_modifiers
                )
                return StateMachineResult(
                    message=f"Sure, I've updated your {updated_summary}. Anything else?",
                    order=order,
                )
            else:
                # Couldn't find matching item - inform user
                if target_desc:
                    logger.warning(
                        "MODIFY EXISTING: Could not find item matching '%s' in cart",
                        target_desc
                    )
                    return StateMachineResult(
                        message=f"I couldn't find a {target_desc} in your order. Would you like to add one?",
                        order=order,
                    )
                else:
                    logger.warning("MODIFY EXISTING: No items in cart to modify")
                    return StateMachineResult(
                        message="I don't see any items in your order to modify. Would you like to add something?",
                        order=order,
                    )

        # Handle item replacement: "make it a coke instead", "change it to X", etc.
        replaced_item_name = None
        if parsed.replace_last_item:
            active_items = order.items.get_active_items()
            if active_items:
                last_item = active_items[-1]

                # Check if parsed result has any valid new items
                has_new_items = parsed.parsed_items or parsed.by_pound_items

                # Special case: If last item is a bagel and the "menu item" is a cream cheese sandwich,
                # treat this as a spread change, not a menu item replacement.
                # e.g., "make it blueberry cream cheese" -> change spread, not add Blueberry Cream Cheese Sandwich
                cream_cheese_menu_item = next(
                    (item for item in parsed.parsed_items
                     if isinstance(item, ParsedMenuItemEntry)
                     and "cream cheese sandwich" in item.menu_item_name.lower()),
                    None
                )
                if has_new_items and cream_cheese_menu_item and isinstance(last_item, BagelItemTask):
                    # Extract the spread name from the menu item name
                    # "Blueberry Cream Cheese Sandwich" -> "blueberry cream cheese"
                    spread_name = cream_cheese_menu_item.menu_item_name.lower().replace(" sandwich", "")
                    old_spread = last_item.spread or "none"
                    last_item.spread = spread_name
                    logger.info("Replacement: interpreted '%s' as spread change from '%s' to '%s'",
                               cream_cheese_menu_item.menu_item_name, old_spread, spread_name)

                    # Recalculate price if needed
                    self.pricing.recalculate_bagel_price(last_item)

                    updated_summary = last_item.get_summary()
                    return StateMachineResult(
                        message=f"Sure, I've changed that to {updated_summary}. Anything else?",
                        order=order,
                    )

                # Special case: If last item is a bagel and user wants to change to a different bagel,
                # preserve the existing modifiers (spread, toasted, protein, etc.)
                # e.g., "make it pumpernickel" when they have "plain bagel toasted with cream cheese"
                bagel_entry = next(
                    (item for item in parsed.parsed_items
                     if isinstance(item, ParsedBagelEntry) and item.bagel_type),
                    None
                )
                if has_new_items and bagel_entry and isinstance(last_item, BagelItemTask):
                    old_type = last_item.bagel_type or "plain"
                    last_item.bagel_type = bagel_entry.bagel_type
                    logger.info("Replacement: changed bagel type from '%s' to '%s', preserving modifiers",
                               old_type, bagel_entry.bagel_type)

                    # Recalculate price if needed
                    self.pricing.recalculate_bagel_price(last_item)

                    updated_summary = last_item.get_summary()
                    return StateMachineResult(
                        message=f"Sure, I've changed that to {updated_summary}. Anything else?",
                        order=order,
                    )

                # If no new items parsed and last item is a bagel, try applying as modifiers
                if not has_new_items and isinstance(last_item, BagelItemTask) and raw_user_input:
                    modifiers = extract_modifiers_from_input(raw_user_input)
                    has_modifiers = modifiers.proteins or modifiers.cheeses or modifiers.toppings

                    if has_modifiers:
                        # Apply modifiers to existing bagel instead of replacing
                        logger.info("Replacement: applying modifiers to existing bagel: %s", modifiers)

                        # Update protein - replace existing
                        if modifiers.proteins:
                            last_item.sandwich_protein = modifiers.proteins[0]
                            # Additional proteins go to extras (replace existing extras)
                            last_item.extras = list(modifiers.proteins[1:])
                        else:
                            # Clear protein if not in new modifiers
                            last_item.sandwich_protein = None
                            last_item.extras = []

                        # Add cheeses and toppings to extras
                        last_item.extras.extend(modifiers.cheeses)
                        last_item.extras.extend(modifiers.toppings)

                        # Update spread if specified
                        if modifiers.spreads:
                            last_item.spread = modifiers.spreads[0]
                        else:
                            last_item.spread = "none"

                        # Recalculate price with new modifiers
                        self.pricing.recalculate_bagel_price(last_item)

                        # Return confirmation with updated item
                        updated_summary = last_item.get_summary()
                        return StateMachineResult(
                            message=f"Sure, I've changed that to {updated_summary}. Anything else?",
                            order=order,
                        )
                    else:
                        # Check if user is changing the spread or bagel type
                        # e.g., "make it blueberry cream cheese", "replace with everything"
                        input_lower = raw_user_input.lower()

                        # Check for spread changes FIRST (longer matches before shorter)
                        # e.g., "blueberry cream cheese" should match before "blueberry" (bagel type)
                        new_spread = None
                        for spread in sorted(get_bagel_spreads(), key=len, reverse=True):
                            if spread in input_lower:
                                # Normalize the spread name
                                new_spread = menu_cache.normalize_modifier(spread)
                                break

                        if new_spread:
                            old_spread = last_item.spread or "none"
                            last_item.spread = new_spread
                            logger.info("Replacement: changed spread from '%s' to '%s'", old_spread, new_spread)

                            # Recalculate price if needed
                            self.pricing.recalculate_bagel_price(last_item)

                            updated_summary = last_item.get_summary()
                            return StateMachineResult(
                                message=f"Sure, I've changed that to {updated_summary}. Anything else?",
                                order=order,
                            )

                        # Check if user is changing the bagel type
                        # e.g., "replace with everything", "can you make it sesame?"
                        new_bagel_type = None
                        for bagel_type in get_bagel_types():
                            if bagel_type in input_lower:
                                new_bagel_type = bagel_type
                                break

                        if new_bagel_type:
                            old_type = last_item.bagel_type or "plain"
                            last_item.bagel_type = new_bagel_type
                            logger.info("Replacement: changed bagel type from '%s' to '%s'", old_type, new_bagel_type)

                            # Recalculate price if needed
                            self.pricing.recalculate_bagel_price(last_item)

                            updated_summary = last_item.get_summary()
                            return StateMachineResult(
                                message=f"Sure, I've changed that to {updated_summary}. Anything else?",
                                order=order,
                            )

                # If no new items parsed and last item is a coffee, check for size/style/milk changes
                if not has_new_items and getattr(last_item, 'is_sized_beverage', False) and raw_user_input:
                    input_lower = raw_user_input.lower()
                    made_change = False

                    # Check for size changes
                    new_size = None
                    for size in ["small", "large"]:
                        if size in input_lower:
                            new_size = size
                            break

                    if new_size and new_size != last_item.size:
                        old_size = last_item.size or "small"
                        last_item.size = new_size
                        logger.info("Replacement: changed coffee size from '%s' to '%s'", old_size, new_size)
                        made_change = True

                    # Check for style changes (hot/iced)
                    new_style = None
                    if "iced" in input_lower:
                        new_style = "iced"
                        last_item.iced = True
                    elif "hot" in input_lower:
                        new_style = "hot"
                        last_item.iced = False

                    if new_style:
                        logger.info("Replacement: changed coffee style to '%s'", new_style)
                        made_change = True

                    # Check for decaf changes
                    if "decaf" in input_lower:
                        if not last_item.decaf:
                            last_item.decaf = True
                            logger.info("Replacement: changed coffee to decaf")
                            made_change = True
                    elif "regular" in input_lower and last_item.decaf:
                        # "make it regular" means not decaf
                        last_item.decaf = None
                        logger.info("Replacement: changed coffee to regular (not decaf)")
                        made_change = True

                    # Check for milk changes - order matters, check longer patterns first
                    milk_options = _get_milk_options_coffee() + [("no milk", "none"), ("black", "none")]
                    new_milk = None
                    for pattern, milk_value in milk_options:
                        if pattern in input_lower:
                            new_milk = milk_value
                            break

                    if new_milk and new_milk != last_item.milk:
                        old_milk = last_item.milk or "none"
                        last_item.milk = new_milk if new_milk != "none" else None
                        logger.info("Replacement: changed coffee milk from '%s' to '%s'", old_milk, new_milk)
                        made_change = True

                    # Check for milk removal: "without milk", "remove the milk"
                    if (("without milk" in input_lower or "remove milk" in input_lower or
                         "remove the milk" in input_lower) and last_item.milk):
                        old_milk = last_item.milk
                        last_item.milk = None
                        last_item.milk_upcharge = 0.0
                        logger.info("Replacement: removed coffee milk '%s'", old_milk)
                        made_change = True

                    # Check for flavor syrup changes - add to array if not already present
                    syrup_options = _get_syrup_options()
                    new_syrup = None
                    for syrup in syrup_options:
                        if syrup in input_lower:
                            new_syrup = syrup
                            break

                    if new_syrup:
                        existing_syrups = [s.get("flavor") for s in last_item.flavor_syrups]
                        if new_syrup not in existing_syrups:
                            last_item.flavor_syrups.append({"flavor": new_syrup, "quantity": 1})
                            logger.info("Replacement: added coffee syrup '%s' (now has %d syrups)",
                                      new_syrup, len(last_item.flavor_syrups))
                            made_change = True

                    # Check for syrup removal: "no syrup", "remove the syrup"
                    if ("no syrup" in input_lower or "remove syrup" in input_lower or
                        "without syrup" in input_lower) and last_item.flavor_syrups:
                        old_syrups = [s.get("flavor") for s in last_item.flavor_syrups]
                        last_item.flavor_syrups = []
                        logger.info("Replacement: removed all coffee syrups %s", old_syrups)
                        made_change = True

                    # Check for sweetener removal: "without sugar", "remove the sugar"
                    if (("without sugar" in input_lower or "remove sugar" in input_lower or
                         "remove the sugar" in input_lower or "no sugar" in input_lower or
                         "without sweetener" in input_lower or "remove sweetener" in input_lower or
                         "no sweetener" in input_lower) and last_item.sweeteners):
                        old_sweeteners = [s.get("type") for s in last_item.sweeteners]
                        last_item.sweeteners = []
                        logger.info("Replacement: removed all coffee sweeteners %s", old_sweeteners)
                        made_change = True

                    # If any changes were made, recalculate price and return
                    if made_change:
                        self.pricing.recalculate_coffee_price(last_item)
                        updated_summary = last_item.get_summary()
                        return StateMachineResult(
                            message=f"Sure, I've changed that to {updated_summary}. Anything else?",
                            order=order,
                        )

                # Normal replacement: remove old item, new item will be added below
                replaced_item_name = last_item.get_summary()
                last_item_index = order.items.items.index(last_item)
                order.items.remove_item(last_item_index)
                logger.info("Replacement: removed last item '%s' from cart", replaced_item_name)
            else:
                logger.info("Replacement requested but no items in cart to replace")

        # Handle modifier removal: "remove the bacon", "no cheese", etc.
        # Use unified modifier operations to handle ALL item types (bagels, coffee, menu items)
        if parsed.cancel_item:
            active_items = order.items.get_active_items()
            if active_items:
                # Try to find a matching modifier on any item (checks most recent first)
                modifier_match = find_modifier_on_any_item(active_items, parsed.cancel_item)
                if modifier_match:
                    # Found a modifier match - remove it
                    result = remove_modifier_from_item(modifier_match.item, modifier_match)
                    if result.success:
                        # Recalculate price based on item type
                        if isinstance(modifier_match.item, BagelItemTask):
                            self.pricing.recalculate_bagel_price(modifier_match.item)
                        elif isinstance(modifier_match.item, MenuItemTask):
                            if modifier_match.item.is_sized_beverage:
                                self.pricing.recalculate_coffee_price(modifier_match.item)
                            else:
                                self.pricing.recalculate_menu_item_price(modifier_match.item)

                        updated_summary = modifier_match.item.get_summary()
                        return StateMachineResult(
                            message=f"{result.message} Your order is now {updated_summary}. Anything else?",
                            order=order,
                        )
                else:
                    # No modifier found - check if it's a default ingredient of a signature/menu item
                    default_match = find_default_ingredient_on_any_item(active_items, parsed.cancel_item)
                    if default_match:
                        # Found a default ingredient - add to removed_ingredients list
                        result = remove_default_ingredient_from_item(default_match.item, default_match)
                        if result.success:
                            # Note: No price recalculation needed - removing default doesn't change price
                            updated_summary = default_match.item.get_summary()
                            return StateMachineResult(
                                message=f"{result.message} Your order is now {updated_summary}. Anything else?",
                                order=order,
                            )

        # Handle item cancellation: "cancel the coke", "remove the bagel", etc.
        if parsed.cancel_item:
            cancel_item_desc = parsed.cancel_item.lower()
            active_items = order.items.get_active_items()

            # Handle special "__last_item__" value for "cancel that", "remove it", etc.
            if parsed.cancel_item == "__last_item__" and active_items:
                last_item = active_items[-1]
                removed_name = last_item.get_summary()
                idx = order.items.items.index(last_item)
                order.items.remove_item(idx)
                logger.info("Cancellation: removed last item from cart: %s", removed_name)

                remaining_items = order.items.get_active_items()
                if remaining_items:
                    return StateMachineResult(
                        message=f"OK, I've removed the {removed_name}. Anything else?",
                        order=order,
                    )
                else:
                    return StateMachineResult(
                        message=f"OK, I've removed the {removed_name}. What would you like to order?",
                        order=order,
                    )

            # Handle special "__all_items__" value for "remove all", "cancel everything", etc.
            if parsed.cancel_item == "__all_items__":
                if active_items:
                    num_items = len(active_items)
                    # Remove all items by marking them as cancelled
                    for item in active_items:
                        idx = order.items.items.index(item)
                        order.items.remove_item(idx)
                    logger.info("Cancellation: removed ALL %d items from cart", num_items)
                    return StateMachineResult(
                        message="OK, I've cleared your order. What would you like to order?",
                        order=order,
                    )
                else:
                    return StateMachineResult(
                        message="Your order is already empty. What would you like to order?",
                        order=order,
                    )

            # Handle special "__reduce_to_one__" value for "just one bagel", "only one", etc.
            # This reduces quantity by removing all but the first item of the specified type
            if parsed.cancel_item and parsed.cancel_item.startswith("__reduce_to_one"):
                if active_items:
                    # Extract item type from cancel_item (e.g., "__reduce_to_one_bagel__" -> "bagel")
                    item_type = None
                    if parsed.cancel_item != "__reduce_to_one__":
                        # Extract the type between "__reduce_to_one_" and "__"
                        parts = parsed.cancel_item.replace("__", "").replace("reduce_to_one_", "")
                        if parts:
                            item_type = parts.strip()

                    # Find items to remove (keep first, remove rest)
                    items_to_check = active_items
                    if item_type:
                        # Filter by item type (use module-level imports)
                        if item_type == "bagel":
                            items_to_check = [i for i in active_items if isinstance(i, BagelItemTask)]
                        elif item_type in ("coffee", "drink"):
                            items_to_check = [
                                i for i in active_items
                                if getattr(i, 'is_sized_beverage', False)
                            ]
                        elif item_type == "sandwich":
                            items_to_check = [i for i in active_items if isinstance(i, MenuItemTask)]

                    if len(items_to_check) > 1:
                        # Keep the first item, remove the rest
                        items_to_remove = items_to_check[1:]
                        removed_count = 0
                        removed_names = []
                        for item in items_to_remove:
                            removed_name = item.get_summary()
                            idx = order.items.items.index(item)
                            order.items.remove_item(idx)
                            removed_count += 1
                            removed_names.append(removed_name)

                        kept_item = items_to_check[0].get_summary()
                        logger.info(
                            "Reduce to one: kept '%s', removed %d items: %s",
                            kept_item, removed_count, removed_names
                        )

                        if removed_count == 1:
                            return StateMachineResult(
                                message=f"OK, I've removed the extra {item_type or 'item'}. You have {kept_item}. Anything else?",
                                order=order,
                            )
                        else:
                            return StateMachineResult(
                                message=f"OK, I've removed {removed_count} items. You have {kept_item}. Anything else?",
                                order=order,
                            )
                    elif len(items_to_check) == 1:
                        # Already just one item
                        kept_item = items_to_check[0].get_summary()
                        return StateMachineResult(
                            message=f"You already have just one {item_type or 'item'}: {kept_item}. Anything else?",
                            order=order,
                        )
                    else:
                        # No items of that type
                        return StateMachineResult(
                            message=f"I don't see any {item_type or 'items'} in your order. What would you like?",
                            order=order,
                        )
                else:
                    return StateMachineResult(
                        message="Your order is empty. What would you like to order?",
                        order=order,
                    )

            if active_items:
                # First, check for ordinal reference (e.g., "second bagel", "3rd coffee")
                ordinal_index, item_type_keyword = extract_ordinal_reference(cancel_item_desc)

                if ordinal_index is not None and item_type_keyword:
                    # User wants to remove a specific Nth item
                    result = find_nth_item_of_type(active_items, item_type_keyword, ordinal_index)
                    if result:
                        item_to_remove, _ = result
                        removed_name = item_to_remove.get_summary()
                        idx = order.items.items.index(item_to_remove)
                        order.items.remove_item(idx)

                        logger.info(
                            "Cancellation: removed %s #%d from cart: %s",
                            item_type_keyword, ordinal_index, removed_name
                        )

                        remaining_items = order.items.get_active_items()
                        if remaining_items:
                            return StateMachineResult(
                                message=f"OK, I've removed the {removed_name}. Anything else?",
                                order=order,
                            )
                        else:
                            return StateMachineResult(
                                message=f"OK, I've removed the {removed_name}. What would you like to order?",
                                order=order,
                            )
                    else:
                        # Ordinal item not found
                        logger.info(
                            "Cancellation: couldn't find %s #%d in cart",
                            item_type_keyword, ordinal_index
                        )
                        # Build appropriate error message
                        if item_type_keyword.lower() in ("item", "items", "one", "thing"):
                            not_found_msg = f"I couldn't find item #{ordinal_index} in your order."
                        else:
                            not_found_msg = f"I couldn't find a {item_type_keyword} #{ordinal_index} in your order."
                        return StateMachineResult(
                            message=f"{not_found_msg} What would you like to do?",
                            order=order,
                        )

                # Check if plural removal (e.g., "coffees", "bagels")
                is_plural = cancel_item_desc.endswith('s') and len(cancel_item_desc) > 2
                singular_desc = cancel_item_desc[:-1] if is_plural else cancel_item_desc

                # Resolve aliases to canonical names (e.g., "coke" -> "Coca-Cola")
                # Try all alias resolution functions in order
                canonical_name = singular_desc
                for resolve_fn in [resolve_soda_alias, resolve_coffee_alias, resolve_side_alias, resolve_menu_item_alias]:
                    resolved = resolve_fn(singular_desc)
                    if resolved and resolved != singular_desc:
                        canonical_name = resolved
                        break
                canonical_name_lower = canonical_name.lower() if canonical_name != singular_desc else None

                # Find matching items (fallback for non-ordinal cancellations)
                items_to_remove = []
                for item in reversed(active_items):  # Search from most recent
                    item_summary = item.get_summary().lower()
                    item_name = getattr(item, 'menu_item_name', '') or ''
                    item_name_lower = item_name.lower()
                    item_type = getattr(item, 'item_type', '') or ''

                    # Check for matches - be careful with empty strings
                    matches = False
                    if cancel_item_desc in item_summary:
                        matches = True
                    elif singular_desc in item_summary:
                        matches = True
                    elif item_name_lower and cancel_item_desc in item_name_lower:
                        matches = True
                    elif item_name_lower and singular_desc in item_name_lower:
                        matches = True
                    elif item_name_lower and item_name_lower in cancel_item_desc:
                        matches = True
                    # Check item_type for "coffees" -> item_type="coffee"
                    elif item_type and (cancel_item_desc == item_type or singular_desc == item_type):
                        matches = True
                    elif any(word in item_summary for word in cancel_item_desc.split() if word):
                        matches = True
                    # Check canonical name from alias resolution (e.g., "coke" -> "Coca-Cola")
                    elif canonical_name_lower and canonical_name_lower == item_name_lower:
                        matches = True

                    if matches:
                        items_to_remove.append(item)
                        # If not plural, only remove one item
                        if not is_plural:
                            break

                if items_to_remove:
                    # Remove all matching items
                    removed_names = []
                    for item in items_to_remove:
                        removed_names.append(item.get_summary())
                        idx = order.items.items.index(item)
                        order.items.remove_item(idx)

                    # Build response message
                    if len(removed_names) == 1:
                        removed_str = f"the {removed_names[0]}"
                    else:
                        removed_str = f"the {len(removed_names)} {singular_desc}s"

                    logger.info("Cancellation: removed %d item(s) from cart: %s", len(removed_names), removed_names)

                    remaining_items = order.items.get_active_items()
                    if remaining_items:
                        return StateMachineResult(
                            message=f"OK, I've removed {removed_str}. Anything else?",
                            order=order,
                        )
                    else:
                        return StateMachineResult(
                            message=f"OK, I've removed {removed_str}. What would you like to order?",
                            order=order,
                        )
                else:
                    # Item not found - let them know
                    logger.info("Cancellation: couldn't find item matching '%s'", cancel_item_desc)
                    return StateMachineResult(
                        message=f"I couldn't find {parsed.cancel_item} in your order. What would you like to do?",
                        order=order,
                    )
            else:
                # No items to cancel
                logger.info("Cancellation requested but no items in cart")
                return StateMachineResult(
                    message="There's nothing in your order yet. What can I get for you?",
                    order=order,
                )

        # Handle "another bagel" / "one more coffee" - treat as new item of that type
        if parsed.duplicate_new_item_type:
            item_type = parsed.duplicate_new_item_type
            logger.info("Adding new %s (from 'another %s' pattern)", item_type, item_type)
            if item_type == "bagel":
                # Add a new bagel and start config flow
                return self.item_adder_handler.add_bagel(order, quantity=1)
            elif item_type == "espresso":
                # Espresso uses MenuItemTask (data-driven flow), not CoffeeItemTask
                if self.item_adder_handler and self.item_adder_handler.menu_item_handler:
                    menu_lookup = self.item_adder_handler.menu_lookup
                    espresso_items = menu_lookup.lookup_menu_items("espresso") if menu_lookup else []
                    espresso_menu_item = None
                    for mi in espresso_items:
                        if mi.get("name", "").lower() == "espresso":
                            espresso_menu_item = mi
                            break

                    base_price = espresso_menu_item.get("base_price", 3.50) if espresso_menu_item else 3.50
                    menu_item_id = espresso_menu_item.get("id") if espresso_menu_item else None

                    # Create basic espresso - let MenuItemConfigHandler ask about shots, milk, etc.
                    espresso_task = MenuItemTask(
                        menu_item_name="Espresso",
                        menu_item_id=menu_item_id,
                        unit_price=base_price,
                        menu_item_type="espresso",
                    )
                    espresso_task.mark_in_progress()
                    order.items.add_item(espresso_task)

                    logger.info("Created new espresso (from 'another espresso' pattern)")

                    # Route through MenuItemConfigHandler for all questions
                    menu_handler = self.item_adder_handler.menu_item_handler
                    return menu_handler.get_first_question(espresso_task, order)
                else:
                    # Fallback if handler not available
                    return StateMachineResult(
                        message="Got it, espresso. How many shots?",
                        order=order,
                    )
            elif item_type == "coffee":
                # Add a new coffee and start config flow
                return self.coffee_handler.add_coffee(order)
            elif item_type == "sandwich":
                # Treat sandwich as bagel with potential proteins
                return self.item_adder_handler.add_bagel(order, quantity=1)
            else:
                # Generic drink or unknown type - ask what they'd like
                return StateMachineResult(
                    message=f"Sure, what kind of {item_type} would you like?",
                    order=order,
                )

        # Handle "make it 2" / "another one" / "one more" - add more of existing item(s)
        if parsed.duplicate_last_item > 0:
            active_items = order.items.get_active_items()
            if not active_items:
                logger.info("'Make it N' / 'another one' requested but no items in cart")
                return StateMachineResult(
                    message="There's nothing in your order yet. What can I get for you?",
                    order=order,
                )

            added_count = parsed.duplicate_last_item

            # Single item in cart - duplicate silently
            if len(active_items) == 1:
                last_item = active_items[-1]
                last_item_name = last_item.get_summary()

                # Add copies of the last item
                for _ in range(added_count):
                    new_item = last_item.model_copy(deep=True)
                    new_item.id = str(uuid.uuid4())
                    new_item.mark_complete()
                    order.items.add_item(new_item)

                if added_count == 1:
                    logger.info("Added 1 more of '%s' to order", last_item_name)
                    return StateMachineResult(
                        message=f"I've added a second {last_item_name}. Anything else?",
                        order=order,
                    )
                else:
                    logger.info("Added %d more of '%s' to order", added_count, last_item_name)
                    return StateMachineResult(
                        message=f"I've added {added_count} more {last_item_name}. Anything else?",
                        order=order,
                    )

            # Multiple items in cart - ask which one to duplicate
            else:
                # Build the clarifying question: "Another [last], another [second-to-last], ... or all items?"
                item_options = []
                for item in reversed(active_items):
                    item_options.append({
                        "id": item.id,
                        "summary": item.get_summary(),
                        "quantity": item.quantity,
                    })

                # Store pending state
                order.pending_duplicate_selection = {
                    "count": added_count,
                    "items": item_options,
                }
                order.pending_field = "duplicate_selection"

                # Build the question text
                question_parts = [f"another {opt['summary']}" for opt in item_options]
                question = ", ".join(question_parts) + ", or all the items in your order?"
                # Capitalize first letter
                question = question[0].upper() + question[1:]

                logger.info("Asking for duplicate clarification with %d items", len(active_items))
                return StateMachineResult(
                    message=question,
                    order=order,
                )

        # Handle "all items" duplicate request
        if parsed.wants_duplicate_all:
            active_items = order.items.get_active_items()
            if not active_items:
                return StateMachineResult(
                    message="There's nothing in your order yet. What can I get for you?",
                    order=order,
                )
            return self._duplicate_all_items(order, active_items)

        # Handle repeat order / "same thing" request
        if parsed.wants_repeat_order:
            active_items = order.items.get_active_items()
            has_cart_items = len(active_items) > 0
            has_previous_order = (
                self._returning_customer
                and self._returning_customer.get("last_order_items")
            )

            # Case 1: Both previous order AND items in cart - ask for clarification
            if has_previous_order and has_cart_items:
                # Build item options for cart
                item_options = []
                for item in reversed(active_items):
                    item_options.append({
                        "id": item.id,
                        "summary": item.get_summary(),
                        "quantity": item.quantity,
                    })

                order.pending_same_thing_clarification = {
                    "has_previous_order": True,
                    "cart_items": item_options,
                }
                order.pending_field = "same_thing_clarification"

                # Build the question
                if len(active_items) == 1:
                    cart_option = f"another {active_items[0].get_summary()}"
                else:
                    cart_option = "duplicate something from your current order"

                logger.info("'Same thing' ambiguous: has previous order AND %d cart items", len(active_items))
                return StateMachineResult(
                    message=f"Would you like to repeat your previous order, or {cart_option}?",
                    order=order,
                )

            # Case 2: Only previous order (no cart items) - repeat previous order
            if has_previous_order:
                return self.checkout_handler.handle_repeat_order(
                    order,
                    returning_customer=self._returning_customer,
                    set_repeat_info_callback=self._set_repeat_info_callback,
                )

            # Case 3: Only cart items (no previous order) - treat as duplicate
            if has_cart_items:
                # Reuse duplicate logic: single item = duplicate it, multiple = ask which one
                if len(active_items) == 1:
                    last_item = active_items[-1]
                    last_item_name = last_item.get_summary()
                    new_item = last_item.model_copy(deep=True)
                    new_item.id = str(uuid.uuid4())
                    new_item.mark_complete()
                    order.items.add_item(new_item)
                    logger.info("'Same thing' with single cart item: duplicated '%s'", last_item_name)
                    return StateMachineResult(
                        message=f"I've added another {last_item_name}. Anything else?",
                        order=order,
                    )
                else:
                    # Multiple items - ask which one to duplicate
                    item_options = []
                    for item in reversed(active_items):
                        item_options.append({
                            "id": item.id,
                            "summary": item.get_summary(),
                            "quantity": item.quantity,
                        })
                    order.pending_duplicate_selection = {
                        "count": 1,
                        "items": item_options,
                    }
                    order.pending_field = "duplicate_selection"
                    question_parts = [f"another {opt['summary']}" for opt in item_options]
                    question = ", ".join(question_parts) + ", or all the items in your order?"
                    question = question[0].upper() + question[1:]
                    logger.info("'Same thing' with %d cart items: asking which to duplicate", len(active_items))
                    return StateMachineResult(
                        message=question,
                        order=order,
                    )

            # Case 4: Neither previous order nor cart items
            logger.info("'Same thing' requested but no previous order and no cart items")
            return StateMachineResult(
                message="I don't have a previous order on file for you. What can I get for you today?",
                order=order,
            )

        # Check if user specified order type upfront (e.g., "I'd like to place a pickup order")
        if parsed.order_type:
            order.delivery_method.order_type = parsed.order_type
            logger.info("Order type set from upfront mention: %s", parsed.order_type)
            order_type_display = "pickup" if parsed.order_type == "pickup" else "delivery"
            # Check if they also ordered items in the same message
            has_items = parsed.parsed_items or parsed.by_pound_items
            if not has_items:
                # Just the order type, no items yet - acknowledge and ask what they want
                return StateMachineResult(
                    message=f"Great, I'll set this up for {order_type_display}. What can I get for you?",
                    order=order,
                )
            # If they also ordered items, continue processing below

        # NEW: Handle multi-item orders via parsed_items list (preferred path)
        # This provides generic handling for any combination of item types
        if parsed.parsed_items:
            result = self._process_multi_item_order(parsed, order)
            if result:
                return result

        if parsed.needs_soda_clarification:
            return self.menu_inquiry_handler.handle_soda_clarification(order)

        # Handle price inquiries for specific items
        if parsed.asks_about_price and parsed.price_query_item:
            return self.menu_inquiry_handler.handle_price_inquiry(parsed.price_query_item, order)

        # Handle store info inquiries
        if parsed.asks_store_hours:
            return self.store_info_handler.handle_store_hours_inquiry(order)

        if parsed.asks_store_location:
            return self.store_info_handler.handle_store_location_inquiry(order)

        if parsed.asks_delivery_zone:
            return self.store_info_handler.handle_delivery_zone_inquiry(parsed.delivery_zone_query, order)

        if parsed.wants_customer_service:
            return self.store_info_handler.handle_customer_service_inquiry(order)

        if parsed.asks_recommendation:
            return self.store_info_handler.handle_recommendation_inquiry(parsed.recommendation_category, order)

        if parsed.asks_item_description:
            return self.menu_inquiry_handler.handle_item_description_inquiry(parsed.item_description_query, order)

        if parsed.asks_modifier_options:
            return self.store_info_handler.handle_modifier_inquiry(
                parsed.modifier_query_item, parsed.modifier_query_category, order
            )

        if parsed.menu_query:
            return self.menu_inquiry_handler.handle_menu_query(parsed.menu_query_type, order, show_prices=parsed.asks_about_price)

        if parsed.wants_more_menu_items:
            return self.menu_inquiry_handler.handle_more_menu_items(order, parsed.more_menu_category)

        if parsed.asking_signature_menu:
            return self.menu_inquiry_handler.handle_signature_menu_inquiry(parsed.signature_menu_type, order)

        if parsed.asking_by_pound:
            return self.by_pound_handler.handle_by_pound_inquiry(parsed.by_pound_category, order)

        if parsed.by_pound_items:
            return self.by_pound_handler.add_by_pound_items(parsed.by_pound_items, order)

        if parsed.is_gratitude:
            return StateMachineResult(
                message="You're welcome! Anything else I can get for you?",
                order=order,
            )

        if parsed.is_help_request:
            return StateMachineResult(
                message="I can help you order bagels, coffee, sandwiches, and more from our menu. Just tell me what you'd like! For example, you can say 'plain bagel with cream cheese' or 'large iced latte'.",
                order=order,
            )

        if parsed.unclear or parsed.is_greeting:
            return StateMachineResult(
                message="What can I get for you?",
                order=order,
            )

        return StateMachineResult(
            message="I didn't catch that. What would you like to order?",
            order=order,
        )

    # =========================================================================
    # Multi-Item Order Handling via ParsedItem Types
    # =========================================================================

    def _add_parsed_item(self, item: ParsedItem, order: OrderTask) -> tuple[OrderTask, str]:
        """
        Dispatch a parsed item to the appropriate handler.

        Returns tuple of (updated_order, item_summary_string).
        """
        if isinstance(item, ParsedMenuItemEntry):
            # Track item count before to detect if item was actually added
            items_before = len(order.items.items)
            result = self.item_adder_handler.add_menu_item(
                item.menu_item_name,
                item.quantity,
                order,
                item.toasted,
                item.bagel_type,
                item.modifiers,
            )
            order = result.order
            items_after = len(order.items.items)

            # Check if item was actually added
            if items_after > items_before:
                summary = item.menu_item_name
                if item.quantity > 1:
                    summary = f"{item.quantity} {summary}s"
            else:
                # Item not found - store the error message for the caller
                logger.info("Menu item '%s' not found - storing error result", item.menu_item_name)
                order.last_add_error = result  # Store error for _process_multi_item_order
                summary = ""  # Don't add to summaries

            return order, summary

        elif isinstance(item, ParsedBagelEntry):
            # Build ExtractedModifiers from parsed entry fields
            extracted_mods = ExtractedModifiers()
            extracted_mods.proteins = list(item.proteins) if item.proteins else []
            extracted_mods.cheeses = list(item.cheeses) if item.cheeses else []
            extracted_mods.toppings = list(item.toppings) if item.toppings else []
            extracted_mods.needs_cheese_clarification = item.needs_cheese_clarification
            # Convert special_instructions string to list for ExtractedModifiers
            if item.special_instructions:
                extracted_mods.special_instructions = [item.special_instructions]

            if item.quantity > 1:
                result = self.item_adder_handler.add_bagels(
                    quantity=item.quantity,
                    bagel_type=item.bagel_type,
                    toasted=item.toasted,
                    scooped=item.scooped,
                    spread=item.spread,
                    spread_type=item.spread_type,
                    order=order,
                    extracted_modifiers=extracted_mods if extracted_mods.has_modifiers() or extracted_mods.has_special_instructions() or extracted_mods.needs_cheese_clarification else None,
                )
            else:
                result = self.item_adder_handler.add_bagel(
                    bagel_type=item.bagel_type,
                    order=order,
                    toasted=item.toasted,
                    scooped=item.scooped,
                    spread=item.spread,
                    spread_type=item.spread_type,
                    extracted_modifiers=extracted_mods if extracted_mods.has_modifiers() or extracted_mods.has_special_instructions() or extracted_mods.needs_cheese_clarification else None,
                )
            order = result.order
            # Build summary - handle None bagel_type
            bagel_desc = f"{item.bagel_type} bagel" if item.bagel_type else "bagel"
            summary = bagel_desc
            if item.toasted:
                summary += " toasted"
            if item.quantity > 1:
                summary = f"{item.quantity} {bagel_desc}s"
                if item.toasted:
                    summary += " toasted"
            return order, summary

        elif isinstance(item, ParsedCoffeeEntry):
            # Check if this is a modifier-only input (e.g., "2 vanilla syrups") that should
            # be added to the last beverage instead of creating a new coffee
            drink_type_lower = (item.drink_type or "").lower()
            has_modifiers = bool(item.syrups or item.sweeteners or item.milk or item.wants_syrup)
            is_default_drink_type = drink_type_lower == "coffee"

            # Check if original input contains a real beverage keyword
            original_text_lower = (item.original_text or "").lower()
            beverage_keywords = {
                "coffee", "latte", "cappuccino", "espresso", "americano", "macchiato",
                "mocha", "tea", "chai", "matcha", "cold brew", "drip", "iced coffee",
                "hot coffee", "coke", "soda", "juice", "water", "drink", "beverage",
            }
            has_explicit_drink = any(kw in original_text_lower for kw in beverage_keywords)

            # If this is a modifier-only input (no explicit drink type), add to last beverage
            if has_modifiers and is_default_drink_type and not has_explicit_drink:
                active_items = order.items.get_active_items()
                if active_items:
                    last_item = active_items[-1]

                    # Add to sized_beverage MenuItemTask or CoffeeItemTask
                    if getattr(last_item, 'is_sized_beverage', False):
                        modifier_summary_parts = []

                        # Add syrups
                        for syrup in item.syrups:
                            existing_syrups = [s.get("flavor") for s in last_item.flavor_syrups]
                            if syrup.type not in existing_syrups:
                                last_item.flavor_syrups.append({"flavor": syrup.type, "quantity": syrup.quantity})
                                qty_str = f"{syrup.quantity} " if syrup.quantity > 1 else ""
                                modifier_summary_parts.append(f"{qty_str}{syrup.type} syrup")

                        # Add sweeteners
                        for sweetener in item.sweeteners:
                            existing_sweeteners = [s.get("type") for s in last_item.sweeteners]
                            if sweetener.type not in existing_sweeteners:
                                last_item.sweeteners.append({"type": sweetener.type, "quantity": sweetener.quantity})
                                qty_str = f"{sweetener.quantity} " if sweetener.quantity > 1 else ""
                                modifier_summary_parts.append(f"{qty_str}{sweetener.type}")

                        # Add milk
                        if item.milk and last_item.milk != item.milk:
                            last_item.milk = item.milk
                            modifier_summary_parts.append(f"{item.milk} milk")

                        if modifier_summary_parts:
                            logger.info("Added modifiers to existing coffee: %s", modifier_summary_parts)
                            summary = ", ".join(modifier_summary_parts) + " added"
                            return order, summary

                    # Add to MenuItemTask espresso (data-driven flow)
                    elif isinstance(last_item, MenuItemTask) and last_item.menu_item_type == "espresso":
                        modifier_summary_parts = []

                        # Get existing selections or initialize empty list
                        existing_selections = last_item.attribute_values.get("milk_sweetener_syrup_selections", [])
                        existing_slugs_list = last_item.attribute_values.get("milk_sweetener_syrup", [])
                        existing_slugs = set(existing_slugs_list)

                        # Add syrups
                        for syrup in item.syrups:
                            syrup_slug = syrup.type.lower().replace(" ", "_")
                            if syrup_slug not in existing_slugs:
                                existing_slugs.add(syrup_slug)
                                existing_selections.append({
                                    "slug": syrup_slug,
                                    "display_name": syrup.type.title(),
                                    "price": 0.65,  # Default syrup price
                                    "quantity": syrup.quantity,
                                })
                                qty_str = f"{syrup.quantity} " if syrup.quantity > 1 else ""
                                modifier_summary_parts.append(f"{qty_str}{syrup.type} syrup")

                        # Add sweeteners
                        for sweetener in item.sweeteners:
                            sweetener_slug = sweetener.type.lower().replace(" ", "_")
                            if sweetener_slug not in existing_slugs:
                                existing_slugs.add(sweetener_slug)
                                existing_selections.append({
                                    "slug": sweetener_slug,
                                    "display_name": sweetener.type.title(),
                                    "price": 0.0,  # Sweeteners are free
                                    "quantity": sweetener.quantity,
                                })
                                qty_str = f"{sweetener.quantity} " if sweetener.quantity > 1 else ""
                                modifier_summary_parts.append(f"{qty_str}{sweetener.type}")

                        # Add milk
                        if item.milk:
                            milk_slug = item.milk.lower().replace(" ", "_")
                            if milk_slug not in existing_slugs:
                                existing_slugs.add(milk_slug)
                                existing_selections.append({
                                    "slug": milk_slug,
                                    "display_name": item.milk.title(),
                                    "price": 0.0,  # Most milks are free, some have upcharge
                                    "quantity": 1,
                                })
                                modifier_summary_parts.append(f"{item.milk} milk")

                        if modifier_summary_parts:
                            # Update attribute_values
                            last_item.attribute_values["milk_sweetener_syrup"] = list(existing_slugs)
                            last_item.attribute_values["milk_sweetener_syrup_selections"] = existing_selections
                            logger.info("Added modifiers to existing espresso (MenuItemTask): %s", modifier_summary_parts)
                            summary = ", ".join(modifier_summary_parts) + " added"
                            return order, summary

            # Check if this is an espresso drink - route to data-driven flow via MenuItemConfigHandler
            is_espresso = drink_type_lower == "espresso"

            if is_espresso and self.item_adder_handler and self.item_adder_handler.menu_item_handler:
                # Look up Espresso from menu
                menu_lookup = self.item_adder_handler.menu_lookup
                espresso_items = menu_lookup.lookup_menu_items("espresso") if menu_lookup else []
                espresso_menu_item = None
                for mi in espresso_items:
                    if mi.get("name", "").lower() == "espresso":
                        espresso_menu_item = mi
                        break

                base_price = espresso_menu_item.get("base_price", 3.50) if espresso_menu_item else 3.50
                menu_item_id = espresso_menu_item.get("id") if espresso_menu_item else None

                # Calculate shots: 1 + extra_shots (0=single, 1=double, 2=triple)
                shots = 1 + item.extra_shots
                shots = max(1, min(4, shots))  # Clamp to 1-4

                # Map shots to attribute slug (must match global_attribute_options)
                shots_slug_map = {
                    1: "single",
                    2: "double",
                    3: "triple",
                    4: "quad",
                }
                shots_slug = shots_slug_map.get(shots, "single")

                # Get shots price from global_attribute_options (data-driven)
                shots_upcharge = 0.0
                shots_display_name = shots_slug.title()  # "Double", "Triple", etc.
                shots_options = menu_cache.get_global_attribute_options("shots")
                for opt in shots_options:
                    if opt.get("slug") == shots_slug:
                        shots_upcharge = opt.get("price_modifier", 0.0) or 0.0
                        shots_display_name = opt.get("display_name", shots_slug.title())
                        break

                # Convert parsed modifiers to milk_sweetener_syrup format for MenuItemTask
                mss_slugs: list[str] = []
                mss_selections: list[dict] = []
                modifiers_upcharge = 0.0

                # Add milk if specified
                if item.milk:
                    milk_slug = item.milk.lower().replace(" ", "_")
                    mss_slugs.append(milk_slug)
                    # Look up price from menu_item_handler if available
                    milk_price = 0.0
                    if pricing:
                        milk_price = pricing.lookup_coffee_modifier_price(milk_slug, "milk") or 0.0
                    mss_selections.append({
                        "slug": milk_slug,
                        "display_name": item.milk.title(),
                        "price": milk_price,
                        "quantity": 1,
                    })
                    modifiers_upcharge += milk_price

                # Add sweeteners
                for sweetener in item.sweeteners:
                    sweetener_slug = sweetener.type.lower().replace(" ", "_")
                    mss_slugs.append(sweetener_slug)
                    mss_selections.append({
                        "slug": sweetener_slug,
                        "display_name": sweetener.type.title(),
                        "price": 0.0,  # Sweeteners are typically free
                        "quantity": sweetener.quantity,
                    })

                # Add syrups
                for syrup in item.syrups:
                    syrup_slug = syrup.type.lower().replace(" ", "_")
                    mss_slugs.append(syrup_slug)
                    syrup_price = 0.0
                    if pricing:
                        syrup_price = pricing.lookup_coffee_modifier_price(syrup_slug, "syrup") or 0.65
                    mss_selections.append({
                        "slug": syrup_slug,
                        "display_name": syrup.type.title(),
                        "price": syrup_price,
                        "quantity": syrup.quantity,
                    })
                    modifiers_upcharge += syrup_price * syrup.quantity

                # Create MenuItemTask(s) for espresso
                # Only include shots_upcharge if user explicitly specified shots
                user_specified_shots = item.extra_shots > 0
                effective_shots_upcharge = shots_upcharge if user_specified_shots else 0.0
                unit_price = base_price + effective_shots_upcharge + modifiers_upcharge
                first_item = None

                for _ in range(item.quantity):
                    espresso_task = MenuItemTask(
                        menu_item_name="Espresso",
                        menu_item_id=menu_item_id,
                        unit_price=unit_price,
                        menu_item_type="espresso",
                    )
                    # Only pre-populate shots if user explicitly specified (double/triple/quad)
                    # Otherwise, let MenuItemConfigHandler ask if ask_in_conversation=True
                    if user_specified_shots:
                        espresso_task.attribute_values["shots"] = shots_slug
                        # Store shots with _selections format for display as modifier line item
                        espresso_task.attribute_values["shots_selections"] = [{
                            "slug": shots_slug,
                            "display_name": shots_display_name,
                            "price": shots_upcharge,
                        }]
                    if item.decaf:
                        espresso_task.attribute_values["decaf"] = True
                    if mss_slugs:
                        espresso_task.attribute_values["milk_sweetener_syrup"] = mss_slugs
                        espresso_task.attribute_values["milk_sweetener_syrup_selections"] = mss_selections.copy()
                    if item.special_instructions:
                        espresso_task.special_instructions = item.special_instructions

                    espresso_task.mark_in_progress()
                    order.items.add_item(espresso_task)
                    if first_item is None:
                        first_item = espresso_task

                logger.info(
                    "ESPRESSO CREATED (MenuItemTask): shots=%d (%s), quantity=%d, decaf=%s, unit_price=%.2f, modifiers=%s",
                    shots, shots_slug, item.quantity, item.decaf, unit_price, mss_slugs
                )

                # Build summary based on shots
                if shots == 2:
                    summary = "double espresso"
                elif shots >= 3:
                    summary = "triple espresso"
                else:
                    summary = "espresso"
                if item.decaf:
                    summary = f"decaf {summary}"
                if item.quantity > 1:
                    summary = f"{item.quantity} {summary}s"

                # Route through MenuItemConfigHandler for any remaining questions
                menu_handler = self.item_adder_handler.menu_item_handler
                result = menu_handler.get_first_question(first_item, order)
                # Replace return to return summary with the result
                return result.order, summary

            # Regular coffee/drink - use coffee handler
            # Extract first sweetener if present
            sweetener = item.sweeteners[0].type if item.sweeteners else None
            sweetener_qty = item.sweeteners[0].quantity if item.sweeteners else 1

            # Extract first syrup if present
            flavor_syrup = item.syrups[0].type if item.syrups else None
            syrup_qty = item.syrups[0].quantity if item.syrups else 1

            result = self.coffee_handler.add_coffee(
                item.drink_type,
                item.size,
                item.temperature == "iced" if item.temperature else None,
                item.milk,
                sweetener,
                sweetener_qty,
                flavor_syrup,
                item.quantity,
                order,
                special_instructions=item.special_instructions,
                decaf=item.decaf,
                syrup_quantity=syrup_qty,
                wants_syrup=item.wants_syrup,
                cream_level=item.cream_level,
                extra_shots=item.extra_shots,
                original_input=item.original_text,
            )
            order = result.order
            summary = item.drink_type
            if item.size:
                summary = f"{item.size} {summary}"
            if item.temperature:
                summary = f"{item.temperature} {summary}"
            if item.quantity > 1:
                summary = f"{item.quantity} {summary}s"
            return order, summary

        elif isinstance(item, ParsedSideItemEntry):
            side_name, error = self.item_adder_handler.add_side_item(
                item.side_name,
                item.quantity,
                order,
            )
            if side_name:
                summary = side_name
                if item.quantity > 1:
                    summary = f"{item.quantity} {summary}s"
                return order, summary
            else:
                logger.warning("Failed to add side item '%s': %s", item.side_name, error)
                return order, ""

        return order, ""

    def _process_multi_item_order(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """
        Process all items in a multi-item order using parsed_items list.

        Flow:
        1. Add all items to the order
        2. Find all items needing configuration (toasted questions, etc.)
        3. Queue items 2+ for later config, each with their display name
        4. Ask first config question: "Got it! Would you like the [Item1] toasted?"
        5. Follow-up questions use abbreviated form: "And the [Item2]?"
        6. Final summary after all configured: "Great, [summary]. Anything else?"

        Returns StateMachineResult if items were processed, None if parsed_items is empty.
        """
        if not parsed.parsed_items:
            return None

        logger.info("Processing %d items via parsed_items list", len(parsed.parsed_items))

        # Track added items with their IDs and names for config queueing
        added_items: list[tuple[str, str, str]] = []  # (item_id, item_name, item_type)
        summaries = []

        # Clear any previous error
        order.last_add_error = None

        for parsed_item in parsed.parsed_items:
            order, summary = self._add_parsed_item(parsed_item, order)

            # Check if add failed (e.g., item not found on menu)
            if order.last_add_error is not None:
                # Return the error message instead of continuing
                error_result = order.last_add_error
                order.last_add_error = None  # Clear it
                return error_result

            if summary:
                summaries.append(summary)
                # Find the item that was just added (last item with matching type)
                last_item = order.items.items[-1] if order.items.items else None
                if last_item:
                    # Determine item type for config handler
                    # Note: ParsedSignatureItemEntry is an alias for ParsedMenuItemEntry with is_signature=True
                    if isinstance(parsed_item, ParsedMenuItemEntry):
                        if parsed_item.is_signature:
                            item_type = "signature_item"
                        else:
                            item_type = "menu_item"
                        display_name = parsed_item.menu_item_name
                    elif isinstance(parsed_item, ParsedBagelEntry):
                        item_type = "bagel"
                        display_name = f"{parsed_item.bagel_type} bagel" if parsed_item.bagel_type else "bagel"
                    elif isinstance(parsed_item, ParsedCoffeeEntry):
                        item_type = "coffee"
                        display_name = parsed_item.drink_type
                    else:
                        item_type = "side"
                        display_name = summary
                    added_items.append((last_item.id, display_name, item_type))
                logger.info("Added item via parsed_items: %s (id=%s)", summary, last_item.id[:8] if last_item else "?")

        # Check if we're waiting for drink type selection (user said "drink" or partial term like "juice")
        # This must be checked BEFORE checking summaries because add_coffee sets pending_field
        # but _add_parsed_item still adds the generic term to summaries
        if order.pending_field == "drink_type" and self.coffee_handler.menu_lookup:
            logger.info("Pending drink type selection - presenting drink options")

            # Check if we have filtered options (partial term like "juice") or need full menu
            if order.pending_drink_options:
                # Use pre-filtered options from add_coffee
                all_drinks = order.pending_drink_options
                logger.info("Using %d pre-filtered drink options", len(all_drinks))
            else:
                # Get full drink menu for generic "drink" request
                items_by_type = self.coffee_handler.menu_lookup.menu_data.get("items_by_type", {})
                sized_items = items_by_type.get("sized_beverage", [])
                cold_items = items_by_type.get("beverage", [])
                all_drinks = sized_items + cold_items

            if all_drinks:
                # Show first batch of drinks with pagination
                batch = all_drinks[:DEFAULT_PAGINATION_SIZE]
                remaining = len(all_drinks) - DEFAULT_PAGINATION_SIZE

                drink_names = [item.get("name", "Unknown") for item in batch]

                # Check if this is for an unknown drink request (user asked for something we don't have)
                unknown_prefix = ""
                if order.unknown_drink_request:
                    unknown_prefix = f"Sorry, we don't have {order.unknown_drink_request}. "
                    order.unknown_drink_request = None  # Clear after using

                if remaining > 0:
                    # Format with "and more"
                    if len(drink_names) == 1:
                        drinks_str = drink_names[0]
                    else:
                        drinks_str = ", ".join(drink_names[:-1]) + f", {drink_names[-1]}"
                    message = f"{unknown_prefix}We have {drinks_str}, and more. What type of drink would you like?"
                    # Set pagination for "what else" follow-up
                    order.set_menu_pagination("drink", DEFAULT_PAGINATION_SIZE, len(all_drinks))
                else:
                    # All drinks fit in one batch
                    if len(drink_names) == 1:
                        drinks_str = drink_names[0]
                    elif len(drink_names) == 2:
                        drinks_str = f"{drink_names[0]} or {drink_names[1]}"
                    else:
                        drinks_str = ", ".join(drink_names[:-1]) + f", or {drink_names[-1]}"
                    message = f"{unknown_prefix}We have {drinks_str}. Which would you like?"

                order.phase = OrderPhase.CONFIGURING_ITEM.value
                return StateMachineResult(message=message, order=order)

        # Check if we're waiting for drink selection (e.g., "latte" matches Latte and Matcha Latte)
        # This handles disambiguation when a drink type matches multiple menu items
        if order.pending_field == "drink_selection" and order.pending_drink_options:
            logger.info("Pending drink selection - presenting %d options", len(order.pending_drink_options))

            # Build the clarification message from pending options
            # Format: numbered list showing each option
            option_list = []
            for i, item in enumerate(order.pending_drink_options, 1):
                name = item.get("name", "Unknown")
                price = item.get("base_price", 0)
                if price > 0:
                    option_list.append(f"{i}. {name} (${price:.2f})")
                else:
                    option_list.append(f"{i}. {name}")

            options_str = "\n".join(option_list)

            # Get the drink term from summaries (e.g., "latte" from "large iced latte")
            # The first summary that looks like a drink is the one being disambiguated
            drink_term = "that drink"
            for summary in summaries:
                if summary:
                    # Extract just the drink type (last word typically)
                    drink_term = summary.split()[-1] if summary else "that drink"
                    break

            # If there are other items (like bagels) that were added, acknowledge them
            other_summaries = [s for s in summaries if s and drink_term.lower() not in s.lower()]
            if other_summaries:
                if len(other_summaries) == 1:
                    prefix = f"Got it, {other_summaries[0]}! For the {drink_term}, "
                else:
                    items_str = ", ".join(other_summaries[:-1]) + f" and {other_summaries[-1]}"
                    prefix = f"Got it, {items_str}! For the {drink_term}, "
            else:
                prefix = ""

            message = f"{prefix}We have a few options:\n{options_str}\nWhich would you like?"
            order.phase = OrderPhase.CONFIGURING_ITEM.value
            return StateMachineResult(message=message, order=order)

        if not summaries:
            return None

        # Find all items that need configuration (toasted question, bagel type, etc.)
        # Group by handler type since handlers like configure_next_incomplete_bagel and
        # configure_next_incomplete_coffee have internal loops that find ALL items of their type.
        # We only need to queue ONE item per handler group - the handler will find the rest.
        #
        # Handler groups:
        # - "bagel_handler": BagelItemTask, MenuItemTask with bagel config (sandwiches, omelette sides)
        # - "coffee_handler": MenuItemTask with is_sized_beverage (coffee, latte, etc.)
        # - Individual items: MenuItemTask needing side_choice (no internal loop)

        bagel_handler_items: list[tuple[str, str, str, str]] = []  # (item_id, name, type, field)
        coffee_handler_items: list[tuple[str, str, str, str]] = []
        individual_items: list[tuple[str, str, str, str]] = []  # Items that don't share a handler loop

        for item in order.items.items:
            if item.status == TaskStatus.IN_PROGRESS:
                if isinstance(item, MenuItemTask):
                    # Omelettes need side choice first (bagel or fruit salad)
                    # These don't share a handler loop - each must be queued individually
                    if item.requires_side_choice and item.side_choice is None:
                        individual_items.append((item.id, item.menu_item_name, "menu_item", "side_choice"))
                    # If omelette chose bagel, need bagel questions (handled by bagel config handler)
                    elif item.side_choice == "bagel":
                        if not item.bagel_choice:
                            bagel_handler_items.append((item.id, item.menu_item_name, "menu_item", "bagel_choice"))
                        elif item.toasted is None:
                            bagel_handler_items.append((item.id, item.menu_item_name, "menu_item", "toasted"))
                        elif item.spread is None:
                            bagel_handler_items.append((item.id, item.menu_item_name, "menu_item", "spread"))
                    # Check if this menu item contains a bagel (e.g., Classic BEC)
                    elif not item.requires_side_choice:
                        # DB-driven items use MenuItemConfigHandler or CoffeeConfigHandler
                        # They should NOT go through the bagel handler's hardcoded toasted question
                        if item.menu_item_type in ("deli_sandwich", "egg_sandwich", "fish_sandwich", "spread_sandwich", "espresso"):
                            individual_items.append((item.id, item.menu_item_name, "menu_item", "menu_item_config"))
                        elif item.is_sized_beverage:
                            # Sized beverages (coffee, latte, etc.) use coffee config handler
                            if item.size is None:
                                coffee_handler_items.append((item.id, item.menu_item_name or "coffee", "coffee", "coffee_size"))
                            elif item.iced is None:
                                coffee_handler_items.append((item.id, item.menu_item_name or "coffee", "coffee", "coffee_style"))
                            elif item.milk is None and not item.sweeteners and not item.flavor_syrups:
                                coffee_handler_items.append((item.id, item.menu_item_name or "coffee", "coffee", "coffee_modifiers"))
                        else:
                            bagel_item_info = self._get_bagel_menu_item_info(item.menu_item_name)
                            if bagel_item_info:
                                # This is a bagel-containing menu item
                                # Apply default bagel type if available and not already set
                                if bagel_item_info.get("default_bagel_type") and not item.bagel_choice:
                                    item.bagel_choice = bagel_item_info["default_bagel_type"]
                                    logger.info("Applied default bagel type '%s' to %s",
                                               item.bagel_choice, item.menu_item_name)
                                # If no default and bagel_choice not set, ask for bagel type
                                if not item.bagel_choice:
                                    bagel_handler_items.append((item.id, item.menu_item_name, "menu_item", "bagel_choice"))
                                # Then ask for toasted if not set
                                elif item.toasted is None:
                                    bagel_handler_items.append((item.id, item.menu_item_name, "menu_item", "toasted"))
                            # Non-bagel menu items (spread/salad sandwiches) need toasted question
                            # These are also handled by bagel config handler
                            elif item.toasted is None:
                                bagel_handler_items.append((item.id, item.menu_item_name, "menu_item", "toasted"))
                elif isinstance(item, BagelItemTask):
                    # Check bagel_type first, then toasted, then cheese clarification, then spread
                    if item.bagel_type is None:
                        bagel_handler_items.append((item.id, "bagel", "bagel", "bagel_choice"))
                    elif item.toasted is None:
                        bagel_handler_items.append((item.id, f"{item.bagel_type} bagel", "bagel", "toasted"))
                    elif item.needs_cheese_clarification:
                        # User said "cheese" without specifying type - need cheese clarification
                        bagel_handler_items.append((item.id, f"{item.bagel_type} bagel", "bagel", "cheese_choice"))
                    elif item.spread is None and not item.extras and not item.sandwich_protein:
                        # Need spread if bagel has no toppings (plain bagel needs spread question)
                        bagel_handler_items.append((item.id, f"{item.bagel_type} bagel", "bagel", "spread"))
                elif isinstance(item, CoffeeItemTask):
                    # Legacy CoffeeItemTask - route to coffee handler like sized_beverage MenuItemTask
                    if item.size is None:
                        coffee_handler_items.append((item.id, item.drink_type or "coffee", "coffee", "coffee_size"))
                    elif item.iced is None:
                        coffee_handler_items.append((item.id, item.drink_type or "coffee", "coffee", "coffee_style"))
                    elif item.milk is None and not item.sweeteners and not item.flavor_syrups:
                        coffee_handler_items.append((item.id, item.drink_type or "coffee", "coffee", "coffee_modifiers"))

        # Build final list: only FIRST item from each handler group + all individual items
        # Handlers with internal loops will find subsequent items of their type automatically
        items_needing_config: list[tuple[str, str, str, str]] = []

        # Add first bagel-handler item (if any) - configure_next_incomplete_bagel will find the rest
        if bagel_handler_items:
            items_needing_config.append(bagel_handler_items[0])
            if len(bagel_handler_items) > 1:
                logger.info("Bagel handler will process %d items via internal loop (not queued): %s",
                           len(bagel_handler_items) - 1,
                           [(n, f) for _, n, _, f in bagel_handler_items[1:]])

        # Add first coffee-handler item (if any) - configure_next_incomplete_coffee will find the rest
        if coffee_handler_items:
            items_needing_config.append(coffee_handler_items[0])
            if len(coffee_handler_items) > 1:
                logger.info("Coffee handler will process %d items via internal loop (not queued): %s",
                           len(coffee_handler_items) - 1,
                           [(n, f) for _, n, _, f in coffee_handler_items[1:]])

        # Add all individual items (no internal loops for these)
        # Note: Espresso items use MenuItemTask and are included in individual_items via menu_item_config
        items_needing_config.extend(individual_items)

        logger.info("Multi-item order: %d items to configure (grouped by handler): %s",
                    len(items_needing_config),
                    [(n, f) for _, n, _, f in items_needing_config])

        # Check if there's pending item disambiguation (e.g., "chips" matches multiple items)
        # This happens when add_menu_item found multiple matches and set up disambiguation
        if order.pending_field == "item_selection" and order.pending_item_options:
            logger.info("Pending item disambiguation: %d options", len(order.pending_item_options))
            # Build the disambiguation question
            generic_term = summaries[0] if summaries else "item"
            option_list = []
            for i, item in enumerate(order.pending_item_options[:6], 1):
                name = item.get("name", "Unknown")
                option_list.append(f"{i}. {name}")
            options_str = "\n".join(option_list)
            return StateMachineResult(
                message=f"We have a few {generic_term} options:\n{options_str}\nWhich would you like?",
                order=order,
            )

        # If no items need configuration, return simple confirmation
        if not items_needing_config:
            if len(summaries) == 1:
                response = f"Got it, {summaries[0]}. Anything else?"
            elif len(summaries) == 2:
                response = f"Got it, {summaries[0]} and {summaries[1]}. Anything else?"
            else:
                items_str = ", ".join(summaries[:-1]) + f", and {summaries[-1]}"
                response = f"Got it, {items_str}. Anything else?"
            return StateMachineResult(message=response, order=order)

        # Queue items 2+ for later configuration with their names
        # Store the names of all items that need config for final summary
        order.multi_item_config_names = [name for _, name, _, _ in items_needing_config]

        for item_id, item_name, item_type, pending_field in items_needing_config[1:]:
            order.queue_item_for_config(item_id, item_type, item_name=item_name, pending_field=pending_field)
            logger.info("Queued %s (%s) for %s config after first item", item_name, item_id[:8], pending_field)

        # Ask about the first item that needs config
        first_item_id, first_item_name, first_item_type, first_field = items_needing_config[0]

        # Build the question for the first item
        if first_field == "side_choice":
            question = f"Would you like a bagel or fruit salad with your {first_item_name}?"
        elif first_field == "toasted":
            # Check if this is an omelette bagel side vs a spread sandwich
            menu_item = next((i for i in order.items.items if i.id == first_item_id), None)
            if isinstance(menu_item, MenuItemTask) and menu_item.side_choice == "bagel":
                # Omelette with bagel side - ask about bagel being toasted
                bagel_desc = f"{menu_item.bagel_choice} bagel" if menu_item.bagel_choice else "bagel"
                question = f"Got it, {bagel_desc}! Would you like that toasted?"
            else:
                question = f"Got it! Would you like the {first_item_name} toasted?"
        elif first_field == "bagel_choice":
            question = f"Got it! What kind of bagel would you like for the {first_item_name}?"
        elif first_field == "bagel_type":
            question = f"Got it! What kind of bagel would you like?"
        elif first_field == "spread":
            # Find the item to check if it's toasted
            item = next((i for i in order.items.items if i.id == first_item_id), None)
            if isinstance(item, BagelItemTask):
                toasted_desc = " toasted" if item.toasted else ""
                question = f"Got it, {first_item_name}{toasted_desc}! Would you like cream cheese or butter on that?"
            elif isinstance(item, MenuItemTask) and item.side_choice == "bagel":
                # Omelette with bagel side
                bagel_desc = f"{item.bagel_choice} bagel" if item.bagel_choice else "bagel"
                toasted_desc = " toasted" if item.toasted else ""
                question = f"Got it, {bagel_desc}{toasted_desc}! Would you like butter or cream cheese on that?"
            else:
                question = f"Got it! Would you like cream cheese or butter on that?"
        elif first_field == "coffee_size":
            question = f"Got it! What size {first_item_name} would you like? Small or Large?"
        elif first_field == "coffee_style":
            question = f"Got it! Would you like the {first_item_name} hot or iced?"
        elif first_field == "coffee_modifiers":
            question = f"Got it, {first_item_name}! Any milk, sweetener, or syrup?"
        elif first_field == "espresso_modifiers":
            question = f"Got it, {first_item_name}! Any milk, sweetener, or syrup?"
        elif first_field == "cheese_choice":
            # Regular bagel with generic "cheese" - ask for type
            item = next((i for i in order.items.items if i.id == first_item_id), None)
            if isinstance(item, BagelItemTask):
                toasted_desc = " toasted" if item.toasted else ""
                question = f"Got it, {first_item_name}{toasted_desc}! What kind of cheese would you like? We have American, cheddar, Swiss, and muenster."
            else:
                question = f"Got it, {first_item_name}! What kind of cheese would you like? We have American, cheddar, Swiss, and muenster."
        elif first_field == "signature_item_cheese_choice":
            question = f"Got it, {first_item_name}! What kind of cheese would you like? We have American, cheddar, Swiss, and muenster."
        elif first_field == "signature_item_bagel_type":
            question = f"Got it, {first_item_name}! What type of bagel would you like?"
        elif first_field == "signature_item_toasted":
            question = f"Got it, {first_item_name}! Would you like that toasted?"
        elif first_field == "menu_item_config":
            # Deli sandwich or other menu item needing DB-driven configuration
            # Delegate to MenuItemConfigHandler
            menu_item = next((i for i in order.items.items if i.id == first_item_id), None)
            if isinstance(menu_item, MenuItemTask) and self.item_adder_handler and self.item_adder_handler.menu_item_handler:
                return self.item_adder_handler.menu_item_handler.get_first_question(menu_item, order)
            else:
                # Fallback if handler not available
                question = f"Got it, {first_item_name}! Any preferences?"
        else:
            question = f"Got it! {first_item_name} - any preferences?"

        # Set up the pending state for handling the answer
        order.pending_item_id = first_item_id
        order.pending_field = first_field
        order.phase = OrderPhase.CONFIGURING_ITEM.value

        return StateMachineResult(message=question, order=order)

    def handle_duplicate_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user's response to duplicate clarification question.

        Called when user said "another one" with multiple items in cart,
        and we asked which item to duplicate.
        """
        from .parsers.deterministic import DUPLICATE_ALL_PATTERN

        pending_info = order.pending_duplicate_selection
        if not pending_info:
            order.pending_field = None
            return StateMachineResult(
                message="Something went wrong. What can I get for you?",
                order=order,
            )

        items = pending_info.get("items", [])
        count = pending_info.get("count", 1)
        text = user_input.strip().lower()

        # Check for "all items" / "everything" response
        if DUPLICATE_ALL_PATTERN.match(text):
            order.pending_duplicate_selection = None
            order.pending_field = None
            active_items = order.items.get_active_items()
            return self._duplicate_all_items(order, active_items)

        # Try to match user's response to one of the item options
        # First, normalize common aliases (e.g., "coke" -> "Coca-Cola")
        from .parsers.constants import resolve_soda_alias
        normalized_text = resolve_soda_alias(text).lower()

        matched_item = None
        best_match_score = 0

        for item_info in items:
            summary_lower = item_info["summary"].lower()
            score = 0

            # Exact match (highest priority)
            if normalized_text == summary_lower:
                score = 100
            # Normalized text matches item exactly
            elif normalized_text in summary_lower and len(normalized_text) == len(summary_lower):
                score = 90
            # User text is the full item name
            elif text == summary_lower:
                score = 85
            # Normalized text starts with item or item starts with normalized text
            elif summary_lower.startswith(normalized_text) or normalized_text.startswith(summary_lower):
                score = 70
            # Original text is substring of item name (but check it's not a partial match like "coke" in "diet coke")
            elif text in summary_lower:
                # Penalize if there's a more specific match possible
                # "coke" in "diet coke" should score lower than "coke" matching "coca-cola" via alias
                score = 30
            # Check for partial word matches (e.g., "bagel" matches "plain bagel toasted")
            else:
                words = text.split()
                matching_words = sum(1 for word in words if len(word) > 2 and word in summary_lower)
                if matching_words > 0:
                    score = 20 + matching_words * 5

            if score > best_match_score:
                best_match_score = score
                matched_item = item_info

        # Also check for ordinal responses: "the first one", "the second", "1", "2", etc.
        if not matched_item:
            ordinal_map = {
                "1": 0, "first": 0, "the first": 0, "the first one": 0,
                "2": 1, "second": 1, "the second": 1, "the second one": 1,
                "3": 2, "third": 2, "the third": 2, "the third one": 2,
                "4": 3, "fourth": 3, "the fourth": 3, "the fourth one": 3,
                "5": 4, "fifth": 4, "the fifth": 4, "the fifth one": 4,
            }
            for key, idx in ordinal_map.items():
                if text == key or text.startswith(key + " "):
                    if idx < len(items):
                        matched_item = items[idx]
                        break

        if not matched_item:
            # Didn't understand - repeat the question
            question_parts = [f"another {opt['summary']}" for opt in items]
            question = ", ".join(question_parts) + ", or all the items in your order?"
            question = "I didn't catch that. " + question[0].upper() + question[1:]
            return StateMachineResult(
                message=question,
                order=order,
            )

        # Found the item to duplicate - find it in the order and duplicate it
        order.pending_duplicate_selection = None
        order.pending_field = None

        # Find the actual item by ID
        item_to_duplicate = None
        for item in order.items.get_active_items():
            if item.id == matched_item["id"]:
                item_to_duplicate = item
                break

        if not item_to_duplicate:
            return StateMachineResult(
                message="I couldn't find that item. What else can I get you?",
                order=order,
            )

        # Duplicate the item
        item_name = item_to_duplicate.get_summary()
        for _ in range(count):
            new_item = item_to_duplicate.model_copy(deep=True)
            new_item.id = str(uuid.uuid4())
            new_item.mark_complete()
            order.items.add_item(new_item)

        if count == 1:
            logger.info("Added 1 more of '%s' to order (from clarification)", item_name)
            return StateMachineResult(
                message=f"I've added another {item_name}. Anything else?",
                order=order,
            )
        else:
            logger.info("Added %d more of '%s' to order (from clarification)", count, item_name)
            return StateMachineResult(
                message=f"I've added {count} more {item_name}. Anything else?",
                order=order,
            )

    def handle_confirm_suggested_item(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user's response to 'Would you like to order one?' after item description.

        Called when user asked about an item (e.g., 'what's in the Lexington?'),
        bot described it and asked 'Would you like to order one?'.
        """
        suggested_item = order.pending_suggested_item
        user_lower = user_input.lower().strip()

        # Clear context first (will be processed either way)
        order.pending_suggested_item = None
        order.pending_field = None

        # Check for affirmative response
        affirmative_patterns = [
            "yes", "yeah", "yep", "yup", "sure", "ok", "okay",
            "give me one", "i'll take one", "i'll have one",
            "i want one", "one please", "get me one",
            "i'll take it", "i'll have it", "i want it",
            "sounds good", "let's do it", "please", "definitely",
            "absolutely", "of course", "why not", "go ahead",
        ]

        is_affirmative = any(pattern in user_lower for pattern in affirmative_patterns)

        if is_affirmative and suggested_item:
            logger.info(
                "User confirmed suggested item '%s' with response: '%s'",
                suggested_item, user_input
            )
            # Use existing add_menu_item to add the suggested item
            return self.item_adder_handler.add_menu_item(
                suggested_item,
                quantity=1,
                order=order,
            )

        # Not affirmative - process as normal taking_items input
        # User might be ordering something else or saying no
        logger.info(
            "User did not confirm suggested item '%s', processing as normal input: '%s'",
            suggested_item, user_input
        )
        return self.handle_taking_items(user_input, order)

    def _duplicate_all_items(
        self,
        order: OrderTask,
        active_items: list,
    ) -> StateMachineResult:
        """Duplicate all items in the cart, matching original quantities."""
        if not active_items:
            return StateMachineResult(
                message="There's nothing in your order yet. What can I get for you?",
                order=order,
            )

        # Duplicate each item, respecting its quantity
        total_added = 0
        for item in active_items:
            qty = item.quantity
            for _ in range(qty):
                new_item = item.model_copy(deep=True)
                new_item.id = str(uuid.uuid4())
                new_item.mark_complete()
                order.items.add_item(new_item)
                total_added += 1

        logger.info("Duplicated all items in cart, added %d items total", total_added)

        if len(active_items) == 1:
            item_name = active_items[0].get_summary()
            return StateMachineResult(
                message=f"I've added another {item_name}. Anything else?",
                order=order,
            )
        else:
            return StateMachineResult(
                message=f"I've duplicated everything in your order. Anything else?",
                order=order,
            )

    def handle_same_thing_clarification(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user's response to 'same thing' clarification question.

        Called when user said "same thing" and we have both a previous order
        AND items in the current cart, so we asked which they meant.
        """
        from .parsers.deterministic import DUPLICATE_ALL_PATTERN

        pending_info = order.pending_same_thing_clarification
        if not pending_info:
            order.pending_field = None
            return StateMachineResult(
                message="Something went wrong. What can I get for you?",
                order=order,
            )

        cart_items = pending_info.get("cart_items", [])
        text = user_input.strip().lower()

        # Check if user wants to repeat previous order
        previous_order_patterns = [
            "previous", "last order", "my order", "repeat", "the order",
            "what i had", "before", "last time"
        ]
        if any(pattern in text for pattern in previous_order_patterns):
            order.pending_same_thing_clarification = None
            order.pending_field = None
            return self.checkout_handler.handle_repeat_order(
                order,
                returning_customer=self._returning_customer,
                set_repeat_info_callback=self._set_repeat_info_callback,
            )

        # Check if user wants to duplicate all items in cart
        if DUPLICATE_ALL_PATTERN.match(text) or "all" in text or "everything" in text:
            order.pending_same_thing_clarification = None
            order.pending_field = None
            active_items = order.items.get_active_items()
            return self._duplicate_all_items(order, active_items)

        # Check if user wants to duplicate something from cart (single item case or specific item)
        cart_patterns = ["cart", "current", "another", "duplicate", "one more"]
        if any(pattern in text for pattern in cart_patterns):
            order.pending_same_thing_clarification = None
            order.pending_field = None
            active_items = order.items.get_active_items()

            if len(active_items) == 1:
                # Single item - duplicate it
                last_item = active_items[-1]
                last_item_name = last_item.get_summary()
                new_item = last_item.model_copy(deep=True)
                new_item.id = str(uuid.uuid4())
                new_item.mark_complete()
                order.items.add_item(new_item)
                logger.info("'Same thing' clarified: duplicated single cart item '%s'", last_item_name)
                return StateMachineResult(
                    message=f"I've added another {last_item_name}. Anything else?",
                    order=order,
                )
            else:
                # Multiple items - ask which one
                item_options = []
                for item in reversed(active_items):
                    item_options.append({
                        "id": item.id,
                        "summary": item.get_summary(),
                        "quantity": item.quantity,
                    })
                order.pending_duplicate_selection = {
                    "count": 1,
                    "items": item_options,
                }
                order.pending_field = "duplicate_selection"
                question_parts = [f"another {opt['summary']}" for opt in item_options]
                question = ", ".join(question_parts) + ", or all the items?"
                question = question[0].upper() + question[1:]
                return StateMachineResult(
                    message=question,
                    order=order,
                )

        # Try to match user's response to one of the cart items directly
        matched_item = None
        for item_info in cart_items:
            summary_lower = item_info["summary"].lower()
            if text in summary_lower or summary_lower in text:
                matched_item = item_info
                break

        if matched_item:
            order.pending_same_thing_clarification = None
            order.pending_field = None

            # Find the actual item by ID
            item_to_duplicate = None
            for item in order.items.get_active_items():
                if item.id == matched_item["id"]:
                    item_to_duplicate = item
                    break

            if item_to_duplicate:
                item_name = item_to_duplicate.get_summary()
                new_item = item_to_duplicate.model_copy(deep=True)
                new_item.id = str(uuid.uuid4())
                new_item.mark_complete()
                order.items.add_item(new_item)
                logger.info("'Same thing' clarified: duplicated specific item '%s'", item_name)
                return StateMachineResult(
                    message=f"I've added another {item_name}. Anything else?",
                    order=order,
                )

        # Didn't understand - repeat the question
        active_items = order.items.get_active_items()
        if len(active_items) == 1:
            cart_option = f"another {active_items[0].get_summary()}"
        else:
            cart_option = "duplicate something from your current order"

        return StateMachineResult(
            message=f"I didn't catch that. Would you like to repeat your previous order, or {cart_option}?",
            order=order,
        )
