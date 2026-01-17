"""
Task Factory Helpers.

Factory functions for creating MenuItemTask instances configured as specific
item types (bagels, coffee, etc.) for use in tests.

IMPORTANT: These helpers are ONLY for tests. They must NOT be imported
by any code in sandwich_bot/ - production code must be data-driven.
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
CoffeeItemTask = create_coffee_task


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
