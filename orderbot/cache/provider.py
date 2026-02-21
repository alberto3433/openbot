"""
Menu data providers for MenuDataCache.

Defines the MenuProvider protocol (the abstraction boundary) and
DatabaseProvider (the default implementation that loads from PostgreSQL).

Future providers (Square, Toast, etc.) implement MenuProvider to supply
menu data from external APIs without changing any cache loader logic.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session, joinedload, selectinload

logger = logging.getLogger(__name__)


class MenuProvider(Protocol):
    """Protocol defining the data source interface for MenuDataCache.

    Providers produce the data structures that cache loaders consume.
    The abstraction boundary is the bulk_data dict and the two auxiliary
    data structures (menu_index and attribute_inquiry_keywords).
    """

    def load_bulk_data(self) -> dict[str, list[Any]]:
        """Load all menu data tables in bulk.

        Returns:
            Dict mapping table names to lists of objects with the expected
            attribute shapes (e.g. .slug, .name, .aliases).
        """
        ...

    def load_menu_index(self) -> dict[str, Any]:
        """Load or build the menu search index.

        Returns:
            Menu index dict as produced by build_menu_index().
        """
        ...

    def load_attribute_inquiry_keywords(self) -> dict[tuple[str, str | None], str]:
        """Load attribute inquiry keyword mappings.

        Returns:
            Dict mapping (keyword, item_type_slug_or_None) -> attribute_slug.
        """
        ...


class DatabaseProvider:
    """MenuProvider implementation that loads data from PostgreSQL via SQLAlchemy."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def load_bulk_data(self) -> dict[str, list[Any]]:
        """Load ALL tables needed for cache in minimal queries using eager loading.

        This eliminates N+1 query patterns by loading all related data upfront
        with selectinload/joinedload, then processing in memory.

        Returns:
            Dict with pre-loaded data for use by cache loader methods.
        """
        from ..db.models import (
            GlobalAttribute, GlobalAttributeOption, GlobalAttributeOptionSkip, Ingredient,
            ItemType, ItemTypeGlobalAttribute, MenuItem,
            ResponsePattern, ModifierQualifier,
            ModifierCategory, IngredientCategory, GlobalAttributeAlias,
            MenuItemIngredient, ItemTypeComponentSlot, ComponentSlotOption,
            UnrecognizedOptionSuggestion, UnrecognizedIngredientSuggestion,
            MenuDisplayGroup,
        )

        db = self._db
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
                # Load modifies_ingredient for deriving the slug
                joinedload(GlobalAttribute.modifies_ingredient),
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

        # 3. Load MenuItem with aliases, item_type, size_prices, and ingredient_links
        menu_items = (
            db.query(MenuItem)
            .options(
                selectinload(MenuItem.alias_records),
                joinedload(MenuItem.item_type),
                selectinload(MenuItem.size_prices),
                selectinload(MenuItem.ingredient_links)
                    .joinedload(MenuItemIngredient.ingredient),
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
        except (OperationalError, ProgrammingError):
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
        except (OperationalError, ProgrammingError):
            # Table may not exist yet if migrations haven't run
            option_skip_rules = []

        # 17. Load unrecognized option suggestions (for detecting terms not in our menu)
        try:
            unrecognized_option_suggestions = (
                db.query(UnrecognizedOptionSuggestion)
                .filter(UnrecognizedOptionSuggestion.is_active == True)  # noqa: E712
                .all()
            )
        except (OperationalError, ProgrammingError):
            # Table may not exist yet if migrations haven't run
            unrecognized_option_suggestions = []

        # 18. Load unrecognized ingredient suggestions (for ingredients not on the menu)
        try:
            unrecognized_ingredient_suggestions = (
                db.query(UnrecognizedIngredientSuggestion)
                .filter(UnrecognizedIngredientSuggestion.is_active == True)  # noqa: E712
                .all()
            )
        except (OperationalError, ProgrammingError):
            # Table may not exist yet if migrations haven't run
            unrecognized_ingredient_suggestions = []

        # 19. Load menu display groups (for "what's on your menu?" responses)
        try:
            menu_display_groups = (
                db.query(MenuDisplayGroup)
                .options(selectinload(MenuDisplayGroup.alias_records))
                .order_by(MenuDisplayGroup.display_order)
                .all()
            )
        except (OperationalError, ProgrammingError):
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
            "unrecognized_ingredient_suggestions": unrecognized_ingredient_suggestions,
            "menu_display_groups": menu_display_groups,
        }

    def load_menu_index(self) -> dict[str, Any]:
        """Load and build the menu index from the database."""
        from ..menu_index import build_menu_index

        logger.info("Building menu index (this may take a moment)...")
        start = time.time()
        menu_index = build_menu_index(self._db)
        elapsed = time.time() - start
        logger.info(
            "Menu index built in %.1f seconds with %d total items",
            elapsed,
            sum(len(v) for k, v in menu_index.items() if isinstance(v, list)),
        )
        return menu_index

    def load_attribute_inquiry_keywords(self) -> dict[tuple[str, str | None], str]:
        """Load attribute inquiry keywords from the database.

        This data-driven mapping replaces hardcoded common_mappings in
        menu_options_inquiry_handler.py for queries like "what types of X do you have?".

        Maps (keyword, item_type_slug) -> attribute_slug
        e.g., ("types", "bagel") -> "bread"
        """
        from sqlalchemy import text

        result = self._db.execute(text("""
            SELECT aik.keyword, it.slug as item_type_slug, ga.slug as attribute_slug
            FROM attribute_inquiry_keywords aik
            LEFT JOIN item_types it ON aik.item_type_id = it.id
            JOIN global_attributes ga ON aik.global_attribute_id = ga.id
        """))

        keywords: dict[tuple[str, str | None], str] = {}
        for row in result:
            keyword = row[0].lower()
            item_type = row[1]  # Can be None
            attr_slug = row[2]
            keywords[(keyword, item_type)] = attr_slug

        logger.debug(
            "Loaded %d attribute inquiry keywords",
            len(keywords),
        )
        return keywords
