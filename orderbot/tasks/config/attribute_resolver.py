"""
Attribute Resolution for Menu Item Configuration.

This module provides functions for resolving and querying item type attributes
during configuration. It determines which attributes are mandatory vs optional,
which have been answered, and which should be skipped based on user selections.

All functions use menu_cache as the single source of truth for attribute data.
"""

import logging
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache

if TYPE_CHECKING:
    from ..models import MenuItemTask

logger = logging.getLogger(__name__)


def get_mandatory_attributes(item_type_slug: str) -> list[dict]:
    """Get mandatory attributes (ask_in_conversation=True) in display order.

    Excludes listen_only attributes which are never asked.
    """
    attrs = menu_cache.get_item_type_attributes(item_type_slug)
    mandatory = [
        attr for attr in attrs.values()
        if attr.get("ask_in_conversation", False)
        and not attr.get("listen_only", False)
    ]
    return sorted(mandatory, key=lambda x: x.get("display_order", 999))


def get_optional_attributes(item_type_slug: str) -> list[dict]:
    """Get optional attributes (ask_in_conversation=False) in display order.

    Excludes listen_only attributes which are never asked.
    """
    attrs = menu_cache.get_item_type_attributes(item_type_slug)
    optional = [
        attr for attr in attrs.values()
        if not attr.get("ask_in_conversation", True)
        and not attr.get("listen_only", False)
    ]
    return sorted(optional, key=lambda x: x.get("display_order", 999))


def get_skipped_attributes(item: "MenuItemTask") -> set[str]:
    """Get attributes that should be skipped based on item's current selections.

    Iterates through the item's attribute_values and selections to find
    any options that trigger skip rules (e.g., "black" skips milk-related attrs).

    Args:
        item: The menu item being configured

    Returns:
        Set of attribute slugs to skip
    """
    skipped: set[str] = set()

    # Check attribute_values (single-select values)
    for attr_slug, value in item.attribute_values.items():
        if isinstance(value, str):
            # Single-select value - check if it triggers skip rules
            attr_skips = menu_cache.get_skipped_attributes_for_option(value)
            skipped.update(attr_skips)
        elif isinstance(value, bool):
            # Boolean - option slugs are "true"/"false" to match DB storage
            bool_slug = "true" if value else "false"
            attr_skips = menu_cache.get_skipped_attributes_for_option(bool_slug)
            skipped.update(attr_skips)

    # Check selections list (multi-select values)
    for selection in item.selections:
        slug = selection.get("slug") if isinstance(selection, dict) else getattr(selection, "slug", None)
        if slug:
            attr_skips = menu_cache.get_skipped_attributes_for_option(slug)
            skipped.update(attr_skips)

    return skipped


def get_unanswered_mandatory(
    item: "MenuItemTask", item_type_slug: str
) -> list[dict]:
    """Get mandatory attributes that haven't been answered yet.

    Checks both canonical attribute slugs and legacy aliases to handle
    backward compatibility with items created by legacy handlers.
    Also checks direct model fields for certain attributes.

    Filters out attributes that should be skipped based on already-selected
    options (e.g., "black" coffee skips milk/sweetener/syrup questions).

    Special handling for auto-populated defaults: If an attribute only has
    a default value (is_default=True) and the attribute has ask_in_conversation=True,
    we still consider it "unanswered" so the user can confirm or change the default.
    """
    mandatory = get_mandatory_attributes(item_type_slug)

    # If user explicitly declined customization (e.g., "nothing else" in initial order),
    # accept all defaults and skip all mandatory questions
    if item.customization_declined:
        logger.info(
            "GET_UNANSWERED_MANDATORY: item_type=%s, customization_declined=True - skipping all",
            item_type_slug,
        )
        return []

    # Get attributes to skip based on current selections
    skipped_attrs = get_skipped_attributes(item)

    unanswered = []
    logger.info(
        "GET_UNANSWERED_MANDATORY: item_type=%s, attribute_values=%s, skipped=%s",
        item_type_slug, item.attribute_values, skipped_attrs
    )
    for attr in mandatory:
        slug = attr["slug"]
        # Check if this attribute should be skipped based on skip rules
        if slug in skipped_attrs:
            logger.debug("  %s: SKIPPED by option skip rule", slug)
            continue

        # Check if attribute has a value
        if slug in item:
            # Check if the value is only an auto-populated default
            # If so, we should still ask the question to let user confirm/change
            selections = item.get_selections(slug)
            all_defaults = selections and all(
                (sel.get("is_default", False) and not sel.get("_confirmed", False))
                if isinstance(sel, dict)
                else (getattr(sel, "is_default", False) and not getattr(sel, "_confirmed", False))
                for sel in selections
            )
            if all_defaults:
                logger.debug("  %s: FOUND but only defaults - adding to unanswered", slug)
                unanswered.append(attr)
            else:
                logger.debug("  %s: FOUND in attribute_values (user-selected)", slug)
            continue

        logger.debug("  %s: NOT FOUND - adding to unanswered", slug)
        unanswered.append(attr)
    logger.info(
        "GET_UNANSWERED_MANDATORY result: %s",
        [a["slug"] for a in unanswered]
    )
    return unanswered


def get_unanswered_optional(
    item: "MenuItemTask", item_type_slug: str
) -> list[dict]:
    """Get optional attributes that haven't been answered yet.

    Checks canonical attribute slugs in attribute_values.
    All properties (bread, toasted, etc.) now use attribute_values as backing store.

    Filters out attributes that should be skipped based on already-selected
    options (e.g., "black" coffee skips milk/sweetener/syrup options).
    """
    optional = get_optional_attributes(item_type_slug)

    # Get attributes to skip based on current selections
    skipped_attrs = get_skipped_attributes(item)

    unanswered = []
    for attr in optional:
        slug = attr["slug"]
        # Check if this attribute should be skipped based on skip rules
        if slug in skipped_attrs:
            continue
        # Check canonical slug in attribute_values
        if slug in item:
            continue
        unanswered.append(attr)
    return unanswered
