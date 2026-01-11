"""
Helper functions for tests.

Provides factory functions for creating MenuItemTask instances configured
as bagels or coffee items (replacing the removed BagelItemTask and CoffeeItemTask classes).
"""

from sandwich_bot.tasks.models import MenuItemTask


def create_bagel_task(
    bagel_type: str = None,
    bagel_type_upcharge: float = 0.0,
    toasted: bool = None,
    spread: str = None,
    spread_type: str = None,
    extras: list = None,
    sandwich_protein: str = None,
    quantity: int = 1,
    unit_price: float = 0.0,
) -> MenuItemTask:
    """Create a MenuItemTask configured as a bagel.

    This is a replacement for the removed BagelItemTask class.
    """
    bagel = MenuItemTask(
        menu_item_name="Bagel",
        menu_item_type="bagel",
        toasted=toasted,
        spread=spread,
        quantity=quantity,
        unit_price=unit_price,
    )
    if bagel_type:
        bagel.bagel_type = bagel_type
    if bagel_type_upcharge:
        bagel.bagel_type_upcharge = bagel_type_upcharge
    if spread_type:
        bagel.spread_type = spread_type
    if extras:
        bagel.extras = extras
    if sandwich_protein:
        bagel.sandwich_protein = sandwich_protein
    return bagel


def create_coffee_task(
    drink_type: str = None,
    size: str = None,
    iced: bool = None,
    decaf: bool = False,
    milk: str = None,
    milk_upcharge: float = 0.0,
    sweeteners: list = None,
    extra_shots: int = 0,
    quantity: int = 1,
    unit_price: float = 0.0,
) -> MenuItemTask:
    """Create a MenuItemTask configured as a sized beverage (coffee).

    This is a replacement for the removed CoffeeItemTask class.
    """
    coffee = MenuItemTask(
        menu_item_name=drink_type or "Coffee",
        menu_item_type="sized_beverage",
        quantity=quantity,
        unit_price=unit_price,
    )
    if size:
        coffee.size = size
    if iced is not None:
        coffee.iced = iced
    if decaf:
        coffee.decaf = decaf
    if milk:
        coffee.milk = milk
    if milk_upcharge:
        coffee.milk_upcharge = milk_upcharge
    if sweeteners:
        coffee.sweeteners = sweeteners
    if extra_shots:
        coffee.extra_shots = extra_shots
    return coffee


# Backwards compatibility aliases that look like class constructors
# These allow tests to use BagelItemTask(...) and CoffeeItemTask(...) syntax
# while actually creating MenuItemTask instances
BagelItemTask = create_bagel_task
CoffeeItemTask = create_coffee_task
