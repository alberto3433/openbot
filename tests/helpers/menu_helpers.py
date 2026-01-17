"""
Menu Test Helpers.

Domain-specific helper functions for testing menu-related functionality.
These functions encode knowledge about specific menu items and categories.

IMPORTANT: These helpers are ONLY for tests. They must NOT be imported
by any code in orderbot/ - production code must be data-driven.
"""


def test_is_soda_drink(drink_type: str | None) -> bool:
    """Check if a drink type is a soda/cold beverage that doesn't need configuration.

    Uses database-loaded soda types (via get_soda_types()) which includes
    both item names and their aliases from the menu_items.aliases column.

    Sized beverages (coffee, latte, etc.) are explicitly excluded even if
    they appear in soda types due to bottled versions (e.g., "Bottled Coffee").

    Args:
        drink_type: The drink type to check (e.g., "coke", "sprite", "latte")

    Returns:
        True if the drink is a soda/bottled beverage, False otherwise.
    """
    if not drink_type:
        return False
    drink_lower = drink_type.lower().strip()

    # Import here to avoid circular imports and keep this test-only
    from orderbot.tasks.parsers.constants import get_coffee_types, get_soda_types

    # Sized beverages (coffee, latte, tea, etc.) are NEVER sodas - they need configuration
    # This prevents "Coffee" from matching "Bottled Coffee" in soda types
    coffee_types = get_coffee_types()
    if drink_lower in coffee_types:
        return False

    # Check exact match only - database includes aliases so substring matching is unnecessary
    # and causes false positives (e.g., "coffee" matching "bottled coffee")
    soda_types = get_soda_types()
    return drink_lower in soda_types
