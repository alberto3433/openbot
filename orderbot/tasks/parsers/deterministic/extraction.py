"""
Extraction Functions for Deterministic Parsing.

This module contains functions for extracting structured data from user input,
including attributes, modifiers, quantities, and special instructions.

Sub-modules:
- qualifier_extraction: extract_modifiers_with_qualifiers
- instructions_extraction: extract_special_instructions_from_input
"""

import re
import logging
from collections import namedtuple
from typing import Any

from orderbot.cache import menu_cache

from ..quantity_utils import WORD_TO_NUM, BASIC_WORD_TO_NUM, extract_quantity_word
from .result_types import (
    AmbiguousSelection,
    AttributeExtractionResult,
    TextSpan,
    UnavailableSelection,
    UnmatchedToken,
)

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


def _check_must_match(option: dict, text: str) -> bool:
    """Check if must_match patterns are present in text.

    Handles both string and list formats for must_match.
    If must_match is set, at least ONE pattern must be present (OR logic).

    The must_match list contains alternative disambiguation patterns.
    For example, vegetable_cream_cheese has must_match=['veggie cream', 'vegetable cream']
    meaning the input must contain at least one of these to disambiguate from
    other cream cheese options.
    """
    must_match_raw = option.get("must_match")
    if not must_match_raw:
        return True  # No must_match requirement

    # Normalize to list (handle string or list format)
    if isinstance(must_match_raw, str):
        must_match_list = [m.strip().lower() for m in must_match_raw.split(",") if m.strip()]
    else:
        must_match_list = [str(m).lower() for m in must_match_raw]

    if not must_match_list:
        return True

    return any(pattern in text for pattern in must_match_list)


CandidateMatch = namedtuple('CandidateMatch', [
    'attr_slug', 'option', 'pattern', 'start', 'end', 'length', 'is_multi_select'
])


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


def _collect_option_candidates(
    input_lower: str,
    attributes: dict[str, dict],
    negated_attrs: set[str],
) -> list:
    """Build candidate match list from all non-boolean, non-negated attributes.

    Scans user input for all potential option matches from all attributes,
    using display names, slugs, and aliases. Validates word boundaries
    (including plural forms) and must_match constraints.

    Args:
        input_lower: Lowercased user input
        attributes: Attribute configs from menu cache
        negated_attrs: Set of attribute slugs already negated (to skip)

    Returns:
        List of CandidateMatch namedtuples (unsorted).
    """
    candidates: list[CandidateMatch] = []

    for attr_slug, attr_config in attributes.items():
        if attr_slug in negated_attrs:
            continue  # Skip - user explicitly said "no {attribute}"
        if attr_config.get("input_type") == "boolean":
            continue  # Already handled in boolean phase

        options = attr_config.get("options", [])
        if not options:
            continue

        is_multi_select = attr_config.get("input_type") == "multi_select"

        for opt in options:
            patterns = []
            # Add display_name
            if opt.get("display_name"):
                patterns.append(opt["display_name"].lower())
            # Add slug as words
            if opt.get("slug"):
                patterns.append(opt["slug"].replace("_", " ").lower())
                patterns.append(opt["slug"].lower())
            # Add aliases (use `or []` in case aliases is explicitly None)
            patterns.extend(alias.lower() for alias in (opt.get("aliases") or []))

            for pattern in patterns:
                start = 0
                while True:
                    pos = input_lower.find(pattern, start)
                    if pos == -1:
                        break
                    end = pos + len(pattern)
                    # Use _check_plural_boundary to match both singular and plural forms
                    # e.g., "plain bagel" matches "plain bagels"
                    is_valid, actual_end = _check_plural_boundary(input_lower, pos, end)
                    if is_valid and _check_must_match(opt, input_lower):
                        candidates.append(CandidateMatch(
                            attr_slug=attr_slug,
                            option=opt,
                            pattern=pattern,
                            start=pos,
                            end=actual_end,  # Include plural suffix in span
                            length=actual_end - pos,  # Use actual matched length
                            is_multi_select=is_multi_select,
                        ))
                    start = pos + 1

    return candidates


