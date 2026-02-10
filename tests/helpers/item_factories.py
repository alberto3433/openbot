"""
Test Item Factory Functions.

Factory functions for creating MenuItemTask instances for testing.
These functions provide convenient ways to create items with specific types
and attributes without having to specify all the details manually.

IMPORTANT: These helpers are ONLY for tests. They must NOT be imported
by any code in orderbot/ - production code must be data-driven.
"""

from typing import List, Tuple, Union

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


def _set_modifier_price(item: "MenuItemTask", category: str, slug: str, price: float) -> None:
    """Set the price on a modifier that was already added.

    This is a test-only helper to set prices on modifiers. In production,
    prices are calculated by PricingEngine.recalculate_item_price() using
    GlobalAttributeOption.price_modifier as the single source of truth.

    Args:
        item: The menu item task
        category: The modifier's category
        slug: The modifier's slug
        price: The price to set
    """
    for mod in item.modifiers:
        if mod.get("category") == category and mod.get("slug") == slug:
            mod["price"] = price
            return
    # If not found by exact slug match, try matching by category only (for spread, etc.)
    if slug:
        for mod in item.modifiers:
            if mod.get("category") == category:
                mod["price"] = price
                return


def BagelItemTask(
    bread: str = _UNSET,
    bagel_type: str = _UNSET,  # Alias for bread (backward compat)
    bagel_type_upcharge: float = 0.0,
    toasted: bool = None,
    spread: str = None,
    spread_type: str = None,  # Alias for spread (backward compat)
    spread_price: float = 0.0,
    extras: list = None,
    proteins: List[Union[str, Tuple[str, float]]] = None,
    quantity: int = 1,
    unit_price: float = 0.0,
    base_price: float = 0.0,
    **kwargs
) -> MenuItemTask:
    """Create a MenuItemTask configured as a bagel.

    Args:
        bread: The bagel type (e.g., "plain", "everything"). Pass None explicitly
               to create a bagel without bread set (for testing incomplete items).
        bagel_type: Alias for bread (backward compatibility)
        bagel_type_upcharge: Price modifier for bagel type (e.g., 0.80 for gluten free)
        toasted: Whether the bagel should be toasted
        spread: The spread type
        spread_type: Alias for spread (backward compatibility)
        spread_price: Price modifier for spread
        extras: List of extra toppings
        proteins: List of protein modifiers with prices (e.g., [("nova scotia salmon", 6.00)])
        quantity: Number of bagels
        unit_price: Final price per bagel (if 0, will use base_price + modifiers)
        base_price: Base bagel price before modifiers (default $2.20 if using pricing)
        **kwargs: Additional attribute values to set

    Returns:
        MenuItemTask with menu_item_type="bagel" and attributes set
    """
    # Support both bread and bagel_type parameter names
    # Use sentinel to detect if explicitly passed as None vs not passed
    # When neither is specified, leave bread unset (for testing incomplete items)
    if bread is not _UNSET:
        bread_value = bread
    elif bagel_type is not _UNSET:
        bread_value = bagel_type
    else:
        bread_value = None  # No default - allows testing incomplete items

    # Support both spread and spread_type parameter names
    spread_value = spread_type if spread_type else spread

    # Menu item name is always "Bagel" - the bread type is stored as a selection
    # This matches how the production system works: menu_item_name is the base item,
    # and selections (like bread type) customize it
    menu_name = "Bagel"

    # Determine the effective base price
    # Default to 2.20 if not explicitly provided but pricing modifiers are present
    effective_base = base_price if base_price > 0 else 2.20

    # Create the bagel using add_selection for proper modifier tracking
    bagel = MenuItemTask(
        menu_item_name=menu_name,
        menu_item_type="bagel",
        quantity=quantity,
        unit_price=effective_base,  # Start with base, add_selection will add modifier prices
        base_price=effective_base,
    )

    # Set properties via selections API
    # Note: add_selection no longer accepts price - prices are set separately for tests
    if toasted is not None:
        bagel.add_selection("yes" if toasted else "no", "toasted")
    if spread_value:
        bagel.add_selection(spread_value, "spread")
        if spread_price > 0:
            _set_modifier_price(bagel, "spread", spread_value, spread_price)
    if bread_value:
        # Include display_name for bread - the "Bagel" suffix is added by get_display_name()
        # when looking up from menu_cache. For tests without menu_cache, display_name
        # should be just the bread type (e.g., "Everything") as it will be looked up.
        bagel.add_selection(
            bread_value,
            "bread",
            display_name=f"{bread_value.title()} Bagel"  # Full name for test contexts
        )
        if bagel_type_upcharge > 0:
            _set_modifier_price(bagel, "bread", bread_value, bagel_type_upcharge)
    if extras:
        for extra in extras:
            bagel.add_selection(extra, "toppings")
    if proteins:
        for protein in proteins:
            if isinstance(protein, tuple):
                protein_name, protein_price = protein
                bagel.add_selection(protein_name, "protein")
                if protein_price > 0:
                    _set_modifier_price(bagel, "protein", protein_name, protein_price)
            else:
                bagel.add_selection(protein, "protein")

    # Apply any additional kwargs
    for key, val in kwargs.items():
        bagel[key] = val

    # If explicit unit_price was provided and differs from calculated, use it
    if unit_price > 0 and unit_price != bagel.unit_price:
        bagel.unit_price = unit_price

    return bagel


