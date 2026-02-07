"""
Ingredient Loaders for MenuDataCache.

Contains loader methods for ingredients, modifiers, and related data.
"""

import logging

from ..base import build_alias_mapping

logger = logging.getLogger(__name__)


class IngredientLoaderMixin:
    """Mixin containing ingredient and modifier loading methods."""

    def _load_modifier_aliases_from_bulk(self, bulk_data: dict) -> None:
        """Load modifier alias mappings from bulk data."""
        ingredients = bulk_data["ingredients"]

        # Use helper to build alias mapping (we only need the alias dict, not the set)
        _, self._modifier_aliases = build_alias_mapping(
            ingredients, name_attr="name", aliases_attr="aliases"
        )

        logger.debug(
            "Loaded %d modifier aliases (from bulk)",
            len(self._modifier_aliases),
        )

    def _load_ingredient_price_contexts_from_bulk(self, bulk_data: dict) -> None:
        """Load ingredient price contexts from bulk data (no N+1 queries).

        Uses bulk_data for ingredients, item_types, menu_items, and global_attr_options.
        Derives item type links from GlobalAttributeOption -> ItemTypeGlobalAttribute.
        """
        ingredients = bulk_data["ingredients"]
        item_types = bulk_data["item_types"]
        menu_items = bulk_data["menu_items"]
        global_attr_options = bulk_data["global_attr_options"]

        self._ingredient_price_contexts = {}

        # Build ingredient_id -> price from GlobalAttributeOption
        ingredient_prices: dict[int, float] = {}
        for opt in global_attr_options:
            if opt.ingredient_id is not None:
                ingredient_prices[opt.ingredient_id] = float(opt.price_modifier or 0)

        # Build ingredient_id -> list of (item_type_slug, item_type_display_name)
        # by traversing ItemType -> ItemTypeGlobalAttribute -> GlobalAttribute -> GlobalAttributeOption
        type_ingredient_index: dict[int, list[tuple]] = {}
        for item_type in item_types:
            for ga_link in item_type.global_attribute_links:
                global_attr = ga_link.global_attribute
                if not global_attr:
                    continue
                for option in global_attr.options:
                    if option.ingredient_id:
                        if option.ingredient_id not in type_ingredient_index:
                            type_ingredient_index[option.ingredient_id] = []
                        # Avoid duplicates
                        entry = (item_type.slug, item_type.display_name)
                        if entry not in type_ingredient_index[option.ingredient_id]:
                            type_ingredient_index[option.ingredient_id].append(entry)

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

    def _load_generic_ingredients_from_bulk(self, bulk_data: dict) -> None:
        """Load all ingredients grouped by category (from bulk)."""
        ingredients = bulk_data["ingredients"]

        ingredients_by_category: dict[str, set[str]] = {}
        ingredient_details_by_category: dict[str, list[dict]] = {}

        # Also build reverse mapping: modifier -> category
        modifier_to_category: dict[str, str] = {}

        for ing in ingredients:
            category = ing.category
            if not category:
                continue

            if category not in ingredients_by_category:
                ingredients_by_category[category] = set()
                ingredient_details_by_category[category] = []

            name_lower = ing.name.lower()
            ingredients_by_category[category].add(name_lower)
            modifier_to_category[name_lower] = category

            patterns = [name_lower]
            for alias in ing.aliases:
                alias_lower = alias.strip().lower()
                if alias_lower:
                    ingredients_by_category[category].add(alias_lower)
                    modifier_to_category[alias_lower] = category
                    patterns.append(alias_lower)

            ingredient_details_by_category[category].append({
                "slug": ing.slug,
                "name": ing.name,
                "patterns": patterns,
                "must_match": ing.must_match,
            })

        self._ingredients_by_category = ingredients_by_category
        self._ingredient_details_by_category = ingredient_details_by_category
        self._modifier_to_category = modifier_to_category

        logger.debug(
            "Loaded generic ingredients (from bulk) for %d categories",
            len(ingredients_by_category),
        )

    def _load_generic_ingredients_for_item_types_from_bulk(self, bulk_data: dict) -> None:
        """Load ingredients valid for each ItemType (from bulk).

        Derives the mapping from GlobalAttributeOption -> ItemTypeGlobalAttribute -> ItemType.
        An ingredient is valid for an item type if:
        1. A GlobalAttributeOption links to that ingredient
        2. That option's GlobalAttribute is linked to the ItemType via ItemTypeGlobalAttribute
        """
        item_types = bulk_data["item_types"]

        ingredients_for_item_type: dict[str, dict[str, set[str]]] = {}

        for item_type in item_types:
            item_type_slug = item_type.slug

            # Iterate through the item type's global attribute links
            for ga_link in item_type.global_attribute_links:
                global_attr = ga_link.global_attribute
                if not global_attr:
                    continue

                # Check each option in this global attribute
                for option in global_attr.options:
                    ingredient = option.ingredient
                    if not ingredient:
                        continue

                    category = ingredient.category or "uncategorized"

                    if item_type_slug not in ingredients_for_item_type:
                        ingredients_for_item_type[item_type_slug] = {}
                    if category not in ingredients_for_item_type[item_type_slug]:
                        ingredients_for_item_type[item_type_slug][category] = set()

                    # Add ingredient name
                    ingredients_for_item_type[item_type_slug][category].add(
                        ingredient.name.lower()
                    )

                    # Add ingredient aliases
                    for alias in ingredient.aliases:
                        alias_lower = alias.strip().lower()
                        if alias_lower:
                            ingredients_for_item_type[item_type_slug][category].add(alias_lower)

        self._ingredients_for_item_type = ingredients_for_item_type

        logger.debug(
            "Loaded ingredients for %d item types (from bulk via global attributes)",
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

    def _load_modifier_categories_from_bulk(self, bulk_data: dict) -> None:
        """Load modifier categories (from bulk)."""
        categories = bulk_data.get("modifier_categories", [])

        modifier_categories: dict[str, dict] = {}
        modifier_category_alias_to_slug: dict[str, str] = {}

        for cat in categories:
            # Get aliases from the eagerly loaded relationship
            aliases = cat.aliases if hasattr(cat, 'aliases') else []

            modifier_categories[cat.slug] = {
                "display_name": cat.display_name,
                "loads_from_ingredients": cat.loads_from_ingredients,
                "ingredient_category": cat.ingredient_category,
                "description": cat.description,
                "prompt_suffix": cat.prompt_suffix,
                "aliases": aliases,
            }

            # Build reverse lookup: alias -> category slug
            for alias in aliases:
                modifier_category_alias_to_slug[alias.lower()] = cat.slug

        self._modifier_categories = modifier_categories
        self._modifier_category_alias_to_slug = modifier_category_alias_to_slug

        logger.debug(
            "Loaded modifier categories (from bulk): %d categories, %d aliases",
            len(modifier_categories),
            len(modifier_category_alias_to_slug),
        )
