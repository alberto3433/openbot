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
- Fallback to hardcoded values if DB unavailable

Usage:
    from sandwich_bot.menu_data_cache import menu_cache

    # Get spread types (returns set)
    spread_types = menu_cache.get_spread_types()

    # Find partial matches for disambiguation
    matches = menu_cache.find_spread_matches("walnut")
    # Returns: ["honey walnut", "maple raisin walnut"]
"""

import asyncio
import logging
import threading
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class MenuDataCache:
    """
    Singleton cache for menu data loaded from the database.

    Replaces hardcoded constants with database-driven values while
    maintaining backward compatibility through fallback values.
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
        self._spreads: set[str] = set()
        self._spread_types: set[str] = set()
        self._bagel_spreads: set[str] = set()  # Combined patterns for matching
        self._bagel_types: set[str] = set()
        self._bagel_types_list: list[str] = []  # Ordered list for display/pagination
        self._proteins: set[str] = set()
        self._toppings: set[str] = set()
        self._cheeses: set[str] = set()
        self._coffee_types: set[str] = set()
        self._soda_types: set[str] = set()
        self._known_menu_items: set[str] = set()

        # Beverage modifier options (from item_type_ingredients table)
        self._beverage_milks: list[str] = []  # Ordered list of milk options
        self._beverage_sweeteners: list[str] = []  # Ordered list of sweetener options
        self._beverage_syrups: list[str] = []  # Ordered list of syrup options

        # Alias-to-canonical name mappings (for resolving user input to menu item names)
        self._coffee_alias_to_canonical: dict[str, str] = {}
        self._soda_alias_to_canonical: dict[str, str] = {}
        self._signature_item_aliases: dict[str, str] = {}  # alias -> menu item name
        self._modifier_aliases: dict[str, str] = {}  # alias -> Ingredient.name (canonical)
        self._side_items: set[str] = set()  # All side item names/aliases (lowercase)
        self._side_alias_to_canonical: dict[str, str] = {}  # alias -> MenuItem.name (canonical)
        self._menu_item_alias_to_canonical: dict[str, str] = {}  # alias -> MenuItem.name (canonical)

        # Abbreviations for text expansion before parsing (e.g., "cc" -> "cream cheese")
        # Unlike aliases (used for matching), abbreviations replace text in the input
        self._abbreviations: dict[str, str] = {}  # abbreviation -> canonical name (lowercase)

        # Category keyword mappings (replaces MENU_CATEGORY_KEYWORDS constant)
        # Maps user keywords (bagels, desserts, etc.) to category info
        self._category_keywords: dict[str, dict] = {}  # keyword -> {slug, expands_to, name_filter}

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

        # Keyword indices for partial matching
        self._spread_keyword_index: dict[str, list[str]] = {}
        self._bagel_keyword_index: dict[str, list[str]] = {}
        self._menu_item_keyword_index: dict[str, list[str]] = {}

        # Cached menu index (expensive to build, loaded once at startup)
        self._menu_index: dict[str, Any] = {}

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

    def load_from_db(self, db: Session, fail_on_error: bool = True) -> None:
        """
        Load all menu data from the database.

        Args:
            db: SQLAlchemy database session
            fail_on_error: If True, raise exception on DB errors (for startup)
                          If False, log warning and keep existing cache

        Raises:
            RuntimeError: If fail_on_error=True and DB load fails
        """
        with self._refresh_lock:
            try:
                logger.info("Loading menu data cache from database...")

                # Load each category
                self._load_spread_types(db)
                self._load_bagel_types(db)
                self._load_proteins(db)
                self._load_toppings(db)
                self._load_cheeses(db)
                self._load_coffee_types(db)
                self._load_soda_types(db)
                self._load_beverage_modifiers(db)
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
                self._load_menu_index(db)

                # Build keyword indices for partial matching
                self._build_keyword_indices()

                self._last_refresh = datetime.now()
                self._is_loaded = True

                logger.info(
                    "Menu data cache loaded: %d spread_types, %d bagel_types, "
                    "%d proteins, %d toppings, %d cheeses, %d coffee_types, "
                    "%d soda_types, %d menu_items, %d signature_item_aliases,"
                    "%d by_pound_categories, %d abbreviations",
                    len(self._spread_types),
                    len(self._bagel_types),
                    len(self._proteins),
                    len(self._toppings),
                    len(self._cheeses),
                    len(self._coffee_types),
                    len(self._soda_types),
                    len(self._known_menu_items),
                    len(self._signature_item_aliases),
                    len(self._by_pound_items),
                    len(self._abbreviations),
                )

            except Exception as e:
                logger.error("Failed to load menu data cache: %s", e)
                if fail_on_error:
                    raise RuntimeError(f"Failed to load menu data cache: {e}") from e
                # Keep existing cache if available

    def _load_spread_types(self, db: Session) -> None:
        """Load spread types from cream cheese menu items and base spreads from ingredients.

        Also builds the _bagel_spreads set which combines base spreads with their
        variety types for pattern matching (e.g., "scallion cream cheese", "scallion").
        """
        import re
        from .models import MenuItem, Ingredient

        spread_types = set()
        spreads = set()
        bagel_spreads = set()

        # Load from cream cheese menu items
        # Items like "Honey Walnut Cream Cheese (1/4 lb)" -> extract "honey walnut"
        cream_cheese_items = (
            db.query(MenuItem)
            .filter(MenuItem.category == "cream_cheese")
            .all()
        )

        for item in cream_cheese_items:
            name = item.name.lower()
            # Remove weight suffix like "(1/4 lb)", "(1 lb)"
            name = re.sub(r'\s*\([^)]*\)\s*$', '', name).strip()

            # Extract spread type from name
            # "honey walnut cream cheese" -> "honey walnut"
            # "plain cream cheese" -> "plain"
            if "cream cheese" in name:
                spread_type = name.replace("cream cheese", "").strip()
                if spread_type and spread_type != "plain":
                    spread_types.add(spread_type)
                spreads.add("cream cheese")

        # Also check spread_sandwich menu items
        spread_sandwiches = (
            db.query(MenuItem)
            .filter(MenuItem.category == "spread_sandwich")
            .all()
        )

        for item in spread_sandwiches:
            name = item.name.lower()
            # "Scallion Cream Cheese Sandwich" -> "scallion"
            name = name.replace("sandwich", "").strip()
            if "cream cheese" in name:
                spread_type = name.replace("cream cheese", "").strip()
                if spread_type and spread_type not in ("plain", "regular"):
                    spread_types.add(spread_type)

        # Load base spreads from ingredients with category='spread'
        spread_ingredients = (
            db.query(Ingredient)
            .filter(Ingredient.category == "spread")
            .all()
        )
        for ing in spread_ingredients:
            spreads.add(ing.name.lower())
            # Also add aliases
            if ing.aliases:
                for alias in ing.aliases.split(","):
                    alias = alias.strip().lower()
                    if alias:
                        spreads.add(alias)

        # Build bagel_spreads - all patterns for matching spreads in user input
        # This combines base spreads with spread types
        for spread in spreads:
            bagel_spreads.add(spread)
            # Add "plain X" variation for cream cheese
            if spread == "cream cheese":
                bagel_spreads.add("plain cream cheese")

        # Add spread type variations (e.g., "scallion cream cheese", "scallion")
        for spread_type in spread_types:
            bagel_spreads.add(spread_type)
            bagel_spreads.add(f"{spread_type} cream cheese")

        # Add specific known patterns
        bagel_spreads.add("lox spread")

        self._spreads = spreads
        self._spread_types = spread_types
        self._bagel_spreads = bagel_spreads

    def _load_bagel_types(self, db: Session) -> None:
        """Load bagel types from ingredients table.

        Parses bagel names and includes aliases for matching.
        Also builds an ordered list for display/pagination.
        """
        from .models import Ingredient

        bagel_types = set()
        bagel_types_list = []

        # Query ingredients that are bagel types (category='bread')
        bagel_ingredients = (
            db.query(Ingredient)
            .filter(Ingredient.category == "bread")
            .filter(Ingredient.is_available == True)  # noqa: E712
            .order_by(Ingredient.name)
            .all()
        )

        for ing in bagel_ingredients:
            name = ing.name.lower()

            # Parse bagel type from name
            # "Plain Bagel" -> "plain", "Everything Bagel" -> "everything"
            # "Bialy" -> "bialy" (no "bagel" suffix)
            if "bagel" in name:
                bagel_type = name.replace("bagel", "").strip()
            else:
                # Handle items without "bagel" in name (e.g., "Bialy")
                bagel_type = name.strip()

            if bagel_type:
                bagel_types.add(bagel_type)
                # Add to ordered list (display name without "Bagel" suffix)
                display_name = bagel_type.title() if bagel_type != "gluten free" else "Gluten Free"
                if bagel_type not in [bt.lower() for bt in bagel_types_list]:
                    bagel_types_list.append(bagel_type)

            # Add aliases if present
            if hasattr(ing, 'aliases') and ing.aliases:
                for alias in ing.aliases.split(","):
                    alias = alias.strip().lower()
                    if alias:
                        bagel_types.add(alias)

        # Fallback if DB is empty
        if not bagel_types:
            bagel_types = {
                "plain", "everything", "sesame", "poppy", "onion",
                "cinnamon raisin", "cinnamon", "raisin", "pumpernickel",
                "whole wheat", "wheat", "salt", "garlic", "bialy",
                "egg", "multigrain", "asiago", "jalapeno", "blueberry",
                "gluten free", "gluten-free",
            }
            bagel_types_list = [
                "plain", "everything", "sesame", "poppy",
                "onion", "cinnamon raisin", "whole wheat", "pumpernickel",
                "salt", "garlic", "egg", "multigrain",
                "asiago", "jalapeno", "blueberry", "bialy",
            ]

        self._bagel_types = bagel_types
        self._bagel_types_list = bagel_types_list

    def _load_proteins(self, db: Session) -> None:
        """Load protein types from ingredients table.

        Loads protein ingredient names and their aliases for matching user input.
        Fails with RuntimeError if no proteins found in database.
        """
        from .models import Ingredient

        proteins = set()

        protein_ingredients = (
            db.query(Ingredient)
            .filter(Ingredient.category == "protein")
            .all()
        )

        for ing in protein_ingredients:
            # Add the ingredient name
            proteins.add(ing.name.lower())
            # Also add aliases if present
            if ing.aliases:
                for alias in ing.aliases.split(","):
                    alias = alias.strip().lower()
                    if alias:
                        proteins.add(alias)

        # Fail if database has no proteins configured
        if not proteins:
            raise RuntimeError(
                "No proteins found in database. Run migrations to populate ingredients table."
            )

        self._proteins = proteins

    def _load_toppings(self, db: Session) -> None:
        """Load topping types from ingredients table.

        Loads topping ingredient names and their aliases for matching user input.
        Also includes sauces (mayo, mustard, etc.) as they function as toppings.
        Fails with RuntimeError if no toppings found in database.
        """
        from .models import Ingredient

        toppings = set()

        # Load toppings category
        topping_ingredients = (
            db.query(Ingredient)
            .filter(Ingredient.category == "topping")
            .all()
        )

        for ing in topping_ingredients:
            # Add the ingredient name
            toppings.add(ing.name.lower())
            # Also add aliases if present
            if ing.aliases:
                for alias in ing.aliases.split(","):
                    alias = alias.strip().lower()
                    if alias:
                        toppings.add(alias)

        # Also load sauces as they function as toppings on bagels
        sauce_ingredients = (
            db.query(Ingredient)
            .filter(Ingredient.category == "sauce")
            .all()
        )

        for ing in sauce_ingredients:
            toppings.add(ing.name.lower())
            if ing.aliases:
                for alias in ing.aliases.split(","):
                    alias = alias.strip().lower()
                    if alias:
                        toppings.add(alias)

        # Fail if database has no toppings configured
        if not toppings:
            raise RuntimeError(
                "No toppings found in database. Run migrations to populate ingredients table."
            )

        self._toppings = toppings

    def _load_cheeses(self, db: Session) -> None:
        """Load sliced cheese types from ingredients table.

        Loads cheese ingredient names and their aliases for matching user input.
        Only loads actual sliced cheeses (American, Swiss, etc.), not cream cheese
        spreads which are in the "spread" category.
        Fails with RuntimeError if no cheeses found in database.
        """
        from .models import Ingredient

        cheeses = set()

        cheese_ingredients = (
            db.query(Ingredient)
            .filter(Ingredient.category == "cheese")
            .all()
        )

        for ing in cheese_ingredients:
            # Add the ingredient name
            cheeses.add(ing.name.lower())
            # Also add aliases if present
            if ing.aliases:
                for alias in ing.aliases.split(","):
                    alias = alias.strip().lower()
                    if alias:
                        cheeses.add(alias)

        # Fail if database has no cheeses configured
        if not cheeses:
            raise RuntimeError(
                "No cheeses found in database. Run migrations to populate ingredients table."
            )

        self._cheeses = cheeses

    def _load_coffee_types(self, db: Session) -> None:
        """Load coffee/tea beverage types from menu items.

        Uses item_type='sized_beverage' or 'espresso' to identify coffee/tea drinks
        that need configuration.

        Includes both item names and their aliases for matching user input.
        Also builds a mapping from aliases to canonical names.
        """
        from .models import MenuItem, ItemType

        coffee_types = set()
        alias_to_canonical = {}

        # Query sized_beverage and espresso items (coffee/tea that need configuration)
        # Espresso is a separate item type but should be recognized as a coffee for parsing
        coffee_items = (
            db.query(MenuItem)
            .join(ItemType, MenuItem.item_type_id == ItemType.id)
            .filter(ItemType.slug.in_(["sized_beverage", "espresso"]))
            .all()
        )

        for item in coffee_items:
            canonical_name = item.name.lower()
            # Add the item name (lowercase)
            coffee_types.add(canonical_name)
            # Map canonical name to itself
            alias_to_canonical[canonical_name] = item.name  # Preserve original casing

            # Add all aliases if present
            if item.aliases:
                for alias in item.aliases.split(","):
                    alias = alias.strip().lower()
                    if alias:
                        coffee_types.add(alias)
                        # Map alias to canonical name (preserve original casing)
                        alias_to_canonical[alias] = item.name

        self._coffee_types = coffee_types
        self._coffee_alias_to_canonical = alias_to_canonical

    def _load_soda_types(self, db: Session) -> None:
        """Load soda/bottled beverage types from menu items.

        Uses item_type='beverage' to identify sodas/bottled drinks that don't
        need configuration (as opposed to 'sized_beverage' for coffee/tea).

        Includes both item names and their aliases for matching user input.
        Also builds a mapping from aliases to canonical names.
        """
        from .models import MenuItem, ItemType

        soda_types = set()
        alias_to_canonical = {}

        # Query beverage items (item_type.slug = 'beverage')
        # These are sodas/bottled drinks that don't need size configuration
        beverage_items = (
            db.query(MenuItem)
            .join(ItemType, MenuItem.item_type_id == ItemType.id)
            .filter(ItemType.slug == "beverage")
            .all()
        )

        for item in beverage_items:
            canonical_name = item.name.lower()
            # Add the item name (lowercase)
            soda_types.add(canonical_name)
            # Map canonical name to itself
            alias_to_canonical[canonical_name] = item.name  # Preserve original casing

            # Add all aliases if present
            if item.aliases:
                for alias in item.aliases.split(","):
                    alias = alias.strip().lower()
                    if alias:
                        soda_types.add(alias)
                        # Map alias to canonical name (preserve original casing)
                        alias_to_canonical[alias] = item.name

        self._soda_types = soda_types
        self._soda_alias_to_canonical = alias_to_canonical

    def _load_beverage_modifiers(self, db: Session) -> None:
        """Load beverage modifier options (milk, sweetener, syrup) from the database.

        Queries the item_type_ingredients table for sized_beverage modifiers.
        The ingredient_group may be 'milk_sweetener_syrup' (consolidated) or the legacy
        individual groups (milk, sweetener, syrup). We categorize by ingredient.category
        to properly split modifiers into milks, sweeteners, and syrups.

        Results are ordered by display_order and store display names for user-facing text.
        """
        from .models import ItemType, ItemTypeIngredient, Ingredient

        # Find the sized_beverage item type
        sized_beverage = db.query(ItemType).filter(ItemType.slug == "sized_beverage").first()
        if not sized_beverage:
            logger.warning("No sized_beverage item type found - beverage modifiers not loaded")
            return

        # Query all drink modifiers (both consolidated 'milk_sweetener_syrup' group
        # and legacy individual groups)
        modifiers = (
            db.query(ItemTypeIngredient, Ingredient)
            .join(Ingredient, ItemTypeIngredient.ingredient_id == Ingredient.id)
            .filter(ItemTypeIngredient.item_type_id == sized_beverage.id)
            .filter(ItemTypeIngredient.ingredient_group.in_(
                ['milk_sweetener_syrup', 'milk', 'sweetener', 'syrup']
            ))
            .filter(ItemTypeIngredient.is_available == True)
            .order_by(ItemTypeIngredient.display_order)
            .all()
        )

        # Clear existing lists
        self._beverage_milks.clear()
        self._beverage_sweeteners.clear()
        self._beverage_syrups.clear()

        # Categorize by ingredient.category (the source of truth)
        for link, ingredient in modifiers:
            display_name = link.display_name_override or ingredient.name
            category = ingredient.category

            if category == 'milk':
                self._beverage_milks.append(display_name)
            elif category == 'sweetener':
                self._beverage_sweeteners.append(display_name)
            elif category == 'syrup':
                self._beverage_syrups.append(display_name)
            # Skip other categories (they may be linked but not beverage modifiers)

        logger.debug("Loaded beverage modifiers: %d milks, %d sweeteners, %d syrups",
                    len(self._beverage_milks), len(self._beverage_sweeteners),
                    len(self._beverage_syrups))

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

        all_items = db.query(MenuItem).all()
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

            # Add all aliases if present
            if item.aliases:
                for alias in item.aliases.split(","):
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

        # Query signature items with aliases
        # Only signature items should be in this mapping
        # (non-signature items like "Coffee" have their own parsing flow)
        items_with_aliases = (
            db.query(MenuItem)
            .filter(MenuItem.is_signature == True)  # noqa: E712
            .filter(MenuItem.aliases.isnot(None))
            .filter(MenuItem.aliases != "")
            .all()
        )

        for item in items_with_aliases:
            canonical_name = item.name  # Keep original casing

            # Parse comma-separated aliases
            for alias in item.aliases.split(","):
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
            len(items_with_aliases),
        )

    def _load_by_pound_items(self, db: Session) -> None:
        """Load by-the-pound items organized by category.

        Builds two data structures:
        1. _by_pound_items: dict mapping category (fish, spread, etc.) to list of item names
        2. _by_pound_aliases: dict mapping aliases to (canonical_name, category) tuples

        This replaces the hardcoded BY_POUND_ITEMS constant.
        """
        import re
        from .models import MenuItem

        by_pound_items: dict[str, list[str]] = {}
        by_pound_aliases: dict[str, tuple[str, str]] = {}

        # Query items with by_pound_category set
        items = (
            db.query(MenuItem)
            .filter(MenuItem.by_pound_category.isnot(None))
            .order_by(MenuItem.by_pound_category, MenuItem.name)
            .all()
        )

        # Group items by category and extract base names (without weight suffix)
        seen_base_names: dict[str, str] = {}  # Track which base names we've seen per category

        for item in items:
            category = item.by_pound_category
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

            # Add aliases if present
            if item.aliases:
                for alias in item.aliases.split(","):
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
        """Load by-the-pound category display names from database.

        Loads the mapping from category slugs (cheese, cold_cut, fish, etc.)
        to human-readable display names (cheeses, cold cuts, smoked fish, etc.).

        Falls back to hardcoded values if the by_pound_categories table doesn't exist.
        """
        category_names: dict[str, str] = {}

        try:
            # Query the by_pound_categories table
            result = db.execute(
                __import__("sqlalchemy").text(
                    "SELECT slug, display_name FROM by_pound_categories"
                )
            )

            for row in result:
                category_names[row.slug] = row.display_name
        except Exception as e:
            # Table may not exist (dropped in migration), use hardcoded fallback
            # Rollback to clear the failed transaction state
            db.rollback()
            logger.debug("by_pound_categories table not available, using fallback: %s", e)
            category_names = {
                "fish": "smoked fish",
                "spread": "spreads",
                "cheese": "cheeses",
                "cold_cut": "cold cuts",
                "salad": "salads",
            }

        self._by_pound_category_names = category_names

        logger.debug(
            "Loaded %d by-pound category names",
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

        # Query all ingredients with aliases
        ingredients_with_aliases = (
            db.query(Ingredient)
            .filter(Ingredient.aliases.isnot(None))
            .filter(Ingredient.aliases != "")
            .all()
        )

        for ing in ingredients_with_aliases:
            canonical_name = ing.name  # Preserve original casing

            # Parse comma-separated aliases
            for alias in ing.aliases.split(","):
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
            len(ingredients_with_aliases),
        )

    def _load_side_items(self, db: Session) -> None:
        """Load side items and their aliases from menu_items.

        Builds a mapping from user input variations (aliases) to canonical
        MenuItem.name values. This replaces the hardcoded SIDE_ITEM_MAP
        constant in constants.py.

        The mapping is used for resolving side item input like "sausage" ->
        "Side of Sausage", "latke" -> "Side of Breakfast Latke", etc.
        """
        from .models import MenuItem

        side_items: set[str] = set()
        alias_to_canonical: dict[str, str] = {}

        # Query side items (category = 'side')
        items = (
            db.query(MenuItem)
            .filter(MenuItem.category == "side")
            .all()
        )

        for item in items:
            canonical_name = item.name  # Preserve original casing
            name_lower = canonical_name.lower()

            # Add the item name (lowercase)
            side_items.add(name_lower)
            alias_to_canonical[name_lower] = canonical_name

            # Add all aliases if present
            if item.aliases:
                for alias in item.aliases.split(","):
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
        """Load category keyword mappings from item_types table.

        Builds a mapping from user keywords (bagels, desserts, coffees, etc.)
        to category info (slug, expands_to, name_filter).

        This replaces the hardcoded MENU_CATEGORY_KEYWORDS constant in constants.py.

        For virtual/meta categories (dessert, beverage_all, etc.), the expands_to
        field contains a list of slugs to query. For regular categories,
        expands_to is None and the slug itself is used.

        Raises:
            RuntimeError: If no category keywords found in database.
        """
        import json
        from .models import ItemType

        category_keywords: dict[str, dict] = {}

        # Query all item_types that have aliases defined
        item_types = (
            db.query(ItemType)
            .filter(ItemType.aliases.isnot(None))
            .filter(ItemType.aliases != "")
            .all()
        )

        for item_type in item_types:
            slug = item_type.slug

            # Parse expands_to JSON if present
            expands_to = None
            if hasattr(item_type, 'expands_to') and item_type.expands_to:
                if isinstance(item_type.expands_to, str):
                    try:
                        expands_to = json.loads(item_type.expands_to)
                    except json.JSONDecodeError:
                        logger.warning("Invalid expands_to JSON for item_type %s", slug)
                else:
                    expands_to = item_type.expands_to

            # Get name_filter if present
            name_filter = getattr(item_type, 'name_filter', None)

            # Create category info dict
            category_info = {
                "slug": slug,
                "expands_to": expands_to,
                "name_filter": name_filter,
            }

            # Add slug itself as a key
            category_keywords[slug] = category_info

            # Add all aliases as keys
            for alias in item_type.aliases.split(","):
                alias = alias.strip().lower()
                if alias:
                    category_keywords[alias] = category_info

        # Fail if database has no category keywords configured
        if not category_keywords:
            raise RuntimeError(
                "No category keywords found in database. Run migrations to populate "
                "item_types.aliases column. Expected categories: bagel, omelette, "
                "dessert, coffee, etc."
            )

        self._category_keywords = category_keywords

        logger.debug(
            "Loaded %d category keywords from %d item_types",
            len(category_keywords),
            len(item_types),
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
        attributes = (
            db.query(ItemTypeAttribute)
            .join(ItemType)
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
        """
        from .models import GlobalAttribute, GlobalAttributeOption

        global_attribute_options: dict[str, list[dict]] = {}

        try:
            # Query all global attributes with their options
            attributes = db.query(GlobalAttribute).all()

            for attr in attributes:
                options = (
                    db.query(GlobalAttributeOption)
                    .filter(GlobalAttributeOption.global_attribute_id == attr.id)
                    .order_by(GlobalAttributeOption.display_order)
                    .all()
                )

                global_attribute_options[attr.slug] = [
                    {
                        "slug": opt.slug,
                        "display_name": opt.display_name,
                        "price_modifier": opt.price_modifier,
                        "iced_price_modifier": opt.iced_price_modifier,
                        "is_default": opt.is_default,
                        "is_available": opt.is_available,
                        "aliases": opt.aliases,  # Pipe-separated aliases for parsing
                        "must_match": opt.must_match,  # Required phrases for matching
                    }
                    for opt in options
                ]

            self._global_attribute_options = global_attribute_options

            logger.debug(
                "Loaded global attribute options for %d attributes",
                len(global_attribute_options),
            )
        except Exception as e:
            logger.warning("Could not load global attribute options: %s", e)
            self._global_attribute_options = {}

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

    def _build_keyword_indices(self) -> None:
        """Build keyword-to-item indices for partial matching."""
        # Words to skip in keyword indexing
        skip_words = {
            "cream", "cheese", "bagel", "sandwich", "the", "a", "an",
            "with", "and", "or", "on", "in",
        }

        # Build spread type keyword index
        self._spread_keyword_index = self._build_index(self._spread_types, skip_words)

        # Build bagel type keyword index
        self._bagel_keyword_index = self._build_index(self._bagel_types, skip_words)

        # Build menu item keyword index
        self._menu_item_keyword_index = self._build_index(self._known_menu_items, skip_words)

        logger.debug(
            "Built keyword indices: %d spread keywords, %d bagel keywords, %d menu keywords",
            len(self._spread_keyword_index),
            len(self._bagel_keyword_index),
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

    def get_spreads(self) -> set[str]:
        """Get base spread types (cream cheese, butter, etc.)."""
        return self._spreads.copy() if self._is_loaded else set()

    def get_spread_types(self) -> set[str]:
        """Get cream cheese variety types (scallion, honey walnut, etc.)."""
        return self._spread_types.copy() if self._is_loaded else set()

    def get_bagel_spreads(self) -> set[str]:
        """Get all spread patterns for matching in user input.

        Returns combined set of:
        - Base spreads (cream cheese, butter, etc.)
        - Spread types (scallion, honey walnut, etc.)
        - Combined patterns (scallion cream cheese, etc.)
        """
        return self._bagel_spreads.copy() if self._is_loaded else set()

    def get_bagel_types(self) -> set[str]:
        """Get bagel types (plain, everything, etc.) including aliases."""
        return self._bagel_types.copy() if self._is_loaded else set()

    def get_bagel_types_list(self) -> list[str]:
        """Get ordered list of bagel types for display/pagination."""
        return self._bagel_types_list.copy() if self._is_loaded else []

    def get_proteins(self) -> set[str]:
        """Get protein types (bacon, ham, etc.)."""
        return self._proteins.copy() if self._is_loaded else set()

    def get_toppings(self) -> set[str]:
        """Get topping types (tomato, onion, etc.)."""
        return self._toppings.copy() if self._is_loaded else set()

    def get_cheeses(self) -> set[str]:
        """Get cheese types (american, swiss, etc.)."""
        return self._cheeses.copy() if self._is_loaded else set()

    def get_coffee_types(self) -> set[str]:
        """Get coffee/tea beverage types."""
        return self._coffee_types.copy() if self._is_loaded else set()

    def get_soda_types(self) -> set[str]:
        """Get soda/bottled beverage types."""
        return self._soda_types.copy() if self._is_loaded else set()

    def get_beverage_milks(self) -> list[str]:
        """Get available milk options for beverages.

        Returns ordered list of milk display names from the database.
        """
        return self._beverage_milks.copy() if self._is_loaded else []

    def get_beverage_sweeteners(self) -> list[str]:
        """Get available sweetener options for beverages.

        Returns ordered list of sweetener display names from the database.
        """
        return self._beverage_sweeteners.copy() if self._is_loaded else []

    def get_beverage_syrups(self) -> list[str]:
        """Get available syrup/flavor options for beverages.

        Returns ordered list of syrup display names from the database.
        """
        return self._beverage_syrups.copy() if self._is_loaded else []

    def get_known_menu_items(self) -> set[str]:
        """Get all known menu item names."""
        return self._known_menu_items.copy() if self._is_loaded else set()

    def get_global_attribute_options(self, attr_slug: str) -> list[dict]:
        """Get options for a global attribute by slug.

        Args:
            attr_slug: The attribute slug (e.g., "shots", "size", "temperature")

        Returns:
            List of option dicts with keys: slug, display_name, price_modifier,
            iced_price_modifier, is_default, is_available, aliases.
            Returns empty list if attribute not found or cache not loaded.

        Example:
            >>> cache.get_global_attribute_options("shots")
            [
                {"slug": "single", "display_name": "Single", "price_modifier": 0.0, ...},
                {"slug": "double", "display_name": "Double", "price_modifier": 0.75, ...},
                ...
            ]
        """
        if not self._is_loaded:
            return []
        return self._global_attribute_options.get(attr_slug, [])

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
            Returns None if no match found.

        Example:
            >>> cache.resolve_option_by_alias("shots", "2")
            {"slug": "double", "display_name": "Double", "price_modifier": 0.75, ...}
            >>> cache.resolve_option_by_alias("shots", "double")
            {"slug": "double", "display_name": "Double", "price_modifier": 0.75, ...}
            >>> cache.resolve_option_by_alias("shots", "two")
            {"slug": "double", "display_name": "Double", "price_modifier": 0.75, ...}
        """
        if not self._is_loaded:
            return None

        options = self._global_attribute_options.get(attr_slug, [])
        if not options:
            return None

        input_lower = input_value.lower().strip()

        for opt in options:
            # Check exact slug match
            if opt["slug"].lower() == input_lower:
                return opt

            # Check aliases (pipe-separated)
            aliases = opt.get("aliases")
            if aliases:
                alias_list = [a.strip().lower() for a in aliases.split("|")]
                if input_lower in alias_list:
                    return opt

        return None

    def get_signature_item_aliases(self) -> dict[str, str]:
        """Get signature item alias mapping.

        Returns a dict mapping user input variations (aliases) to the actual
        menu item names in the database. This is used for recognizing orders
        like "bec", "bacon egg and cheese", "the classic", "the leo", etc.

        Returns:
            Dict mapping lowercase alias -> menu item name (with original casing).
            Returns empty dict if cache not loaded.
        """
        return self._signature_item_aliases.copy() if self._is_loaded else {}

    def get_by_pound_items(self) -> dict[str, list[str]]:
        """Get by-the-pound items organized by category.

        Returns a dict mapping category names (fish, spread, cheese, cold_cut, salad)
        to lists of item names available in that category.

        Returns:
            Dict mapping category -> list of item names.
            Returns empty dict if cache not loaded.

        Example:
            {
                "fish": ["Nova Scotia Salmon", "Whitefish Salad", "Sable", ...],
                "spread": ["Plain Cream Cheese", "Scallion Cream Cheese", ...],
            }
        """
        # Return deep copy to prevent mutation
        if not self._is_loaded:
            return {}
        return {k: list(v) for k, v in self._by_pound_items.items()}

    def get_by_pound_aliases(self) -> dict[str, tuple[str, str]]:
        """Get by-the-pound item alias mapping.

        Returns a dict mapping user input aliases to (canonical_name, category) tuples.
        This is used for recognizing by-pound orders like "lox", "nova", "whitefish".

        Returns:
            Dict mapping lowercase alias -> (canonical_name, category).
            Returns empty dict if cache not loaded.

        Example:
            {
                "lox": ("Nova Scotia Salmon", "fish"),
                "nova": ("Nova Scotia Salmon", "fish"),
                "scallion": ("Scallion Cream Cheese", "spread"),
            }
        """
        return self._by_pound_aliases.copy() if self._is_loaded else {}

    def get_by_pound_category_names(self) -> dict[str, str]:
        """Get by-the-pound category display names.

        Returns a dict mapping category slugs to human-readable display names.

        Returns:
            Dict mapping category slug -> display name.
            Returns empty dict if cache not loaded.

        Example:
            {
                "cheese": "cheeses",
                "cold_cut": "cold cuts",
                "fish": "smoked fish",
                "salad": "salads",
                "spread": "spreads",
            }
        """
        return self._by_pound_category_names.copy() if self._is_loaded else {}

    def find_by_pound_item(self, item_name: str) -> tuple[str, str] | None:
        """Find a by-pound item and its category by name or alias.

        Args:
            item_name: Item name or alias to look up (e.g., "lox", "nova", "whitefish salad")

        Returns:
            Tuple of (canonical_name, category) if found, None otherwise.
        """
        if not self._is_loaded:
            return None

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

        return None

    def get_bagel_only_types(self) -> set[str]:
        """Get bagel types that are NOT also spread types.

        These are unambiguous bagel types - when a user says "change it to plain",
        we know they mean the bagel type, not a spread type.

        Returns:
            Set of bagel types that don't exist as spread types.
        """
        if not self._is_loaded:
            return set()
        return self._bagel_types - self._spread_types

    def get_spread_only_types(self) -> set[str]:
        """Get spread types that are NOT also bagel types.

        These are unambiguous spread types - when a user says "change it to scallion",
        we know they mean the spread type, not a bagel type.

        Returns:
            Set of spread types that don't exist as bagel types.
        """
        if not self._is_loaded:
            return set()
        return self._spread_types - self._bagel_types

    def get_ambiguous_modifiers(self) -> set[str]:
        """Get types that are BOTH bagel types AND spread types.

        These are ambiguous - when a user says "change it to blueberry",
        we need to ask for clarification (blueberry bagel vs blueberry cream cheese).

        Returns:
            Set of types that exist as both bagel and spread types.
        """
        if not self._is_loaded:
            return set()
        return self._bagel_types & self._spread_types

    def resolve_coffee_alias(self, name: str) -> str:
        """
        Resolve a coffee/tea name or alias to its canonical menu item name.

        Args:
            name: User input like "matcha" or "latte"

        Returns:
            Canonical menu item name (e.g., "Seasonal Latte Matcha" for "matcha")
            or the original name if no mapping found.
        """
        if not self._is_loaded:
            return name
        name_lower = name.lower().strip()
        return self._coffee_alias_to_canonical.get(name_lower, name)

    def resolve_soda_alias(self, name: str) -> str:
        """
        Resolve a soda/beverage name or alias to its canonical menu item name.

        Args:
            name: User input like "coke" or "sprite"

        Returns:
            Canonical menu item name (e.g., "Coca-Cola" for "coke")
            or the original name if no mapping found.
        """
        if not self._is_loaded:
            return name
        name_lower = name.lower().strip()
        return self._soda_alias_to_canonical.get(name_lower, name)

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
            if no mapping found (graceful failure).

        Examples:
            >>> cache.normalize_modifier("lox")
            "Nova Scotia Salmon"
            >>> cache.normalize_modifier("veggie")
            "Vegetable Cream Cheese"
            >>> cache.normalize_modifier("unknown")
            "unknown"  # Returns original if not found
        """
        if not self._is_loaded:
            return modifier
        modifier_lower = modifier.lower().strip()
        return self._modifier_aliases.get(modifier_lower, modifier)

    def get_side_items(self) -> set[str]:
        """
        Get all known side item names and aliases (lowercase).

        Returns:
            Set of side item names and their aliases, all lowercase.
        """
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
            Returns None (not original) to allow graceful failure handling
            by the caller.

        Examples:
            >>> cache.resolve_side_alias("sausage")
            "Side of Sausage"
            >>> cache.resolve_side_alias("latke")
            "Side of Breakfast Latke"
            >>> cache.resolve_side_alias("unknown")
            None  # Not found - caller should handle gracefully
        """
        if not self._is_loaded:
            return None
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
            Returns None (not original) to allow graceful failure handling
            by the caller.

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
        if not self._is_loaded:
            return None
        name_lower = name.lower().strip()
        return self._menu_item_alias_to_canonical.get(name_lower)

    def get_abbreviations(self) -> dict[str, str]:
        """
        Get the abbreviation-to-canonical mapping.

        Returns:
            Dict mapping abbreviation (lowercase) to canonical name (lowercase).
            Example: {"cc": "cream cheese", "pb": "peanut butter"}
        """
        return self._abbreviations.copy() if self._is_loaded else {}

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
            Returns original text if cache not loaded.

        Examples:
            >>> cache.expand_abbreviations("strawberry cc")
            "strawberry cream cheese"
            >>> cache.expand_abbreviations("plain bagel with cc toasted")
            "plain bagel with cream cheese toasted"
            >>> cache.expand_abbreviations("I want a pb&j")  # no match for "pb&j"
            "I want a pb&j"
        """
        import re

        if not self._is_loaded or not self._abbreviations:
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
                "slug": str,          # The item_type slug (e.g., "dessert", "bagel")
                "expands_to": list | None,  # List of slugs to query (for meta-categories)
                "name_filter": str | None,  # Substring filter for item names (e.g., "tea")
            }
            Returns None if keyword not found.

        Examples:
            >>> cache.get_category_keyword_mapping("bagels")
            {"slug": "bagel", "expands_to": None, "name_filter": None}
            >>> cache.get_category_keyword_mapping("desserts")
            {"slug": "dessert", "expands_to": ["pastry", "snack"], "name_filter": None}
            >>> cache.get_category_keyword_mapping("teas")
            {"slug": "tea", "expands_to": ["sized_beverage"], "name_filter": "tea"}
            >>> cache.get_category_keyword_mapping("unknown")
            None
        """
        if not self._is_loaded:
            return None
        keyword_lower = keyword.lower().strip()
        return self._category_keywords.get(keyword_lower)

    def get_available_category_keywords(self) -> list[str]:
        """
        Get list of all available category keywords for error messages.

        Returns:
            Sorted list of all valid category keywords that can be used
            in menu/price queries.

        Example:
            >>> cache.get_available_category_keywords()
            ["bagels", "beverages", "coffees", "desserts", "drinks", ...]
        """
        if not self._is_loaded:
            return []
        return sorted(self._category_keywords.keys())

    # =========================================================================
    # Partial Matching Methods
    # =========================================================================

    def find_spread_matches(self, query: str) -> list[str]:
        """
        Find spread types that match a partial query.

        Args:
            query: User input like "walnut" or "honey walnut"

        Returns:
            List of matching spread types. Empty if no matches.
            Single item if exact match.
            Multiple items if disambiguation needed.

        Examples:
            >>> cache.find_spread_matches("walnut")
            ["honey walnut", "maple raisin walnut"]
            >>> cache.find_spread_matches("honey walnut")
            ["honey walnut"]
            >>> cache.find_spread_matches("scallion")
            ["scallion"]
        """
        query_lower = query.lower().strip()

        # Remove "cream cheese" from query if present
        query_lower = query_lower.replace("cream cheese", "").strip()

        if not query_lower:
            return []

        # Check for exact match first
        if query_lower in self._spread_types:
            return [query_lower]

        # Check keyword index for partial matches
        matches = set()
        for word in query_lower.split():
            if word in self._spread_keyword_index:
                matches.update(self._spread_keyword_index[word])

        # If no keyword matches, try substring matching
        if not matches:
            for spread_type in self._spread_types:
                if query_lower in spread_type or spread_type in query_lower:
                    matches.add(spread_type)

        return sorted(matches)

    def find_bagel_matches(self, query: str) -> list[str]:
        """
        Find bagel types that match a partial query.

        Args:
            query: User input like "cinnamon" or "whole wheat"

        Returns:
            List of matching bagel types.
        """
        query_lower = query.lower().strip()

        # Remove "bagel" from query if present
        query_lower = query_lower.replace("bagel", "").strip()

        if not query_lower:
            return []

        # Check for exact match first
        if query_lower in self._bagel_types:
            return [query_lower]

        # Check keyword index
        matches = set()
        for word in query_lower.split():
            if word in self._bagel_keyword_index:
                matches.update(self._bagel_keyword_index[word])

        # Substring matching
        if not matches:
            for bagel_type in self._bagel_types:
                if query_lower in bagel_type or bagel_type in query_lower:
                    matches.add(bagel_type)

        return sorted(matches)

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
            Returns empty list if item type not found or cache not loaded.

        Examples:
            >>> cache.get_item_type_fields("bagel")
            [
                {"field_name": "bagel_type", "display_order": 1, "required": True, ...},
                {"field_name": "toasted", "display_order": 2, "required": True, ...},
                ...
            ]
        """
        if not self._is_loaded:
            return []
        return self._item_type_fields.get(item_type_slug, [])

    def get_question_for_field(self, item_type_slug: str, field_name: str) -> str | None:
        """
        Get the question text for a specific field of an item type.

        Args:
            item_type_slug: The item type slug (e.g., "bagel", "sized_beverage")
            field_name: The field name (e.g., "toasted", "size")

        Returns:
            The question_text for the field, or None if not found.

        Examples:
            >>> cache.get_question_for_field("bagel", "toasted")
            "Would you like it toasted?"
            >>> cache.get_question_for_field("sized_beverage", "size")
            "What size?"
        """
        if not self._is_loaded:
            return None
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
            The cached menu index dict, or empty dict if not loaded.

        Note:
            This returns the cached index built at startup. The index is
            expensive to build (~55 seconds with N+1 queries) so we cache
            it rather than building on every request.
        """
        if not self._is_loaded:
            return {}
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
            Set of patterns for the type, or empty set if not found.

        Examples:
            >>> cache.get_response_patterns("affirmative")
            {"yes", "yeah", "yep", "sure", "ok", ...}
        """
        if not self._is_loaded:
            return set()
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

        Examples:
            >>> cache.is_response_type("yes", "affirmative")
            True
            >>> cache.is_response_type("no thanks", "negative")
            True
        """
        if not self._is_loaded:
            return False
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
            Returns empty dict if cache not loaded.

        Example:
            {
                "extra": {"normalized_form": "extra", "category": "amount"},
                "lots of": {"normalized_form": "extra", "category": "amount"},
                "on the side": {"normalized_form": "on the side", "category": "position"},
            }
        """
        if not self._is_loaded:
            return {}
        return self._modifier_qualifiers.copy()

    def get_qualifier_patterns(self) -> list[str]:
        """
        Get all qualifier patterns sorted by length (longest first).

        This ordering is important for matching - longer patterns like
        "a little bit of" should be matched before shorter patterns like "little".

        Returns:
            List of patterns sorted by length descending.
        """
        if not self._is_loaded:
            return []
        return sorted(self._modifier_qualifiers.keys(), key=len, reverse=True)

    def get_qualifier_patterns_by_category(self, category: str) -> set[str]:
        """
        Get all qualifier patterns for a specific category.

        Args:
            category: The category (amount, position, preparation)

        Returns:
            Set of patterns for the category.
        """
        if not self._is_loaded:
            return set()
        return self._qualifier_patterns_by_category.get(category, set()).copy()

    def get_qualifier_info(self, pattern: str) -> dict | None:
        """
        Get info for a specific qualifier pattern.

        Args:
            pattern: The pattern to look up (e.g., "extra", "on the side")

        Returns:
            Dict with {normalized_form, category} or None if not found.
        """
        if not self._is_loaded:
            return None
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

    def get_status(self) -> dict[str, Any]:
        """Get cache status information."""
        return {
            "is_loaded": self._is_loaded,
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
            "counts": {
                "spreads": len(self._spreads),
                "spread_types": len(self._spread_types),
                "bagel_spreads": len(self._bagel_spreads),
                "bagel_types": len(self._bagel_types),
                "proteins": len(self._proteins),
                "toppings": len(self._toppings),
                "cheeses": len(self._cheeses),
                "coffee_types": len(self._coffee_types),
                "soda_types": len(self._soda_types),
                "known_menu_items": len(self._known_menu_items),
                "by_pound_categories": len(self._by_pound_items),
                "by_pound_aliases": len(self._by_pound_aliases),
                "item_type_fields": sum(len(fields) for fields in self._item_type_fields.values()),
                "response_patterns": sum(len(p) for p in self._response_patterns.values()),
                "modifier_qualifiers": len(self._modifier_qualifiers),
            },
            "keyword_indices": {
                "spread_keywords": len(self._spread_keyword_index),
                "bagel_keywords": len(self._bagel_keyword_index),
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
                    self.load_from_db(db, fail_on_error=False)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in background cache refresh: %s", e)
                # Wait an hour before retrying on error
                await asyncio.sleep(3600)


# Global singleton instance
menu_cache = MenuDataCache()
