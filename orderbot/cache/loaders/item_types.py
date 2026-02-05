"""
Item Type Loaders for MenuDataCache.

Contains loader methods for item types, attributes, and related configuration.
"""

import logging

from ..base import build_index_by_key

logger = logging.getLogger(__name__)


class ItemTypeLoaderMixin:
    """Mixin containing item type and attribute loading methods."""

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
                    "listen_only": link.listen_only,
                    "display_order": link.display_order,
                    "question_text": link.question_text,
                    "options": options,
                    "source": "global",
                    "modifies_ingredient_slug": getattr(attr, 'modifies_ingredient_slug', None),
                }
                field_to_slug_map[attr.slug] = attr.slug

            self._item_type_attributes[item_type.slug] = result
            self._field_to_slug_map[item_type.slug] = field_to_slug_map

        logger.debug(
            "Pre-loaded attributes for %d item types (from bulk)",
            len(self._item_type_attributes),
        )

        # Build option alias -> (item_type, attr_slug, option_slug) mapping
        # This enables inferring item type from attribute option aliases
        # e.g., "earl grey" -> ("tea", "tea_flavor", "earl_gray")
        #
        # IMPORTANT: Options that are shared across multiple item types (like "large", "small")
        # are excluded because they are ambiguous - saying "large" doesn't tell us if the user
        # wants a large coffee, latte, or fruit salad.

        # First pass: collect all options and the item types that have them
        option_to_item_types: dict[str, set[str]] = {}

        for item_type_slug, attrs in self._item_type_attributes.items():
            # Only map options for configurable item types
            if item_type_slug not in self._configurable_item_type_slugs:
                continue

            for attr_slug, attr_config in attrs.items():
                for opt in attr_config.get("options", []):
                    opt_slug = opt.get("slug")
                    if not opt_slug:
                        continue

                    # Track all keys for this option
                    keys = []

                    # Option slug itself (with underscores replaced by spaces)
                    key = opt_slug.lower().replace("_", " ")
                    keys.append(key)

                    # Display name
                    display_name = opt.get("display_name")
                    if display_name:
                        keys.append(display_name.lower().strip())

                    # Aliases
                    for alias in (opt.get("aliases") or []):
                        alias_lower = alias.lower().strip()
                        if alias_lower:
                            keys.append(alias_lower)

                    # Add this item type to each key's set
                    for k in keys:
                        if k not in option_to_item_types:
                            option_to_item_types[k] = set()
                        option_to_item_types[k].add(item_type_slug)

        # Second pass: build the mapping, excluding ambiguous options
        option_alias_to_item_type: dict[str, tuple[str, str, str]] = {}

        for item_type_slug, attrs in self._item_type_attributes.items():
            if item_type_slug not in self._configurable_item_type_slugs:
                continue

            for attr_slug, attr_config in attrs.items():
                for opt in attr_config.get("options", []):
                    opt_slug = opt.get("slug")
                    if not opt_slug:
                        continue

                    # Option slug itself
                    key = opt_slug.lower().replace("_", " ")
                    if len(option_to_item_types.get(key, set())) == 1:
                        if key not in option_alias_to_item_type:
                            option_alias_to_item_type[key] = (item_type_slug, attr_slug, opt_slug)

                    # Display name
                    display_name = opt.get("display_name")
                    if display_name:
                        display_key = display_name.lower().strip()
                        if display_key and len(option_to_item_types.get(display_key, set())) == 1:
                            if display_key not in option_alias_to_item_type:
                                option_alias_to_item_type[display_key] = (item_type_slug, attr_slug, opt_slug)

                    # Aliases
                    for alias in (opt.get("aliases") or []):
                        alias_lower = alias.lower().strip()
                        if alias_lower and len(option_to_item_types.get(alias_lower, set())) == 1:
                            if alias_lower not in option_alias_to_item_type:
                                option_alias_to_item_type[alias_lower] = (item_type_slug, attr_slug, opt_slug)

        self._option_alias_to_item_type = option_alias_to_item_type
        logger.debug(
            "Built option alias -> item type mapping with %d entries",
            len(option_alias_to_item_type),
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

    def _load_option_skip_rules_from_bulk(self, bulk_data: dict) -> None:
        """Load attribute option skip rules from bulk data.

        Skip rules define which attributes to skip when certain options are selected.
        For example, selecting "black" for coffee skips asking about milk/sweetener/syrup.
        """
        skip_rules = bulk_data.get("option_skip_rules", [])

        option_skip_rules: dict[str, set[str]] = {}

        for rule in skip_rules:
            # Get the triggering option's slug
            opt = rule.triggering_option
            if not opt:
                continue
            # Derive slug from linked ingredient if present, otherwise use option slug
            opt_slug = opt.ingredient.slug if opt.ingredient else opt.slug
            if not opt_slug:
                continue

            # Get the skipped attribute's slug
            attr = rule.skipped_attribute
            if not attr:
                continue
            attr_slug = attr.slug

            # Build the mapping
            if opt_slug not in option_skip_rules:
                option_skip_rules[opt_slug] = set()
            option_skip_rules[opt_slug].add(attr_slug)

        self._option_skip_rules = option_skip_rules

        logger.debug(
            "Loaded %d option skip rules from bulk: %s",
            sum(len(v) for v in option_skip_rules.values()),
            {k: list(v) for k, v in option_skip_rules.items()},
        )

    def _load_component_slots_from_bulk(self, bulk_data: dict) -> None:
        """Load component slots from bulk data.

        Component slots define how item types can include configurable sub-items.
        For example, omelettes have a "side" slot that accepts bagels or fruit salad.
        """
        slots = bulk_data.get("component_slots", [])

        component_slots: dict[str, dict[str, dict]] = {}

        for slot in slots:
            parent_type_slug = slot.parent_item_type.slug

            if parent_type_slug not in component_slots:
                component_slots[parent_type_slug] = {}

            # Build options list
            options = []
            for opt in slot.slot_options:
                option_dict = {
                    "price_rule": opt.price_rule,
                    "fixed_price": opt.fixed_price,
                    "included_price_cents": opt.included_price_cents,
                    "display_name": opt.display_name,
                    "display_order": opt.display_order,
                }

                if opt.allowed_item_type:
                    option_dict["allowed_item_type"] = opt.allowed_item_type.slug
                if opt.allowed_menu_item:
                    option_dict["allowed_menu_item_id"] = opt.allowed_menu_item.id
                    option_dict["allowed_menu_item_name"] = opt.allowed_menu_item.name

                options.append(option_dict)

            # Sort options by display_order
            options.sort(key=lambda x: x.get("display_order", 0))

            component_slots[parent_type_slug][slot.slot_name] = {
                "display_name": slot.display_name,
                "prompt_text": slot.prompt_text,
                "is_required": slot.is_required,
                "min_quantity": slot.min_quantity,
                "max_quantity": slot.max_quantity,
                "display_order": slot.display_order,
                "options": options,
            }

        self._component_slots = component_slots

        logger.debug(
            "Loaded component slots for %d item types: %s",
            len(component_slots),
            list(component_slots.keys()),
        )