def _apply_longest_match_first(
    candidates: list,
    input_lower: str,
    exclude_spans: list[tuple[int, int]] | None,
) -> tuple[dict[str, Any], list[tuple[int, int]], dict[str, set[str]], list[UnavailableSelection]]:
    """Sort candidates by length and apply non-overlapping matches.

    Processes candidates longest-first. For each candidate, checks for span
    overlaps, negation prefixes, and availability before recording the match.

    Args:
        candidates: List of CandidateMatch namedtuples (will be sorted in place)
        input_lower: Lowercased user input
        exclude_spans: Optional list of (start, end) tuples to exclude from matching

    Returns:
        Tuple of (result, matched_spans, matched_options_per_attr, unavailable_selections)
        where:
        - result: Dict mapping attr slugs to matched values
        - matched_spans: List of (start, end) tuples for consumed spans
        - matched_options_per_attr: Dict mapping attr slugs to sets of matched option slugs
        - unavailable_selections: List of UnavailableSelection for unavailable options
    """
    # Sort by length descending (longest matches first)
    candidates.sort(key=lambda c: c.length, reverse=True)

    result: dict[str, Any] = {}
    matched_spans: list[tuple[int, int]] = []
    matched_options_per_attr: dict[str, set[str]] = {}
    unavailable_selections: list[UnavailableSelection] = []

    for cand in candidates:
        slug = cand.option.get("slug", "")

        # Skip if this option already matched for this attribute
        if slug in matched_options_per_attr.get(cand.attr_slug, set()):
            continue

        # Skip if overlaps with existing match
        if _spans_overlap(cand.start, cand.end, matched_spans, exclude_spans):
            continue

        # Skip if preceded by negation word ("no", "without", "skip")
        # This prevents "capers" from matching as an addition when user said "no capers"
        # The modification parser handles "no X" separately as a removal
        # Mark the span as matched to prevent Phase 5 from re-matching the negated word
        before_text = input_lower[:cand.start].rstrip()
        if before_text.endswith(('no', 'without', 'skip')):
            matched_spans.append((cand.start, cand.end))
            logger.debug(
                "Skipping negated option: '%s' preceded by negation word",
                cand.pattern
            )
            continue

        # Check if option is unavailable (e.g., "medium" size doesn't exist)
        # Track the unavailable attempt for helpful user feedback
        opt_is_available = cand.option.get("is_available", True)
        logger.debug(
            "CHECKING CANDIDATE: slug=%s, attr=%s, is_available=%s, option_keys=%s",
            slug, cand.attr_slug, opt_is_available, list(cand.option.keys())
        )
        if not opt_is_available:
            # Mark span as matched to prevent overlapping available options
            matched_spans.append((cand.start, cand.end))
            matched_options_per_attr.setdefault(cand.attr_slug, set()).add(slug)

            # Track unavailable selection for "We don't have X - we have Y or Z" messaging
            unavailable_selections.append(UnavailableSelection(
                attr_slug=cand.attr_slug,
                attempted_slug=slug,
                attempted_display=cand.option.get("display_name", slug),
            ))
            logger.debug(
                "Unavailable option detected: '%s' for attr '%s' (user said '%s')",
                slug, cand.attr_slug, cand.pattern
            )
            continue  # Don't add to normal result

        # Record the match
        matched_spans.append((cand.start, cand.end))
        matched_options_per_attr.setdefault(cand.attr_slug, set()).add(slug)

        quantity = _extract_quantity_before(input_lower, cand.start, exclude_spans=exclude_spans)
        match_data = {
            "slug": slug,
            "display_name": cand.option.get("display_name", slug),
            "quantity": quantity,
            "price": cand.option.get("price") or cand.option.get("price_modifier") or 0,
            "category": cand.option.get("category"),
        }

        if cand.is_multi_select:
            result.setdefault(cand.attr_slug, []).append(match_data)
        else:
            # Single select: only set if not already set
            if cand.attr_slug not in result:
                # Preserve quantity for single-select when user specified a quantity
                # e.g., "2 shots" should store quantity=2, not just "shot"
                if quantity > 1:
                    result[cand.attr_slug] = match_data
                else:
                    result[cand.attr_slug] = slug

        logger.debug(
            "Extracted attribute value: '%s' -> '%s' (qty=%d, attr=%s)",
            cand.pattern, slug, quantity, cand.attr_slug
        )

    return result, matched_spans, matched_options_per_attr, unavailable_selections


