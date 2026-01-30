"""
Taking Items Handler for Order State Machine.

This module handles the taking items phase of the order flow including
greeting, processing new item orders, and multi-item order coordination.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import re
from typing import Callable, TYPE_CHECKING

from orderbot.menu_data_cache import menu_cache
from orderbot.exceptions import MenuDataNotLoadedError
from orderbot.cache.base import singularize, get_singular_plural_variants

from .models import (
    OrderTask,
    MenuItemTask,
    TaskStatus,
)
from .pending_fields import PendingField
from .schemas.phases import OrderPhase
from .schemas import (
    StateMachineResult,
    OpenInputResponse,
    Selection,
    # ParsedItem types for multi-item handling
    ParsedItemEntry,
    ParsedItem,
)
from .parsers import parse_open_input, extract_attribute_values, extract_special_instructions_from_input
from .modifier_operations import (
    find_modifier_on_any_item,
    remove_modifier_from_item,
    find_default_ingredient_on_any_item,
    remove_default_ingredient_from_item,
)
from .item_cancellation_handler import (
    ItemCancellationHandler,
    extract_ordinal_reference,
    find_nth_item_of_type,
)
from .item_replacement_handler import ItemReplacementHandler
from .item_modification_handler import ItemModificationHandler
from .checkout_messages import got_it_anything_else
from .parsers.constants import ORDINAL_WORDS, ADD_MODIFIER_PATTERNS
from .parsers.deterministic.patterns import REPLACE_ITEM_PATTERN
from .parsers.quantity_utils import (
    extract_quantity_for_pattern,
    extract_leading_quantity,
    parse_make_it_n_quantity,
)
from .mixins import MenuDataMixin
from .utils.text import format_english_list
from .utils.constants import is_price_metadata_key
from .normalization import format_slug_for_display

if TYPE_CHECKING:
    from .handler_config import HandlerConfig
    from .context import OrderContext

logger = logging.getLogger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================

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
                items_text = format_english_list(display_names)
            return f"I can help you order {items_text} from our menu. Just tell me what you'd like!"
        else:
            return "I can help you order from our menu. Just tell me what you'd like!"
    except Exception:
        # Fallback if cache not loaded
        return "I can help you order from our menu. Just tell me what you'd like!"


def _get_modifier_patterns(category: str) -> set[str]:
    """Get all matching patterns for an ingredient category.

    Returns a flat set of all patterns that can match this category for input detection.
    Works for any ingredient category

    Args:
        category: The ingredient category

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

    Args:
        input_lower: Lowercase user input to match against
        category: The ingredient category

    Returns:
        Dict with {slug, name, pattern} if matched, None otherwise.
        - slug: Database identifier for storage
        - name: Display name for UI
        - pattern: The pattern that matched

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
        item_type_slug: The item type slug.
                       If None, returns empty set.

    Returns:
        Set of all modifier patterns (lowercase) for this item type.

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

    Args:
        input_lower: Lowercase user input
        pattern: The modifier pattern to look for quantity before

    Returns:
        Quantity (defaults to 1 if not found)
    """
    return extract_quantity_for_pattern(input_lower, pattern)


def _add_modifier_to_item(
    item: "MenuItemTask",
    slug: str,
    display_name: str,
    quantity: int = 1,
    category: str | None = None,
) -> bool:
    """Add a modifier to an item using the unified storage model.

    Uses the unified 'selections' list on MenuItemTask for all modifiers.
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
    # Get current selections (unified storage)
    current_selections = item.modifiers or []

    # Check if already present (by slug)
    existing_slugs = [m.get("slug") for m in current_selections]
    if slug in existing_slugs:
        return False

    # Build the selection entry
    selection_entry = {
        "slug": slug,
        "display_name": display_name,
        "quantity": quantity,
    }
    if category:
        selection_entry["category"] = category

    # Add to unified selections list
    current_selections.append(selection_entry)
    item.modifiers = current_selections

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


