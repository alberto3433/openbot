"""
Base utilities for the menu data cache.

This module contains:
- Helper functions (singularize, etc.)
- BaseCacheMixin with cache attribute initialization
- MenuDataNotLoadedError handling
"""

import asyncio
import logging
import threading
from collections import defaultdict
from datetime import datetime
from typing import Any, Pattern

from ..exceptions import MenuDataNotLoadedError

logger = logging.getLogger(__name__)


def singularize(word: str) -> str:
    """Convert plural to singular form. Handles common English patterns.

    This is a simple helper for data-driven category/item matching.
    Does not handle irregular plurals - those should be defined as aliases in the database.

    Examples:
        >>> singularize("pastries")
        'pastry'
        >>> singularize("cookies")
        'cookie'
        >>> singularize("boxes")
        'box'
        >>> singularize("drinks")
        'drink'
        >>> singularize("glass")
        'glass'
        >>> singularize("tomatoes")
        'tomato'
        >>> singularize("potatoes")
        'potato'
    """
    word = word.lower().strip()
    if not word:
        return word

    # Don't singularize words ending in 'ss' (glass, boss, etc.)
    if word.endswith("ss"):
        return word
    # -ies handling: distinguish between two patterns
    # 1. Words ending in "-ie" that pluralize by adding "-s" (cookie/cookies, brownie/brownies)
    # 2. Words ending in consonant + y that change to "-ies" (pastry/pastries, city/cities)
    if word.endswith("ies") and len(word) > 3:
        # Common "-ie" word suffixes (these just add -s for plural)
        ie_suffixes = ("ookies", "ovies", "ownies", "uppies", "ippies", "ommies",
                       "addies", "onnies", "innies", "unnies", "annies")
        if any(word.endswith(suffix) for suffix in ie_suffixes):
            return word[:-1]  # cookies -> cookie (just remove 's')
        # Short words ending in common -ie patterns
        if len(word) <= 5 and word.endswith(("pies", "ties", "lies", "dies")):
            return word[:-1]  # pies -> pie, ties -> tie
        # Otherwise use standard -ies -> -y (pastries -> pastry, cities -> city)
        return word[:-3] + "y"
    # -oes -> -o (tomatoes -> tomato, potatoes -> potato, heroes -> hero)
    if word.endswith("oes"):
        return word[:-2]
    # -es after s, sh, ch, x, z -> remove -es (boxes -> box, dishes -> dish)
    if word.endswith("es") and len(word) > 2:
        if word[-3] in "shxz" or word[-4:-2] == "ch":
            return word[:-2]
    # -s -> remove s (drinks -> drink, bagels -> bagel)
    if word.endswith("s"):
        return word[:-1]
    return word


