"""
Item Type Configuration Loader Mixin.

Contains loader methods for item type triggers, category keywords,
item type fields, and item type metadata.
"""

import logging

from ..base import build_index_by_key, pluralize

logger = logging.getLogger(__name__)


class ItemTypeConfigLoaderMixin:
    """Mixin for loading item type configuration and metadata."""

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
        menu_items_by_type_id = build_index_by_key(menu_items, "item_type_id")

        for item_type in item_types:
            triggers: set[str] = set()

            triggers.add(item_type.slug.lower())

            if item_type.display_name:
                triggers.add(item_type.display_name.lower())
                if item_type.display_name.lower().endswith("s"):
                    triggers.add(item_type.display_name.lower()[:-1])

            # Add item type aliases (e.g., "omelet" for "omelette")
            for alias in item_type.aliases:
                alias_lower = alias.strip().lower()
                if alias_lower:
                    triggers.add(alias_lower)

            # Use pre-built index instead of per-item-type query
            type_menu_items = menu_items_by_type_id.get(item_type.id, [])

            for item in type_menu_items:
                name_lower = item.name.lower()
                triggers.add(name_lower)

                for suffix in all_type_suffixes:
                    if name_lower.endswith(suffix):
                        stripped = name_lower[:-len(suffix)]
                        # If the item has required_match_phrases, only add the
                        # stripped trigger when it satisfies those phrases.
                        if item.required_match_phrases:
                            phrases = [
                                p.strip().lower()
                                for p in item.required_match_phrases.split(",")
                                if p.strip()
                            ]
                            if not any(phrase in stripped for phrase in phrases):
                                continue
                        triggers.add(stripped)

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

    def _load_category_keywords_from_bulk(self, bulk_data: dict) -> None:
        """Load category keyword mappings from bulk data."""
        item_types = bulk_data["item_types"]
        categories = bulk_data["categories"]

        category_keywords: dict[str, dict] = {}
        item_type_displays: dict[str, dict] = {}  # For get_categories_for_inference()

        # 1. Load ItemTypes
        for item_type in item_types:
            slug = item_type.slug
            display_name = item_type.display_name
            display_name_plural = item_type.display_name_plural or pluralize(display_name)

            category_info = {
                "slug": slug,
                "display_name": display_name,
                "display_name_plural": display_name_plural,
                "lookup_type": "item_type",
            }

            category_keywords[slug] = category_info

            # Also populate item_type_displays for LLM category inference
            item_type_displays[slug] = {
                "display_name": display_name,
                "display_name_plural": display_name_plural,
            }

            for alias in item_type.aliases:
                alias = alias.strip().lower()
                if alias:
                    category_keywords[alias] = category_info

        # 2. Load Categories
        for category in categories:
            slug = category.slug
            display_name = category.name
            display_name_plural = pluralize(display_name)

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
        self._item_type_displays = item_type_displays

        logger.debug(
            "Loaded %d category keywords, %d item type displays (from bulk)",
            len(category_keywords),
            len(item_type_displays),
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
                    "question_text": global_attr.question_text,
                    "offer_question_text": global_attr.offer_question_text,
                    "input_type": global_attr.input_type,
                    "display_name": global_attr.display_name,
                })

        self._item_type_fields = item_type_fields

        logger.debug(
            "Loaded item type fields for %d item types (from bulk)",
            len(item_type_fields),
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
