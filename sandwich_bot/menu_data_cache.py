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
from datetime import datetime, time
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

        # Alias-to-canonical name mappings (for resolving user input to menu item names)
        self._coffee_alias_to_canonical: dict[str, str] = {}
        self._soda_alias_to_canonical: dict[str, str] = {}
        self._speed_menu_bagels: dict[str, str] = {}  # alias -> menu item name
        self._modifier_aliases: dict[str, str] = {}  # alias -> Ingredient.name (canonical)

        # By-the-pound items
        self._by_pound_items: dict[str, list[str]] = {}  # category -> list of item names
        self._by_pound_aliases: dict[str, tuple[str, str]] = {}  # alias -> (canonical_name, category)
        self._by_pound_category_names: dict[str, str] = {}  # slug -> display_name

        # Keyword indices for partial matching
        self._spread_keyword_index: dict[str, list[str]] = {}
        self._bagel_keyword_index: dict[str, list[str]] = {}
        self._menu_item_keyword_index: dict[str, list[str]] = {}

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
                self._load_known_menu_items(db)
                self._load_speed_menu_bagels(db)
                self._load_by_pound_items(db)
                self._load_by_pound_category_names(db)
                self._load_modifier_aliases(db)

                # Build keyword indices for partial matching
                self._build_keyword_indices()

                self._last_refresh = datetime.now()
                self._is_loaded = True

                logger.info(
                    "Menu data cache loaded: %d spread_types, %d bagel_types, "
                    "%d proteins, %d toppings, %d cheeses, %d coffee_types, "
                    "%d soda_types, %d menu_items, %d speed_menu_aliases, "
                    "%d by_pound_categories",
                    len(self._spread_types),
                    len(self._bagel_types),
                    len(self._proteins),
                    len(self._toppings),
                    len(self._cheeses),
                    len(self._coffee_types),
                    len(self._soda_types),
                    len(self._known_menu_items),
                    len(self._speed_menu_bagels),
                    len(self._by_pound_items),
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

        Uses item_type='sized_beverage' to identify coffee/tea drinks that need
        configuration (size, hot/iced).

        Includes both item names and their aliases for matching user input.
        Also builds a mapping from aliases to canonical names.
        """
        from .models import MenuItem, ItemType

        coffee_types = set()
        alias_to_canonical = {}

        # Query sized_beverage items (coffee/tea that need configuration)
        coffee_items = (
            db.query(MenuItem)
            .join(ItemType, MenuItem.item_type_id == ItemType.id)
            .filter(ItemType.slug == "sized_beverage")
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

    def _load_known_menu_items(self, db: Session) -> None:
        """Load all menu item names for recognition."""
        from .models import MenuItem

        menu_items = set()

        all_items = db.query(MenuItem).all()
        for item in all_items:
            menu_items.add(item.name.lower())
            # Also add without "The " prefix for matching
            name_lower = item.name.lower()
            if name_lower.startswith("the "):
                menu_items.add(name_lower[4:])

        self._known_menu_items = menu_items

    def _load_speed_menu_bagels(self, db: Session) -> None:
        """Load speed menu bagel aliases from signature items.

        Builds a mapping from user input variations (aliases) to the actual
        menu item names in the database. This replaces the hardcoded
        SPEED_MENU_BAGELS constant.

        The mapping is used for recognizing orders like "bec", "bacon egg and cheese",
        "the classic", etc. and resolving them to actual menu items.
        """
        from .models import MenuItem

        speed_menu_bagels: dict[str, str] = {}

        # Query signature items with aliases
        # Only signature items should be in the speed menu mapping
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
                    speed_menu_bagels[alias] = canonical_name

            # Also add variations of the item name itself
            name_lower = item.name.lower()
            speed_menu_bagels[name_lower] = canonical_name

            # Add without "The " prefix if present
            if name_lower.startswith("the "):
                speed_menu_bagels[name_lower[4:]] = canonical_name

        self._speed_menu_bagels = speed_menu_bagels

        logger.debug(
            "Loaded %d speed menu bagel aliases from %d items",
            len(speed_menu_bagels),
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

        This replaces the hardcoded BY_POUND_CATEGORY_NAMES constant.
        """
        category_names: dict[str, str] = {}

        # Query the by_pound_categories table
        result = db.execute(
            __import__("sqlalchemy").text(
                "SELECT slug, display_name FROM by_pound_categories"
            )
        )

        for row in result:
            category_names[row.slug] = row.display_name

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

    def get_known_menu_items(self) -> set[str]:
        """Get all known menu item names."""
        return self._known_menu_items.copy() if self._is_loaded else set()

    def get_speed_menu_bagels(self) -> dict[str, str]:
        """Get speed menu bagel alias mapping.

        Returns a dict mapping user input variations (aliases) to the actual
        menu item names in the database. This is used for recognizing orders
        like "bec", "bacon egg and cheese", "the classic", etc.

        Returns:
            Dict mapping lowercase alias -> menu item name (with original casing).
            Returns empty dict if cache not loaded.
        """
        return self._speed_menu_bagels.copy() if self._is_loaded else {}

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
