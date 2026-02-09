"""
Base Repository.

Provides the base class for all repositories with common functionality.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orderbot.cache import MenuDataCache


class BaseRepository:
    """Base class for all repositories.

    Provides access to the underlying cache and common utilities.
    """

    def __init__(self, cache: "MenuDataCache"):
        """Initialize the repository with a cache reference.

        Args:
            cache: The MenuDataCache instance to delegate queries to
        """
        self._cache = cache

    @property
    def cache(self) -> "MenuDataCache":
        """Access the underlying cache."""
        return self._cache

    def is_loaded(self) -> bool:
        """Check if the cache is loaded and ready for queries."""
        return self._cache._is_loaded
