"""
Loader mixin for MenuDataCache.

Contains all _load_* methods that populate the cache from the database.
"""

import logging
import re
import time
from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, selectinload

logger = logging.getLogger(__name__)


class LoaderMixin:
    """Mixin containing all database loading methods for the cache."""

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
                self._load_signature_item_aliases_from_bulk(bulk_data)
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

                # Load menu item categories (drink, food, etc.)
                self._load_menu_item_categories_from_bulk(bulk_data)

                # Load modifier categories (toppings, proteins, milks, etc.)
                self._load_modifier_categories_from_bulk(bulk_data)

                # Price inquiry support (pre-compute resolved prices)
                self._load_priced_attributes_from_bulk(bulk_data)
                self._load_resolved_item_prices_from_bulk(bulk_data)
                self._load_ingredient_price_contexts_from_bulk(bulk_data)

                # Pre-load ALL item type attributes at startup (eliminates runtime lazy loading)
                self._preload_all_item_type_attributes(bulk_data)

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
            Dict with pre-loaded data for use by other loader methods:
            - global_attrs: List of GlobalAttribute with options eagerly loaded
            - item_types: List of ItemType with global_attribute_links loaded
            - menu_items: List of MenuItem with aliases loaded
            - ingredients: List of Ingredient with aliases loaded
            - type_ingredients: List of ItemTypeIngredient with relationships
            - global_attr_options: List of GlobalAttributeOption (all)
            - categories: List of Category
            - menu_item_categories: List of MenuItemCategory with relationships
            - response_patterns: List of ResponsePattern
            - modifier_qualifiers: List of ModifierQualifier
            - modifier_categories: List of ModifierCategory
            - ingredient_categories: List of IngredientCategory
            - global_attr_aliases: List of GlobalAttributeAlias
        """
        from ..models import (
            GlobalAttribute, GlobalAttributeOption, Ingredient,
            ItemType, ItemTypeGlobalAttribute, MenuItem, ItemTypeIngredient,
            Category, MenuItemCategory, ResponsePattern, ModifierQualifier,
            ModifierCategory, IngredientCategory, GlobalAttributeAlias,
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
                selectinload(GlobalAttribute.options)
                    .selectinload(GlobalAttributeOption.modifier_category),
            )
            .all()
        )

        # 2. Load ItemType with all global attribute links
        item_types = (
            db.query(ItemType)
            .options(
                selectinload(ItemType.alias_records),
                joinedload(ItemType.overall_category),
                selectinload(ItemType.global_attribute_links)
                    .selectinload(ItemTypeGlobalAttribute.global_attribute)
                    .selectinload(GlobalAttribute.options),
            )
            .all()
        )

        # 3. Load MenuItem with aliases, item_type, and size_prices
        # Note: size_prices is needed because base_price property accesses it
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

        # 5. Load ItemTypeIngredient links
        type_ingredients = (
            db.query(ItemTypeIngredient)
            .options(
                joinedload(ItemTypeIngredient.item_type),
                joinedload(ItemTypeIngredient.ingredient)
                    .selectinload(Ingredient.alias_records),
            )
            .all()
        )

        # 6. Load all GlobalAttributeOption for price lookups
        global_attr_options = (
            db.query(GlobalAttributeOption)
            .all()
        )

        # 7. Load Categories
        categories = db.query(Category).all()

        # 8. Load MenuItemCategory with relationships for side items lookup
        menu_item_categories = (
            db.query(MenuItemCategory)
            .options(
                joinedload(MenuItemCategory.menu_item).selectinload(MenuItem.alias_records),
                joinedload(MenuItemCategory.category),
            )
            .all()
        )

        # 9. Load response patterns
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

        # 11. Load modifier categories
        modifier_categories_list = db.query(ModifierCategory).all()

        # 12. Load ingredient categories
        ingredient_categories = db.query(IngredientCategory).all()

        # 13. Load global attribute aliases
        global_attr_aliases = (
            db.query(GlobalAttributeAlias)
            .options(joinedload(GlobalAttributeAlias.global_attribute))
            .all()
        )

        elapsed = time.time() - start_time
        logger.info(
            "Bulk loaded all tables in %.2fs: %d global_attrs, %d item_types, "
            "%d menu_items, %d ingredients, %d type_ingredients, %d categories",
            elapsed,
            len(global_attrs),
            len(item_types),
            len(menu_items),
            len(ingredients),
            len(type_ingredients),
            len(categories),
        )

        return {
            "global_attrs": global_attrs,
            "item_types": item_types,
            "menu_items": menu_items,
            "ingredients": ingredients,
            "type_ingredients": type_ingredients,
            "global_attr_options": global_attr_options,
            "categories": categories,
            "menu_item_categories": menu_item_categories,
            "response_patterns": response_patterns,
            "modifier_qualifiers": modifier_qualifiers,
            "modifier_categories": modifier_categories_list,
            "ingredient_categories": ingredient_categories,
            "global_attr_aliases": global_attr_aliases,
        }

    def _build_global_option_dict(self, opt) -> dict:
        """Build option dict with aliases from both option and linked ingredient.

        Aliases are merged from two sources:
        1. Option's own alias_records (GlobalAttributeOptionAlias)
        2. Linked Ingredient's alias_records (IngredientAlias)

        This allows options like "double_shot" to have aliases like "2 shots"
        without requiring a linked ingredient.
        """
        # Start with option's own aliases
        aliases = list(opt.aliases) if opt.aliases else []

        # Add linked ingredient aliases (if any)
        must_match = None
        ingredient_category = None
        if opt.ingredient:
            if opt.ingredient.aliases:
                for ing_alias in opt.ingredient.aliases:
                    if ing_alias not in aliases:
                        aliases.append(ing_alias)
            must_match = opt.ingredient.must_match
            ingredient_category = opt.ingredient.category

        modifier_category_slug = None
        if opt.modifier_category:
            modifier_category_slug = opt.modifier_category.slug

        # Derive slug/display_name from ingredient when linked
        slug = opt.ingredient.slug if opt.ingredient else opt.slug
        display_name = opt.ingredient.name if opt.ingredient else opt.display_name

        # Guard against NULL slug (ingredient-linked option with unloaded ingredient)
        if not slug:
            logger.warning(
                "GlobalAttributeOption id=%d has NULL slug (ingredient_id=%s). Skipping.",
                opt.id, opt.ingredient_id,
            )
            return None

        return {
            "slug": slug,
            "display_name": display_name or slug,
            "price_modifier": opt.price_modifier,
            "is_default": opt.is_default,
            "is_available": opt.is_available,
            "aliases": aliases if aliases else None,
            "must_match": must_match,
            "modifier_category": modifier_category_slug,
            "ingredient_category": ingredient_category,
        }

    def _load_global_attribute_options_from_bulk(self, bulk_data: dict) -> None:
        """Load global attribute options from pre-loaded bulk data (no N+1 queries).

        Uses bulk_data["global_attrs"] which has options eagerly loaded.
        """
        global_attrs = bulk_data["global_attrs"]

        global_attribute_options: dict[str, list[dict]] = {}
        property_names: dict[str, str] = {}
        global_attribute_metadata: dict[str, dict] = {}
        modifier_category_to_attrs: dict[str, set[str]] = {}

        for attr in global_attrs:
            # Options are already loaded via selectinload - no query here
            sorted_options = sorted(attr.options, key=lambda o: o.display_order)
            global_attribute_options[attr.slug] = [
                d for opt in sorted_options
                if (d := self._build_global_option_dict(opt)) is not None
            ]

            if attr.property_name:
                property_names[attr.slug] = attr.property_name

            global_attribute_metadata[attr.slug] = {
                "display_name": attr.display_name,
                "input_type": attr.input_type,
            }

        # Build modifier_category -> attrs index
        for attr_slug, options in global_attribute_options.items():
            for opt in options:
                mod_cat = opt.get("modifier_category")
                if mod_cat:
                    if mod_cat not in modifier_category_to_attrs:
                        modifier_category_to_attrs[mod_cat] = set()
                    modifier_category_to_attrs[mod_cat].add(attr_slug)

        self._global_attribute_options = global_attribute_options
        self._global_attribute_property_names = property_names
        self._global_attribute_metadata = global_attribute_metadata
        self._modifier_category_to_attrs = modifier_category_to_attrs

        logger.debug(
            "Loaded global attribute options (from bulk) for %d attributes, %d modifier categories",
            len(global_attribute_options),
            len(modifier_category_to_attrs),
        )

    def _load_menu_index(self, db: Session) -> None:
        """Load and cache the menu index."""
        from ..menu_index_builder import build_menu_index

        logger.info("Building menu index (this may take a moment)...")
        start = time.time()
        self._menu_index = build_menu_index(db)
        elapsed = time.time() - start
        logger.info(
            "Menu index built in %.1f seconds with %d total items",
            elapsed,
            sum(len(v) for k, v in self._menu_index.items() if isinstance(v, list)),
        )

    def _load_item_type_triggers_from_bulk(self, bulk_data: dict) -> None:
        """Load item type trigger keywords from bulk data (no N+1 queries).

        Uses bulk_data["item_types"] and bulk_data["menu_items"] which have
        aliases already eagerly loaded.
        """
        item_types = bulk_data["item_types"]
        menu_items = bulk_data["menu_items"]

        item_type_triggers: dict[str, set[str]] = {}

        # Pre-compute all item type display names as suffixes (data-driven)
        all_type_suffixes = {
            " " + it.display_name.lower()
            for it in item_types
            if it.display_name
        }

        # Build menu items index by item_type_id for O(1) lookup
        menu_items_by_type_id: dict[int, list] = {}
        for item in menu_items:
            if item.item_type_id:
                if item.item_type_id not in menu_items_by_type_id:
                    menu_items_by_type_id[item.item_type_id] = []
                menu_items_by_type_id[item.item_type_id].append(item)

        for item_type in item_types:
            triggers: set[str] = set()

            triggers.add(item_type.slug.lower())

            if item_type.display_name:
                triggers.add(item_type.display_name.lower())
                if item_type.display_name.lower().endswith("s"):
                    triggers.add(item_type.display_name.lower()[:-1])

            # Use pre-built index instead of per-item-type query
            type_menu_items = menu_items_by_type_id.get(item_type.id, [])

            for item in type_menu_items:
                name_lower = item.name.lower()
                triggers.add(name_lower)

                for suffix in all_type_suffixes:
                    if name_lower.endswith(suffix):
                        triggers.add(name_lower[:-len(suffix)])

                words = name_lower.split()
                if len(words) > 1:
                    triggers.add(words[0])

                # Aliases are already loaded via selectinload
                for alias in item.aliases:
                    alias_lower = alias.strip().lower()
                    if alias_lower:
                        triggers.add(alias_lower)

            if triggers:
                item_type_triggers[item_type.slug] = triggers

        self._item_type_triggers = item_type_triggers
        logger.debug(
            "Loaded item type triggers (from bulk): %s",
            {k: len(v) for k, v in item_type_triggers.items()}
        )

    def _load_priced_attributes_from_bulk(self, bulk_data: dict) -> None:
        """Load item types that have priced attributes (from bulk data).

        Uses bulk_data to avoid N+1 queries for global attribute links and options.
        """
        item_types = bulk_data["item_types"]
        global_attrs = bulk_data["global_attrs"]

        self._item_type_priced_attribute = {}

        # Build index: global_attr_id -> has_priced_options
        global_attr_has_priced: dict[int, bool] = {}
        global_attr_slug: dict[int, str] = {}
        for attr in global_attrs:
            global_attr_slug[attr.id] = attr.slug
            has_priced = any(opt.price_modifier and opt.price_modifier > 0 for opt in attr.options)
            global_attr_has_priced[attr.id] = has_priced

        for it in item_types:
            priced_attr = None

            # global_attribute_links is already loaded via selectinload
            for link in it.global_attribute_links:
                if global_attr_has_priced.get(link.global_attribute_id, False):
                    priced_attr = global_attr_slug.get(link.global_attribute_id)
                    if priced_attr:
                        break

            self._item_type_priced_attribute[it.slug] = priced_attr

        logger.debug(
            "Loaded priced attributes (from bulk) for %d item types",
            len([k for k, v in self._item_type_priced_attribute.items() if v]),
        )

    def _load_ingredient_price_contexts_from_bulk(self, bulk_data: dict) -> None:
        """Load ingredient price contexts from bulk data (no N+1 queries).

        Uses bulk_data for ingredients, type_ingredients, menu_items, and global_attr_options.
        """
        ingredients = bulk_data["ingredients"]
        type_ingredients = bulk_data["type_ingredients"]
        menu_items = bulk_data["menu_items"]
        global_attr_options = bulk_data["global_attr_options"]

        self._ingredient_price_contexts = {}

        # Build ingredient_id -> price from GlobalAttributeOption
        ingredient_prices: dict[int, float] = {}
        for opt in global_attr_options:
            if opt.ingredient_id is not None:
                ingredient_prices[opt.ingredient_id] = float(opt.price_modifier or 0)

        # Build ingredient_id -> list of (item_type_slug, item_type_display_name)
        type_ingredient_index: dict[int, list[tuple]] = {}
        for ti in type_ingredients:
            if ti.ingredient and ti.item_type:
                if ti.ingredient_id not in type_ingredient_index:
                    type_ingredient_index[ti.ingredient_id] = []
                type_ingredient_index[ti.ingredient_id].append(
                    (ti.item_type.slug, ti.item_type.display_name)
                )

        # Build list of by_weight menu items with their names (lowercase)
        by_weight_items = [
            item for item in menu_items
            if item.unit_type == "by_weight"
        ]

        for ing in ingredients:
            contexts = []
            ing_name_lower = ing.name.lower()

            # Get price for this ingredient
            ing_price = ingredient_prices.get(ing.id, 0.0)

            # Get item type links from pre-built index
            for item_type_slug, item_type_display in type_ingredient_index.get(ing.id, []):
                contexts.append({
                    "context_type": "modifier",
                    "item_type_slug": item_type_slug,
                    "label": f"{item_type_display} topping",
                    "price": ing_price,
                })

            # Find by_weight items that contain this ingredient name
            for item in by_weight_items:
                if ing.name.lower() in item.name.lower():
                    contexts.append({
                        "context_type": "standalone",
                        "item_type_slug": item.item_type.slug if item.item_type else None,
                        "label": "by the pound",
                        "price": float(item.base_price) if item.base_price else 0.0,
                        "unit": "lb",
                        "menu_item_name": item.name,
                    })

            if contexts:
                self._ingredient_price_contexts[ing_name_lower] = contexts
                # Aliases are already loaded via selectinload
                for alias in ing.aliases:
                    alias_lower = alias.lower().strip()
                    if alias_lower and alias_lower != ing_name_lower:
                        self._ingredient_price_contexts[alias_lower] = contexts

        logger.debug(
            "Loaded price contexts (from bulk) for %d ingredients",
            len(self._ingredient_price_contexts),
        )

    def _preload_all_item_type_attributes(self, bulk_data: dict) -> None:
        """Pre-load ALL item type attributes at startup (eliminates runtime lazy loading).

        Uses bulk_data["item_types"] which has global_attribute_links eagerly loaded
        with the full GlobalAttribute and its options.
        """
        item_types = bulk_data["item_types"]
        global_attrs = bulk_data["global_attrs"]

        # Build global_attr_id -> GlobalAttribute for quick lookup
        global_attrs_by_id: dict[int, object] = {attr.id: attr for attr in global_attrs}

        for item_type in item_types:
            result = {}
            field_to_slug_map = {}

            # global_attribute_links is eagerly loaded
            sorted_links = sorted(item_type.global_attribute_links, key=lambda l: l.display_order)

            for link in sorted_links:
                attr = global_attrs_by_id.get(link.global_attribute_id)
                if not attr:
                    continue

                # Build options list from eagerly loaded options
                options = []
                for opt in sorted(attr.options, key=lambda o: o.display_order):
                    aliases = None
                    must_match = None
                    ingredient_category = None
                    # Derive slug/display_name from ingredient when linked
                    slug = opt.slug
                    display_name = opt.display_name
                    if opt.ingredient:
                        slug = opt.ingredient.slug
                        display_name = opt.ingredient.name
                        aliases = opt.ingredient.aliases
                        must_match = opt.ingredient.must_match
                        ingredient_category = opt.ingredient.category

                    # Guard against NULL slug (ingredient-linked option with unloaded ingredient)
                    if not slug:
                        logger.warning(
                            "GlobalAttributeOption id=%d has NULL slug (ingredient_id=%s). Skipping.",
                            opt.id, getattr(opt, 'ingredient_id', None),
                        )
                        continue

                    options.append({
                        "slug": slug,
                        "display_name": display_name or slug,
                        "price_modifier": float(opt.price_modifier or 0),
                        "is_default": opt.is_default,
                        "is_available": opt.is_available,
                        "aliases": aliases,
                        "must_match": must_match,
                        "ingredient_category": ingredient_category,
                    })

                result[attr.slug] = {
                    "slug": attr.slug,
                    "display_name": attr.display_name,
                    "input_type": attr.input_type,
                    "is_required": link.is_required,
                    "allow_none": link.allow_none,
                    "ask_in_conversation": link.ask_in_conversation,
                    "display_order": link.display_order,
                    "question_text": link.question_text,
                    "options": options,
                    "source": "global",
                }
                field_to_slug_map[attr.slug] = attr.slug

            self._item_type_attributes[item_type.slug] = result
            self._field_to_slug_map[item_type.slug] = field_to_slug_map

        logger.debug(
            "Pre-loaded attributes for %d item types (from bulk)",
            len(self._item_type_attributes),
        )

    # ========================================================================
    # Bulk-only loaders (no database queries - use pre-loaded data)
    # ========================================================================

    def _load_known_menu_items_from_bulk(self, bulk_data: dict) -> None:
        """Load all menu item names and aliases for recognition (from bulk data)."""
        menu_items_list = bulk_data["menu_items"]
        item_types = bulk_data["item_types"]

        menu_items = set()
        alias_to_canonical: dict[str, str] = {}
        menu_items_cache: dict[str, dict] = {}

        # Build set of item_type_ids that have askable attributes
        exclude_type_ids = set()
        for item_type in item_types:
            for link in item_type.global_attribute_links:
                if link.ask_in_conversation:
                    exclude_type_ids.add(item_type.id)
                    break

        for item in menu_items_list:
            # Build menu items cache for get_items_by_item_type
            item_type_slug = item.item_type.slug if item.item_type else None
            menu_items_cache[item.name.lower()] = {
                "id": item.id,
                "name": item.name,
                "item_type": item_type_slug,
                "base_price": float(item.base_price) if item.base_price else 0.0,
            }

            # Skip items that have their own configuration flows
            # BUT always include signature items
            if item.item_type_id in exclude_type_ids and not item.is_signature:
                continue

            canonical_name = item.name
            name_lower = item.name.lower()

            menu_items.add(name_lower)
            alias_to_canonical[name_lower] = canonical_name

            if name_lower.startswith("the "):
                without_the = name_lower[4:]
                menu_items.add(without_the)
                alias_to_canonical[without_the] = canonical_name

            for alias in item.aliases:
                alias = alias.strip().lower()
                if alias:
                    menu_items.add(alias)
                    alias_to_canonical[alias] = canonical_name

        self._known_menu_items = menu_items
        self._menu_item_alias_to_canonical = alias_to_canonical
        self._menu_items = menu_items_cache

        logger.debug(
            "Loaded %d known menu items with %d alias mappings (from bulk)",
            len(menu_items),
            len(alias_to_canonical),
        )

    def _load_signature_item_aliases_from_bulk(self, bulk_data: dict) -> None:
        """Load signature item aliases from bulk data."""
        menu_items = bulk_data["menu_items"]

        signature_item_aliases: dict[str, str] = {}
        signature_item_types: dict[str, str] = {}

        for item in menu_items:
            if not item.is_signature:
                continue

            canonical_name = item.name

            if item.item_type:
                signature_item_types[canonical_name] = item.item_type.slug

            for alias in item.aliases:
                alias = alias.strip().lower()
                if alias:
                    signature_item_aliases[alias] = canonical_name

            name_lower = item.name.lower()
            signature_item_aliases[name_lower] = canonical_name

            if name_lower.startswith("the "):
                signature_item_aliases[name_lower[4:]] = canonical_name

        self._signature_item_aliases = signature_item_aliases
        self._signature_item_types = signature_item_types

        logger.debug(
            "Loaded %d signature item aliases (from bulk)",
            len(signature_item_aliases),
        )

    def _load_modifier_aliases_from_bulk(self, bulk_data: dict) -> None:
        """Load modifier alias mappings from bulk data."""
        ingredients = bulk_data["ingredients"]

        modifier_aliases: dict[str, str] = {}

        for ing in ingredients:
            canonical_name = ing.name

            for alias in ing.aliases:
                alias = alias.strip().lower()
                if alias:
                    modifier_aliases[alias] = canonical_name

            name_lower = ing.name.lower()
            modifier_aliases[name_lower] = canonical_name

        self._modifier_aliases = modifier_aliases

        logger.debug(
            "Loaded %d modifier aliases (from bulk)",
            len(modifier_aliases),
        )

    def _load_side_items_from_bulk(self, bulk_data: dict) -> None:
        """Load side items and their aliases from bulk data."""
        menu_item_categories = bulk_data["menu_item_categories"]

        side_items: set[str] = set()
        alias_to_canonical: dict[str, str] = {}

        for mic in menu_item_categories:
            if mic.category and mic.category.slug == "side":
                item = mic.menu_item
                if not item:
                    continue

                canonical_name = item.name
                name_lower = canonical_name.lower()

                side_items.add(name_lower)
                alias_to_canonical[name_lower] = canonical_name

                for alias in item.aliases:
                    alias = alias.strip().lower()
                    if alias:
                        side_items.add(alias)
                        alias_to_canonical[alias] = canonical_name

        self._side_items = side_items
        self._side_alias_to_canonical = alias_to_canonical

        logger.debug(
            "Loaded %d side item aliases (from bulk)",
            len(alias_to_canonical),
        )

    def _load_category_keywords_from_bulk(self, bulk_data: dict) -> None:
        """Load category keyword mappings from bulk data."""
        item_types = bulk_data["item_types"]
        categories = bulk_data["categories"]

        category_keywords: dict[str, dict] = {}

        # 1. Load ItemTypes
        for item_type in item_types:
            slug = item_type.slug
            display_name = item_type.display_name
            display_name_plural = item_type.display_name_plural or f"{display_name}s"

            category_info = {
                "slug": slug,
                "display_name": display_name,
                "display_name_plural": display_name_plural,
                "lookup_type": "item_type",
            }

            category_keywords[slug] = category_info

            for alias in item_type.aliases:
                alias = alias.strip().lower()
                if alias:
                    category_keywords[alias] = category_info

        # 2. Load Categories
        for category in categories:
            slug = category.slug
            display_name = category.name
            display_name_plural = f"{display_name}s" if not display_name.endswith('s') else display_name

            category_info = {
                "slug": slug,
                "category_id": category.id,
                "display_name": display_name,
                "display_name_plural": display_name_plural,
                "lookup_type": "category",
            }

            category_keywords[slug] = category_info

            name_lower = display_name.lower()
            if name_lower != slug:
                category_keywords[name_lower] = category_info
            plural_lower = display_name_plural.lower()
            if plural_lower != slug and plural_lower != name_lower:
                category_keywords[plural_lower] = category_info

        if not category_keywords:
            raise RuntimeError(
                "No category keywords found in database. Run migrations to populate "
                "item_types and categories tables."
            )

        self._category_keywords = category_keywords

        logger.debug(
            "Loaded %d category keywords (from bulk)",
            len(category_keywords),
        )

    def _load_abbreviations_from_bulk(self, bulk_data: dict) -> None:
        """Load abbreviations from bulk data."""
        ingredients = bulk_data["ingredients"]
        menu_items = bulk_data["menu_items"]

        abbreviations: dict[str, str] = {}

        for ingredient in ingredients:
            if ingredient.abbreviation:
                abbrev = ingredient.abbreviation.strip().lower()
                canonical = ingredient.name.lower()
                if abbrev and canonical:
                    abbreviations[abbrev] = canonical

        for item in menu_items:
            if item.abbreviation:
                abbrev = item.abbreviation.strip().lower()
                canonical = item.name.lower()
                if abbrev and canonical:
                    abbreviations[abbrev] = canonical

        self._abbreviations = abbreviations

        logger.debug(
            "Loaded %d abbreviations (from bulk)",
            len(abbreviations),
        )

    def _load_item_type_fields_from_bulk(self, bulk_data: dict) -> None:
        """Load item type attribute configurations from bulk data."""
        item_types = bulk_data["item_types"]
        global_attrs = bulk_data["global_attrs"]

        item_type_fields: dict[str, list[dict]] = {}

        # Build global_attr_id -> GlobalAttribute for quick lookup
        global_attrs_by_id = {attr.id: attr for attr in global_attrs}

        for item_type in item_types:
            slug = item_type.slug
            if slug not in item_type_fields:
                item_type_fields[slug] = []

            sorted_links = sorted(item_type.global_attribute_links, key=lambda l: l.display_order)

            for link in sorted_links:
                global_attr = global_attrs_by_id.get(link.global_attribute_id)
                if not global_attr:
                    continue

                item_type_fields[slug].append({
                    "field_name": global_attr.slug,
                    "display_order": link.display_order,
                    "required": link.is_required,
                    "ask": link.ask_in_conversation,
                    "question_text": link.question_text,
                    "input_type": global_attr.input_type,
                    "display_name": global_attr.display_name,
                })

        self._item_type_fields = item_type_fields

        logger.debug(
            "Loaded item type fields for %d item types (from bulk)",
            len(item_type_fields),
        )

    def _load_response_patterns_from_bulk(self, bulk_data: dict) -> None:
        """Load response patterns from bulk data."""
        patterns_list = bulk_data["response_patterns"]

        response_patterns: dict[str, set[str]] = {}
        regex_patterns: dict[str, list[str]] = {}

        for pattern in patterns_list:
            pattern_type = pattern.pattern_type
            if pattern.is_regex:
                if pattern_type not in regex_patterns:
                    regex_patterns[pattern_type] = []
                regex_patterns[pattern_type].append(pattern.pattern)
            else:
                if pattern_type not in response_patterns:
                    response_patterns[pattern_type] = set()
                response_patterns[pattern_type].add(pattern.pattern.lower())

        self._response_patterns = response_patterns
        self._response_regex_raw = regex_patterns

        # Build combined regex for each type
        all_types = set(response_patterns.keys()) | set(regex_patterns.keys())
        response_regex_compiled: dict[str, re.Pattern | None] = {}

        for pattern_type in all_types:
            pattern_parts = []

            exact = response_patterns.get(pattern_type, set())
            if exact:
                escaped = [re.escape(p) for p in exact]
                pattern_parts.extend(escaped)

            regex_list = regex_patterns.get(pattern_type, [])
            pattern_parts.extend(regex_list)

            if pattern_parts:
                combined = "|".join(f"({p})" for p in pattern_parts)
                full_pattern = f"^({combined})[\\s!.,]*$"
                try:
                    response_regex_compiled[pattern_type] = re.compile(full_pattern, re.IGNORECASE)
                except re.error as e:
                    logger.error("Failed to compile regex for %s: %s", pattern_type, e)
                    response_regex_compiled[pattern_type] = None
            else:
                response_regex_compiled[pattern_type] = None

        self._response_regex_compiled = response_regex_compiled

        logger.debug(
            "Loaded response patterns (from bulk): %d types",
            len(all_types),
        )

    def _load_modifier_qualifiers_from_bulk(self, bulk_data: dict) -> None:
        """Load modifier qualifier patterns from bulk data."""
        qualifiers = bulk_data.get("modifier_qualifiers", [])

        modifier_qualifiers: dict[str, dict] = {}
        qualifier_patterns_by_category: dict[str, set[str]] = {}

        for qualifier in qualifiers:
            pattern = qualifier.pattern.lower()
            category = qualifier.category

            modifier_qualifiers[pattern] = {
                "normalized_form": qualifier.normalized_form,
                "category": category,
            }

            if category not in qualifier_patterns_by_category:
                qualifier_patterns_by_category[category] = set()
            qualifier_patterns_by_category[category].add(pattern)

        self._modifier_qualifiers = modifier_qualifiers
        self._qualifier_patterns_by_category = qualifier_patterns_by_category

        logger.debug(
            "Loaded %d modifier qualifiers (from bulk)",
            len(modifier_qualifiers),
        )

    def _load_global_attribute_aliases_from_bulk(self, bulk_data: dict) -> None:
        """Load global attribute aliases from bulk data."""
        aliases = bulk_data.get("global_attr_aliases", [])

        global_attribute_aliases: dict[str, str] = {}

        for alias_record in aliases:
            alias_lower = alias_record.alias.lower()
            attr_slug = alias_record.global_attribute.slug
            global_attribute_aliases[alias_lower] = attr_slug

        self._global_attribute_aliases = global_attribute_aliases

        logger.debug(
            "Loaded %d global attribute aliases (from bulk)",
            len(global_attribute_aliases),
        )

    def _load_item_type_metadata_from_bulk(self, bulk_data: dict) -> None:
        """Load item type metadata from bulk data."""
        item_types = bulk_data["item_types"]
        menu_items = bulk_data["menu_items"]

        modifier_categories: dict[str, str | None] = {}
        item_keywords: set[str] = set()
        configurable_types: set[str] = set()
        side_choice_config: dict[str, dict] = {}

        for item_type in item_types:
            slug = item_type.slug
            if item_type.overall_category:
                modifier_categories[slug] = item_type.overall_category.slug
            else:
                modifier_categories[slug] = None

            side_choice_config[slug] = {
                "has_side_choice": item_type.has_side_choice,
            }

            item_keywords.add(slug.lower())

            for alias in item_type.aliases:
                item_keywords.add(alias.lower())

            # Check if this item type has configurable attributes
            if item_type.global_attribute_links:
                configurable_types.add(slug)

        for item in menu_items:
            name = item.name
            item_keywords.add(name.lower())
            words = name.lower().split()
            for word in words:
                if len(word) > 2:
                    item_keywords.add(word)

        self._item_type_modifier_categories = modifier_categories
        self._item_keywords = item_keywords
        self._configurable_item_types = configurable_types
        self._item_type_side_choice = side_choice_config

        logger.debug(
            "Loaded item type metadata (from bulk): %d modifier_categories, %d keywords",
            len(modifier_categories),
            len(item_keywords),
        )

    def _load_compound_phrases_from_bulk(self, bulk_data: dict) -> None:
        """Load compound phrases from bulk data."""
        menu_items = bulk_data["menu_items"]
        ingredients = bulk_data["ingredients"]

        compound_phrases: set[str] = set()

        for item in menu_items:
            if " and " in item.name.lower():
                compound_phrases.add(item.name.lower())
            for alias in item.aliases:
                if " and " in alias.lower():
                    compound_phrases.add(alias.lower())

        for ing in ingredients:
            if " and " in ing.name.lower():
                compound_phrases.add(ing.name.lower())
            for alias in ing.aliases:
                if " and " in alias.lower():
                    compound_phrases.add(alias.lower())

        self._compound_phrases = compound_phrases
        logger.debug("Loaded %d compound phrases (from bulk)", len(compound_phrases))

    def _load_configurable_item_types_from_bulk(self, bulk_data: dict) -> None:
        """Load slugs of item types that have askable attributes (from bulk)."""
        item_types = bulk_data["item_types"]

        configurable_slugs: set[str] = set()

        for item_type in item_types:
            for link in item_type.global_attribute_links:
                if link.ask_in_conversation:
                    configurable_slugs.add(item_type.slug)
                    break

        self._configurable_item_type_slugs = configurable_slugs
        logger.debug(
            "Loaded %d configurable item type slugs (from bulk): %s",
            len(configurable_slugs), configurable_slugs
        )

    def _load_items_with_required_phrases_from_bulk(self, bulk_data: dict) -> None:
        """Load menu items that have required_match_phrases set (from bulk)."""
        menu_items = bulk_data["menu_items"]

        items_with_phrases: dict[str, str] = {}

        for item in menu_items:
            if item.required_match_phrases:
                items_with_phrases[item.name.lower()] = item.required_match_phrases

        self._items_with_required_phrases = items_with_phrases
        logger.debug(
            "Loaded %d items with required_match_phrases (from bulk)",
            len(items_with_phrases)
        )

    def _load_by_unit_type_items_from_bulk(self, bulk_data: dict) -> None:
        """Load menu items grouped by unit_type (from bulk)."""
        menu_items = bulk_data["menu_items"]

        by_unit_type: dict[str, set[str]] = {}
        unit_type_aliases: dict[str, dict[str, tuple[str, str]]] = {}

        seen_base_names: dict[str, set[str]] = {}

        for item in menu_items:
            unit_type = item.unit_type or "each"
            item_type_slug = item.item_type.slug if item.item_type else "unknown"
            name = item.name

            base_name = re.sub(r'\s*\([^)]*\)\s*$', '', name).strip()
            base_name_lower = base_name.lower()

            if unit_type not in by_unit_type:
                by_unit_type[unit_type] = set()
            if unit_type not in unit_type_aliases:
                unit_type_aliases[unit_type] = {}
            if unit_type not in seen_base_names:
                seen_base_names[unit_type] = set()

            by_unit_type[unit_type].add(base_name_lower)

            if base_name_lower in seen_base_names[unit_type]:
                continue
            seen_base_names[unit_type].add(base_name_lower)

            unit_type_aliases[unit_type][base_name_lower] = (base_name, item_type_slug)

            for alias in item.aliases:
                alias = alias.strip().lower()
                if alias:
                    unit_type_aliases[unit_type][alias] = (base_name, item_type_slug)

        self._by_unit_type_items = by_unit_type
        self._unit_type_aliases = unit_type_aliases

        logger.debug(
            "Loaded items by unit_type (from bulk): %s",
            {k: len(v) for k, v in by_unit_type.items()},
        )

    def _load_generic_item_names_from_bulk(self, bulk_data: dict) -> None:
        """Load all item names grouped by ItemType slug (from bulk)."""
        menu_items = bulk_data["menu_items"]

        item_names_by_type: dict[str, set[str]] = {}
        alias_to_canonical_by_type: dict[str, dict[str, str]] = {}

        for item in menu_items:
            if not item.item_type:
                continue

            item_type_slug = item.item_type.slug
            canonical_name = item.name

            if item_type_slug not in item_names_by_type:
                item_names_by_type[item_type_slug] = set()
                alias_to_canonical_by_type[item_type_slug] = {}

            name_lower = canonical_name.lower()
            item_names_by_type[item_type_slug].add(name_lower)
            alias_to_canonical_by_type[item_type_slug][name_lower] = canonical_name

            for alias in item.aliases:
                alias_lower = alias.strip().lower()
                if alias_lower:
                    item_names_by_type[item_type_slug].add(alias_lower)
                    alias_to_canonical_by_type[item_type_slug][alias_lower] = canonical_name

        self._item_names_by_type = item_names_by_type
        self._item_alias_to_canonical_by_type = alias_to_canonical_by_type

        logger.debug(
            "Loaded generic item names (from bulk) for %d item types",
            len(item_names_by_type),
        )

    def _load_generic_ingredients_from_bulk(self, bulk_data: dict) -> None:
        """Load all ingredients grouped by category (from bulk)."""
        ingredients = bulk_data["ingredients"]

        ingredients_by_category: dict[str, set[str]] = {}
        ingredient_details_by_category: dict[str, list[dict]] = {}

        for ing in ingredients:
            category = ing.category
            if not category:
                continue

            if category not in ingredients_by_category:
                ingredients_by_category[category] = set()
                ingredient_details_by_category[category] = []

            name_lower = ing.name.lower()
            ingredients_by_category[category].add(name_lower)

            patterns = [name_lower]
            for alias in ing.aliases:
                alias_lower = alias.strip().lower()
                if alias_lower:
                    ingredients_by_category[category].add(alias_lower)
                    patterns.append(alias_lower)

            ingredient_details_by_category[category].append({
                "slug": ing.slug,
                "name": ing.name,
                "patterns": patterns,
            })

        self._ingredients_by_category = ingredients_by_category
        self._ingredient_details_by_category = ingredient_details_by_category

        logger.debug(
            "Loaded generic ingredients (from bulk) for %d categories",
            len(ingredients_by_category),
        )

    def _load_generic_ingredients_for_item_types_from_bulk(self, bulk_data: dict) -> None:
        """Load ingredients valid for each ItemType (from bulk)."""
        type_ingredients = bulk_data["type_ingredients"]

        ingredients_for_item_type: dict[str, dict[str, set[str]]] = {}

        for ti in type_ingredients:
            if not ti.item_type or not ti.ingredient:
                continue

            item_type_slug = ti.item_type.slug
            category = ti.ingredient.category or "uncategorized"

            if item_type_slug not in ingredients_for_item_type:
                ingredients_for_item_type[item_type_slug] = {}
            if category not in ingredients_for_item_type[item_type_slug]:
                ingredients_for_item_type[item_type_slug][category] = set()

            ingredients_for_item_type[item_type_slug][category].add(ti.ingredient.name.lower())

            for alias in ti.ingredient.aliases:
                alias_lower = alias.strip().lower()
                if alias_lower:
                    ingredients_for_item_type[item_type_slug][category].add(alias_lower)

        self._ingredients_for_item_type = ingredients_for_item_type

        logger.debug(
            "Loaded ingredients for %d item types (from bulk)",
            len(ingredients_for_item_type)
        )

    def _load_ingredient_category_metadata_from_bulk(self, bulk_data: dict) -> None:
        """Load ingredient category metadata (from bulk)."""
        categories = bulk_data.get("ingredient_categories", [])

        categories_by_modifier_type: dict[str, set[str]] = {}
        category_field_config: dict[str, dict] = {}
        category_order: dict[str, int] = {}
        name_forming_categories: set[str] = set()

        for cat in categories:
            if cat.modifier_type:
                if cat.modifier_type not in categories_by_modifier_type:
                    categories_by_modifier_type[cat.modifier_type] = set()
                categories_by_modifier_type[cat.modifier_type].add(cat.slug)

            category_field_config[cat.slug] = {
                "code_field_name": cat.code_field_name or cat.slug,
                "is_multi_select": cat.is_multi_select or False,
                "display_name": cat.display_name,
                "quantity_unit": getattr(cat, 'quantity_unit', None),
            }

            category_order[cat.slug] = cat.display_order or 999

            # Collect name-forming categories
            if getattr(cat, 'is_name_forming', False):
                name_forming_categories.add(cat.slug)

        self._ingredient_categories_by_modifier_type = categories_by_modifier_type
        self._ingredient_category_field_config = category_field_config
        self._ingredient_category_order = category_order
        self._name_forming_categories = name_forming_categories

        logger.debug(
            "Loaded ingredient category metadata (from bulk): %d configs, %d name-forming",
            len(category_field_config),
            len(name_forming_categories)
        )

    def _load_menu_item_categories_from_bulk(self, bulk_data: dict) -> None:
        """Load menu item categories (from bulk)."""
        from sqlalchemy import func

        categories = bulk_data["categories"]
        menu_item_categories = bulk_data["menu_item_categories"]
        item_types = bulk_data["item_types"]

        available_categories: dict[str, str] = {}
        menu_items_by_category: dict[str, list[dict]] = {}

        for cat in categories:
            available_categories[cat.slug] = cat.name
            menu_items_by_category[cat.slug] = []

        # Build item_type_id -> slug map
        item_type_slugs = {it.id: it.slug for it in item_types}

        for mic in menu_item_categories:
            if not mic.menu_item or not mic.category:
                continue

            item = mic.menu_item
            cat_slug = mic.category.slug

            item_type_slug = item_type_slugs.get(item.item_type_id)
            item_dict = {
                "id": item.id,
                "name": item.name,
                "base_price": float(item.base_price) if item.base_price else 0.0,
                "item_type": item_type_slug,
            }

            if cat_slug in menu_items_by_category:
                menu_items_by_category[cat_slug].append(item_dict)

        self._available_categories = available_categories
        self._menu_items_by_category_slug = menu_items_by_category

        logger.debug(
            "Loaded menu item categories (from bulk): %d categories",
            len(available_categories),
        )

    def _load_modifier_categories_from_bulk(self, bulk_data: dict) -> None:
        """Load modifier categories (from bulk)."""
        categories = bulk_data.get("modifier_categories", [])

        modifier_categories: dict[str, dict] = {}

        for cat in categories:
            modifier_categories[cat.slug] = {
                "display_name": cat.display_name,
                "loads_from_ingredients": cat.loads_from_ingredients,
                "ingredient_category": cat.ingredient_category,
                "description": cat.description,
                "prompt_suffix": cat.prompt_suffix,
            }

        self._modifier_categories = modifier_categories

        logger.debug(
            "Loaded modifier categories (from bulk): %d categories",
            len(modifier_categories),
        )

    def _load_resolved_item_prices_from_bulk(self, bulk_data: dict) -> None:
        """Pre-compute resolved prices for menu items (from bulk)."""
        menu_items = bulk_data["menu_items"]

        self._resolved_item_prices = {}

        for item in menu_items:
            if not item.item_type:
                continue

            self._resolved_item_prices[item.name.lower()] = float(item.base_price or 0)

        logger.debug("Pre-loaded %d resolved item prices (from bulk)", len(self._resolved_item_prices))

    def _load_recommendation_search_data_from_bulk(self, bulk_data: dict) -> None:
        """Load ALL menu items for recommendation search (from bulk)."""
        menu_items = bulk_data["menu_items"]

        all_items: dict[str, dict] = {}
        keyword_index: dict[str, list[str]] = defaultdict(list)

        for item in menu_items:
            canonical_name = item.name
            name_lower = canonical_name.lower()
            item_type_slug = item.item_type.slug if item.item_type else None

            item_data = {
                "id": item.id,
                "name": canonical_name,
                "item_type_slug": item_type_slug,
            }
            all_items[name_lower] = item_data

            for word in name_lower.split():
                if len(word) >= 3 and word not in {"the", "and", "with"}:
                    keyword_index[word].append(name_lower)

            for alias in item.aliases:
                alias_lower = alias.lower().strip()
                if alias_lower:
                    all_items[alias_lower] = item_data
                    for word in alias_lower.split():
                        if len(word) >= 3 and word not in {"the", "and", "with"}:
                            keyword_index[word].append(name_lower)

        self._all_menu_items_by_name = all_items
        self._recommendation_keyword_index = dict(keyword_index)

        logger.debug(
            "Loaded recommendation search data (from bulk): %d items, %d keywords",
            len(all_items),
            len(keyword_index),
        )
