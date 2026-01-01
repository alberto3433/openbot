"""
Menu Lookup Engine for Order Items.

This module handles all menu item lookups and searching, including
fuzzy matching, category inference, and suggestion generation.

Extracted from state_machine.py for better separation of concerns.
"""

import logging

from .parsers.constants import normalize_for_match

logger = logging.getLogger(__name__)


class MenuLookup:
    """
    Handles menu item lookups and searching.

    Provides fuzzy matching, plural/singular handling, category inference,
    and helpful suggestion generation when items aren't found.
    """

    # Categories to search when looking up items
    CATEGORIES_TO_SEARCH = [
        "signature_sandwiches", "signature_bagels", "signature_omelettes",
        "sides", "drinks", "desserts", "other",
        "custom_sandwiches", "custom_bagels",
    ]

    # Known drink synonyms/brands - map generic terms to brand keywords
    DRINK_SYNONYMS = {
        "orange juice": ["tropicana", "fresh squeezed"],
        "oj": ["orange juice", "tropicana", "fresh squeezed"],
        "apple juice": ["martinelli"],
        "lemonade": ["minute maid"],
    }

    # Category keyword mappings for inference
    CATEGORY_KEYWORDS = {
        "drinks": [
            "juice", "coffee", "tea", "latte", "cappuccino", "espresso",
            "soda", "coke", "pepsi", "sprite", "water", "smoothie",
            "milk", "chocolate milk", "hot chocolate", "mocha",
            "drink", "beverage", "lemonade", "iced", "frappe",
        ],
        "sides": [
            "hash", "hashbrown", "fries", "tots", "bacon", "sausage",
            "egg", "eggs", "fruit", "salad", "side", "toast",
            "home fries", "potatoes", "pancake", "waffle",
        ],
        "signature_bagels": [
            "bagel", "everything", "plain", "sesame", "poppy",
            "cinnamon", "raisin", "onion", "pumpernickel", "whole wheat",
        ],
        "signature_omelettes": [
            "sandwich", "omelette", "omelet", "wrap", "panini",
            "club", "blt", "reuben",
        ],
        "desserts": [
            "cookie", "brownie", "muffin", "cake", "pastry",
            "donut", "doughnut", "dessert", "sweet",
        ],
    }

    # Friendly names for categories
    CATEGORY_DISPLAY_NAMES = {
        "drinks": "drinks",
        "sides": "sides",
        "signature_bagels": "bagels",
        "signature_omelettes": "sandwiches and omelettes",
        "desserts": "desserts",
    }

    # Map categories to item_type slugs for items_by_type lookup
    CATEGORY_TYPE_MAP = {
        "sides": ["side"],
        "drinks": ["drink", "coffee", "soda", "sized_beverage", "beverage"],
        "desserts": ["dessert", "pastry", "snack"],
    }

    def __init__(self, menu_data: dict | None):
        """
        Initialize the menu lookup engine.

        Args:
            menu_data: Menu data dictionary containing items by category.
        """
        self._menu_data = menu_data or {}

    @property
    def menu_data(self) -> dict:
        """Get current menu data."""
        return self._menu_data

    @menu_data.setter
    def menu_data(self, value: dict | None):
        """Update menu data."""
        self._menu_data = value or {}

    def _get_all_items(self) -> list[dict]:
        """
        Collect all items from all categories in menu data.

        Returns:
            List of all menu item dicts.
        """
        all_items = []

        for category in self.CATEGORIES_TO_SEARCH:
            all_items.extend(self._menu_data.get(category, []))

        # Also include items_by_type
        items_by_type = self._menu_data.get("items_by_type", {})
        for type_slug, items in items_by_type.items():
            all_items.extend(items)

        return all_items

    def _get_search_variants(self, item_name: str) -> list[str]:
        """
        Generate search variants to handle singular/plural variations.

        Args:
            item_name: The name to generate variants for.

        Returns:
            List of search variants (lowercase).
        """
        item_name_lower = item_name.lower()
        search_variants = [item_name_lower]

        # Handle singular/plural variations
        # e.g., "cookies" should match "cookie", "bagels" should match "bagel"
        if item_name_lower.endswith('ies'):
            # Try both transformations:
            # 1. "ladies" -> "lady" (y -> ies rule)
            # 2. "cookies" -> "cookie" (just -s, the "ie" is part of the word)
            search_variants.append(item_name_lower[:-3] + 'y')  # ladies -> lady
            search_variants.append(item_name_lower[:-1])  # cookies -> cookie
        elif item_name_lower.endswith('es'):
            # dishes -> dish
            search_variants.append(item_name_lower[:-2])
        elif item_name_lower.endswith('s') and len(item_name_lower) > 2:
            # bagels -> bagel
            search_variants.append(item_name_lower[:-1])

        return search_variants

    def lookup_menu_item(self, item_name: str) -> dict | None:
        """
        Look up a menu item by name from the menu data.

        Args:
            item_name: Name of the item to find (case-insensitive fuzzy match)

        Returns:
            Menu item dict with id, name, base_price, etc. or None if not found
        """
        if not self._menu_data:
            return None

        search_variants = self._get_search_variants(item_name)
        all_items = self._get_all_items()

        # Pass 1: Exact match (highest priority)
        for variant in search_variants:
            for item in all_items:
                if item.get("name", "").lower() == variant:
                    return item

        # Pass 2: Search term is contained in item name
        # e.g., searching "chipotle" finds "The Chipotle Egg Omelette"
        # Also handles "cookies" matching "Chocolate Chip Cookie" via search_variants
        # Prefer shorter item names (more specific match)
        matches = []
        for variant in search_variants:
            for item in all_items:
                item_name_db = item.get("name", "").lower()
                if variant in item_name_db:
                    matches.append(item)
        if matches:
            # Return the shortest matching name (most specific)
            return min(matches, key=lambda x: len(x.get("name", "")))

        # Pass 3: Item name is contained in search term
        # e.g., searching "The Chipotle Egg Omelette" finds item named "Chipotle Egg Omelette"
        # Prefer LONGER item names (more complete match)
        matches = []
        for variant in search_variants:
            for item in all_items:
                item_name_db = item.get("name", "").lower()
                if item_name_db in variant:
                    matches.append(item)
        if matches:
            # Return the longest matching name (most complete)
            return max(matches, key=lambda x: len(x.get("name", "")))

        # Pass 4: Normalized matching
        # Handles "blue berry" matching "blueberry", "black and white" matching "black & white"
        matches = []
        for variant in search_variants:
            variant_compact = normalize_for_match(variant)
            for item in all_items:
                item_name_db = item.get("name", "").lower()
                item_name_db_compact = normalize_for_match(item_name_db)
                # Check if compact search term is in compact item name or vice versa
                if variant_compact in item_name_db_compact or item_name_db_compact in variant_compact:
                    matches.append(item)
        if matches:
            # Return the shortest matching name (most specific)
            return min(matches, key=lambda x: len(x.get("name", "")))

        return None

    def lookup_menu_items(self, item_name: str) -> list[dict]:
        """
        Look up ALL menu items matching a name from the menu data.

        Unlike lookup_menu_item which returns only the best match, this returns
        ALL items that match the search term. Used for disambiguation when
        multiple items match (e.g., "orange juice" matches 3 different OJ types).

        Args:
            item_name: Name of the item to find (case-insensitive fuzzy match)

        Returns:
            List of menu item dicts with id, name, base_price, etc.
        """
        if not self._menu_data:
            return []

        item_name_lower = item_name.lower()

        # Build list of search terms (original + singular/plural variants + any synonyms)
        search_terms = self._get_search_variants(item_name_lower)
        for generic_term, synonyms in self.DRINK_SYNONYMS.items():
            if generic_term in item_name_lower:
                search_terms.extend(synonyms)

        all_items = self._get_all_items()

        # Deduplicate by item name (some items appear in multiple categories)
        seen_names = set()
        unique_items = []
        for item in all_items:
            name = item.get("name", "").lower()
            if name not in seen_names:
                seen_names.add(name)
                unique_items.append(item)
        all_items = unique_items

        # Pass 1: Search term (or synonyms) is contained in item name
        # e.g., "orange juice" finds "Tropicana Orange Juice", "Fresh Squeezed Orange Juice"
        # Also "tropicana" (synonym) finds "Tropicana Orange Juice No Pulp"
        matches = []
        matched_names = set()
        for item in all_items:
            item_name_db = item.get("name", "").lower()
            for search_term in search_terms:
                if search_term in item_name_db and item_name_db not in matched_names:
                    matches.append(item)
                    matched_names.add(item_name_db)
                    break
        if matches:
            # Sort by name length (shortest first = more specific)
            return sorted(matches, key=lambda x: len(x.get("name", "")))

        # Pass 2: Item name is contained in search term
        # e.g., "tropicana orange juice" finds "Tropicana"
        matches = []
        for item in all_items:
            item_name_db = item.get("name", "").lower()
            if item_name_db in item_name_lower:
                matches.append(item)
        if matches:
            # Sort by name length (longest first = more complete match)
            return sorted(matches, key=lambda x: len(x.get("name", "")), reverse=True)

        # Pass 3: Normalized matching
        # Handles "blue berry" matching "blueberry", "black and white" matching "black & white"
        item_name_compact = normalize_for_match(item_name_lower)
        matches = []
        for item in all_items:
            item_name_db = item.get("name", "").lower()
            item_name_db_compact = normalize_for_match(item_name_db)
            if item_name_compact in item_name_db_compact or item_name_db_compact in item_name_compact:
                matches.append(item)
        if matches:
            return sorted(matches, key=lambda x: len(x.get("name", "")))

        return []

    def infer_item_category(self, item_name: str) -> str | None:
        """
        Infer the likely category of an unknown item based on keywords.

        Args:
            item_name: The name of the item the user requested

        Returns:
            Category key like "drinks", "sides", "signature_bagels", or None if unclear
        """
        name_lower = item_name.lower()

        for category, keywords in self.CATEGORY_KEYWORDS.items():
            if any(kw in name_lower for kw in keywords):
                return category

        return None

    def get_category_suggestions(self, category: str, limit: int = 5) -> str:
        """
        Get a formatted string of menu suggestions from a category.

        Args:
            category: The menu category key (e.g., "drinks", "sides")
            limit: Maximum number of suggestions to include

        Returns:
            Formatted string like "home fries, fruit cup, or a side of bacon"
        """
        if not self._menu_data:
            return ""

        items = self._menu_data.get(category, [])

        # If no items in direct category, try items_by_type
        if not items and category in self.CATEGORY_TYPE_MAP:
            items_by_type = self._menu_data.get("items_by_type", {})
            for type_slug in self.CATEGORY_TYPE_MAP.get(category, []):
                items.extend(items_by_type.get(type_slug, []))

        if not items:
            return ""

        # Get unique item names, limited to the specified count
        item_names = []
        seen = set()
        for item in items:
            name = item.get("name", "")
            if name and name.lower() not in seen:
                seen.add(name.lower())
                item_names.append(name)
                if len(item_names) >= limit:
                    break

        if not item_names:
            return ""

        # Format as natural language list
        if len(item_names) == 1:
            return item_names[0]
        elif len(item_names) == 2:
            return f"{item_names[0]} or {item_names[1]}"
        else:
            return ", ".join(item_names[:-1]) + f", or {item_names[-1]}"

    def get_not_found_message(self, item_name: str) -> tuple[str, str | None]:
        """
        Generate a helpful message when an item isn't found on the menu.

        Infers the category and suggests alternatives.

        Args:
            item_name: The name of the item the user requested

        Returns:
            Tuple of (message, category_for_followup).
            category_for_followup is set when the message asks "Would you like to hear what X we have?"
            so the caller can track state for a "yes" follow-up.
        """
        category = self.infer_item_category(item_name)

        if category:
            suggestions = self.get_category_suggestions(category, limit=4)
            category_name = self.CATEGORY_DISPLAY_NAMES.get(category, "items")

            if suggestions:
                # We already gave suggestions, no need to track follow-up
                return (
                    f"I'm sorry, we don't have {item_name}. "
                    f"For {category_name}, we have {suggestions}. "
                    f"Would any of those work?",
                    None,
                )
            else:
                # Return the category so caller can track state for "yes" follow-up
                return (
                    f"I'm sorry, we don't have {item_name}. "
                    f"Would you like to hear what {category_name} we have?",
                    category,
                )
        else:
            # Generic fallback
            return (
                f"I'm sorry, I couldn't find '{item_name}' on our menu. "
                f"Could you try again or ask what we have available?",
                None,
            )
