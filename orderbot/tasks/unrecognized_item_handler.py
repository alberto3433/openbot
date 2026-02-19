"""
Unrecognized Item Handler.

Provides a 4-level fallback chain for handling menu items that aren't found:
1. Curated suggestions - Check unrecognized_item_suggestions table
2. Fuzzy matching - Find similar menu items by string similarity
3. LLM category inference - Minimal prompt to infer category
4. Generic fallback - Show top menu categories

This module is order-state aware, adjusting responses based on cart contents.
"""

import logging

from sqlalchemy.exc import SQLAlchemyError

from orderbot.cache import menu_cache
from orderbot.cache.base import singularize
from orderbot.constants import FUZZY_MATCH_THRESHOLD, MAX_FUZZY_MATCHES
from orderbot.exceptions import MenuDataNotLoadedError

from .menu_lookup import MenuLookup
from .normalization import strip_leading_filler_words
from .utils.text import format_english_list, normalize_text

logger = logging.getLogger(__name__)


class UnrecognizedItemHandler:
    """
    Handles unrecognized menu item requests with intelligent fallbacks.

    Uses a 4-level fallback chain:
    1. Curated suggestions from database
    2. Fuzzy string matching against menu items
    3. LLM-based category inference
    4. Generic category suggestions
    """

    # Fuzzy matching threshold (0-100)
    FUZZY_THRESHOLD = FUZZY_MATCH_THRESHOLD

    # Maximum fuzzy matches to show
    MAX_FUZZY_MATCHES = MAX_FUZZY_MATCHES

    def __init__(
        self,
        menu_lookup: MenuLookup,
        db_session=None,
    ):
        """
        Initialize the handler.

        Args:
            menu_lookup: MenuLookup instance for suggestions
            db_session: Optional SQLAlchemy session for database queries
        """
        self.menu_lookup = menu_lookup
        self._db_session = db_session
        self._rapidfuzz_available = self._check_rapidfuzz()

    def _check_rapidfuzz(self) -> bool:
        """Check if rapidfuzz is available for fuzzy matching."""
        try:
            import rapidfuzz
            return True
        except ImportError:
            logger.debug("rapidfuzz not available, fuzzy matching disabled")
            return False

    def get_not_found_response(
        self,
        item_name: str,
        order=None,
        session_id: str | None = None,
    ) -> tuple[str, str | None, list[dict]]:
        """
        Generate a helpful response when an item isn't found on the menu.

        Uses a 4-level fallback chain:
        1. Check curated suggestions table
        2. Try fuzzy matching against menu items
        3. Use LLM to infer category
        4. Fall back to generic category suggestions

        Args:
            item_name: The name of the item the user requested
            order: Optional OrderTask for context-aware responses
            session_id: Optional session ID for analytics logging

        Returns:
            Tuple of (message, category_slug_for_followup, quick_replies).
            category_slug_for_followup is set when asking if user wants
            to hear what items are in a category.
            quick_replies contains clickable suggestion items.
        """
        item_name_normalized = normalize_text(item_name)
        # Strip filler words for lookup (some, a, an, the)
        item_name_for_lookup = strip_leading_filler_words(item_name_normalized)
        # Strip trailing punctuation (?, !, .)
        item_name_for_lookup = item_name_for_lookup.rstrip('?!.')

        order_item_count = 0
        if order and hasattr(order, 'items') and hasattr(order.items, 'items'):
            order_item_count = len(order.items.items)

        logger.info(
            "UnrecognizedItemHandler: item_name='%s', normalized='%s', lookup='%s', db_session=%s",
            item_name, item_name_normalized, item_name_for_lookup, "set" if self._db_session else "None"
        )

        # Level 1: Check curated suggestions (using cleaned name for lookup)
        curated = self._check_curated_suggestions(item_name_for_lookup)
        if curated:
            message, category, suggested_items = self._build_curated_response(
                item_name, curated, order_item_count
            )
            qr = self._build_suggestion_quick_replies(suggested_items)
            self._log_unrecognized(
                item_name, item_name_for_lookup, session_id,
                order_item_count, "curated", category
            )
            return (message, category, qr)

        # Level 1.5: Check if term matches a display group (e.g., "sandwich" -> "Sandwiches")
        display_group_result = self._check_display_group_match(item_name_for_lookup, order)
        if display_group_result:
            self._log_unrecognized(
                item_name, item_name_for_lookup, session_id,
                order_item_count, "display_group", display_group_result[1]
            )
            return (display_group_result[0], display_group_result[1], [])

        # Level 2: Try fuzzy matching (using cleaned name)
        fuzzy_matches = self._get_fuzzy_matches(item_name_for_lookup)
        if fuzzy_matches:
            message = self._build_fuzzy_response(
                item_name, fuzzy_matches, order_item_count
            )
            qr = self._build_suggestion_quick_replies(fuzzy_matches)
            self._log_unrecognized(
                item_name, item_name_for_lookup, session_id,
                order_item_count, "fuzzy", None
            )
            return (message, None, qr)

        # Level 3: LLM category inference (using cleaned name)
        inferred_category = self._infer_category_with_llm(item_name_for_lookup)
        if inferred_category:
            message, category, suggested_items = self._build_inferred_response(
                item_name, inferred_category, order_item_count
            )
            qr = self._build_suggestion_quick_replies(suggested_items)
            self._log_unrecognized(
                item_name, item_name_for_lookup, session_id,
                order_item_count, "llm", inferred_category
            )
            return (message, category, qr)

        # Level 4: Generic fallback
        message = self._build_generic_response(item_name, order_item_count)
        self._log_unrecognized(
            item_name, item_name_for_lookup, session_id,
            order_item_count, "generic", None
        )
        return (message, None, [])

    def _check_curated_suggestions(self, normalized_input: str) -> dict | None:
        """
        Check the curated suggestions table for a matching pattern.

        Tries both the original input and singularized form to handle
        plural variations (e.g., "tacos" -> "taco").

        Args:
            normalized_input: Lowercase, stripped item name

        Returns:
            Dict with suggestion info if found, None otherwise.
        """
        if not self._db_session:
            logger.warning("Curated suggestions skipped: no db_session available")
            return None

        logger.debug("Checking curated suggestions for: '%s'", normalized_input)

        # Build list of forms to try: original and singularized
        forms_to_try = [normalized_input]
        singular_form = singularize(normalized_input)
        if singular_form and singular_form != normalized_input:
            forms_to_try.append(singular_form)

        try:
            from orderbot.db.models import UnrecognizedMenuItemSuggestion

            # Try exact match first (for both original and singular forms)
            for form in forms_to_try:
                suggestion = self._db_session.query(UnrecognizedMenuItemSuggestion).filter(
                    UnrecognizedMenuItemSuggestion.is_active == True,
                    UnrecognizedMenuItemSuggestion.match_type == "exact",
                    UnrecognizedMenuItemSuggestion.input_pattern == form,
                ).first()

                if suggestion:
                    suggestion.hit_count += 1
                    self._db_session.commit()
                    return self._extract_suggestion_data(suggestion)

            # Try prefix match (for both forms)
            suggestions = self._db_session.query(UnrecognizedMenuItemSuggestion).filter(
                UnrecognizedMenuItemSuggestion.is_active == True,
                UnrecognizedMenuItemSuggestion.match_type == "prefix",
            ).all()

            for s in suggestions:
                for form in forms_to_try:
                    if form.startswith(s.input_pattern):
                        s.hit_count += 1
                        self._db_session.commit()
                        return self._extract_suggestion_data(s)

            # Try contains match (for both forms)
            suggestions = self._db_session.query(UnrecognizedMenuItemSuggestion).filter(
                UnrecognizedMenuItemSuggestion.is_active == True,
                UnrecognizedMenuItemSuggestion.match_type == "contains",
            ).all()

            for s in suggestions:
                for form in forms_to_try:
                    if s.input_pattern in form:
                        s.hit_count += 1
                        self._db_session.commit()
                        return self._extract_suggestion_data(s)

        except (SQLAlchemyError, KeyError, ValueError, AttributeError) as e:
            logger.warning("Failed to query curated suggestions: %s", e)
            try:
                self._db_session.rollback()
            except SQLAlchemyError:
                pass

        return None

    def _check_display_group_match(
        self,
        normalized_input: str,
        order=None,
    ) -> tuple[str, str | None] | None:
        """
        Check if the input matches a display group (e.g., "sandwich" -> "Sandwiches").

        If matched, returns a helpful response listing items from that display group.

        Args:
            normalized_input: Lowercase, stripped item name
            order: Optional OrderTask for pagination state

        Returns:
            Tuple of (message, display_group_slug) if match found, None otherwise.
        """
        # Try to find a matching display group
        display_group = menu_cache.get_display_group_by_slug(normalized_input)

        if not display_group:
            return None

        group_name = display_group.get("display_name", normalized_input)
        group_slug = display_group.get("slug", normalized_input)

        # Get items from this display group
        item_type_slugs = menu_cache.get_item_types_in_display_group(group_slug)
        if not item_type_slugs:
            return None

        # Gather all items from the display group's item types
        all_items = []
        for item_type_slug in item_type_slugs:
            items = self.menu_lookup.get_items_for_item_type(item_type_slug)
            all_items.extend(items)

        if not all_items:
            return None

        # Show first few items with pagination hint if more available
        max_to_show = 4
        item_names = [item.get("name", "") for item in all_items[:max_to_show]]
        items_list = format_english_list(item_names, conjunction="or")

        remaining = len(all_items) - max_to_show
        if remaining > 0:
            message = (
                f"We have several {group_name.lower()}! Here are a few: {items_list}. "
                f"We have {remaining} more options. Would you like to hear more, or would you like any of these?"
            )
            # Set up pagination state
            if order:
                order.menu_query_pagination = {
                    "type": "display_group_items",
                    "display_group": group_slug,
                    "items": [item.get("name", "") for item in all_items],
                    "offset": max_to_show,
                }
        else:
            message = (
                f"We have {group_name.lower()}! Our options are: {items_list}. "
                f"Would you like any of these?"
            )
            if order:
                order.clear_menu_pagination()

        return (message, group_slug)

    def _extract_suggestion_data(self, suggestion) -> dict:
        """Extract category slug and menu items from a suggestion object.

        Args:
            suggestion: UnrecognizedMenuItemSuggestion model instance

        Returns:
            Dict with category_slug and menu_items list
        """
        # Get category slug from the related item_type
        category_slug = None
        if suggestion.suggested_item_type:
            category_slug = suggestion.suggested_item_type.slug

        # Get menu item names from the relationship
        menu_items = None
        if suggestion.suggested_menu_items:
            menu_items = [item.name for item in suggestion.suggested_menu_items]

        return {
            "category_slug": category_slug,
            "menu_items": menu_items,
        }

    def _build_curated_response(
        self,
        item_name: str,
        curated: dict,
        order_item_count: int,
    ) -> tuple[str, str | None, list[str]]:
        """Build response from curated suggestion.

        Returns:
            Tuple of (message, category_slug, suggested_item_names).
        """
        # Clean up item name by removing filler words
        clean_name = strip_leading_filler_words(item_name).rstrip('?!.')

        # If specific menu items are suggested
        if curated.get("menu_items"):
            items = curated["menu_items"]
            if isinstance(items, list) and items:
                shown = items[:4]
                item_list = format_english_list(shown, conjunction="or")
                followup = self._get_order_aware_followup(order_item_count, len(shown))
                # Safety net: if clean_name appears in the suggestions, don't say
                # "We don't have X" (it would be contradictory)
                if clean_name.lower() in item_list.lower():
                    return (
                        f"We have {item_list}. {followup}",
                        None,
                        shown,
                    )
                return (
                    f"We don't have {clean_name}, but we do have {item_list}. {followup}",
                    None,
                    shown,
                )

        # If a category is suggested
        category_slug = curated.get("category_slug")
        if category_slug:
            suggestion_names = self.menu_lookup.get_suggestion_names_for_item_type(
                category_slug, limit=4
            )
            if suggestion_names:
                suggestion_text = format_english_list(suggestion_names, conjunction="or")
                followup = self._get_order_aware_followup(order_item_count, len(suggestion_names))
                return (
                    f"We don't have {clean_name}, but we do have {suggestion_text}. {followup}",
                    None,
                    suggestion_names,
                )
            else:
                # Return category for follow-up inquiry
                category_display = self._get_category_display_name(category_slug)
                return (
                    f"We don't have {clean_name}. Would you like to hear what {category_display} we have?",
                    category_slug,
                    [],
                )

        # Fallback if curated entry is incomplete
        return (
            f"I'm sorry, we don't have {clean_name}. Is there something else I can help you with?",
            None,
            [],
        )

    def _get_fuzzy_matches(self, normalized_input: str) -> list[str]:
        """
        Find similar menu items using fuzzy string matching.

        Args:
            normalized_input: Lowercase, stripped item name

        Returns:
            List of similar menu item names (up to MAX_FUZZY_MATCHES).
        """
        if not self._rapidfuzz_available:
            return []

        try:
            from rapidfuzz import fuzz, process

            # Get all menu item names
            all_names = menu_cache.get_all_menu_item_names()
            if not all_names:
                return []

            # Use token_sort_ratio for better matching of word order variations
            # e.g., "muffin blueberry" matches "Blueberry Muffin"
            matches = process.extract(
                normalized_input,
                all_names,
                scorer=fuzz.token_sort_ratio,
                limit=self.MAX_FUZZY_MATCHES + 2,  # Get extra to filter
            )

            # Filter by threshold and return names only
            good_matches = []
            for name, score, _ in matches:
                if score >= self.FUZZY_THRESHOLD:
                    good_matches.append(name)
                    if len(good_matches) >= self.MAX_FUZZY_MATCHES:
                        break

            return good_matches

        except (ValueError, KeyError, TypeError, AttributeError, MenuDataNotLoadedError) as e:
            logger.warning("Fuzzy matching failed: %s", e)
            return []

    def _build_fuzzy_response(
        self,
        item_name: str,
        fuzzy_matches: list[str],
        order_item_count: int,
    ) -> str:
        """Build response with fuzzy match suggestions."""
        clean_name = strip_leading_filler_words(item_name).rstrip('?!.')
        match_list = format_english_list(fuzzy_matches, conjunction="or")
        followup = self._get_order_aware_followup(order_item_count, len(fuzzy_matches))
        return f"We don't have {clean_name}. Did you mean {match_list}? {followup}"

    def _infer_category_with_llm(self, normalized_input: str) -> str | None:
        """
        Use LLM to infer what category the item might belong to.

        Args:
            normalized_input: Lowercase, stripped item name

        Returns:
            Category slug if inference succeeds, None otherwise.
        """
        try:
            from .parsers.llm_category_inference import infer_item_category

            categories = menu_cache.get_categories_for_inference()
            if not categories:
                return None

            return infer_item_category(normalized_input, categories)

        except (ValueError, KeyError, ConnectionError, TimeoutError, MenuDataNotLoadedError) as e:
            logger.warning("LLM category inference failed: %s", e)
            return None

    def _build_inferred_response(
        self,
        item_name: str,
        category_slug: str,
        order_item_count: int,
    ) -> tuple[str, str | None, list[str]]:
        """Build response based on LLM-inferred category.

        Returns:
            Tuple of (message, category_slug, suggested_item_names).
        """
        clean_name = strip_leading_filler_words(item_name).rstrip('?!.')
        suggestion_names = self.menu_lookup.get_suggestion_names_for_item_type(
            category_slug, limit=4
        )

        if suggestion_names:
            category_display = self._get_category_display_name(category_slug)
            suggestion_text = format_english_list(suggestion_names, conjunction="or")
            followup = self._get_order_aware_followup(order_item_count, len(suggestion_names))
            # Safety net: if clean_name appears in the suggestions, don't say
            # "We don't have X" (it would be contradictory)
            if clean_name.lower() in suggestion_text.lower():
                return (
                    f"For {category_display}, we have {suggestion_text}. {followup}",
                    None,
                    suggestion_names,
                )
            return (
                f"We don't have {clean_name}. For {category_display}, we have {suggestion_text}. {followup}",
                None,
                suggestion_names,
            )
        else:
            category_display = self._get_category_display_name(category_slug)
            return (
                f"We don't have {clean_name}. Would you like to hear what {category_display} we have?",
                category_slug,
                [],
            )

    def _build_generic_response(
        self,
        item_name: str,
        order_item_count: int,
    ) -> str:
        """Build generic fallback response with top categories.

        Uses high-level display groups (Breads, Sandwiches, Drinks) instead of
        granular item types (Bagels, Chai Drinks, etc.) for cleaner UX.
        """
        clean_name = strip_leading_filler_words(item_name).rstrip('?!.')
        # Get high-level display groups
        display_groups = menu_cache.get_menu_display_groups()

        if display_groups:
            # Show top 3-4 display groups
            group_names = [g["display_name"] for g in display_groups][:4]
            group_list = format_english_list(group_names, conjunction="and")
            return (
                f"I'm sorry, we don't have {clean_name}. "
                f"We do have {group_list} though - would any of those interest you?"
            )
        else:
            return (
                f"I'm sorry, we don't have {clean_name}. "
                f"Is there something else I can help you with?"
            )

    @staticmethod
    def _build_suggestion_quick_replies(items: list[str] | None) -> list[dict]:
        """Build quick_replies from a list of suggested item names."""
        if not items:
            return []
        return [{"label": name, "value": name} for name in items[:4]]

    def _get_order_aware_followup(self, order_item_count: int, num_alternatives: int = 2) -> str:
        """Get a context-appropriate follow-up question based on cart state.

        Args:
            order_item_count: Number of items in the cart
            num_alternatives: Number of alternatives suggested (1 = "that", 2+ = "those")
        """
        is_singular = num_alternatives == 1

        if order_item_count == 0:
            if is_singular:
                return "Would you like that, or can I help you find something else?"
            else:
                return "Would you like any of those, or can I help you find something else?"
        elif order_item_count < 3:
            if is_singular:
                return "Would that work, or is there something else to add?"
            else:
                return "Would any of those work, or is there something else to add?"
        else:
            return "Would you like to add one, or are you ready to check out?"

    def _get_category_display_name(self, category_slug: str) -> str:
        """Get display name for a category slug."""
        # Try category keywords first
        info = menu_cache.get_category_keyword_mapping(category_slug)
        if info:
            return info.get("display_name_plural") or info.get("display_name", category_slug)

        # Try item type display
        display = menu_cache.get_item_type_display_name(category_slug)
        if display:
            return display

        # Fallback: format slug
        return category_slug.replace("_", " ")

    def _log_unrecognized(
        self,
        user_input: str,
        normalized_input: str,
        session_id: str | None,
        order_item_count: int,
        fallback_level: str,
        inferred_category: str | None,
    ) -> None:
        """Log unrecognized item request for analytics."""
        if not self._db_session:
            return

        try:
            from orderbot.db.models import UnrecognizedMenuItemLog

            log_entry = UnrecognizedMenuItemLog(
                user_input=user_input[:500],  # Truncate if needed
                normalized_input=normalized_input[:200],
                session_id=session_id,
                order_item_count=order_item_count,
                fallback_level=fallback_level,
                inferred_category=inferred_category,
            )
            self._db_session.add(log_entry)
            self._db_session.commit()

        except (SQLAlchemyError, KeyError, ValueError, TypeError) as e:
            logger.warning("Failed to log unrecognized item: %s", e)
            try:
                self._db_session.rollback()
            except SQLAlchemyError:
                pass
