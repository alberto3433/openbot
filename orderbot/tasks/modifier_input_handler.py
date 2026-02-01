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
from .parsers.quantity_utils import extract_quantity_for_pattern, extract_additive_quantity
from .handler_utils import (
    is_configurable_menu_item,
    get_last_item,
    recalculate_and_summarize,
)
from .schemas import StateMachineResult

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
            if pattern in input_lower:
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


def _extract_quantity_from_input(input_lower: str, pattern: str) -> int:
    """Extract quantity from user input for a modifier.

    Args:
        input_lower: Lowercase user input
        pattern: The modifier pattern to look for quantity before

    Returns:
        Quantity (defaults to 1 if not found)
    """
    return extract_quantity_for_pattern(input_lower, pattern)


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

    categories = menu_cache.get_scannable_modifier_categories(item_type)

    # Check each modifier category for this item type
    for category in categories:
        match = match_modifier(input_lower, category)
        if match:
            # Extract quantity and check if additive ("another vanilla", "one more syrup")
            quantity, is_additive = extract_additive_quantity(input_lower, match["pattern"])

            # Check if modifier already exists
            existing = None
            for mod in (item.modifiers or []):
                if mod.get("slug") == match["slug"]:
                    existing = mod
                    break

            if existing and is_additive:
                # Increment existing quantity
                old_qty = existing.get("quantity", 1)
                existing["quantity"] = old_qty + quantity
                logger.info(
                    "Incremented %s modifier: %s (qty=%d -> %d)",
                    category, match["slug"], old_qty, old_qty + quantity
                )
                made_change = True
            elif not existing:
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

            # Check if option matches input
            if opt_slug_pattern in input_lower or opt_display_pattern in input_lower:
                # Extract quantity and check if additive ("another shot", "one more shot")
                pattern = opt_slug_pattern if opt_slug_pattern in input_lower else opt_display_pattern
                quantity, is_additive = extract_additive_quantity(input_lower, pattern)

                # Get price for this option
                opt_price = opt.get("price") or opt.get("price_modifier") or 0

                # Check if modifier already exists
                existing = item.get_selection(attr_slug)
                if existing and existing.get("slug") == opt_slug:
                    if is_additive:
                        # Increment existing quantity
                        new_qty = existing.get("quantity", 1) + quantity
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