def _count_token_option_matches(
    input_tokens: list[tuple[str, int, int]],
    options: list[dict],
    attr_slug: str,
    matched_options_per_attr: dict[str, set[str]],
    input_lower: str,
) -> dict[str, list[dict]]:
    """First pass of reverse matching: count how many options each input token matches.

    For each option, checks if any input token appears (word-boundary) in the
    option's display name or slug. Skips already-matched options and options
    that fail must_match constraints.

    Args:
        input_tokens: List of (word, start, end) tuples from user input.
        options: Attribute option dicts from menu cache.
        attr_slug: The attribute slug being processed.
        matched_options_per_attr: Already matched options per attribute.
        input_lower: Full lowercased user input (for must_match checks).

    Returns:
        Dict mapping token string to list of matching option info dicts.
    """
    token_match_counts: dict[str, list[dict]] = {}
    for opt in options:
        slug = opt.get("slug", "")
        if slug in matched_options_per_attr.get(attr_slug, set()):
            continue

        if not _check_must_match(opt, input_lower):
            continue

        display_lower = opt.get("display_name", "").lower()
        slug_readable = slug.replace("_", " ").lower()

        for token, token_start, token_end in input_tokens:
            matched = (
                re.search(rf'\b{re.escape(token)}\b', display_lower)
                or re.search(rf'\b{re.escape(token)}\b', slug_readable)
            )
            if matched:
                existing_slugs = {m["slug"] for m in token_match_counts.get(token, [])}
                if slug not in existing_slugs:
                    token_match_counts.setdefault(token, []).append({
                        "opt": opt,
                        "slug": slug,
                        "token_start": token_start,
                    })

    return token_match_counts


def _apply_token_matches(
    token_match_counts: dict[str, list[dict]],
    attr_slug: str,
    input_lower: str,
    exclude_spans: list[tuple[int, int]] | None,
    result: dict[str, Any],
    matched_options_per_attr: dict[str, set[str]],
) -> list[AmbiguousSelection]:
    """Second pass of reverse matching: apply single-match tokens, record ambiguous ones.

    Tokens that matched exactly one option are applied to the result. Tokens
    that matched multiple options are recorded as AmbiguousSelection for
    disambiguation by the handler.

    Args:
        token_match_counts: Output of _count_token_option_matches.
        attr_slug: The attribute slug being processed.
        input_lower: Full lowercased user input (for quantity extraction).
        exclude_spans: Spans to exclude from quantity extraction.
        result: Result dict to add matches to (mutated in place).
        matched_options_per_attr: Already matched options (mutated in place).

    Returns:
        List of AmbiguousSelection for tokens that matched multiple options.
    """
    ambiguous: list[AmbiguousSelection] = []

    for token, matches in token_match_counts.items():
        if len(matches) > 1:
            logger.debug(
                "Phase 5 skipping ambiguous token '%s' - matches %d options: %s",
                token, len(matches), [m["slug"] for m in matches]
            )
            ambiguous.append(AmbiguousSelection(
                attr_slug=attr_slug,
                token=token,
                matching_options=[
                    {
                        "slug": m["slug"],
                        "display_name": m["opt"].get("display_name", m["slug"]),
                        "price": m["opt"].get("price_modifier", 0),
                    }
                    for m in matches
                ],
            ))
            continue

        match_info = matches[0]
        opt = match_info["opt"]
        slug = match_info["slug"]
        token_start = match_info["token_start"]

        quantity = _extract_quantity_before(input_lower, token_start, exclude_spans=exclude_spans)
        result.setdefault(attr_slug, []).append({
            "slug": slug,
            "display_name": opt.get("display_name", slug),
            "quantity": quantity,
            "price": opt.get("price_modifier", 0),
            "category": opt.get("category"),
        })
        matched_options_per_attr.setdefault(attr_slug, set()).add(slug)
        logger.debug(
            "Phase 5 reverse match: token '%s' -> option '%s' for attr '%s'",
            token, opt.get("display_name", slug), attr_slug
        )

    return ambiguous


