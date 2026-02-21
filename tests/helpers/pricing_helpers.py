"""
Pricing Test Helpers.

Shared utilities for pricing arithmetic verification tests.
These helpers provide convenient access to the pricing engine, menu data,
and common assertions for verifying price decomposition.

IMPORTANT: These helpers are ONLY for tests. They must NOT be imported
by any code in orderbot/ - production code must be data-driven.
"""

from __future__ import annotations

from typing import Any

import pytest

from orderbot.cache import menu_cache
from orderbot.tasks.models import MenuItemTask, OrderTask, TaskStatus
from orderbot.tasks.pricing import PricingEngine
from orderbot.tasks.adapter import _calculate_subtotal, order_task_to_dict
from orderbot.services.tax_utils import calculate_order_total


def get_menu_data() -> dict:
    """Get the global menu data loaded by conftest."""
    from orderbot.tasks.state_machine import _global_menu_data
    assert _global_menu_data is not None, (
        "Global menu_data not loaded - menu_cache_loaded fixture must run first"
    )
    return _global_menu_data


def get_pricing_engine() -> PricingEngine:
    """Create a PricingEngine using the real DB-loaded menu data."""
    from orderbot.tasks.menu_lookup import MenuLookup
    menu_data = get_menu_data()
    lookup = MenuLookup(menu_data)
    return PricingEngine(menu_data, lookup.lookup_menu_item)


def find_menu_items_by_type(item_type_slug: str) -> list[dict]:
    """Find all menu items of a given type from the loaded menu data."""
    menu_data = get_menu_data()
    return menu_data.get("items_by_type", {}).get(item_type_slug, [])


def find_first_menu_item(item_type_slug: str) -> dict | None:
    """Find the first menu item of a given type."""
    items = find_menu_items_by_type(item_type_slug)
    return items[0] if items else None


def find_menu_item_by_name(name: str) -> dict | None:
    """Find a menu item by name across all types."""
    menu_data = get_menu_data()
    for type_slug, items in menu_data.get("items_by_type", {}).items():
        for item in items:
            if item.get("name", "").lower() == name.lower():
                return item
    return None


def get_priced_options(item_type_slug: str) -> list[dict]:
    """Get all attribute options with price_modifier > 0 for an item type."""
    menu_data = get_menu_data()
    type_data = menu_data.get("item_types", {}).get(item_type_slug, {})
    results = []
    for attr in type_data.get("attributes", []):
        attr_slug = attr.get("slug", "")
        for opt in attr.get("options", []):
            price = opt.get("price_modifier") or opt.get("price") or 0.0
            if price > 0:
                results.append({
                    "attr_slug": attr_slug,
                    "option_slug": opt.get("slug", ""),
                    "option_display": opt.get("display_name", ""),
                    "price_modifier": price,
                })
    return results


def get_zero_price_options(item_type_slug: str) -> list[dict]:
    """Get all attribute options with price_modifier == 0 for an item type."""
    menu_data = get_menu_data()
    type_data = menu_data.get("item_types", {}).get(item_type_slug, {})
    results = []
    for attr in type_data.get("attributes", []):
        attr_slug = attr.get("slug", "")
        for opt in attr.get("options", []):
            price = opt.get("price_modifier") or opt.get("price") or 0.0
            if price == 0:
                results.append({
                    "attr_slug": attr_slug,
                    "option_slug": opt.get("slug", ""),
                    "option_display": opt.get("display_name", ""),
                    "price_modifier": 0.0,
                })
    return results


def get_all_item_type_slugs() -> list[str]:
    """Get all item type slugs from loaded menu data."""
    menu_data = get_menu_data()
    return list(menu_data.get("item_types", {}).keys())


def create_item_with_selections(
    menu_item_name: str,
    item_type: str,
    selections: list[tuple[str, str]] | None = None,
    quantity: int = 1,
) -> MenuItemTask:
    """Create a MenuItemTask with given selections for pricing tests.

    Args:
        menu_item_name: Name of the menu item
        item_type: Item type slug
        selections: List of (slug, category) tuples
        quantity: Item quantity
    """
    item = MenuItemTask(
        menu_item_name=menu_item_name,
        menu_item_type=item_type,
        quantity=quantity,
    )
    if selections:
        for slug, category in selections:
            item.add_selection(slug, category)
    return item


def build_order_with_items(items: list[MenuItemTask]) -> OrderTask:
    """Build an OrderTask with the given items."""
    order = OrderTask()
    for item in items:
        order.items.add_item(item)
    return order


def make_store_info(
    city_tax_rate: float = 0.045,
    state_tax_rate: float = 0.04,
    delivery_fee: float = 3.99,
) -> dict:
    """Create a store_info dict for tax tests."""
    return {
        "city_tax_rate": city_tax_rate,
        "state_tax_rate": state_tax_rate,
        "delivery_fee": delivery_fee,
    }