def match_category_removal_pattern(input_lower: str, item_type_slug: str) -> str | None:
    """Check if input matches a removal pattern for any modifier category.

    Uses templatized patterns ("no {}", "without {}", etc.) with category names
    AND ingredient names from the database. No hardcoded patterns.

    Args:
        input_lower: Lowercase user input to check
        item_type_slug: The item type to get modifier categories for

    Returns:
        Category slug if a removal pattern matches, None otherwise.

    Examples:
        >>> match_category_removal_pattern("no milk", "sized_beverage")
        "milk"
        >>> match_category_removal_pattern("without syrup", "sized_beverage")
        "syrup"
        >>> match_category_removal_pattern("remove the sugar", "sized_beverage")
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

        # Also add ingredient names in this category (e.g., "sugar" for sweetener)
        # This allows "without sugar" to match the sweetener category
        ingredients = menu_cache.get_ingredients(category)
        for ingredient in ingredients:
            names_to_check.add(ingredient.lower())

        # Check each removal template with each name variant
        for template in REMOVAL_TEMPLATES:
            for name in names_to_check:
                pattern = template.format(name)
                if pattern in input_lower:
                    return category

    return None


def remove_modifiers_by_category(
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

    def belongs_to_category(modifier: dict, target_category: str) -> bool:
        """Check if modifier belongs to target category.

        Checks both the stored category field AND looks up the ingredient category
        from the modifier's slug. This handles cases where modifiers are stored
        with attribute slugs (e.g., "milk_sweetener_syrup") but we want to remove
        by ingredient category (e.g., "milk").
        """
        # Direct category match
        if modifier.get("category") == target_category:
            return True

        # Look up ingredient category from slug
        slug = modifier.get("slug", "")
        if slug:
            # Try full slug first, then with common suffixes
            ingredient_cat = menu_cache.get_ingredient_category(slug)
            if ingredient_cat == target_category:
                return True

            # Try adding common suffixes (e.g., "whole" -> "whole milk")
            for suffix in [" milk", " syrup"]:
                ingredient_cat = menu_cache.get_ingredient_category(slug + suffix)
                if ingredient_cat == target_category:
                    return True

        return False

    # Filter out selections of the specified category
    new_selections = [m for m in current_selections if not belongs_to_category(m, category)]

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

    def handle_add_modifier_to_last_item(
        self,
        raw_user_input: str | None,
        order: "OrderTask",
    ) -> StateMachineResult | None:
        """Handle 'add [modifier]' patterns that modify the last item.

        Handles patterns like:
        - "add vanilla syrup", "add oat milk", "with caramel"
        - Pure modifier input (just "vanilla" when there's a coffee in cart)
        - Category-level modifier removal ("no milk", "without syrup")
        - Single_select attribute modifier updates

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
            last_item_check = get_last_item(active_items)
            if is_configurable_menu_item(last_item_check):
                # Get modifier patterns for this specific item type (data-driven)
                item_modifier_patterns = get_all_modifier_patterns_for_item(last_item_check.menu_item_type)
                has_item_modifier = any(mod in input_lower for mod in item_modifier_patterns)

        if has_item_modifier and active_items:
            last_item_check = get_last_item(active_items)
            # Check if item accepts input modifiers (data-driven)
            accepts_modifiers = (
                is_configurable_menu_item(last_item_check) and
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
            last_item = get_last_item(active_items)
            # Check if item accepts input modifiers (data-driven)
            accepts_modifiers = (
                is_configurable_menu_item(last_item) and
                menu_cache.item_accepts_input_modifiers(last_item.menu_item_type)
            )
            if accepts_modifiers:
                made_change = add_modifiers_from_input(last_item, input_lower)

                if made_change:
                    updated_summary = recalculate_and_summarize(last_item, self.pricing)
                    return StateMachineResult(
                        message=f"Sure, I've added that to your {updated_summary}. Anything else?",
                        order=order,
                    )

        # Check for category-level modifier removal using templatized patterns
        # e.g., "no milk", "without syrup", "remove the sweetener"
        # This is data-driven: patterns generated from database category names
        if active_items:
            last_item = get_last_item(active_items)
            if is_configurable_menu_item(last_item):
                removed_category = match_category_removal_pattern(input_lower, last_item.menu_item_type)
                if removed_category:
                    if remove_modifiers_by_category(last_item, removed_category):
                        updated_summary = recalculate_and_summarize(last_item, self.pricing)
                        category_display = menu_cache.get_ingredient_category_display_name(removed_category)
                        return StateMachineResult(
                            message=f"Sure, I've removed the {category_display.lower()}. Your order is now {updated_summary}. Anything else?",
                            order=order,
                        )

        if is_add_modifier_request and active_items:
            # Check if input contains a modifier from a single_select attribute category
            # Data-driven: loop through ingredient categories and find single_select attributes
            from .models import MenuItemTask

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
                        updated_summary = recalculate_and_summarize(target_item, self.pricing)
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
                has_item_modifier = any(mod in input_lower for mod in item_modifier_patterns)

        if has_item_modifier and active_items:
            last_item = get_last_item(active_items)
            accepts_modifiers = (
                is_configurable_menu_item(last_item) and
                menu_cache.item_accepts_input_modifiers(last_item.menu_item_type)
            )
            if accepts_modifiers:
                item_keywords = menu_cache.get_item_keywords()
                non_modifier_keywords = {kw for kw in item_keywords if kw not in item_modifier_patterns}
                has_other_item = any(kw in input_lower for kw in non_modifier_keywords)
                if not has_other_item:
                    return True, item_modifier_patterns

        return False, item_modifier_patterns
