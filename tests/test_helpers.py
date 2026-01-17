"""
Helper functions for tests.

Provides factory functions for creating MenuItemTask instances configured
as bagels or coffee items (replacing the removed BagelItemTask and CoffeeItemTask classes).
"""

from orderbot.tasks.models import MenuItemTask, TaskStatus


def create_bagel_task(
    bread: str = None,
    bread_upcharge: float = 0.0,
    toasted: bool = None,
    spread: str = None,
    spread_type: str = None,
    extras: list = None,
    extra_protein: str = None,
    quantity: int = 1,
    unit_price: float = 0.0,
    # Legacy parameter names for backwards compatibility
    bagel_type: str = None,
    bagel_type_upcharge: float = 0.0,
) -> MenuItemTask:
    """Create a MenuItemTask configured as a bagel.

    This is a replacement for the removed BagelItemTask class.
    """
    # Support legacy parameter names
    bread = bread or bagel_type
    bread_upcharge = bread_upcharge or bagel_type_upcharge

    bagel = MenuItemTask(
        menu_item_name="Bagel",
        menu_item_type="bagel",
        quantity=quantity,
        unit_price=unit_price,
    )
    # Set properties via setters (stored in attribute_values)
    if toasted is not None:
        bagel.toasted = toasted
    if spread:
        bagel.spread = spread
    if spread_type:
        bagel.spread_type = spread_type
    if bread:
        bagel.bread = bread
    if bread_upcharge:
        bagel.bread_upcharge = bread_upcharge
    if extras:
        bagel.toppings = extras
    if extra_protein:
        bagel.extra_protein = extra_protein
    return bagel


def create_coffee_task(
    drink_type: str = None,
    size: str = None,
    iced: bool = None,
    style: str = None,
    decaf: bool = False,
    milk: str = None,
    milk_upcharge: float = 0.0,
    sweeteners: list = None,
    flavor_syrups: list = None,
    extra_shots: int = 0,
    quantity: int = 1,
    unit_price: float = 0.0,
) -> MenuItemTask:
    """Create a MenuItemTask configured as a sized beverage (coffee).

    This is a replacement for the removed CoffeeItemTask class.

    Args:
        style: "hot" or "iced" - alternative to using iced bool directly.
               If both style and iced are provided, iced takes precedence.
    """
    coffee = MenuItemTask(
        menu_item_name=drink_type or "Coffee",
        menu_item_type="sized_beverage",
        quantity=quantity,
        unit_price=unit_price,
    )
    if size:
        coffee.size = size
    # Set temperature/iced - the iced property sets attribute_values["temperature"]
    if iced is not None:
        coffee.iced = iced
    elif style:
        coffee.iced = (style.lower() == "iced")
    if decaf:
        coffee.decaf = decaf
    if milk:
        coffee.milk = milk
    if milk_upcharge:
        coffee.milk_upcharge = milk_upcharge
    if sweeteners:
        coffee.sweeteners = sweeteners
    if flavor_syrups:
        coffee.flavor_syrups = flavor_syrups
    if extra_shots:
        coffee.extra_shots = extra_shots
    return coffee


# Backwards compatibility aliases that look like class constructors
# These allow tests to use BagelItemTask(...) and CoffeeItemTask(...) syntax
# while actually creating MenuItemTask instances
BagelItemTask = create_bagel_task


def is_bagel_item(item) -> bool:
    """Check if an item is a bagel (for use in tests).

    This replaces isinstance(item, BagelItemTask) checks.
    Uses has_attribute('bread') for data-driven detection.
    """
    if hasattr(item, 'has_attribute'):
        return item.has_attribute('bread')
    return False


def is_coffee_item(item) -> bool:
    """Check if an item is a coffee/sized beverage (for use in tests).

    This replaces isinstance(item, CoffeeItemTask) checks.
    Uses has_attribute('size') for data-driven detection.
    """
    if hasattr(item, 'has_attribute'):
        return item.has_attribute('size')
    return False
CoffeeItemTask = create_coffee_task


# =============================================================================
# parsed_items Query Helpers for Test Assertions
# =============================================================================
# These helpers make it easy to query the generic parsed_items list in
# OpenInputResponse, replacing assertions on legacy fields like new_bagel,
# new_coffee, new_signature_item, etc.

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
        # Note: ParsedItemEntry uses "item_type", while ParsedMenuItemEntry and
        # ParsedSideItemEntry use "type" field
        if item_type is not None:
            actual_type = getattr(item, 'item_type', None) or getattr(item, 'type', None)
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


def get_signature_item(result):
    """Shorthand to get the first signature item from parsed_items.

    Replaces: result.new_signature_item_name
    """
    return get_parsed_item(result, is_signature=True)


def has_signature_item(result) -> bool:
    """Shorthand to check if any signature item exists.

    Replaces: result.new_signature_item is True
    """
    return has_parsed_item(result, is_signature=True)


def get_bagel_item(result):
    """Shorthand to get the first bagel from parsed_items.

    Replaces: result.new_bagel is True / result.new_bagel_type
    """
    return get_parsed_item(result, item_type="bagel")


def has_bagel(result) -> bool:
    """Shorthand to check if any bagel exists.

    Replaces: result.new_bagel is True
    """
    return has_parsed_item(result, item_type="bagel")


def get_coffee_item(result):
    """Shorthand to get the first coffee/beverage from parsed_items.

    Replaces: result.new_coffee is True / result.new_coffee_type

    Checks for both "sized_beverage" and "coffee" item types since parsers may
    use either depending on context.
    """
    # Try sized_beverage first (new convention)
    item = get_parsed_item(result, item_type="sized_beverage")
    if item is not None:
        return item
    # Fall back to "coffee" item_type
    return get_parsed_item(result, item_type="coffee")


def has_coffee(result) -> bool:
    """Shorthand to check if any coffee/beverage exists.

    Replaces: result.new_coffee is True

    Checks for both "sized_beverage" and "coffee" item types.
    """
    return has_parsed_item(result, item_type="sized_beverage") or has_parsed_item(result, item_type="coffee")


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
