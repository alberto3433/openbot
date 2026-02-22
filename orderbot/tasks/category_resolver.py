"""Category Resolver - Menu category lookup and matching."""

import logging
import re

from orderbot.cache import menu_cache
from orderbot.cache.base import singularize

from .utils.text import normalize_text

logger = logging.getLogger(__name__)


def get_available_menu_categories_message() -> str:
    """Build a message listing a few available menu categories from database.

    Returns a formatted string like "sandwiches or drinks" for use in
    helpful suggestions when an item isn't found.

    Uses high-level display groups (Breads, Sandwiches, Drinks) instead of
    granular item types (Bagels, Chai Drinks, etc.) for cleaner UX.
    """
    try:
        # Get high-level display groups (e.g., Breads, Sandwiches, Drinks)
        display_groups = menu_cache.get_menu_display_groups()
        if display_groups:
            # Pick 2-3 main categories
            display_names = [g["display_name"] for g in display_groups][:3]
            if len(display_names) == 1:
                return display_names[0].lower()
            elif len(display_names) == 2:
                return f"{display_names[0].lower()} or {display_names[1].lower()}"
            else:
                return f"{display_names[0].lower()}, {display_names[1].lower()}, or {display_names[2].lower()}"
    except (KeyError, ValueError, AttributeError) as e:
        logger.warning("Failed to get display groups from database: %s", e)

    # Fallback message
    return "our menu items"


def find_matching_item_types(
    query: str, items_by_type: dict, exact_only: bool = False
) -> list[str]:
    """Find item types that match a query term.

    Checks for:
    1. Exact slug match (query == item_type_slug)
    2. Singular form match (singularize(query) == item_type_slug)
    3. Slug contains singular query as a word (e.g., "tea" matches "iced_tea")
       — only when exact_only=False

    Args:
        query: The search term.
        items_by_type: Dict of item_type_slug -> items.
        exact_only: If True, only return exact/singular slug matches (skip partial).

    Returns:
        List of matching item type slugs, empty if none found.
    """
    query_lower = normalize_text(query)
    singular = singularize(query_lower)

    matching = []
    for item_type_slug in items_by_type.keys():
        # Exact match
        if item_type_slug == query_lower or item_type_slug == singular:
            matching.append(item_type_slug)
        # Partial match: item type contains the query as a word
        # e.g., "tea" matches "iced_tea" (tea is a word in iced_tea)
        elif not exact_only and singular in item_type_slug.split('_'):
            matching.append(item_type_slug)

    return matching


