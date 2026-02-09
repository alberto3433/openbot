"""
Repository Layer for Orderbot.

This module provides a clean abstraction over the cache layer, grouping related
queries into domain-focused repositories. The repositories delegate to the existing
MenuDataCache while providing a more organized API.

Usage:
    from orderbot.repositories import Repositories, get_repositories

    # Get the singleton instance
    repos = get_repositories()

    # Use individual repositories
    menu_item = repos.menu.find_by_name("Plain Bagel")
    ingredient = repos.ingredients.get_by_slug("cheddar_cheese")
    attrs = repos.attributes.get_for_item_type("bagel")

Architecture:
    Repositories (facade)
    ├── MenuRepository - Menu item lookups and searches
    ├── IngredientRepository - Ingredient and modifier queries
    ├── AttributeRepository - Global attributes and options
    └── PricingRepository - Price lookups

All repositories wrap the existing MenuDataCache methods for backward compatibility.
"""

from .base import BaseRepository
from .menu_repository import MenuRepository
from .ingredient_repository import IngredientRepository
from .attribute_repository import AttributeRepository
from .pricing_repository import PricingRepository
from .facade import Repositories, get_repositories

__all__ = [
    # Base class
    "BaseRepository",
    # Individual repositories
    "MenuRepository",
    "IngredientRepository",
    "AttributeRepository",
    "PricingRepository",
    # Facade
    "Repositories",
    "get_repositories",
]
