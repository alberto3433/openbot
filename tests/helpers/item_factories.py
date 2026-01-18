"""
Test Item Factory Functions.

Factory functions for creating MenuItemTask instances for testing.
These functions provide convenient ways to create items with specific types
and attributes without having to specify all the details manually.

IMPORTANT: These helpers are ONLY for tests. They must NOT be imported
by any code in orderbot/ - production code must be data-driven.
"""

from orderbot.tasks.models import MenuItemTask


def BagelItemTask(
    bread: str = None,
    bagel_type: str = None,  # Alias for bread (backward compat)
    toasted: bool = None,
    spread: str = None,
    extras: list = None,
    quantity: int = 1,
    unit_price: float = 0.0,
    **kwargs
) -> MenuItemTask:
    """Create a MenuItemTask configured as a bagel.

    Args:
        bread: The bagel type (e.g., "plain", "everything")
        bagel_type: Alias for bread (backward compatibility)
        toasted: Whether the bagel should be toasted
        spread: The spread type
        extras: List of extra toppings
        quantity: Number of bagels
        unit_price: Price per bagel
        **kwargs: Additional attribute values to set

    Returns:
        MenuItemTask with menu_item_type="bagel" and attributes set
    """
    # Support both bread and bagel_type parameter names
    bread_value = bread or bagel_type
    if not bread_value:
        bread_value = "plain"  # Default

    attribute_values = {"bread": bread_value}
    if toasted is not None:
        attribute_values["toasted"] = toasted
    if spread:
        attribute_values["spread"] = spread
    if extras:
        attribute_values["toppings"] = extras
    attribute_values.update(kwargs)

    return MenuItemTask(
        menu_item_name=f"{bread_value.title()} Bagel",
        menu_item_type="bagel",
        quantity=quantity,
        unit_price=unit_price,
        attribute_values=attribute_values,
    )


def CoffeeItemTask(
    drink_type: str = None,
    size: str = None,
    iced: bool = None,
    milk: str = None,
    sweeteners: list = None,
    flavor_syrups: list = None,
    extra_shots: int = 0,
    decaf: bool = False,
    quantity: int = 1,
    unit_price: float = 0.0,
    **kwargs
) -> MenuItemTask:
    """Create a MenuItemTask configured as a coffee/beverage.

    Args:
        drink_type: The drink type (e.g., "latte", "coffee", "cappuccino")
        size: The drink size (e.g., "small", "medium", "large")
        iced: Whether the drink is iced
        milk: Milk type (stored as modifier)
        sweeteners: List of sweeteners (stored as modifiers)
        flavor_syrups: List of flavor syrups (stored as modifiers)
        extra_shots: Number of extra espresso shots
        decaf: Whether the drink is decaf
        quantity: Number of drinks
        unit_price: Price per drink
        **kwargs: Additional attribute values to set

    Returns:
        MenuItemTask with menu_item_type="sized_beverage" and attributes set
    """
    attribute_values = {}
    # Default size to "medium" if not specified (sized_beverage items require size)
    attribute_values["size"] = size or "medium"
    if iced is not None:
        attribute_values["temperature"] = "iced" if iced else "hot"
    if extra_shots:
        attribute_values["extra_shots"] = extra_shots
    if decaf:
        attribute_values["decaf"] = decaf
    attribute_values.update(kwargs)

    item = MenuItemTask(
        menu_item_name=drink_type or "Coffee",
        menu_item_type="sized_beverage",
        quantity=quantity,
        unit_price=unit_price,
        attribute_values=attribute_values,
    )

    # Add modifiers
    if milk:
        item.add_modifier(category="milk", slug=milk)
    if sweeteners:
        for s in sweeteners:
            if isinstance(s, dict):
                item.add_modifier(category="sweetener", slug=s.get("slug", ""), quantity=s.get("quantity", 1))
            else:
                item.add_modifier(category="sweetener", slug=str(s))
    if flavor_syrups:
        for s in flavor_syrups:
            if isinstance(s, dict):
                item.add_modifier(category="syrup", slug=s.get("slug", ""), quantity=s.get("quantity", 1))
            else:
                item.add_modifier(category="syrup", slug=str(s))

    return item
