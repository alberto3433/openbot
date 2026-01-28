"""
Cache package - exports menu_cache singleton.

This package provides the MenuDataCache class and a pre-instantiated singleton
for thread-safe access to cached menu data throughout the application.

Usage:
    from orderbot.cache import menu_cache

    # At application startup
    menu_cache.load_from_db(db_session)

    # Throughout the application
    items = menu_cache.get_known_menu_items()
    normalized = menu_cache.normalize_modifier("lox")
"""

from .core import MenuDataCache
from .base import singularize, pluralize, get_singular_plural_variants

# Singleton instance
menu_cache = MenuDataCache()

__all__ = ["menu_cache", "MenuDataCache", "singularize", "pluralize", "get_singular_plural_variants"]