# =============================================================================
# Templatized Removal Pattern Matching (Data-Driven)
# =============================================================================
# These templates generate removal patterns dynamically from ingredient categories.
# No hardcoded patterns like "no milk", "without sugar" - all driven by database.

REMOVAL_TEMPLATES = [
    "no {}",
    "without {}",
    "remove {}",
    "remove the {}",
    "hold the {}",
]


def _match_category_removal_pattern(input_lower: str, item_type_slug: str) -> str | None:
    """Check if input matches a removal pattern for any modifier category.

    Uses templatized patterns ("no {}", "without {}", etc.) with category names
    from the database. No hardcoded category names.

    Args:
        input_lower: Lowercase user input to check
        item_type_slug: The item type to get modifier categories for

    Returns:
        Category slug if a removal pattern matches, None otherwise.

    Examples:
        >>> _match_category_removal_pattern("no milk", "sized_beverage")
        "milk"
        >>> _match_category_removal_pattern("without syrup", "sized_beverage")
        "syrup"
        >>> _match_category_removal_pattern("remove the sugar", "sized_beverage")
        "sweetener"
    """
    # Get scannable modifier categories for this item type (data-driven)
    categories = menu_cache.get_scannable_modifier_categories(item_type_slug)

    for category in categories:
        # Get category display name and slug
        display_name = menu_cache.get_ingredient_category_display_name(category)
        names_to_check = {category.lower(), display_name.lower()}

        # Also check singular forms if display name is plural
        if display_name.endswith("s") and len(display_name) > 2:
            names_to_check.add(display_name[:-1].lower())

        # Check each removal template with each name variant
        for template in REMOVAL_TEMPLATES:
            for name in names_to_check:
                pattern = template.format(name)
                if pattern in input_lower:
                    return category

    return None


def _remove_modifiers_by_category(
    item: "MenuItemTask",
    category: str,
) -> bool:
    """Remove all modifiers of a specific category from an item.

    Uses the unified selections list. Works for any item type and category.

    Args:
        item: The MenuItemTask to modify
        category: The category of modifiers to remove (e.g., "milk", "syrup")

    Returns:
        True if any modifiers were removed, False otherwise.
    """
    current_selections = item.modifiers or []
    if not current_selections:
        return False

    # Filter out selections of the specified category
    new_selections = [m for m in current_selections if m.get("category") != category]

    if len(new_selections) < len(current_selections):
        item.modifiers = new_selections
        logger.info(
            "Removed %d %s modifier(s) from %s",
            len(current_selections) - len(new_selections),
            category,
            item.menu_item_name or item.menu_item_type
        )
        return True

    return False


# =============================================================================
# ParsedItemEntry Processing Helpers (Data-Driven)
# =============================================================================

def _get_selections_from_parsed_item(item: ParsedItemEntry) -> list[Selection]:
    """Get selections from a ParsedItemEntry.

    Works for ALL item types - uses unified selections list.

    Args:
        item: The parsed item entry

    Returns:
        List of Selection objects from the item
    """
    return list(item.modifiers)


def _build_item_summary(item: ParsedItemEntry) -> str:
    """Build human-readable summary for a parsed item (data-driven).

    Returns uniform format: "{quantity}x {item_name}, {attr1}, {attr2}, ..."

    Args:
        item: The parsed item entry

    Returns:
        Summary string

    Examples:
        "Everything Bagel, toasted, cream cheese"
        "2x Latte, large, iced, oat milk"
    """
    # Use item_name if present, otherwise item_type display name
    if item.item_name:
        base = item.item_name
    else:
        base = menu_cache.get_item_type_display_name(item.item_type) or item.item_type

    # Add quantity prefix if more than 1
    if item.quantity > 1:
        base = f"{item.quantity}x {base}"

    # Collect attribute display values uniformly
    attr_displays = []
    for key, value in item.attribute_values.items():
        # Skip internal storage fields
        if is_price_metadata_key(key):
            continue

        if value is True:
            # Boolean - use key as display (e.g., "toasted")
            attr_displays.append(key)
        elif value is False or value is None:
            continue
        elif isinstance(value, list):
            # Multi-select - show all values
            for v in value:
                if isinstance(v, str):
                    attr_displays.append(v)
        else:
            # Single-select - show value
            attr_displays.append(str(value))

    # Add modifiers if present (selections converted to display names)
    if item.modifiers:
        for sel in item.modifiers:
            display = sel.display_name or sel.slug
            if sel.quantity > 1:
                display = f"{sel.quantity}x {display}"
            attr_displays.append(display)

    # Build final summary
    if attr_displays:
        return f"{base}, {', '.join(attr_displays)}"
    return base


