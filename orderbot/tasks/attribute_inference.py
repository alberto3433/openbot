"""
Attribute Inference Utilities.

This module provides data-driven utilities for inferring and extracting
attribute values from item names and kwargs. These functions are used
primarily by ItemAdderHandler to pre-populate item configurations.

Key functions:
- infer_attributes_from_item_name: Scan item name to pre-fill attributes
- extract_pre_filled_attributes: Extract known attributes from kwargs
- extract_generic_term: Detect generic category terms for disambiguation
"""

import logging
from typing import TYPE_CHECKING

from orderbot.menu_data_cache import menu_cache

if TYPE_CHECKING:
    from .models import MenuItemTask

logger = logging.getLogger(__name__)


def infer_attributes_from_item_name(item: "MenuItemTask") -> None:
    """
    Infer attribute values from the menu item name using database configuration.

    This is a data-driven approach that scans the item name against attribute
    options and pre-populates matching values. This prevents asking questions
    that are already answered by the item name.

    For example:
    - "Hot Coffee" → temperature = "hot" (if "hot" is an option for temperature)
    - "Iced Latte" → temperature = "iced"
    - "Decaf Americano" → decaf = True (if decaf is a boolean attribute)

    Args:
        item: The MenuItemTask to update with inferred attribute values
    """
    logger.info(
        "INFER_ATTRIBUTES: Called for item_name='%s', item_type='%s'",
        item.menu_item_name, item.menu_item_type
    )
    if not item.menu_item_type or not item.menu_item_name:
        logger.info("INFER_ATTRIBUTES: Skipping - missing type or name")
        return

    # Get all attributes for this item type from the database
    attrs = menu_cache.get_item_type_attributes(item.menu_item_type)
    if not attrs:
        logger.info("INFER_ATTRIBUTES: No attributes found for type '%s'", item.menu_item_type)
        return

    logger.info("INFER_ATTRIBUTES: Found %d attributes for '%s'", len(attrs), item.menu_item_type)
    item_name_lower = item.menu_item_name.lower()

    for attr_slug, attr_data in attrs.items():
        # Skip if attribute is already set
        if attr_slug in item:
            continue

        options = attr_data.get("options", [])
        input_type = attr_data.get("input_type", "single_select")

        # For boolean attributes, check if the attribute name appears in item name
        if input_type == "boolean":
            attr_display = attr_data.get("display_name", attr_slug).lower()
            if attr_display in item_name_lower:
                item[attr_slug] = True
                logger.info(
                    "Inferred %s=True from item name '%s'",
                    attr_slug, item.menu_item_name
                )
            continue

        # For select attributes, check if any option appears in item name
        for opt in options:
            opt_slug = opt.get("slug", "")
            opt_display = opt.get("display_name", "").lower()
            opt_slug_readable = opt_slug.replace("_", " ").lower()

            # Check if option slug or display name appears in item name
            if (opt_slug_readable in item_name_lower or
                    opt_display in item_name_lower or
                    opt_slug.lower() in item_name_lower):
                # Set the attribute value
                item[attr_slug] = opt_slug
                logger.info(
                    "Inferred %s='%s' from item name '%s'",
                    attr_slug, opt_slug, item.menu_item_name
                )
                break  # Only match first option per attribute


def extract_pre_filled_attributes(item_type: str, kwargs: dict) -> dict:
    """Extract pre-filled attributes from kwargs based on item type.

    Extracts only kwargs that match known attribute slugs for the item type.
    Unknown kwargs are ignored.

    Args:
        item_type: The item type slug
        kwargs: Original kwargs with item details

    Returns:
        Dict of attribute_slug -> value for pre-filling
    """
    if not item_type:
        return {}

    # Get known attributes for this item type from DB
    known_attrs = set(menu_cache.get_item_type_attributes(item_type).keys())

    attrs = {}
    for key, value in kwargs.items():
        if key in known_attrs:
            attrs[key] = value

    return attrs


def extract_generic_term(item_name: str) -> str | None:
    """Extract a generic category term from item_name if present.

    Uses data-driven matching - checks if the term or its suffix matches
    multiple menu items, indicating it's a generic term that needs disambiguation.

    Returns the generic term for searching, or None if no generic term found.

    Examples:
    - "chips" -> "chips" (if multiple chip items exist)
    - "Bagel Chips" -> "chips" (suffix matches multiple items)
    - "Potato Chips" -> "chips"
    - "Chocolate Chip Cookie" -> "cookie"
    - "Turkey Club" -> None (specific item)
    """
    item_lower = item_name.lower().strip()

    # Check if exact term matches multiple menu items
    matches = menu_cache.search_menu_items_by_name(item_lower)
    if len(matches) > 1:
        return item_lower

    # Check if last word is a generic term (matches multiple items)
    words = item_lower.split()
    if len(words) > 1:
        last_word = words[-1]
        suffix_matches = menu_cache.search_menu_items_by_name(last_word)
        if len(suffix_matches) > 1:
            return last_word

    return None
