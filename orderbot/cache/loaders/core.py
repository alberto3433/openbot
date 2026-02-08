"""
Core Loader for MenuDataCache.

Contains the main load_from_db method and bulk data loading.
Inherits from all specialized loader mixins.
"""

import logging
import time

from sqlalchemy.orm import Session, joinedload, selectinload

from .menu_items import MenuItemLoaderMixin
from .ingredients import IngredientLoaderMixin
from .item_types import ItemTypeLoaderMixin
from .patterns import PatternLoaderMixin

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
    load_from_db orchestration method.
    """

    def load_from_db(self, db: Session, fail_on_error: bool = True, force: bool = False) -> None:
        """
        Load all menu data from the database.

        Args:
            db: SQLAlchemy database session
            fail_on_error: If True, raise exception on DB errors (for startup)
                          If False, log warning and keep existing cache
            force: If True, reload even if already loaded (for manual refresh)

        Raises:
            RuntimeError: If fail_on_error=True and DB load fails
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
                logger.info("Loading menu data cache from database...")

                # Bulk load all tables first to eliminate N+1 queries
                bulk_data = self._bulk_load_all_tables(db)

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
                self._load_menu_index(db)  # Uses build_menu_index which queries DB

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

                # Load menu display groups (for "what's on your menu?" responses)
                self._load_menu_display_groups_from_bulk(bulk_data)

                # Load attribute inquiry keywords (data-driven mapping for "what types?" queries)
                self._load_attribute_inquiry_keywords(db)

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

            except Exception as e:
                logger.error("Failed to load menu data cache: %s", e)
                if fail_on_error:
                    raise RuntimeError(f"Failed to load menu data cache: {e}") from e
                # Keep existing cache if available

    def _bulk_load_all_tables(self, db: Session) -> dict:
        """Load ALL tables needed for cache in minimal queries using eager loading.

        This eliminates N+1 query patterns by loading all related data upfront
        with selectinload/joinedload, then processing in memory.

        Returns:
            Dict with pre-loaded data for use by other loader methods.
        """
        from ...db.models import (
            GlobalAttribute, GlobalAttributeOption, GlobalAttributeOptionSkip, Ingredient,
            ItemType, ItemTypeGlobalAttribute, MenuItem,
            ResponsePattern, ModifierQualifier,
            ModifierCategory, IngredientCategory, GlobalAttributeAlias,
            MenuItemIngredient, ItemTypeComponentSlot, ComponentSlotOption,
            UnrecognizedOptionSuggestion, MenuDisplayGroup,
        )

        start_time = time.time()

        # 1. Load GlobalAttribute with all options and their ingredients
        global_attrs = (
            db.query(GlobalAttribute)
            .options(
                selectinload(GlobalAttribute.options)
                    .selectinload(GlobalAttributeOption.alias_records),
                selectinload(GlobalAttribute.options)
                    .selectinload(GlobalAttributeOption.ingredient)
                    .selectinload(Ingredient.alias_records),
                selectinload(GlobalAttribute.options)
                    .selectinload(GlobalAttributeOption.ingredient)
                    .selectinload(Ingredient.must_match_records),
                # Load modifier_category via ingredient (derived at runtime)
                selectinload(GlobalAttribute.options)
                    .selectinload(GlobalAttributeOption.ingredient)
                    .joinedload(Ingredient.modifier_category),
                selectinload(GlobalAttribute.options)
                    .joinedload(GlobalAttributeOption.forward_to_attribute),
            )
            .all()
        )

        # 2. Load ItemType with all global attribute links
        item_types = (
            db.query(ItemType)
            .options(
                selectinload(ItemType.alias_records),
                joinedload(ItemType.menu_display_group).joinedload(MenuDisplayGroup.overall_category),
                selectinload(ItemType.global_attribute_links)
                    .selectinload(ItemTypeGlobalAttribute.global_attribute)
                    .selectinload(GlobalAttribute.options)
                    .joinedload(GlobalAttributeOption.forward_to_attribute),
            )
            .all()
        )

        # 3. Load MenuItem with aliases, item_type, and size_prices
        menu_items = (
            db.query(MenuItem)
            .options(
                selectinload(MenuItem.alias_records),
                joinedload(MenuItem.item_type),
                selectinload(MenuItem.size_prices),
            )
            .all()
        )

        # 4. Load Ingredient with aliases
        ingredients = (
            db.query(Ingredient)
            .options(
                selectinload(Ingredient.alias_records),
                selectinload(Ingredient.must_match_records),
            )
            .all()
        )

        # 5. Load all GlobalAttributeOption for price lookups
        global_attr_options = db.query(GlobalAttributeOption).all()

        # 7. Load response patterns
        response_patterns = db.query(ResponsePattern).all()

        # 10. Load modifier qualifiers
        try:
            modifier_qualifiers = (
                db.query(ModifierQualifier)
                .filter(ModifierQualifier.is_active == True)  # noqa: E712
                .all()
            )
        except Exception:
            modifier_qualifiers = []

        # 11. Load modifier categories (with aliases eagerly loaded)
        modifier_categories_list = (
            db.query(ModifierCategory)
            .options(selectinload(ModifierCategory.alias_records))
            .all()
        )

        # 12. Load ingredient categories
        ingredient_categories = db.query(IngredientCategory).all()

        # 13. Load global attribute aliases
        global_attr_aliases = (
            db.query(GlobalAttributeAlias)
            .options(joinedload(GlobalAttributeAlias.global_attribute))
            .all()
        )

        # 14. Load menu item ingredients (default ingredients for signature items)
        menu_item_ingredients = (
            db.query(MenuItemIngredient)
            .options(
                joinedload(MenuItemIngredient.menu_item),
                joinedload(MenuItemIngredient.ingredient),
            )
            .all()
        )

        # 15. Load component slots (for items that include configurable sub-items)
        component_slots = (
            db.query(ItemTypeComponentSlot)
            .options(
                joinedload(ItemTypeComponentSlot.parent_item_type),
                selectinload(ItemTypeComponentSlot.slot_options)
                    .joinedload(ComponentSlotOption.allowed_item_type),
                selectinload(ItemTypeComponentSlot.slot_options)
                    .joinedload(ComponentSlotOption.allowed_menu_item),
            )
            .all()
        )

        # 16. Load attribute option skip rules
        try:
            option_skip_rules = (
                db.query(GlobalAttributeOptionSkip)
                .options(
                    joinedload(GlobalAttributeOptionSkip.triggering_option),
                    joinedload(GlobalAttributeOptionSkip.skipped_attribute),
                )
                .all()
            )
        except Exception:
            # Table may not exist yet if migrations haven't run
            option_skip_rules = []

        # 17. Load unrecognized option suggestions (for detecting terms not in our menu)
        try:
            unrecognized_option_suggestions = (
                db.query(UnrecognizedOptionSuggestion)
                .filter(UnrecognizedOptionSuggestion.is_active == True)  # noqa: E712
                .all()
            )
        except Exception:
            # Table may not exist yet if migrations haven't run
            unrecognized_option_suggestions = []

        # 18. Load menu display groups (for "what's on your menu?" responses)
        try:
            menu_display_groups = (
                db.query(MenuDisplayGroup)
                .options(selectinload(MenuDisplayGroup.alias_records))
                .order_by(MenuDisplayGroup.display_order)
                .all()
            )
        except Exception:
            # Table may not exist yet if migrations haven't run
            menu_display_groups = []

        elapsed = time.time() - start_time
        logger.info(
            "Bulk loaded all tables in %.2fs: %d global_attrs, %d item_types, "
            "%d menu_items, %d ingredients",
            elapsed,
            len(global_attrs),
            len(item_types),
            len(menu_items),
            len(ingredients),
        )

        return {
            "global_attrs": global_attrs,
            "item_types": item_types,
            "menu_items": menu_items,
            "ingredients": ingredients,
            "global_attr_options": global_attr_options,
            "categories": [],  # Removed - now using display groups
            "menu_item_categories": [],  # Removed - now using display groups
            "response_patterns": response_patterns,
            "modifier_qualifiers": modifier_qualifiers,
            "modifier_categories": modifier_categories_list,
            "ingredient_categories": ingredient_categories,
            "global_attr_aliases": global_attr_aliases,
            "menu_item_ingredients": menu_item_ingredients,
            "component_slots": component_slots,
            "option_skip_rules": option_skip_rules,
            "unrecognized_option_suggestions": unrecognized_option_suggestions,
            "menu_display_groups": menu_display_groups,
        }

    def _load_menu_index(self, db: Session) -> None:
        """Load and cache the menu index."""
        from ...menu_index import build_menu_index

        logger.info("Building menu index (this may take a moment)...")
        start = time.time()
        self._menu_index = build_menu_index(db)
        elapsed = time.time() - start
        logger.info(
            "Menu index built in %.1f seconds with %d total items",
            elapsed,
            sum(len(v) for k, v in self._menu_index.items() if isinstance(v, list)),
        )
