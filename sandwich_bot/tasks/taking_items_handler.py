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
from sandwich_bot.exceptions import MenuDataNotLoadedError

from .models import (
    OrderTask,
    MenuItemTask,
    TaskStatus,
)
from .schemas.phases import OrderPhase
from .schemas import (
    StateMachineResult,
    OpenInputResponse,
    ExtractedModifiers,
    CoffeeOrderDetails,
    # ParsedItem types for multi-item handling
    ParsedItemEntry,
    ParsedMenuItemEntry,
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
    get_bagel_spreads,
    get_coffee_types,
    is_soda_drink,
    resolve_soda_alias,
    resolve_coffee_alias,
    resolve_side_alias,
    resolve_menu_item_alias,
)

if TYPE_CHECKING:
    from .handler_config import HandlerConfig
    from .pricing import PricingEngine
    from .item_adder_handler import ItemAdderHandler
    from .menu_inquiry_handler import MenuInquiryHandler
    from .store_info_handler import StoreInfoHandler
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


# =============================================================================
# ParsedItem Type Checking Helpers
# =============================================================================
# These helpers check item types using data-driven attribute lookups.

def _is_bagel_entry(item: "ParsedItem") -> bool:
    """Check if a ParsedItem represents a bagel (has bread attribute)."""
    item_type = getattr(item, 'item_type', None)
    if not item_type:
        return False
    # Data-driven check: item type has bread attribute
    attrs = menu_cache.get_item_type_attributes(item_type)
    return "bread" in attrs


def _is_coffee_entry(item: "ParsedItem") -> bool:
    """Check if a ParsedItem represents a coffee/beverage (has size attribute)."""
    item_type = getattr(item, 'item_type', None)
    if not item_type:
        return False
    # Data-driven check: item type has size attribute (sized beverages)
    attrs = menu_cache.get_item_type_attributes(item_type)
    return "size" in attrs


def _get_beverage_modifier_patterns(category: str) -> set[str]:
    """Get all matching patterns for a beverage modifier category.

    This is the generic replacement for _get_syrup_options(), _get_sweetener_options(), etc.
    Returns a flat set of all patterns that can match this category for input detection.

    Args:
        category: The ingredient category (e.g., "syrup", "milk", "sweetener")

    Returns:
        Set of lowercase patterns for matching user input.

    Raises:
        MenuDataNotLoadedError: If menu cache is not loaded
    """
    details = menu_cache.get_ingredient_details(category)
    patterns = set()
    for detail in details:
        patterns.update(detail["patterns"])
    return patterns


def _match_beverage_modifier(
    input_lower: str, category: str
) -> dict | None:
    """Match user input against a beverage modifier category and return details.

    This is the generic replacement for the various _get_*_options functions.
    Uses database slugs and display names instead of manually constructing them.

    Args:
        input_lower: Lowercase user input to match against
        category: The ingredient category (e.g., "syrup", "milk", "sweetener")

    Returns:
        Dict with {slug, name, pattern} if matched, None otherwise.
        - slug: Database identifier for storage (e.g., "oat_milk")
        - name: Display name for UI (e.g., "Oat Milk")
        - pattern: The pattern that matched (e.g., "oat")

    Raises:
        MenuDataNotLoadedError: If menu cache is not loaded
    """
    details = menu_cache.get_ingredient_details(category)
    for detail in details:
        for pattern in detail["patterns"]:
            if pattern in input_lower:
                return {
                    "slug": detail["slug"],
                    "name": detail["name"],
                    "pattern": pattern,
                }
    return None


def _get_all_beverage_modifier_patterns() -> set[str]:
    """Get all beverage modifier patterns for input detection.

    Returns combined patterns for syrup, milk, and sweetener categories.
    Used to detect if user input contains any beverage modifier.

    Returns:
        Set of all beverage modifier patterns (lowercase).
    """
    patterns = set()
    for category in ["syrup", "milk", "sweetener"]:
        patterns.update(_get_beverage_modifier_patterns(category))
    # Add generic category keywords
    patterns.update({"syrup", "sweetener", "milk"})
    return patterns


def _extract_quantity_from_input(input_lower: str, pattern: str) -> int:
    """Extract quantity from user input for a modifier.

    Handles patterns like "2 vanilla", "two sugars", "double shot".

    Args:
        input_lower: Lowercase user input
        pattern: The modifier pattern to look for quantity before

    Returns:
        Quantity (defaults to 1 if not found)
    """
    word_to_num = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "double": 2, "triple": 3
    }
    qty_match = re.search(rf'(\d+|one|two|three|four|five|double|triple)\s+{re.escape(pattern)}', input_lower)
    if qty_match:
        qty_str = qty_match.group(1)
        return int(qty_str) if qty_str.isdigit() else word_to_num.get(qty_str, 1)
    return 1


def _add_beverage_modifier_to_item(
    item: "MenuItemTask",
    slug: str,
    display_name: str,
    quantity: int = 1,
    category: str | None = None,
) -> bool:
    """Add a beverage modifier to an item using the unified storage model.

    Uses milk_sweetener_syrup_selections for all beverage modifiers.
    This is the single unified storage model for milk, sweeteners, and syrups.

    Args:
        item: The MenuItemTask to modify
        slug: Database slug for the modifier (e.g., "oat_milk")
        display_name: Display name for the modifier (e.g., "Oat Milk")
        quantity: Quantity (default 1, used for sweeteners/syrups)
        category: Optional category for logging ("milk", "sweetener", "syrup")

    Returns:
        True if modifier was added, False if already present
    """
    # Get current selections (unified storage)
    mss_slugs = item.attribute_values.get("milk_sweetener_syrup", [])
    mss_selections = item.attribute_values.get("milk_sweetener_syrup_selections", [])

    # Check if already present
    if slug in mss_slugs:
        return False

    # Add the modifier
    mss_slugs.append(slug)
    selection_entry = {
        "slug": slug,
        "display_name": display_name,
        "quantity": quantity,
    }
    if category:
        selection_entry["category"] = category
    mss_selections.append(selection_entry)

    # Update item
    item.attribute_values["milk_sweetener_syrup"] = mss_slugs
    item.attribute_values["milk_sweetener_syrup_selections"] = mss_selections

    logger.info(
        "Added %s modifier: %s (qty=%d) to %s",
        category or "beverage",
        slug,
        quantity,
        item.item_name or item.menu_item_type
    )
    return True


