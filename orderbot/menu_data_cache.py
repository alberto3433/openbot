"""
Menu Data Cache - Backward compatibility re-export.

This module re-exports from the new modular orderbot.cache package
to maintain backward compatibility with existing imports.

Usage (unchanged):
    from orderbot.menu_data_cache import menu_cache

    # Get ingredients by category (returns set)
    milks = menu_cache.get_ingredients("milk")

    # Find partial matches for disambiguation
    matches = menu_cache.find_menu_item_matches("classic")
    # Returns: ["classic egg sandwich", "classic blt"]

New preferred import:
    from orderbot.cache import menu_cache
"""

from orderbot.cache import menu_cache, MenuDataCache
from orderbot.cache.base import singularize

__all__ = ["menu_cache", "MenuDataCache", "singularize"]