def CoffeeItemTask(
    drink_type: str = None,
    size: str = None,
    iced: bool = None,
    milk: str = None,
    milk_upcharge: float = 0.0,
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
        milk_upcharge: Price modifier for milk (e.g., 0.50 for oat milk)
        sweeteners: List of sweeteners (stored as modifiers)
        flavor_syrups: List of flavor syrups (stored as modifiers)
        extra_shots: Number of extra espresso shots
        decaf: Whether the drink is decaf
        quantity: Number of drinks
        unit_price: Price per drink
        **kwargs: Additional attribute values to set

    Returns:
        MenuItemTask with appropriate menu_item_type ("espresso_based_beverage" for lattes/cappuccinos, "espresso" for plain espresso, "coffee_based_beverage" for coffee/tea)
    """
    # Determine item type based on drink type
    # Plain espresso has its own type (no size attribute)
    # Espresso-based drinks (latte, cappuccino, etc.) have size attribute
    drink_type_lower = (drink_type or "").lower()

    if drink_type_lower == "espresso":
        menu_item_type = "espresso"
    elif any(e in drink_type_lower for e in {"latte", "cappuccino", "americano", "macchiato", "matcha"}):
        menu_item_type = "espresso_based_beverage"
    else:
        menu_item_type = "coffee_based_beverage"

    item = MenuItemTask(
        menu_item_name=drink_type or "Coffee",
        menu_item_type=menu_item_type,
        quantity=quantity,
        unit_price=unit_price,
    )

    # Set properties via selections API
    if size:
        item.add_selection(size, "size")
    if iced is not None:
        item.add_selection("iced" if iced else "hot", "temperature")
    if decaf:
        item.add_selection("yes" if decaf else "no", "decaf")
    # Use milk_sweetener_syrup as category for all milk/sweetener/syrup selections
    # This matches the database schema where espresso items have a single multi-select
    # attribute called milk_sweetener_syrup that holds all three types
    if milk:
        item.add_selection(slug=milk, category="milk_sweetener_syrup")
        if milk_upcharge > 0:
            _set_modifier_price(item, "milk_sweetener_syrup", milk, milk_upcharge)
    if sweeteners:
        for s in sweeteners:
            if isinstance(s, dict):
                item.add_selection(slug=s.get("slug", ""), category="milk_sweetener_syrup", quantity=s.get("quantity", 1))
            else:
                item.add_selection(slug=str(s), category="milk_sweetener_syrup")
    if flavor_syrups:
        for s in flavor_syrups:
            if isinstance(s, dict):
                item.add_selection(slug=s.get("slug", ""), category="milk_sweetener_syrup", quantity=s.get("quantity", 1))
            else:
                item.add_selection(slug=str(s), category="milk_sweetener_syrup")
    if extra_shots:
        item.add_selection(str(extra_shots), "extra_shots")

    # Apply any additional kwargs
    for key, val in kwargs.items():
        item[key] = val

    return item


# =============================================================================
# Backward-compatible aliases
# =============================================================================

# Aliases for backward compatibility with existing test code that uses
# create_bagel_task and create_coffee_task function names
create_bagel_task = BagelItemTask
create_coffee_task = CoffeeItemTask
