"""
Unified Modifier Operations.

This module provides a generic system for handling modifier operations
(add, remove, update) across all item types (bagels, coffee, menu items, etc.).

The key insight is that modifiers are just fields on item objects, and we can
handle them generically by defining which fields are "modifiers" for each item type.

All modifier field definitions are loaded from the database. There are no
hardcoded fallbacks - if the database doesn't have modifier fields configured,
an exception is raised to fail fast and make the configuration problem visible.
"""

import logging
from dataclasses import dataclass
from typing import Any

from .models import (
    ItemTask,
    MenuItemTask,
)
from orderbot.exceptions import MenuDataNotLoadedError
from orderbot.cache import menu_cache
from orderbot.cache.base import get_singular_plural_variants
from .utils.constants import is_price_metadata_key
from .utils.text import strip_leading_article
from .modifier_resolver import normalize_modifier_input

logger = logging.getLogger(__name__)


@dataclass
class ModifierField:
    """Definition of a modifier field on an item."""
    field_name: str  # The actual attribute name on the item (e.g., "spread")
    display_name: str  # Human-readable name (e.g., "cream cheese")
    aliases: list[str]  # Alternative names users might say (e.g., ["cc", "schmear"])
    is_list: bool = False  # True if field is a list (e.g., extras, sweeteners)


@dataclass
class ModifierMatch:
    """Result of matching user input to a modifier."""
    field: ModifierField
    matched_value: str | None  # The specific value matched (for lists)
    item: ItemTask
    attribute_key: str | None = None  # For MenuItemTask attribute_values (e.g., "condiments")


@dataclass
class ModifierRemovalResult:
    """Result of removing a modifier."""
    success: bool
    removed_value: str | None
    message: str


def _load_modifier_fields_from_db(item_type_slug: str) -> list[ModifierField]:
    """Load modifier fields from database for an item type.

    Returns a list of ModifierField objects. Returns empty list if no modifier
    fields are defined for this item type (this is valid - not all item types
    have modifier fields via global attributes).
    """
    field_configs = menu_cache.get_modifier_fields_for_item_type(item_type_slug)
    if not field_configs:
        return []  # No modifier fields defined for this item type

    result = []
    for config in field_configs:
        result.append(ModifierField(
            field_name=config["field_name"],
            display_name=config["display_name"],
            aliases=config["aliases"],
            is_list=config["is_list"],
        ))

    logger.debug(
        "Loaded %d modifier fields from DB for %s: %s",
        len(result), item_type_slug,
        [(f.field_name, len(f.aliases)) for f in result]
    )
    return result


def get_modifier_fields(item: ItemTask) -> list[ModifierField]:
    """Get the modifier field definitions for an item type.

    Loads modifier fields from database. Fails fast if item type not set.

    Raises:
        MenuDataNotLoadedError: If item has no menu_item_type or no modifier fields in database
    """
    if isinstance(item, MenuItemTask):
        item_type = item.menu_item_type
        if not item_type:
            raise MenuDataNotLoadedError(
                f"MenuItemTask '{item.menu_item_name}' has no menu_item_type set. "
                f"Ensure menu_item_type is populated when creating items."
            )
        return _load_modifier_fields_from_db(item_type)
    else:
        return []


def _get_list_item_slug(list_item: Any) -> str:
    """Extract the slug/value string from a list item (dict or scalar)."""
    if isinstance(list_item, dict):
        return list_item.get("slug", "") or ""
    return str(list_item)


def _normalize_for_matching(value: Any) -> str:
    """Normalize a value for modifier matching: lowercase + underscores to spaces."""
    return str(value).lower().replace("_", " ")


def _normalize_modifier_name(name: str) -> str:
    """Normalize a modifier name for matching.

    Delegates to modifier_resolver.normalize_modifier_input().
    """
    return normalize_modifier_input(name, strip_articles=False)


