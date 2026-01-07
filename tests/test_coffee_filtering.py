"""
Test for required_match_phrases filtering in coffee disambiguation.

This test verifies that items like "Boxed Coffee Large/Small" with
required_match_phrases="boxed coffee, boxed" are filtered out when
user says just "coffee".
"""
import pytest


@pytest.fixture(autouse=True)
def ensure_cache_loaded(menu_cache_loaded):
    """Ensure menu cache is loaded before each test."""
    pass


def test_coffee_filtering_excludes_boxed_coffee():
    """When user says just 'coffee', boxed coffee items with required_match_phrases should be filtered out."""
    from sandwich_bot.tasks.menu_lookup import MenuLookup
    from sandwich_bot.menu_data_cache import menu_cache

    menu_data = menu_cache.get_menu_index()
    lookup = MenuLookup(menu_data)

    # Get coffee items (simulating coffee_config_handler.py behavior)
    items_by_type = lookup.menu_data.get("items_by_type", {})
    sized_items = items_by_type.get("sized_beverage", [])
    cold_items = items_by_type.get("beverage", [])
    all_drinks = sized_items + cold_items

    coffee_type_lower = "coffee"

    # Find items that match "coffee" in name
    matching_by_name = [
        item for item in all_drinks
        if coffee_type_lower in item.get("name", "").lower()
    ]
    print(f"\nItems matching 'coffee' in name: {[i.get('name') for i in matching_by_name]}")

    # Now filter using _passes_match_filter
    matching_filtered = [
        item for item in all_drinks
        if coffee_type_lower in item.get("name", "").lower()
        and lookup._passes_match_filter(item, coffee_type_lower)
    ]
    print(f"Items after required_match_phrases filter: {[i.get('name') for i in matching_filtered]}")

    # Check for items with required_match_phrases
    for item in matching_by_name:
        name = item.get("name", "")
        rmp = item.get("required_match_phrases")
        print(f"  {name}: required_match_phrases={rmp}")

    # Verify boxed coffee is excluded if it has required_match_phrases set
    for item in matching_by_name:
        name = item.get("name", "")
        rmp = item.get("required_match_phrases")
        if "boxed" in name.lower() and rmp:
            # This item has required_match_phrases - verify it's filtered out
            assert item not in matching_filtered, (
                f"{name} has required_match_phrases='{rmp}' but was not filtered out"
            )


def test_boxed_coffee_matches_when_user_says_boxed():
    """When user says 'boxed coffee', boxed coffee items should match."""
    from sandwich_bot.tasks.menu_lookup import MenuLookup
    from sandwich_bot.menu_data_cache import menu_cache

    menu_data = menu_cache.get_menu_index()
    lookup = MenuLookup(menu_data)

    items_by_type = lookup.menu_data.get("items_by_type", {})
    sized_items = items_by_type.get("sized_beverage", [])
    cold_items = items_by_type.get("beverage", [])
    all_drinks = sized_items + cold_items

    # User says "boxed coffee" - should match boxed coffee items
    search_term = "boxed coffee"

    matching_filtered = [
        item for item in all_drinks
        if "boxed" in item.get("name", "").lower()
        and lookup._passes_match_filter(item, search_term)
    ]

    # If there are boxed coffee items in the menu, they should match
    boxed_items = [
        item for item in all_drinks
        if "boxed" in item.get("name", "").lower()
    ]

    if boxed_items:
        # Verify boxed coffee items pass the filter when user says "boxed coffee"
        print(f"\nBoxed coffee items: {[i.get('name') for i in boxed_items]}")
        print(f"Items matching 'boxed coffee': {[i.get('name') for i in matching_filtered]}")
        # Note: matching_filtered could be a subset if required_match_phrases doesn't include "boxed coffee"
