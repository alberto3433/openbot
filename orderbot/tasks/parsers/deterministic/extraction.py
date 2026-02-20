"""
Extraction Functions for Deterministic Parsing.

This module contains core utility functions for extracting structured data from
user input, including span overlap detection, quantity extraction, negation/boolean
attribute detection, modifier extraction, and by-pound parsing.

Sub-modules:
- attribute_matching: multi-phase attribute option matching pipeline
- inapplicable_detection: inapplicable modifier/attribute detection
- qualifier_extraction: extract_modifiers_with_qualifiers
- instructions_extraction: extract_special_instructions_from_input
"""

import re
import logging
from typing import Any

from orderbot.cache import menu_cache

from ..quantity_utils import WORD_TO_NUM, BASIC_WORD_TO_NUM, extract_quantity_word

# Re-export from sub-modules for backward compatibility
from .qualifier_extraction import extract_modifiers_with_qualifiers

logger = logging.getLogger(__name__)


def _spans_overlap(
    start: int,
    end: int,
    *span_lists: list[tuple[int, int]] | None,
) -> bool:
    """Check if a (start, end) span overlaps with any span in the given lists.

    Args:
        start: Start position to check
        end: End position to check
        *span_lists: One or more lists of (start, end) tuples to check against.
            None values are safely skipped.

    Returns:
        True if the span overlaps with any span in any of the provided lists.
    """
    for span_list in span_lists:
        if not span_list:
            continue
        for s, e in span_list:
            if not (end <= s or start >= e):
                return True
    return False


def _check_plural_boundary(text: str, start: int, end: int) -> tuple[bool, int]:
    """Check if match is at word boundary, allowing for plural suffixes.

    Returns (is_valid, actual_end) where actual_end includes any plural suffix.
    Handles common English plural patterns: -s, -es.

    Examples:
        "bagel" in "bagels" -> (True, end+1)  # includes 's'
        "box" in "boxes" -> (True, end+2)     # includes 'es'
    """
    before_ok = start == 0 or not text[start - 1].isalnum()
    if not before_ok:
        return (False, end)

    # Check exact word boundary first
    if end >= len(text) or not text[end].isalnum():
        return (True, end)

    # Check for plural suffix
    remaining = text[end:]

    # Check 's' suffix (bagels, drinks)
    if remaining.startswith('s') and (len(remaining) == 1 or not remaining[1].isalnum()):
        return (True, end + 1)

    # Check 'es' suffix (boxes, dishes, tomatoes)
    if remaining.startswith('es') and (len(remaining) == 2 or not remaining[2].isalnum()):
        return (True, end + 2)

    return (False, end)


def _extract_quantity_before(
    text: str,
    pos: int,
    exclude_spans: list[tuple[int, int]] | None = None,
) -> int:
    """Extract quantity prefix before a match position.

    Uses BASIC_WORD_TO_NUM from quantity_utils as single source of truth.

    Args:
        text: Full input text
        pos: Position of the match to look before
        exclude_spans: Optional spans to exclude (e.g., item-level quantity already consumed)
    """
    before_text = text[:pos]
    if not before_text.strip():
        return 1

    qty_pattern = re.compile(
        r'(\d+|one|two|three|four|five|six|double|triple|quad|quadruple|extra)\s*$',
        re.IGNORECASE
    )
    qty_match = qty_pattern.search(before_text)
    if qty_match:
        # Check if this quantity word overlaps with an excluded span
        if exclude_spans and _spans_overlap(qty_match.start(1), qty_match.end(1), exclude_spans):
            return 1

        qty_str = qty_match.group(1).lower()
        if qty_str.isdigit():
            return int(qty_str)
        elif qty_str == "extra":
            return 2  # "extra" means 2 in modifier context
        else:
            return BASIC_WORD_TO_NUM.get(qty_str, 1)
    return 1


# =============================================================================
# Sub-functions for _extract_attribute_values
# =============================================================================

def _detect_negated_attributes(
    input_lower: str,
    attributes: dict[str, dict],
) -> tuple[dict[str, Any], set[str]]:
    """Detect "no {attribute}" negation patterns for ALL attributes.

    Must run BEFORE any option matching to prevent false positives.
    E.g., "no spread" should set spread=None and skip all spread matching.

    Args:
        input_lower: Lowercased user input
        attributes: Attribute configs from menu cache

    Returns:
        Tuple of (result_updates, negated_attrs) where result_updates maps
        attr slugs to None and negated_attrs is the set of negated slugs.
    """
    result_updates: dict[str, Any] = {}
    negated_attrs: set[str] = set()

    for attr_slug, attr_config in attributes.items():
        attr_display = attr_config.get("display_name", attr_slug).lower()

        # Build set of name variants to check for negation.
        # Users say "no spread" not "no spread type", so we try multiple forms.
        names_to_check = {attr_display}
        # Also try slug with underscores as spaces (e.g., "spread_type" -> "spread type")
        names_to_check.add(attr_slug.replace("_", " ").lower())
        # Also try display name without trailing "type"/"choice" suffix
        for suffix in (" type", " choice"):
            if attr_display.endswith(suffix):
                names_to_check.add(attr_display[:-len(suffix)].strip())

        # Match patterns like "no spread", "without spread", "skip spread"
        for name in names_to_check:
            negation_pattern = rf'\b(?:no|without|skip)\s+{re.escape(name)}\b'
            if re.search(negation_pattern, input_lower, re.IGNORECASE):
                # Set to None for ALL attribute types when explicitly negated.
                # This follows the codebase convention where None triggers the
                # "_declined" marker in MenuItemTask.__setitem__, which marks
                # the attribute as "answered" so the slot orchestrator won't ask.
                result_updates[attr_slug] = None
                negated_attrs.add(attr_slug)
                logger.debug(
                    "Negation detected for attribute '%s' (matched '%s'): "
                    "setting to None (declined)",
                    attr_slug, name
                )
                break

    return result_updates, negated_attrs


