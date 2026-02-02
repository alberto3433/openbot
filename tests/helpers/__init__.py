"""
Test Helpers Package.

This package contains helper functions for tests. These are domain-specific
utilities that encode knowledge about specific menu items, categories, etc.

IMPORTANT: These helpers are ONLY for tests. They must NOT be imported
by any code in sandwich_bot/ - production code must be data-driven.
"""

# Re-export from orderbot.tasks.models for convenience
from orderbot.tasks.models import MenuItemTask, TaskStatus

# Menu helpers
from .menu_helpers import test_is_soda_drink

# Test item factory functions
from .item_factories import (
    BagelItemTask,
    CoffeeItemTask,
    create_bagel_task,
    create_coffee_task,
)

# Menu data factory functions
from .menu_data_factories import (
    create_minimal_menu_data,
    create_bagel_menu_data,
    create_beverage_menu_data,
    create_test_menu_data,
    create_full_menu_data,
)

# Generic menu data builder
from .menu_data_builder import MenuDataBuilder

# Parsed item query helpers
from .parsed_item_queries import (
    get_parsed_items,
    get_parsed_item,
    has_parsed_item,
    count_parsed_items,
    get_item_with_defaults,
    has_item_with_defaults,
    get_signature_item,  # Backward compatibility alias
    has_signature_item,  # Backward compatibility alias
    get_bagel_item,
    has_bagel,
    get_coffee_item,
    has_coffee,
    get_menu_item,
    has_menu_item,
    get_side_item,
    has_side_item,
)

__all__ = [
    # Re-exports from orderbot.tasks.models
    "MenuItemTask",
    "TaskStatus",
    # Menu helpers
    "test_is_soda_drink",
    # Test item factory functions
    "BagelItemTask",
    "CoffeeItemTask",
    "create_bagel_task",
    "create_coffee_task",
    # Menu data factory functions
    "create_minimal_menu_data",
    "create_bagel_menu_data",
    "create_beverage_menu_data",
    "create_test_menu_data",
    "create_full_menu_data",
    # Generic menu data builder
    "MenuDataBuilder",
    # Parsed item queries
    "get_parsed_items",
    "get_parsed_item",
    "has_parsed_item",
    "count_parsed_items",
    "get_item_with_defaults",
    "has_item_with_defaults",
    "get_signature_item",  # Backward compatibility alias
    "has_signature_item",  # Backward compatibility alias
    "get_bagel_item",
    "has_bagel",
    "get_coffee_item",
    "has_coffee",
    "get_menu_item",
    "has_menu_item",
    "get_side_item",
    "has_side_item",
]
