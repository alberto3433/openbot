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

from orderbot.menu_data_cache import menu_cache
from orderbot.exceptions import MenuDataNotLoadedError

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
    ParsedItem,
)
from .parsers import parse_open_input, extract_modifiers_from_input
from .modifier_operations import (
    find_modifier_on_any_item,
    remove_modifier_from_item,
    find_default_ingredient_on_any_item,
    remove_default_ingredient_from_item,
)
from .parsers.constants import DEFAULT_PAGINATION_SIZE

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
# ParsedItem Type Checking Helpers (Data-Driven)
# =============================================================================
# These helpers check item type capabilities using database-driven attribute lookups.
# They do NOT check for specific item type slugs - they check what attributes an item has.

def _item_has_bread_attribute(item: "ParsedItem") -> bool:
    """Check if a ParsedItem's item_type has a bread attribute (data-driven)."""
    item_type = getattr(item, 'item_type', None)
    if not item_type:
        return False
    return menu_cache.item_type_has_attribute(item_type, "bread")


def _item_has_size_attribute(item: "ParsedItem") -> bool:
    """Check if a ParsedItem's item_type has a size attribute (data-driven)."""
    item_type = getattr(item, 'item_type', None)
    if not item_type:
        return False
    return menu_cache.item_type_has_attribute(item_type, "size")


def _get_bread_value(item: "ParsedItem") -> str | None:
    """Get the bread value from a ParsedItem (data-driven)."""
    return getattr(item, 'bread', None)


def _get_dynamic_help_text() -> str:
    """Generate help text dynamically from database item types.

    Returns a help message listing available item categories from the database
    instead of hardcoding specific items like 'bagels, coffee, sandwiches'.
    """
    try:
        item_types = menu_cache.get_all_item_type_slugs()
        # Get plural display names for user-friendly output
        display_names = []
        for slug in sorted(item_types):
            name = menu_cache.get_item_type_display_name(slug, plural=True)
            if name and name != slug:  # Only include if we have a proper display name
                display_names.append(name)

        if display_names:
            # Take first few for a concise message
            if len(display_names) > 3:
                items_text = ", ".join(display_names[:3]) + ", and more"
            else:
                items_text = ", ".join(display_names[:-1]) + f", and {display_names[-1]}" if len(display_names) > 1 else display_names[0]
            return f"I can help you order {items_text} from our menu. Just tell me what you'd like!"
        else:
            return "I can help you order from our menu. Just tell me what you'd like!"
    except Exception:
        # Fallback if cache not loaded
        return "I can help you order from our menu. Just tell me what you'd like!"


def _get_modifier_patterns(category: str) -> set[str]:
    """Get all matching patterns for an ingredient category.

    Returns a flat set of all patterns that can match this category for input detection.
    Works for any ingredient category (milk, syrup, sweetener, spread, protein, etc.).

    Args:
        category: The ingredient category (e.g., "syrup", "milk", "sweetener", "spread")

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


def _match_modifier(
    input_lower: str, category: str
) -> dict | None:
    """Match user input against an ingredient category and return details.

    Uses database slugs and display names for any ingredient category.
    Works for milk, syrup, sweetener, spread, protein, cheese, etc.

    Args:
        input_lower: Lowercase user input to match against
        category: The ingredient category (e.g., "syrup", "milk", "sweetener", "spread")

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


def _get_all_modifier_patterns_for_item(item_type_slug: str | None) -> set[str]:
    """Get all modifier patterns for an item type (data-driven).

    Returns combined patterns for all ingredient categories that the item type accepts.
    Used to detect if user input contains any modifier for this item type.

    Args:
        item_type_slug: The item type slug (e.g., "sized_beverage", "bagel").
                       If None, returns empty set.

    Returns:
        Set of all modifier patterns (lowercase) for this item type.

    Example:
        >>> _get_all_modifier_patterns_for_item("sized_beverage")
        {"oat", "almond", "vanilla", "sugar", ...}  # All milk/syrup/sweetener patterns
    """
    if not item_type_slug:
        return set()

    patterns = set()
    # Get scannable categories from database (data-driven)
    categories = menu_cache.get_scannable_modifier_categories(item_type_slug)
    for category in categories:
        patterns.update(_get_modifier_patterns(category))
        # Add the category name itself as a pattern
        patterns.add(category)
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


