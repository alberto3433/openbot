"""
Item Type Global Attributes Loader Mixin.

Contains loader methods for global attribute options, priced attributes,
item type attributes, and global attribute aliases.
"""

import logging

from ..base import build_index_by_key, normalize_text

logger = logging.getLogger(__name__)


class ItemTypeGlobalAttrsLoaderMixin:
    """Mixin for loading global attributes and item type attribute configurations."""

    @staticmethod
    def _build_option_base(opt) -> dict | None:
        """Build the common option dict fields from a GlobalAttributeOption.

        Returns None if the option has no valid slug (skipped).
        Shared by _build_global_option_dict and _preload_all_item_type_attributes.
        """
        # Start with option's own aliases
        aliases = list(opt.aliases) if opt.aliases else []

        # Add linked ingredient aliases (if any)
        must_match = None
        ingredient_category = None
        ingredient_subcategory = None
        if opt.ingredient:
            if opt.ingredient.aliases:
                for ing_alias in opt.ingredient.aliases:
                    if ing_alias not in aliases:
                        aliases.append(ing_alias)
            must_match = opt.ingredient.must_match
            ingredient_category = opt.ingredient.category
            ingredient_subcategory = opt.ingredient.subcategory

        # Derive slug/display_name from ingredient when linked
        slug = opt.ingredient.slug if opt.ingredient else opt.slug
        display_name = opt.ingredient.name if opt.ingredient else opt.display_name

        # Guard against NULL slug (ingredient-linked option with unloaded ingredient)
        if not slug:
            logger.warning(
                "GlobalAttributeOption id=%d has NULL slug (ingredient_id=%s). Skipping.",
                opt.id, getattr(opt, 'ingredient_id', None),
            )
            return None

        # Get forward_to_attribute slug if set
        forward_to_attribute = None
        if hasattr(opt, 'forward_to_attribute') and opt.forward_to_attribute:
            forward_to_attribute = opt.forward_to_attribute.slug

        return {
            "slug": slug,
            "display_name": display_name or slug,
            "price_modifier": opt.price_modifier,
            "is_default": opt.is_default,
            "is_available": opt.is_available,
            "aliases": aliases,
            "must_match": must_match,
            "ingredient_category": ingredient_category,
            "ingredient_subcategory": ingredient_subcategory,
            "forward_to_attribute": forward_to_attribute,
        }

    def _build_global_option_dict(self, opt) -> dict:
        """Build option dict with aliases from both option and linked ingredient.

        Aliases are merged from two sources:
        1. Option's own alias_records (GlobalAttributeOptionAlias)
        2. Linked Ingredient's alias_records (IngredientAlias)

        This allows options like "double_shot" to have aliases like "2 shots"
        without requiring a linked ingredient.
        """
        base = self._build_option_base(opt)
        if base is None:
            return None

        # Derive modifier_category from ingredient at runtime
        modifier_category_slug = None
        if opt.ingredient and opt.ingredient.modifier_category:
            modifier_category_slug = opt.ingredient.modifier_category.slug

        base["modifier_category"] = modifier_category_slug
        # Global options store None for empty aliases
        if not base["aliases"]:
            base["aliases"] = None

        return base

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
                "options_source_category": attr.options_source_category,
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
                    base = self._build_option_base(opt)
                    if base is None:
                        continue
                    # This context needs float-coerced price_modifier
                    base["price_modifier"] = float(base["price_modifier"] or 0)
                    options.append(base)

                # Filter options by subcategory if configured on the link
                subcategory_filter = getattr(link, 'option_subcategory_filter', None)
                if subcategory_filter:
                    options = [
                        o for o in options
                        if o.get("ingredient_subcategory") == subcategory_filter
                    ]

                # Override question_text when subcategory filter narrows the options
                question_text = attr.question_text
                if subcategory_filter:
                    subcategory_display = subcategory_filter.replace("_", " ")
                    question_text = f"What kind of {subcategory_display}?"

                result[attr.slug] = {
                    "slug": attr.slug,
                    "display_name": attr.display_name,
                    "input_type": attr.input_type,
                    "is_required": link.is_required,
                    "allow_none": link.allow_none,
                    "ask_in_conversation": link.ask_in_conversation,
                    "listen_only": link.listen_only,
                    "display_order": link.display_order,
                    "question_text": question_text,
                    "offer_question_text": attr.offer_question_text,
                    "options": options,
                    "source": "global",
                    "option_subcategory_filter": subcategory_filter,
                    "modifies_ingredient_slug": attr.modifies_ingredient.slug if attr.modifies_ingredient else None,
                }
                field_to_slug_map[attr.slug] = attr.slug

            self._item_type_attributes[item_type.slug] = result
            self._field_to_slug_map[item_type.slug] = field_to_slug_map

        # Build reverse index: attr_slug -> set of item_type_slugs that have that attribute
        attr_to_types: dict[str, set[str]] = {}
        for type_slug, attrs in self._item_type_attributes.items():
            for attr_slug in attrs:
                if attr_slug not in attr_to_types:
                    attr_to_types[attr_slug] = set()
                attr_to_types[attr_slug].add(type_slug)
        self._attr_to_item_types = attr_to_types

        logger.debug(
            "Pre-loaded attributes for %d item types (from bulk), %d attr->type mappings",
            len(self._item_type_attributes),
            len(self._attr_to_item_types),
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
                        keys.append(normalize_text(display_name))

                    # Aliases
                    for alias in (opt.get("aliases") or []):
                        alias_lower = normalize_text(alias)
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
                        display_key = normalize_text(display_name)
                        if display_key and len(option_to_item_types.get(display_key, set())) == 1:
                            if display_key not in option_alias_to_item_type:
                                option_alias_to_item_type[display_key] = (item_type_slug, attr_slug, opt_slug)

                    # Aliases
                    for alias in (opt.get("aliases") or []):
                        alias_lower = normalize_text(alias)
                        if alias_lower and len(option_to_item_types.get(alias_lower, set())) == 1:
                            if alias_lower not in option_alias_to_item_type:
                                option_alias_to_item_type[alias_lower] = (item_type_slug, attr_slug, opt_slug)

        self._option_alias_to_item_type = option_alias_to_item_type
        logger.debug(
            "Built option alias -> item type mapping with %d entries",
            len(option_alias_to_item_type),
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