def _apply_reverse_matching(
    input_lower: str,
    attributes: dict[str, dict],
    negated_attrs: set[str],
    matched_spans: list[tuple[int, int]],
    matched_options_per_attr: dict[str, set[str]],
    exclude_spans: list[tuple[int, int]] | None,
    result: dict[str, Any],
) -> list[AmbiguousSelection]:
    """Reverse matching: user token appears inside option name.

    E.g., "milk" (user token) in "Whole Milk" (option display_name).
    Handles cases where user says "coffee with milk" but database has
    options like "Whole Milk", "Oat Milk" etc.

    Only applies to multi_select attributes. Adds to existing matches.
    Uses must_match to filter ambiguous options.

    If a token matches multiple options, all matches for that token are
    skipped and an AmbiguousSelection is recorded for disambiguation.
    """
    ambiguous_selections: list[AmbiguousSelection] = []

    # Tokenize input, filtering out short tokens and already-matched spans
    input_token_matches = [(m.group(), m.start(), m.end())
                           for m in re.finditer(r'\b\w+\b', input_lower)
                           if len(m.group()) >= 3]
    input_tokens = [(word, start, end) for word, start, end in input_token_matches
                    if not _spans_overlap(start, end, matched_spans, exclude_spans)]

    for attr_slug, attr_config in attributes.items():
        if attr_slug in negated_attrs:
            continue
        if attr_config.get("input_type", "single_select") != "multi_select":
            continue
        options = attr_config.get("options", [])
        if not options:
            continue

        token_match_counts = _count_token_option_matches(
            input_tokens, options, attr_slug, matched_options_per_attr, input_lower,
        )
        ambiguous_selections.extend(_apply_token_matches(
            token_match_counts, attr_slug, input_lower, exclude_spans,
            result, matched_options_per_attr,
        ))

    return ambiguous_selections


def _detect_unrecognized_size_terms(
    input_lower: str,
    attributes: dict[str, dict],
    result: dict[str, Any],
    unavailable_selections: list[UnavailableSelection],
) -> None:
    """Detect common size terms not in the menu and add to unavailable list.

    If user mentions a size term (medium, regular, tall, etc.) that isn't
    in our menu options, adds it to unavailable_selections so the handler
    can say "We don't have medium".

    Args:
        input_lower: Lowercased user input
        attributes: Attribute configs from menu cache
        result: Current result dict (checked for existing size match)
        unavailable_selections: List to append to (mutated in place)
    """
    has_size_unavailable = any(u.attr_slug == "size" for u in unavailable_selections)
    if "size" not in attributes or "size" in result or has_size_unavailable:
        return

    # Get unavailable size terms from database
    unavailable_size_terms = menu_cache.get_unavailable_size_terms()

    for term, display in unavailable_size_terms.items():
        # Word boundary match
        pattern = re.compile(rf'\b{re.escape(term)}\b', re.IGNORECASE)
        if pattern.search(input_lower):
            # Check if this term is NOT a known size option for this item
            known_slugs = {opt.get("slug", "").lower() for opt in attributes["size"].get("options", [])}
            known_displays = {opt.get("display_name", "").lower() for opt in attributes["size"].get("options", [])}

            if term.lower() not in known_slugs and term.lower() not in known_displays:
                unavailable_selections.append(UnavailableSelection(
                    attr_slug="size",
                    attempted_slug=term,
                    attempted_display=display,
                ))
                logger.info(
                    "Unrecognized size term detected: '%s' (not in menu options)",
                    term
                )
                break


# =============================================================================
# Generic Attribute Value Extraction (Data-Driven)
# =============================================================================