def _extract_boolean_attrs(
    input_lower: str,
    attributes: dict[str, dict],
    negated_attrs: set[str],
) -> dict[str, bool]:
    """Extract boolean true/false attributes from user input.

    Checks for negative patterns first (e.g., "not toasted") before positive
    patterns (e.g., "toasted"), to avoid false matches.

    Args:
        input_lower: Lowercased user input
        attributes: Attribute configs from menu cache
        negated_attrs: Set of attribute slugs already negated (to skip)

    Returns:
        Dict mapping attribute slugs to boolean values.
    """
    result: dict[str, bool] = {}

    for attr_slug, attr_config in attributes.items():
        if attr_slug in negated_attrs:
            continue  # Skip - user explicitly said "no {attribute}"
        if attr_config.get("input_type") == "boolean":
            display_name = attr_config.get("display_name", attr_slug).lower()
            # Check for negative patterns FIRST (before positive check)
            # This prevents "not toasted" from matching just "toasted"
            if re.search(rf'\b(?:not\s+{re.escape(display_name)}|un{re.escape(display_name)}|no\s+{re.escape(display_name)})\b', input_lower):
                result[attr_slug] = False
                logger.debug("Extracted boolean attribute: %s = False", attr_slug)
            elif re.search(rf'\b{re.escape(display_name)}\b', input_lower):
                result[attr_slug] = True
                logger.debug("Extracted boolean attribute: %s = True", attr_slug)

    return result


# =============================================================================
# Helper Functions
# =============================================================================

def _extract_modifiers_generic(
    text: str,
    item_type: str,
    exclude_spans: list[tuple[int, int]] | None = None
) -> list[str]:
    """Extract modifiers for an item type from text.

    Uses the modifier category for the item type to determine which
    modifier groups to search. All logic is data-driven from the database.

    Skips categories that are handled via item type attributes (e.g., milk,
    sweetener for beverages) since those are extracted by pipeline.extract_attributes().

    Args:
        text: User input text (lowercase)
        item_type: Item type slug
        exclude_spans: List of (start, end) tuples to exclude from matching.
            These are typically spans already consumed by pipeline.extract_attributes()
            to prevent double-extraction (e.g., "scrambled eggs" matched as egg_style
            should not also match "eggs" as a protein modifier).

    Returns:
        List of matched modifier names (normalized/canonical)
    """
    text_lower = text.lower()
    found_modifiers = []

    # Get modifier category for this item type (data-driven from database)
    modifier_type = menu_cache.get_modifier_category(item_type)

    if not modifier_type:
        return found_modifiers

    # Build set of all attribute option slugs AND aliases for this item type
    # This lets us detect when an ingredient (or its alias) overlaps with attribute options
    # Example: oat_milk option has aliases ["oat milk", "oat"], so we add all of them
    attr_option_slugs: set[str] = set()
    # Also track canonical attribute option slugs (raw, lowercased) for ingredient-level dedup
    attr_option_canonical_slugs: set[str] = set()
    item_type_attrs = menu_cache.get_item_type_attributes(item_type)
    for attr_config in item_type_attrs.values():
        for opt in attr_config.get("options", []):
            slug = opt.get("slug", "")
            if slug:
                attr_option_canonical_slugs.add(slug.lower())
            # Normalize: "oat_milk" -> "oat milk"
            attr_option_slugs.add(slug.replace("_", " ").lower())
            # Also add all aliases (e.g., "oat" for oat_milk)
            for alias in (opt.get("aliases") or []):
                attr_option_slugs.add(alias.lower())

    # Build set of attribute slugs for this item type
    # Categories that match attribute slugs should be skipped entirely
    # (e.g., "bread" category for bagels is the "bread" attribute)
    attr_slugs = set(item_type_attrs.keys())

    # Get ingredients that are valid for this specific item type (from global attributes)
    # This ensures we only extract modifiers that make sense for this item type
    valid_ingredients_by_category = menu_cache.get_ingredients_by_category_for_item_type(item_type)

    # Track matched modifier spans to prevent overlapping matches within this function
    # (e.g., ingredient name and alias matching the same text region)
    found_modifier_spans: list[tuple[int, int]] = []

    # Extract modifiers from categories that aren't handled as attributes
    for category in menu_cache.get_ordered_ingredient_categories(modifier_type):
        # Skip categories that are directly used as attributes for this item type
        # (e.g., "bread", "spread", "cheese" for bagels)
        if category in attr_slugs:
            continue

        # Only use ingredients that are valid for this item type
        valid_ingredients = valid_ingredients_by_category.get(category, set())
        if not valid_ingredients:
            continue

        # Build pattern -> ingredient slug mapping for this category
        # Used to check if an ingredient alias maps to an attribute option
        ingredient_details = menu_cache.get_ingredient_details(category)
        pattern_to_slug: dict[str, str] = {}
        for detail in ingredient_details:
            detail_slug = detail.get("slug", "").lower()
            for pattern in detail.get("patterns", []):
                pattern_to_slug[pattern.lower()] = detail_slug

        for ingredient in valid_ingredients:
            ing_lower = ingredient.lower()
            # Skip ingredients that overlap with attribute options - those are handled
            # via extract_attribute_values
            if ing_lower in attr_option_slugs or ing_lower.replace(" ", "_") in attr_option_slugs:
                continue

            # Skip if this ingredient's canonical slug matches an attribute option slug
            # This catches cases where the ingredient alias differs from the attribute
            # option alias but they refer to the same thing (e.g., ingredient alias
            # "jalape\u00f1o cream" for ingredient slug "jalapeno_cc" which is also an
            # attribute option)
            canonical_slug = pattern_to_slug.get(ing_lower, "")
            if canonical_slug and canonical_slug in attr_option_canonical_slugs:
                continue

            # Find position of ingredient in text and check for span overlap
            pos = text_lower.find(ing_lower)
            if pos != -1:
                end_pos = pos + len(ing_lower)
                if not _spans_overlap(pos, end_pos, exclude_spans, found_modifier_spans):
                    found_modifiers.append(ing_lower)
                    found_modifier_spans.append((pos, end_pos))

    return found_modifiers


