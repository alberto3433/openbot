"""
Modifier Input Handler Module.

Handles modifier detection and addition from raw user input.
Supports data-driven modifier patterns for any item type.

Extracted from taking_items_handler.py for better separation of concerns.
"""

import logging
import re
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache
from .parsers.constants import ADD_MODIFIER_PATTERNS
from .parsers.quantity_utils import extract_additive_quantity, MAX_MODIFIER_QUANTITY
from .handler_utils import (
    is_configurable_menu_item,
    get_last_item,
    recalculate_and_summarize,
)
from .schemas import StateMachineResult
from .utils.text import find_first_word_boundary_match
from .modifier_resolver import match_pattern_in_input
from .checkout_messages import (
    sure_added_to_anything_else,
    sure_removed_anything_else,
    sure_changed_anything_else,
    item_not_customizable,
    modifier_not_available_for_item,
)
from .modifier_removal import (
    REMOVAL_TEMPLATES,
    match_category_removal_pattern,
    remove_modifiers_by_category,
)

if TYPE_CHECKING:
    from .models import MenuItemTask
    from .pricing import PricingEngine
    from .models import OrderTask

logger = logging.getLogger(__name__)

__all__ = [
    "get_modifier_patterns",
    "match_modifier",
    "get_all_modifier_patterns_for_item",
    "add_modifier_to_item",
    "add_modifiers_from_input",
    "REMOVAL_TEMPLATES",
    "match_category_removal_pattern",
    "remove_modifiers_by_category",
    "ModifierInputHandler",
]


# =============================================================================
# Module-Level Helper Functions
# =============================================================================

def get_modifier_patterns(category: str) -> set[str]:
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


