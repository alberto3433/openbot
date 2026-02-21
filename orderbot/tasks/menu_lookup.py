"""
Menu Lookup Engine for Order Items.

This module handles all menu item lookups and searching, including
fuzzy matching, category inference, and suggestion generation.

Extracted from state_machine.py for better separation of concerns.
"""

import logging

from .normalization import normalize_for_match
from .mixins import MenuDataMixin
from .utils.text import format_english_list, normalize_text, word_boundary_match
from orderbot.cache import menu_cache
from orderbot.cache.base import get_singular_plural_variants

logger = logging.getLogger(__name__)


class MenuLookup(MenuDataMixin):
    """
    Handles menu item lookups and searching.

    Provides fuzzy matching, plural/singular handling, category inference,
    and helpful suggestion generation when items aren't found.

    Category inference and display names are loaded from the database via
    menu_cache, eliminating the need for hardcoded keyword mappings.
    """

    def __init__(self, menu_data: dict | None):
        """
        Initialize the menu lookup engine.

        Args:
            menu_data: Menu data dictionary containing items by category.
        """
        self._menu_data = menu_data or {}

    def _get_all_items(self) -> list[dict]:
        """
        Collect all items from all item types in menu data.

        Returns:
            List of all menu item dicts.
        """
        all_items = []

        # Use items_by_type (data-driven from database)
        items_by_type = self._menu_data.get("items_by_type", {})
        for type_slug, items in items_by_type.items():
            if isinstance(items, list):
                all_items.extend(items)

        return all_items

    def _get_search_variants(self, item_name: str) -> list[str]:
        """
        Generate search variants to handle singular/plural variations.

        Uses the centralized get_singular_plural_variants function from cache/base.py
        which handles irregular plurals correctly via the inflect library.

        Args:
            item_name: The name to generate variants for.

        Returns:
            List of search variants (lowercase).
        """
        return get_singular_plural_variants(item_name)

    def _passes_match_filter(self, item: dict, user_input: str) -> bool:
        """
        Check if an item passes its required_match_phrases filter.

        If the item has required_match_phrases set, the user's input must contain
        at least ONE of the comma-separated phrases for the item to match.

        Args:
            item: Menu item dict (must have 'required_match_phrases' key)
            user_input: The user's search input (lowercase)

        Returns:
            True if the item passes the filter (or has no filter), False otherwise.

        Example:
            Item: "Russian Coffee Cake" with required_match_phrases="coffee cake, cake"
            - user_input="coffee" -> False (doesn't contain "coffee cake" OR "cake")
            - user_input="coffee cake" -> True (contains "coffee cake")
            - user_input="cake" -> True (contains "cake")
        """
        required_phrases = item.get("required_match_phrases")

        # No filter set - item passes
        if not required_phrases:
            return True

        user_input_lower = user_input.lower()

        # Parse comma-separated phrases and check if user input contains at least one
        phrases = [normalize_text(p) for p in required_phrases.split(",") if p.strip()]
        for phrase in phrases:
            if phrase in user_input_lower:
                return True

        # None of the required phrases found in user input
        return False

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
        # No filter applied - if user types exact name, they want that item
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
                    # Check required_match_phrases filter
                    if self._passes_match_filter(item, item_name):
                        matches.append(item)
        if matches:
            # Return the shortest matching name (most specific)
            return min(matches, key=lambda x: len(x.get("name", "")))

        # Pass 3: Item name is contained in search term
        # e.g., searching "The Chipotle Egg Omelette" finds item named "Chipotle Egg Omelette"
        # Prefer LONGER item names (more complete match)
        # IMPORTANT: Require minimum similarity to prevent false matches like "ham" in "hamburger"
        matches = []
        for variant in search_variants:
            for item in all_items:
                item_name_db = item.get("name", "").lower()
                if item_name_db in variant:
                    # Compute similarity ratio: item name length / search term length
                    # Require at least 50% overlap to prevent false positives
                    # e.g., "ham" (3) in "hamburger" (9) = 0.33 -> rejected
                    # e.g., "chipotle egg omelette" (21) in "the chipotle egg omelette" (25) = 0.84 -> OK
                    match_ratio = len(item_name_db) / len(variant) if variant else 0
                    if match_ratio < 0.5:
                        logger.debug(
                            "Pass 3 reject: item '%s' (%d) in search '%s' (%d), ratio=%.2f",
                            item_name_db, len(item_name_db), variant, len(variant), match_ratio
                        )
                        continue
                    # Check required_match_phrases filter
                    if self._passes_match_filter(item, item_name):
                        matches.append(item)
        if matches:
            # Return the longest matching name (most complete)
            return max(matches, key=lambda x: len(x.get("name", "")))

        # Pass 4: Normalized matching
        # Handles "blue berry" matching "blueberry", "black and white" matching "black & white"
        # Also applies similarity threshold for reverse matches (item in search term)
        matches = []
        for variant in search_variants:
            variant_compact = normalize_for_match(variant)
            for item in all_items:
                item_name_db = item.get("name", "").lower()
                item_name_db_compact = normalize_for_match(item_name_db)

                # Case 1: Search term is in item name (e.g., "blueberry" in "Blueberry Muffin")
                if variant_compact in item_name_db_compact:
                    if self._passes_match_filter(item, item_name):
                        matches.append(item)
                # Case 2: Item name is in search term - apply similarity threshold
                elif item_name_db_compact in variant_compact:
                    # Require at least 50% overlap to prevent false positives
                    match_ratio = len(item_name_db_compact) / len(variant_compact) if variant_compact else 0
                    if match_ratio >= 0.5:
                        if self._passes_match_filter(item, item_name):
                            matches.append(item)
                    else:
                        logger.debug(
                            "Pass 4 reject: item '%s' in search '%s', ratio=%.2f",
                            item_name_db_compact, variant_compact, match_ratio
                        )
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

        # Build list of search terms (original + singular/plural variants)
        # Synonyms are handled via MenuItem.aliases in the database
        search_terms = self._get_search_variants(item_name_lower)

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

        # Pass 1a: Word-boundary matching for short search terms
        # Uses \b word boundaries to avoid false positives like "tea" matching "Cheesesteak"
        # This ensures "tea" only matches items with "tea" as a complete word
        matches = []
        matched_names = set()
        for item in all_items:
            item_name_db = item.get("name", "")
            item_name_db_lower = item_name_db.lower()
            for search_term in search_terms:
                if word_boundary_match(search_term, item_name_db, case_insensitive=True):
                    if item_name_db_lower not in matched_names:
                        if self._passes_match_filter(item, item_name):
                            matches.append(item)
                            matched_names.add(item_name_db_lower)
                    break
        if matches:
            # Sort by name length (shortest first = more specific)
            return sorted(matches, key=lambda x: len(x.get("name", "")))

        # Pass 1b: Substring matching for longer search terms (fallback)
        # e.g., "orange juice" finds "Tropicana Orange Juice", "Fresh Squeezed Orange Juice"
        # Only used if word-boundary matching didn't find anything
        matches = []
        matched_names = set()
        for item in all_items:
            item_name_db = item.get("name", "").lower()
            for search_term in search_terms:
                if search_term in item_name_db and item_name_db not in matched_names:
                    # Check required_match_phrases filter
                    if self._passes_match_filter(item, item_name):
                        matches.append(item)
                        matched_names.add(item_name_db)
                    break
        if matches:
            # Sort by name length (shortest first = more specific)
            return sorted(matches, key=lambda x: len(x.get("name", "")))

        # Pass 2: Item name is contained in search term
        # e.g., "tropicana orange juice" finds "Tropicana"
        # IMPORTANT: Require minimum similarity to prevent false matches like "ham" in "hamburger"
        matches = []
        for item in all_items:
            item_name_db = item.get("name", "").lower()
            if item_name_db in item_name_lower:
                # Compute similarity ratio: require at least 50% overlap
                match_ratio = len(item_name_db) / len(item_name_lower) if item_name_lower else 0
                if match_ratio < 0.5:
                    logger.debug(
                        "lookup_menu_items Pass 2 reject: item '%s' in search '%s', ratio=%.2f",
                        item_name_db, item_name_lower, match_ratio
                    )
                    continue
                # Check required_match_phrases filter
                if self._passes_match_filter(item, item_name):
                    matches.append(item)
        if matches:
            # Sort by name length (longest first = more complete match)
            return sorted(matches, key=lambda x: len(x.get("name", "")), reverse=True)

        # Pass 3: Normalized matching
        # Handles "blue berry" matching "blueberry", "black and white" matching "black & white"
        # Also applies similarity threshold for reverse matches
        item_name_compact = normalize_for_match(item_name_lower)
        matches = []
        for item in all_items:
            item_name_db = item.get("name", "").lower()
            item_name_db_compact = normalize_for_match(item_name_db)

            # Case 1: Search term is in item name - no threshold needed
            if item_name_compact in item_name_db_compact:
                if self._passes_match_filter(item, item_name):
                    matches.append(item)
            # Case 2: Item name is in search term - apply similarity threshold
            elif item_name_db_compact in item_name_compact:
                match_ratio = len(item_name_db_compact) / len(item_name_compact) if item_name_compact else 0
                if match_ratio >= 0.5:
                    if self._passes_match_filter(item, item_name):
                        matches.append(item)
                else:
                    logger.debug(
                        "lookup_menu_items Pass 3 reject: item '%s' in search '%s', ratio=%.2f",
                        item_name_db_compact, item_name_compact, match_ratio
                    )
        if matches:
            return sorted(matches, key=lambda x: len(x.get("name", "")))

        return []

    def find_similar_item_with_modifier(
        self,
        current_name: str,
        modifier: str,
    ) -> dict | None:
        """
        Find a menu item similar to current_name but including the modifier.

        Uses name similarity heuristic: both items should share significant words.
        Example: "Hot Tea" -> "Iced Tea" (both contain "Tea")

        Args:
            current_name: Name of the current menu item (e.g., "Hot Tea")
            modifier: The modifier to look for (e.g., "iced")

        Returns:
            Menu item dict if a similar item with the modifier is found, None otherwise
        """
        if not self._menu_data or not current_name or not modifier:
            return None

        all_items = self._get_all_items()
        current_words = set(current_name.lower().split())
        modifier_lower = modifier.lower()

        # Remove common filler words that don't help with matching
        filler_words = {"a", "an", "the", "of", "with", "and", "or"}
        current_words_clean = current_words - filler_words - {modifier_lower}

        best_match = None
        best_score = 0

        for item in all_items:
            item_name = item.get("name", "")
            item_name_lower = item_name.lower()

            # Skip current item (exact match)
            if item_name_lower == current_name.lower():
                continue

            # Item must contain the modifier (the thing user asked for)
            if modifier_lower not in item_name_lower:
                continue

            # Calculate word overlap (excluding the modifier and filler words)
            item_words = set(item_name_lower.split())
            item_words_clean = item_words - filler_words - {modifier_lower}

            overlap = len(item_words_clean & current_words_clean)

            # Require at least 1 shared meaningful word
            if overlap > best_score:
                best_score = overlap
                best_match = item

        return best_match if best_score > 0 else None

    def infer_item_type(self, item_name: str) -> dict | None:
        """
        Infer the likely item type of an unknown item based on keywords.

        Uses database-driven category keywords loaded via menu_cache.

        Args:
            item_name: The name of the item the user requested

        Returns:
            Dict with item type info if a keyword matches:
            {
                "slug": str,                    # The item_type slug
                "display_name": str,            # Singular display name
                "display_name_plural": str,     # Plural display name
                "lookup_type": str,             # "item_type" or "category"
            }
            Returns None if no keyword matches.
        """
        return menu_cache.infer_item_type_from_text(item_name)

    def get_items_for_item_type(self, item_type_slug: str) -> list[dict]:
        """
        Get all menu items for an item type.

        Args:
            item_type_slug: The item type slug (e.g., "sized_beverage", "side", "bagel")

        Returns:
            List of menu item dicts with name, base_price, etc.
        """
        if not self._menu_data:
            return []

        items_by_type = self._menu_data.get("items_by_type", {})
        return items_by_type.get(item_type_slug, [])

    def get_suggestions_for_item_type(self, item_type_slug: str, limit: int = 5) -> str:
        """
        Get a formatted string of menu suggestions for an item type.

        Uses items_by_type from menu_data for database-driven suggestions.

        Args:
            item_type_slug: The item type slug (e.g., "sized_beverage", "side", "bagel")
            limit: Maximum number of suggestions to include

        Returns:
            Formatted string like "home fries, fruit cup, or a side of bacon"
        """
        if not self._menu_data:
            return ""

        items_by_type = self._menu_data.get("items_by_type", {})
        items = items_by_type.get(item_type_slug, [])

        # If no items found directly, check if this is a category (lookup via join table)
        if not items:
            type_info = menu_cache.get_category_keyword_mapping(item_type_slug)
            if type_info and type_info.get("lookup_type") == "category":
                items = menu_cache.get_items_by_category(item_type_slug)

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
        return format_english_list(item_names, conjunction="or")

    def get_suggestion_names_for_item_type(self, item_type_slug: str, limit: int = 5) -> list[str]:
        """Get a list of menu item names for an item type (for quick replies).

        Same logic as get_suggestions_for_item_type but returns the raw list.
        """
        if not self._menu_data:
            return []

        items_by_type = self._menu_data.get("items_by_type", {})
        items = items_by_type.get(item_type_slug, [])

        if not items:
            type_info = menu_cache.get_category_keyword_mapping(item_type_slug)
            if type_info and type_info.get("lookup_type") == "category":
                items = menu_cache.get_items_by_category(item_type_slug)

        if not items:
            return []

        item_names = []
        seen = set()
        for item in items:
            name = item.get("name", "")
            if name and name.lower() not in seen:
                seen.add(name.lower())
                item_names.append(name)
                if len(item_names) >= limit:
                    break

        return item_names

    def get_not_found_message(self, item_name: str) -> tuple[str, str | None]:
        """
        Generate a helpful message when an item isn't found on the menu.

        Infers the item type and suggests alternatives using database-driven
        category keywords and display names.

        Args:
            item_name: The name of the item the user requested

        Returns:
            Tuple of (message, item_type_slug_for_followup).
            item_type_slug_for_followup is set when the message asks "Would you like
            to hear what X we have?" so the caller can track state for a "yes" follow-up.
        """
        type_info = self.infer_item_type(item_name)

        if type_info:
            item_type_slug = type_info["slug"]
            suggestions = self.get_suggestions_for_item_type(item_type_slug, limit=4)
            category_name = type_info.get("display_name_plural") or type_info.get("display_name", "items")

            if suggestions:
                # We already gave suggestions, no need to track follow-up
                return (
                    f"I'm sorry, we don't have {item_name}. "
                    f"For {category_name}, we have {suggestions}. "
                    f"Would any of those work?",
                    None,
                )
            else:
                # Return the item_type_slug so caller can track state for "yes" follow-up
                return (
                    f"I'm sorry, we don't have {item_name}. "
                    f"Would you like to hear what {category_name} we have?",
                    item_type_slug,
                )
        else:
            # Generic fallback
            return (
                f"I'm sorry, I couldn't find '{item_name}' on our menu. "
                f"Could you try again or ask what we have available?",
                None,
            )