def _extract_quantity(text: str) -> int | None:
    """Extract quantity from text like '3', 'three', 'a couple of', 'a dozen'.

    Delegates to extract_quantity_word from quantity_utils (single source of truth).
    """
    return extract_quantity_word(text)


def _extract_by_pound_info(text: str) -> tuple[str | None, str | None]:
    """Extract by-pound weight unit and product name from text.

    Detects patterns like "quarter pound of cream cheese", "half lb salmon".

    Args:
        text: User input text

    Returns:
        (weight_unit, product_name) or (None, None) if not a by-pound pattern

    Example:
        >>> _extract_by_pound_info("quarter pound of plain cream cheese")
        ("1/4 lb", "plain cream cheese")
        >>> _extract_by_pound_info("half a pound of whitefish salad")
        ("1/2 lb", "whitefish salad")
    """
    text_lower = text.lower().strip()

    # Weight patterns to detect (pattern, normalized weight_unit)
    weight_patterns = [
        (r"(?:a\s+)?quarter\s+(?:pound|lb)", "1/4 lb"),
        (r"1/4\s*(?:pound|lb)", "1/4 lb"),
        (r"(?:a\s+)?half\s+(?:a\s+)?(?:pound|lb)", "1/2 lb"),
        (r"1/2\s*(?:pound|lb)", "1/2 lb"),
        (r"(?:one|1)\s+(?:pound|lb)", "1 lb"),
        (r"a\s+(?:pound|lb)", "1 lb"),
    ]

    for pattern, weight_unit in weight_patterns:
        match = re.search(pattern, text_lower)
        if match:
            # Extract product name (part after "of" or after weight)
            after_match = text_lower[match.end():].strip()
            # Remove "of" prefix if present
            if after_match.startswith("of "):
                after_match = after_match[3:].strip()
            # Remove trailing "please"
            after_match = re.sub(r"\s+please\s*$", "", after_match).strip()

            if after_match:
                return weight_unit, after_match

    return None, None


# =============================================================================
# Re-exports from sub-modules for backward compatibility
# =============================================================================
# These imports are placed at the bottom of the file to avoid circular imports:
# attribute_matching.py imports utility functions defined above in this file,
# so those must be defined before attribute_matching is loaded.

from .attribute_matching import (  # noqa: E402
    _check_must_match,
    CandidateMatch,
    _collect_option_candidates,
    _apply_longest_match_first,
    _count_token_option_matches,
    _apply_token_matches,
    _apply_reverse_matching,
    _detect_unrecognized_size_terms,
    _extract_attribute_values,
)

from .inapplicable_detection import (  # noqa: E402
    _detect_inapplicable_modifiers,
    _detect_inapplicable_attributes,
)
