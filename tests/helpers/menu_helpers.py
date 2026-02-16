"""
Menu Test Helpers.

Domain-specific helper functions for testing menu-related functionality.
These functions encode knowledge about specific menu items and categories.

IMPORTANT: These helpers are ONLY for tests. They must NOT be imported
by any code in orderbot/ - production code must be data-driven.
"""


def test_is_soda_drink(drink_type: str | None) -> bool:
    """Check if a drink type is a soda/cold beverage that doesn't need configuration.

    Uses database-loaded beverage item names which includes
    both item names and their aliases from the menu_items.aliases column.

    Configurable items (coffee, latte, etc.) are explicitly excluded even if
    they appear in beverage types due to bottled versions (e.g., "Bottled Coffee").

    Args:
        drink_type: The drink type to check (e.g., "coke", "sprite", "latte")

    Returns:
        True if the drink is a soda/bottled beverage, False otherwise.
    """
    if not drink_type:
        return False
    drink_lower = drink_type.lower().strip()

    # Import here to avoid circular imports and keep this test-only
    from orderbot.cache import menu_cache

    # Configurable items (coffee, latte, tea, etc.) are NEVER sodas - they need configuration
    # This prevents "Coffee" from matching "Bottled Coffee" in beverage types
    configurable_item_names = menu_cache.get_configurable_item_names()
    if drink_lower in configurable_item_names:
        return False

    # Check exact match only - database includes aliases so substring matching is unnecessary
    # and causes false positives (e.g., "coffee" matching "bottled coffee")
    # Check soda and all non-configurable beverage sub-types
    non_config_types = ["soda", "juice", "water", "smoothie", "kombucha",
                        "energy_drink", "bottled_tea", "other_bottled"]
    for item_type in non_config_types:
        if drink_lower in menu_cache.get_item_names(item_type):
            return True
    return False