def find_modifier_match(item: ItemTask, user_input: str) -> ModifierMatch | None:
    """
    Find if user input matches any modifier on the item.

    Args:
        item: The item to check
        user_input: What the user said (e.g., "cream cheese", "the bacon")

    Returns:
        ModifierMatch if found, None otherwise
    """
    normalized_input = _normalize_modifier_name(user_input)
    # Remove leading "the " if present
    normalized_input = strip_leading_article(normalized_input)

    fields = get_modifier_fields(item)

    logger.debug(
        "find_modifier_match: searching for '%s' in %d fields on %s",
        normalized_input, len(fields), item.menu_item_name if isinstance(item, MenuItemTask) else 'unknown'
    )

    for field in fields:
        value = getattr(item, field.field_name, None)
        logger.debug(
            "find_modifier_match: field=%s, value=%r, num_aliases=%d",
            field.field_name, value, len(field.aliases)
        )
        if value is None:
            continue

        # Check if user input matches the field's aliases
        # Check for early matches
        matching_aliases = [a for a in field.aliases if normalized_input == a or a in normalized_input]
        if matching_aliases:
            logger.debug(
                "find_modifier_match: field=%s matched aliases=%s for input='%s'",
                field.field_name, matching_aliases[:5], normalized_input
            )
        for alias in field.aliases:
            is_exact_alias_match = (normalized_input == alias)
            is_substring_alias_match = (alias in normalized_input) and not is_exact_alias_match

            if is_exact_alias_match or is_substring_alias_match:
                if field.is_list:
                    # For lists, find the specific matching item
                    if isinstance(value, list):
                        # Skip empty lists - nothing to match against
                        if not value:
                            continue
                        for list_item in value:
                            item_value = _get_list_item_slug(list_item)
                            item_value_normalized = _normalize_for_matching(item_value)
                            if alias in item_value_normalized or normalized_input in item_value_normalized:
                                return ModifierMatch(field=field, matched_value=item_value, item=item)
                        # Only return "remove all" match if it's an EXACT alias match
                        # e.g., "remove syrup" should remove all syrups
                        # But "no whole milk" (where "milk" is substring) should NOT remove
                        # other items if "whole_milk" isn't in the list
                        if is_exact_alias_match:
                            return ModifierMatch(field=field, matched_value=None, item=item)
                        # For substring matches, continue looking in other fields
                        continue
                else:
                    return ModifierMatch(field=field, matched_value=None, item=item)

        # For non-list fields, also check if the actual value matches
        if not field.is_list and value:
            value_str = str(value).lower()
            # Check if user input contains the value or vice versa
            if normalized_input in value_str or value_str in normalized_input:
                return ModifierMatch(field=field, matched_value=None, item=item)

            # Special handling for abbreviated/short modifier names that match longer values
            # e.g., spread="kalamata olive cream cheese", user says "cream cheese" or "cc"
            # Use database normalization to expand abbreviations
            canonical_input = menu_cache.normalize_modifier(normalized_input)
            if canonical_input:
                canonical_lower = canonical_input.lower()
                if canonical_lower in value_str:
                    return ModifierMatch(field=field, matched_value=None, item=item)

        # For list fields, check if any item matches the input directly
        if field.is_list and isinstance(value, list):
            for list_item in value:
                item_value = _get_list_item_slug(list_item)
                item_value_normalized = _normalize_for_matching(item_value)
                if normalized_input in item_value_normalized or item_value_normalized in normalized_input:
                    return ModifierMatch(field=field, matched_value=item_value, item=item)

    # For MenuItemTask, also check attribute_values dictionary
    if isinstance(item, MenuItemTask):
        attribute_values = item.attribute_values
        if attribute_values:
            # Get singular/plural variants for matching (e.g., "eggs" -> ["eggs", "egg"])
            input_variants = get_singular_plural_variants(normalized_input)

            # Expand alias abbreviations via DB (e.g., "scallion cc" → "scallion cream cheese")
            canonical_input = menu_cache.normalize_modifier(normalized_input)
            if canonical_input:
                canonical_lower = canonical_input.lower().replace("_", " ")
                if canonical_lower not in input_variants:
                    input_variants.append(canonical_lower)

            for attr_key, attr_value in attribute_values.items():
                # Skip metadata fields
                if is_price_metadata_key(attr_key):
                    continue

                if isinstance(attr_value, list):
                    for list_item in attr_value:
                        item_value_normalized = _normalize_for_matching(list_item)
                        for variant in input_variants:
                            if variant in item_value_normalized or item_value_normalized in variant:
                                synthetic_field = ModifierField(
                                    field_name="attribute_values",
                                    display_name=attr_key.replace("_", " "),
                                    aliases=[],
                                    is_list=True,
                                )
                                return ModifierMatch(
                                    field=synthetic_field,
                                    matched_value=str(list_item),
                                    item=item,
                                    attribute_key=attr_key,
                                )
                elif attr_value:
                    value_str_normalized = _normalize_for_matching(attr_value)
                    for variant in input_variants:
                        if variant in value_str_normalized or value_str_normalized in variant:
                            synthetic_field = ModifierField(
                                field_name="attribute_values",
                                display_name=attr_key.replace("_", " "),
                                aliases=[],
                                is_list=False,
                            )
                            return ModifierMatch(
                                field=synthetic_field,
                                matched_value=str(attr_value),
                                item=item,
                                attribute_key=attr_key,
                            )

    return None


def find_modifier_on_any_item(
    items: list[ItemTask],
    user_input: str,
    prefer_last: bool = True,
) -> ModifierMatch | None:
    """
    Find if user input matches a modifier on any item in the list.

    Args:
        items: List of items to check
        user_input: What the user said
        prefer_last: If True, check items from last to first (default)

    Returns:
        ModifierMatch if found, None otherwise
    """
    search_order = reversed(items) if prefer_last else items

    for item in search_order:
        match = find_modifier_match(item, user_input)
        if match:
            return match

    return None


# Re-exports for backward compatibility
from .default_ingredient_operations import (  # noqa: F401
    DefaultIngredientMatch,
    DefaultIngredientRemovalResult,
    find_default_ingredient_match,
    remove_default_ingredient_from_item,
    find_default_ingredient_on_any_item,
)
from .modifier_field_removal import (  # noqa: F401
    remove_modifier_from_item,
)