def get_items_for_category(menu_query_type: str, menu_data: dict | None) -> tuple[list, str]:
    """Get items and display name for a menu category.

    Uses DB-driven approach with lookup_type:
    1. Exact item type slug match → use all matches (exact + partial), skip display groups
       e.g., "bagels" → "bagel" exact → bagel items only (not all "breads")
       e.g., "beverage" → "beverage" exact + partial "espresso_based_beverage" etc.
    2. Display group match (no exact type match)
       e.g., "drinks" → display group → all drink types (not just "energy_drink")
    3. Partial item type match (no exact match, no display group)
       e.g., "tea" → partial "iced_tea" → iced tea items
    4. Look up category in menu_cache.get_category_keyword_mapping()
    5. If lookup_type=="category", query via MenuItemCategory join table
    6. If lookup_type=="item_type", query by item_type_id
    7. Fall back to direct slug in items_by_type (for pagination state)
    8. Fall back to partial string matching on all items

    Returns:
        Tuple of (items list, category_key for pagination)
    """
    items_by_type = menu_data.get("items_by_type", {}) if menu_data else {}

    # Find all item type matches (exact + partial) and exact-only matches
    all_matching_types = find_matching_item_types(menu_query_type, items_by_type)
    exact_matching_types = find_matching_item_types(menu_query_type, items_by_type, exact_only=True)

    # If there's an exact item type slug match, use ALL matches (exact + partial)
    # and skip display groups. This ensures:
    # - "bagels" → exact "bagel" → returns only bagel items (not all "breads")
    # - "beverage" → exact "beverage" + partial "espresso_based_beverage" etc. → all beverage types
    if exact_matching_types:
        items = []
        for item_type_slug in all_matching_types:
            items.extend(items_by_type.get(item_type_slug, []))

        # Also search by name to catch items with the search term in their name
        name_matched_items = menu_cache.search_menu_items_by_term(menu_query_type)
        if name_matched_items:
            existing_names = {item.get("name", "").lower() for item in items}
            for item in name_matched_items:
                item_name = item.get("name", "").lower()
                if item_name and item_name not in existing_names:
                    items.append(item)
                    existing_names.add(item_name)

        if items:
            logger.info(
                "Menu query: '%s' matched %d item type(s): %s with %d items (exact match)",
                menu_query_type, len(all_matching_types), all_matching_types, len(items)
            )
            return items, exact_matching_types[0]

    # No exact item type match — check display groups (e.g., "breads", "sandwiches", "drinks")
    # Display groups win over partial item type matches so "drinks" shows all drinks,
    # not just "energy_drink" (which would be a partial match on "drink")
    display_group = menu_cache.get_display_group_by_slug(menu_query_type)
    if display_group:
        item_type_slugs = menu_cache.get_item_types_in_display_group(display_group["slug"])
        if item_type_slugs:
            items = []
            for item_type_slug in item_type_slugs:
                items.extend(items_by_type.get(item_type_slug, []))
            if items:
                logger.info(
                    "Menu query: '%s' matched display group with %d item types, %d total items",
                    menu_query_type, len(item_type_slugs), len(items)
                )
                return items, display_group["slug"]

    # No exact match and no display group — use partial item type matches
    # e.g., "tea" → partial match "iced_tea" → returns iced tea items
    if all_matching_types:
        items = []
        for item_type_slug in all_matching_types:
            items.extend(items_by_type.get(item_type_slug, []))

        name_matched_items = menu_cache.search_menu_items_by_term(menu_query_type)
        if name_matched_items:
            existing_names = {item.get("name", "").lower() for item in items}
            for item in name_matched_items:
                item_name = item.get("name", "").lower()
                if item_name and item_name not in existing_names:
                    items.append(item)
                    existing_names.add(item_name)

        if items:
            logger.info(
                "Menu query: '%s' matched %d item type(s): %s with %d items (partial match)",
                menu_query_type, len(all_matching_types), all_matching_types, len(items)
            )
            return items, all_matching_types[0]

    # Look up category info from DB-loaded cache
    # This ensures "beverage" maps to sized_beverage/espresso_based_beverage per DB config
    category_info = menu_cache.get_category_keyword_mapping(menu_query_type)

    if category_info:
        slug = category_info["slug"]
        lookup_type = category_info.get("lookup_type", "item_type")

        if lookup_type == "category":
            # Query via MenuItemCategory join table
            items = menu_cache.get_items_by_category(slug)
            return items, slug
        else:
            # Query by item_type_id
            items = items_by_type.get(slug, [])
            return items, slug

    # Fall back to direct item_type slug (used in pagination state)
    if menu_query_type in items_by_type:
        return items_by_type[menu_query_type], menu_query_type

    # FALLBACK: For unrecognized terms, search by word-boundary in names AND aliases
    # This handles "what lattes do you have?" by finding Hot Latte, Iced Latte, etc.
    # Uses word-boundary matching (not substring) and singularizes the search term
    filtered = menu_cache.search_menu_items_by_term(menu_query_type)
    if filtered:
        logger.info(
            "Menu query fallback: '%s' matched %d items via word-boundary search",
            menu_query_type, len(filtered)
        )
        return filtered, menu_query_type

    # FALLBACK 2: Check if first word is a known name prefix (e.g., "iced", "hot")
    # This handles "what iced drinks do you have?" by finding items like "Iced Coffee"
    words = menu_query_type.split()
    if words:
        first_word = words[0].lower()
        prefix_items = menu_cache.get_menu_items_by_name_prefix(first_word)
        if prefix_items:
            # If there's a category filter (remaining words), apply it
            if len(words) >= 2:
                category_filter = " ".join(words[1:])
                # Try to look up the category to filter by item types
                display_group = menu_cache.get_display_group_by_slug(category_filter)
                if display_group:
                    # Filter prefix_items to only those in the display group's item types
                    allowed_types = set(
                        menu_cache.get_item_types_in_display_group(display_group["slug"])
                    )
                    prefix_items = [
                        item for item in prefix_items
                        if item.get("item_type") in allowed_types
                    ]
                else:
                    # Try category keyword mapping
                    category_info = menu_cache.get_category_keyword_mapping(category_filter)
                    if category_info:
                        slug = category_info["slug"]
                        lookup_type = category_info.get("lookup_type", "item_type")
                        if lookup_type == "item_type":
                            prefix_items = [
                                item for item in prefix_items
                                if item.get("item_type") == slug
                            ]

            if prefix_items:
                logger.info(
                    "Menu query prefix: '%s' -> prefix='%s' matched %d items",
                    menu_query_type, first_word, len(prefix_items)
                )
                return prefix_items, menu_query_type

    # FALLBACK 3: Handle "adjective + category" patterns (legacy approach)
    # Try splitting into prefix word(s) + base category, then filter by name containing prefix
    # This is less precise than prefix index but catches items where prefix isn't the first word
    if len(words) >= 2:
        # Try the last word as category (e.g., "drinks" from "iced drinks")
        base_category = words[-1]
        prefix_filter = " ".join(words[:-1])  # e.g., "iced"

        category_info = menu_cache.get_category_keyword_mapping(base_category)
        if category_info:
            slug = category_info["slug"]
            lookup_type = category_info.get("lookup_type", "item_type")

            if lookup_type == "category":
                all_items = menu_cache.get_items_by_category(slug)
            else:
                all_items = items_by_type.get(slug, [])

            # Filter items by prefix (e.g., items containing "iced")
            if all_items and prefix_filter:
                filter_pattern = re.compile(rf'\b{re.escape(prefix_filter)}\b', re.IGNORECASE)
                filtered = [
                    item for item in all_items
                    if filter_pattern.search(item.get("name", ""))
                ]
                if filtered:
                    logger.info(
                        "Menu query fallback: '%s' -> base='%s' + filter='%s' matched %d items",
                        menu_query_type, base_category, prefix_filter, len(filtered)
                    )
                    return filtered, menu_query_type

    # No matches found
    return [], menu_query_type
