"""
Menu Item Loaders for MenuDataCache.

Contains loader methods for menu items, signature items, side items,
and related data structures.
"""

import logging
import re
from collections import defaultdict

from ..base import build_alias_mapping

logger = logging.getLogger(__name__)


class MenuItemLoaderMixin:
    """Mixin containing menu item loading methods."""

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
