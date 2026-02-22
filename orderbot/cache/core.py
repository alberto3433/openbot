"""
MenuDataCache orchestrator - inherits all mixins.

This is the main cache class that composes all functionality through mixin inheritance.
"""

import threading

from .base import BaseCacheMixin
from .loaders import LoaderMixin
from .menu_queries import MenuQueryMixin
from .ingredient_queries import IngredientQueryMixin
from .item_type_queries import ItemTypeQueryMixin
from .category_queries import CategoryQueryMixin
from .parsing_queries import ParsingQueryMixin
from .pricing_queries import PricingQueryMixin


class MenuDataCache(
    BaseCacheMixin,
    LoaderMixin,
    MenuQueryMixin,
    IngredientQueryMixin,
    ItemTypeQueryMixin,
    CategoryQueryMixin,
    ParsingQueryMixin,
    PricingQueryMixin,
):
    """
    Thread-safe singleton cache for menu data.

    This class composes all query and loader functionality through mixins,
    providing a single interface for all menu data access.

    Usage:
        from orderbot.cache import menu_cache

        # Load data at startup
        menu_cache.load_from_db(db_session)

        # Query data
        items = menu_cache.get_known_menu_items()
        is_valid = menu_cache.is_known_modifier("bacon")
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._is_loaded = False
        self._company = None
        # Initialize all cache dictionaries from BaseCacheMixin
        self._init_all_caches()

    def reset(self) -> None:
        """Reset the cache to unloaded state.

        This clears all cached data and resets the loaded flag.
        Call load_from_db() to reload data.
        """
        self._is_loaded = False
        self._company = None
        self._init_all_caches()

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (primarily for testing)."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance._initialized = False
                cls._instance._is_loaded = False
                cls._instance = None

    async def start_background_refresh(self, get_db_session) -> None:
        """Start background task to periodically refresh the cache.

        Args:
            get_db_session: A callable that returns a context manager for database sessions.
                           Example: lambda: contextmanager(lambda: (yield SessionLocal()))()
        """
        import asyncio
        import logging
        from datetime import datetime, timedelta

        logger = logging.getLogger(__name__)

        self._get_db_session = get_db_session

        async def refresh_loop():
            """Background loop that refreshes cache daily at configured hour."""
            while True:
                try:
                    # Calculate time until next refresh
                    now = datetime.now()
                    next_refresh = now.replace(
                        hour=self._refresh_hour, minute=0, second=0, microsecond=0
                    )
                    if next_refresh <= now:
                        next_refresh += timedelta(days=1)

                    sleep_seconds = (next_refresh - now).total_seconds()
                    logger.info(
                        "Background refresh scheduled for %s (in %.1f hours)",
                        next_refresh.strftime("%Y-%m-%d %H:%M"),
                        sleep_seconds / 3600,
                    )

                    await asyncio.sleep(sleep_seconds)

                    # Perform refresh
                    logger.info("Starting scheduled cache refresh...")
                    with self._get_db_session() as db:
                        self.load_from_db(db, fail_on_error=False, force=True)
                    logger.info("Scheduled cache refresh completed")

                except asyncio.CancelledError:
                    logger.info("Background refresh task cancelled")
                    break
                except (RuntimeError, ConnectionError, OSError, ValueError, KeyError) as e:
                    logger.error("Error in background refresh: %s", e)
                    # Wait before retrying to avoid tight error loops
                    from ..constants import CACHE_RETRY_DELAY_SECONDS
                    await asyncio.sleep(CACHE_RETRY_DELAY_SECONDS)

        self._refresh_task = asyncio.create_task(refresh_loop())
        logger.info("Background cache refresh task started")

    async def stop_background_refresh(self) -> None:
        """Stop the background refresh task."""
        import logging

        logger = logging.getLogger(__name__)

        if self._refresh_task is not None:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
            self._refresh_task = None
            logger.info("Background cache refresh task stopped")
