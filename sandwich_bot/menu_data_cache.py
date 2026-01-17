"""
Menu Data Cache - Dynamic Loading of Menu Constants from Database.

This module provides a centralized cache for menu-driven constants that were
previously hardcoded in constants.py. Data is loaded from the database at
server startup and can be refreshed on-demand or on a schedule.

Features:
- Lazy loading with singleton pattern
- Partial string matching for disambiguation
- Background refresh at configurable intervals (default: 3 AM daily)
- Admin endpoint for manual refresh
- Fail-fast behavior: raises MenuDataNotLoadedError if cache not loaded or data missing

Usage:
    from sandwich_bot.menu_data_cache import menu_cache

    # Get ingredients by category (returns set)
    milks = menu_cache.get_ingredients("milk")

    # Find partial matches for disambiguation
    matches = menu_cache.find_menu_item_matches("classic")
    # Returns: ["classic egg sandwich", "classic blt"]
"""

import asyncio
import logging
import threading
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session, joinedload

from .exceptions import MenuDataNotLoadedError

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
    """
    word = word.lower().strip()
    if not word:
        return word

    # Don't singularize words ending in 'ss' (glass, boss, etc.)
    if word.endswith("ss"):
        return word
    # -ies -> -y (pastries -> pastry, cookies -> cookie)
    if word.endswith("ies"):
        return word[:-3] + "y"
    # -es after s, sh, ch, x, z -> remove -es (boxes -> box, dishes -> dish)
    if word.endswith("es") and len(word) > 2:
        if word[-3] in "shxz" or word[-4:-2] == "ch":
            return word[:-2]
    # -s -> remove s (drinks -> drink, bagels -> bagel)
    if word.endswith("s"):
        return word[:-1]
    return word


class MenuDataCache:
    """
    Singleton cache for menu data loaded from the database.

    Replaces hardcoded constants with database-driven values.
    Raises MenuDataNotLoadedError if accessed before loading or if data is missing.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        # Core data sets
        self._known_menu_items: set[str] = set()

        # Alias-to-canonical name mappings (for resolving user input to menu item names)
        self._signature_item_aliases: dict[str, str] = {}  # alias -> menu item name
        self._modifier_aliases: dict[str, str] = {}  # alias -> Ingredient.name (canonical)
        self._side_items: set[str] = set()  # All side item names/aliases (lowercase)
        self._side_alias_to_canonical: dict[str, str] = {}  # alias -> MenuItem.name (canonical)
        self._menu_item_alias_to_canonical: dict[str, str] = {}  # alias -> MenuItem.name (canonical)

        # Abbreviations for text expansion before parsing (e.g., "cc" -> "cream cheese")
        # Unlike aliases (used for matching), abbreviations replace text in the input
        self._abbreviations: dict[str, str] = {}  # abbreviation -> canonical name (lowercase)

        # Category keyword mappings (replaces MENU_CATEGORY_KEYWORDS constant)
        # Maps user keywords (bagels, sandwiches, etc.) to category info
        self._category_keywords: dict[str, dict] = {}  # keyword -> {slug, lookup_type, display_name, ...}

        # By-the-pound items
        self._by_pound_items: dict[str, list[str]] = {}  # category -> list of item names
        self._by_pound_aliases: dict[str, tuple[str, str]] = {}  # alias -> (canonical_name, category)
        self._by_pound_category_names: dict[str, str] = {}  # slug -> display_name

        # Item type field configurations
        self._item_type_fields: dict[str, list[dict]] = {}  # item_type_slug -> list of field configs

        # Response patterns for recognizing user intent
        self._response_patterns: dict[str, set[str]] = {}  # pattern_type -> set of patterns

        # Modifier qualifiers (extra, light, on the side, etc.)
        self._modifier_qualifiers: dict[str, dict] = {}  # pattern -> {normalized_form, category}
        self._qualifier_patterns_by_category: dict[str, set[str]] = {}  # category -> set of patterns

        # Global attribute options cache (for shots, size, temperature, etc.)
        self._global_attribute_options: dict[str, list[dict]] = {}  # attr_slug -> list of options

        # Modifier category to attribute slugs index (data-driven lookup)
        # Maps modifier_category slug -> set of attribute slugs that contain options with that category
        # E.g., "milk" -> {"milk_sweetener_syrup"}, "syrup" -> {"milk_sweetener_syrup"}
        self._modifier_category_to_attrs: dict[str, set[str]] = {}

        # Global attribute aliases (e.g., "cream cheese" -> "spread_type")
        self._global_attribute_aliases: dict[str, str] = {}  # alias -> attr_slug

        # Global attribute property names (mapping DB slug to Python property name)
        # E.g., "milk_sweetener_syrup" -> "milk" (when property_name differs from slug)
        self._global_attribute_property_names: dict[str, str] = {}  # attr_slug -> property_name

        # Item type attributes cache (lazy-loaded per item type)
        # This is the single source of truth for attribute configs
        self._item_type_attributes: dict[str, dict] = {}  # item_type_slug -> {attr_slug -> attr_config}

        # Field-to-slug mapping: maps code field names to DB attribute slugs
        # For attributes that load from ingredients, multiple field names (ingredient categories)
        # can map to one attribute slug (e.g., "milk" -> "milk_sweetener_syrup")
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

        # Menu items by unit type - for filtering by how items are sold
        self._by_unit_type_items: dict[str, set[str]] = {}  # unit_type -> set of item names (lowercase)

        # Generic caches for data-driven lookups (replaces domain-specific caches)
        # Item names by ItemType slug (includes aliases)
        self._item_names_by_type: dict[str, set[str]] = {}  # item_type_slug -> set of names/aliases
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

        # Menu item categories (high-level classifications like "drink", "food")
        # Maps category slug -> list of menu item dicts (id, name, item_type_slug)
        self._menu_items_by_category_slug: dict[str, list[dict]] = {}
        # Available category slugs with display names
        self._available_categories: dict[str, str] = {}  # slug -> display_name

        # Modifier categories for menu inquiries (toppings, proteins, milks, etc.)
        # Maps slug -> {display_name, loads_from_ingredients, ingredient_category, description}
        self._modifier_categories: dict[str, dict] = {}

        # Metadata
        self._last_refresh: datetime | None = None
        self._is_loaded: bool = False
        self._refresh_lock = threading.Lock()

        # Background refresh settings
        self._refresh_hour: int = 3  # 3 AM local time
        self._refresh_task: asyncio.Task | None = None

        self._initialized = True

    @property
    def is_loaded(self) -> bool:
        """Check if cache has been loaded from database."""
        return self._is_loaded

    @property
    def last_refresh(self) -> datetime | None:
        """Get timestamp of last cache refresh."""
        return self._last_refresh

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

                # Load each category
                self._load_known_menu_items(db)
                self._load_signature_item_aliases(db)
                self._load_by_pound_items(db)
                self._load_by_pound_category_names(db)
                self._load_modifier_aliases(db)
                self._load_side_items(db)
                self._load_category_keywords(db)
                self._load_abbreviations(db)
                self._load_item_type_fields(db)
                self._load_response_patterns(db)
                self._load_modifier_qualifiers(db)
                self._load_global_attribute_options(db)
                self._load_global_attribute_aliases(db)
                self._load_item_type_metadata(db)
                self._load_menu_index(db)

                # Data-driven parsing support loaders
                self._load_compound_phrases(db)
                self._load_item_type_triggers(db)
                self._load_by_unit_type_items(db)

                # Generic data-driven loaders (replace domain-specific functions)
                self._load_generic_item_names(db)
                self._load_generic_ingredients(db)
                self._load_generic_ingredients_for_item_types(db)
                self._load_ingredient_category_metadata(db)

                # Load menu item categories (drink, food, etc.)
                self._load_menu_item_categories(db)

                # Load modifier categories (toppings, proteins, milks, etc.)
                self._load_modifier_categories(db)

                # Build keyword indices for partial matching
                self._build_keyword_indices()

                self._last_refresh = datetime.now()
                self._is_loaded = True

                logger.info(
                    "Menu data cache loaded: %d menu_items, %d signature_item_aliases, "
                    "%d by_pound_categories, %d abbreviations, "
                    "%d item_types, %d ingredient_categories",
                    len(self._known_menu_items),
                    len(self._signature_item_aliases),
                    len(self._by_pound_items),
                    len(self._abbreviations),
                    len(self._item_names_by_type),
                    len(self._ingredients_by_category),
                )

            except Exception as e:
                logger.error("Failed to load menu data cache: %s", e)
                if fail_on_error:
                    raise RuntimeError(f"Failed to load menu data cache: {e}") from e
                # Keep existing cache if available

    def _load_known_menu_items(self, db: Session) -> None:
        """Load all menu item names and aliases for recognition.

        This method builds:
        1. A set of known menu item strings for pattern matching
        2. A mapping from aliases to canonical menu item names

        Known items include:
        - Full menu item names (lowercased)
        - Names without "The " prefix (for matching "blt" to "The BLT")
        - All aliases from the aliases column (comma-separated)

        EXCLUDES certain item types that have their own configuration flows:
        - 'bagel': goes through bagel config (toasted, spread, etc.)
        - 'sized_beverage': goes through coffee config (size, iced, milk, etc.)

        These items are recognized by their respective parsers, not as direct
        menu item matches.

        This replaces:
        - The hardcoded KNOWN_MENU_ITEMS constant in constants.py
        - The hardcoded NO_THE_PREFIX_ITEMS constant in constants.py
        - The hardcoded MENU_ITEM_CANONICAL_NAMES constant in constants.py
        """
        from .models import MenuItem, ItemType

        menu_items = set()
        alias_to_canonical: dict[str, str] = {}

        # Get item_type ids to exclude items that have config flows
        exclude_slugs = ['bagel', 'sized_beverage']
        exclude_type_ids = set()
        for slug in exclude_slugs:
            item_type = db.query(ItemType).filter(ItemType.slug == slug).first()
            if item_type:
                exclude_type_ids.add(item_type.id)

        # Use joinedload to avoid N+1 queries when accessing aliases
        all_items = (
            db.query(MenuItem)
            .options(joinedload(MenuItem.alias_records))
            .all()
        )
        for item in all_items:
            # Skip items that have their own configuration flows
            if item.item_type_id in exclude_type_ids:
                continue

            canonical_name = item.name  # Preserve original casing
            name_lower = item.name.lower()

            # Add the full name
            menu_items.add(name_lower)
            alias_to_canonical[name_lower] = canonical_name

            # Also add without "The " prefix for matching
            if name_lower.startswith("the "):
                without_the = name_lower[4:]
                menu_items.add(without_the)
                alias_to_canonical[without_the] = canonical_name

            # Add all aliases if present (now a list from child table)
            for alias in item.aliases:
                alias = alias.strip().lower()
                if alias:
                    menu_items.add(alias)
                    alias_to_canonical[alias] = canonical_name

        self._known_menu_items = menu_items
        self._menu_item_alias_to_canonical = alias_to_canonical

        logger.debug(
            "Loaded %d known menu items with %d alias mappings",
            len(menu_items),
            len(alias_to_canonical),
        )

    def _load_signature_item_aliases(self, db: Session) -> None:
        """Load signature item aliases from database.

        Builds a mapping from user input variations (aliases) to the actual
        menu item names in the database.

        The mapping is used for recognizing orders like "bec", "bacon egg and cheese",
        "the classic", "the leo", etc. and resolving them to actual menu items.
        """
        from .models import MenuItem

        signature_item_aliases: dict[str, str] = {}

        # Query signature items (aliases are loaded via relationship)
        # Only signature items should be in this mapping
        # (non-signature items like "Coffee" have their own parsing flow)
        # Use joinedload to avoid N+1 queries when accessing aliases
        signature_items = (
            db.query(MenuItem)
            .options(joinedload(MenuItem.alias_records))
            .filter(MenuItem.is_signature == True)  # noqa: E712
            .all()
        )

        for item in signature_items:
            canonical_name = item.name  # Keep original casing

            # Add aliases from child table (now a list)
            for alias in item.aliases:
                alias = alias.strip().lower()
                if alias:
                    signature_item_aliases[alias] = canonical_name

            # Also add variations of the item name itself
            name_lower = item.name.lower()
            signature_item_aliases[name_lower] = canonical_name

            # Add without "The " prefix if present
            if name_lower.startswith("the "):
                signature_item_aliases[name_lower[4:]] = canonical_name

        self._signature_item_aliases = signature_item_aliases

        logger.debug(
            "Loaded %d signature item aliases from %d items",
            len(signature_item_aliases),
            len(signature_items),
        )

    def _load_by_pound_items(self, db: Session) -> None:
        """Load by-the-pound items organized by category.

        Builds two data structures:
        1. _by_pound_items: dict mapping category (fish, spread, etc.) to list of item names
        2. _by_pound_aliases: dict mapping aliases to (canonical_name, category) tuples

        Categories are determined by ItemType slugs (cheese, cold_cut, fish, salad, spread).
        """
        import re
        from .models import MenuItem, ItemType

        by_pound_items: dict[str, list[str]] = {}
        by_pound_aliases: dict[str, tuple[str, str]] = {}

        # Query items where item_type.is_by_pound = True (data-driven)
        # Use joinedload to avoid N+1 queries when accessing aliases
        items = (
            db.query(MenuItem)
            .options(joinedload(MenuItem.alias_records), joinedload(MenuItem.item_type))
            .join(ItemType, MenuItem.item_type_id == ItemType.id)
            .filter(ItemType.is_by_pound == True)  # noqa: E712
            .order_by(ItemType.slug, MenuItem.name)
            .all()
        )

        # Group items by category and extract base names (without weight suffix)
        seen_base_names: dict[str, str] = {}  # Track which base names we've seen per category

        for item in items:
            # Get category from item_type slug
            category = item.item_type.slug if item.item_type else None
            if not category:
                continue
            name = item.name

            # Extract base name without weight suffix: "Nova Scotia Salmon (1 lb)" -> "Nova Scotia Salmon"
            base_name = re.sub(r'\s*\([^)]*\)\s*$', '', name).strip()

            # Skip if we've already processed this base name for this category
            category_key = f"{category}:{base_name}"
            if category_key in seen_base_names:
                continue
            seen_base_names[category_key] = base_name

            # Add to category list
            if category not in by_pound_items:
                by_pound_items[category] = []
            by_pound_items[category].append(base_name)

            # Add base name as alias
            base_name_lower = base_name.lower()
            by_pound_aliases[base_name_lower] = (base_name, category)

            # Add aliases if present (now a list from child table)
            for alias in item.aliases:
                alias = alias.strip().lower()
                if alias:
                    by_pound_aliases[alias] = (base_name, category)

        self._by_pound_items = by_pound_items
        self._by_pound_aliases = by_pound_aliases

        logger.debug(
            "Loaded %d by-pound categories with %d total items and %d aliases",
            len(by_pound_items),
            sum(len(items) for items in by_pound_items.values()),
            len(by_pound_aliases),
        )

    def _load_by_pound_category_names(self, db: Session) -> None:
        """Load by-the-pound category display names from ItemType table.

        Loads the mapping from category slugs (cheese, cold_cut, fish, etc.)
        to human-readable display names (cheeses, cold cuts, smoked fish, etc.)
        using ItemType.display_name_plural.
        """
        from .models import ItemType

        category_names: dict[str, str] = {}

        try:
            # Query ItemTypes where is_by_pound = True (data-driven)
            item_types = (
                db.query(ItemType)
                .filter(ItemType.is_by_pound == True)  # noqa: E712
                .all()
            )

            for it in item_types:
                # Use display_name_plural if available, otherwise display_name
                display_name = it.display_name_plural or it.display_name or it.slug
                category_names[it.slug] = display_name

        except Exception as e:
            db.rollback()
            logger.warning(
                "Failed to load by-pound category names from ItemType: %s",
                e
            )

        self._by_pound_category_names = category_names

        logger.debug(
            "Loaded %d by-pound category names from ItemType",
            len(category_names),
        )

    def _load_modifier_aliases(self, db: Session) -> None:
        """Load modifier alias mappings from ingredient aliases.

        Builds a mapping from user input variations (aliases) to canonical
        Ingredient.name values. This replaces the hardcoded MODIFIER_NORMALIZATIONS
        constant in constants.py.

        The mapping is used for normalizing modifier input like "lox" -> "Nova Scotia Salmon",
        "veggie" -> "Vegetable Cream Cheese", etc.
        """
        from .models import Ingredient

        modifier_aliases: dict[str, str] = {}

        # Query all ingredients (aliases are loaded via relationship)
        # Use joinedload to avoid N+1 queries when accessing aliases
        all_ingredients = (
            db.query(Ingredient)
            .options(joinedload(Ingredient.alias_records))
            .all()
        )

        ingredients_with_aliases_count = 0
        for ing in all_ingredients:
            canonical_name = ing.name  # Preserve original casing

            # Add aliases from child table (now a list)
            if ing.aliases:
                ingredients_with_aliases_count += 1
                for alias in ing.aliases:
                    alias = alias.strip().lower()
                    if alias:
                        modifier_aliases[alias] = canonical_name

            # Also add the ingredient name itself (lowercase) as a key
            name_lower = ing.name.lower()
            modifier_aliases[name_lower] = canonical_name

        self._modifier_aliases = modifier_aliases

        logger.debug(
            "Loaded %d modifier aliases from %d ingredients",
            len(modifier_aliases),
            ingredients_with_aliases_count,
        )

    def _load_side_items(self, db: Session) -> None:
        """Load side items and their aliases from menu_items.

        Builds a mapping from user input variations (aliases) to canonical
        MenuItem.name values. This replaces the hardcoded SIDE_ITEM_MAP
        constant in constants.py.

        The mapping is used for resolving side item input like "sausage" ->
        "Side of Sausage", "latke" -> "Side of Breakfast Latke", etc.
        """
        from .models import MenuItem, Category, MenuItemCategory

        side_items: set[str] = set()
        alias_to_canonical: dict[str, str] = {}

        # Query side items (category slug = 'side') via many-to-many relationship
        # Use joinedload to avoid N+1 queries when accessing aliases
        items = (
            db.query(MenuItem)
            .options(joinedload(MenuItem.alias_records))
            .join(MenuItemCategory, MenuItemCategory.menu_item_id == MenuItem.id)
            .join(Category, Category.id == MenuItemCategory.category_id)
            .filter(Category.slug == "side")
            .all()
        )

        for item in items:
            canonical_name = item.name  # Preserve original casing
            name_lower = canonical_name.lower()

            # Add the item name (lowercase)
            side_items.add(name_lower)
            alias_to_canonical[name_lower] = canonical_name

            # Add all aliases if present (now a list from child table)
            for alias in item.aliases:
                alias = alias.strip().lower()
                if alias:
                    side_items.add(alias)
                    alias_to_canonical[alias] = canonical_name

        self._side_items = side_items
        self._side_alias_to_canonical = alias_to_canonical

        logger.debug(
            "Loaded %d side item aliases from %d items",
            len(alias_to_canonical),
            len(items),
        )

    def _load_category_keywords(self, db: Session) -> None:
        """Load category keyword mappings from item_types and categories tables.

        Builds a mapping from user keywords (bagels, sandwiches, drinks, etc.)
        to category info for menu queries.

        Two types of lookups are supported:
        1. ItemType lookups (lookup_type="item_type"): Query MenuItems by item_type_id
           Example: "bagel" -> items with item_type.slug = "bagel"
        2. Category lookups (lookup_type="category"): Query MenuItems via MenuItemCategory
           Example: "sandwich" -> items with category.slug = "sandwich"

        Raises:
            RuntimeError: If no category keywords found in database.
        """
        from .models import ItemType, Category

        category_keywords: dict[str, dict] = {}

        # 1. Load ItemTypes (for item type-based lookups like "bagel", "sized_beverage")
        item_types = (
            db.query(ItemType)
            .options(joinedload(ItemType.alias_records))
            .all()
        )

        item_types_count = 0
        for item_type in item_types:
            slug = item_type.slug
            display_name = item_type.display_name
            display_name_plural = item_type.display_name_plural or f"{display_name}s"

            category_info = {
                "slug": slug,
                "display_name": display_name,
                "display_name_plural": display_name_plural,
                "lookup_type": "item_type",  # Query by item_type_id
            }

            # Add slug itself as a key
            category_keywords[slug] = category_info
            item_types_count += 1

            # Add all aliases as keys
            for alias in item_type.aliases:
                alias = alias.strip().lower()
                if alias:
                    category_keywords[alias] = category_info

        # 2. Load Categories (for category-based lookups like "sandwich", "drink", "food")
        categories = db.query(Category).all()

        categories_count = 0
        for category in categories:
            slug = category.slug
            display_name = category.name
            # Simple pluralization for categories
            display_name_plural = f"{display_name}s" if not display_name.endswith('s') else display_name

            category_info = {
                "slug": slug,
                "category_id": category.id,
                "display_name": display_name,
                "display_name_plural": display_name_plural,
                "lookup_type": "category",  # Query via MenuItemCategory join
            }

            # Add slug as a key (may override item_type if same name - category takes precedence)
            category_keywords[slug] = category_info
            categories_count += 1

            # Also add singular/plural variations
            name_lower = display_name.lower()
            if name_lower != slug:
                category_keywords[name_lower] = category_info
            # Add plural form if different
            plural_lower = display_name_plural.lower()
            if plural_lower != slug and plural_lower != name_lower:
                category_keywords[plural_lower] = category_info

        # Fail if database has no category keywords configured
        if not category_keywords:
            raise RuntimeError(
                "No category keywords found in database. Run migrations to populate "
                "item_types and categories tables."
            )

        self._category_keywords = category_keywords

        logger.debug(
            "Loaded %d category keywords from %d item_types and %d categories",
            len(category_keywords),
            item_types_count,
            categories_count,
        )

    def _load_item_type_metadata(self, db: Session) -> None:
        """Load item type metadata: modifier_category, item_keywords, and configurable types.

        This replaces:
        - MODIFIER_EXTRACTION_TYPE hardcoded dict in menu_item_config_handler.py
        - SUPPORTED_ITEM_TYPES hardcoded set in menu_item_config_handler.py
        - non_modifier_keywords hardcoded sets in taking_items_handler.py

        Loads:
        - modifier_category: "food" or "beverage" from item_type_categories.slug (via FK)
        - item_keywords: all menu item names (lowercase) + item type slugs for disambiguation
        - configurable_item_types: item types that have attributes defined
        """
        from .models import ItemType, MenuItem, ItemTypeAttribute, ItemTypeGlobalAttribute

        modifier_categories: dict[str, str | None] = {}
        item_keywords: set[str] = set()
        configurable_types: set[str] = set()
        side_choice_config: dict[str, dict] = {}

        # Load all item types with their category
        # Use joinedload to avoid N+1 queries when accessing aliases and category
        item_types = (
            db.query(ItemType)
            .options(
                joinedload(ItemType.alias_records),
                joinedload(ItemType.item_type_category),
                joinedload(ItemType.side_choice_attribute),
            )
            .all()
        )
        for item_type in item_types:
            slug = item_type.slug
            # Get category from FK relationship
            if item_type.item_type_category:
                modifier_categories[slug] = item_type.item_type_category.slug
            else:
                modifier_categories[slug] = None

            # Load side choice configuration
            side_choice_config[slug] = {
                "has_side_choice": item_type.has_side_choice,
                "side_choice_attribute_id": item_type.side_choice_attribute_id,
                "side_choice_attribute": None,
            }
            # Include attribute details if has_side_choice is True
            if item_type.has_side_choice and item_type.side_choice_attribute:
                attr = item_type.side_choice_attribute
                side_choice_config[slug]["side_choice_attribute"] = {
                    "slug": attr.slug,
                    "question_text": attr.question_text,
                    "display_name": attr.display_name,
                }

            # Add item type slug as a keyword
            item_keywords.add(slug.lower())

            # Add item type aliases as keywords
            for alias in item_type.aliases:
                item_keywords.add(alias.lower())

        # Check which item types have attributes (either item_type_attributes or global_attributes)
        types_with_attrs = set()

        # Item types with ItemTypeAttribute entries
        attr_types = (
            db.query(ItemTypeAttribute.item_type_id)
            .distinct()
            .all()
        )
        types_with_attrs.update(t[0] for t in attr_types)

        # Item types with ItemTypeGlobalAttribute links
        global_attr_types = (
            db.query(ItemTypeGlobalAttribute.item_type_id)
            .distinct()
            .all()
        )
        types_with_attrs.update(t[0] for t in global_attr_types)

        # Map item type IDs to slugs for configurable types
        for item_type in item_types:
            if item_type.id in types_with_attrs:
                configurable_types.add(item_type.slug)

        # Load all menu item names as keywords
        menu_items = db.query(MenuItem.name).all()
        for (name,) in menu_items:
            # Add the full name
            item_keywords.add(name.lower())
            # Also add individual words from multi-word names (e.g., "cold brew" -> "cold", "brew")
            words = name.lower().split()
            for word in words:
                if len(word) > 2:  # Skip very short words
                    item_keywords.add(word)

        self._item_type_modifier_categories = modifier_categories
        self._item_keywords = item_keywords
        self._configurable_item_types = configurable_types
        self._item_type_side_choice = side_choice_config

        logger.debug(
            "Loaded item type metadata: %d modifier_categories, %d item_keywords, %d configurable_types, %d side_choice_configs",
            len(modifier_categories),
            len(item_keywords),
            len(configurable_types),
            len(side_choice_config),
        )

    def _load_abbreviations(self, db: Session) -> None:
        """Load abbreviations from ingredients and menu_items tables.

        Abbreviations are short forms that get expanded before parsing.
        Unlike aliases (used for matching), abbreviations perform text
        replacement on the input string.

        Example: "cc" -> "cream cheese", so "strawberry cc" becomes
        "strawberry cream cheese" before parsing.

        Loads from both:
        - ingredients.abbreviation column
        - menu_items.abbreviation column
        """
        import re
        from .models import Ingredient, MenuItem

        abbreviations: dict[str, str] = {}

        # Load abbreviations from ingredients
        ingredients = (
            db.query(Ingredient)
            .filter(Ingredient.abbreviation.isnot(None))
            .filter(Ingredient.abbreviation != "")
            .all()
        )

        for ingredient in ingredients:
            abbrev = ingredient.abbreviation.strip().lower()
            canonical = ingredient.name.lower()
            if abbrev and canonical:
                abbreviations[abbrev] = canonical

        # Load abbreviations from menu_items
        menu_items = (
            db.query(MenuItem)
            .filter(MenuItem.abbreviation.isnot(None))
            .filter(MenuItem.abbreviation != "")
            .all()
        )

        for item in menu_items:
            abbrev = item.abbreviation.strip().lower()
            canonical = item.name.lower()
            if abbrev and canonical:
                abbreviations[abbrev] = canonical

        self._abbreviations = abbreviations

        logger.debug(
            "Loaded %d abbreviations from %d ingredients and %d menu items",
            len(abbreviations),
            len(ingredients),
            len(menu_items),
        )

    def _load_item_type_fields(self, db: Session) -> None:
        """Load item type attribute configurations from the database.

        Loads attribute definitions (required, ask_in_conversation, question_text)
        from the item_type_attributes table. This is the consolidated table that
        replaces the old item_type_field table.

        Attributes are organized by item_type_slug for easy lookup.
        """
        from .models import ItemType, ItemTypeAttribute

        item_type_fields: dict[str, list[dict]] = {}

        # Query all attributes with their item type from the NEW table
        # Explicit join condition needed due to multiple FKs between tables
        attributes = (
            db.query(ItemTypeAttribute)
            .join(ItemType, ItemTypeAttribute.item_type_id == ItemType.id)
            .order_by(ItemType.slug, ItemTypeAttribute.display_order)
            .all()
        )

        for attr in attributes:
            slug = attr.item_type.slug
            if slug not in item_type_fields:
                item_type_fields[slug] = []

            item_type_fields[slug].append({
                "field_name": attr.slug,  # Use 'slug' as field_name for compatibility
                "display_order": attr.display_order,
                "required": attr.is_required,
                "ask": attr.ask_in_conversation,
                "question_text": attr.question_text,
                "input_type": attr.input_type,
                "display_name": attr.display_name,
            })

        self._item_type_fields = item_type_fields

        logger.debug(
            "Loaded item type attributes for %d item types (%d total attributes)",
            len(item_type_fields),
            sum(len(fields) for fields in item_type_fields.values()),
        )

    def _load_response_patterns(self, db: Session) -> None:
        """Load response patterns from the database.

        Loads patterns for recognizing user response types:
        - affirmative: yes, yeah, yep, sure, ok, etc.
        - negative: no, nope, nah, no thanks, etc.
        - cancel: cancel, never mind, forget it, etc.
        - done: that's all, that's it, nothing else, etc.

        Patterns are organized by type for efficient lookup.
        """
        from .models import ResponsePattern

        response_patterns: dict[str, set[str]] = {}

        # Query all response patterns
        patterns = db.query(ResponsePattern).all()

        for pattern in patterns:
            pattern_type = pattern.pattern_type
            if pattern_type not in response_patterns:
                response_patterns[pattern_type] = set()
            response_patterns[pattern_type].add(pattern.pattern.lower())

        self._response_patterns = response_patterns

        total_patterns = sum(len(p) for p in response_patterns.values())
        logger.debug(
            "Loaded %d response patterns across %d types: %s",
            total_patterns,
            len(response_patterns),
            ", ".join(f"{k}({len(v)})" for k, v in response_patterns.items()),
        )

    def _load_modifier_qualifiers(self, db: Session) -> None:
        """Load modifier qualifier patterns from the database.

        Loads patterns for recognizing modifier qualifiers:
        - amount: extra, light, double, lots of, etc.
        - position: on the side, on top
        - preparation: crispy, well done, etc.

        Qualifiers are organized by pattern and by category for efficient lookup.
        """
        from .models import ModifierQualifier

        modifier_qualifiers: dict[str, dict] = {}
        qualifier_patterns_by_category: dict[str, set[str]] = {}

        # Query all active modifier qualifiers
        # Handle case where table doesn't exist yet (migration not run)
        try:
            qualifiers = (
                db.query(ModifierQualifier)
                .filter(ModifierQualifier.is_active == True)  # noqa: E712
                .order_by(ModifierQualifier.category, ModifierQualifier.pattern)
                .all()
            )
        except Exception as e:
            logger.warning("Could not load modifier qualifiers (table may not exist): %s", e)
            self._modifier_qualifiers = {}
            self._qualifier_patterns_by_category = {}
            return

        for qualifier in qualifiers:
            pattern = qualifier.pattern.lower()
            category = qualifier.category

            # Store pattern -> info mapping
            modifier_qualifiers[pattern] = {
                "normalized_form": qualifier.normalized_form,
                "category": category,
            }

            # Store by category for conflict detection
            if category not in qualifier_patterns_by_category:
                qualifier_patterns_by_category[category] = set()
            qualifier_patterns_by_category[category].add(pattern)

        self._modifier_qualifiers = modifier_qualifiers
        self._qualifier_patterns_by_category = qualifier_patterns_by_category

        logger.debug(
            "Loaded %d modifier qualifiers across %d categories: %s",
            len(modifier_qualifiers),
            len(qualifier_patterns_by_category),
            ", ".join(f"{k}({len(v)})" for k, v in qualifier_patterns_by_category.items()),
        )

    def _load_global_attribute_options(self, db: Session) -> None:
        """Load global attribute options from the database.

        Loads options for global attributes like shots, size, temperature, etc.
        These are used for data-driven pricing and display.

        When an option has an ingredient_id, must_match and aliases are loaded
        from the linked Ingredient record (single source of truth).
        """
        from .models import GlobalAttribute, GlobalAttributeOption, Ingredient

        global_attribute_options: dict[str, list[dict]] = {}

        try:
            # Query all global attributes with their options
            attributes = db.query(GlobalAttribute).all()

            for attr in attributes:
                # Eagerly load the ingredient relationship for options that have one
                # Also load ingredient's alias_records and must_match_records to avoid N+1
                options = (
                    db.query(GlobalAttributeOption)
                    .options(
                        joinedload(GlobalAttributeOption.ingredient)
                        .joinedload(Ingredient.alias_records),
                        joinedload(GlobalAttributeOption.ingredient)
                        .joinedload(Ingredient.must_match_records),
                        joinedload(GlobalAttributeOption.modifier_category),
                    )
                    .filter(GlobalAttributeOption.global_attribute_id == attr.id)
                    .order_by(GlobalAttributeOption.display_order)
                    .all()
                )

                global_attribute_options[attr.slug] = [
                    self._build_global_option_dict(opt)
                    for opt in options
                ]

            self._global_attribute_options = global_attribute_options

            # Build property_name mapping for attributes where it differs from slug
            property_names: dict[str, str] = {}
            for attr in attributes:
                if attr.property_name:
                    property_names[attr.slug] = attr.property_name
            self._global_attribute_property_names = property_names

            # Build modifier_category -> attribute_slugs index
            modifier_category_to_attrs: dict[str, set[str]] = {}
            for attr_slug, options in global_attribute_options.items():
                for opt in options:
                    mod_cat = opt.get("modifier_category")
                    if mod_cat:
                        if mod_cat not in modifier_category_to_attrs:
                            modifier_category_to_attrs[mod_cat] = set()
                        modifier_category_to_attrs[mod_cat].add(attr_slug)
            self._modifier_category_to_attrs = modifier_category_to_attrs

            logger.debug(
                "Loaded global attribute options for %d attributes, %d modifier categories",
                len(global_attribute_options),
                len(modifier_category_to_attrs),
            )
        except Exception as e:
            logger.warning("Could not load global attribute options: %s", e)
            self._global_attribute_options = {}
            self._global_attribute_property_names = {}
            self._modifier_category_to_attrs = {}

    def _build_global_option_dict(self, opt) -> dict:
        """Build option dict, reading aliases/must_match ONLY from linked Ingredient.

        Options that need aliases or must_match MUST be linked to an Ingredient.
        If not linked, aliases and must_match will be None (fail gracefully).
        """
        # Aliases and must_match come ONLY from the linked Ingredient
        # No fallback to deprecated option columns
        if opt.ingredient:
            aliases = opt.ingredient.aliases
            must_match = opt.ingredient.must_match
        else:
            # Option not linked to ingredient - no aliases/must_match available
            # This is expected for options that don't need special parsing
            aliases = None
            must_match = None

        # Get modifier category slug if linked
        modifier_category_slug = None
        if opt.modifier_category:
            modifier_category_slug = opt.modifier_category.slug

        return {
            "slug": opt.slug,
            "display_name": opt.display_name,
            "price_modifier": opt.price_modifier,
            "iced_price_modifier": opt.iced_price_modifier,
            "is_default": opt.is_default,
            "is_available": opt.is_available,
            "aliases": aliases,
            "must_match": must_match,
            "modifier_category": modifier_category_slug,
        }

    def _load_global_attribute_aliases(self, db: Session) -> None:
        """Load global attribute aliases from the database.

        Maps alternative names for global attributes to their canonical slugs.
        For example, "cream cheese" -> "spread_type".

        This enables users to refer to attributes by common alternative names
        without hardcoding these mappings in the codebase.
        """
        from .models import GlobalAttribute, GlobalAttributeAlias

        global_attribute_aliases: dict[str, str] = {}

        try:
            # Query all aliases with their associated global attributes
            aliases = (
                db.query(GlobalAttributeAlias)
                .join(GlobalAttribute)
                .all()
            )

            for alias_record in aliases:
                # Map the alias (lowercase for case-insensitive lookup) to the attribute slug
                alias_lower = alias_record.alias.lower()
                attr_slug = alias_record.global_attribute.slug
                global_attribute_aliases[alias_lower] = attr_slug

            self._global_attribute_aliases = global_attribute_aliases

            logger.debug(
                "Loaded %d global attribute aliases",
                len(global_attribute_aliases),
            )
        except Exception as e:
            logger.warning("Could not load global attribute aliases: %s", e)
            self._global_attribute_aliases = {}

    def _load_menu_index(self, db: Session) -> None:
        """Load and cache the menu index.

        The menu index is expensive to build (many DB queries) so we cache it
        at startup and refresh it along with the rest of the cache.

        This is called once at server startup and on manual refresh.
        """
        from .menu_index_builder import build_menu_index

        logger.info("Building menu index (this may take a moment)...")
        import time
        start = time.time()
        self._menu_index = build_menu_index(db)
        elapsed = time.time() - start
        logger.info(
            "Menu index built in %.1f seconds with %d total items",
            elapsed,
            sum(len(v) for k, v in self._menu_index.items() if isinstance(v, list)),
        )

    def _load_compound_phrases(self, db: Session) -> None:
        """Load compound phrases that shouldn't be split during multi-item parsing.

        These are phrases containing " and " that represent single items or concepts,
        like "bacon egg and cheese", "ham and swiss", "salt and pepper".

        Source: Menu item names and aliases containing " and ".
        """
        from .models import MenuItem, MenuItemAlias, Ingredient, IngredientAlias

        compound_phrases: set[str] = set()

        # Get all menu item names containing " and "
        menu_items_with_and = (
            db.query(MenuItem.name)
            .filter(MenuItem.name.ilike("% and %"))
            .all()
        )
        for (name,) in menu_items_with_and:
            compound_phrases.add(name.lower())

        # Get all menu item aliases containing " and "
        menu_aliases_with_and = (
            db.query(MenuItemAlias.alias)
            .filter(MenuItemAlias.alias.ilike("% and %"))
            .all()
        )
        for (alias,) in menu_aliases_with_and:
            compound_phrases.add(alias.lower())

        # Get all ingredient names containing " and "
        ingredients_with_and = (
            db.query(Ingredient.name)
            .filter(Ingredient.name.ilike("% and %"))
            .all()
        )
        for (name,) in ingredients_with_and:
            compound_phrases.add(name.lower())

        # Get all ingredient aliases containing " and "
        ingredient_aliases_with_and = (
            db.query(IngredientAlias.alias)
            .filter(IngredientAlias.alias.ilike("% and %"))
            .all()
        )
        for (alias,) in ingredient_aliases_with_and:
            compound_phrases.add(alias.lower())

        self._compound_phrases = compound_phrases
        logger.debug("Loaded %d compound phrases", len(compound_phrases))

    def _load_item_type_triggers(self, db: Session) -> None:
        """Load item type trigger keywords from menu item names.

        Builds a mapping from item_type_slug -> set of keywords that trigger
        detection of that item type. Keywords are derived from menu item names.

        Example: "latte", "cappuccino", "espresso" -> "sized_beverage"
        """
        from .models import MenuItem, ItemType, MenuItemAlias

        item_type_triggers: dict[str, set[str]] = {}

        # Get all item types with their menu items
        item_types = db.query(ItemType).all()

        for item_type in item_types:
            triggers: set[str] = set()

            # Add the item type slug itself as a trigger
            triggers.add(item_type.slug.lower())

            # Add item type display name variations
            if item_type.display_name:
                triggers.add(item_type.display_name.lower())
                # Add singular form if plural
                if item_type.display_name.lower().endswith("s"):
                    triggers.add(item_type.display_name.lower()[:-1])

            # Get all menu items of this type
            menu_items = (
                db.query(MenuItem)
                .options(joinedload(MenuItem.alias_records))
                .filter(MenuItem.item_type_id == item_type.id)
                .all()
            )

            for item in menu_items:
                # Add full name (lowercase)
                name_lower = item.name.lower()
                triggers.add(name_lower)

                # Add name without common suffixes
                for suffix in [" sandwich", " bagel", " omelette", " salad"]:
                    if name_lower.endswith(suffix):
                        triggers.add(name_lower[:-len(suffix)])

                # Add first word if multi-word (e.g., "Iced Coffee" -> "iced")
                words = name_lower.split()
                if len(words) > 1:
                    triggers.add(words[0])

                # Add aliases
                for alias in item.aliases:
                    alias_lower = alias.strip().lower()
                    if alias_lower:
                        triggers.add(alias_lower)

            if triggers:
                item_type_triggers[item_type.slug] = triggers

        self._item_type_triggers = item_type_triggers
        logger.debug(
            "Loaded item type triggers: %s",
            {k: len(v) for k, v in item_type_triggers.items()}
        )

    def _load_by_unit_type_items(self, db: Session) -> None:
        """Load menu items grouped by unit_type.

        Groups items by how they are sold:
        - 'each': sold individually (bagels, sandwiches, drinks)
        - 'by_weight': sold by weight (cream cheese by the lb, smoked fish)
        - 'dozen': sold by the dozen (bagel packages)
        """
        from .models import MenuItem

        by_unit_type: dict[str, set[str]] = {}

        # Query all menu items with their unit_type
        all_items = db.query(MenuItem.name, MenuItem.unit_type).all()

        for name, unit_type in all_items:
            if unit_type not in by_unit_type:
                by_unit_type[unit_type] = set()
            by_unit_type[unit_type].add(name.lower())

        self._by_unit_type_items = by_unit_type
        logger.debug(
            "Loaded items by unit_type: %s",
            {k: len(v) for k, v in by_unit_type.items()}
        )

    def _load_generic_item_names(self, db: Session) -> None:
        """Load all item names grouped by ItemType slug.

        This is the generic replacement for domain-specific loaders like
        _load_coffee_types, _load_soda_types, _load_bagel_types.

        For each ItemType, loads:
        - MenuItem names (lowercase)
        - MenuItem aliases (lowercase)
        - Alias-to-canonical name mapping
        """
        from .models import MenuItem, ItemType

        item_names_by_type: dict[str, set[str]] = {}
        alias_to_canonical_by_type: dict[str, dict[str, str]] = {}

        # Query all menu items with their item types
        items = (
            db.query(MenuItem)
            .options(joinedload(MenuItem.alias_records), joinedload(MenuItem.item_type))
            .all()
        )

        for item in items:
            if not item.item_type:
                continue

            item_type_slug = item.item_type.slug
            canonical_name = item.name

            # Initialize dicts for this item type if needed
            if item_type_slug not in item_names_by_type:
                item_names_by_type[item_type_slug] = set()
                alias_to_canonical_by_type[item_type_slug] = {}

            # Add canonical name (lowercase for matching)
            name_lower = canonical_name.lower()
            item_names_by_type[item_type_slug].add(name_lower)
            alias_to_canonical_by_type[item_type_slug][name_lower] = canonical_name

            # Add aliases
            for alias in item.aliases:
                alias_lower = alias.strip().lower()
                if alias_lower:
                    item_names_by_type[item_type_slug].add(alias_lower)
                    alias_to_canonical_by_type[item_type_slug][alias_lower] = canonical_name

        self._item_names_by_type = item_names_by_type
        self._item_alias_to_canonical_by_type = alias_to_canonical_by_type

        logger.debug(
            "Loaded generic item names for %d item types: %s",
            len(item_names_by_type),
            {k: len(v) for k, v in item_names_by_type.items()}
        )

    def _load_generic_ingredients(self, db: Session) -> None:
        """Load all ingredients grouped by category.

        This is the generic replacement for domain-specific loaders like
        _load_proteins, _load_cheeses, _load_toppings.

        For each category, loads:
        - Ingredient names (lowercase)
        - Ingredient aliases (lowercase)
        - Full ingredient details (slug, name, aliases) for generic modifier handling
        """
        from .models import Ingredient

        ingredients_by_category: dict[str, set[str]] = {}
        ingredient_details_by_category: dict[str, list[dict]] = {}

        # Query all ingredients with their aliases
        ingredients = (
            db.query(Ingredient)
            .options(joinedload(Ingredient.alias_records))
            .all()
        )

        for ing in ingredients:
            category = ing.category
            if not category:
                continue

            # Initialize structures for this category if needed
            if category not in ingredients_by_category:
                ingredients_by_category[category] = set()
                ingredient_details_by_category[category] = []

            # Add ingredient name (lowercase for matching)
            name_lower = ing.name.lower()
            ingredients_by_category[category].add(name_lower)

            # Build list of all matching patterns (name + aliases, lowercase)
            patterns = [name_lower]
            for alias in ing.aliases:
                alias_lower = alias.strip().lower()
                if alias_lower:
                    ingredients_by_category[category].add(alias_lower)
                    patterns.append(alias_lower)

            # Store full ingredient details for generic modifier handling
            ingredient_details_by_category[category].append({
                "slug": ing.slug,
                "name": ing.name,  # Original display name
                "patterns": patterns,  # All lowercase patterns for matching
            })

        self._ingredients_by_category = ingredients_by_category
        self._ingredient_details_by_category = ingredient_details_by_category

        logger.debug(
            "Loaded generic ingredients for %d categories: %s",
            len(ingredients_by_category),
            {k: len(v) for k, v in ingredients_by_category.items()}
        )

    def _load_generic_ingredients_for_item_types(self, db: Session) -> None:
        """Load ingredients valid for each ItemType, grouped by category.

        Uses the ItemTypeIngredient junction table to determine which
        ingredients are valid for each item type.

        This is the generic replacement for domain-specific functions like
        get_bagel_spreads that filter ingredients by item type.
        """
        from .models import ItemTypeIngredient, ItemType, Ingredient

        ingredients_for_item_type: dict[str, dict[str, set[str]]] = {}

        # Query all item type ingredients with related data
        type_ingredients = (
            db.query(ItemTypeIngredient)
            .options(
                joinedload(ItemTypeIngredient.item_type),
                joinedload(ItemTypeIngredient.ingredient).joinedload(Ingredient.alias_records)
            )
            .all()
        )

        for ti in type_ingredients:
            if not ti.item_type or not ti.ingredient:
                continue

            item_type_slug = ti.item_type.slug
            category = ti.ingredient.category or "uncategorized"

            # Initialize nested dicts if needed
            if item_type_slug not in ingredients_for_item_type:
                ingredients_for_item_type[item_type_slug] = {}
            if category not in ingredients_for_item_type[item_type_slug]:
                ingredients_for_item_type[item_type_slug][category] = set()

            # Add ingredient name (lowercase for matching)
            ingredients_for_item_type[item_type_slug][category].add(ti.ingredient.name.lower())

            # Add aliases
            for alias in ti.ingredient.aliases:
                alias_lower = alias.strip().lower()
                if alias_lower:
                    ingredients_for_item_type[item_type_slug][category].add(alias_lower)

        self._ingredients_for_item_type = ingredients_for_item_type

        logger.debug(
            "Loaded ingredients for %d item types",
            len(ingredients_for_item_type)
        )

    def _load_ingredient_category_metadata(self, db: Session) -> None:
        """Load ingredient category metadata for data-driven modifier type lookups.

        This allows querying which ingredient categories belong to which modifier type
        (food vs beverage) without hardcoding category names.

        Also loads code_field_name and is_multi_select for data-driven modifier field
        configuration, replacing the hardcoded INGREDIENT_GROUP_TO_FIELD mapping.

        Example:
            get_ingredient_categories_by_modifier_type("food")
            -> {"protein", "topping", "cheese", "spread"}

            get_ingredient_category_field_config("topping")
            -> {"code_field_name": "toppings", "is_multi_select": True}
        """
        from .models import IngredientCategory

        categories_by_modifier_type: dict[str, set[str]] = {}
        category_field_config: dict[str, dict] = {}
        category_order: dict[str, int] = {}

        # Query all ingredient categories
        categories = db.query(IngredientCategory).all()

        for cat in categories:
            # Load modifier type grouping
            if cat.modifier_type:
                if cat.modifier_type not in categories_by_modifier_type:
                    categories_by_modifier_type[cat.modifier_type] = set()
                categories_by_modifier_type[cat.modifier_type].add(cat.slug)

            # Load field configuration (code_field_name, is_multi_select)
            # If code_field_name is NULL, default to the category slug
            # If is_multi_select is NULL, default to False
            category_field_config[cat.slug] = {
                "code_field_name": cat.code_field_name or cat.slug,
                "is_multi_select": cat.is_multi_select or False,
            }

            # Load display order for extraction ordering
            category_order[cat.slug] = cat.display_order or 999

        self._ingredient_categories_by_modifier_type = categories_by_modifier_type
        self._ingredient_category_field_config = category_field_config
        self._ingredient_category_order = category_order

        logger.debug(
            "Loaded ingredient category metadata: %s modifier types, %s field configs, %s orders",
            {k: len(v) for k, v in categories_by_modifier_type.items()},
            len(category_field_config),
            len(category_order)
        )

    def _load_menu_item_categories(self, db: Session) -> None:
        """Load menu item categories (drink, food, etc.) for category-based searches.

        When a user says "I want a drink", we need to look up all items in the "drink"
        category to present disambiguation options.

        Loads:
        - _available_categories: slug -> display_name mapping
        - _menu_items_by_category_slug: slug -> list of item dicts
        """
        from .models import Category, MenuItemCategory, MenuItem, ItemType, MenuItemSizePrice

        available_categories: dict[str, str] = {}
        menu_items_by_category: dict[str, list[dict]] = {}

        # Load all categories
        categories = db.query(Category).all()
        for cat in categories:
            available_categories[cat.slug] = cat.name
            menu_items_by_category[cat.slug] = []

        # Load menu items by category
        # Subquery to get minimum price from size_prices for each menu_item
        from sqlalchemy import func
        price_subq = (
            db.query(
                MenuItemSizePrice.menu_item_id,
                func.min(MenuItemSizePrice.price).label("min_price")
            )
            .group_by(MenuItemSizePrice.menu_item_id)
            .subquery()
        )

        category_assignments = (
            db.query(MenuItemCategory)
            .join(MenuItem, MenuItemCategory.menu_item_id == MenuItem.id)
            .join(Category, MenuItemCategory.category_id == Category.id)
            .outerjoin(price_subq, MenuItem.id == price_subq.c.menu_item_id)
            .add_columns(
                MenuItem.id.label("menu_item_id"),
                MenuItem.name.label("menu_item_name"),
                func.coalesce(price_subq.c.min_price, 0.0).label("base_price"),
                MenuItem.item_type_id.label("item_type_id"),
                Category.slug.label("category_slug"),
            )
            .all()
        )

        # Also get item_type slugs for quick lookup
        item_type_slugs = {it.id: it.slug for it in db.query(ItemType).all()}

        for assignment in category_assignments:
            item_type_slug = item_type_slugs.get(assignment.item_type_id)
            item_dict = {
                "id": assignment.menu_item_id,
                "name": assignment.menu_item_name,
                "base_price": assignment.base_price,
                "item_type": item_type_slug,  # Use 'item_type' key to match expectations
            }
            if assignment.category_slug in menu_items_by_category:
                menu_items_by_category[assignment.category_slug].append(item_dict)

        self._available_categories = available_categories
        self._menu_items_by_category_slug = menu_items_by_category

        logger.debug(
            "Loaded menu item categories: %d categories, items by category: %s",
            len(available_categories),
            {k: len(v) for k, v in menu_items_by_category.items()}
        )

    def _load_modifier_categories(self, db: Session) -> None:
        """Load modifier categories for menu inquiries (toppings, proteins, milks, etc.).

        This provides data-driven configuration for handling "what X do you have?" questions.
        Each category specifies whether it loads from ingredients or has a static description.

        Loads:
        - _modifier_categories: slug -> {display_name, loads_from_ingredients, ingredient_category, description}
        """
        from .models import ModifierCategory

        modifier_categories: dict[str, dict] = {}

        categories = db.query(ModifierCategory).all()
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
            "Loaded modifier categories: %d categories (%s)",
            len(modifier_categories),
            list(modifier_categories.keys())
        )

    def _build_keyword_indices(self) -> None:
        """Build keyword-to-item indices for partial matching."""
        # Words to skip in keyword indexing
        skip_words = {
            "cream", "cheese", "bagel", "sandwich", "the", "a", "an",
            "with", "and", "or", "on", "in",
        }

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

    # =========================================================================
    # Getter Methods
    # =========================================================================

    def _ensure_loaded(self) -> None:
        """Ensure cache is loaded, raise exception if not."""
        if not self._is_loaded:
            raise MenuDataNotLoadedError(
                "Menu cache not loaded. Ensure menu_cache.load_from_db() is called at startup. "
                "Check that the database connection is working and migrations have run."
            )

    # -------------------------------------------------------------------------
    # Generic Data-Driven Getters
    # These replace domain-specific functions with generic, data-driven lookups
    # -------------------------------------------------------------------------

    def get_item_names(self, item_type_slug: str) -> set[str]:
        """Get all MenuItem names and aliases for a given ItemType.

        This is the generic replacement for domain-specific functions like
        get_coffee_types(), get_soda_types().

        Args:
            item_type_slug: The ItemType slug (e.g., "sized_beverage", "bagel", "beverage")

        Returns:
            Set of lowercase item names and aliases for matching user input.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded or item type not found.

        Examples:
            >>> menu_cache.get_item_names("sized_beverage")
            {"latte", "cappuccino", "coffee", "matcha", ...}
            >>> menu_cache.get_item_names("bagel")
            {"plain", "everything", "sesame", ...}
        """
        self._ensure_loaded()
        if item_type_slug not in self._item_names_by_type:
            # Return empty set for unknown item types (not an error)
            return set()
        return self._item_names_by_type[item_type_slug].copy()

    def get_items_by_category(self, category_slug: str) -> list[dict]:
        """Get all menu items in a given high-level category (drink, food, etc.).

        This enables generic searches like "I want a drink" to return all items
        categorized as drinks for disambiguation.

        Args:
            category_slug: The category slug (e.g., "drink", "food")

        Returns:
            List of dicts with menu item info: [{"id": int, "name": str, "item_type_slug": str}]

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.

        Examples:
            >>> menu_cache.get_items_by_category("drink")
            [{"id": 1, "name": "Coca-Cola", "item_type_slug": "beverage"},
             {"id": 2, "name": "Coffee", "item_type_slug": "sized_beverage"}, ...]
        """
        self._ensure_loaded()
        return self._menu_items_by_category_slug.get(category_slug, []).copy()

    def is_category_slug(self, keyword: str) -> bool:
        """Check if a keyword is a valid high-level category slug.

        Args:
            keyword: The keyword to check (e.g., "drink", "food")

        Returns:
            True if keyword is a valid category slug.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.

        Examples:
            >>> menu_cache.is_category_slug("drink")
            True
            >>> menu_cache.is_category_slug("coffee")
            False
        """
        self._ensure_loaded()
        return keyword.lower() in self._available_categories

    def get_available_menu_categories(self) -> dict[str, str]:
        """Get all available high-level menu categories.

        Returns:
            Dict mapping category slug to display name.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.

        Examples:
            >>> menu_cache.get_available_menu_categories()
            {"drink": "Drink", "food": "Food"}
        """
        self._ensure_loaded()
        return self._available_categories.copy()

    def resolve_item_alias(
        self, alias: str, item_type_slug: str | None = None
    ) -> str | None:
        """Resolve an item alias to its canonical MenuItem name.

        This is the generic replacement for domain-specific functions like
        resolve_coffee_alias(), resolve_soda_alias().

        Args:
            alias: The alias to resolve (e.g., "coke", "matcha", "drip")
            item_type_slug: Optional ItemType slug to restrict search.
                           If None, searches all item types.

        Returns:
            Canonical MenuItem name (with original casing), or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.

        Examples:
            >>> menu_cache.resolve_item_alias("coke", "beverage")
            "Coca-Cola"
            >>> menu_cache.resolve_item_alias("matcha", "sized_beverage")
            "Seasonal Latte Matcha"
            >>> menu_cache.resolve_item_alias("unknown")
            None
        """
        self._ensure_loaded()
        alias_lower = alias.lower().strip()

        if item_type_slug:
            # Search only in specified item type
            type_aliases = self._item_alias_to_canonical_by_type.get(item_type_slug, {})
            return type_aliases.get(alias_lower)
        else:
            # Search across all item types
            for type_aliases in self._item_alias_to_canonical_by_type.values():
                if alias_lower in type_aliases:
                    return type_aliases[alias_lower]
            return None

    def get_ingredients(self, category: str) -> set[str]:
        """Get all ingredient names and aliases for a given category.

        This is the generic replacement for domain-specific functions like
        get_proteins(), get_cheeses(), get_toppings().

        Args:
            category: The ingredient category (e.g., "protein", "cheese", "topping", "spread")

        Returns:
            Set of lowercase ingredient names and aliases for matching user input.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.

        Examples:
            >>> menu_cache.get_ingredients("protein")
            {"bacon", "ham", "turkey", "egg", ...}
            >>> menu_cache.get_ingredients("cheese")
            {"american", "swiss", "provolone", "cheddar", ...}
        """
        self._ensure_loaded()
        if category not in self._ingredients_by_category:
            # Return empty set for unknown categories (not an error)
            return set()
        return self._ingredients_by_category[category].copy()

    def get_ingredient_details(self, category: str) -> list[dict]:
        """Get full ingredient details for a category (slug, name, patterns).

        This is the generic method for data-driven modifier handling.
        Returns ingredient details including database slugs for storage
        and display names for UI, replacing domain-specific functions like
        _get_milk_options_espresso(), _get_sweetener_options(), etc.

        Args:
            category: The ingredient category (e.g., "milk", "sweetener", "syrup")

        Returns:
            List of ingredient detail dicts, each containing:
            - slug: Database identifier (e.g., "oat_milk")
            - name: Display name (e.g., "Oat Milk")
            - patterns: List of lowercase patterns for matching (name + aliases)

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.

        Examples:
            >>> menu_cache.get_ingredient_details("milk")
            [
                {"slug": "oat_milk", "name": "Oat Milk", "patterns": ["oat milk", "oat"]},
                {"slug": "whole_milk", "name": "Whole Milk", "patterns": ["whole milk", "whole"]},
                ...
            ]
            >>> menu_cache.get_ingredient_details("sweetener")
            [
                {"slug": "sugar", "name": "Sugar", "patterns": ["sugar"]},
                {"slug": "splenda", "name": "Splenda", "patterns": ["splenda"]},
                ...
            ]
        """
        self._ensure_loaded()
        if category not in self._ingredient_details_by_category:
            # Return empty list for unknown categories (not an error)
            return []
        # Return a deep copy to prevent mutation
        return [detail.copy() for detail in self._ingredient_details_by_category[category]]

    def get_all_ingredients(self) -> dict[str, dict]:
        """Get all ingredients across all categories.

        Returns a flat dictionary mapping ingredient names (lowercase) to their details.

        Returns:
            Dict mapping ingredient name (lowercase) -> {"name": str, "category": str, "slug": str}

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.

        Examples:
            >>> all_ings = menu_cache.get_all_ingredients()
            >>> all_ings.get("bacon")
            {"name": "Bacon", "category": "protein", "slug": "bacon"}
        """
        self._ensure_loaded()
        result: dict[str, dict] = {}
        for category, details in self._ingredient_details_by_category.items():
            for detail in details:
                name_lower = detail.get("name", "").lower()
                if name_lower:
                    result[name_lower] = {
                        "name": detail.get("name", ""),
                        "category": category,
                        "slug": detail.get("slug", ""),
                    }
        return result

    def get_ingredients_for_item_type(
        self, item_type_slug: str, category: str | None = None
    ) -> set[str]:
        """Get ingredients valid for a specific ItemType, optionally filtered by category.

        This is the generic replacement for domain-specific functions like
        get_bagel_spreads() that filter ingredients by item type.

        Uses the ItemTypeIngredient junction table to determine which
        ingredients are valid for each item type.

        Args:
            item_type_slug: The ItemType slug (e.g., "bagel", "sandwich")
            category: Optional ingredient category to filter by (e.g., "spread", "protein")

        Returns:
            Set of lowercase ingredient names and aliases valid for the item type.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.

        Examples:
            >>> menu_cache.get_ingredients_for_item_type("bagel", "spread")
            {"cream cheese", "butter", "scallion cream cheese", ...}
            >>> menu_cache.get_ingredients_for_item_type("sandwich")
            {"bacon", "ham", "turkey", "lettuce", "tomato", ...}  # All ingredients
        """
        self._ensure_loaded()

        type_ingredients = self._ingredients_for_item_type.get(item_type_slug, {})
        if not type_ingredients:
            return set()

        if category:
            # Return only ingredients in the specified category
            return type_ingredients.get(category, set()).copy()
        else:
            # Return all ingredients for this item type
            all_ingredients: set[str] = set()
            for cat_ingredients in type_ingredients.values():
                all_ingredients.update(cat_ingredients)
            return all_ingredients

    def get_all_item_type_slugs(self) -> set[str]:
        """Get all known ItemType slugs.

        Returns:
            Set of all ItemType slugs that have menu items.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.

        Examples:
            >>> menu_cache.get_all_item_type_slugs()
            {"bagel", "sized_beverage", "beverage", "sandwich", ...}
        """
        self._ensure_loaded()
        return set(self._item_names_by_type.keys())

    def get_all_ingredient_categories(self) -> set[str]:
        """Get all known ingredient categories.

        Returns:
            Set of all ingredient category names.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.

        Examples:
            >>> menu_cache.get_all_ingredient_categories()
            {"protein", "cheese", "topping", "spread", ...}
        """
        self._ensure_loaded()
        return set(self._ingredients_by_category.keys())

    def get_ingredient_category(self, ingredient_name: str) -> str | None:
        """Get the category for an ingredient by name or alias.

        Performs a reverse lookup to find which category contains the ingredient.
        This is used for data-driven ingredient categorization instead of hardcoded
        lists like ("bacon", "ham", "sausage", ...).

        Args:
            ingredient_name: The ingredient name or alias to look up (case-insensitive)

        Returns:
            The category slug (e.g., "protein", "cheese", "topping") or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.

        Examples:
            >>> menu_cache.get_ingredient_category("bacon")
            "protein"
            >>> menu_cache.get_ingredient_category("swiss")
            "cheese"
            >>> menu_cache.get_ingredient_category("lettuce")
            "topping"
        """
        self._ensure_loaded()
        name_lower = ingredient_name.lower().strip()
        for category, ingredients in self._ingredients_by_category.items():
            if name_lower in ingredients:
                return category
        return None

    def find_all_categories_for_ingredient(self, ingredient_name: str) -> list[str]:
        """Find ALL ingredient categories that contain a given value.

        Unlike get_ingredient_category() which returns the first match,
        this returns all categories where the ingredient exists. Used for
        detecting ambiguous modifiers (e.g., "blueberry" could be bread or spread).

        Matching strategy (in order):
        1. Exact match: "oat milk" in {"oat milk", "whole milk", ...}
        2. Suffix-stripped match: "oat" from "oat milk" in {"oat", ...}
        3. Contains match: if any ingredient in category is contained in input
           (e.g., "oat" in "oat milk" -> matches milk category)

        Args:
            ingredient_name: The ingredient name or alias to look up (case-insensitive)

        Returns:
            List of category slugs containing this ingredient. Empty if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.

        Examples:
            >>> menu_cache.find_all_categories_for_ingredient("blueberry")
            ["bread", "spread"]  # Ambiguous - exists in both
            >>> menu_cache.find_all_categories_for_ingredient("bacon")
            ["protein"]  # Unambiguous
            >>> menu_cache.find_all_categories_for_ingredient("oat milk")
            ["milk"]  # Matches "oat" in milk category
        """
        self._ensure_loaded()
        name_lower = ingredient_name.lower().strip()
        matching_categories = []

        # Common suffixes that can be stripped for matching
        strippable_suffixes = [" milk", " cream cheese", " spread", " bagel"]

        for category, ingredients in self._ingredients_by_category.items():
            # 1. Exact match
            if name_lower in ingredients:
                matching_categories.append(category)
                continue

            # 2. Try stripping common suffixes
            for suffix in strippable_suffixes:
                if name_lower.endswith(suffix):
                    stripped = name_lower[:-len(suffix)].strip()
                    if stripped and stripped in ingredients:
                        matching_categories.append(category)
                        break
            else:
                # 3. Check if any ingredient in this category is contained in the input
                # This handles cases like "oat milk" matching "oat" in the milk category
                for ingredient in ingredients:
                    # Only match if ingredient is a significant word (3+ chars)
                    # and appears as a word boundary in the input
                    if len(ingredient) >= 3 and ingredient in name_lower:
                        # Verify it's at a word boundary (not partial match)
                        import re
                        if re.search(r'\b' + re.escape(ingredient) + r'\b', name_lower):
                            matching_categories.append(category)
                            break

        return matching_categories

    def get_category_attribute_slug(self, category_slug: str) -> str:
        """Get the attribute slug (code_field_name) for an ingredient category.

        Maps ingredient category to the Python attribute name used in MenuItemTask.
        Uses code_field_name from ingredient_categories table, defaulting to
        the category slug if not set.

        Args:
            category_slug: The ingredient category (e.g., "spread", "protein", "milk")

        Returns:
            The attribute slug (e.g., "spread_type", "extra_protein", "milk")

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.

        Examples:
            >>> menu_cache.get_category_attribute_slug("protein")
            "extra_protein"
            >>> menu_cache.get_category_attribute_slug("spread")
            "spread"  # Defaults to slug if no code_field_name set
        """
        self._ensure_loaded()
        config = self._ingredient_category_field_config.get(category_slug)
        if config:
            return config.get("code_field_name", category_slug)
        # Fallback to category slug if not in config
        return category_slug

    def get_ingredient_categories_by_modifier_type(self, modifier_type: str) -> set[str]:
        """Get all ingredient category slugs for a given modifier type.

        This is used to dynamically determine which ingredient categories
        should be used for food modifiers vs beverage modifiers without
        hardcoding category names.

        Args:
            modifier_type: The modifier type ("food" or "beverage")

        Returns:
            Set of ingredient category slugs for the given modifier type.
            Returns empty set if modifier_type is not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.

        Examples:
            >>> menu_cache.get_ingredient_categories_by_modifier_type("food")
            {"protein", "topping", "cheese", "spread"}

            >>> menu_cache.get_ingredient_categories_by_modifier_type("beverage")
            {"milk", "sweetener", "syrup"}
        """
        self._ensure_loaded()
        return self._ingredient_categories_by_modifier_type.get(modifier_type, set()).copy()

    def get_ordered_ingredient_categories(self, modifier_type: str) -> list[str]:
        """Get ingredient category slugs for a modifier type, ordered by display_order.

        This is used for data-driven parsing where extraction order matters
        (e.g., spreads should be extracted before proteins to avoid ambiguity).

        Args:
            modifier_type: The modifier type ("food" or "beverage")

        Returns:
            List of ingredient category slugs, sorted by display_order.
            Returns empty list if modifier_type is not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.

        Examples:
            >>> menu_cache.get_ordered_ingredient_categories("food")
            ["spread", "protein", "cheese", "topping"]  # ordered by display_order
        """
        self._ensure_loaded()
        categories = self._ingredient_categories_by_modifier_type.get(modifier_type, set())
        # Sort by display_order (stored in _ingredient_category_order)
        return sorted(categories, key=lambda c: self._ingredient_category_order.get(c, 999))

    def get_ingredient_category_field_config(self, category_slug: str) -> dict | None:
        """Get field configuration for an ingredient category.

        Returns the code_field_name and is_multi_select for the category,
        used for data-driven modifier field definitions.

        Args:
            category_slug: The ingredient category slug (e.g., "topping", "sweetener")

        Returns:
            Dict with:
            - code_field_name: Python property name (e.g., "toppings", "flavor_syrups")
            - is_multi_select: True if category supports multiple selections

            Returns None if category not found.

        Examples:
            >>> menu_cache.get_ingredient_category_field_config("topping")
            {"code_field_name": "toppings", "is_multi_select": True}

            >>> menu_cache.get_ingredient_category_field_config("milk")
            {"code_field_name": "milk", "is_multi_select": False}
        """
        self._ensure_loaded()
        return self._ingredient_category_field_config.get(category_slug)

    def get_modifier_categories_for_inquiry(self) -> dict[str, dict]:
        """Get all modifier categories for menu inquiry handling.

        Returns dict mapping slug -> {display_name, loads_from_ingredients, ingredient_category, description}.
        Used by menu_inquiry_handler to answer "what X do you have?" questions.
        """
        self._ensure_loaded()
        return self._modifier_categories.copy()

    def get_modifier_category_items(self, slug: str) -> set[str]:
        """Get items for a specific modifier category.

        This is the generic data-driven method for getting modifier items.
        All modifier categories are backed by ingredients in the database.

        Args:
            slug: The modifier category slug (e.g., "toppings", "proteins", "milks")

        Returns:
            Set of item names for the category. Returns empty set if category not found.
        """
        self._ensure_loaded()

        cat_info = self._modifier_categories.get(slug)
        if not cat_info:
            return set()

        # Handle ingredient-backed categories
        if cat_info.get("loads_from_ingredients"):
            ingredient_category = cat_info.get("ingredient_category")
            if ingredient_category:
                return self.get_ingredients(ingredient_category)

        # Unknown category type
        return set()

    def get_known_menu_items(self) -> set[str]:
        """Get all known menu item names."""
        self._ensure_loaded()
        if not self._known_menu_items:
            raise MenuDataNotLoadedError(
                "No menu items found in database. "
                "Check that menu_items table has been populated."
            )
        return self._known_menu_items.copy()

    def get_modifier_category(self, item_type_slug: str) -> str | None:
        """Get the modifier extraction category for an item type.

        Args:
            item_type_slug: The item type slug (e.g., "bagel", "sized_beverage")

        Returns:
            "food" for items with food-style modifiers (proteins, cheeses, toppings)
            "beverage" for items with beverage-style modifiers (milk, sweetener, syrup)
            None if the item type has no modifier category defined

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Example:
            >>> cache.get_modifier_category("bagel")
            "food"
            >>> cache.get_modifier_category("sized_beverage")
            "beverage"
        """
        self._ensure_loaded()
        # Note: returning None is valid - not all item types have modifier categories
        return self._item_type_modifier_categories.get(item_type_slug)

    def get_item_keywords(self) -> set[str]:
        """Get all item keywords for disambiguation.

        Returns a set of lowercase keywords that indicate a new item request
        (as opposed to a modifier for an existing item). This includes:
        - Item type slugs (bagel, coffee, sandwich, etc.)
        - Item type aliases (latte, cappuccino, etc.)
        - Menu item names (The Classic BEC, etc.)
        - Words from menu item names (classic, bec, etc.)

        This replaces the hardcoded non_modifier_keywords sets.

        Returns:
            Set of lowercase item keywords.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded or no keywords found

        Example:
            >>> keywords = cache.get_item_keywords()
            >>> "bagel" in keywords
            True
            >>> "latte" in keywords
            True
        """
        self._ensure_loaded()
        if not self._item_keywords:
            raise MenuDataNotLoadedError(
                "No item keywords found in database. "
                "Check that item_types and menu_items tables are populated."
            )
        return self._item_keywords.copy()

    def get_configurable_item_types(self) -> set[str]:
        """Get item type slugs that have attributes defined.

        Returns the set of item type slugs that have either:
        - ItemTypeAttribute entries
        - ItemTypeGlobalAttribute links

        This replaces the hardcoded SUPPORTED_ITEM_TYPES set.

        Returns:
            Set of item type slugs.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded or no configurable types found

        Example:
            >>> types = cache.get_configurable_item_types()
            >>> "bagel" in types
            True
            >>> "sized_beverage" in types
            True
        """
        self._ensure_loaded()
        if not self._configurable_item_types:
            raise MenuDataNotLoadedError(
                "No configurable item types found in database. "
                "Check that item_type_attributes or item_type_global_attributes tables are populated."
            )
        return self._configurable_item_types.copy()

    def item_type_has_side_choice(self, item_type_slug: str) -> bool:
        """Check if an item type has a side choice requirement.

        Args:
            item_type_slug: The item type slug (e.g., "omelette")

        Returns:
            True if the item type requires a side choice, False otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Example:
            >>> cache.item_type_has_side_choice("omelette")
            True
            >>> cache.item_type_has_side_choice("bagel")
            False
        """
        self._ensure_loaded()
        config = self._item_type_side_choice.get(item_type_slug)
        if config is None:
            return False
        return config.get("has_side_choice", False)

    def get_side_choice_attribute(self, item_type_slug: str) -> dict | None:
        """Get the side choice attribute configuration for an item type.

        Args:
            item_type_slug: The item type slug (e.g., "omelette")

        Returns:
            Dict with attribute details if has_side_choice is True, None otherwise.
            Dict structure: {"slug": str, "question_text": str, "display_name": str}

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Example:
            >>> cache.get_side_choice_attribute("omelette")
            {"slug": "side_choice", "question_text": "Would you like a bagel or fruit salad with it?", ...}
            >>> cache.get_side_choice_attribute("bagel")
            None
        """
        self._ensure_loaded()
        config = self._item_type_side_choice.get(item_type_slug)
        if config is None:
            return None
        if not config.get("has_side_choice", False):
            return None
        return config.get("side_choice_attribute")

    def get_global_attribute_options(self, attr_slug: str) -> list[dict]:
        """Get options for a global attribute by slug.

        Args:
            attr_slug: The attribute slug (e.g., "shots", "size", "temperature")

        Returns:
            List of option dicts with keys: slug, display_name, price_modifier,
            iced_price_modifier, is_default, is_available, aliases.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded or attribute has no options

        Example:
            >>> cache.get_global_attribute_options("shots")
            [
                {"slug": "single", "display_name": "Single", "price_modifier": 0.0, ...},
                {"slug": "double", "display_name": "Double", "price_modifier": 0.75, ...},
                ...
            ]
        """
        self._ensure_loaded()
        options = self._global_attribute_options.get(attr_slug, [])
        if not options:
            raise MenuDataNotLoadedError(
                f"No options found for global attribute '{attr_slug}'. "
                f"Check that global_attribute_options table has options for this attribute."
            )
        return options

    def get_global_attribute_slug_by_alias(self, alias: str) -> str | None:
        """Look up a global attribute slug by its alias.

        Args:
            alias: The alias to look up (e.g., "cream cheese")

        Returns:
            The attribute slug (e.g., "spread_type") if alias exists, None otherwise.

        Example:
            >>> cache.get_global_attribute_slug_by_alias("cream cheese")
            "spread_type"
            >>> cache.get_global_attribute_slug_by_alias("unknown")
            None
        """
        self._ensure_loaded()
        return self._global_attribute_aliases.get(alias.lower())

    def get_all_global_attribute_aliases(self) -> dict[str, str]:
        """Get all global attribute aliases.

        Returns:
            Dict mapping alias (lowercase) to attribute slug.

        Example:
            >>> cache.get_all_global_attribute_aliases()
            {"cream cheese": "spread_type", ...}
        """
        self._ensure_loaded()
        return self._global_attribute_aliases.copy()

    def get_property_name_for_attribute(self, attr_slug: str) -> str:
        """Get the Python property name for an attribute slug.

        Some attributes have a different property name than their database slug.
        For example, "milk_sweetener_syrup" -> "milk".

        This method does NOT require the cache to be loaded - it gracefully
        falls back to returning the slug itself if the cache isn't loaded.
        This is safe because property name mapping is a code-level concern,
        and the calling code should have fallback logic anyway.

        Args:
            attr_slug: The attribute slug (e.g., "milk_sweetener_syrup")

        Returns:
            The property name to use in Python code.
            Returns the slug itself if no custom property_name is defined
            or if the cache is not loaded.

        Example:
            >>> cache.get_property_name_for_attribute("milk_sweetener_syrup")
            "milk"
            >>> cache.get_property_name_for_attribute("size")
            "size"
        """
        # Don't require cache to be loaded - property name mapping is optional
        # and the caller should handle the fallback case
        if not self._is_loaded:
            return attr_slug
        return self._global_attribute_property_names.get(attr_slug, attr_slug)

    def get_attributes_for_modifier_category(self, modifier_category: str) -> set[str]:
        """Get attribute slugs that contain options with the given modifier category.

        This enables data-driven lookup of which attributes to search when
        looking for a specific type of modifier (e.g., milk, syrup, sweetener).

        Args:
            modifier_category: The modifier category slug (e.g., "milk", "syrup", "sweetener")

        Returns:
            Set of attribute slugs that contain options with this modifier category.
            Empty set if no attributes contain options for this category.

        Example:
            >>> cache.get_attributes_for_modifier_category("milk")
            {"milk_sweetener_syrup"}
            >>> cache.get_attributes_for_modifier_category("syrup")
            {"milk_sweetener_syrup"}
        """
        self._ensure_loaded()
        return self._modifier_category_to_attrs.get(modifier_category, set()).copy()

    def attribute_contains_modifier_category(self, attr_slug: str, modifier_category: str) -> bool:
        """Check if an attribute contains options with the given modifier category.

        Args:
            attr_slug: The attribute slug to check
            modifier_category: The modifier category to look for (e.g., "milk", "syrup")

        Returns:
            True if the attribute has options with this modifier category.

        Example:
            >>> cache.attribute_contains_modifier_category("milk_sweetener_syrup", "milk")
            True
            >>> cache.attribute_contains_modifier_category("size", "milk")
            False
        """
        self._ensure_loaded()
        attrs_with_category = self._modifier_category_to_attrs.get(modifier_category, set())
        return attr_slug in attrs_with_category

    def get_item_type_attributes(self, item_type_slug: str) -> dict:
        """Get attributes for an item type (lazy-loaded, single source of truth).

        This is the consolidated cache for item type attributes. All handlers
        should use this method instead of maintaining their own caches.

        Args:
            item_type_slug: The item type slug (e.g., "sized_beverage", "deli_sandwich")

        Returns:
            Dict with structure:
            {
                "attribute_slug": {
                    "slug": "attribute_slug",
                    "display_name": "Attribute Name",
                    "question_text": "What would you like?",
                    "ask_in_conversation": True,
                    "input_type": "single_select",
                    "display_order": 1,
                    "allow_none": False,
                    "options": [{"slug": "opt1", "display_name": "Option 1", "price": 0.0}, ...]
                },
                ...
            }
        """
        # Check cache first
        if item_type_slug in self._item_type_attributes:
            return self._item_type_attributes[item_type_slug]

        # Load from database
        result = self._load_item_type_attributes_from_db(item_type_slug)
        self._item_type_attributes[item_type_slug] = result
        return result

    def item_type_has_attribute(self, item_type_slug: str, attribute_slug: str) -> bool:
        """Check if an item type has a specific attribute.

        This is the preferred data-driven way to check item type capabilities
        instead of checking item type slugs directly (e.g., `if item_type == "sized_beverage"`).

        Args:
            item_type_slug: The item type slug (e.g., "sized_beverage", "bagel")
            attribute_slug: The attribute slug to check for (e.g., "temperature", "toasted")

        Returns:
            True if the item type has the attribute, False otherwise.

        Example:
            >>> # Instead of: if item.menu_item_type == "sized_beverage":
            >>> if menu_cache.item_type_has_attribute(item.menu_item_type, "temperature"):
            ...     # Handle temperature configuration
        """
        attrs = self.get_item_type_attributes(item_type_slug)
        return attribute_slug in attrs

    def _load_item_type_attributes_from_db(self, item_type_slug: str) -> dict:
        """Load item type attributes from database.

        Loads both item-type-specific attributes (from ItemTypeAttribute table)
        and linked global attributes (from ItemTypeGlobalAttribute table).
        """
        from .db import SessionLocal
        from .models import (
            ItemType, ItemTypeAttribute,
            ItemTypeIngredient, Ingredient,
            ItemTypeGlobalAttribute, GlobalAttribute,
        )

        db = SessionLocal()
        try:
            item_type = db.query(ItemType).filter(ItemType.slug == item_type_slug).first()
            if not item_type:
                logger.warning("Item type '%s' not found in database", item_type_slug)
                return {}

            result: dict = {}

            # Load item-type-specific attributes
            attrs = db.query(ItemTypeAttribute).filter(
                ItemTypeAttribute.item_type_id == item_type.id
            ).order_by(ItemTypeAttribute.display_order).all()

            for attr in attrs:
                opts_data = self._load_attribute_options_from_db(
                    db, attr, item_type.id
                )
                result[attr.slug] = {
                    "slug": attr.slug,
                    "display_name": attr.display_name,
                    "question_text": attr.question_text,
                    "ask_in_conversation": attr.ask_in_conversation,
                    "is_required": attr.is_required,
                    "default_value": attr.default_value,
                    "input_type": attr.input_type,
                    "display_order": attr.display_order,
                    "allow_none": getattr(attr, 'allow_none', False),
                    "options": opts_data,
                }

            # Load global attributes linked to this item type
            global_attr_links = (
                db.query(ItemTypeGlobalAttribute)
                .filter(ItemTypeGlobalAttribute.item_type_id == item_type.id)
                .order_by(ItemTypeGlobalAttribute.display_order)
                .all()
            )

            for link in global_attr_links:
                global_attr = db.query(GlobalAttribute).filter(
                    GlobalAttribute.id == link.global_attribute_id
                ).first()
                if not global_attr:
                    continue

                # Load options from our own cache (already loaded at startup)
                cached_opts = self._global_attribute_options.get(global_attr.slug, [])

                opts_data = []
                for opt in cached_opts:
                    if not opt.get("is_available", True):
                        continue
                    opt_data = {
                        "slug": opt["slug"],
                        "display_name": opt["display_name"],
                        "price": float(opt.get("price_modifier") or 0),
                        "is_default": opt.get("is_default", False),
                    }
                    if opt.get("aliases"):
                        opt_data["aliases"] = opt["aliases"]
                    if opt.get("must_match"):
                        opt_data["must_match"] = opt["must_match"]
                    opts_data.append(opt_data)

                # Use link's question_text if provided, else generate
                if link.question_text:
                    question_text = link.question_text
                elif global_attr.input_type == "boolean":
                    question_text = f"Would you like it {global_attr.display_name.lower()}?"
                else:
                    question_text = f"What {global_attr.display_name.lower()} would you like?"

                result[global_attr.slug] = {
                    "slug": global_attr.slug,
                    "display_name": global_attr.display_name,
                    "question_text": question_text,
                    "ask_in_conversation": link.ask_in_conversation,
                    "input_type": global_attr.input_type or "single_select",
                    "display_order": link.display_order,
                    "allow_none": link.allow_none,
                    "options": opts_data,
                    "is_global_attribute": True,
                }

            # Build field-to-slug mapping for this item type
            # For attributes that load from ingredients, use ingredient categories as field names
            field_map: dict[str, str] = {}
            for attr_slug, attr_config in result.items():
                options = attr_config.get("options", [])
                # Extract unique categories from options (if they have category field)
                categories = {opt.get("category") for opt in options if opt.get("category")}
                if categories:
                    # Multiple field names (categories) map to this attribute slug
                    for category in categories:
                        field_map[category] = attr_slug
                # Note: If no categories, field_name == attr_slug (no mapping needed)

            # Store the mapping
            self._field_to_slug_map[item_type_slug] = field_map

            logger.info(
                "Loaded %d attributes for %s: %s",
                len(result), item_type_slug, list(result.keys())
            )
            if field_map:
                logger.debug(
                    "Field-to-slug map for %s: %s",
                    item_type_slug, field_map
                )
            return result

        finally:
            db.close()

    def _load_attribute_options_from_db(self, db, attr, item_type_id: int) -> list[dict]:
        """Load options for an attribute from ingredients.

        Note: Options from the deprecated attribute_options table are no longer loaded.
        All options should come from either:
        1. ItemTypeIngredient (when loads_from_ingredients=True)
        2. GlobalAttributeOption (via item_type_global_attributes)
        """
        from .models import ItemTypeIngredient, Ingredient

        opts_data = []

        if attr.loads_from_ingredients and attr.ingredient_group:
            # Load from item_type_ingredients + ingredients
            # Use joinedload to avoid N+1 queries when accessing ingredient aliases/must_match
            ingredient_links = (
                db.query(ItemTypeIngredient)
                .options(
                    joinedload(ItemTypeIngredient.ingredient)
                    .joinedload(Ingredient.alias_records),
                    joinedload(ItemTypeIngredient.ingredient)
                    .joinedload(Ingredient.must_match_records),
                )
                .filter(
                    ItemTypeIngredient.item_type_id == item_type_id,
                    ItemTypeIngredient.ingredient_group == attr.ingredient_group,
                    ItemTypeIngredient.is_available == True,
                )
                .order_by(ItemTypeIngredient.display_order)
                .all()
            )

            for link in ingredient_links:
                ingredient = link.ingredient
                opt_data = {
                    "slug": ingredient.slug or ingredient.name.lower().replace(" ", "_"),
                    "display_name": link.display_name_override or ingredient.name,
                    "price": float(link.price_modifier or 0),
                    "is_default": getattr(link, 'is_default', False),
                    "category": ingredient.category,
                }
                if ingredient.aliases:
                    opt_data["aliases"] = ingredient.aliases
                if ingredient.must_match:
                    opt_data["must_match"] = ingredient.must_match
                opts_data.append(opt_data)
        else:
            # For attributes that don't load from ingredients (e.g., boolean types like toasted),
            # options should come from GlobalAttributeOption via item_type_global_attributes.
            # This code path returns empty - the caller should use global attributes instead.
            pass

        return opts_data

    def clear_item_type_attributes_cache(self) -> None:
        """Clear the item type attributes cache (for testing or after DB changes)."""
        self._item_type_attributes = {}
        self._field_to_slug_map = {}

    def get_field_to_slug_map(self, item_type_slug: str) -> dict[str, str]:
        """Get the field-to-slug mapping for an item type.

        For attributes that load from ingredients, code field names (ingredient categories)
        may differ from the DB attribute slug. This method returns a mapping that can be
        used to resolve code field names to DB attribute slugs.

        For example, for sized_beverage:
            {"milk": "milk_sweetener_syrup", "sweetener": "milk_sweetener_syrup", "syrup": "milk_sweetener_syrup"}

        Args:
            item_type_slug: The item type slug (e.g., "sized_beverage", "bagel")

        Returns:
            Dict mapping field_name -> attribute_slug for fields that differ.
            Empty dict if no mappings are needed (all field names = attribute slugs).
        """
        # Ensure attributes are loaded (which also populates field_to_slug_map)
        self.get_item_type_attributes(item_type_slug)
        return self._field_to_slug_map.get(item_type_slug, {})

    def resolve_field_to_slug(self, item_type_slug: str, field_name: str) -> str:
        """Resolve a code field name to its DB attribute slug.

        If no mapping exists, returns the field_name unchanged (field_name == slug).

        Args:
            item_type_slug: The item type slug
            field_name: The code field name (e.g., "milk", "sweetener")

        Returns:
            The DB attribute slug (e.g., "milk_sweetener_syrup" or the field_name itself)
        """
        field_map = self.get_field_to_slug_map(item_type_slug)
        return field_map.get(field_name, field_name)

    def get_field_config(self, item_type_slug: str, field_slug: str) -> dict | None:
        """Get field configuration for a specific attribute from database.

        This method replaces the hardcoded DEFAULT_BAGEL_FIELDS and DEFAULT_COFFEE_FIELDS
        in field_config.py with database-driven configuration.

        Args:
            item_type_slug: The item type (e.g., "bagel", "sized_beverage")
            field_slug: The field/attribute slug (e.g., "bread", "toasted", "size")

        Returns:
            Dict with field config, or None if not found:
            {
                "required": True/False,
                "ask_if_empty": True/False,
                "question": "Question text?",
                "default": <default value or None>,
            }
        """
        import json

        attrs = self.get_item_type_attributes(item_type_slug)
        if field_slug not in attrs:
            return None

        attr = attrs[field_slug]

        # Parse default_value from JSON string if present
        default = None
        if attr.get("default_value"):
            try:
                default = json.loads(attr["default_value"])
            except (json.JSONDecodeError, TypeError):
                default = attr["default_value"]

        return {
            "required": attr.get("is_required", False),
            "ask_if_empty": attr.get("ask_in_conversation", True),
            "question": attr.get("question_text"),
            "default": default,
        }

    def get_all_field_configs(self, item_type_slug: str) -> dict:
        """Get all field configurations for an item type from database.

        Args:
            item_type_slug: The item type (e.g., "bagel", "sized_beverage")

        Returns:
            Dict mapping field slugs to their configs:
            {
                "bread": {"required": True, "ask_if_empty": True, ...},
                "toasted": {"required": False, "ask_if_empty": True, ...},
                ...
            }
        """
        import json

        attrs = self.get_item_type_attributes(item_type_slug)
        result = {}

        for field_slug, attr in attrs.items():
            # Parse default_value from JSON string if present
            default = None
            if attr.get("default_value"):
                try:
                    default = json.loads(attr["default_value"])
                except (json.JSONDecodeError, TypeError):
                    default = attr["default_value"]

            result[field_slug] = {
                "required": attr.get("is_required", False),
                "ask_if_empty": attr.get("ask_in_conversation", True),
                "question": attr.get("question_text"),
                "default": default,
            }

        return result

    def get_modifier_fields_for_item_type(self, item_type_slug: str) -> list[dict]:
        """Get modifier field definitions for an item type from database.

        This method loads ingredients linked to an item type via ItemTypeIngredient,
        groups them by ingredient_group, and returns a list of modifier field configs.

        This replaces the hardcoded BAGEL_MODIFIER_FIELDS and COFFEE_MODIFIER_FIELDS
        in modifier_operations.py with database-driven configuration.

        Args:
            item_type_slug: The item type (e.g., "bagel", "sized_beverage")

        Returns:
            List of modifier field configs, each containing:
            {
                "field_name": "spread",  # The attribute name on the item
                "display_name": "spread",  # Human-readable name
                "aliases": ["cream cheese", "cc", "schmear", ...],  # All recognized terms
                "is_list": False,  # True for toppings, sweeteners, syrups
                "ingredient_group": "spread",  # Database ingredient_group
            }
        """
        from .db import SessionLocal
        from .models import ItemType, ItemTypeIngredient, Ingredient

        # Field configuration is now data-driven from ingredient_categories table
        # (code_field_name, is_multi_select columns)
        # Special case: milk_sweetener_syrup group is split by ingredient category

        result = []
        db = SessionLocal()

        try:
            # Find the item type
            item_type = db.query(ItemType).filter(ItemType.slug == item_type_slug).first()
            if not item_type:
                logger.warning("Item type '%s' not found for modifier fields", item_type_slug)
                return result

            # Query all ingredients linked to this item type
            ingredient_links = (
                db.query(ItemTypeIngredient)
                .options(
                    joinedload(ItemTypeIngredient.ingredient)
                    .joinedload(Ingredient.alias_records),
                )
                .filter(
                    ItemTypeIngredient.item_type_id == item_type.id,
                    ItemTypeIngredient.is_available == True,
                )
                .order_by(ItemTypeIngredient.ingredient_group, ItemTypeIngredient.display_order)
                .all()
            )

            # Group ingredients by group (or category for milk_sweetener_syrup)
            from collections import defaultdict
            groups: dict[str, list[tuple[ItemTypeIngredient, Ingredient]]] = defaultdict(list)

            for link in ingredient_links:
                ingredient = link.ingredient
                group = link.ingredient_group

                # For the combined milk_sweetener_syrup group, use ingredient category
                if group == "milk_sweetener_syrup":
                    group = ingredient.category  # 'milk', 'sweetener', or 'syrup'

                groups[group].append((link, ingredient))

            # Convert each group to a modifier field
            for group, items in groups.items():
                # Get field config from cached ingredient_categories data (data-driven)
                field_config = self.get_ingredient_category_field_config(group)
                if field_config is None:
                    # Unknown category - skip or log
                    logger.debug("Unknown ingredient category '%s' - skipping", group)
                    continue

                # Collect all aliases for this group
                aliases = []
                for link, ingredient in items:
                    # Add the ingredient name
                    name_lower = ingredient.name.lower()
                    if name_lower not in aliases:
                        aliases.append(name_lower)

                    # Add display_name_override if different
                    if link.display_name_override:
                        override_lower = link.display_name_override.lower()
                        if override_lower not in aliases:
                            aliases.append(override_lower)

                    # Add all ingredient aliases
                    for alias in ingredient.aliases:
                        alias_lower = alias.strip().lower()
                        if alias_lower and alias_lower not in aliases:
                            aliases.append(alias_lower)

                result.append({
                    "field_name": field_config["code_field_name"],
                    "display_name": group.replace("_", " "),
                    "aliases": aliases,
                    "is_list": field_config["is_multi_select"],
                    "ingredient_group": group,
                })

            # For any item type with spread global attribute, add spread modifiers
            # Spreads are now stored as global attribute options
            from .models import ItemTypeGlobalAttribute, GlobalAttribute, GlobalAttributeOption

            spread_link = (
                db.query(ItemTypeGlobalAttribute)
                .join(GlobalAttribute)
                .filter(
                    ItemTypeGlobalAttribute.item_type_id == item_type.id,
                    GlobalAttribute.slug == "spread",
                )
                .first()
            )

            if spread_link:
                # Start with empty aliases - all aliases come from database
                spread_aliases = []

                # Get spread option names and aliases from global_attribute_options
                spread_options = (
                    db.query(GlobalAttributeOption)
                    .filter(
                        GlobalAttributeOption.global_attribute_id == spread_link.global_attribute_id,
                        GlobalAttributeOption.is_available == True,
                    )
                    .all()
                )

                for opt in spread_options:
                    # Add display name
                    display = (opt.display_name or opt.slug.replace("_", " ")).lower()
                    if display and display not in spread_aliases:
                        spread_aliases.append(display)
                    # Also add slug as an alias
                    slug_alias = opt.slug.lower().replace("_", " ")
                    if slug_alias and slug_alias not in spread_aliases:
                        spread_aliases.append(slug_alias)

                # Also add the category name "spread" as a catch-all alias
                if "spread" not in spread_aliases:
                    spread_aliases.append("spread")

                result.append({
                    "field_name": "spread",
                    "display_name": "spread",
                    "aliases": spread_aliases,
                    "is_list": False,
                    "ingredient_group": "spread",
                })

            logger.debug(
                "Loaded %d modifier field groups for %s: %s",
                len(result), item_type_slug, [f["field_name"] for f in result]
            )
            return result

        except Exception as e:
            logger.error("Failed to load modifier fields for %s: %s", item_type_slug, e)
            return result

        finally:
            db.close()

    def resolve_option_by_alias(self, attr_slug: str, input_value: str) -> dict | None:
        """Resolve an option by alias or slug for a global attribute.

        This method looks up an option by:
        1. Exact slug match
        2. Match against pipe-separated aliases

        Args:
            attr_slug: The attribute slug (e.g., "shots", "size")
            input_value: User input to resolve (e.g., "2", "double", "two")

        Returns:
            Option dict with keys: slug, display_name, price_modifier,
            iced_price_modifier, is_default, is_available, aliases.
            Returns None if no match found (this is semantic, not an error).

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Example:
            >>> cache.resolve_option_by_alias("shots", "2")
            {"slug": "double", "display_name": "Double", "price_modifier": 0.75, ...}
            >>> cache.resolve_option_by_alias("shots", "double")
            {"slug": "double", "display_name": "Double", "price_modifier": 0.75, ...}
            >>> cache.resolve_option_by_alias("shots", "two")
            {"slug": "double", "display_name": "Double", "price_modifier": 0.75, ...}
        """
        self._ensure_loaded()

        options = self._global_attribute_options.get(attr_slug, [])
        if not options:
            return None  # No options for this attribute - semantic "not found"

        input_lower = input_value.lower().strip()

        for opt in options:
            # Check exact slug match
            if opt["slug"].lower() == input_lower:
                return opt

            # Check aliases (now a list from child table)
            aliases = opt.get("aliases")
            if aliases:
                alias_list = [a.strip().lower() for a in aliases]
                if input_lower in alias_list:
                    return opt

        return None  # No match found - semantic "not found"

    def get_signature_item_aliases(self) -> dict[str, str]:
        """Get signature item alias mapping.

        Returns a dict mapping user input variations (aliases) to the actual
        menu item names in the database. This is used for recognizing orders
        like "bec", "bacon egg and cheese", "the classic", "the leo", etc.

        Returns:
            Dict mapping lowercase alias -> menu item name (with original casing).
            May be empty if no signature items are configured.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._signature_item_aliases.copy()

    def get_by_pound_items(self) -> dict[str, list[str]]:
        """Get by-the-pound items organized by category.

        Returns a dict mapping category names (fish, spread, cheese, cold_cut, salad)
        to lists of item names available in that category.

        Returns:
            Dict mapping category -> list of item names.
            May be empty if store doesn't sell by-pound items.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Example:
            {
                "fish": ["Nova Scotia Salmon", "Whitefish Salad", "Sable", ...],
                "spread": ["Plain Cream Cheese", "Scallion Cream Cheese", ...],
            }
        """
        self._ensure_loaded()
        return {k: list(v) for k, v in self._by_pound_items.items()}

    def get_by_pound_aliases(self) -> dict[str, tuple[str, str]]:
        """Get by-the-pound item alias mapping.

        Returns a dict mapping user input aliases to (canonical_name, category) tuples.
        This is used for recognizing by-pound orders like "lox", "nova", "whitefish".

        Returns:
            Dict mapping lowercase alias -> (canonical_name, category).
            May be empty if store doesn't sell by-pound items.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Example:
            {
                "lox": ("Nova Scotia Salmon", "fish"),
                "nova": ("Nova Scotia Salmon", "fish"),
                "scallion": ("Scallion Cream Cheese", "spread"),
            }
        """
        self._ensure_loaded()
        return self._by_pound_aliases.copy()

    def get_by_pound_category_names(self) -> dict[str, str]:
        """Get by-the-pound category display names.

        Returns a dict mapping category slugs to human-readable display names.

        Returns:
            Dict mapping category slug -> display name.
            May be empty if store doesn't sell by-pound items.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Example:
            {
                "cheese": "cheeses",
                "cold_cut": "cold cuts",
                "fish": "smoked fish",
                "salad": "salads",
                "spread": "spreads",
            }
        """
        self._ensure_loaded()
        return self._by_pound_category_names.copy()

    def find_by_pound_item(self, item_name: str) -> tuple[str, str] | None:
        """Find a by-pound item and its category by name or alias.

        Args:
            item_name: Item name or alias to look up (e.g., "lox", "nova", "whitefish salad")

        Returns:
            Tuple of (canonical_name, category) if found, None otherwise.
            None is a semantic "not found", not an error.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()

        item_lower = item_name.lower().strip()

        # Check direct alias match
        if item_lower in self._by_pound_aliases:
            return self._by_pound_aliases[item_lower]

        # Try partial matching
        best_match: tuple[str, str, int] | None = None  # (canonical_name, category, match_length)

        for alias, (canonical_name, category) in self._by_pound_aliases.items():
            # Check if input contains the alias or vice versa
            if item_lower in alias:
                match_len = len(alias)
                if best_match is None or match_len > best_match[2]:
                    best_match = (canonical_name, category, match_len)
            elif alias in item_lower:
                match_len = len(alias)
                if best_match is None or match_len > best_match[2]:
                    best_match = (canonical_name, category, match_len)

        if best_match:
            return (best_match[0], best_match[1])

        return None  # No match found - semantic "not found"

    def normalize_modifier(self, modifier: str) -> str:
        """
        Normalize a modifier name or alias to its canonical Ingredient name.

        This replaces the hardcoded MODIFIER_NORMALIZATIONS dictionary in constants.py.
        Aliases are loaded from the Ingredient.aliases column in the database.

        Args:
            modifier: User input like "lox", "veggie", "scallion", "eggs"

        Returns:
            Canonical Ingredient.name (e.g., "Nova Scotia Salmon" for "lox",
            "Vegetable Cream Cheese" for "veggie") or the original modifier
            if no mapping found (semantic "not found").

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Examples:
            >>> cache.normalize_modifier("lox")
            "Nova Scotia Salmon"
            >>> cache.normalize_modifier("veggie")
            "Vegetable Cream Cheese"
            >>> cache.normalize_modifier("unknown")
            "unknown"  # Returns original if not found
        """
        self._ensure_loaded()
        modifier_lower = modifier.lower().strip()
        return self._modifier_aliases.get(modifier_lower, modifier)

    def is_known_modifier(self, word: str) -> bool:
        """
        Check if a word is a known modifier (ingredient or alias).

        Used for smart tokenization to determine if a word is a modifier
        vs an item trigger.

        Args:
            word: Word to check (e.g., "cheese", "bacon", "lox")

        Returns:
            True if the word is a known modifier/ingredient

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Examples:
            >>> cache.is_known_modifier("bacon")
            True
            >>> cache.is_known_modifier("coffee")
            False
        """
        self._ensure_loaded()
        return word.lower().strip() in self._modifier_aliases

    def get_ingredient_aliases(self) -> dict[str, str]:
        """
        Get the mapping of ingredient aliases to canonical names.

        Returns a dictionary mapping lowercase alias strings to their
        canonical ingredient names.

        Used for merging search results between aliases (e.g., "lox" and "nova scotia salmon").

        Returns:
            Dict mapping alias (lowercase) -> canonical ingredient name

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Examples:
            >>> aliases = cache.get_ingredient_aliases()
            >>> aliases.get("lox")
            "Nova Scotia Salmon"
        """
        self._ensure_loaded()
        return self._modifier_aliases.copy()

    def get_all_modifier_words(self) -> set[str]:
        """
        Get all known modifier words (ingredients and their aliases).

        Returns lowercase set of all words that are recognized as modifiers.
        Used for fast lookup during tokenization.

        Returns:
            Set of all modifier words (lowercase)

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Examples:
            >>> words = cache.get_all_modifier_words()
            >>> "bacon" in words
            True
            >>> "lox" in words
            True
        """
        self._ensure_loaded()
        return set(self._modifier_aliases.keys())

    def is_known_attribute_option(self, word: str) -> tuple[bool, str | None]:
        """
        Check if a word is a known attribute option value.

        Checks against all global attribute options (size, temperature, etc.)
        and returns which attribute it belongs to.

        Args:
            word: Word to check (e.g., "large", "iced", "hot")

        Returns:
            Tuple of (is_known, attribute_slug)
            - (True, "size") if "large" is a size option
            - (True, "temperature") if "iced" is a temperature option
            - (False, None) if not a known attribute option

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Examples:
            >>> cache.is_known_attribute_option("large")
            (True, "size")
            >>> cache.is_known_attribute_option("iced")
            (True, "temperature")
            >>> cache.is_known_attribute_option("bagel")
            (False, None)
        """
        self._ensure_loaded()
        word_lower = word.lower().strip()

        for attr_slug, options in self._global_attribute_options.items():
            for opt in options:
                # Check slug and display_name
                if opt.get("slug", "").lower() == word_lower:
                    return True, attr_slug
                if opt.get("display_name", "").lower() == word_lower:
                    return True, attr_slug
        return False, None

    def get_all_attribute_option_words(self) -> dict[str, str]:
        """
        Get all known attribute option words mapped to their attribute slug.

        Returns dict mapping lowercase option words to their attribute slug.
        Used for fast lookup during tokenization.

        Returns:
            Dict mapping option word -> attribute slug
            e.g., {"large": "size", "iced": "temperature", "hot": "temperature"}

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Examples:
            >>> opts = cache.get_all_attribute_option_words()
            >>> opts.get("large")
            "size"
            >>> opts.get("iced")
            "temperature"
        """
        self._ensure_loaded()
        result: dict[str, str] = {}

        for attr_slug, options in self._global_attribute_options.items():
            for opt in options:
                slug = opt.get("slug", "").lower()
                display = opt.get("display_name", "").lower()
                if slug:
                    result[slug] = attr_slug
                if display and display != slug:
                    result[display] = attr_slug
        return result

    def get_all_config_answer_words(self) -> set[str]:
        """
        Get all valid configuration answer words from the database.

        Returns a set of lowercase words that are valid answers to item configuration
        questions. Includes:
        - All attribute option slugs and display names (e.g., "small", "large", "hot", "iced")
        - All bagel type names
        - All side item names
        - Negation variants for boolean attributes (e.g., "not toasted", "untoasted")

        This method replaces hardcoded answer lists with database-driven data.

        Returns:
            Set of lowercase answer words

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Examples:
            >>> words = cache.get_all_config_answer_words()
            >>> "large" in words
            True
            >>> "not toasted" in words
            True
        """
        self._ensure_loaded()
        answers: set[str] = set()

        # Add all global attribute options (size, temperature, etc.)
        for attr_slug, options in self._global_attribute_options.items():
            for opt in options:
                slug = opt.get("slug", "").lower()
                display = opt.get("display_name", "").lower()
                if slug:
                    answers.add(slug)
                if display:
                    answers.add(display)
                # Add aliases if available
                aliases = opt.get("aliases")
                if aliases:
                    for alias in aliases:
                        answers.add(alias.lower())

        # Add side item names (for side choice questions)
        if self._side_items:
            answers.update(self._side_items)

        # Add negation variants for boolean fields across all item types
        # Pattern: "not {field_name}" and "un{field_name}" for boolean fields
        for item_type_slug, fields in self._item_type_fields.items():
            for field in fields:
                input_type = field.get("input_type", "")
                if input_type == "boolean":
                    field_name = field.get("field_name", "").lower()
                    display_name = field.get("display_name", "").lower()
                    # Add the field name itself as valid answer
                    if field_name:
                        answers.add(field_name)
                        answers.add(f"not {field_name}")
                        answers.add(f"un{field_name}")
                    if display_name and display_name != field_name:
                        answers.add(display_name)
                        answers.add(f"not {display_name}")
                        answers.add(f"un{display_name}")

        return answers

    def get_relevant_keywords_for_attribute(
        self, item_type_slug: str | None, attr_slug: str
    ) -> set[str]:
        """
        Get keywords relevant to a specific attribute for off-topic detection.

        When configuring an attribute (e.g., "spread_type" for bagels), this returns
        keywords that indicate the user is asking about that same attribute, not
        going off-topic. For example, when asking about spread, "cream cheese",
        "butter", "schmear" are relevant keywords.

        Args:
            item_type_slug: The item type slug (e.g., "bagel", "sized_beverage").
                           Can be None for global attributes.
            attr_slug: The attribute slug (e.g., "spread_type", "size", "toasted")

        Returns:
            Set of lowercase keywords relevant to this attribute, including:
            - Attribute display_name words
            - All option display_names and slugs
            - All option aliases
            - Option category names (e.g., "cheese" for cheese options)

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Examples:
            >>> cache.get_relevant_keywords_for_attribute("bagel", "spread_type")
            {"spread", "cream cheese", "butter", "schmear", "scallion", ...}
            >>> cache.get_relevant_keywords_for_attribute("sized_beverage", "size")
            {"size", "small", "medium", "large", "regular", ...}
        """
        self._ensure_loaded()
        keywords: set[str] = set()

        # Try item-type-specific attributes first
        if item_type_slug:
            attrs = self.get_item_type_attributes(item_type_slug)
            if attr_slug in attrs:
                attr = attrs[attr_slug]
                self._extract_keywords_from_attribute(attr, keywords)
                return keywords

        # Try global attributes
        if attr_slug in self._global_attribute_options:
            options = self._global_attribute_options[attr_slug]
            # Add the attribute slug itself
            keywords.add(attr_slug.lower().replace("_", " "))
            keywords.add(attr_slug.lower())
            for opt in options:
                self._extract_keywords_from_option(opt, keywords)
            return keywords

        # Fallback: just use the attr_slug as a keyword
        keywords.add(attr_slug.lower().replace("_", " "))
        keywords.add(attr_slug.lower())
        return keywords

    def _extract_keywords_from_attribute(self, attr: dict, keywords: set[str]) -> None:
        """Extract keywords from an attribute config dict."""
        # Add attribute display_name words
        display_name = attr.get("display_name", "")
        if display_name:
            keywords.add(display_name.lower())
            for word in display_name.lower().split():
                if len(word) > 2:  # Skip tiny words like "a", "of"
                    keywords.add(word)

        # Add attribute slug
        slug = attr.get("slug", "")
        if slug:
            keywords.add(slug.lower())
            keywords.add(slug.lower().replace("_", " "))

        # Add keywords from all options
        for opt in attr.get("options", []):
            self._extract_keywords_from_option(opt, keywords)

    def _extract_keywords_from_option(self, opt: dict, keywords: set[str]) -> None:
        """Extract keywords from an option dict."""
        # Add option slug
        slug = opt.get("slug", "")
        if slug:
            keywords.add(slug.lower())
            keywords.add(slug.lower().replace("_", " "))

        # Add option display_name
        display_name = opt.get("display_name", "")
        if display_name:
            keywords.add(display_name.lower())
            # Also add individual words for multi-word options
            for word in display_name.lower().split():
                if len(word) > 2:
                    keywords.add(word)

        # Add option aliases
        aliases = opt.get("aliases")
        if aliases:
            for alias in aliases:
                keywords.add(alias.lower())

        # Add option category (e.g., "cheese", "spread")
        category = opt.get("category", "")
        if category:
            keywords.add(category.lower())

    def get_side_items(self) -> set[str]:
        """
        Get all known side item names and aliases (lowercase).

        Returns:
            Set of side item names and their aliases, all lowercase.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded or no side items found
        """
        self._ensure_loaded()
        if not self._side_items:
            raise MenuDataNotLoadedError(
                "No side items found in database. "
                "Check that menu_items table has items in 'side' category."
            )
        return self._side_items.copy()

    def resolve_side_alias(self, name: str) -> str | None:
        """
        Resolve a side item name or alias to its canonical menu item name.

        This replaces the hardcoded SIDE_ITEM_MAP dictionary in constants.py.
        Aliases are loaded from the MenuItem.aliases column in the database.

        Args:
            name: User input like "sausage", "latke", "bacon"

        Returns:
            Canonical MenuItem.name (e.g., "Side of Sausage" for "sausage",
            "Side of Breakfast Latke" for "latke") or None if not found.
            None is semantic "not found", not an error.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Examples:
            >>> cache.resolve_side_alias("sausage")
            "Side of Sausage"
            >>> cache.resolve_side_alias("latke")
            "Side of Breakfast Latke"
            >>> cache.resolve_side_alias("unknown")
            None  # Not found - caller should handle gracefully
        """
        self._ensure_loaded()
        name_lower = name.lower().strip()
        return self._side_alias_to_canonical.get(name_lower)

    def resolve_menu_item_alias(self, name: str) -> str | None:
        """
        Resolve a menu item name or alias to its canonical menu item name.

        This replaces:
        - The hardcoded MENU_ITEM_CANONICAL_NAMES dictionary in constants.py
        - The hardcoded NO_THE_PREFIX_ITEMS set in constants.py

        Aliases are loaded from the MenuItem.aliases column in the database.
        The canonical name is the MenuItem.name which already includes correct
        casing and "The " prefix where appropriate.

        Args:
            name: User input like "tuna salad", "blt", "cheese omelette"

        Returns:
            Canonical MenuItem.name (e.g., "Tuna Salad Sandwich" for "tuna salad",
            "The BLT" for "blt", "Cheese Omelette" for "cheese omelette")
            or None if not found.
            None is semantic "not found", not an error.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Examples:
            >>> cache.resolve_menu_item_alias("tuna salad")
            "Tuna Salad Sandwich"
            >>> cache.resolve_menu_item_alias("blt")
            "The BLT"
            >>> cache.resolve_menu_item_alias("cheese omelette")
            "Cheese Omelette"
            >>> cache.resolve_menu_item_alias("unknown item")
            None  # Not found - caller should handle gracefully
        """
        self._ensure_loaded()
        name_lower = name.lower().strip()
        return self._menu_item_alias_to_canonical.get(name_lower)

    def get_abbreviations(self) -> dict[str, str]:
        """
        Get the abbreviation-to-canonical mapping.

        Returns:
            Dict mapping abbreviation (lowercase) to canonical name (lowercase).
            Example: {"cc": "cream cheese", "pb": "peanut butter"}

        Raises:
            MenuDataNotLoadedError: If cache is not loaded or no abbreviations found
        """
        self._ensure_loaded()
        if not self._abbreviations:
            raise MenuDataNotLoadedError(
                "No abbreviations found in database. "
                "Check that ingredients or menu_items tables have abbreviation values."
            )
        return self._abbreviations.copy()

    def expand_abbreviations(self, text: str) -> str:
        """
        Expand abbreviations in the input text.

        Performs word-boundary replacement of abbreviations with their
        canonical forms. This should be called at the very beginning of
        parsing, before any other text processing.

        Args:
            text: Raw user input text

        Returns:
            Text with abbreviations expanded to canonical forms.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Examples:
            >>> cache.expand_abbreviations("strawberry cc")
            "strawberry cream cheese"
            >>> cache.expand_abbreviations("plain bagel with cc toasted")
            "plain bagel with cream cheese toasted"
            >>> cache.expand_abbreviations("I want a pb&j")  # no match for "pb&j"
            "I want a pb&j"
        """
        import re

        self._ensure_loaded()
        if not self._abbreviations:
            # No abbreviations defined - return original text
            return text

        result = text
        # Sort by length descending to match longer abbreviations first
        for abbrev, canonical in sorted(
            self._abbreviations.items(), key=lambda x: len(x[0]), reverse=True
        ):
            # Use word boundary matching (case-insensitive)
            # This ensures "cc" matches but "success" doesn't become "sucream cheesess"
            pattern = rf'\b{re.escape(abbrev)}\b'
            result = re.sub(pattern, canonical, result, flags=re.IGNORECASE)

        return result

    def get_category_keyword_mapping(self, keyword: str) -> dict | None:
        """
        Look up category info for a user keyword.

        This replaces the hardcoded MENU_CATEGORY_KEYWORDS constant in constants.py.
        Category keywords are loaded from the item_types.aliases column.

        Args:
            keyword: User input like "bagels", "desserts", "coffees", "teas"

        Returns:
            Dict with category info if found:
            {
                "slug": str,           # The category slug (e.g., "dessert", "bagel")
                "display_name": str,   # Singular display name
                "display_name_plural": str,  # Plural display name
                "lookup_type": str,    # "item_type" or "category"
            }
            Returns None if keyword not found.

            lookup_type determines how to query items:
            - "item_type": Query MenuItems by item_type_id
            - "category": Query MenuItems via MenuItemCategory join table

        Examples:
            >>> cache.get_category_keyword_mapping("bagels")
            {"slug": "bagel", "lookup_type": "item_type", ...}
            >>> cache.get_category_keyword_mapping("sandwiches")
            {"slug": "sandwich", "lookup_type": "category", ...}
            >>> cache.get_category_keyword_mapping("unknown")
            None
        """
        self._ensure_loaded()
        keyword_lower = keyword.lower().strip()
        return self._category_keywords.get(keyword_lower)

    def get_available_category_keywords(self) -> list[str]:
        """
        Get list of all available category keywords for error messages.

        Returns:
            Sorted list of all valid category keywords that can be used
            in menu/price queries.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Example:
            >>> cache.get_available_category_keywords()
            ["bagels", "beverages", "coffees", "desserts", "drinks", ...]
        """
        self._ensure_loaded()
        return sorted(self._category_keywords.keys())

    def is_category_reference(self, term: str) -> str | None:
        """Check if a term matches a category name/slug (case-insensitive).

        Handles pluralization dynamically using the singularize helper.
        This is a data-driven replacement for hardcoded GENERIC_DRINK_TERMS
        and similar constants.

        Args:
            term: User input like "drinks", "beverage", "cookies", "muffin"

        Returns:
            Category slug if match found, None otherwise.

        Examples:
            >>> menu_cache.is_category_reference("drinks")
            "sized_beverage"  # or whatever the DB slug is
            >>> menu_cache.is_category_reference("cookie")
            "pastry"  # if cookie maps to pastry category
            >>> menu_cache.is_category_reference("random word")
            None
        """
        self._ensure_loaded()
        term_lower = term.lower().strip()

        # Direct lookup first
        mapping = self._category_keywords.get(term_lower)
        if mapping:
            return mapping["slug"]

        # Try singularized form
        term_singular = singularize(term_lower)
        if term_singular != term_lower:
            mapping = self._category_keywords.get(term_singular)
            if mapping:
                return mapping["slug"]

        return None

    def search_menu_items_by_name(self, term: str) -> list[dict]:
        """Find menu items where the name contains the search term.

        This is a data-driven replacement for GENERIC_CATEGORY_TERMS matching.
        Use for disambiguation when user says something generic like "cookie"
        or "muffin" that could match multiple specific items.

        Args:
            term: Search term (e.g., "muffin", "cookie", "chip")

        Returns:
            List of matching menu item dicts with keys:
            - name: Menu item name
            - item_type: Item type slug
            - base_price: Base price if available

        Examples:
            >>> menu_cache.search_menu_items_by_name("muffin")
            [{"name": "Blueberry Muffin", "item_type": "pastry", "base_price": 3.50},
             {"name": "Corn Muffin", "item_type": "pastry", "base_price": 3.50}]
        """
        self._ensure_loaded()
        term_lower = term.lower().strip()
        term_singular = singularize(term_lower)

        matches = []

        # Search through known menu items
        for item_name in self._known_menu_items:
            item_lower = item_name.lower()
            # Match if term or singular form is in the item name
            if term_lower in item_lower or term_singular in item_lower:
                # Try to get item type from menu index
                item_info = self._menu_index.get(item_name, {})
                matches.append({
                    "name": item_name,
                    "item_type": item_info.get("item_type", "menu_item"),
                    "base_price": item_info.get("base_price", 0.0),
                })

        return matches

    def get_menu_item_names_by_category(self, category_slug: str) -> set[str]:
        """Get all menu item names that belong to a category.

        This is a data-driven replacement for hardcoded beverage/food keyword lists.
        Returns item names and their aliases for pattern matching.

        Args:
            category_slug: Category slug (e.g., "beverage", "bagel", "sandwich")

        Returns:
            Set of menu item names and aliases in that category

        Examples:
            >>> menu_cache.get_menu_item_names_by_category("beverage")
            {"Latte", "Cappuccino", "Espresso", "Coffee", "Cold Brew", ...}
        """
        self._ensure_loaded()
        names = set()

        # Get all menu items and filter by category
        for item_name, item_info in self._menu_index.items():
            item_category = item_info.get("category", "")
            # Match category directly or check if category contains the slug
            if item_category == category_slug or category_slug in item_category.lower():
                names.add(item_name)
                # Also add any aliases for this item
                aliases = item_info.get("aliases", [])
                if aliases:
                    names.update(aliases)

        # Also check modifier_category for item types
        for item_name, item_info in self._menu_index.items():
            item_type = item_info.get("item_type", "")
            if item_type:
                modifier_cat = self.get_modifier_category(item_type)
                if modifier_cat == category_slug:
                    names.add(item_name)
                    aliases = item_info.get("aliases", [])
                    if aliases:
                        names.update(aliases)

        return names

    def resolve_item_type_slug(self, name_or_alias: str) -> str:
        """
        Resolve an item type name or alias to its canonical database slug.

        This method enables data-driven item type resolution, eliminating
        the need for hardcoded mappings. It uses the item_type_aliases table
        loaded into _category_keywords.

        Args:
            name_or_alias: Item type name or alias (e.g., "coffee", "bagel",
                           "sized_beverage"). Case-insensitive.

        Returns:
            The canonical item type slug from the database.
            If no mapping is found, returns the input unchanged (pass-through).

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Examples:
            >>> cache.resolve_item_type_slug("coffee")
            "sized_beverage"
            >>> cache.resolve_item_type_slug("bagel")
            "bagel"
            >>> cache.resolve_item_type_slug("sized_beverage")
            "sized_beverage"
            >>> cache.resolve_item_type_slug("unknown_type")
            "unknown_type"  # Pass-through for unknown types
        """
        self._ensure_loaded()

        name_lower = name_or_alias.lower().strip()
        category_info = self._category_keywords.get(name_lower)

        if category_info and "slug" in category_info:
            return category_info["slug"]

        # Pass-through: return input unchanged if not found
        return name_or_alias

    def infer_item_type_from_text(self, text: str) -> dict | None:
        """
        Infer item type by checking if any category keyword appears in the text.

        This is used for fallback inference when an item isn't found on the menu.
        It scans the text for any word that matches a category keyword/alias
        and returns the corresponding item type info.

        Args:
            text: User input text like "orange juice" or "blueberry muffin"

        Returns:
            Dict with item type info if a keyword is found:
            {
                "slug": str,                    # The item_type or category slug
                "display_name": str,            # Singular display name
                "display_name_plural": str,     # Plural display name for suggestions
                "lookup_type": str,             # "item_type" or "category"
            }
            Returns None if no keyword matches.

        Examples:
            >>> cache.infer_item_type_from_text("orange juice")
            {"slug": "sized_beverage", "display_name": "Sized Beverage", ...}
            >>> cache.infer_item_type_from_text("blueberry muffin")
            {"slug": "pastry", "display_name": "Pastry", ...}
            >>> cache.infer_item_type_from_text("something random")
            None
        """
        self._ensure_loaded()

        text_lower = text.lower()
        words = text_lower.split()

        # Check each word against category keywords
        for word in words:
            if word in self._category_keywords:
                return self._category_keywords[word]

        # Check if any multi-word keyword is contained in the text
        for keyword, info in self._category_keywords.items():
            if " " in keyword and keyword in text_lower:
                return info

        return None

    def get_item_type_display_name(self, item_type_slug: str, plural: bool = False) -> str:
        """
        Get the display name for an item type slug.

        Args:
            item_type_slug: The item type slug (e.g., "sized_beverage", "bagel")
            plural: If True, return plural form for suggestions

        Returns:
            Display name string. Returns slug if not found.

        Examples:
            >>> cache.get_item_type_display_name("sized_beverage")
            "Sized Beverage"
            >>> cache.get_item_type_display_name("sized_beverage", plural=True)
            "coffees and teas"
        """
        self._ensure_loaded()

        info = self._category_keywords.get(item_type_slug)
        if info:
            if plural:
                return info.get("display_name_plural", info.get("display_name", item_type_slug) + "s")
            return info.get("display_name", item_type_slug)

        return item_type_slug

    # =========================================================================
    # Partial Matching Methods
    # =========================================================================

    def find_menu_item_matches(self, query: str) -> list[str]:
        """
        Find menu items that match a partial query.

        Args:
            query: User input like "classic" or "blt"

        Returns:
            List of matching menu item names.
        """
        query_lower = query.lower().strip()

        if not query_lower:
            return []

        # Check for exact match
        if query_lower in self._known_menu_items:
            return [query_lower]

        # Check keyword index
        matches = set()
        for word in query_lower.split():
            if word in self._menu_item_keyword_index:
                matches.update(self._menu_item_keyword_index[word])

        # Substring matching for short queries
        if not matches and len(query_lower) >= 3:
            for item in self._known_menu_items:
                if query_lower in item:
                    matches.add(item)

        return sorted(matches)

    # =========================================================================
    # Cache Status and Refresh
    # =========================================================================

    # =========================================================================
    # Item Type Field Methods
    # =========================================================================

    def get_item_type_fields(self, item_type_slug: str) -> list[dict]:
        """
        Get all field configurations for an item type.

        Fields are ordered by display_order and include:
        - field_name: The field identifier (e.g., "bagel_type", "toasted")
        - display_order: Order in which to ask questions
        - required: Whether the field must have a value for item to be complete
        - ask: Whether to prompt user for this field
        - question_text: The question to ask for this field

        Args:
            item_type_slug: The item type slug (e.g., "bagel", "sized_beverage")

        Returns:
            List of field config dicts, ordered by display_order.
            Returns empty list if item type not found in config.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Examples:
            >>> cache.get_item_type_fields("bagel")
            [
                {"field_name": "bagel_type", "display_order": 1, "required": True, ...},
                {"field_name": "toasted", "display_order": 2, "required": True, ...},
                ...
            ]
        """
        self._ensure_loaded()
        return self._item_type_fields.get(item_type_slug, [])

    def get_question_for_field(self, item_type_slug: str, field_name: str) -> str | None:
        """
        Get the question text for a specific field of an item type.

        Args:
            item_type_slug: The item type slug (e.g., "bagel", "sized_beverage")
            field_name: The field name (e.g., "toasted", "size")

        Returns:
            The question_text for the field, or None if not found (semantic "not found").

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Examples:
            >>> cache.get_question_for_field("bagel", "toasted")
            "Would you like it toasted?"
            >>> cache.get_question_for_field("sized_beverage", "size")
            "What size?"
        """
        self._ensure_loaded()
        fields = self._item_type_fields.get(item_type_slug, [])
        for field in fields:
            if field["field_name"] == field_name:
                return field.get("question_text")
        return None

    # =========================================================================
    # Menu Index Methods
    # =========================================================================

    def get_menu_index(self, store_id: str | None = None) -> dict[str, Any]:
        """
        Get the cached menu index.

        The menu index is built once at server startup and cached for
        performance. It contains all menu items organized by category.

        Args:
            store_id: Optional store ID (currently not used, for future
                     store-specific filtering)

        Returns:
            The cached menu index dict.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Note:
            This returns the cached index built at startup. The index is
            expensive to build (~55 seconds with N+1 queries) so we cache
            it rather than building on every request.
        """
        self._ensure_loaded()
        return self._menu_index

    # =========================================================================
    # Response Pattern Methods
    # =========================================================================

    def get_response_patterns(self, pattern_type: str) -> set[str]:
        """
        Get all patterns for a response type.

        Args:
            pattern_type: The type of response (affirmative, negative, cancel, done)

        Returns:
            Set of patterns for the type, or empty set if pattern_type not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Examples:
            >>> cache.get_response_patterns("affirmative")
            {"yes", "yeah", "yep", "sure", "ok", ...}
        """
        self._ensure_loaded()
        return self._response_patterns.get(pattern_type, set()).copy()

    def is_response_type(self, text: str, pattern_type: str) -> bool:
        """
        Check if text matches a response pattern type.

        Performs exact match against patterns after normalizing the text
        (lowercase, stripped).

        Args:
            text: User input to check
            pattern_type: The type of response to check (affirmative, negative, cancel, done)

        Returns:
            True if text matches any pattern of the given type.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Examples:
            >>> cache.is_response_type("yes", "affirmative")
            True
            >>> cache.is_response_type("no thanks", "negative")
            True
        """
        self._ensure_loaded()
        patterns = self._response_patterns.get(pattern_type, set())
        return text.lower().strip() in patterns

    def is_affirmative(self, text: str) -> bool:
        """
        Check if text is an affirmative response (yes, yeah, sure, ok, etc.).

        Args:
            text: User input to check

        Returns:
            True if text matches an affirmative pattern.

        Examples:
            >>> cache.is_affirmative("yes")
            True
            >>> cache.is_affirmative("sounds good")
            True
        """
        return self.is_response_type(text, "affirmative")

    def is_negative(self, text: str) -> bool:
        """
        Check if text is a negative response (no, nope, no thanks, etc.).

        Args:
            text: User input to check

        Returns:
            True if text matches a negative pattern.

        Examples:
            >>> cache.is_negative("no")
            True
            >>> cache.is_negative("no thanks")
            True
        """
        return self.is_response_type(text, "negative")

    def is_cancel(self, text: str) -> bool:
        """
        Check if text is a cancel response (cancel, never mind, forget it, etc.).

        Args:
            text: User input to check

        Returns:
            True if text matches a cancel pattern.

        Examples:
            >>> cache.is_cancel("cancel")
            True
            >>> cache.is_cancel("never mind")
            True
        """
        return self.is_response_type(text, "cancel")

    def is_done(self, text: str) -> bool:
        """
        Check if text is a done response (that's all, nothing else, etc.).

        Args:
            text: User input to check

        Returns:
            True if text matches a done pattern.

        Examples:
            >>> cache.is_done("that's all")
            True
            >>> cache.is_done("nothing else")
            True
        """
        return self.is_response_type(text, "done")

    # =========================================================================
    # Modifier Qualifier Methods
    # =========================================================================

    def get_modifier_qualifiers(self) -> dict[str, dict]:
        """
        Get all modifier qualifier patterns and their info.

        Returns:
            Dict mapping pattern (lowercase) to {normalized_form, category}.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded

        Example:
            {
                "extra": {"normalized_form": "extra", "category": "amount"},
                "lots of": {"normalized_form": "extra", "category": "amount"},
                "on the side": {"normalized_form": "on the side", "category": "position"},
            }
        """
        self._ensure_loaded()
        return self._modifier_qualifiers.copy()

    def get_qualifier_patterns(self) -> list[str]:
        """
        Get all qualifier patterns sorted by length (longest first).

        This ordering is important for matching - longer patterns like
        "a little bit of" should be matched before shorter patterns like "little".

        Returns:
            List of patterns sorted by length descending.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return sorted(self._modifier_qualifiers.keys(), key=len, reverse=True)

    def get_qualifier_patterns_by_category(self, category: str) -> set[str]:
        """
        Get all qualifier patterns for a specific category.

        Args:
            category: The category (amount, position, preparation)

        Returns:
            Set of patterns for the category.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._qualifier_patterns_by_category.get(category, set()).copy()

    def get_qualifier_info(self, pattern: str) -> dict | None:
        """
        Get info for a specific qualifier pattern.

        Args:
            pattern: The pattern to look up (e.g., "extra", "on the side")

        Returns:
            Dict with {normalized_form, category} or None if not found (semantic "not found").

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._modifier_qualifiers.get(pattern.lower())

    def normalize_qualifier(self, pattern: str) -> str | None:
        """
        Get the normalized form for a qualifier pattern.

        Args:
            pattern: The pattern to normalize (e.g., "lots of", "a little bit of")

        Returns:
            Normalized form (e.g., "extra", "light") or None if not found.

        Examples:
            >>> cache.normalize_qualifier("lots of")
            "extra"
            >>> cache.normalize_qualifier("a little bit of")
            "light"
            >>> cache.normalize_qualifier("on the side")
            "on the side"
        """
        info = self.get_qualifier_info(pattern)
        return info["normalized_form"] if info else None

    def get_qualifier_category(self, pattern: str) -> str | None:
        """
        Get the category for a qualifier pattern.

        Args:
            pattern: The pattern to look up (e.g., "extra", "on the side")

        Returns:
            Category (amount, position, preparation) or None if not found.
        """
        info = self.get_qualifier_info(pattern)
        return info["category"] if info else None

    # =========================================================================
    # Data-Driven Parsing Support Methods
    # =========================================================================

    def get_compound_phrases(self) -> set[str]:
        """
        Get phrases containing ' and ' that shouldn't be split during parsing.

        These phrases represent single items or concepts (like "bacon egg and cheese",
        "ham and swiss", "salt and pepper") that should be protected from being
        split when processing multi-item orders.

        Returns:
            Set of compound phrases (lowercase).

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._compound_phrases.copy()

    def get_item_type_triggers(self, item_type_slug: str | None = None) -> dict[str, set[str]] | set[str]:
        """
        Get trigger keywords for item types.

        These keywords trigger detection of specific item types during parsing.
        For example, "latte" or "cappuccino" trigger "sized_beverage".

        Args:
            item_type_slug: Optional specific item type to get triggers for.
                If None, returns all triggers keyed by item type.

        Returns:
            If item_type_slug is provided: Set of trigger keywords for that type.
            If item_type_slug is None: Dict mapping item_type_slug -> set of triggers.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        if item_type_slug is not None:
            return self._item_type_triggers.get(item_type_slug, set()).copy()
        return {k: v.copy() for k, v in self._item_type_triggers.items()}

    def get_menu_items_by_unit_type(self, unit_type: str) -> set[str]:
        """
        Get menu items sold by a specific unit type.

        Args:
            unit_type: How items are sold - 'each', 'by_weight', or 'dozen'.

        Returns:
            Set of menu item names (lowercase) sold by that unit type.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._by_unit_type_items.get(unit_type, set()).copy()

    def is_by_weight_item(self, item_name: str) -> bool:
        """
        Check if an item is sold by weight.

        Args:
            item_name: The menu item name to check.

        Returns:
            True if the item is sold by weight, False otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return item_name.lower() in self._by_unit_type_items.get("by_weight", set())

    def is_dozen_item(self, item_name: str) -> bool:
        """
        Check if an item is sold by the dozen.

        Args:
            item_name: The menu item name to check.

        Returns:
            True if the item is sold by the dozen, False otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return item_name.lower() in self._by_unit_type_items.get("dozen", set())

    def detect_item_type_from_keyword(self, keyword: str) -> str | None:
        """
        Detect which item type a keyword belongs to.

        Scans all item type triggers to find which item type (if any)
        the given keyword triggers.

        Args:
            keyword: The keyword to check (e.g., "latte", "bagel", "omelette")

        Returns:
            The item_type_slug if found, None otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        keyword_lower = keyword.lower()
        for item_type_slug, triggers in self._item_type_triggers.items():
            if keyword_lower in triggers:
                return item_type_slug
        return None

    def get_status(self) -> dict[str, Any]:
        """Get cache status information."""
        return {
            "is_loaded": self._is_loaded,
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
            "counts": {
                "known_menu_items": len(self._known_menu_items),
                "by_pound_categories": len(self._by_pound_items),
                "by_pound_aliases": len(self._by_pound_aliases),
                "item_type_fields": sum(len(fields) for fields in self._item_type_fields.values()),
                "response_patterns": sum(len(p) for p in self._response_patterns.values()),
                "modifier_qualifiers": len(self._modifier_qualifiers),
                "compound_phrases": len(self._compound_phrases),
                "item_type_triggers": sum(len(t) for t in self._item_type_triggers.values()),
                "by_unit_type_items": {k: len(v) for k, v in self._by_unit_type_items.items()},
                # Generic data-driven caches
                "item_names_by_type": {k: len(v) for k, v in self._item_names_by_type.items()},
                "ingredients_by_category": {k: len(v) for k, v in self._ingredients_by_category.items()},
            },
            "keyword_indices": {
                "menu_item_keywords": len(self._menu_item_keyword_index),
            },
        }

    async def start_background_refresh(self, get_db_session) -> None:
        """
        Start the background refresh task that runs daily at configured hour.

        Args:
            get_db_session: Callable that returns a database session context manager
        """
        self._refresh_task = asyncio.create_task(
            self._background_refresh_loop(get_db_session)
        )
        logger.info("Started background menu cache refresh task (runs daily at %d:00)", self._refresh_hour)

    async def stop_background_refresh(self) -> None:
        """Stop the background refresh task."""
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
            self._refresh_task = None
            logger.info("Stopped background menu cache refresh task")

    async def _background_refresh_loop(self, get_db_session) -> None:
        """Background loop that refreshes cache daily at configured hour."""
        while True:
            try:
                # Calculate seconds until next refresh time
                now = datetime.now()
                target_time = now.replace(hour=self._refresh_hour, minute=0, second=0, microsecond=0)

                # If target time has passed today, schedule for tomorrow
                if now >= target_time:
                    from datetime import timedelta
                    target_time += timedelta(days=1)

                seconds_until_refresh = (target_time - now).total_seconds()
                logger.debug("Next cache refresh in %.0f seconds (at %s)", seconds_until_refresh, target_time)

                await asyncio.sleep(seconds_until_refresh)

                # Perform refresh
                logger.info("Running scheduled menu cache refresh...")
                with get_db_session() as db:
                    self.load_from_db(db, fail_on_error=False, force=True)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in background cache refresh: %s", e)
                # Wait an hour before retrying on error
                await asyncio.sleep(3600)


# Global singleton instance
menu_cache = MenuDataCache()