def _extract_attribute_values(
    user_input: str,
    item_type: str,
    exclude_spans: list[tuple[int, int]] | None = None,
) -> AttributeExtractionResult:
    """
    Extract attribute values from user input for a specific item type.

    Internal function - use ExtractionPipeline.extract_attributes() instead.

    This is the generic, data-driven function. It queries the database for what
    attributes the item type has and matches input against those options.

    Uses cross-attribute longest-match-first algorithm:
    1. Collect ALL potential matches from ALL attributes
    2. Sort by match length descending
    3. Apply matches in order, skipping overlaps

    This ensures longer matches always win regardless of attribute processing order.
    For example, "plain cream cheese" will match spread before "plain" matches bread.

    Args:
        user_input: The raw user input string
        item_type: The item type slug
        exclude_spans: Optional list of (start, end) tuples to exclude from matching.
            Used to prevent matching words within menu item names (e.g., "butter" in
            "Cinnamon Sugar Butter Sandwich" should not match as a spread attribute).

    Returns:
        AttributeExtractionResult containing:
        - values: Dict mapping attribute slugs to extracted values
        - matched_spans: List of TextSpan indicating consumed text spans
        - unavailable: List of UnavailableSelection for unavailable options user tried
        - unmatched: List of UnmatchedToken for unrecognized tokens

    """
    input_lower = user_input.lower()

    # Get all attributes for this item type from database
    attributes = menu_cache.get_item_type_attributes(item_type)
    if not attributes:
        logger.debug("No attributes found for item type '%s'", item_type)
        return AttributeExtractionResult(values={}, matched_spans=[])

    # Pre-Phase: Detect "no {attribute}" negation patterns
    negation_updates, negated_attrs = _detect_negated_attributes(input_lower, attributes)

    # Phase 1: Extract boolean attributes
    boolean_updates = _extract_boolean_attrs(input_lower, attributes, negated_attrs)

    # Phase 2: Collect all potential option matches from all attributes
    candidates = _collect_option_candidates(input_lower, attributes, negated_attrs)

    # Phase 3-4: Sort by length descending and apply non-overlapping matches
    forward_result, matched_spans, matched_options_per_attr, unavailable_selections = (
        _apply_longest_match_first(candidates, input_lower, exclude_spans)
    )

    # Merge results: negation -> boolean -> forward matches
    result: dict[str, Any] = {}
    result.update(negation_updates)
    result.update(boolean_updates)
    result.update(forward_result)

    # Phase 5: Reverse matching - user token appears in option name
    ambiguous_selections = _apply_reverse_matching(
        input_lower, attributes, negated_attrs,
        matched_spans, matched_options_per_attr, exclude_spans, result,
    )

    # Phase 6: Detect unrecognized size terms
    _detect_unrecognized_size_terms(
        input_lower, attributes, result, unavailable_selections,
    )

    logger.debug(
        "Extracted attribute values for %s: %s",
        item_type, result
    )

    # Convert matched_spans to typed TextSpan
    result_spans = [TextSpan(start=s, end=e) for s, e in matched_spans]

    return AttributeExtractionResult(
        values=result,
        matched_spans=result_spans,
        unavailable=unavailable_selections,
        unmatched=[],  # No unmatched tracking currently implemented
        ambiguous=ambiguous_selections,
    )


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
            # "jalapeño cream" for ingredient slug "jalapeno_cc" which is also an
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


def _detect_unrecognized_ingredients(
    input_lower: str,
    consumed_spans: list[tuple[int, int]],
) -> list[dict]:
    """Detect tokens in user input that match unrecognized ingredient suggestions.

    After attribute and modifier extraction have consumed their spans, this function
    checks remaining tokens against the unrecognized ingredient suggestions cache.

    Args:
        input_lower: Lowercase user input text.
        consumed_spans: List of (start, end) tuples already consumed by attributes/modifiers.

    Returns:
        List of dicts, each with: token, display_name, modifier_category, alternatives.
    """
    results: list[dict] = []

    # Tokenize the input into words
    words = input_lower.split()
    if not words:
        return results

    # Build simple word-position map for checking consumed spans
    pos = 0
    word_positions: list[tuple[int, int, str]] = []
    for word in words:
        start = input_lower.find(word, pos)
        end = start + len(word)
        word_positions.append((start, end, word))
        pos = end

    # Check each word against unrecognized ingredient suggestions
    for start, end, word in word_positions:
        # Skip if this span is already consumed by attributes or modifiers
        if _spans_overlap(start, end, consumed_spans, []):
            continue

        # Strip common punctuation
        clean_word = word.strip(".,!?;:")
        if not clean_word or len(clean_word) < 2:
            continue

        suggestion = menu_cache.get_unrecognized_ingredient_suggestion(clean_word)
        if suggestion:
            results.append({
                "token": clean_word,
                "display_name": suggestion["display_name"],
                "modifier_category": suggestion.get("modifier_category"),
                "alternatives": suggestion.get("alternatives", []),
            })

    return results