def _add_modifier_to_item(
    item: "MenuItemTask",
    slug: str,
    display_name: str,
    quantity: int = 1,
    category: str | None = None,
) -> bool:
    """Add a modifier to an item using the unified storage model.

    Uses the unified 'modifiers' list on MenuItemTask for all modifiers.
    Format: {"slug": ..., "category": ..., "quantity": ..., "display_name": ...}
    Works for any item type and modifier category.

    Args:
        item: The MenuItemTask to modify
        slug: Database slug for the modifier (e.g., "oat_milk", "bacon")
        display_name: Display name for the modifier (e.g., "Oat Milk", "Bacon")
        quantity: Quantity (default 1, used for countable modifiers)
        category: Optional category (e.g., "milk", "sweetener", "protein")

    Returns:
        True if modifier was added, False if already present
    """
    # Get current modifiers (unified storage)
    current_modifiers = item.modifiers or []

    # Check if already present (by slug)
    existing_slugs = [m.get("slug") for m in current_modifiers]
    if slug in existing_slugs:
        return False

    # Build the modifier entry
    modifier_entry = {
        "slug": slug,
        "display_name": display_name,
        "quantity": quantity,
    }
    if category:
        modifier_entry["category"] = category

    # Add to unified modifiers list
    current_modifiers.append(modifier_entry)
    item.modifiers = current_modifiers

    logger.info(
        "Added %s modifier: %s (qty=%d) to %s",
        category or "unknown",
        slug,
        quantity,
        item.menu_item_name or item.menu_item_type
    )
    return True