def match_modifier(
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
            # Use word-boundary matching to avoid false positives
            # e.g., "egg" should not match "veggie" (v-egg-ie)
            if match_pattern_in_input(pattern, input_lower):
                return {
                    "slug": detail["slug"],
                    "name": detail["name"],
                    "pattern": pattern,
                }
    return None


def get_all_modifier_patterns_for_item(item_type_slug: str | None) -> set[str]:
    """Get all modifier patterns for an item type (data-driven).

    Returns combined patterns for all ingredient categories that the item type accepts,
    plus patterns from global attribute options (e.g., "shot" from espresso_shots).
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
        patterns.update(get_modifier_patterns(category))
        # Add the category name itself as a pattern
        patterns.add(category)

    # Also include patterns from global attribute options
    # This handles attributes like espresso_shots that have options (shot)
    # which users may want to add after initial configuration
    attrs = menu_cache.get_item_type_attributes(item_type_slug)
    for attr in attrs.values():
        options = attr.get("options", [])
        for opt in options:
            # Add both slug and display_name as patterns
            if opt.get("slug"):
                patterns.add(opt["slug"].lower().replace("_", " "))
            if opt.get("display_name"):
                patterns.add(opt["display_name"].lower())

    return patterns


def add_modifier_to_item(
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
    current_selections = item.selections or []

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
    item.selections = current_selections

    logger.info(
        "Added %s modifier: %s (qty=%d) to %s",
        category or "unknown",
        slug,
        quantity,
        item.menu_item_name or item.menu_item_type
    )
    return True


def add_modifiers_from_input(
    item: "MenuItemTask",
    input_lower: str,
) -> bool:
    """Add all matching modifiers from user input to an item (data-driven).

    Scans input for modifiers based on the item type's accepted modifier categories
    (queried from database) and global attribute options, adding them using the
    unified storage model.

    Works for any item type - beverages get milk/syrup/sweetener scanned,
    other item types get their configured modifier categories scanned.
    Also handles global attribute options like espresso_shots.

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

    # Skip non-configurable items (handled at handler level with proper message)
    if not menu_cache.is_item_type_configurable(item_type):
        return False

    categories = menu_cache.get_scannable_modifier_categories(item_type)

    # Single-select modifier categories (only one selection allowed at a time)
    # When adding a new modifier in these categories, replace any existing one
    single_select_categories = {"spread", "spread_type"}

    # Check each modifier category for this item type
    for category in categories:
        match = match_modifier(input_lower, category)
        if match:
            # Extract quantity and check if additive ("another vanilla", "one more syrup")
            quantity, is_additive = extract_additive_quantity(input_lower, match["pattern"])
            # Cap per-modifier quantity
            if quantity > MAX_MODIFIER_QUANTITY:
                quantity = MAX_MODIFIER_QUANTITY

            # Check if modifier already exists (exact slug match)
            existing = None
            for mod in (item.selections or []):
                if mod.get("slug") == match["slug"]:
                    existing = mod
                    break

            if existing and is_additive:
                # Increment existing quantity, capped at max
                old_qty = existing.get("quantity", 1)
                new_qty = min(old_qty + quantity, MAX_MODIFIER_QUANTITY)
                existing["quantity"] = new_qty
                logger.info(
                    "Incremented %s modifier: %s (qty=%d -> %d)",
                    category, match["slug"], old_qty, new_qty
                )
                made_change = True
            elif not existing:
                # For single-select categories, remove any existing selection first
                if category in single_select_categories:
                    existing_in_category = [
                        mod for mod in (item.selections or [])
                        if mod.get("category") in single_select_categories
                    ]
                    if existing_in_category:
                        old_mod = existing_in_category[0]
                        item.selections.remove(old_mod)
                        logger.info(
                            "Replaced %s: %s -> %s",
                            category, old_mod.get("slug"), match["slug"]
                        )

                # Add new modifier
                if add_modifier_to_item(
                    item,
                    slug=match["slug"],
                    display_name=match["name"],
                    quantity=quantity,
                    category=category,
                ):
                    made_change = True

    # Also check global attribute options (e.g., "shot" from espresso_shots)
    # This handles attributes that aren't ingredient categories
    attrs = menu_cache.get_item_type_attributes(item_type)
    for attr_slug, attr in attrs.items():
        options = attr.get("options", [])
        for opt in options:
            opt_slug = opt.get("slug", "")
            opt_display = opt.get("display_name", "")
            opt_slug_pattern = opt_slug.lower().replace("_", " ")
            opt_display_pattern = opt_display.lower()

            # Check if option matches input (use word-boundary to avoid false positives)
            # e.g., "add" in "add veggie cream cheese" should NOT match an "add" option slug
            slug_match = match_pattern_in_input(opt_slug_pattern, input_lower)
            display_match = match_pattern_in_input(opt_display_pattern, input_lower)
            if slug_match or display_match:
                # Skip if this slug was already added by the category loop above
                # This prevents double-adding when categories and attribute options overlap
                # (e.g., "syrup" category vs "milk_sweetener_syrup" attribute)
                if opt_slug in {m.get("slug") for m in (item.selections or [])}:
                    continue

                # Extract quantity and check if additive ("another shot", "one more shot")
                pattern = opt_slug_pattern if slug_match else opt_display_pattern
                quantity, is_additive = extract_additive_quantity(input_lower, pattern)
                # Cap per-modifier quantity
                if quantity > MAX_MODIFIER_QUANTITY:
                    quantity = MAX_MODIFIER_QUANTITY

                # Get price for this option
                opt_price = opt.get("price") or opt.get("price_modifier") or 0

                # Check if modifier already exists
                existing = item.get_selection(attr_slug)
                if existing and existing.get("slug") == opt_slug:
                    if is_additive:
                        # Increment existing quantity, capped at max
                        new_qty = min(existing.get("quantity", 1) + quantity, MAX_MODIFIER_QUANTITY)
                        existing["quantity"] = new_qty
                        # Update unit_price for the additional quantity
                        if opt_price > 0:
                            item.unit_price = (item.unit_price or 0.0) + (opt_price * quantity)
                        logger.info(
                            "Incremented attribute option: %s=%s (qty=%d -> %d, price=$%.2f)",
                            attr_slug, opt_slug, new_qty - quantity, new_qty, opt_price
                        )
                        made_change = True
                    # else: already exists and not additive, skip
                else:
                    # For single-select attributes, remove existing selection first
                    input_type = attr.get("input_type", "single_select")
                    if input_type != "multi_select" and existing:
                        item.remove_selection(attr_slug)
                        logger.info(
                            "Replaced single-select attribute: %s=%s -> %s",
                            attr_slug, existing.get("slug"), opt_slug
                        )
                    # Add new selection
                    item.add_selection(
                        slug=opt_slug,
                        category=attr_slug,
                        quantity=quantity,
                        price=opt_price,
                        display_name=opt_display,
                    )
                    logger.info(
                        "Added attribute option from input: %s=%s (qty=%d, price=$%.2f)",
                        attr_slug, opt_slug, quantity, opt_price
                    )
                    made_change = True

    return made_change


# =============================================================================
# ModifierInputHandler Class
# =============================================================================

class ModifierInputHandler:
    """
    Handler for modifier detection and application from raw user input.

    Provides methods for:
    - Detecting "add [modifier]" patterns
    - Detecting pure modifier input (e.g., just "vanilla" for a coffee)
    - Adding modifiers to the last item in cart
    - Category-level modifier removal ("no milk", "without syrup")
    """

    def __init__(self, pricing: "PricingEngine | None" = None) -> None:
        """Initialize the modifier input handler.

        Args:
            pricing: PricingEngine for recalculating prices after modifications.
        """
        self.pricing = pricing

    def handle_single_select_attribute_fallback(
        self,
        raw_user_input: str | None,
        order: "OrderTask",
    ) -> StateMachineResult | None:
        """Fallback handler for single_select attribute modifications.

        This is a FALLBACK that runs after EarlyPatternHandler. It handles cases
        where an ingredient maps to a single_select attribute on an item, but
        wasn't caught by add_modifiers_from_input().

        Example: "add butter" where "butter" is an ingredient in the "spread"
        category, and the item has a single_select "spread" attribute.

        NOTE: The main modifier handling (ADD_MODIFIER_PATTERNS, pure modifier
        detection, category removal) is done by EarlyPatternHandler. This method
        only handles the single_select attribute edge case.

        Args:
            raw_user_input: The raw user input string.
            order: The current order task.

        Returns:
            StateMachineResult if handled, None otherwise.
        """
        if not raw_user_input:
            return None

        input_lower = raw_user_input.lower().strip()
        active_items = order.items.get_active_items()

        if not active_items:
            return None

        # Only run this fallback for "add X" style patterns
        # Other patterns are fully handled by EarlyPatternHandler
        is_add_modifier_request = any(
            re.search(pattern, input_lower) for pattern in ADD_MODIFIER_PATTERNS
        )

        if not is_add_modifier_request:
            return None

        # Check if input contains a modifier from a single_select attribute category
        # Data-driven: loop through ingredient categories and find single_select attributes
        from .models import MenuItemTask

        for category in menu_cache.get_all_ingredient_categories():
            # Use word-boundary matching to avoid false positives (e.g., "egg" in "veggie")
            detected_modifier = find_first_word_boundary_match(
                input_lower,
                menu_cache.get_ingredients(category),
            )

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
                    updated_summary = recalculate_and_summarize(target_item, self.pricing)
                    category_display = menu_cache.get_ingredient_category_display_name(category)

                    if old_value:
                        logger.info("Add %s: changed from '%s' to '%s' on item", category, old_value, normalized_modifier)
                        return StateMachineResult(
                            message=sure_changed_anything_else(category_display.lower(), normalized_modifier, updated_summary),
                            order=order,
                        )
                    else:
                        logger.info("Add %s: added '%s' to item", category, normalized_modifier)
                        return StateMachineResult(
                            message=sure_added_to_anything_else(updated_summary),
                            order=order,
                        )

        return None

    def detect_pure_modifier_input(
        self,
        input_lower: str,
        active_items: list,
    ) -> tuple[bool, set[str]]:
        """Detect if input is purely a modifier for the last item.

        Args:
            input_lower: Lowercase user input to check.
            active_items: List of active items in the cart.

        Returns:
            Tuple of (is_pure_modifier_input, item_modifier_patterns)
        """
        has_item_modifier = False
        item_modifier_patterns: set[str] = set()

        if active_items:
            last_item = get_last_item(active_items)
            if is_configurable_menu_item(last_item):
                item_modifier_patterns = get_all_modifier_patterns_for_item(last_item.menu_item_type)
                # Use word-boundary matching to avoid false positives (e.g., "egg" in "veggie")
                has_item_modifier = any(
                    match_pattern_in_input(mod, input_lower)
                    for mod in item_modifier_patterns
                )

        if has_item_modifier and active_items:
            last_item = get_last_item(active_items)
            accepts_modifiers = (
                is_configurable_menu_item(last_item) and
                menu_cache.item_accepts_input_modifiers(last_item.menu_item_type)
            )
            if accepts_modifiers:
                # Strip qualifier phrases first so "on the side" doesn't match "side" as an item
                input_for_keyword_check = input_lower
                for qp in menu_cache.get_qualifier_patterns():
                    input_for_keyword_check = re.sub(
                        rf'\b{re.escape(qp)}\b', '', input_for_keyword_check
                    ).strip()
                item_keywords = menu_cache.get_item_keywords()
                non_modifier_keywords = {kw for kw in item_keywords if kw not in item_modifier_patterns}
                # Use word-boundary matching to avoid false positives
                has_other_item = any(
                    re.search(rf'\b{re.escape(kw)}\b', input_for_keyword_check)
                    for kw in non_modifier_keywords
                )
                if not has_other_item:
                    return True, item_modifier_patterns

        return False, item_modifier_patterns
