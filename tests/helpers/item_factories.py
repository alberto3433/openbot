"""
Test Item Factory Functions.

Factory functions for creating MenuItemTask instances for testing.
These functions provide convenient ways to create items with specific types
and attributes without having to specify all the details manually.

IMPORTANT: These helpers are ONLY for tests. They must NOT be imported
by any code in orderbot/ - production code must be data-driven.
"""

from orderbot.tasks.models import MenuItemTask

# Sentinel to distinguish between "not passed" and "explicitly passed as None"
_UNSET = object()


def _convert_attrs_to_selections(attribute_values: dict) -> list[dict]:
    """Convert attribute_values dict to selections list.

    This is needed because Pydantic doesn't call property setters during __init__.
    """
    selections = []
    for key, val in attribute_values.items():
        if isinstance(val, bool):
            selections.append({"slug": "yes" if val else "no", "category": key, "quantity": 1, "price": 0})
        elif isinstance(val, list):
            for v in val:
                if isinstance(v, dict):
                    selections.append(v)
                else:
                    selections.append({"slug": str(v), "category": key, "quantity": 1, "price": 0})
        elif val is not None:
            selections.append({"slug": str(val), "category": key, "quantity": 1, "price": 0})
    return selections


def BagelItemTask(
    bread: str = _UNSET,
    bagel_type: str = _UNSET,  # Alias for bread (backward compat)
    toasted: bool = None,
    spread: str = None,
    extras: list = None,
    quantity: int = 1,
    unit_price: float = 0.0,
    **kwargs
) -> MenuItemTask:
    """Create a MenuItemTask configured as a bagel.

    Args:
        bread: The bagel type (e.g., "plain", "everything"). Pass None explicitly
               to create a bagel without bread set (for testing incomplete items).
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
    # Use sentinel to detect if explicitly passed as None vs not passed
    if bread is not _UNSET:
        bread_value = bread
    elif bagel_type is not _UNSET:
        bread_value = bagel_type
    else:
        bread_value = "plain"  # Default when neither is specified

    attribute_values = {}
    if bread_value is not None:
        attribute_values["bread"] = bread_value
    if toasted is not None:
        attribute_values["toasted"] = toasted
    if spread:
        attribute_values["spread"] = spread
    if extras:
        attribute_values["toppings"] = extras
    attribute_values.update(kwargs)

    # Handle menu_item_name when bread is not set
    if bread_value:
        menu_name = f"{bread_value.title()} Bagel"
    else:
        menu_name = "Bagel"

    # Convert attribute_values to selections (Pydantic doesn't use property setters during init)
    selections = _convert_attrs_to_selections(attribute_values)

    return MenuItemTask(
        menu_item_name=menu_name,
        menu_item_type="bagel",
        quantity=quantity,
        unit_price=unit_price,
        selections=selections,
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

    # Convert attribute_values to selections (Pydantic doesn't use property setters during init)
    selections = _convert_attrs_to_selections(attribute_values)

    item = MenuItemTask(
        menu_item_name=drink_type or "Coffee",
        menu_item_type="sized_beverage",
        quantity=quantity,
        unit_price=unit_price,
        selections=selections,
    )

    # Add selections (modifiers)
    if milk:
        item.add_selection(slug=milk, category="milk")
    if sweeteners:
        for s in sweeteners:
            if isinstance(s, dict):
                item.add_selection(slug=s.get("slug", ""), category="sweetener", quantity=s.get("quantity", 1))
            else:
                item.add_selection(slug=str(s), category="sweetener")
    if flavor_syrups:
        for s in flavor_syrups:
            if isinstance(s, dict):
                item.add_selection(slug=s.get("slug", ""), category="syrup", quantity=s.get("quantity", 1))
            else:
                item.add_selection(slug=str(s), category="syrup")

    return item