class BaseCacheMixin:
    """Mixin class that initializes all cache attributes.

    This provides the foundation for the MenuDataCache, defining all the
    dictionary and set attributes used by the various query mixins.
    """

    def _init_all_caches(self) -> None:
        """Initialize all cache data structures.

        Called once during __init__ to set up empty caches.
        """
        # Core data sets
        self._known_menu_items: set[str] = set()

        # Alias-to-canonical name mappings (for resolving user input to menu item names)
        self._signature_item_aliases: dict[str, str] = {}  # alias -> menu item name
        self._signature_item_types: dict[str, str] = {}  # menu item name -> item_type_slug
        self._modifier_aliases: dict[str, str] = {}  # alias -> Ingredient.name (canonical)
        self._side_items: set[str] = set()  # All side item names/aliases (lowercase)
        self._side_alias_to_canonical: dict[str, str] = {}  # alias -> MenuItem.name (canonical)
        self._menu_item_alias_to_canonical: dict[str, str] = {}  # alias -> MenuItem.name (canonical)
        self._menu_item_name_to_id: dict[str, int] = {}  # canonical name (lowercase) -> MenuItem.id

        # Abbreviations for text expansion before parsing (e.g., "cc" -> "cream cheese")
        # Unlike aliases (used for matching), abbreviations replace text in the input
        self._abbreviations: dict[str, str] = {}  # abbreviation -> canonical name (lowercase)

        # Category keyword mappings (replaces MENU_CATEGORY_KEYWORDS constant)
        # Maps user keywords (bagels, sandwiches, etc.) to category info
        self._category_keywords: dict[str, dict] = {}  # keyword -> {slug, lookup_type, display_name, ...}

        # Item type field configurations
        self._item_type_fields: dict[str, list[dict]] = {}  # item_type_slug -> list of field configs

        # Response patterns for recognizing user intent
        self._response_patterns: dict[str, set[str]] = {}  # pattern_type -> set of exact patterns
        self._response_regex_raw: dict[str, list[str]] = {}  # pattern_type -> list of raw regex strings
        self._response_regex_compiled: dict[str, Pattern | None] = {}  # pattern_type -> compiled combined regex

        # Modifier qualifiers (extra, light, on the side, etc.)
        self._modifier_qualifiers: dict[str, dict] = {}  # pattern -> {normalized_form, category}
        self._qualifier_patterns_by_category: dict[str, set[str]] = {}  # category -> set of patterns

        # Global attribute options cache (for shots, size, temperature, etc.)
        self._global_attribute_options: dict[str, list[dict]] = {}  # attr_slug -> list of options

        # Modifier category to attribute slugs index (data-driven lookup)
        # Maps modifier_category slug -> set of attribute slugs that contain options with that category
        self._modifier_category_to_attrs: dict[str, set[str]] = {}

        # Global attribute aliases (e.g., "cream cheese" -> "spread")
        self._global_attribute_aliases: dict[str, str] = {}  # alias -> attr_slug

        # Global attribute property names (mapping DB slug to Python property name)
        self._global_attribute_property_names: dict[str, str] = {}  # attr_slug -> property_name

        # Global attribute metadata cache (display_name, input_type for each global attribute)
        self._global_attribute_metadata: dict[str, dict] = {}  # attr_slug -> {display_name, input_type}

        # Item type attributes cache (lazy-loaded per item type)
        # This is the single source of truth for attribute configs
        self._item_type_attributes: dict[str, dict] = {}  # item_type_slug -> {attr_slug -> attr_config}

        # Field-to-slug mapping: maps code field names to DB attribute slugs
        # For attributes that load from ingredients, multiple field names (ingredient categories)
        # can map to one attribute slug
        # Lazily populated alongside _item_type_attributes
        self._field_to_slug_map: dict[str, dict[str, str]] = {}  # item_type_slug -> {field_name -> attr_slug}

        # Item type modifier categories ("food" or "beverage") - replaces MODIFIER_EXTRACTION_TYPE
        self._item_type_modifier_categories: dict[str, str | None] = {}  # item_type_slug -> modifier_category

        # Item keywords for disambiguation (menu item names + item type slugs)
        # Used to detect "this input contains a new item" vs "this is a modifier"
        self._item_keywords: set[str] = set()

        # Configurable item types (those with attributes defined)
        self._configurable_item_types: set[str] = set()

        # Item type side choice configuration
        # Maps item_type_slug -> {"has_side_choice": bool, "side_choice_attribute_id": int|None}
        self._item_type_side_choice: dict[str, dict] = {}

        # Keyword indices for partial matching
        self._menu_item_keyword_index: dict[str, list[str]] = {}

        # Cached menu index (expensive to build, loaded once at startup)
        self._menu_index: dict[str, Any] = {}

        # Data-driven parsing support
        # Compound phrases - phrases containing " and " that shouldn't be split during parsing
        # (e.g., "bacon egg and cheese", "ham and swiss")
        self._compound_phrases: set[str] = set()

        # Item type triggers - keywords that trigger detection of each item type
        # Derived from menu item names (e.g., "latte" triggers "sized_beverage")
        self._item_type_triggers: dict[str, set[str]] = {}  # item_type_slug -> set of trigger keywords

        # Configurable item type slugs - item types that have ask_in_conversation=True attributes
        # These require inline parsing with attribute extraction (e.g., "bagel", "sized_beverage")
        self._configurable_item_type_slugs: set[str] = set()

        # Items with required match phrases - for exclusion logic during parsing
        # Maps item_name (lowercase) -> required_match_phrases string
        self._items_with_required_phrases: dict[str, str] = {}

        # Menu items by unit type - for filtering by how items are sold
        self._by_unit_type_items: dict[str, set[str]] = {}  # unit_type -> set of item names (lowercase)
        # Aliases by unit type - for finding items by name/alias within a unit type
        # Maps unit_type -> {alias_lowercase -> (canonical_name, item_type_slug)}
        self._unit_type_aliases: dict[str, dict[str, tuple[str, str]]] = {}

        # Generic caches for data-driven lookups (replaces domain-specific caches)
        # Item names by ItemType slug (includes aliases)
        self._item_names_by_type: dict[str, set[str]] = {}  # item_type_slug -> set of names/aliases
        # Combined item names for ALL configurable item types (cached for performance)
        self._configurable_item_names: set[str] | None = None
        # Alias-to-canonical mapping by ItemType slug
        self._item_alias_to_canonical_by_type: dict[str, dict[str, str]] = {}  # item_type_slug -> {alias -> canonical}
        # Ingredients by category (protein, cheese, topping, spread, etc.)
        self._ingredients_by_category: dict[str, set[str]] = {}  # category -> set of names/aliases
        # Ingredient details by category (for generic modifier handling)
        # category -> list of {slug, name, aliases: [pattern, ...]}
        self._ingredient_details_by_category: dict[str, list[dict]] = {}
        # Ingredients valid for each ItemType, grouped by category
        self._ingredients_for_item_type: dict[str, dict[str, set[str]]] = {}  # item_type_slug -> {category -> names}

        # Ingredient category metadata (for data-driven modifier type lookups)
        # Maps modifier_type ("food", "beverage") to set of category slugs
        self._ingredient_categories_by_modifier_type: dict[str, set[str]] = {}

        # Ingredient category field configuration (for data-driven modifier field definitions)
        # Maps category_slug -> {code_field_name, is_multi_select}
        # Replaces hardcoded INGREDIENT_GROUP_TO_FIELD mapping
        self._ingredient_category_field_config: dict[str, dict] = {}

        # Ingredient category display order (for ordered extraction in parsing)
        # Maps category_slug -> display_order (int)
        self._ingredient_category_order: dict[str, int] = {}

        # Name-forming categories (e.g., "bread" - ingredient name replaces menu item name)
        # Set of category slugs where ingredient display name should replace base item name
        self._name_forming_categories: set[str] = set()

        # Menu item categories (high-level classifications like "drink", "food")
        # Maps category slug -> list of menu item dicts (id, name, item_type_slug)
        self._menu_items_by_category_slug: dict[str, list[dict]] = {}
        # Available category slugs with display names
        self._available_categories: dict[str, str] = {}  # slug -> display_name

        # Modifier categories for menu inquiries (toppings, proteins, milks, etc.)
        # Maps slug -> {display_name, loads_from_ingredients, ingredient_category, description}
        self._modifier_categories: dict[str, dict] = {}

        # Price inquiry support (data-driven)
        # Pre-computed resolved prices for items with attribute-based pricing
        # Maps item_name (lowercase) -> resolved_price (base + attribute upcharge)
        self._resolved_item_prices: dict[str, float] = {}

        # Item types with priced attributes (e.g., bagel with bread type upcharges)
        # Maps item_type_slug -> first priced attribute slug (or None)
        self._item_type_priced_attribute: dict[str, str | None] = {}

        # Ingredient contexts for price inquiries
        # Maps ingredient_name (lowercase) -> list of context dicts
        # Each context: {context_type, item_type_slug, label, price}
        self._ingredient_price_contexts: dict[str, list[dict]] = {}

        # Recommendation search support (includes ALL menu items, not filtered)
        # Maps canonical_name (lowercase) -> {id, name, item_type_slug}
        self._all_menu_items_by_name: dict[str, dict] = {}
        # Keyword index for partial matching: keyword -> list of canonical names (lowercase)
        self._recommendation_keyword_index: dict[str, list[str]] = {}

        # Menu items cache (for get_items_by_item_type)
        self._menu_items: dict[str, dict] = {}

        # Metadata
        self._last_refresh: datetime | None = None
        self._is_loaded: bool = False
        self._refresh_lock = threading.Lock()

        # Background refresh settings
        self._refresh_hour: int = 3  # 3 AM local time
        self._refresh_task: asyncio.Task | None = None

    def _ensure_loaded(self) -> None:
        """Ensure cache is loaded, raise exception if not."""
        if not self._is_loaded:
            raise MenuDataNotLoadedError(
                "Menu cache not loaded. Ensure menu_cache.load_from_db() is called at startup. "
                "Check that the database connection is working and migrations have run."
            )

    def _build_keyword_indices(self) -> None:
        """Build keyword-to-item indices for partial matching."""
        # English stop words / union words (language-specific, not domain-specific)
        # These have special semantic meaning:
        # - "a", "an", "the" often signify count
        # - "and", "with" are union words joining items or modifiers
        # - "or", "on", "in" are prepositions
        skip_words = {"the", "a", "an", "with", "and", "or", "on", "in"}

        # Build menu item keyword index
        self._menu_item_keyword_index = self._build_index(self._known_menu_items, skip_words)

        logger.debug(
            "Built keyword indices: %d menu keywords",
            len(self._menu_item_keyword_index),
        )

    def _build_index(self, items: set[str], skip_words: set[str]) -> dict[str, list[str]]:
        """Build a keyword-to-items index for a set of items."""
        index: dict[str, list[str]] = defaultdict(list)

        for item in items:
            words = item.lower().split()
            for word in words:
                if word not in skip_words and len(word) > 2:
                    if item not in index[word]:
                        index[word].append(item)

        return dict(index)