def _add_beverage_modifiers_from_input(
    item: "MenuItemTask",
    input_lower: str,
) -> bool:
    """Add all matching beverage modifiers from user input to an item.

    Scans input for milk, sweetener, and syrup modifiers and adds them
    using the unified storage model (milk_sweetener_syrup_selections).

    Args:
        item: The MenuItemTask to modify
        input_lower: Lowercase user input to scan for modifiers

    Returns:
        True if any modifiers were added, False otherwise
    """
    made_change = False

    # Check each beverage modifier category
    for category in ["syrup", "milk", "sweetener"]:
        match = _match_beverage_modifier(input_lower, category)
        if match:
            # Extract quantity from input
            quantity = _extract_quantity_from_input(input_lower, match["pattern"])

            # Add to item using unified storage
            if _add_beverage_modifier_to_item(
                item,
                slug=match["slug"],
                display_name=match["name"],
                quantity=quantity,
                category=category,
            ):
                made_change = True

    return made_change


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

    # Type annotations for instance variables
    model: str
    pricing: "PricingEngine | None"
    _menu_data: dict
    item_adder_handler: "ItemAdderHandler | None"
    menu_inquiry_handler: "MenuInquiryHandler | None"
    store_info_handler: "StoreInfoHandler | None"
    checkout_utils_handler: "CheckoutUtilsHandler | None"
    checkout_handler: "CheckoutHandler | None"
    _returning_customer: dict | None
    _set_repeat_info_callback: Callable[[bool, str | None], None] | None

    def __init__(
        self,
        config: "HandlerConfig",
        item_adder_handler: "ItemAdderHandler | None" = None,
        menu_inquiry_handler: "MenuInquiryHandler | None" = None,
        store_info_handler: "StoreInfoHandler | None" = None,
        checkout_utils_handler: "CheckoutUtilsHandler | None" = None,
        checkout_handler: "CheckoutHandler | None" = None,
    ) -> None:
        """
        Initialize the taking items handler.

        Args:
            config: HandlerConfig with shared dependencies.
            item_adder_handler: Handler for adding items.
            menu_inquiry_handler: Handler for menu inquiries.
            store_info_handler: Handler for store info inquiries.
            checkout_utils_handler: Handler for checkout utilities.
            checkout_handler: Handler for checkout flow including confirmation/repeat orders.
        """
        self.model = config.model
        self.pricing = config.pricing
        self._menu_data = config.menu_data or {}

        # Handler-specific dependencies
        self.item_adder_handler = item_adder_handler
        self.menu_inquiry_handler = menu_inquiry_handler
        self.store_info_handler = store_info_handler
        self.checkout_utils_handler = checkout_utils_handler
        self.checkout_handler = checkout_handler

        # Context set per-request
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
        returning_customer: dict | None,
        set_repeat_info_callback: Callable[[bool, str | None], None] | None = None,
    ) -> None:
        """Set per-request context."""
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

        # Beverage modifiers that should trigger modification instead of new item
        # Built from database using generic helper
        beverage_modifiers = _get_all_beverage_modifier_patterns()
        has_beverage_modifier = any(mod in input_lower for mod in beverage_modifiers)

        # Check if this is a pure modifier input (e.g., "2 vanilla syrups", "vanilla syrup")
        # that should be added to an existing beverage
        is_pure_modifier_input = False
        if has_beverage_modifier and active_items:
            last_item = active_items[-1]
            # Check if item is a beverage (has milk attribute or beverage modifier category)
            is_beverage = (
                isinstance(last_item, MenuItemTask) and
                (last_item.has_attribute("milk") or
                 menu_cache.get_modifier_category(last_item.menu_item_type) == "beverage")
            )
            if is_beverage:
                # Check if input is ONLY a modifier (no other item keywords)
                # Use item keywords from database (menu item names + item type slugs)
                item_keywords = menu_cache.get_item_keywords()
                has_other_item = any(kw in input_lower for kw in item_keywords)
                if not has_other_item:
                    is_pure_modifier_input = True

        # If it's an "add modifier" pattern OR pure modifier input, and the last item is a beverage, modify it
        if (is_add_modifier_request or is_pure_modifier_input) and has_beverage_modifier and active_items:
            last_item = active_items[-1]
            # Unified beverage modifier handling using milk_sweetener_syrup_selections
            is_beverage = (
                isinstance(last_item, MenuItemTask) and
                (last_item.has_attribute("milk") or
                 menu_cache.get_modifier_category(last_item.menu_item_type) == "beverage")
            )
            if is_beverage:
                made_change = _add_beverage_modifiers_from_input(last_item, input_lower)

                if made_change:
                    self.pricing.recalculate_item_price(last_item)
                    updated_summary = last_item.get_summary()
                    return StateMachineResult(
                        message=f"Sure, I've added that to your {updated_summary}. Anything else?",
                        order=order,
                    )

        parsed = parse_open_input(
            user_input,
            model=self.model,
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

            # Beverage modifiers that should trigger modification instead of new item
            # Built from database using generic helper
            beverage_modifiers = _get_all_beverage_modifier_patterns()
            has_beverage_modifier = any(mod in input_lower for mod in beverage_modifiers)

            # Check if this is a pure modifier input (e.g., "2 vanilla syrups", "vanilla syrup")
            # that should be added to an existing beverage
            is_pure_modifier_input = False
            if has_beverage_modifier and active_items:
                last_item_check = active_items[-1]
                # Check if item is a beverage (has milk attribute or beverage modifier category)
                is_beverage = (
                    isinstance(last_item_check, MenuItemTask) and
                    (last_item_check.has_attribute("milk") or
                     menu_cache.get_modifier_category(last_item_check.menu_item_type) == "beverage")
                )
                if is_beverage:
                    # Check if input is ONLY a modifier (no other item keywords)
                    # Use item keywords from database (menu item names + item type slugs)
                    item_keywords = menu_cache.get_item_keywords()
                    has_other_item = any(kw in input_lower for kw in item_keywords)
                    if not has_other_item:
                        is_pure_modifier_input = True

            # If it's an "add modifier" pattern OR pure modifier input, and the last item is a beverage, modify it
            if (is_add_modifier_request or is_pure_modifier_input) and has_beverage_modifier and active_items:
                last_item = active_items[-1]
                # Unified beverage modifier handling using milk_sweetener_syrup_selections
                is_beverage = (
                    isinstance(last_item, MenuItemTask) and
                    (last_item.has_attribute("milk") or
                     menu_cache.get_modifier_category(last_item.menu_item_type) == "beverage")
                )
                if is_beverage:
                    made_change = _add_beverage_modifiers_from_input(last_item, input_lower)

                    if made_change:
                        self.pricing.recalculate_item_price(last_item)
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
                    # Find an item that accepts spread to add the spread to
                    # Prefer: 1) item without spread, 2) most recent item with spread attribute
                    items_accepting_spread = [i for i in active_items if isinstance(i, MenuItemTask) and i.has_attribute("spread")]
                    target_item = None

                    # First, look for an item without a spread
                    for item in reversed(items_accepting_spread):
                        if item.spread is None:
                            target_item = item
                            break

                    # If all items have spreads, use the most recent one
                    if target_item is None and items_accepting_spread:
                        target_item = items_accepting_spread[-1]

                    if target_item:
                        # Normalize the spread name
                        normalized_spread = menu_cache.normalize_modifier(detected_spread)
                        old_spread = target_item.spread

                        # Set the spread on the item
                        target_item.spread = normalized_spread

                        # Recalculate price
                        self.pricing.recalculate_item_price(target_item)
                        updated_summary = target_item.get_summary()

                        if old_spread:
                            logger.info("Add spread: changed spread from '%s' to '%s' on item", old_spread, normalized_spread)
                            return StateMachineResult(
                                message=f"Sure, I've changed the spread to {normalized_spread}. Your order is now {updated_summary}. Anything else?",
                                order=order,
                            )
                        else:
                            logger.info("Add spread: added '%s' to item", normalized_spread)
                            return StateMachineResult(
                                message=f"Sure, I've added {normalized_spread}. Your order is now {updated_summary}. Anything else?",
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
            # Items with bread attribute (bagels, some sandwiches) can be matched by bread/bagel type
            items_with_bread = [i for i in active_items if isinstance(i, MenuItemTask) and i.has_attribute("bread")]
            menu_items_in_cart = [i for i in active_items if isinstance(i, MenuItemTask)]

            if target_desc:
                # Explicit target - find matching item by bread/bagel type
                for item in items_with_bread:
                    item_bagel_type = (item.bread or "").lower()
                    # Match if the target description contains the bagel type
                    # e.g., "cinnamon raisin" matches a cinnamon raisin bagel
                    if item_bagel_type and item_bagel_type in target_desc:
                        target_item = item
                        break
                    # Also match if target is a category reference (e.g., "bagel") and there's only one item with bread
                    target_category = menu_cache.is_category_reference(target_desc)
                    if target_category and len(items_with_bread) == 1:
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
                # Handle MenuItemTask
                if isinstance(target_item, MenuItemTask):
                    # For MenuItemTask, add modifiers to attribute_values
                    if parsed.modify_add_modifiers:
                        # Build modifier→category lookup (data-driven from database)
                        modifier_to_category: dict[str, str] = {}
                        for category in menu_cache.get_ordered_ingredient_categories("food"):
                            for ingredient in menu_cache.get_ingredients(category):
                                modifier_to_category[ingredient.lower()] = category

                        for modifier in parsed.modify_add_modifiers:
                            # Handle qualified modifiers: "mayo (extra)" -> base="mayo", full="mayo_(extra)"
                            # Extract base modifier name for categorization
                            modifier_lower = modifier.lower()
                            base_modifier = modifier_lower.split(" (")[0].strip()  # "mayo (extra)" -> "mayo"
                            modifier_slug = modifier_lower.replace(" ", "_")  # Keep full "mayo_(extra)"

                            # Determine which attribute this modifier belongs to (data-driven)
                            category = modifier_to_category.get(base_modifier)
                            if category:
                                attr_key = menu_cache.get_category_attribute_slug(category)
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

                # Bagel handling (original logic)
                # Apply the spread modification
                if parsed.modify_new_spread:
                    target_item.spread = parsed.modify_new_spread
                if parsed.modify_new_spread_type:
                    target_item.spread_type = parsed.modify_new_spread_type

                # Apply add-modifier modifications ("add bacon", "extra cheese", etc.)
                if parsed.modify_add_modifiers:
                    # Build modifier→category lookup (data-driven from database)
                    modifier_to_category: dict[str, str] = {}
                    for category in menu_cache.get_ordered_ingredient_categories("food"):
                        for ingredient in menu_cache.get_ingredients(category):
                            modifier_to_category[ingredient.lower()] = category

                    for modifier in parsed.modify_add_modifiers:
                        # Handle qualified modifiers: "bacon (extra)" -> base="bacon"
                        # Extract base modifier name for categorization
                        modifier_lower = modifier.lower()
                        base_modifier = modifier_lower.split(" (")[0].strip()  # "bacon (extra)" -> "bacon"

                        # Determine modifier category (data-driven)
                        category = modifier_to_category.get(base_modifier)

                        # Special handling for protein: single field with overflow to toppings
                        if category == "protein":
                            if not target_item.extra_protein:
                                target_item.extra_protein = modifier  # Store full qualified modifier
                            else:
                                # Already have a protein, add to toppings
                                if modifier not in target_item.toppings:
                                    target_item.toppings.append(modifier)
                        else:
                            # All other modifiers (cheese, topping, unknown) go to toppings
                            if modifier not in target_item.toppings:
                                target_item.toppings.append(modifier)
                        logger.info("MODIFY ADD: Added '%s' to '%s'", modifier, target_item.bread)

                # Recalculate price
                self.pricing.recalculate_item_price(target_item)

                updated_summary = target_item.get_summary()
                logger.info(
                    "MODIFY EXISTING: Updated '%s' with spread=%s, spread_type=%s, add_modifiers=%s",
                    target_item.bread, parsed.modify_new_spread, parsed.modify_new_spread_type,
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
                has_new_items = bool(parsed.parsed_items)

                # Special case: If last item is a bagel and the "menu item" is a cream cheese sandwich,
                # treat this as a spread change, not a menu item replacement.
                # e.g., "make it blueberry cream cheese" -> change spread, not add Blueberry Cream Cheese Sandwich
                cream_cheese_menu_item = next(
                    (item for item in parsed.parsed_items
                     if (isinstance(item, ParsedMenuItemEntry) and "cream cheese sandwich" in item.menu_item_name.lower())
                     or (isinstance(item, ParsedItemEntry) and item.item_type == "menu_item"
                         and item.item_name and "cream cheese sandwich" in item.item_name.lower())),
                    None
                )
                # Get the menu item name from either type
                cream_cheese_name = (
                    cream_cheese_menu_item.menu_item_name if isinstance(cream_cheese_menu_item, ParsedMenuItemEntry)
                    else cream_cheese_menu_item.item_name if cream_cheese_menu_item else None
                )
                if has_new_items and cream_cheese_menu_item and cream_cheese_name and isinstance(last_item, MenuItemTask) and last_item.has_attribute("spread"):
                    # Extract the spread name from the menu item name
                    # "Blueberry Cream Cheese Sandwich" -> "blueberry cream cheese"
                    spread_name = cream_cheese_name.lower().replace(" sandwich", "")
                    old_spread = last_item.spread or "none"
                    last_item.spread = spread_name
                    logger.info("Replacement: interpreted '%s' as spread change from '%s' to '%s'",
                               cream_cheese_menu_item.menu_item_name, old_spread, spread_name)

                    # Recalculate price if needed
                    self.pricing.recalculate_item_price(last_item)

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
                     if _is_bagel_entry(item) and item.bread),
                    None
                )
                if has_new_items and bagel_entry and isinstance(last_item, MenuItemTask) and last_item.has_attribute("bread"):
                    old_type = last_item.bread or "plain"
                    last_item.bread = bagel_entry.bread
                    logger.info("Replacement: changed bagel type from '%s' to '%s', preserving modifiers",
                               old_type, bagel_entry.bread)

                    # Recalculate price if needed
                    self.pricing.recalculate_item_price(last_item)

                    updated_summary = last_item.get_summary()
                    return StateMachineResult(
                        message=f"Sure, I've changed that to {updated_summary}. Anything else?",
                        order=order,
                    )

                # If no new items parsed and last item accepts food modifiers, try applying as modifiers
                if not has_new_items and isinstance(last_item, MenuItemTask) and last_item.has_attribute("spread") and raw_user_input:
                    modifiers = extract_modifiers_from_input(raw_user_input)
                    proteins = modifiers.get_names("protein")
                    cheeses = modifiers.get_names("cheese")
                    toppings = modifiers.get_names("topping")
                    spreads = modifiers.get_names("spread")
                    has_modifiers = proteins or cheeses or toppings

                    if has_modifiers:
                        # Apply modifiers to existing bagel instead of replacing
                        logger.info("Replacement: applying modifiers to existing bagel: %s", modifiers)

                        # Update protein - replace existing
                        if proteins:
                            last_item.extra_protein = proteins[0]
                            # Additional proteins go to toppings (replace existing toppings)
                            last_item.toppings = list(proteins[1:])
                        else:
                            # Clear protein if not in new modifiers
                            last_item.extra_protein = None
                            last_item.toppings = []

                        # Add cheeses and toppings to item.toppings
                        last_item.toppings.extend(cheeses)
                        last_item.toppings.extend(toppings)

                        # Update spread if specified
                        if spreads:
                            last_item.spread = spreads[0]
                        else:
                            last_item.spread = "none"

                        # Recalculate price with new modifiers
                        self.pricing.recalculate_item_price(last_item)

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
                            self.pricing.recalculate_item_price(last_item)

                            updated_summary = last_item.get_summary()
                            return StateMachineResult(
                                message=f"Sure, I've changed that to {updated_summary}. Anything else?",
                                order=order,
                            )

                        # Bagel type change detection removed - now data-driven

                # If no new items parsed and last item has size attribute (beverage), check for size/style/milk changes
                if not has_new_items and isinstance(last_item, MenuItemTask) and last_item.has_attribute("size") and raw_user_input:
                    input_lower = raw_user_input.lower()
                    made_change = False

                    # Check for size changes (data-driven from DB)
                    new_size = None
                    size_options = menu_cache.get_global_attribute_options("size")
                    for opt in size_options:
                        size_slug = opt.get("slug", "")
                        if size_slug in input_lower:
                            new_size = size_slug
                            break

                    if new_size and new_size != last_item.size:
                        # Get default size from DB for logging
                        default_size = next(
                            (opt["slug"] for opt in size_options if opt.get("is_default")),
                            size_options[0]["slug"] if size_options else "small"
                        )
                        old_size = last_item.size or default_size
                        last_item.size = new_size
                        logger.info("Replacement: changed coffee size from '%s' to '%s'", old_size, new_size)
                        made_change = True

                    # Note: temperature (hot/iced) is now part of the menu item name itself
                    # (e.g., "Iced Latte" vs "Hot Latte"). To change temperature, user
                    # would need to order a different menu item.

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

                    # Check for milk changes using generic matcher
                    milk_match = _match_beverage_modifier(input_lower, "milk")
                    # Also check for "no milk" / "black" patterns
                    if "no milk" in input_lower or "black" in input_lower:
                        milk_match = {"slug": "none", "name": "None", "pattern": "no milk"}

                    if milk_match:
                        new_milk_slug = milk_match["slug"]
                        # Use unified storage model
                        if _add_beverage_modifier_to_item(
                            last_item, new_milk_slug, milk_match["name"],
                            quantity=1, category="milk"
                        ):
                            made_change = True

                    # Check for milk removal: "without milk", "remove the milk"
                    if ("without milk" in input_lower or "remove milk" in input_lower or
                        "remove the milk" in input_lower):
                        # Remove milk from unified storage
                        mss_slugs = last_item.attribute_values.get("milk_sweetener_syrup", [])
                        mss_selections = last_item.attribute_values.get("milk_sweetener_syrup_selections", [])
                        milk_details = menu_cache.get_ingredient_details("milk")
                        milk_slugs = {d["slug"] for d in milk_details}
                        # Filter out any milk entries
                        new_slugs = [s for s in mss_slugs if s not in milk_slugs]
                        new_selections = [s for s in mss_selections if s.get("slug") not in milk_slugs]
                        if len(new_slugs) != len(mss_slugs):
                            last_item.attribute_values["milk_sweetener_syrup"] = new_slugs
                            last_item.attribute_values["milk_sweetener_syrup_selections"] = new_selections
                            logger.info("Replacement: removed milk from beverage")
                            made_change = True

                    # Check for flavor syrup changes using generic matcher
                    syrup_match = _match_beverage_modifier(input_lower, "syrup")
                    if syrup_match:
                        quantity = _extract_quantity_from_input(input_lower, syrup_match["pattern"])
                        if _add_beverage_modifier_to_item(
                            last_item, syrup_match["slug"], syrup_match["name"],
                            quantity=quantity, category="syrup"
                        ):
                            made_change = True

                    # Check for syrup removal: "no syrup", "remove the syrup"
                    if ("no syrup" in input_lower or "remove syrup" in input_lower or
                        "without syrup" in input_lower):
                        # Remove syrups from unified storage
                        mss_slugs = last_item.attribute_values.get("milk_sweetener_syrup", [])
                        mss_selections = last_item.attribute_values.get("milk_sweetener_syrup_selections", [])
                        syrup_details = menu_cache.get_ingredient_details("syrup")
                        syrup_slugs = {d["slug"] for d in syrup_details}
                        # Filter out any syrup entries
                        new_slugs = [s for s in mss_slugs if s not in syrup_slugs]
                        new_selections = [s for s in mss_selections if s.get("slug") not in syrup_slugs]
                        if len(new_slugs) != len(mss_slugs):
                            last_item.attribute_values["milk_sweetener_syrup"] = new_slugs
                            last_item.attribute_values["milk_sweetener_syrup_selections"] = new_selections
                            logger.info("Replacement: removed all syrups from beverage")
                            made_change = True

                    # Check for sweetener removal: "without sugar", "remove the sugar"
                    if ("without sugar" in input_lower or "remove sugar" in input_lower or
                        "remove the sugar" in input_lower or "no sugar" in input_lower or
                        "without sweetener" in input_lower or "remove sweetener" in input_lower or
                        "no sweetener" in input_lower):
                        # Remove sweeteners from unified storage
                        mss_slugs = last_item.attribute_values.get("milk_sweetener_syrup", [])
                        mss_selections = last_item.attribute_values.get("milk_sweetener_syrup_selections", [])
                        sweetener_details = menu_cache.get_ingredient_details("sweetener")
                        sweetener_slugs = {d["slug"] for d in sweetener_details}
                        # Filter out any sweetener entries
                        new_slugs = [s for s in mss_slugs if s not in sweetener_slugs]
                        new_selections = [s for s in mss_selections if s.get("slug") not in sweetener_slugs]
                        if len(new_slugs) != len(mss_slugs):
                            last_item.attribute_values["milk_sweetener_syrup"] = new_slugs
                            last_item.attribute_values["milk_sweetener_syrup_selections"] = new_selections
                            logger.info("Replacement: removed all sweeteners from beverage")
                            made_change = True

                    # If any changes were made, recalculate price and return
                    if made_change:
                        self.pricing.recalculate_item_price(last_item)
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
                        # Recalculate price using unified method
                        self.pricing.recalculate_item_price(modifier_match.item)

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
                        # Filter by item type using data-driven attribute checks
                        # Look up the primary attribute for this item type from the database
                        type_attrs = menu_cache.get_item_type_attributes(item_type)
                        if type_attrs:
                            # Get the first required attribute as the discriminator
                            # Items with this attribute are considered to be of this type
                            primary_attr = type_attrs[0] if type_attrs else None
                            if primary_attr:
                                items_to_check = [
                                    i for i in active_items
                                    if isinstance(i, MenuItemTask) and i.has_attribute(primary_attr)
                                ]
                            else:
                                # No specific attribute - match all menu items
                                items_to_check = [i for i in active_items if isinstance(i, MenuItemTask)]
                        else:
                            # Unknown item type - match all menu items
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

                # Map user category terms to item_type via database (e.g., "coffee" -> "sized_beverage")
                # Uses category keywords from item_types.aliases in the database
                mapped_item_type = None
                category_mapping = menu_cache.get_category_keyword_mapping(cancel_item_desc)
                if not category_mapping:
                    category_mapping = menu_cache.get_category_keyword_mapping(singular_desc)
                if category_mapping:
                    mapped_item_type = category_mapping.get("slug")

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
                    menu_item_type = getattr(item, 'menu_item_type', '') or ''

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
                    # Check menu_item_type (e.g., "sized_beverage", "bagel")
                    elif menu_item_type and (cancel_item_desc == menu_item_type or singular_desc == menu_item_type):
                        matches = True
                    # Check if user's category term maps to this item's type (e.g., "coffee" -> "sized_beverage")
                    elif mapped_item_type and menu_item_type == mapped_item_type:
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

            # Use data-driven lookup from ItemType aliases
            category_info = menu_cache.get_category_keyword_mapping(item_type)
            mapped_type = category_info.get("slug") if category_info else None

            if mapped_type:
                # Use unified add_item() dispatcher (routes based on attributes)
                return self.item_adder_handler.add_item(
                    item_type=mapped_type,
                    order=order,
                    quantity=1,
                )
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
            has_items = bool(parsed.parsed_items)
            if not has_items:
                # Just the order type, no items yet - acknowledge and ask what they want
                return StateMachineResult(
                    message=f"Great, I'll set this up for {order_type_display}. What can I get for you?",
                    order=order,
                )
            # If they also ordered items, continue processing below

        # Process all items via parsed_items list (unified path for any number of items)
        # This is the primary code path - all parsing now populates parsed_items
        if parsed.parsed_items:
            result = self._process_items(parsed, order)
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

    def _add_parsed_item_entry(self, item: ParsedItemEntry, order: OrderTask) -> tuple[OrderTask, str]:
        """
        Handle the unified ParsedItemEntry type (data-driven).

        This method routes based on item_type and extracts attribute_values
        to pass to the unified add_item() dispatcher.

        Returns tuple of (updated_order, item_summary_string).
        """
        item_type = item.item_type

        # Data-driven check: items with bread attribute (bagel-like)
        if menu_cache.item_type_has_attribute(item_type, "bread"):
            # Build ExtractedModifiers from modifiers list
            extracted_mods = ExtractedModifiers()
            # Parse modifiers into categories using data-driven lookup
            for mod in item.modifiers:
                category = menu_cache.get_ingredient_category(mod)
                if category == "protein":
                    extracted_mods.add("protein", mod)
                elif category == "cheese":
                    extracted_mods.add("cheese", mod)
                else:
                    extracted_mods.add("topping", mod)

            if item.needs_cheese_clarification:
                extracted_mods.needs_clarification["cheese"] = True
            if item.special_instructions:
                extracted_mods.special_instructions = [item.special_instructions]

            # Use unified add_item() dispatcher (item_type from parsed item, not hardcoded)
            result = self.item_adder_handler.add_item(
                item_type=item_type,
                order=order,
                quantity=item.quantity,
                bread=item.attribute_values.get("bread"),
                toasted=item.attribute_values.get("toasted"),
                scooped=item.attribute_values.get("scooped"),
                spread=item.attribute_values.get("spread"),
                spread_type=item.attribute_values.get("spread_type"),
                extracted_modifiers=extracted_mods if extracted_mods.has_modifiers() or extracted_mods.has_special_instructions() or extracted_mods.needs_clarification.get("cheese") else None,
            )
            order = result.order

            # Build summary (data-driven display name from DB)
            bread_type = item.attribute_values.get("bread")
            type_display_name = menu_cache.get_item_type_display_name(item_type)
            item_desc = f"{bread_type} {type_display_name}" if bread_type else type_display_name
            summary = item_desc
            if item.attribute_values.get("toasted"):
                summary += " toasted"
            if item.quantity > 1:
                summary = f"{item.quantity} {item_desc}s"
                if item.attribute_values.get("toasted"):
                    summary += " toasted"
            return order, summary

        # Data-driven check: beverage items (modifier_category == "beverage")
        elif menu_cache.get_modifier_category(item_type) == "beverage":
            # Convert sweeteners and syrups to the format expected by add_item
            sweetener = None
            sweetener_quantity = 1
            if item.sweeteners:
                sweetener = item.sweeteners[0].slug
                sweetener_quantity = item.sweeteners[0].quantity

            flavor_syrup = None
            syrup_quantity = 1
            if item.syrups:
                flavor_syrup = item.syrups[0].slug
                syrup_quantity = item.syrups[0].quantity

            # Note: temperature (iced/hot) is now part of the menu item name itself
            # (e.g., "Iced Latte" vs "Hot Latte"), not a separate attribute

            # Track item count before to detect if item was actually added
            # (disambiguation returns without adding to order)
            items_before = len(order.items.items)

            # Use unified add_item() dispatcher
            result = self.item_adder_handler.add_item(
                item_type=item_type,
                order=order,
                quantity=item.quantity,
                item_name=item.item_name,
                size=item.attribute_values.get("size"),
                milk=item.attribute_values.get("milk"),
                sweetener=sweetener,
                sweetener_quantity=sweetener_quantity,
                flavor_syrup=flavor_syrup,
                syrup_quantity=syrup_quantity,
                decaf=item.attribute_values.get("decaf"),
                cream_level=item.attribute_values.get("cream_level"),
                extra_shots=item.attribute_values.get("extra_shots", 0),
                special_instructions=item.special_instructions,
                wants_syrup=item.wants_syrup,
                original_input=item.original_text,
            )
            order = result.order
            items_after = len(order.items.items)

            # Only return summary if item was actually added
            # (disambiguation triggers pending_field without adding item)
            if items_after > items_before:
                # Use item_name or derive from item_type display name (data-driven)
                drink_name = item.item_name or menu_cache.get_item_type_display_name(item_type)
                summary = drink_name
                if item.quantity > 1:
                    summary = f"{item.quantity} {drink_name}s"
                return order, summary
            else:
                # Item wasn't added (disambiguation or error) - return empty summary
                return order, ""

        # Data-driven check: by-pound item types (cheese, fish, spread, etc.)
        elif item_type in menu_cache.get_by_pound_category_names():
            # By-pound items are sized items with "1/4 lb" or "1 lb" sizes
            # The parser converts weight phrases to size + quantity:
            # - "half pound" -> size="1/4 lb", quantity=2
            # - "1 lb" -> size="1 lb", quantity=1
            size = item.attribute_values.get("size", "1/4 lb")

            # Use unified add_item() dispatcher with size parameter
            result = self.item_adder_handler.add_item(
                item_type=item_type,
                order=order,
                quantity=item.quantity,
                item_name=item.item_name,
                size=size,
            )
            order = result.order

            # Build summary with size
            summary = f"{size} {item.item_name}"
            if item.quantity > 1:
                summary = f"{item.quantity}x {summary}"
            return order, summary

        else:
            # Generic item type - use add_menu_item
            result = self.item_adder_handler.add_menu_item(
                item.item_name or item_type,
                item.quantity,
                order,
                item.attribute_values.get("toasted"),
                item.attribute_values.get("bread"),
                item.modifiers,
            )
            order = result.order
            summary = item.item_name or item_type
            if item.quantity > 1:
                summary = f"{item.quantity} {summary}s"
            return order, summary

    def _add_parsed_item(self, item: ParsedItem, order: OrderTask) -> tuple[OrderTask, str]:
        """
        Dispatch a parsed item to the appropriate handler.

        Returns tuple of (updated_order, item_summary_string).
        """
        # Handle new unified ParsedItemEntry type (data-driven)
        if isinstance(item, ParsedItemEntry):
            return self._add_parsed_item_entry(item, order)

        if isinstance(item, ParsedMenuItemEntry):
            # Track item count before to detect if item was actually added
            items_before = len(order.items.items)
            result = self.item_adder_handler.add_menu_item(
                item.menu_item_name,
                item.quantity,
                order,
                item.toasted,
                item.bread,
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
                order.last_add_error = result  # Store error for _process_items
                summary = ""  # Don't add to summaries

            return order, summary

        elif _is_bagel_entry(item):
            # Build ExtractedModifiers from parsed entry fields
            extracted_mods = ExtractedModifiers()
            # For ParsedItemEntry, modifiers are combined in item.modifiers
            # Some parsed entries may have categorized lists (proteins, cheeses, toppings)
            if item.proteins:
                for p in item.proteins:
                    extracted_mods.add("protein", p)
            if item.cheeses:
                for c in item.cheeses:
                    extracted_mods.add("cheese", c)
            if item.toppings:
                for t in item.toppings:
                    extracted_mods.add("topping", t)
            # If using unified ParsedItemEntry, combined modifiers are in item.modifiers
            # Store them in toppings (they'll be recategorized by add_bagel)
            if not extracted_mods.has_modifiers():
                if hasattr(item, 'modifiers') and item.modifiers:
                    for m in item.modifiers:
                        extracted_mods.add("topping", m)
            if item.needs_cheese_clarification:
                extracted_mods.needs_clarification["cheese"] = True
            # Convert special_instructions string to list for ExtractedModifiers
            if item.special_instructions:
                extracted_mods.special_instructions = [item.special_instructions]

            # Use unified add_item() dispatcher (item_type from parsed item)
            # Note: _is_bagel_entry already verified item_type exists
            item_type = item.item_type
            result = self.item_adder_handler.add_item(
                item_type=item_type,
                order=order,
                quantity=item.quantity,
                bread=item.bread,
                toasted=item.toasted,
                scooped=item.scooped,
                spread=item.spread,
                spread_type=item.spread_type,
                extracted_modifiers=extracted_mods if extracted_mods.has_modifiers() or extracted_mods.has_special_instructions() or extracted_mods.needs_clarification.get("cheese") else None,
            )
            order = result.order
            # Build summary (data-driven display name from DB)
            type_display_name = menu_cache.get_item_type_display_name(item_type)
            item_desc = f"{item.bread} {type_display_name}" if item.bread else type_display_name
            summary = item_desc
            if item.toasted:
                summary += " toasted"
            if item.quantity > 1:
                summary = f"{item.quantity} {item_desc}s"
                if item.toasted:
                    summary += " toasted"
            return order, summary

        elif _is_coffee_entry(item):
            # Check if this is a modifier-only input (e.g., "2 vanilla syrups") that should
            # be added to the last beverage instead of creating a new coffee
            drink_type_lower = (item.drink_type or "").lower()
            has_modifiers = bool(item.syrups or item.sweeteners or item.milk or item.wants_syrup)
            # Check if drink type is a generic category reference (not a specific menu item)
            is_default_drink_type = bool(menu_cache.is_category_reference(drink_type_lower))

            # Check if original input contains a real beverage keyword from the database
            original_text_lower = (item.original_text or "").lower()
            # Get beverage names from database (menu items in beverage category + their aliases)
            beverage_names = menu_cache.get_menu_item_names_by_category("beverage")
            has_explicit_drink = any(name.lower() in original_text_lower for name in beverage_names)

            # If this is a modifier-only input (no explicit drink type), add to last beverage
            if has_modifiers and is_default_drink_type and not has_explicit_drink:
                active_items = order.items.get_active_items()
                if active_items:
                    last_item = active_items[-1]

                    # Add to sized_beverage MenuItemTask (has milk attribute)
                    if isinstance(last_item, MenuItemTask) and last_item.has_attribute("milk"):
                        modifier_summary_parts = []

                        # Add syrups using add_flavor_syrup() for proper normalization
                        for syrup in item.syrups:
                            existing_syrups = [s.get("slug") or s.get("flavor") for s in last_item.flavor_syrups]
                            if syrup.slug not in existing_syrups:
                                last_item.add_flavor_syrup(syrup.slug, syrup.quantity)
                                qty_str = f"{syrup.quantity} " if syrup.quantity > 1 else ""
                                modifier_summary_parts.append(f"{qty_str}{syrup.slug} syrup")

                        # Add sweeteners using add_sweetener() for proper normalization
                        for sweetener in item.sweeteners:
                            existing_sweeteners = [s.get("slug") for s in last_item.sweeteners]
                            if sweetener.slug not in existing_sweeteners:
                                last_item.add_sweetener(sweetener.slug, sweetener.quantity)
                                qty_str = f"{sweetener.quantity} " if sweetener.quantity > 1 else ""
                                modifier_summary_parts.append(f"{qty_str}{sweetener.slug}")

                        # Add milk
                        if item.milk and last_item.milk != item.milk:
                            last_item.milk = item.milk
                            modifier_summary_parts.append(f"{item.milk} milk")

                        if modifier_summary_parts:
                            logger.info("Added modifiers to existing coffee: %s", modifier_summary_parts)
                            summary = ", ".join(modifier_summary_parts) + " added"
                            return order, summary

                    # Add to MenuItemTask beverage (data-driven flow)
                    elif isinstance(last_item, MenuItemTask) and menu_cache.get_modifier_category(last_item.menu_item_type) == "beverage":
                        modifier_summary_parts = []

                        # Get existing selections or initialize empty list
                        existing_selections = last_item.attribute_values.get("milk_sweetener_syrup_selections", [])
                        existing_slugs_list = last_item.attribute_values.get("milk_sweetener_syrup", [])
                        existing_slugs = set(existing_slugs_list)

                        # Add syrups
                        for syrup in item.syrups:
                            syrup_slug = syrup.slug.lower().replace(" ", "_")
                            if syrup_slug not in existing_slugs:
                                existing_slugs.add(syrup_slug)
                                existing_selections.append({
                                    "slug": syrup_slug,
                                    "display_name": syrup.slug.title(),
                                    "price": 0.65,  # Default syrup price
                                    "quantity": syrup.quantity,
                                })
                                qty_str = f"{syrup.quantity} " if syrup.quantity > 1 else ""
                                modifier_summary_parts.append(f"{qty_str}{syrup.slug} syrup")

                        # Add sweeteners
                        for sweetener in item.sweeteners:
                            sweetener_slug = sweetener.slug.lower().replace(" ", "_")
                            if sweetener_slug not in existing_slugs:
                                existing_slugs.add(sweetener_slug)
                                existing_selections.append({
                                    "slug": sweetener_slug,
                                    "display_name": sweetener.slug.title(),
                                    "price": 0.0,  # Sweeteners are free
                                    "quantity": sweetener.quantity,
                                })
                                qty_str = f"{sweetener.quantity} " if sweetener.quantity > 1 else ""
                                modifier_summary_parts.append(f"{qty_str}{sweetener.slug}")

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

            # Check if this is an espresso-type drink (has shots attribute) - route to data-driven flow
            menu_lookup = self.item_adder_handler.menu_lookup if self.item_adder_handler else None
            drink_menu_item = menu_lookup.lookup_menu_item(drink_type_lower) if menu_lookup else None
            drink_item_type = drink_menu_item.get("item_type") if drink_menu_item else None
            is_espresso_type = drink_item_type and menu_cache.item_type_has_attribute(drink_item_type, "shots")

            if is_espresso_type and self.item_adder_handler and self.item_adder_handler.menu_item_handler:
                # Use the looked-up menu item for espresso-type drinks
                espresso_menu_item = drink_menu_item

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
                    # Look up price from pricing engine (data-driven: use item type from DB)
                    milk_price = 0.0
                    if pricing and drink_item_type:
                        milk_price = pricing.lookup_generic_modifier_price(milk_slug, drink_item_type, "milk") or 0.0
                    mss_selections.append({
                        "slug": milk_slug,
                        "display_name": item.milk.title(),
                        "price": milk_price,
                        "quantity": 1,
                    })
                    modifiers_upcharge += milk_price

                # Add sweeteners
                for sweetener in item.sweeteners:
                    sweetener_slug = sweetener.slug.lower().replace(" ", "_")
                    mss_slugs.append(sweetener_slug)
                    mss_selections.append({
                        "slug": sweetener_slug,
                        "display_name": sweetener.slug.title(),
                        "price": 0.0,  # Sweeteners are typically free
                        "quantity": sweetener.quantity,
                    })

                # Add syrups
                for syrup in item.syrups:
                    syrup_slug = syrup.slug.lower().replace(" ", "_")
                    mss_slugs.append(syrup_slug)
                    # Look up price from pricing engine (data-driven: use item type from DB)
                    syrup_price = 0.0
                    if pricing and drink_item_type:
                        syrup_price = pricing.lookup_generic_modifier_price(syrup_slug, drink_item_type, "syrup") or 0.65
                    mss_selections.append({
                        "slug": syrup_slug,
                        "display_name": syrup.slug.title(),
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

                    # Infer attributes from item name (data-driven)
                    if self.item_adder_handler:
                        self.item_adder_handler._infer_attributes_from_item_name(espresso_task)
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

            # Regular coffee/drink - use unified add_item() dispatcher
            # Extract first sweetener if present
            sweetener = item.sweeteners[0].slug if item.sweeteners else None
            sweetener_qty = item.sweeteners[0].quantity if item.sweeteners else 1

            # Extract first syrup if present
            flavor_syrup = item.syrups[0].slug if item.syrups else None
            syrup_qty = item.syrups[0].quantity if item.syrups else 1

            # Track item count before to detect if item was actually added
            # (disambiguation returns without adding to order)
            items_before = len(order.items.items)

            # Use item_type from parsed item (data-driven, verified by _is_coffee_entry)
            result = self.item_adder_handler.add_item(
                item_type=item.item_type,
                order=order,
                quantity=item.quantity,
                item_name=item.drink_type,
                size=item.size,
                milk=item.milk,
                sweetener=sweetener,
                sweetener_quantity=sweetener_qty,
                flavor_syrup=flavor_syrup,
                special_instructions=item.special_instructions,
                decaf=item.decaf,
                syrup_quantity=syrup_qty,
                wants_syrup=item.wants_syrup,
                cream_level=item.cream_level,
                extra_shots=item.extra_shots,
                original_input=item.original_text,
            )
            order = result.order
            items_after = len(order.items.items)

            # DEBUG: Log item counts to trace multi-item order issue
            logger.info("ADD COFFEE DEBUG: items_before=%d, items_after=%d, drink_type=%s, pending_field=%s",
                       items_before, items_after, item.drink_type, order.pending_field)

            # Only return summary if item was actually added
            # (disambiguation triggers pending_field without adding item)
            if items_after > items_before:
                summary = item.drink_type
                if item.size:
                    summary = f"{item.size} {summary}"
                # Note: temperature is now part of drink_type name (e.g., "Iced Latte")
                if item.quantity > 1:
                    summary = f"{item.quantity} {summary}s"
                return order, summary
            else:
                # Item wasn't added (disambiguation or error) - return empty summary
                return order, ""

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

    def _process_items(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """
        Process all items from parsed_items list (unified path for 1 or N items).

        This is the primary code path for adding items to the order. All parsing
        now populates parsed_items, making this the single unified processing path.

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
                    # Determine item type for config handler (data-driven from parsed entry)
                    if isinstance(parsed_item, ParsedMenuItemEntry):
                        item_type = "signature_item" if parsed_item.is_signature else "menu_item"
                        display_name = parsed_item.menu_item_name
                    elif isinstance(parsed_item, ParsedItemEntry) and parsed_item.item_type == "menu_item":
                        # New unified ParsedItemEntry with menu_item type
                        item_type = "signature_item" if parsed_item.is_signature else "menu_item"
                        display_name = parsed_item.item_name or summary
                    elif _is_bagel_entry(parsed_item):
                        # _is_bagel_entry already verified item_type exists
                        item_type = parsed_item.item_type
                        type_display = menu_cache.get_item_type_display_name(item_type)
                        display_name = f"{parsed_item.bread} {type_display}" if parsed_item.bread else type_display
                    elif _is_coffee_entry(parsed_item):
                        # _is_coffee_entry already verified item_type exists
                        item_type = parsed_item.item_type
                        display_name = parsed_item.drink_type or menu_cache.get_item_type_display_name(item_type)
                    else:
                        # For other entries, use actual item_type (required in ParsedItemEntry)
                        item_type = getattr(parsed_item, 'item_type', None) or "unknown"
                        display_name = summary
                    added_items.append((last_item.id, display_name, item_type))
                logger.info("Added item via parsed_items: %s (id=%s)", summary, last_item.id[:8] if last_item else "?")

        # Check if we're waiting for drink type selection (user said "drink" or partial term like "juice")
        # This must be checked BEFORE checking summaries because add_coffee sets pending_field
        # but _add_parsed_item still adds the generic term to summaries
        if order.pending_field == "drink_type" and self.item_adder_handler.menu_lookup:
            logger.info("Pending drink type selection - presenting drink options")

            # Check if we have filtered options (partial term like "juice") or need full menu
            if order.pending_item_options:
                # Use pre-filtered options from add_coffee
                all_drinks = order.pending_item_options
                logger.info("Using %d pre-filtered drink options", len(all_drinks))
            else:
                # Get full drink menu for generic "drink" request (data-driven: all beverage item types)
                items_by_type = self.item_adder_handler.menu_lookup.menu_data.get("items_by_type", {})
                all_drinks = []
                for item_type_slug, items in items_by_type.items():
                    if menu_cache.get_modifier_category(item_type_slug) == "beverage":
                        all_drinks.extend(items)

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
        if order.pending_field == "drink_selection" and order.pending_item_options:
            logger.info("Pending drink selection - presenting %d options", len(order.pending_item_options))

            # Build the clarification message from pending options
            # Format: numbered list showing each option
            option_list = []
            for i, item in enumerate(order.pending_item_options, 1):
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
        # - "bagel_handler": MenuItemTask with bagel config (bagels, sandwiches, omelette sides)
        # - "coffee_handler": MenuItemTask with size/milk attributes (coffee, latte, etc.)
        # - Individual items: MenuItemTask needing side_choice (no internal loop)

        bagel_handler_items: list[tuple[str, str, str, str]] = []  # (item_id, name, type, field)
        coffee_handler_items: list[tuple[str, str, str, str]] = []
        individual_items: list[tuple[str, str, str, str]] = []  # Items that don't share a handler loop

        for item in order.items.items:
            if item.status == TaskStatus.IN_PROGRESS:
                if isinstance(item, MenuItemTask):
                    # Items that need side choice first (e.g., omelettes with bagel or fruit salad)
                    # These don't share a handler loop - each must be queued individually
                    if item.requires_side_choice and item.side_choice is None:
                        individual_items.append((item.id, item.menu_item_name, "menu_item", "side_choice"))
                    # If item has a configurable side choice, check if it needs further config
                    # Uses data-driven approach: check for {side_choice}_choice field dynamically
                    elif item.side_choice:
                        choice_field = f"{item.side_choice}_choice"
                        specific_choice = getattr(item, choice_field, None)
                        # Check if side type has "toasted" attribute using data lookup
                        side_attrs = menu_cache.get_item_type_attributes(item.side_choice)
                        if hasattr(item, choice_field) and not specific_choice:
                            bagel_handler_items.append((item.id, item.menu_item_name, "menu_item", choice_field))
                        elif "toasted" in side_attrs and item.toasted is None:
                            bagel_handler_items.append((item.id, item.menu_item_name, "menu_item", "toasted"))
                        elif "spread" in side_attrs and item.spread is None:
                            bagel_handler_items.append((item.id, item.menu_item_name, "menu_item", "spread"))
                    # Check if this menu item contains a bagel (e.g., Classic BEC)
                    elif not item.requires_side_choice:
                        # DB-driven items use MenuItemConfigHandler
                        # They should NOT go through the bagel handler's hardcoded toasted question
                        # TODO: This list of item types should be data-driven (e.g., check if item type
                        # has is_configurable=True in DB, or has any ask_in_conversation attributes).
                        # For now, using a configurable item type check via database query.
                        item_attrs = menu_cache.get_item_type_attributes(item.menu_item_type) if item.menu_item_type else {}
                        has_configurable_attrs = any(
                            attr.get("ask_in_conversation", False) for attr in item_attrs.values()
                        )
                        if has_configurable_attrs:
                            individual_items.append((item.id, item.menu_item_name, "menu_item", "menu_item_config"))
                        elif item.has_attribute("size"):
                            # Items with size attribute use sized beverage config handler
                            # Note: temperature is now part of the menu item name (e.g., "Iced Latte")
                            if not item.menu_item_type:
                                raise MenuDataNotLoadedError(
                                    f"MenuItemTask '{item.menu_item_name}' has size attribute but no menu_item_type set. "
                                    f"Ensure menu_item_type is populated when creating items."
                                )
                            item_type_slug = item.menu_item_type
                            display_name = item.menu_item_name or menu_cache.get_item_type_display_name(item_type_slug)
                            if item.size is None:
                                coffee_handler_items.append((item.id, display_name, item_type_slug, "coffee_size"))
                            elif item.milk is None and not item.sweeteners and not item.flavor_syrups:
                                coffee_handler_items.append((item.id, display_name, item_type_slug, "coffee_modifiers"))
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
                # Note: Legacy BagelItemTask branch removed - all bagels are now MenuItemTask

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
        # Uses data-driven approach where possible
        if first_field == "side_choice":
            # TODO: Side options should come from database
            question = f"What would you like on the side with your {first_item_name}?"
        elif first_field == "toasted":
            # Check if this is an item with a configurable side choice
            menu_item = next((i for i in order.items.items if i.id == first_item_id), None)
            if isinstance(menu_item, MenuItemTask) and menu_item.side_choice:
                # Item with configurable side - ask about side being toasted
                choice_field = f"{menu_item.side_choice}_choice"
                specific_choice = getattr(menu_item, choice_field, None)
                if specific_choice:
                    side_desc = f"{specific_choice} {menu_item.side_choice}"
                else:
                    side_desc = menu_item.side_choice.replace("_", " ")
                question = f"Got it, {side_desc}! Would you like that toasted?"
            else:
                question = f"Got it! Would you like the {first_item_name} toasted?"
        elif first_field.endswith("_choice"):
            # Generic handling for side choice sub-selections (e.g., bagel_choice)
            # Extract the side type from the field name (e.g., "bagel" from "bagel_choice")
            side_type = first_field.replace("_choice", "")
            side_display = side_type.replace("_", " ")
            question = f"Got it! What kind of {side_display} would you like for the {first_item_name}?"
        elif first_field.endswith("_type"):
            # Generic handling for type selections (e.g., bagel_type)
            item_type = first_field.replace("_type", "")
            item_display = item_type.replace("_", " ")
            question = f"Got it! What kind of {item_display} would you like?"
        elif first_field == "spread":
            # Find the item to check if it's toasted
            item = next((i for i in order.items.items if i.id == first_item_id), None)
            if isinstance(item, MenuItemTask) and item.has_attribute("bread"):
                # Item with bread attribute
                toasted_desc = " toasted" if item.toasted else ""
                question = f"Got it, {first_item_name}{toasted_desc}! Would you like cream cheese or butter on that?"
            elif isinstance(item, MenuItemTask) and item.side_choice:
                # Item with configurable side
                choice_field = f"{item.side_choice}_choice"
                specific_choice = getattr(item, choice_field, None)
                if specific_choice:
                    side_desc = f"{specific_choice} {item.side_choice}"
                else:
                    side_desc = item.side_choice.replace("_", " ")
                toasted_desc = " toasted" if item.toasted else ""
                question = f"Got it, {side_desc}{toasted_desc}! Would you like butter or cream cheese on that?"
            else:
                question = f"Got it! Would you like cream cheese or butter on that?"
        elif first_field == "coffee_size":
            question = f"Got it! What size {first_item_name} would you like? Small or Large?"
        elif first_field == "coffee_modifiers":
            question = f"Got it, {first_item_name}! Any milk, sweetener, or syrup?"
        elif first_field == "espresso_modifiers":
            question = f"Got it, {first_item_name}! Any milk, sweetener, or syrup?"
        elif first_field == "cheese_choice":
            # Regular bagel with generic "cheese" - ask for type
            item = next((i for i in order.items.items if i.id == first_item_id), None)
            if isinstance(item, MenuItemTask) and item.has_attribute("bread"):
                # Bagel or other item with bread attribute
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

    def handle_drink_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user selecting from multiple drink options.

        Called when pending_field == "drink_selection" and user needs
        to choose from multiple matching drink items.
        """
        if not order.pending_item_options:
            order.clear_pending()
            return StateMachineResult(
                message="What would you like to order?",
                order=order,
            )

        user_lower = user_input.lower().strip()
        options = order.pending_item_options

        # Reject negative numbers or other invalid input early
        if user_lower.startswith('-') or user_lower.startswith('−'):
            option_list = []
            for i, item in enumerate(options, 1):
                name = item.get("name", "Unknown")
                price = item.get("base_price", 0)
                if price > 0:
                    option_list.append(f"{i}. {name} (${price:.2f})")
                else:
                    option_list.append(f"{i}. {name}")
            options_str = "\n".join(option_list)
            return StateMachineResult(
                message=f"Please choose a number from 1 to {len(options)}:\n{options_str}",
                order=order,
            )

        # Try to match by number (1, 2, 3, "first", "second", etc.)
        number_map = {
            "1": 0, "one": 0, "first": 0, "the first": 0, "number 1": 0, "number one": 0,
            "2": 1, "two": 1, "second": 1, "the second": 1, "number 2": 1, "number two": 1,
            "3": 2, "three": 2, "third": 2, "the third": 2, "number 3": 2, "number three": 2,
            "4": 3, "four": 3, "fourth": 3, "the fourth": 3, "number 4": 3, "number four": 3,
        }

        selected_item = None

        # Check for number/ordinal selection
        for key, idx in number_map.items():
            if key in user_lower:
                if idx < len(options):
                    selected_item = options[idx]
                    break
                else:
                    # User selected a number that's out of range - ask again
                    logger.info("DRINK SELECTION: User selected %s but only %d options available", key, len(options))
                    option_list = []
                    for i, item in enumerate(options, 1):
                        name = item.get("name", "Unknown")
                        price = item.get("base_price", 0)
                        if price > 0:
                            option_list.append(f"{i}. {name} (${price:.2f})")
                        else:
                            option_list.append(f"{i}. {name}")
                    options_str = "\n".join(option_list)
                    return StateMachineResult(
                        message=f"I only have {len(options)} options. Please choose:\n{options_str}",
                        order=order,
                    )

        # If not found by number, try to match by name
        if not selected_item:
            for option in options:
                option_name = option.get("name", "").lower()
                # Check if the option name is in user input or vice versa
                # But require minimum length to avoid false matches like "4" in "46 oz"
                if len(user_lower) > 3 and (option_name in user_lower or user_lower in option_name):
                    selected_item = option
                    break
                # Also try matching individual words
                for word in user_lower.split():
                    if len(word) > 3 and word in option_name:
                        selected_item = option
                        break

        if not selected_item:
            # Couldn't determine which one - ask again
            option_list = []
            for i, item in enumerate(options, 1):
                name = item.get("name", "Unknown")
                price = item.get("base_price", 0)
                if price > 0:
                    option_list.append(f"{i}. {name} (${price:.2f})")
                else:
                    option_list.append(f"{i}. {name}")
            options_str = "\n".join(option_list)
            return StateMachineResult(
                message=f"I didn't catch which one. Please choose:\n{options_str}",
                order=order,
            )

        # Found the selection - retrieve stored modifiers BEFORE clearing pending state
        selected_name = selected_item.get("name", "drink")
        selected_price = selected_item.get("base_price", 0)
        selected_item_type = selected_item.get("item_type")  # Data-driven item type from DB

        # Retrieve stored modifiers from disambiguation (e.g., "large oat milk latte")
        # Note: temperature is now part of the menu item name (e.g., "Iced Latte")
        stored_mods = order.pending_item_modifiers or {}
        stored_size = stored_mods.get("size")
        stored_milk = stored_mods.get("milk")
        stored_sweetener = stored_mods.get("sweetener")
        stored_sweetener_qty = stored_mods.get("sweetener_quantity", 1)
        stored_syrup = stored_mods.get("flavor_syrup")
        stored_syrup_qty = stored_mods.get("syrup_quantity", 1)
        stored_decaf = stored_mods.get("decaf")
        stored_cream = stored_mods.get("cream_level")
        stored_shots = stored_mods.get("extra_shots", 0)
        stored_instructions = stored_mods.get("special_instructions")
        stored_quantity = stored_mods.get("quantity", 1)

        order.pending_item_options = []
        order.clear_pending()

        logger.info(
            "DRINK SELECTION: User chose '%s' (price: $%.2f), applying stored modifiers: size=%s, milk=%s, syrup=%s",
            selected_name, selected_price, stored_size, stored_milk, stored_syrup
        )

        # Check if this drink should skip configuration
        is_configurable_coffee = any(
            bev in selected_name.lower() for bev in get_coffee_types()
        )
        should_skip_config = selected_item.get("skip_config", False) or is_soda_drink(selected_name)

        if should_skip_config or not is_configurable_coffee:
            # Add directly as complete (no size/iced questions)
            drink = MenuItemTask(
                menu_item_name=selected_name,
                menu_item_type=selected_item_type,
                unit_price=selected_price,
            )
            # Infer attributes from item name (data-driven)
            if self.item_adder_handler:
                self.item_adder_handler._infer_attributes_from_item_name(drink)
            drink.mark_complete()
            order.items.add_item(drink)

            return StateMachineResult(
                message=f"Got it, {selected_name}. Anything else?",
                order=order,
            )
        else:
            # Needs configuration - apply stored modifiers from original order
            # Build sweeteners list from stored modifier (standard format)
            sweeteners_list = []
            if stored_sweetener:
                sweeteners_list.append({
                    "slug": stored_sweetener,
                    "category": "sweetener",
                    "quantity": stored_sweetener_qty or 1,
                })

            # Build flavor syrups list from stored modifier (standard format)
            syrups_list = []
            if stored_syrup:
                syrups_list.append({
                    "slug": stored_syrup,
                    "category": "syrup",
                    "quantity": stored_syrup_qty or 1,
                })

            # Create drinks with stored modifiers
            for _ in range(stored_quantity):
                drink = MenuItemTask(
                    menu_item_name=selected_name,
                    menu_item_type=selected_item_type,
                    unit_price=selected_price,
                    special_instructions=stored_instructions,
                )
                # Set beverage properties via attribute_values
                if stored_size:
                    drink.size = stored_size
                if stored_decaf:
                    drink.decaf = stored_decaf
                if stored_milk:
                    drink.milk = stored_milk
                if stored_cream:
                    drink.cream_level = stored_cream
                if sweeteners_list:
                    drink.sweeteners = sweeteners_list.copy()
                if syrups_list:
                    drink.flavor_syrups = syrups_list.copy()
                if stored_shots:
                    drink.extra_shots = stored_shots

                # Infer attributes from item name (e.g., "Hot Coffee" -> temperature=hot)
                if self.item_adder_handler:
                    self.item_adder_handler._infer_attributes_from_item_name(drink)

                # Calculate price with modifiers
                if self.pricing:
                    self.pricing.recalculate_item_price(drink)

                # Check if fully configured (size specified)
                if drink.size is not None:
                    drink.mark_complete()
                else:
                    drink.mark_in_progress()

                order.items.add_item(drink)

            # If still needs configuration, ask the next question
            if any(d.status == TaskStatus.IN_PROGRESS for d in order.items.items if isinstance(d, MenuItemTask) and d.has_attribute("size")):
                if self.item_adder_handler and self.item_adder_handler._configure_next_incomplete_coffee:
                    return self.item_adder_handler._configure_next_incomplete_coffee(order)
                # Fallback
                return StateMachineResult(
                    message="What size would you like?",
                    order=order,
                )
            else:
                # Build summary for confirmation
                summary = drink.get_summary() if stored_quantity == 1 else f"{stored_quantity} {selected_name}s"
                return StateMachineResult(
                    message=f"Got it, {summary}. Anything else?",
                    order=order,
                )

    def handle_drink_type_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user specifying a drink type after asking for a generic 'drink'.

        This is called when the user said something like "drink" and we asked
        "What type of drink would you like?" and now they're responding.
        """
        user_lower = user_input.lower().strip()

        # Check for "what else" / "more options" pagination requests
        show_more_phrases = [
            "what else", "any other", "more options", "other options",
            "what other", "anything else", "show more", "more drinks",
            "other drinks", "different",
        ]
        if any(phrase in user_lower for phrase in show_more_phrases):
            pagination = order.get_menu_pagination()
            if pagination and pagination.get("category") == "drink":
                offset = pagination.get("offset", 0)
                # Get drink items again (data-driven: all beverage item types)
                menu_lookup = self.item_adder_handler.menu_lookup if self.item_adder_handler else None
                items_by_type = menu_lookup.menu_data.get("items_by_type", {}) if menu_lookup else {}
                all_drinks = []
                for item_type_slug, items in items_by_type.items():
                    if menu_cache.get_modifier_category(item_type_slug) == "beverage":
                        all_drinks.extend(items)

                if offset < len(all_drinks):
                    batch = all_drinks[offset:offset + DEFAULT_PAGINATION_SIZE]
                    remaining = len(all_drinks) - (offset + len(batch))

                    drink_names = [item.get("name", "Unknown") for item in batch]

                    if remaining > 0:
                        if len(drink_names) == 1:
                            drinks_str = drink_names[0]
                        else:
                            drinks_str = ", ".join(drink_names[:-1]) + f", {drink_names[-1]}"
                        message = f"We also have {drinks_str}, and more."
                        order.set_menu_pagination("drink", offset + DEFAULT_PAGINATION_SIZE, len(all_drinks))
                    else:
                        if len(drink_names) == 1:
                            drinks_str = drink_names[0]
                        elif len(drink_names) == 2:
                            drinks_str = f"{drink_names[0]} and {drink_names[1]}"
                        else:
                            drinks_str = ", ".join(drink_names[:-1]) + f", and {drink_names[-1]}"
                        message = f"We also have {drinks_str}. That's all our drinks."
                        order.clear_menu_pagination()

                    return StateMachineResult(message=message, order=order)
                else:
                    order.clear_menu_pagination()
                    return StateMachineResult(
                        message="That's all our drinks. Which would you like?",
                        order=order,
                    )
            # No pagination state - just re-ask
            return StateMachineResult(
                message="Which drink would you like?",
                order=order,
            )

        # FIRST: Check if we have pending drink options (from disambiguation like "latte" matching multiple items)
        # If so, try to match the user's input against those options before doing anything else
        if order.pending_item_options:
            options = order.pending_item_options
            selected_item = None

            # Try to match by number (1, 2, 3, "first", "second", etc.)
            number_map = {
                "1": 0, "one": 0, "first": 0, "the first": 0, "number 1": 0, "number one": 0,
                "2": 1, "two": 1, "second": 1, "the second": 1, "number 2": 1, "number two": 1,
                "3": 2, "three": 2, "third": 2, "the third": 2, "number 3": 2, "number three": 2,
                "4": 3, "four": 3, "fourth": 3, "the fourth": 3, "number 4": 3, "number four": 3,
            }

            for key, idx in number_map.items():
                if key in user_lower:
                    if idx < len(options):
                        selected_item = options[idx]
                        break

            # If not found by number, try to match by name
            if not selected_item:
                for option in options:
                    option_name = option.get("name", "").lower()
                    # Check if the option name is in user input or vice versa
                    if len(user_lower) >= 3 and (option_name in user_lower or user_lower in option_name):
                        selected_item = option
                        break
                    # Also try matching individual words
                    for word in user_lower.split():
                        if len(word) >= 3 and word in option_name:
                            selected_item = option
                            break
                    if selected_item:
                        break

            if selected_item:
                # Found the selection - retrieve stored modifiers before clearing pending state
                selected_name = selected_item.get("name", "drink")
                selected_price = selected_item.get("base_price", 0)
                selected_item_type = selected_item.get("item_type")  # Data-driven item type from DB

                # Retrieve stored modifiers from disambiguation (e.g., "large oat milk latte")
                stored_mods = order.pending_item_modifiers or {}
                stored_size = stored_mods.get("size")
                stored_milk = stored_mods.get("milk")
                stored_sweetener = stored_mods.get("sweetener")
                stored_sweetener_qty = stored_mods.get("sweetener_quantity", 1)
                stored_syrup = stored_mods.get("flavor_syrup")
                stored_syrup_qty = stored_mods.get("syrup_quantity", 1)
                stored_decaf = stored_mods.get("decaf")
                stored_cream = stored_mods.get("cream_level")
                stored_shots = stored_mods.get("extra_shots", 0)
                stored_instructions = stored_mods.get("special_instructions")
                stored_quantity = stored_mods.get("quantity", 1)

                logger.info(
                    "DRINK TYPE SELECTION: User chose '%s' (price: $%.2f), applying stored modifiers: size=%s, milk=%s, sweetener=%s(%d), syrup=%s",
                    selected_name, selected_price, stored_size, stored_milk, stored_sweetener, stored_sweetener_qty, stored_syrup
                )

                order.pending_item_options = []
                order.clear_pending()

                # Check if this drink should skip configuration
                is_configurable_coffee = any(
                    bev in selected_name.lower() for bev in get_coffee_types()
                )
                should_skip_config = selected_item.get("skip_config", False) or is_soda_drink(selected_name)

                if should_skip_config or not is_configurable_coffee:
                    # Add directly as complete (no size/iced questions)
                    drink = MenuItemTask(
                        menu_item_name=selected_name,
                        menu_item_type=selected_item_type,
                        unit_price=selected_price,
                    )
                    # Infer attributes from item name (data-driven)
                    if self.item_adder_handler:
                        self.item_adder_handler._infer_attributes_from_item_name(drink)
                    drink.mark_complete()
                    order.items.add_item(drink)

                    return StateMachineResult(
                        message=f"Got it, {selected_name}. Anything else?",
                        order=order,
                    )
                else:
                    # Needs configuration - apply stored modifiers from original order
                    # Build sweeteners list from stored modifier (standard format)
                    sweeteners_list = []
                    if stored_sweetener:
                        sweeteners_list.append({
                            "slug": stored_sweetener,
                            "category": "sweetener",
                            "quantity": stored_sweetener_qty or 1,
                        })

                    # Build flavor syrups list from stored modifier (standard format)
                    syrups_list = []
                    if stored_syrup:
                        syrups_list.append({
                            "slug": stored_syrup,
                            "category": "syrup",
                            "quantity": stored_syrup_qty or 1,
                        })

                    drink = MenuItemTask(
                        menu_item_name=selected_name,
                        menu_item_type=selected_item_type,
                        unit_price=selected_price,
                        special_instructions=stored_instructions,
                    )
                    # Set beverage properties via attribute_values
                    if stored_size:
                        drink.size = stored_size
                    if stored_milk:
                        drink.milk = stored_milk
                    if sweeteners_list:
                        drink.sweeteners = sweeteners_list
                    if syrups_list:
                        drink.flavor_syrups = syrups_list
                    if stored_decaf:
                        drink.decaf = stored_decaf
                    if stored_cream:
                        drink.cream_level = stored_cream
                    if stored_shots:
                        drink.extra_shots = stored_shots
                    # Infer attributes from item name (e.g., "Hot Coffee" -> temperature=hot)
                    if self.item_adder_handler:
                        self.item_adder_handler._infer_attributes_from_item_name(drink)
                    drink.mark_in_progress()
                    order.items.add_item(drink)
                    logger.info("DRINK TYPE SELECTION: Added drink '%s' (id=%s), total items=%d",
                                selected_name, drink.id[:8], len(order.items.items))

                    # Add multiple drinks if quantity > 1
                    for _ in range(stored_quantity - 1):
                        extra_drink = MenuItemTask(
                            menu_item_name=selected_name,
                            menu_item_type=selected_item_type,
                            unit_price=selected_price,
                            special_instructions=stored_instructions,
                        )
                        # Set beverage properties via attribute_values
                        if stored_size:
                            extra_drink.size = stored_size
                        if stored_milk:
                            extra_drink.milk = stored_milk
                        if sweeteners_list:
                            extra_drink.sweeteners = sweeteners_list.copy()
                        if syrups_list:
                            extra_drink.flavor_syrups = syrups_list.copy()
                        if stored_decaf:
                            extra_drink.decaf = stored_decaf
                        if stored_cream:
                            extra_drink.cream_level = stored_cream
                        if stored_shots:
                            extra_drink.extra_shots = stored_shots
                        # Infer attributes from item name (e.g., "Hot Coffee" -> temperature=hot)
                        if self.item_adder_handler:
                            self.item_adder_handler._infer_attributes_from_item_name(extra_drink)
                        extra_drink.mark_in_progress()
                        order.items.add_item(extra_drink)

                    # Use _get_next_question which checks for incomplete bagels first
                    # This ensures bagels are configured before coffees when both are ordered together
                    if self.item_adder_handler and self.item_adder_handler._get_next_question:
                        return self.item_adder_handler._get_next_question(order)
                    # Fallback
                    return StateMachineResult(
                        message="What size would you like?",
                        order=order,
                    )

        # Clear pending state and pagination
        order.clear_pending()
        order.clear_menu_pagination()

        # Try to parse the drink type from the user's input
        # Use the deterministic parser to extract coffee type
        from .parsers.deterministic import parse_open_input_deterministic
        parsed = parse_open_input_deterministic(user_input)

        # Check if they specified a coffee/drink via parsed_items
        if parsed and parsed.parsed_items:
            coffee_entry = next(
                (item for item in parsed.parsed_items if _is_coffee_entry(item)),
                None
            )
            if coffee_entry:
                # Extract sweetener/syrup info from the new format
                sweetener = coffee_entry.sweeteners[0].slug if coffee_entry.sweeteners else None
                sweetener_quantity = coffee_entry.sweeteners[0].quantity if coffee_entry.sweeteners else 1
                flavor_syrup = coffee_entry.syrups[0].slug if coffee_entry.syrups else None
                syrup_quantity = coffee_entry.syrups[0].quantity if coffee_entry.syrups else 1

                # Use unified add_item() dispatcher (data-driven: item_type from parsed item)
                return self.item_adder_handler.add_item(
                    item_type=coffee_entry.item_type,
                    order=order,
                    quantity=coffee_entry.quantity,
                    item_name=coffee_entry.drink_type,
                    size=coffee_entry.size,
                    milk=coffee_entry.milk,
                    sweetener=sweetener,
                    sweetener_quantity=sweetener_quantity,
                    flavor_syrup=flavor_syrup,
                    special_instructions=coffee_entry.special_instructions,
                    decaf=coffee_entry.decaf,
                    syrup_quantity=syrup_quantity,
                    cream_level=coffee_entry.cream_level,
                    original_input=user_input,
                )

        # Try direct matching with known drink types
        menu_lookup = self.item_adder_handler.menu_lookup if self.item_adder_handler else None
        for bev_type in get_coffee_types():
            if bev_type in user_lower:
                # Look up item type from menu (data-driven)
                bev_item_type = None
                if menu_lookup:
                    bev_item = menu_lookup.lookup_menu_item(bev_type)
                    bev_item_type = bev_item.get("item_type") if bev_item else None
                # Use unified add_item() dispatcher
                return self.item_adder_handler.add_item(
                    item_type=bev_item_type,
                    order=order,
                    quantity=1,
                    item_name=bev_type,
                    original_input=user_input,
                )

        # Try to look up in menu
        menu_lookup = self.item_adder_handler.menu_lookup if self.item_adder_handler else None
        if menu_lookup:
            matching_items = menu_lookup.lookup_menu_items(user_input)
            if matching_items:
                # Use the first match (data-driven: get item_type from DB)
                matched_item = matching_items[0]
                item_name = matched_item.get("name", user_input)
                matched_item_type = matched_item.get("item_type")
                # Use unified add_item() dispatcher
                return self.item_adder_handler.add_item(
                    item_type=matched_item_type,
                    order=order,
                    quantity=1,
                    item_name=item_name,
                    original_input=user_input,
                )

        # Couldn't parse - ask again
        logger.info("DRINK TYPE SELECTION: Couldn't parse '%s', asking again", user_input[:50])
        order.pending_field = "drink_type"
        order.phase = OrderPhase.CONFIGURING_ITEM.value
        return StateMachineResult(
            message="I didn't catch that. What type of drink would you like - coffee, latte, tea, or something else?",
            order=order,
        )
