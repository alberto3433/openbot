"""
Menu Item Loaders for MenuDataCache.

Contains loader methods for menu items, items with default ingredients,
side items, and related data structures.
"""

import logging
import re
from collections import defaultdict

from ...constants import MIN_KEYWORD_LENGTH, MIN_PREFIX_WORDS
from ..base import build_alias_mapping, normalize_text

logger = logging.getLogger(__name__)


class MenuItemLoaderMixin:
    """Mixin containing menu item loading methods."""

    def _load_known_menu_items_from_bulk(self, bulk_data: dict) -> None:
        """Load all menu item names and aliases for recognition (from bulk data)."""
        menu_items_list = bulk_data["menu_items"]
        item_types = bulk_data["item_types"]
        menu_item_ingredients = bulk_data.get("menu_item_ingredients", [])

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

        # Build set of menu_item_ids that have default ingredients
        items_with_defaults = {link.menu_item_id for link in menu_item_ingredients}

        for item in menu_items_list:
            # Build menu items cache for get_items_by_item_type
            item_type_slug = item.item_type.slug if item.item_type else None
            menu_items_cache[item.name.lower()] = {
                "id": item.id,
                "name": item.name,
                "item_type": item_type_slug,
                "base_price": float(item.base_price) if item.base_price else 0.0,
                "unit_type": item.unit_type,
                "quantity_per_unit": item.quantity_per_unit,
            }

            # Skip items that have their own configuration flows
            # BUT always include items with default ingredients (they need direct recognition)
            if item.item_type_id in exclude_type_ids and item.id not in items_with_defaults:
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
                alias = normalize_text(alias)
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

    def _load_items_with_defaults_aliases_from_bulk(self, bulk_data: dict) -> None:
        """Load aliases for items that have default ingredients (from bulk data).

        Items with default ingredients need special recognition in parsing to prevent
        trigger-based detection from overriding them. For example, "The Classic BEC
        on a wheat bagel" should match The Classic BEC, not the "bagel" item type.
        """
        menu_items = bulk_data["menu_items"]
        menu_item_ingredients = bulk_data.get("menu_item_ingredients", [])

        # Build set of menu_item_ids that have default ingredients
        items_with_defaults = {link.menu_item_id for link in menu_item_ingredients}

        items_with_defaults_aliases: dict[str, str] = {}
        items_with_defaults_types: dict[str, str] = {}

        for item in menu_items:
            if item.id not in items_with_defaults:
                continue

            canonical_name = item.name

            if item.item_type:
                items_with_defaults_types[canonical_name] = item.item_type.slug

            for alias in item.aliases:
                alias = normalize_text(alias)
                if alias:
                    items_with_defaults_aliases[alias] = canonical_name

            name_lower = item.name.lower()
            items_with_defaults_aliases[name_lower] = canonical_name

            if name_lower.startswith("the "):
                items_with_defaults_aliases[name_lower[4:]] = canonical_name

        self._items_with_defaults_aliases = items_with_defaults_aliases
        self._items_with_defaults_types = items_with_defaults_types

        logger.debug(
            "Loaded %d aliases for items with default ingredients (from bulk)",
            len(items_with_defaults_aliases),
        )

    def _load_side_items_from_bulk(self, bulk_data: dict) -> None:
        """Load side items and their aliases from bulk data."""
        menu_item_categories = bulk_data["menu_item_categories"]

        # Filter to just the side category items
        side_menu_items = [
            mic.menu_item
            for mic in menu_item_categories
            if mic.category and mic.category.slug == "side" and mic.menu_item
        ]

        # Use helper to build alias mapping
        self._side_items, self._side_alias_to_canonical = build_alias_mapping(
            side_menu_items, name_attr="name", aliases_attr="aliases"
        )

        logger.debug(
            "Loaded %d side item aliases (from bulk)",
            len(self._side_alias_to_canonical),
        )

    def _load_menu_item_categories_from_bulk(self, bulk_data: dict) -> None:
        """Load menu item categories (from bulk)."""
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

    def _load_items_with_required_phrases_from_bulk(self, bulk_data: dict) -> None:
        """Load menu items that have required_match_phrases set (from bulk)."""
        menu_items = bulk_data["menu_items"]

        items_with_phrases: dict[str, str] = {}
        phrase_item_types: dict[str, str] = {}

        for item in menu_items:
            if item.required_match_phrases:
                items_with_phrases[item.name.lower()] = item.required_match_phrases
                if item.item_type:
                    phrase_item_types[item.name.lower()] = item.item_type.slug

        self._items_with_required_phrases = items_with_phrases
        self._required_phrase_item_types = phrase_item_types
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
                alias = normalize_text(alias)
                if alias:
                    unit_type_aliases[unit_type][alias] = (base_name, item_type_slug)

            # Derive aliases from item names for better by-weight matching
            # e.g., "muenster" from "Muenster Cheese", "whitefish" from "Whitefish Salad"
            if unit_type == "by_weight" and " " in base_name_lower:
                words = base_name_lower.split()
                first_word = words[0]
                if first_word not in unit_type_aliases[unit_type]:
                    unit_type_aliases[unit_type][first_word] = (base_name, item_type_slug)

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
                alias_lower = normalize_text(alias)
                if alias_lower:
                    item_names_by_type[item_type_slug].add(alias_lower)
                    alias_to_canonical_by_type[item_type_slug][alias_lower] = canonical_name

        self._item_names_by_type = item_names_by_type
        self._item_alias_to_canonical_by_type = alias_to_canonical_by_type

        logger.debug(
            "Loaded generic item names (from bulk) for %d item types",
            len(item_names_by_type),
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
                if len(word) >= MIN_KEYWORD_LENGTH and word not in {"the", "and", "with"}:
                    keyword_index[word].append(name_lower)

            for alias in item.aliases:
                alias_lower = normalize_text(alias)
                if alias_lower:
                    all_items[alias_lower] = item_data
                    for word in alias_lower.split():
                        if len(word) >= MIN_KEYWORD_LENGTH and word not in {"the", "and", "with"}:
                            keyword_index[word].append(name_lower)

        self._all_menu_items_by_name = all_items
        self._recommendation_keyword_index = dict(keyword_index)

        logger.debug(
            "Loaded recommendation search data (from bulk): %d items, %d keywords",
            len(all_items),
            len(keyword_index),
        )

    def _load_menu_item_default_ingredients_from_bulk(self, bulk_data: dict) -> None:
        """Load default ingredients for menu items (from bulk).

        Populates _menu_item_default_ingredients: menu_item_id -> list of ingredient dicts
        Each dict contains: ingredient_id, ingredient_slug, ingredient_name, ingredient_category, quantity
        """
        menu_item_ingredients = bulk_data.get("menu_item_ingredients", [])

        defaults_by_item: dict[int, list[dict]] = {}

        for link in menu_item_ingredients:
            if not link.menu_item or not link.ingredient:
                continue

            menu_item_id = link.menu_item_id
            ingredient = link.ingredient

            if menu_item_id not in defaults_by_item:
                defaults_by_item[menu_item_id] = []

            defaults_by_item[menu_item_id].append({
                "ingredient_id": ingredient.id,
                "ingredient_slug": ingredient.slug,
                "ingredient_name": ingredient.name,
                "ingredient_category": ingredient.category,
                "quantity": link.quantity or 1,
            })

        self._menu_item_default_ingredients = defaults_by_item

        logger.debug(
            "Loaded default ingredients for %d menu items (from bulk)",
            len(defaults_by_item),
        )

    def _build_prefix_index_from_menu_index(self) -> None:
        """Build index of menu items by first word of name.

        This enables queries like "what iced drinks do you have?" by indexing
        items under their name prefix (e.g., "iced" -> [Iced Coffee, Iced Tea]).

        Must be called after _load_menu_index() since it uses _menu_index.
        """
        prefix_index: dict[str, list[dict]] = {}

        items_by_type = self._menu_index.get("items_by_type", {})
        seen_names: set[str] = set()  # Avoid duplicates across item types

        for items in items_by_type.values():
            for item in items:
                name = item.get("name", "")
                name_lower = name.lower()

                # Skip if we've already indexed this item
                if name_lower in seen_names:
                    continue
                seen_names.add(name_lower)

                # Only index multi-word names (e.g., "Iced Coffee", not "Latte")
                words = name.split()
                if len(words) >= MIN_PREFIX_WORDS:
                    prefix = words[0].lower()
                    if prefix not in prefix_index:
                        prefix_index[prefix] = []
                    prefix_index[prefix].append(item)

        self._menu_items_by_prefix = prefix_index

        logger.debug(
            "Built prefix index: %d prefixes, %d total items",
            len(prefix_index),
            sum(len(items) for items in prefix_index.values()),
        )

    def _load_dietary_data_from_bulk(self, bulk_data: dict) -> None:
        """Load dietary and allergen data for menu items (from bulk).

        Computes dietary properties from ingredients when available, falls back
        to stored column values when no ingredients are defined.

        Populates:
        - _items_by_dietary_property: maps dietary property to list of matching items
        - _item_dietary_info: maps item name to its dietary/allergen info dict

        Dietary properties: is_vegan, is_vegetarian, is_gluten_free, is_dairy_free, is_kosher
        Allergen properties: contains_eggs, contains_fish, contains_sesame, contains_nuts
        """
        menu_items = bulk_data["menu_items"]

        # All dietary and allergen property names
        dietary_properties = [
            "is_vegan", "is_vegetarian", "is_gluten_free", "is_dairy_free", "is_kosher"
        ]
        allergen_properties = [
            "contains_eggs", "contains_fish", "contains_sesame", "contains_nuts"
        ]
        all_properties = dietary_properties + allergen_properties

        # Initialize cache structures
        items_by_property: dict[str, list[dict]] = {prop: [] for prop in all_properties}
        item_dietary_info: dict[str, dict] = {}

        for item in menu_items:
            name_lower = item.name.lower()
            item_type_slug = item.item_type.slug if item.item_type else None

            # Get ingredients from eagerly loaded relationship
            ingredients = [link.ingredient for link in item.ingredient_links if link.ingredient]
            has_ingredients = len(ingredients) > 0

            # Compute dietary values from ingredients if available
            computed_values = self._compute_dietary_from_ingredients(
                ingredients, dietary_properties, allergen_properties
            ) if has_ingredients else {}

            # Build dietary info dict for this item
            dietary_info = {
                "id": item.id,
                "name": item.name,
                "item_type_slug": item_type_slug,
                "base_price": float(item.base_price) if item.base_price else 0.0,
                "has_ingredients": has_ingredients,
            }

            # Add all dietary/allergen properties: computed takes precedence, then fallback to stored
            for prop in all_properties:
                if prop in computed_values:
                    dietary_info[prop] = computed_values[prop]
                else:
                    dietary_info[prop] = getattr(item, prop, None)

            # Store per-item info
            item_dietary_info[name_lower] = dietary_info

            # Also index by aliases
            for alias in item.aliases:
                alias_lower = normalize_text(alias)
                if alias_lower:
                    item_dietary_info[alias_lower] = dietary_info

            # Index items by dietary property (True values only)
            for prop in dietary_properties:
                if dietary_info.get(prop) is True:
                    items_by_property[prop].append({
                        "id": item.id,
                        "name": item.name,
                        "item_type_slug": item_type_slug,
                        "base_price": float(item.base_price) if item.base_price else 0.0,
                    })

            # For allergen properties, also index items that DON'T contain the allergen
            # (useful for "nut-free options" queries)
            for prop in allergen_properties:
                # Items where contains_X is explicitly False are allergen-free
                if dietary_info.get(prop) is False:
                    free_prop = prop.replace("contains_", "") + "_free"
                    if free_prop not in items_by_property:
                        items_by_property[free_prop] = []
                    items_by_property[free_prop].append({
                        "id": item.id,
                        "name": item.name,
                        "item_type_slug": item_type_slug,
                        "base_price": float(item.base_price) if item.base_price else 0.0,
                    })

        self._items_by_dietary_property = items_by_property
        self._item_dietary_info = item_dietary_info

        # Log summary
        counts = {k: len(v) for k, v in items_by_property.items() if v}
        logger.debug(
            "Loaded dietary data for %d menu items (from bulk): %s",
            len(item_dietary_info),
            counts,
        )

    def _compute_dietary_from_ingredients(
        self,
        ingredients: list,
        dietary_properties: list[str],
        allergen_properties: list[str],
    ) -> dict[str, bool | None]:
        """Compute dietary/allergen values from a list of ingredients.

        Args:
            ingredients: List of Ingredient model objects
            dietary_properties: List of dietary property names (is_vegan, etc.)
            allergen_properties: List of allergen property names (contains_eggs, etc.)

        Returns:
            Dict mapping property names to computed boolean values.
            Empty dict if no ingredients provided.
        """
        if not ingredients:
            return {}

        result: dict[str, bool | None] = {}

        # Dietary properties: ALL ingredients must have property=True for item to be True
        # (e.g., item is vegan only if all ingredients are vegan)
        for prop in dietary_properties:
            values = [getattr(ing, prop, None) for ing in ingredients]
            # Only compute if at least one ingredient has a defined value
            if not all(v is None for v in values):
                # Item has property only if ALL non-None values are True
                result[prop] = all(v is True for v in values if v is not None)

        # Allergen properties: ANY ingredient having property=True means item has it
        # (e.g., item contains eggs if any ingredient contains eggs)
        for prop in allergen_properties:
            values = [getattr(ing, prop, None) for ing in ingredients]
            # Only compute if at least one ingredient has a defined value
            if not all(v is None for v in values):
                # Item has allergen if ANY non-None value is True
                result[prop] = any(v is True for v in values)

        return result