def _has_any_selections(selections: list[Selection] | None) -> bool:
    """Check if selections list has any content worth passing.

    Args:
        selections: The list of selections

    Returns:
        True if there are any selections
    """
    return bool(selections)


class TakingItemsHandler(MenuDataMixin):
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

        # Extracted sub-handlers
        self.item_cancellation_handler = ItemCancellationHandler(pricing=config.pricing)
        self.item_replacement_handler = ItemReplacementHandler(pricing=config.pricing)
        self.item_modification_handler = ItemModificationHandler(
            pricing=config.pricing,
            item_adder_handler=item_adder_handler,
        )

        # Context set per-request
        self._returning_customer: dict | None = None
        self._set_repeat_info_callback: Callable[[bool, str | None], None] | None = None

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
        ctx: "OrderContext | None" = None,
        # Legacy kwargs for backward compatibility
        returning_customer: dict | None = None,
        set_repeat_info_callback: Callable[[bool, str | None], None] | None = None,
    ) -> None:
        """Set per-request context from unified OrderContext."""
        if ctx is not None:
            self._returning_customer = ctx.returning_customer
            self._set_repeat_info_callback = ctx.set_repeat_info_callback
        else:
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
        # Selections are already extracted in the parsed items during parsing
        extracted_selections: list[Selection] | None = None
        if parsed.parsed_items and parsed.parsed_items[0].modifiers:
            extracted_selections = list(parsed.parsed_items[0].modifiers)
            if extracted_selections:
                logger.info("Selections from greeting input: %s", extracted_selections)

        # Phase is derived from orchestrator, no need to set explicitly
        return self.handle_taking_items_with_parsed(parsed, order, extracted_selections, user_input)

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
                target_qty = parse_make_it_n_quantity(num_str)
                if target_qty:
                    active_items = order.items.get_active_items()
                    if active_items:
                        last_item = active_items[-1]
                        last_item_name = last_item.get_summary()
                        added_count = target_qty - 1

                        for _ in range(added_count):
                            order.items.add_item(last_item.duplicate())

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

        is_add_modifier_request = any(
            re.search(pattern, input_lower) for pattern in ADD_MODIFIER_PATTERNS
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

        # Selections are already extracted in the parsed items during parsing
        extracted_selections: list[Selection] | None = None
        if parsed.parsed_items and parsed.parsed_items[0].modifiers:
            extracted_selections = list(parsed.parsed_items[0].modifiers)
            if extracted_selections:
                logger.info("Selections from input: %s", extracted_selections)

        # Extract order-level special instructions from user input
        instructions_list = extract_special_instructions_from_input(user_input)
        if instructions_list:
            new_instructions = "; ".join(instructions_list)
            if order.special_instructions:
                order.special_instructions += f"; {new_instructions}"
            else:
                order.special_instructions = new_instructions
            logger.info("Order-level special instructions: %s", order.special_instructions)

        return self.handle_taking_items_with_parsed(parsed, order, extracted_selections, user_input)

    def handle_taking_items_with_parsed(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        extracted_selections: list[Selection] | None = None,
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
        result = self._handle_ingredient_search(parsed, order)
        if result:
            return result

        # Handle "add [modifier]" patterns that modify the last item
        result = self._handle_add_modifier_to_last_item(raw_user_input, order)
        if result:
            return result

        # Handle modification to an existing item in the cart
        result = self._handle_modify_existing_item(parsed, order, raw_user_input)
        if result:
            return result

        # Handle item replacement: "make it a coke instead", "change it to X", etc.
        result, replaced_item_name = self._handle_item_replacement(parsed, order, raw_user_input)
        if result:
            return result

        # Handle item/modifier cancellation: "cancel the coke", "remove bacon", etc.
        result = self._handle_item_cancellation(parsed, order)
        if result:
            return result

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
                    order.items.add_item(last_item.duplicate())

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
                order.pending_field = PendingField.DUPLICATE_SELECTION

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
                order.pending_field = PendingField.SAME_THING_CLARIFICATION

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
                    order.items.add_item(last_item.duplicate())
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
                    order.pending_field = PendingField.DUPLICATE_SELECTION
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

        if parsed.needs_category_clarification:
            return self.menu_inquiry_handler.handle_category_clarification(
                parsed.needs_category_clarification, order
            )

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
            return self.store_info_handler.handle_recommendation_inquiry(
                match_type=parsed.recommendation_match_type,
                order=order,
                item_type_slug=parsed.recommendation_item_type_slug,
                menu_item_ids=parsed.recommendation_menu_item_ids,
                search_term=parsed.recommendation_search_term,
            )

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
    # Extracted Handler Methods (refactored from handle_taking_items_with_parsed)
    # =========================================================================

    def _handle_item_cancellation(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle item/modifier cancellation - delegates to ItemCancellationHandler."""
        return self.item_cancellation_handler.handle_item_cancellation(parsed, order)

    def _handle_item_replacement(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        raw_user_input: str | None,
    ) -> tuple[StateMachineResult | None, str | None]:
        """Handle item replacement - delegates to ItemReplacementHandler."""
        return self.item_replacement_handler.handle_item_replacement(parsed, order, raw_user_input)

    def _handle_modify_existing_item(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        raw_user_input: str | None,
    ) -> StateMachineResult | None:
        """Handle modification to existing item - delegates to ItemModificationHandler."""
        return self.item_modification_handler.handle_modify_existing_item(parsed, order, raw_user_input)

    def _handle_add_modifier_to_last_item(
        self,
        raw_user_input: str | None,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle 'add [modifier]' patterns that modify the last item.

        Handles patterns like:
        - "add vanilla syrup", "add oat milk", "with caramel"
        - Pure modifier input (just "vanilla" when there's a coffee in cart)
        - Category-level modifier removal ("no milk", "without syrup")
        - Single_select attribute modifier updates

        Returns:
            StateMachineResult if handled, None otherwise.
        """
        if not raw_user_input:
            return None

        input_lower = raw_user_input.lower().strip()
        active_items = order.items.get_active_items()

        # Check if this looks like a modifier addition for the last item
        # Patterns: "add X", "with X", "can I get X", "I'd like X added"
        is_add_modifier_request = any(
            re.search(pattern, input_lower) for pattern in ADD_MODIFIER_PATTERNS
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

        # Check for category-level modifier removal using templatized patterns
        # e.g., "no milk", "without syrup", "remove the sweetener"
        # This is data-driven: patterns generated from database category names
        if active_items:
            last_item = active_items[-1]
            if isinstance(last_item, MenuItemTask) and last_item.menu_item_type:
                removed_category = _match_category_removal_pattern(input_lower, last_item.menu_item_type)
                if removed_category:
                    if _remove_modifiers_by_category(last_item, removed_category):
                        self.pricing.recalculate_item_price(last_item)
                        updated_summary = last_item.get_summary()
                        category_display = menu_cache.get_ingredient_category_display_name(removed_category)
                        return StateMachineResult(
                            message=f"Sure, I've removed the {category_display.lower()}. Your order is now {updated_summary}. Anything else?",
                            order=order,
                        )

        if is_add_modifier_request and active_items:
            # Check if input contains a modifier from a single_select attribute category
            # Data-driven: loop through ingredient categories and find single_select attributes
            for category in menu_cache.get_all_ingredient_categories():
                detected_modifier = None
                for modifier in sorted(menu_cache.get_ingredients(category), key=len, reverse=True):
                    if modifier in input_lower:
                        detected_modifier = modifier
                        break

                if detected_modifier:
                    # Find items that have a single_select attribute for this category
                    items_accepting_modifier = []
                    for item in active_items:
                        if not isinstance(item, MenuItemTask):
                            continue
                        attr_slug = menu_cache.get_attribute_for_category(item.menu_item_type, category)
                        if attr_slug:
                            input_type = menu_cache.get_attribute_input_type(item.menu_item_type, attr_slug)
                            if input_type == "single_select":
                                items_accepting_modifier.append((item, attr_slug))

                    if items_accepting_modifier:
                        target_item = None
                        target_attr = None

                        # Prefer item without value set
                        for item, attr_slug in reversed(items_accepting_modifier):
                            if item.get(attr_slug) is None:
                                target_item = item
                                target_attr = attr_slug
                                break

                        # If all items have values, use the most recent one
                        if target_item is None:
                            target_item, target_attr = items_accepting_modifier[-1]

                        # Normalize and set the value (REPLACE behavior for single_select)
                        normalized_modifier = menu_cache.normalize_modifier(detected_modifier)
                        old_value = target_item.get(target_attr)
                        target_item[target_attr] = normalized_modifier

                        # Recalculate price
                        self.pricing.recalculate_item_price(target_item)
                        updated_summary = target_item.get_summary()

                        category_display = menu_cache.get_ingredient_category_display_name(category)

                        if old_value:
                            logger.info("Add %s: changed from '%s' to '%s' on item", category, old_value, normalized_modifier)
                            return StateMachineResult(
                                message=f"Sure, I've changed the {category_display.lower()} to {normalized_modifier}. Your order is now {updated_summary}. Anything else?",
                                order=order,
                            )
                        else:
                            logger.info("Add %s: added '%s' to item", category, normalized_modifier)
                            return StateMachineResult(
                                message=f"Sure, I've added {normalized_modifier}. Your order is now {updated_summary}. Anything else?",
                                order=order,
                            )

        return None

    def _handle_ingredient_search(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle ingredient-based menu search.

        When user says "chicken" or "something with bacon", show matching items.

        Returns:
            StateMachineResult if handled, None otherwise.
        """
        if not parsed.ingredient_search_matches:
            return None

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

            # Store context so "yes" / "give me one" adds this item
            order.pending_suggested_item = item_name
            order.pending_field = PendingField.CONFIRM_SUGGESTED_ITEM
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
                items_list = format_english_list(item_names, conjunction="or")

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
        1. Gets selections from the parsed item
        2. Passes all attribute_values to add_item (receiver filters to valid attrs)
        3. Builds summary using item_name or item_type display name

        Returns tuple of (updated_order, item_summary_string, disambiguation_result).
        The third element is non-None when disambiguation is needed.
        """
        # 1. Get selections from parsed item (data-driven, works for all item types)
        selections = _get_selections_from_parsed_item(item)

        # 2. Track item count to detect if item was actually added
        #    (disambiguation returns without adding to order)
        items_before = len(order.items.items)

        # 3. Call add_item with all attribute_values as kwargs
        #    The receiver (_extract_pre_filled_attributes) filters to valid attributes
        #    Pass unavailable_selections so it's set BEFORE get_first_question() is called
        result = self.item_adder_handler.add_item(
            item_type=item.item_type,
            order=order,
            quantity=item.quantity,
            item_name=item.item_name,
            extracted_selections=selections if _has_any_selections(selections) else None,
            original_input=item.original_text,
            unavailable_selections=item.unavailable_selections if item.unavailable_selections else None,
            **item.attribute_values,  # Data-driven: pass all, receiver filters (backward compat)
        )
        order = result.order

        # 4. Check if disambiguation was triggered (message present, no item added)
        items_after = len(order.items.items)
        if result.message and items_after == items_before and order.pending_field:
            # Disambiguation result - return it to be handled by caller
            return order, "", result

        # 5. Build summary if item was added
        if items_after > items_before:
            # Note: unavailable_selections is now passed to add_item and set before
            # get_first_question() is called, so it's already on the MenuItemTask

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
            items_before_count = len(order.items.items)
            order, summary, disambiguation_result = self._add_parsed_item(parsed_item, order)

            # Check if disambiguation was triggered - return immediately
            if disambiguation_result:
                logger.info("Disambiguation triggered for item, returning result")
                # Before returning, queue any items already added that need configuration.
                # This ensures they're not forgotten when disambiguation resolves.
                # Example: "everything bagel and a latte" - bagel is added first,
                # then latte triggers disambiguation. Without this, bagel config is skipped.
                for item_id, display_name, item_type in added_items:
                    item = order.items.get_item_by_id(item_id)
                    if item and item.status == TaskStatus.IN_PROGRESS:
                        order.queue_item_for_config(item_id, item_type, item_name=display_name)
                        logger.info("Queued %s (%s) for config before disambiguation", display_name, item_id[:8])
                return disambiguation_result

            # Check if add failed (e.g., item not found on menu)
            if order.last_add_error is not None:
                # Return the error message instead of continuing
                error_result = order.last_add_error
                order.last_add_error = None  # Clear it
                return error_result

            if summary:
                summaries.append(summary)
                # Capture ALL newly added items (quantity>1 creates multiple MenuItemTasks)
                new_items = order.items.items[items_before_count:]
                for new_item in new_items:
                    added_items.append((new_item.id, new_item.get_display_name(), parsed_item.item_type))
                if new_items:
                    logger.info(
                        "Added item via parsed_items: %s (%d tasks, first id=%s)",
                        summary, len(new_items), new_items[0].id[:8],
                    )

        if not summaries:
            return None

        # Find items that need configuration (IN_PROGRESS status)
        # Data-driven: let MenuItemConfigHandler determine what to ask
        items_needing_config: list[tuple[str, str, str]] = []  # (item_id, display_name, item_type)
        for item_id, display_name, item_type in added_items:
            item = order.items.get_item_by_id(item_id)
            if item and item.status == TaskStatus.IN_PROGRESS:
                items_needing_config.append((item_id, display_name, item_type))

        logger.info("Items needing configuration: %d", len(items_needing_config))

        # If no items need configuration, return simple confirmation
        if not items_needing_config:
            items_str = format_english_list(summaries)
            return StateMachineResult(message=got_it_anything_else(items_str), order=order)

        # Queue items 2+ for later configuration
        order.multi_item_config_names = [name for _, name, _ in items_needing_config]
        for item_id, item_name, item_type in items_needing_config[1:]:
            order.queue_item_for_config(item_id, item_type, item_name=item_name)
            logger.info("Queued %s (%s) for config", item_name, item_id[:8])

        # Get first item and delegate question to MenuItemConfigHandler
        first_item_id, first_item_name, first_item_type = items_needing_config[0]
        first_item = order.items.get_item_by_id(first_item_id)

        if isinstance(first_item, MenuItemTask) and self.item_adder_handler and self.item_adder_handler.menu_item_handler:
            return self.item_adder_handler.menu_item_handler.get_first_question(first_item, order)

        # Fallback if handler not available
        order.pending_item_id = first_item_id
        order.set_phase(OrderPhase.CONFIGURING_ITEM)
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
            order.items.add_item(item_to_duplicate.duplicate())

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
                order.items.add_item(item.duplicate())
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
                order.items.add_item(last_item.duplicate())
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
                order.pending_field = PendingField.DUPLICATE_SELECTION
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
                order.items.add_item(item_to_duplicate.duplicate())
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
