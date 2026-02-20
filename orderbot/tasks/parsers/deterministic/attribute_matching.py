"""
Attribute Option Matching Pipeline for Deterministic Parsing.

This module implements the multi-phase attribute option matching pipeline,
including candidate collection, longest-match-first application, reverse
matching, and the main orchestrator _extract_attribute_values().
"""

import re
import logging
from collections import namedtuple
from typing import Any

from orderbot.cache import menu_cache

from .result_types import (
    AmbiguousSelection,
    AttributeExtractionResult,
    TextSpan,
    UnavailableSelection,
)
from .extraction import (
    _spans_overlap,
    _check_plural_boundary,
    _extract_quantity_before,
    _detect_negated_attributes,
    _extract_boolean_attrs,
)

logger = logging.getLogger(__name__)


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
