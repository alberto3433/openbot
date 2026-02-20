"""
Item Type Suggestions Loader Mixin.

Contains loader methods for option skip rules, unrecognized option/ingredient
suggestions, and menu display groups.
"""

import logging

logger = logging.getLogger(__name__)


class ItemTypeSuggestionsLoaderMixin:
    """Mixin for loading suggestion rules and display group configurations."""

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

    def _load_unrecognized_option_suggestions_from_bulk(self, bulk_data: dict) -> None:
        """Load unrecognized option suggestions from bulk data.

        These are common attribute option terms that aren't in our menu
        (e.g., "venti" size) that we want to detect and respond appropriately to.
        """
        suggestions = bulk_data.get("unrecognized_option_suggestions", [])

        result: dict[str, dict[str, str]] = {}

        for s in suggestions:
            if not s.is_active:
                continue
            attr_slug = s.attribute_slug
            pattern = s.input_pattern.lower()
            display = s.suggested_display_name

            if attr_slug not in result:
                result[attr_slug] = {}
            result[attr_slug][pattern] = display

        self._unrecognized_option_suggestions = result

        logger.debug(
            "Loaded unrecognized option suggestions: %d attributes, %d total patterns",
            len(result),
            sum(len(v) for v in result.values()),
        )

    def _load_unrecognized_ingredient_suggestions_from_bulk(self, bulk_data: dict) -> None:
        """Load unrecognized ingredient suggestions from bulk data.

        These are common ingredient terms not on our menu (e.g., "honey")
        that we want to detect and suggest alternatives for.
        """
        suggestions = bulk_data.get("unrecognized_ingredient_suggestions", [])

        result: dict[str, dict] = {}

        for s in suggestions:
            if not s.is_active:
                continue
            pattern = s.input_pattern.lower()
            alternatives = []
            for ing in (s.alternative_ingredients or []):
                alternatives.append({
                    "name": ing.name,
                    "slug": ing.name.lower().replace(" ", "_"),
                })

            result[pattern] = {
                "display_name": s.suggested_display_name,
                "modifier_category": s.modifier_category,
                "match_type": s.match_type,
                "alternatives": alternatives,
            }

        self._unrecognized_ingredient_suggestions = result

        logger.debug(
            "Loaded unrecognized ingredient suggestions: %d patterns",
            len(result),
        )

    def _load_menu_display_groups_from_bulk(self, bulk_data: dict) -> None:
        """Load menu display groups from bulk data.

        Display groups are high-level menu categories shown when user asks
        "what's on your menu?" - e.g., "breads", "sandwiches", "drinks".

        Also builds:
        - mapping of display group slug -> item type slugs for queries like "what breads do you have?"
        - mapping of alias -> group slug for recognizing user references like "pastries"
        """
        groups = bulk_data.get("menu_display_groups", [])
        item_types = bulk_data.get("item_types", [])

        # Build id -> slug lookup for resolving parent references
        id_to_slug = {g.id: g.slug for g in groups}

        self._menu_display_groups_ordered = [
            {
                "slug": g.slug,
                "display_name": g.display_name,
                "display_order": g.display_order,
                "parent_slug": id_to_slug.get(g.parent_id) if g.parent_id else None,
            }
            for g in sorted(groups, key=lambda g: g.display_order)
        ]

        # Build parent-child hierarchy: parent_slug -> [child_slugs]
        children: dict[str, list[str]] = {}
        for g in groups:
            if g.parent_id:
                parent_slug = id_to_slug.get(g.parent_id)
                if parent_slug:
                    children.setdefault(parent_slug, []).append(g.slug)
        self._display_group_children = children

        # Build mapping: display_group_slug -> list of item_type_slugs
        item_types_by_group: dict[str, list[str]] = {}
        for it in item_types:
            if it.menu_display_group:
                group_slug = it.menu_display_group.slug
                if group_slug not in item_types_by_group:
                    item_types_by_group[group_slug] = []
                item_types_by_group[group_slug].append(it.slug)

        self._item_types_by_display_group = item_types_by_group

        # Build mapping: alias -> group_slug
        alias_to_slug: dict[str, str] = {}
        for g in groups:
            # alias_records is eagerly loaded
            for alias_record in g.alias_records:
                alias_lower = alias_record.alias.lower()
                alias_to_slug[alias_lower] = g.slug

        self._display_group_alias_to_slug = alias_to_slug

        logger.debug(
            "Loaded %d menu display groups: %s",
            len(self._menu_display_groups_ordered),
            [g["slug"] for g in self._menu_display_groups_ordered],
        )
        logger.debug(
            "Item types by display group: %s",
            {k: len(v) for k, v in item_types_by_group.items()},
        )
        logger.debug(
            "Loaded %d display group aliases, %d parent-child relationships",
            len(alias_to_slug),
            sum(len(v) for v in children.values()),
        )