def _add_modifiers_from_input(
    item: "MenuItemTask",
    input_lower: str,
) -> bool:
    """Add all matching modifiers from user input to an item (data-driven).

    Scans input for modifiers based on the item type's accepted modifier categories
    (queried from database) and adds them using the unified storage model.

    Works for any item type - beverages get milk/syrup/sweetener scanned,
    other item types get their configured modifier categories scanned.

    Args:
        item: The MenuItemTask to modify
        input_lower: Lowercase user input to scan for modifiers

    Returns:
        True if any modifiers were added, False otherwise
    """
    made_change = False

    # Get scannable categories from database (data-driven)
    item_type = item.menu_item_type
    if not item_type:
        return False

    categories = menu_cache.get_scannable_modifier_categories(item_type)

    # Check each modifier category for this item type
    for category in categories:
        match = _match_modifier(input_lower, category)
        if match:
            # Extract quantity from input
            quantity = _extract_quantity_from_input(input_lower, match["pattern"])

            # Add to item using unified storage
            if _add_modifier_to_item(
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

    # Resolve synonyms to canonical names using unified resolver (data-driven)
    keyword_lower = item_type_keyword.lower()
    canonical_name, _ = menu_cache.resolve_alias(keyword_lower)

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
        # Check canonical name match (e.g., "coke" -> "Coca-Cola")
        elif canonical_name and canonical_name.lower() in item_name_lower:
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


# =============================================================================
# ParsedItemEntry Processing Helpers (Data-Driven)
# =============================================================================

def _build_extracted_modifiers(item: ParsedItemEntry) -> ExtractedModifiers:
    """Build ExtractedModifiers from ParsedItemEntry (data-driven).

    Works for ALL item types - categorizes modifiers using database lookup.
    Handles:
    - Plain modifiers (item.modifiers list)
    - Quantified modifiers (item.sweeteners, item.syrups)
    - Clarification flags (needs_cheese_clarification, wants_syrup)
    - Special instructions

    Args:
        item: The parsed item entry

    Returns:
        ExtractedModifiers with all modifiers categorized
    """
    extracted_mods = ExtractedModifiers()

    # 1. Categorize plain modifiers using database lookup
    for mod in item.modifiers:
        category = menu_cache.get_ingredient_category(mod)
        # Use category from DB, or "topping" as generic fallback
        extracted_mods.add(category or "topping", mod)

    # 2. Add quantified modifiers (sweeteners, syrups)
    for sw in item.sweeteners:
        extracted_mods.add("sweetener", sw.slug, sw.quantity)
    for sy in item.syrups:
        extracted_mods.add("syrup", sy.slug, sy.quantity)

    # 3. Handle clarification flags
    if item.needs_cheese_clarification:
        extracted_mods.needs_clarification["cheese"] = True
    if item.wants_syrup:
        extracted_mods.needs_clarification["syrup"] = True

    # 4. Handle special instructions
    if item.special_instructions:
        extracted_mods.special_instructions.append(item.special_instructions)

    return extracted_mods


def _build_item_summary(item: ParsedItemEntry) -> str:
    """Build human-readable summary for an item (data-driven).

    Uses item_name if present (e.g., "Iced Latte"), otherwise builds
    from attribute_values (e.g., bread type) and item_type display name.
    Handles quantity pluralization.

    Args:
        item: The parsed item entry

    Returns:
        Summary string like "Iced Latte" or "2 everything bagels"
    """
    # Use item_name if present (e.g., "Iced Latte", "Turkey Club")
    if item.item_name:
        base = item.item_name
    else:
        # Build from attribute_values and item_type display name
        type_display = menu_cache.get_item_type_display_name(item.item_type) or item.item_type
        # Include bread attribute if present (e.g., "everything bagel")
        bread = item.attribute_values.get("bread")
        if bread:
            base = f"{bread} {type_display}"
        else:
            base = type_display

    # Add quantity prefix if more than 1
    if item.quantity > 1:
        return f"{item.quantity} {base}s"
    return base


def _has_any_modifiers(extracted_mods: ExtractedModifiers) -> bool:
    """Check if ExtractedModifiers has any content worth passing.

    Args:
        extracted_mods: The extracted modifiers object

    Returns:
        True if there are modifiers, clarifications, or special instructions
    """
    return (
        extracted_mods.has_modifiers() or
        extracted_mods.has_special_instructions() or
        bool(extracted_mods.needs_clarification)
    )


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

        # Check if this is a pure modifier input for the last item (data-driven)
        # Get modifier patterns based on the last item's type
        is_pure_modifier_input = False
        has_item_modifier = False
        item_modifier_patterns: set[str] = set()

        if active_items:
            last_item = active_items[-1]
            if isinstance(last_item, MenuItemTask) and last_item.menu_item_type:
                # Get modifier patterns for this specific item type (data-driven)
                item_modifier_patterns = _get_all_modifier_patterns_for_item(last_item.menu_item_type)
                has_item_modifier = any(mod in input_lower for mod in item_modifier_patterns)

        logger.info("EARLY_MOD_DETECT: has_item_modifier=%s, active_items=%d", has_item_modifier, len(active_items))

        if has_item_modifier and active_items:
            last_item = active_items[-1]
            # Check if item accepts input modifiers (data-driven)
            accepts_modifiers = (
                isinstance(last_item, MenuItemTask) and
                last_item.menu_item_type and
                menu_cache.item_accepts_input_modifiers(last_item.menu_item_type)
            )
            logger.info("EARLY_MOD_DETECT: accepts_modifiers=%s", accepts_modifiers)
            if accepts_modifiers:
                # Check if input is ONLY a modifier (no other item keywords)
                # Use item keywords from database (menu item names + item type slugs)
                # Exclude modifier patterns from the check since "vanilla" is both
                # a modifier pattern AND might be an item keyword (e.g., "Vanilla Latte")
                item_keywords = menu_cache.get_item_keywords()
                # Filter out words that are also modifiers for this item type
                non_modifier_keywords = {kw for kw in item_keywords if kw not in item_modifier_patterns}
                has_other_item = any(kw in input_lower for kw in non_modifier_keywords)
                logger.info("EARLY_MOD_DETECT: has_other_item=%s", has_other_item)
                if not has_other_item:
                    is_pure_modifier_input = True
                    logger.info("EARLY_MOD_DETECT: Setting is_pure_modifier_input=True")

        # If it's an "add modifier" pattern OR pure modifier input, modify the last item
        if (is_add_modifier_request or is_pure_modifier_input) and has_item_modifier and active_items:
            last_item = active_items[-1]
            # Check if item accepts input modifiers (data-driven)
            accepts_modifiers = (
                isinstance(last_item, MenuItemTask) and
                last_item.menu_item_type and
                menu_cache.item_accepts_input_modifiers(last_item.menu_item_type)
            )
            if accepts_modifiers:
                made_change = _add_modifiers_from_input(last_item, input_lower)

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

            # Check if this is a pure modifier input for the last item (data-driven)
            # Get modifier patterns based on the last item's type
            is_pure_modifier_input = False
            has_item_modifier = False
            item_modifier_patterns: set[str] = set()

            if active_items:
                last_item_check = active_items[-1]
                if isinstance(last_item_check, MenuItemTask) and last_item_check.menu_item_type:
                    # Get modifier patterns for this specific item type (data-driven)
                    item_modifier_patterns = _get_all_modifier_patterns_for_item(last_item_check.menu_item_type)
                    has_item_modifier = any(mod in input_lower for mod in item_modifier_patterns)

            if has_item_modifier and active_items:
                last_item_check = active_items[-1]
                # Check if item accepts input modifiers (data-driven)
                accepts_modifiers = (
                    isinstance(last_item_check, MenuItemTask) and
                    last_item_check.menu_item_type and
                    menu_cache.item_accepts_input_modifiers(last_item_check.menu_item_type)
                )
                if accepts_modifiers:
                    # Check if input is ONLY a modifier (no other item keywords)
                    # Use item keywords from database (menu item names + item type slugs)
                    # Exclude modifier patterns from the check since "vanilla" is both
                    # a modifier pattern AND might be an item keyword (e.g., "Vanilla Latte")
                    item_keywords = menu_cache.get_item_keywords()
                    non_modifier_keywords = {kw for kw in item_keywords if kw not in item_modifier_patterns}
                    has_other_item = any(kw in input_lower for kw in non_modifier_keywords)
                    if not has_other_item:
                        is_pure_modifier_input = True

            # If it's an "add modifier" pattern OR pure modifier input, modify the last item
            if (is_add_modifier_request or is_pure_modifier_input) and has_item_modifier and active_items:
                last_item = active_items[-1]
                # Check if item accepts input modifiers (data-driven)
                accepts_modifiers = (
                    isinstance(last_item, MenuItemTask) and
                    last_item.menu_item_type and
                    menu_cache.item_accepts_input_modifiers(last_item.menu_item_type)
                )
                if accepts_modifiers:
                    made_change = _add_modifiers_from_input(last_item, input_lower)

                    if made_change:
                        self.pricing.recalculate_item_price(last_item)
                        updated_summary = last_item.get_summary()
                        return StateMachineResult(
                            message=f"Sure, I've added that to your {updated_summary}. Anything else?",
                            order=order,
                        )

            # Handle "add [spread]" for items that accept spreads - e.g., "add scallion cream cheese"
            # This should modify an existing item, not add a new "Scallion Cream Cheese Sandwich"
            if is_add_modifier_request and active_items:
                # Check if input contains a spread pattern (longer matches first)
                # Data-driven: get spreads from database ingredient category
                detected_spread = None
                for spread in sorted(menu_cache.get_ingredients("spread"), key=len, reverse=True):
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
                        if item.attribute_values.get("spread") is None:
                            target_item = item
                            break

                    # If all items have spreads, use the most recent one
                    if target_item is None and items_accepting_spread:
                        target_item = items_accepting_spread[-1]

                    if target_item:
                        # Normalize the spread name
                        normalized_spread = menu_cache.normalize_modifier(detected_spread)
                        old_spread = target_item.attribute_values.get("spread")

                        # Set the spread on the item
                        target_item.attribute_values["spread"] = normalized_spread

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
                    item_bagel_type = (item.attribute_values.get("bread") or "").lower()
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
                    target_item.attribute_values["spread"] = parsed.modify_new_spread
                if parsed.modify_new_spread_type:
                    target_item.attribute_values["spread_type"] = parsed.modify_new_spread_type

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
                        target_attrs = target_item.attribute_values
                        existing_protein = target_attrs.get("extra_protein")
                        existing_toppings = target_attrs.get("toppings") or []
                        if category == "protein":
                            if not existing_protein:
                                target_attrs["extra_protein"] = modifier  # Store full qualified modifier
                            else:
                                # Already have a protein, add to toppings
                                if modifier not in existing_toppings:
                                    if not target_attrs.get("toppings"):
                                        target_attrs["toppings"] = []
                                    target_attrs["toppings"].append(modifier)
                        else:
                            # All other modifiers (cheese, topping, unknown) go to toppings
                            if modifier not in existing_toppings:
                                if not target_attrs.get("toppings"):
                                    target_attrs["toppings"] = []
                                target_attrs["toppings"].append(modifier)
                        logger.info("MODIFY ADD: Added '%s' to '%s'", modifier, target_attrs.get("bread"))

                # Recalculate price
                self.pricing.recalculate_item_price(target_item)

                updated_summary = target_item.get_summary()
                logger.info(
                    "MODIFY EXISTING: Updated '%s' with spread=%s, spread_type=%s, add_modifiers=%s",
                    target_item.attribute_values.get("bread"), parsed.modify_new_spread, parsed.modify_new_spread_type,
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
                     if isinstance(item, ParsedItemEntry) and item.item_type == "menu_item"
                         and item.item_name and "cream cheese sandwich" in item.item_name.lower()),
                    None
                )
                cream_cheese_name = cream_cheese_menu_item.item_name if cream_cheese_menu_item else None
                if has_new_items and cream_cheese_menu_item and cream_cheese_name and isinstance(last_item, MenuItemTask) and last_item.has_attribute("spread"):
                    # Extract the spread name from the menu item name
                    # "Blueberry Cream Cheese Sandwich" -> "blueberry cream cheese"
                    spread_name = cream_cheese_name.lower().replace(" sandwich", "")
                    last_attr = last_item.attribute_values
                    old_spread = last_attr.get("spread") or "none"
                    last_attr["spread"] = spread_name
                    logger.info("Replacement: interpreted '%s' as spread change from '%s' to '%s'",
                               cream_cheese_name, old_spread, spread_name)

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
                     if _item_has_bread_attribute(item) and _get_bread_value(item)),
                    None
                )
                if has_new_items and bagel_entry and isinstance(last_item, MenuItemTask) and last_item.has_attribute("bread"):
                    bagel_entry_bread = _get_bread_value(bagel_entry)
                    last_attr = last_item.attribute_values
                    old_type = last_attr.get("bread") or "plain"
                    last_attr["bread"] = bagel_entry_bread
                    logger.info("Replacement: changed bagel type from '%s' to '%s', preserving modifiers",
                               old_type, bagel_entry_bread)

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
                        last_attr = last_item.attribute_values

                        # Update protein - replace existing
                        if proteins:
                            last_attr["extra_protein"] = proteins[0]
                            # Additional proteins go to toppings (replace existing toppings)
                            last_attr["toppings"] = list(proteins[1:])
                        else:
                            # Clear protein if not in new modifiers
                            last_attr["extra_protein"] = None
                            last_attr["toppings"] = []

                        # Add cheeses and toppings to item.toppings
                        last_attr["toppings"].extend(cheeses)
                        last_attr["toppings"].extend(toppings)

                        # Update spread if specified
                        if spreads:
                            last_attr["spread"] = spreads[0]
                        else:
                            last_attr["spread"] = "none"

                        # Recalculate price with new modifiers
                        self.pricing.recalculate_item_price(last_item)

                        # Return confirmation with updated item
                        updated_summary = last_item.get_summary()
                        return StateMachineResult(
                            message=f"Sure, I've changed that to {updated_summary}. Anything else?",
                            order=order,
                        )
                    else:
                        # Check if user is changing the spread
                        # e.g., "make it blueberry cream cheese"
                        input_lower = raw_user_input.lower()

                        # Check for spread changes (longer matches before shorter)
                        # Data-driven: get spreads from database ingredient category
                        new_spread = None
                        for spread in sorted(menu_cache.get_ingredients("spread"), key=len, reverse=True):
                            if spread in input_lower:
                                # Normalize the spread name
                                new_spread = menu_cache.normalize_modifier(spread)
                                break

                        if new_spread:
                            last_attr = last_item.attribute_values
                            old_spread = last_attr.get("spread") or "none"
                            last_attr["spread"] = new_spread
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

                    last_attr = last_item.attribute_values
                    if new_size and new_size != last_attr.get("size"):
                        # Get default size from DB for logging
                        default_size = next(
                            (opt["slug"] for opt in size_options if opt.get("is_default")),
                            size_options[0]["slug"] if size_options else "small"
                        )
                        old_size = last_attr.get("size") or default_size
                        last_attr["size"] = new_size
                        logger.info("Replacement: changed coffee size from '%s' to '%s'", old_size, new_size)
                        made_change = True

                    # Note: temperature (hot/iced) is now part of the menu item name itself
                    # (e.g., "Iced Latte" vs "Hot Latte"). To change temperature, user
                    # would need to order a different menu item.

                    # Check for decaf changes
                    if "decaf" in input_lower:
                        if not last_attr.get("decaf"):
                            last_attr["decaf"] = True
                            logger.info("Replacement: changed coffee to decaf")
                            made_change = True
                    elif "regular" in input_lower and last_attr.get("decaf"):
                        # "make it regular" means not decaf
                        last_attr["decaf"] = None
                        logger.info("Replacement: changed coffee to regular (not decaf)")
                        made_change = True

                    # Check for milk changes using generic matcher
                    milk_match = _match_modifier(input_lower, "milk")
                    # Also check for "no milk" / "black" patterns
                    if "no milk" in input_lower or "black" in input_lower:
                        milk_match = {"slug": "none", "name": "None", "pattern": "no milk"}

                    if milk_match:
                        new_milk_slug = milk_match["slug"]
                        # Use unified storage model
                        if _add_modifier_to_item(
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
                    syrup_match = _match_modifier(input_lower, "syrup")
                    if syrup_match:
                        quantity = _extract_quantity_from_input(input_lower, syrup_match["pattern"])
                        if _add_modifier_to_item(
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

                # Resolve aliases to canonical names using unified resolver (data-driven)
                resolved_name, _ = menu_cache.resolve_alias(singular_desc)
                canonical_name_lower = resolved_name.lower() if resolved_name else None

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
            # Generate help text dynamically from database item types
            help_text = _get_dynamic_help_text()
            return StateMachineResult(
                message=help_text,
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

    def _add_parsed_item_entry(
        self, item: ParsedItemEntry, order: OrderTask
    ) -> tuple[OrderTask, str, StateMachineResult | None]:
        """
        Handle ParsedItemEntry using unified data-driven approach.

        This method works for ALL item types without branching on specific
        item_type slugs. It:
        1. Builds ExtractedModifiers from all modifier sources (data-driven)
        2. Passes all attribute_values to add_item (receiver filters to valid attrs)
        3. Builds summary using item_name or item_type display name

        Returns tuple of (updated_order, item_summary_string, disambiguation_result).
        The third element is non-None when disambiguation is needed.
        """
        # 1. Build modifiers from all sources (data-driven, works for all item types)
        extracted_mods = _build_extracted_modifiers(item)

        # 2. Track item count to detect if item was actually added
        #    (disambiguation returns without adding to order)
        items_before = len(order.items.items)

        # 3. Call add_item with all attribute_values as kwargs
        #    The receiver (_extract_pre_filled_attributes) filters to valid attributes
        result = self.item_adder_handler.add_item(
            item_type=item.item_type,
            order=order,
            quantity=item.quantity,
            item_name=item.item_name,
            extracted_modifiers=extracted_mods if _has_any_modifiers(extracted_mods) else None,
            original_input=item.original_text,
            **item.attribute_values,  # Data-driven: pass all, receiver filters
        )
        order = result.order

        # 4. Check if disambiguation was triggered (message present, no item added)
        items_after = len(order.items.items)
        if result.message and items_after == items_before and order.pending_field:
            # Disambiguation result - return it to be handled by caller
            return order, "", result

        # 5. Build summary if item was added
        if items_after > items_before:
            summary = _build_item_summary(item)
            return order, summary, None

        # Item wasn't added (error case) - return empty summary
        return order, "", None

    def _add_parsed_item(
        self, item: ParsedItem, order: OrderTask
    ) -> tuple[OrderTask, str, StateMachineResult | None]:
        """
        Dispatch a parsed item to the appropriate handler.

        Returns tuple of (updated_order, item_summary_string, disambiguation_result).
        The third element is non-None when disambiguation is needed.
        """
        # Handle unified ParsedItemEntry type (data-driven)
        if isinstance(item, ParsedItemEntry):
            return self._add_parsed_item_entry(item, order)

        return order, "", None

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
            order, summary, disambiguation_result = self._add_parsed_item(parsed_item, order)

            # Check if disambiguation was triggered - return immediately
            if disambiguation_result:
                logger.info("Disambiguation triggered for item, returning result")
                return disambiguation_result

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
                    # Data-driven: use summary from _build_item_summary, item_type from parsed entry
                    display_name = summary
                    item_type = parsed_item.item_type
                    added_items.append((last_item.id, display_name, item_type))
                logger.info("Added item via parsed_items: %s (id=%s)", summary, last_item.id[:8] if last_item else "?")

        if not summaries:
            return None

        # Find items that need configuration (IN_PROGRESS status)
        # Data-driven: let MenuItemConfigHandler determine what to ask
        items_needing_config: list[tuple[str, str, str]] = []  # (item_id, display_name, item_type)
        for item_id, display_name, item_type in added_items:
            item = next((i for i in order.items.items if i.id == item_id), None)
            if item and item.status == TaskStatus.IN_PROGRESS:
                items_needing_config.append((item_id, display_name, item_type))

        logger.info("Items needing configuration: %d", len(items_needing_config))

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

        # Queue items 2+ for later configuration
        order.multi_item_config_names = [name for _, name, _ in items_needing_config]
        for item_id, item_name, item_type in items_needing_config[1:]:
            order.queue_item_for_config(item_id, item_type, item_name=item_name)
            logger.info("Queued %s (%s) for config", item_name, item_id[:8])

        # Get first item and delegate question to MenuItemConfigHandler
        first_item_id, first_item_name, first_item_type = items_needing_config[0]
        first_item = next((i for i in order.items.items if i.id == first_item_id), None)

        if isinstance(first_item, MenuItemTask) and self.item_adder_handler and self.item_adder_handler.menu_item_handler:
            return self.item_adder_handler.menu_item_handler.get_first_question(first_item, order)

        # Fallback if handler not available
        order.pending_item_id = first_item_id
        order.phase = OrderPhase.CONFIGURING_ITEM.value
        return StateMachineResult(
            message=f"Got it, {first_item_name}! Any preferences?",
            order=order,
        )

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
        # First, normalize common aliases using unified resolver (data-driven)
        resolved_name, _ = menu_cache.resolve_alias(text)
        normalized_text = (resolved_name or text).lower()

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

        # Check for affirmative response using patterns from database
        affirmative_patterns = menu_cache.get_response_patterns("affirmative")
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

        # Check if this drink should skip configuration (data-driven)
        # An item type needs configuration if it has attributes with ask_in_conversation=True
        needs_config = (
            selected_item_type
            and menu_cache.item_type_needs_configuration(selected_item_type)
            and not selected_item.get("skip_config", False)
        )

        if not needs_config:
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
                drink_attr = drink.attribute_values
                drink_modifiers = drink.modifiers or []
                if stored_size:
                    drink_attr["size"] = stored_size
                if stored_decaf:
                    drink_attr["decaf"] = stored_decaf
                if stored_milk:
                    drink_attr["milk"] = stored_milk
                if stored_cream:
                    drink_attr["cream_level"] = stored_cream
                if sweeteners_list:
                    for sw in sweeteners_list:
                        drink_modifiers.append(sw.copy())
                if syrups_list:
                    for sy in syrups_list:
                        drink_modifiers.append(sy.copy())
                if stored_shots:
                    drink_attr["extra_shots"] = stored_shots
                drink.modifiers = drink_modifiers

                # Infer attributes from item name (e.g., "Hot Coffee" -> temperature=hot)
                if self.item_adder_handler:
                    self.item_adder_handler._infer_attributes_from_item_name(drink)

                # Calculate price with modifiers
                if self.pricing:
                    self.pricing.recalculate_item_price(drink)

                # Check if fully configured (size specified)
                if drink_attr.get("size") is not None:
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

                # Check if this drink should skip configuration (data-driven)
                # An item type needs configuration if it has attributes with ask_in_conversation=True
                needs_config = (
                    selected_item_type
                    and menu_cache.item_type_needs_configuration(selected_item_type)
                    and not selected_item.get("skip_config", False)
                )

                if not needs_config:
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
                    drink_attr = drink.attribute_values
                    drink_modifiers = drink.modifiers or []
                    if stored_size:
                        drink_attr["size"] = stored_size
                    if stored_milk:
                        drink_attr["milk"] = stored_milk
                    if sweeteners_list:
                        drink_modifiers.extend(sweeteners_list)
                    if syrups_list:
                        drink_modifiers.extend(syrups_list)
                    if stored_decaf:
                        drink_attr["decaf"] = stored_decaf
                    if stored_cream:
                        drink_attr["cream_level"] = stored_cream
                    if stored_shots:
                        drink_attr["extra_shots"] = stored_shots
                    drink.modifiers = drink_modifiers
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
                        extra_attr = extra_drink.attribute_values
                        extra_modifiers = extra_drink.modifiers or []
                        if stored_size:
                            extra_attr["size"] = stored_size
                        if stored_milk:
                            extra_attr["milk"] = stored_milk
                        if sweeteners_list:
                            extra_modifiers.extend([s.copy() for s in sweeteners_list])
                        if syrups_list:
                            extra_modifiers.extend([s.copy() for s in syrups_list])
                        if stored_decaf:
                            extra_attr["decaf"] = stored_decaf
                        if stored_cream:
                            extra_attr["cream_level"] = stored_cream
                        if stored_shots:
                            extra_attr["extra_shots"] = stored_shots
                        extra_drink.modifiers = extra_modifiers
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
                (item for item in parsed.parsed_items if _item_has_size_attribute(item)),
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

        # Try to look up in menu (data-driven - no hardcoded beverage types)
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
