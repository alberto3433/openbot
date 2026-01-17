"""
Test Helpers Package.

This package contains helper functions for tests. These are domain-specific
utilities that encode knowledge about specific menu items, categories, etc.

IMPORTANT: These helpers are ONLY for tests. They must NOT be imported
by any code in sandwich_bot/ - production code must be data-driven.
"""

# Re-export from orderbot.tasks.models for convenience
from orderbot.tasks.models import MenuItemTask, TaskStatus

# Task factory helpers
from .task_factories import (
    create_bagel_task,
    create_coffee_task,
    BagelItemTask,
    CoffeeItemTask,
    is_bagel_item,
    is_coffee_item,
)

# Menu helpers
from .menu_helpers import test_is_soda_drink

# Parsed item query helpers
from .parsed_item_queries import (
    get_parsed_items,
    get_parsed_item,
    has_parsed_item,
    count_parsed_items,
    get_signature_item,
    has_signature_item,
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
    # Task factories
    "create_bagel_task",
    "create_coffee_task",
    "BagelItemTask",
    "CoffeeItemTask",
    "is_bagel_item",
    "is_coffee_item",
    # Menu helpers
    "test_is_soda_drink",
    # Parsed item queries
    "get_parsed_items",
    "get_parsed_item",
    "has_parsed_item",
    "count_parsed_items",
    "get_signature_item",
    "has_signature_item",
    "get_bagel_item",
    "has_bagel",
    "get_coffee_item",
    "has_coffee",
    "get_menu_item",
    "has_menu_item",
    "get_side_item",
    "has_side_item",
]
