"""
Core Loader for MenuDataCache.

Contains the main load/load_from_db methods and orchestrates all specialized loaders.
Inherits from all specialized loader mixins.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from .menu_items import MenuItemLoaderMixin
from .ingredients import IngredientLoaderMixin
from .item_types import ItemTypeLoaderMixin
from .patterns import PatternLoaderMixin

if TYPE_CHECKING:
    from ..provider import MenuProvider

logger = logging.getLogger(__name__)


class LoaderMixin(
    MenuItemLoaderMixin,
    IngredientLoaderMixin,
    ItemTypeLoaderMixin,
    PatternLoaderMixin,
):
    """
    Combined loader mixin for MenuDataCache.

    Inherits from all specialized loader mixins and provides the main
    load/load_from_db orchestration methods.
    """

    def load_from_db(self, db: Session, fail_on_error: bool = True, force: bool = False) -> None:
        """Load all menu data from a PostgreSQL database.

        Backward-compatible entry point that wraps DatabaseProvider.

        Args:
            db: SQLAlchemy database session
            fail_on_error: If True, raise exception on DB errors (for startup)
                          If False, log warning and keep existing cache
            force: If True, reload even if already loaded (for manual refresh)

        Raises:
            RuntimeError: If fail_on_error=True and DB load fails
        """
        from ..provider import DatabaseProvider

        self.load(DatabaseProvider(db), fail_on_error=fail_on_error, force=force)

    def load(self, provider: MenuProvider, fail_on_error: bool = True, force: bool = False) -> None:
        """Load all menu data from the given provider.

        This is the primary entry point for loading menu data. The provider
        abstracts the data source (database, Square API, etc.).

        Args:
            provider: A MenuProvider implementation that supplies menu data
            fail_on_error: If True, raise exception on load errors (for startup)
                          If False, log warning and keep existing cache
            force: If True, reload even if already loaded (for manual refresh)

        Raises:
            RuntimeError: If fail_on_error=True and load fails
        """
        from datetime import datetime

        # Skip if already loaded (unless forced)
        if self._is_loaded and not force:
            logger.info("Menu data cache already loaded, skipping reload")
            return

        with self._refresh_lock:
            # Double-check after acquiring lock
            if self._is_loaded and not force:
                logger.info("Menu data cache already loaded, skipping reload")
                return

            try:
                logger.info("Loading menu data cache...")

                # Bulk load all tables from provider
                bulk_data = provider.load_bulk_data()

                # All loaders now use bulk_data to avoid duplicate queries
                self._load_known_menu_items_from_bulk(bulk_data)
                self._load_items_with_defaults_aliases_from_bulk(bulk_data)
                self._load_modifier_aliases_from_bulk(bulk_data)
                self._load_side_items_from_bulk(bulk_data)
                self._load_category_keywords_from_bulk(bulk_data)
                self._load_abbreviations_from_bulk(bulk_data)
                self._load_item_type_fields_from_bulk(bulk_data)
                self._load_response_patterns_from_bulk(bulk_data)
                self._load_modifier_qualifiers_from_bulk(bulk_data)
                self._load_global_attribute_options_from_bulk(bulk_data)
                self._load_global_attribute_aliases_from_bulk(bulk_data)
                self._load_item_type_metadata_from_bulk(bulk_data)
                self._menu_index = provider.load_menu_index()

                # Build prefix index for queries like "what iced drinks do you have?"
                self._build_prefix_index_from_menu_index()

                # Data-driven parsing support loaders
                self._load_compound_phrases_from_bulk(bulk_data)
                self._load_item_type_triggers_from_bulk(bulk_data)
                self._load_configurable_item_types_from_bulk(bulk_data)
                self._load_items_with_required_phrases_from_bulk(bulk_data)
                self._load_by_unit_type_items_from_bulk(bulk_data)

                # Generic data-driven loaders (replace domain-specific functions)
                self._load_generic_item_names_from_bulk(bulk_data)
                self._load_generic_ingredients_from_bulk(bulk_data)
                self._load_generic_ingredients_for_item_types_from_bulk(bulk_data)
                self._load_ingredient_category_metadata_from_bulk(bulk_data)

                # Note: Old menu_item_categories removed - categories now derived
                # from item_type -> display_group -> overall_category

                # Load modifier categories (toppings, proteins, milks, etc.)
                self._load_modifier_categories_from_bulk(bulk_data)

                # Load menu item default ingredients (for signature items)
                self._load_menu_item_default_ingredients_from_bulk(bulk_data)

                # Load dietary and allergen data (for dietary/allergen inquiries)
                self._load_dietary_data_from_bulk(bulk_data)

                # Load component slots (for items that include configurable sub-items)
                self._load_component_slots_from_bulk(bulk_data)

                # Price inquiry support (pre-compute resolved prices)
                self._load_priced_attributes_from_bulk(bulk_data)
                self._load_resolved_item_prices_from_bulk(bulk_data)
                self._load_ingredient_price_contexts_from_bulk(bulk_data)

                # Pre-load ALL item type attributes at startup (eliminates runtime lazy loading)
                self._preload_all_item_type_attributes(bulk_data)

                # Load attribute option skip rules (for question skipping logic)
                self._load_option_skip_rules_from_bulk(bulk_data)

                # Load unrecognized option suggestions (for detecting terms not in our menu)
                self._load_unrecognized_option_suggestions_from_bulk(bulk_data)

                # Load unrecognized ingredient suggestions (for ingredients not on the menu)
                self._load_unrecognized_ingredient_suggestions_from_bulk(bulk_data)

                # Load menu display groups (for "what's on your menu?" responses)
                self._load_menu_display_groups_from_bulk(bulk_data)

                # Load attribute inquiry keywords (data-driven mapping for "what types?" queries)
                self._attribute_inquiry_keywords = provider.load_attribute_inquiry_keywords()

                # Build keyword indices for partial matching
                self._build_keyword_indices()

                # Recommendation search support (includes ALL menu items)
                self._load_recommendation_search_data_from_bulk(bulk_data)

                self._last_refresh = datetime.now()
                self._is_loaded = True

                logger.info(
                    "Menu data cache loaded: %d menu_items, %d signature_item_aliases, "
                    "%d abbreviations, %d item_types, %d ingredient_categories, "
                    "%d unit_type_items",
                    len(self._known_menu_items),
                    len(self._signature_item_aliases),
                    len(self._abbreviations),
                    len(self._item_names_by_type),
                    len(self._ingredients_by_category),
                    sum(len(v) for v in self._by_unit_type_items.values()),
                )

            except (OperationalError, ProgrammingError, RuntimeError, ValueError, KeyError, TypeError, AttributeError) as e:
                logger.error("Failed to load menu data cache: %s", e)
                if fail_on_error:
                    raise RuntimeError(f"Failed to load menu data cache: {e}") from e
                # Keep existing cache if available
