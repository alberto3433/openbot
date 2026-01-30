"""
Cache validation helpers for menu data access.

This module provides shared utilities for validating menu data cache state
and retrieving item type configuration. These helpers ensure consistent
error handling and messaging across modules that depend on menu data.
"""

from typing import Any

from orderbot.exceptions import MenuDataNotLoadedError


def ensure_menu_data_loaded(
    menu_data: dict | None,
    context_msg: str,
) -> dict:
    """Ensure menu_data is loaded and return it.

    This is a guard function to be called at the start of any function
    that requires menu_data to be available. It provides consistent
    error messages when menu data is missing.

    Args:
        menu_data: The menu_data dict (may be None or empty)
        context_msg: Context for error message (e.g., "look up modifier price")

    Returns:
        The validated menu_data dict

    Raises:
        MenuDataNotLoadedError: If menu_data is None or empty

    Examples:
        >>> data = ensure_menu_data_loaded(self._menu_data, "calculate price")
        >>> # data is now guaranteed to be a non-empty dict
    """
    if not menu_data:
        raise MenuDataNotLoadedError(
            f"Cannot {context_msg}. "
            "menu_data is required. Ensure menu is loaded."
        )
    return menu_data


def ensure_item_types_loaded(
    menu_data: dict | None,
    context_msg: str,
) -> dict[str, Any]:
    """Ensure menu_data has item_types structure and return it.

    Validates that menu_data is loaded and contains the 'item_types' structure
    needed for most pricing and configuration operations.

    Args:
        menu_data: The menu_data dict (may be None or empty)
        context_msg: Context for error message (e.g., "look up modifier price")

    Returns:
        The item_types dict from menu_data

    Raises:
        MenuDataNotLoadedError: If menu_data or item_types is missing

    Examples:
        >>> item_types = ensure_item_types_loaded(self._menu_data, "calculate price")
        >>> # item_types is now guaranteed to be a non-empty dict
    """
    data = ensure_menu_data_loaded(menu_data, context_msg)
    item_types = data.get("item_types", {})

    if not item_types:
        raise MenuDataNotLoadedError(
            f"Cannot {context_msg}. "
            "menu_data must contain 'item_types' structure. "
            "Ensure menu is loaded with full item type configuration."
        )

    return item_types


def get_item_type_config(
    menu_data: dict | None,
    item_type: str,
    context_msg: str,
) -> dict[str, Any]:
    """Get configuration for a specific item type from menu_data.

    Combines validation of menu_data and item_type existence into a single
    helper. Returns the type_data dict for the requested item type.

    Args:
        menu_data: The menu_data dict (may be None or empty)
        item_type: The item type slug to look up (e.g., "bagel", "sized_beverage")
        context_msg: Context for error message (e.g., "look up modifier price for 'ham'")

    Returns:
        The type_data dict for the specified item type

    Raises:
        MenuDataNotLoadedError: If menu_data or item_types is missing,
                                or if the item_type doesn't exist

    Examples:
        >>> type_data = get_item_type_config(self._menu_data, "bagel", "calculate price")
        >>> attributes = type_data.get("attributes", [])
    """
    item_types = ensure_item_types_loaded(menu_data, context_msg)

    type_data = item_types.get(item_type)

    if not type_data or not isinstance(type_data, dict):
        raise MenuDataNotLoadedError(
            f"Item type '{item_type}' not found in menu_data. "
            f"Cannot {context_msg}. "
            f"Available item types: {list(item_types.keys())}"
        )

    return type_data


def get_item_type_attributes(
    menu_data: dict | None,
    item_type: str,
    context_msg: str,
) -> list[dict]:
    """Get attributes list for a specific item type.

    Convenience wrapper that gets type config and extracts the attributes list.

    Args:
        menu_data: The menu_data dict
        item_type: The item type slug
        context_msg: Context for error message

    Returns:
        List of attribute dicts for the item type (may be empty)

    Raises:
        MenuDataNotLoadedError: If menu_data or item type is not available
    """
    type_data = get_item_type_config(menu_data, item_type, context_msg)
    return type_data.get("attributes", [])
