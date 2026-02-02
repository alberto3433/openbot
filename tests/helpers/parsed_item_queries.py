"""
Parsed Item Query Helpers.

Helper functions for querying parsed_items in OpenInputResponse objects.
These make it easy to write test assertions on the generic parsed_items list.

IMPORTANT: These helpers are ONLY for tests. They must NOT be imported
by any code in sandwich_bot/ - production code must be data-driven.
"""


def get_parsed_items(result, item_type: str = None, is_signature: bool = None,
                     item_name: str = None) -> list:
    """Get all parsed items matching the criteria.

    Args:
        result: OpenInputResponse object
        item_type: Filter by item_type (e.g., "bagel", "sized_beverage", "menu_item", "side")
        is_signature: Filter by is_signature flag
        item_name: Filter by item_name (case-insensitive substring match)

    Returns:
        List of matching ParsedItemEntry objects
    """
    if not hasattr(result, 'parsed_items'):
        return []

    matches = []
    for item in result.parsed_items:
        # Filter by item_type
        if item_type is not None:
            actual_type = getattr(item, 'item_type', None)
            if actual_type != item_type:
                continue
        # Filter by is_signature
        if is_signature is not None:
            if not hasattr(item, 'is_signature') or item.is_signature != is_signature:
                continue
        # Filter by item_name (case-insensitive substring)
        if item_name is not None:
            if not hasattr(item, 'item_name') or item.item_name is None:
                continue
            if item_name.lower() not in item.item_name.lower():
                continue
        matches.append(item)
    return matches


def get_parsed_item(result, item_type: str = None, is_signature: bool = None,
                    item_name: str = None):
    """Get first parsed item matching the criteria, or None.

    Args:
        result: OpenInputResponse object
        item_type: Filter by item_type
        is_signature: Filter by is_signature flag
        item_name: Filter by item_name (case-insensitive substring match)

    Returns:
        First matching ParsedItemEntry or None
    """
    matches = get_parsed_items(result, item_type, is_signature, item_name)
    return matches[0] if matches else None


def has_parsed_item(result, item_type: str = None, is_signature: bool = None,
                    item_name: str = None) -> bool:
    """Check if any parsed item matches the criteria.

    Args:
        result: OpenInputResponse object
        item_type: Filter by item_type
        is_signature: Filter by is_signature flag
        item_name: Filter by item_name (case-insensitive substring match)

    Returns:
        True if at least one item matches
    """
    return len(get_parsed_items(result, item_type, is_signature, item_name)) > 0


def count_parsed_items(result, item_type: str = None, is_signature: bool = None,
                       item_name: str = None) -> int:
    """Count parsed items matching the criteria.

    Args:
        result: OpenInputResponse object
        item_type: Filter by item_type
        is_signature: Filter by is_signature flag
        item_name: Filter by item_name (case-insensitive substring match)

    Returns:
        Number of matching items
    """
    return len(get_parsed_items(result, item_type, is_signature, item_name))


def get_item_with_defaults(result):
    """Shorthand to get the first item with default ingredients from parsed_items.

    Items with default ingredients have is_signature=True in their parsed representation.
    This includes items like "The Classic BEC" that have predefined ingredient configurations.
    """
    return get_parsed_item(result, is_signature=True)


def has_item_with_defaults(result) -> bool:
    """Shorthand to check if any item with default ingredients exists.

    Items with default ingredients have is_signature=True in their parsed representation.
    """
    return has_parsed_item(result, is_signature=True)


# Backward compatibility aliases
get_signature_item = get_item_with_defaults
has_signature_item = has_item_with_defaults


def get_bagel_item(result):
    """Shorthand to get the first bagel from parsed_items.

    Replaces: result.new_bagel is True / result.new_bagel_type

    Note: Plain bagels use "bagel" item type in the database.
    """
    return get_parsed_item(result, item_type="bagel")


def has_bagel(result) -> bool:
    """Shorthand to check if any bagel exists.

    Replaces: result.new_bagel is True

    Note: Plain bagels use "bagel" item type in the database.
    """
    return has_parsed_item(result, item_type="bagel")


def get_coffee_item(result):
    """Shorthand to get the first coffee/beverage from parsed_items.

    Replaces: result.new_coffee is True / result.new_coffee_type

    Checks for "sized_beverage", "espresso", "espresso_based", and "coffee" item types
    since parsers may use any of these depending on context.
    """
    # Try sized_beverage first (new convention)
    item = get_parsed_item(result, item_type="sized_beverage")
    if item is not None:
        return item
    # Try espresso
    item = get_parsed_item(result, item_type="espresso")
    if item is not None:
        return item
    # Try espresso_based (lattes, cappuccinos, etc.)
    item = get_parsed_item(result, item_type="espresso_based")
    if item is not None:
        return item
    # Fall back to "coffee" item_type
    return get_parsed_item(result, item_type="coffee")


def has_coffee(result) -> bool:
    """Shorthand to check if any coffee/beverage exists.

    Replaces: result.new_coffee is True

    Checks for "sized_beverage", "espresso", "espresso_based", and "coffee" item types.
    """
    return (
        has_parsed_item(result, item_type="sized_beverage") or
        has_parsed_item(result, item_type="espresso") or
        has_parsed_item(result, item_type="espresso_based") or
        has_parsed_item(result, item_type="coffee")
    )


def get_menu_item(result, item_name: str = None):
    """Shorthand to get the first menu item from parsed_items.

    Replaces: result.new_menu_item
    """
    return get_parsed_item(result, item_type="menu_item", item_name=item_name)


def has_menu_item(result, item_name: str = None) -> bool:
    """Shorthand to check if any menu item exists.

    Replaces: result.new_menu_item is not None
    """
    return has_parsed_item(result, item_type="menu_item", item_name=item_name)


def get_side_item(result):
    """Shorthand to get the first side item from parsed_items.

    Replaces: result.new_side_item
    """
    return get_parsed_item(result, item_type="side")


def has_side_item(result) -> bool:
    """Shorthand to check if any side item exists.

    Replaces: result.new_side_item is not None
    """
    return has_parsed_item(result, item_type="side")
