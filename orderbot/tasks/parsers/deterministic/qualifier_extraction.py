"""
Modifier Qualifier Extraction.

Extracts modifiers with their associated qualifiers (extra, light, on the side, etc.)
from user input text.
"""

import re
import logging

from orderbot.cache import menu_cache
from ...utils.text import normalize_text

logger = logging.getLogger(__name__)

# =============================================================================
# Pattern Matching Helpers
# =============================================================================

def _compile_word_pattern(text: str) -> re.Pattern:
    """Compile a case-insensitive word-boundary pattern.

    Args:
        text: The literal text to match

    Returns:
        Compiled regex pattern that matches the text with word boundaries
    """
    return re.compile(rf'\b{re.escape(text)}\b', re.IGNORECASE)


def _find_pattern_matches(
    patterns: list[str],
    text: str,
    info_func: callable = None,
) -> list[tuple[int, int, str, any]]:
    """Find all word-boundary matches for patterns in text.

    Args:
        patterns: List of patterns to search for
        text: Text to search in (should be lowercased)
        info_func: Optional function to get info for each pattern.
                   If provided, only patterns where info_func returns truthy are included.

    Returns:
        List of (start, end, pattern, info) tuples for each match.
        If info_func is None, info will be None.
    """
    matches = []
    for pattern in patterns:
        pattern_re = _compile_word_pattern(pattern)
        for match in pattern_re.finditer(text):
            info = info_func(pattern) if info_func else None
            if info_func is None or info:
                matches.append((match.start(), match.end(), pattern, info))
    return matches


# =============================================================================
# Modifier Qualifier Extraction
# =============================================================================

def extract_modifiers_with_qualifiers(
    text: str,
    known_modifiers: set[str]
) -> tuple[list[str], list[tuple[str, str, str]] | None]:
    """
    Extract modifiers and their associated qualifiers from text.

    Scans the text for qualifier patterns (extra, light, on the side, etc.)
    from the database and associates them with adjacent modifiers.

    Args:
        text: The text to parse (e.g., "extra mayo and bacon on the side")
        known_modifiers: Set of valid modifiers to look for

    Returns:
        Tuple of:
        - List of formatted modifiers with qualifiers (e.g., ["Mayo (extra)", "Bacon (on the side)"])
        - List of conflicts if any (modifier, qualifier1, qualifier2 tuples), or None if no conflicts

    Examples:
        >>> extract_modifiers_with_qualifiers("extra mayo", {"mayo", "bacon"})
        (["Mayo (extra)"], None)

        >>> extract_modifiers_with_qualifiers("mayo on the side, crispy bacon", {"mayo", "bacon"})
        (["Mayo (on the side)", "Bacon (crispy)"], None)

        >>> extract_modifiers_with_qualifiers("light extra mayo", {"mayo"})
        ([], [("mayo", "light", "extra")])  # Conflict detected
    """
    text_lower = normalize_text(text)

    # Get qualifier patterns from database (sorted by length for longest match first)
    qualifier_patterns = menu_cache.get_qualifier_patterns()

    if not qualifier_patterns:
        # No qualifiers in database, fall back to simple modifier extraction
        formatted = []
        for modifier in sorted(known_modifiers, key=len, reverse=True):
            if _compile_word_pattern(modifier).search(text_lower):
                normalized = menu_cache.normalize_modifier(modifier)
                if normalized not in formatted:
                    formatted.append(normalized)
        return (formatted, None)

    # Find qualifiers with positions using pattern matching helper
    # Format: [(start, end, pattern, info), ...] where info = {"normalized_form", "category"}
    raw_qualifier_matches = _find_pattern_matches(
        qualifier_patterns, text_lower, menu_cache.get_qualifier_info
    )
    # Expand to include normalized_form and category
    found_qualifiers: list[tuple[int, int, str, str, str]] = [
        (start, end, pattern, info["normalized_form"], info["category"])
        for start, end, pattern, info in raw_qualifier_matches
    ]

    # Track found modifiers with their positions
    # Format: [(start, end, modifier, normalized), ...]
    found_modifiers: list[tuple[int, int, str, str]] = []
    matched_spans: list[tuple[int, int]] = [(start, end) for start, end, _, _, _ in found_qualifiers]

    for modifier in sorted(known_modifiers, key=len, reverse=True):
        pattern_re = _compile_word_pattern(modifier)
        for match in pattern_re.finditer(text_lower):
            start, end = match.start(), match.end()
            # Check for overlap with existing spans
            overlaps = any(not (end <= s or start >= e) for s, e in matched_spans)
            if not overlaps:
                normalized = menu_cache.normalize_modifier(modifier)
                found_modifiers.append((start, end, modifier, normalized))
                matched_spans.append((start, end))

    # Associate qualifiers with modifiers
    # A qualifier applies to a modifier if it's adjacent (before or after)
    modifier_qualifiers: dict[str, list[tuple[str, str]]] = {}  # normalized_modifier -> [(normalized_qual, category), ...]
    conflicts: list[tuple[str, str, str]] = []

    for mod_start, mod_end, _, normalized_mod in found_modifiers:
        if normalized_mod not in modifier_qualifiers:
            modifier_qualifiers[normalized_mod] = []

        # Find qualifiers adjacent to this modifier
        for qual_start, qual_end, _, qual_normalized, qual_category in found_qualifiers:
            # Check if qualifier is adjacent (within 20 chars, accounting for spaces)
            # Qualifier before modifier: "extra mayo" -> qual_end near mod_start
            # Qualifier after modifier: "mayo on the side" -> mod_end near qual_start
            is_before = qual_end <= mod_start and mod_start - qual_end <= 15
            is_after = qual_start >= mod_end and qual_start - mod_end <= 15

            if is_before or is_after:
                # Check for conflicts in same category
                existing_categories = [cat for _, cat in modifier_qualifiers[normalized_mod]]
                if qual_category == "amount" and "amount" in existing_categories:
                    # Conflict: multiple amount qualifiers for same modifier
                    existing_amount = next(q for q, c in modifier_qualifiers[normalized_mod] if c == "amount")
                    conflicts.append((normalized_mod, existing_amount, qual_normalized))
                else:
                    modifier_qualifiers[normalized_mod].append((qual_normalized, qual_category))

    # Build formatted output
    formatted: list[str] = []

    for mod_start, mod_end, _, normalized_mod in found_modifiers:
        qualifiers = modifier_qualifiers.get(normalized_mod, [])
        if qualifiers:
            # Sort qualifiers for consistent output
            qual_strs = sorted(set(q for q, _ in qualifiers))
            formatted.append(f"{normalized_mod} ({', '.join(qual_strs)})")
        else:
            formatted.append(normalized_mod)

    return (formatted, conflicts if conflicts else None)
