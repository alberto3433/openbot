"""
Pattern Loaders for MenuDataCache.

Contains loader methods for response patterns, abbreviations,
and compound phrases.
"""

import logging
import re

logger = logging.getLogger(__name__)


class PatternLoaderMixin:
    """Mixin containing pattern and text matching loading methods."""

    def _load_response_patterns_from_bulk(self, bulk_data: dict) -> None:
        """Load response patterns from bulk data."""
        patterns_list = bulk_data["response_patterns"]

        response_patterns: dict[str, set[str]] = {}
        regex_patterns: dict[str, list[str]] = {}

        for pattern in patterns_list:
            pattern_type = pattern.pattern_type
            if pattern.is_regex:
                if pattern_type not in regex_patterns:
                    regex_patterns[pattern_type] = []
                regex_patterns[pattern_type].append(pattern.pattern)
            else:
                if pattern_type not in response_patterns:
                    response_patterns[pattern_type] = set()
                response_patterns[pattern_type].add(pattern.pattern.lower())

        self._response_patterns = response_patterns
        self._response_regex_raw = regex_patterns

        # Build combined regex for each type
        all_types = set(response_patterns.keys()) | set(regex_patterns.keys())
        response_regex_compiled: dict[str, re.Pattern | None] = {}

        for pattern_type in all_types:
            pattern_parts = []

            exact = response_patterns.get(pattern_type, set())
            if exact:
                escaped = [re.escape(p) for p in exact]
                pattern_parts.extend(escaped)

            regex_list = regex_patterns.get(pattern_type, [])
            pattern_parts.extend(regex_list)

            if pattern_parts:
                combined = "|".join(f"({p})" for p in pattern_parts)
                full_pattern = f"^({combined})[\\s!.,]*$"
                try:
                    response_regex_compiled[pattern_type] = re.compile(full_pattern, re.IGNORECASE)
                except re.error as e:
                    logger.error("Failed to compile regex for %s: %s", pattern_type, e)
                    response_regex_compiled[pattern_type] = None
            else:
                response_regex_compiled[pattern_type] = None

        self._response_regex_compiled = response_regex_compiled

        logger.debug(
            "Loaded response patterns (from bulk): %d types",
            len(all_types),
        )

    def _load_abbreviations_from_bulk(self, bulk_data: dict) -> None:
        """Load abbreviations from bulk data."""
        ingredients = bulk_data["ingredients"]
        menu_items = bulk_data["menu_items"]

        abbreviations: dict[str, str] = {}

        for ingredient in ingredients:
            if ingredient.abbreviation:
                abbrev = ingredient.abbreviation.strip().lower()
                canonical = ingredient.name.lower()
                if abbrev and canonical:
                    abbreviations[abbrev] = canonical

        for item in menu_items:
            if item.abbreviation:
                abbrev = item.abbreviation.strip().lower()
                canonical = item.name.lower()
                if abbrev and canonical:
                    abbreviations[abbrev] = canonical

        self._abbreviations = abbreviations

        logger.debug(
            "Loaded %d abbreviations (from bulk)",
            len(abbreviations),
        )

    def _load_compound_phrases_from_bulk(self, bulk_data: dict) -> None:
        """Load compound phrases from bulk data."""
        menu_items = bulk_data["menu_items"]
        ingredients = bulk_data["ingredients"]

        compound_phrases: set[str] = set()

        for item in menu_items:
            if " and " in item.name.lower():
                compound_phrases.add(item.name.lower())
            for alias in item.aliases:
                if " and " in alias.lower():
                    compound_phrases.add(alias.lower())

        for ing in ingredients:
            if " and " in ing.name.lower():
                compound_phrases.add(ing.name.lower())
            for alias in ing.aliases:
                if " and " in alias.lower():
                    compound_phrases.add(alias.lower())

        self._compound_phrases = compound_phrases
        logger.debug("Loaded %d compound phrases (from bulk)", len(compound_phrases))

    def _load_attribute_inquiry_keywords(self, db) -> None:
        """Load attribute inquiry keywords from the database.

        This data-driven mapping replaces hardcoded common_mappings in
        menu_options_inquiry_handler.py for queries like "what types of X do you have?".

        Maps (keyword, item_type_slug) -> attribute_slug
        e.g., ("types", "bagel") -> "bread"
        """
        from sqlalchemy import text

        # Query all keywords from the database, joining to get slugs from FK relationships
        result = db.execute(text("""
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

        self._attribute_inquiry_keywords = keywords
        logger.debug(
            "Loaded %d attribute inquiry keywords",
            len(keywords),
        )