def _detect_inapplicable_modifiers(text_lower: str) -> list[dict]:
    """Detect globally-known modifiers in 'with X' phrases that weren't matched for an item.

    Used for non-configurable items where item-type-specific modification extraction
    found nothing. Checks if there are 'with X' phrases where X is a known modifier
    globally (e.g., 'hazelnut syrup' on Deviled Eggs).

    Args:
        text_lower: Lowercase user input.

    Returns:
        List of dicts with token and display_name for each inapplicable modifier.
    """
    with_match = re.search(r'\bwith\s+(.+?)(?:\s*(?:please|thanks)|\s*$)', text_lower)
    if not with_match:
        return []

    modifier_text = with_match.group(1).strip()
    if not modifier_text:
        return []

    results: list[dict] = []
    candidates = [modifier_text]
    for part in re.split(r'\s+and\s+|\s*,\s*', modifier_text):
        part = part.strip()
        if part and part != modifier_text:
            candidates.append(part)

    for candidate in candidates:
        canonical = menu_cache.normalize_modifier(candidate)
        if canonical != candidate:
            results.append({
                "token": candidate,
                "display_name": canonical,
            })
            return results

        if " " in candidate:
            for word in candidate.split():
                word = word.strip()
                if len(word) < 3:
                    continue
                if menu_cache.is_known_modifier(word):
                    canonical = menu_cache.normalize_modifier(word)
                    results.append({
                        "token": candidate,
                        "display_name": canonical if canonical != word else candidate.title(),
                    })
                    return results

    return results


def _detect_inapplicable_attributes(
    text_lower: str,
    menu_item: str,
    menu_item_span: tuple[int, int] | None,
    item_type_slug: str | None,
) -> list[dict]:
    """Detect attribute option words in input that don't apply to the matched item type.

    Scans text outside the menu item name span for words that are known attribute
    option values (e.g., "small", "iced") but map to attributes the item type
    doesn't have. This lets us notify the user: "Heads up, only comes in one size."

    Args:
        text_lower: Lowercase user input.
        menu_item: The matched menu item name.
        menu_item_span: (start, end) character span of the item name in text_lower.
        item_type_slug: The item type slug (e.g., "sandwich", "sized_beverage").

    Returns:
        List of {word, attribute_slug} for each inapplicable attribute word found.
    """
    if not item_type_slug:
        return []

    # Get all known attribute option words → attribute slug mapping
    all_option_words = menu_cache.get_all_attribute_option_words()
    if not all_option_words:
        return []

    # Get the attributes this item type actually has
    item_attrs = menu_cache.get_item_type_attributes(item_type_slug)
    item_attr_slugs = set(item_attrs.keys()) if item_attrs else set()

    # Build set of words that are part of the menu item name (to exclude)
    item_name_words = set(menu_item.lower().split())

    # Get the text outside the menu item span
    if menu_item_span:
        outside_text = text_lower[:menu_item_span[0]] + " " + text_lower[menu_item_span[1]:]
    else:
        outside_text = text_lower

    # Tokenize the outside text
    words = outside_text.split()

    results: list[dict] = []
    seen_attrs: set[str] = set()
    for word in words:
        word_clean = word.strip(",.!?;:'\"")
        if not word_clean or len(word_clean) < 2:
            continue
        # Skip words that are part of the item name
        if word_clean in item_name_words:
            continue
        # Check if this word is a known attribute option
        if word_clean in all_option_words:
            attr_slug = all_option_words[word_clean]
            # Only flag if the item type does NOT have this attribute
            if attr_slug not in item_attr_slugs and attr_slug not in seen_attrs:
                seen_attrs.add(attr_slug)
                results.append({"word": word_clean, "attribute_slug": attr_slug})

    return results


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
