"""
Repository Facade.

Provides a unified interface to all repositories.
"""

import threading
from typing import TYPE_CHECKING

from .menu_repository import MenuRepository
from .ingredient_repository import IngredientRepository
from .attribute_repository import AttributeRepository
from .pricing_repository import PricingRepository

if TYPE_CHECKING:
    from orderbot.cache import MenuDataCache


class Repositories:
    """Singleton facade providing access to all repositories.

    Usage:
        repos = Repositories.get_instance()
        item = repos.menu.find_by_name("Plain Bagel")
    """

    _instance: "Repositories | None" = None
    _lock = threading.Lock()

    def __init__(self, cache: "MenuDataCache"):
        """Initialize all repositories with the cache.

        Args:
            cache: The MenuDataCache instance to use
        """
        self._cache = cache
        self._menu = MenuRepository(cache)
        self._ingredients = IngredientRepository(cache)
        self._attributes = AttributeRepository(cache)
        self._pricing = PricingRepository(cache)

    @classmethod
    def get_instance(cls, cache: "MenuDataCache | None" = None) -> "Repositories":
        """Get the singleton Repositories instance.

        Args:
            cache: Optional cache instance. If not provided, uses menu_cache.

        Returns:
            The singleton Repositories instance
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    if cache is None:
                        from orderbot.cache import menu_cache
                        cache = menu_cache
                    cls._instance = cls(cache)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance.

        Used primarily for testing.
        """
        with cls._lock:
            cls._instance = None

    # =========================================================================
    # Repository Accessors
    # =========================================================================

    @property
    def menu(self) -> MenuRepository:
        """Access the menu repository."""
        return self._menu

    @property
    def ingredients(self) -> IngredientRepository:
        """Access the ingredient repository."""
        return self._ingredients

    @property
    def attributes(self) -> AttributeRepository:
        """Access the attribute repository."""
        return self._attributes

    @property
    def pricing(self) -> PricingRepository:
        """Access the pricing repository."""
        return self._pricing

    @property
    def cache(self) -> "MenuDataCache":
        """Direct access to the underlying cache.

        Use this when you need cache methods not exposed by repositories.
        """
        return self._cache


def get_repositories(cache: "MenuDataCache | None" = None) -> Repositories:
    """Convenience function to get the Repositories singleton.

    Args:
        cache: Optional cache instance. If not provided, uses menu_cache.

    Returns:
        The singleton Repositories instance
    """
    return Repositories.get_instance(cache)
