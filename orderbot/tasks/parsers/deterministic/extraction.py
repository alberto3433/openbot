"""
Extraction Functions for Deterministic Parsing.

This module contains functions for extracting structured data from user input,
including attributes, modifiers, quantities, and special instructions.
"""

import re
import logging
from collections import namedtuple
from typing import Any

from orderbot.menu_data_cache import menu_cache

from ..constants import (
    WORD_TO_NUM,
    QUALIFIER_PATTERNS,
    SKIP_WORDS,
)

logger = logging.getLogger(__name__)


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
    text_lower = text.lower().strip()

    # Get qualifier patterns from database (sorted by length for longest match first)
    qualifier_patterns = menu_cache.get_qualifier_patterns()

    if not qualifier_patterns:
        # No qualifiers in database, fall back to simple modifier extraction
        formatted = []
        for modifier in sorted(known_modifiers, key=len, reverse=True):
            if re.search(rf'\b{re.escape(modifier)}\b', text_lower):
                normalized = menu_cache.normalize_modifier(modifier)
                if normalized not in formatted:
                    formatted.append(normalized)
        return (formatted, None)

    # Track found qualifiers with their positions
    # Format: [(start, end, pattern, normalized_form, category), ...]
    found_qualifiers: list[tuple[int, int, str, str, str]] = []

    for pattern in qualifier_patterns:
        # Find all occurrences of this qualifier pattern
        pattern_re = re.compile(rf'\b{re.escape(pattern)}\b', re.IGNORECASE)
        for match in pattern_re.finditer(text_lower):
            info = menu_cache.get_qualifier_info(pattern)
            if info:
                found_qualifiers.append((
                    match.start(),
                    match.end(),
                    pattern,
                    info["normalized_form"],
                    info["category"],
                ))

    # Track found modifiers with their positions
    # Format: [(start, end, modifier, normalized), ...]
    found_modifiers: list[tuple[int, int, str, str]] = []
    matched_spans: list[tuple[int, int]] = []

    # Mark qualifier spans to avoid matching modifiers inside them
    for start, end, _, _, _ in found_qualifiers:
        matched_spans.append((start, end))

    for modifier in sorted(known_modifiers, key=len, reverse=True):
        pattern_re = re.compile(rf'\b{re.escape(modifier)}\b', re.IGNORECASE)
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


# =============================================================================
# Special Instructions Extraction
# =============================================================================

def extract_special_instructions_from_input(user_input: str) -> list[str]:
    """
    Extract special instructions from user input.

    Args:
        user_input: The raw user input string

    Returns:
        List of instruction strings like ["light cream cheese", "extra bacon", "leave room"]
    """
    instructions = []
    input_lower = user_input.lower()

    # Check qualifier patterns (e.g., "light X", "extra X", "no X")
    for pattern, qualifier in QUALIFIER_PATTERNS:
        for match in re.finditer(pattern, input_lower, re.IGNORECASE):
            item = match.group(1).strip()
            if item.lower() in SKIP_WORDS:
                continue
            if qualifier == 'no':
                instruction = f"no {item}"
            elif qualifier == 'on the side':
                instruction = f"{item} on the side"
            else:
                instruction = f"{qualifier} {item}"
            if instruction not in instructions:
                instructions.append(instruction)
                logger.debug("Extracted special instruction: '%s' from input", instruction)

    # Check standalone patterns (e.g., "leave room", "cut in half", "melted")
    # Data-driven: patterns loaded from database via menu_cache
    for pattern in menu_cache.get_standalone_instruction_patterns():
        match = pattern.search(input_lower)  # Already compiled with IGNORECASE
        if match:
            instruction = match.group(0).strip()
            if instruction and instruction not in instructions:
                instructions.append(instruction)
                logger.debug("Extracted standalone instruction: '%s' from input", instruction)

    return instructions


# =============================================================================
# Generic Attribute Value Extraction (Data-Driven)
# =============================================================================

def extract_attribute_values(
    user_input: str,
    item_type: str,
) -> dict[str, Any]:
    """
    Extract attribute values from user input for a specific item type.

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

    Returns:
        Dict mapping attribute slugs to extracted values:
        - For single_select: {attr_slug: option_slug}
        - For multi_select: {attr_slug: [{slug, quantity, display_name}, ...]}
        - For boolean: {attr_slug: True/False}

    """
    result: dict[str, any] = {}
    input_lower = user_input.lower()

    # Get all attributes for this item type from database
    attributes = menu_cache.get_item_type_attributes(item_type)
    if not attributes:
        logger.debug("No attributes found for item type '%s'", item_type)
        return result

    # ==========================================================================
    # Pre-Phase: Detect "no {attribute}" negation patterns for ALL attributes
    # This must run BEFORE any option matching to prevent false positives.
    # E.g., "no spread" should set spread=None and skip all spread matching.
    # ==========================================================================
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
                result[attr_slug] = None
                negated_attrs.add(attr_slug)
                logger.debug(
                    "Negation detected for attribute '%s' (matched '%s'): "
                    "setting to None (declined)",
                    attr_slug, name
                )
                break

    def check_plural_boundary(text: str, start: int, end: int) -> tuple[bool, int]:
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

    def extract_quantity_before(text: str, pos: int) -> int:
        """Extract quantity prefix before a match position."""
        before_text = text[:pos].strip()
        if not before_text:
            return 1

        qty_pattern = re.compile(
            r'(\d+|one|two|three|four|five|six|double|triple|extra)\s*$',
            re.IGNORECASE
        )
        qty_match = qty_pattern.search(before_text)
        if qty_match:
            qty_str = qty_match.group(1).lower()
            if qty_str.isdigit():
                return int(qty_str)
            elif qty_str == "double":
                return 2
            elif qty_str == "triple":
                return 3
            elif qty_str == "extra":
                return 2
            else:
                return WORD_TO_NUM.get(qty_str, 1)
        return 1

    def check_must_match(option: dict, text: str) -> bool:
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

    # Phase 1: Handle boolean attributes first (they don't overlap with option matches)
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

    # Phase 2: Collect all potential option matches from all attributes
    CandidateMatch = namedtuple('CandidateMatch', [
        'attr_slug', 'option', 'pattern', 'start', 'end', 'length', 'is_multi_select'
    ])
    candidates: list[CandidateMatch] = []

    for attr_slug, attr_config in attributes.items():
        if attr_slug in negated_attrs:
            continue  # Skip - user explicitly said "no {attribute}"
        if attr_config.get("input_type") == "boolean":
            continue  # Already handled in Phase 1

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
                    # Use check_plural_boundary to match both singular and plural forms
                    # e.g., "plain bagel" matches "plain bagels"
                    is_valid, actual_end = check_plural_boundary(input_lower, pos, end)
                    if is_valid and check_must_match(opt, input_lower):
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

    # Phase 3: Sort by length descending (longest matches first)
    candidates.sort(key=lambda c: c.length, reverse=True)

    # Phase 4: Apply matches, tracking spans and avoiding overlaps
    matched_spans: list[tuple[int, int]] = []
    matched_options_per_attr: dict[str, set[str]] = {}  # Track matched option slugs per attribute

    def spans_overlap(start: int, end: int) -> bool:
        """Check if position overlaps with any matched span."""
        return any(not (end <= s or start >= e) for s, e in matched_spans)

    for cand in candidates:
        slug = cand.option.get("slug", "")

        # Skip if this option already matched for this attribute
        if slug in matched_options_per_attr.get(cand.attr_slug, set()):
            continue

        # Skip if overlaps with existing match
        if spans_overlap(cand.start, cand.end):
            continue

        # Check if option is unavailable (e.g., "medium" size doesn't exist)
        # Track the unavailable attempt for helpful user feedback
        if not cand.option.get("is_available", True):
            # Mark span as matched to prevent overlapping available options
            matched_spans.append((cand.start, cand.end))
            matched_options_per_attr.setdefault(cand.attr_slug, set()).add(slug)

            # Store unavailable selection info using special key pattern
            # The config handler will use this to show "We don't have X - we have Y or Z"
            unavail_key = f"_unavailable_{cand.attr_slug}"
            result[unavail_key] = {
                "attempted_slug": slug,
                "attempted_display": cand.option.get("display_name", slug),
            }
            logger.debug(
                "Unavailable option detected: '%s' for attr '%s' (user said '%s')",
                slug, cand.attr_slug, cand.pattern
            )
            continue  # Don't add to normal result

        # Record the match
        matched_spans.append((cand.start, cand.end))
        matched_options_per_attr.setdefault(cand.attr_slug, set()).add(slug)

        quantity = extract_quantity_before(input_lower, cand.start)
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
                result[cand.attr_slug] = slug

        logger.debug(
            "Extracted attribute value: '%s' -> '%s' (qty=%d, attr=%s)",
            cand.pattern, slug, quantity, cand.attr_slug
        )

    # Phase 5: Reverse matching - user token appears in option name
    # E.g., "milk" (user token) in "Whole Milk" (option display_name)
    # This handles cases where user says "coffee with milk" but database has
    # options like "Whole Milk", "Oat Milk" etc.
    #
    # Only applies to multi_select attributes. Adds to existing matches (e.g., Phase 4
    # found "sugar", Phase 5 can still add "milk" → "Whole Milk").
    # Uses must_match to filter: "oat_milk" requires "oat" in input, but "whole_milk"
    # (with no must_match) matches just "milk".
    #
    # Important: Filter out tokens that fall within spans already matched in Phase 4.
    # This prevents "cream" from matching "Veggie Cream Cheese" when "plain cream cheese"
    # was already matched by Phase 4.
    input_token_matches = [(m.group(), m.start(), m.end())
                           for m in re.finditer(r'\b\w+\b', input_lower)
                           if len(m.group()) >= 3]
    input_tokens = [(word, start, end) for word, start, end in input_token_matches
                    if not spans_overlap(start, end)]

    for attr_slug, attr_config in attributes.items():
        if attr_slug in negated_attrs:
            continue  # Skip - user explicitly said "no {attribute}"
        # Only apply Phase 5 to multi_select attributes
        input_type = attr_config.get("input_type", "single_select")
        if input_type != "multi_select":
            continue

        # Note: Don't skip if matches exist - Phase 5 adds ADDITIONAL
        # reverse matches. The per-option guard below prevents duplicates.

        options = attr_config.get("options", [])
        if not options:
            continue

        for opt in options:
            slug = opt.get("slug", "")
            if slug in matched_options_per_attr.get(attr_slug, set()):
                continue

            # Check must_match constraint
            if not check_must_match(opt, input_lower):
                continue

            display_lower = opt.get("display_name", "").lower()
            slug_readable = slug.replace("_", " ").lower()

            for token, token_start, token_end in input_tokens:
                matched = False
                if re.search(rf'\b{re.escape(token)}\b', display_lower):
                    matched = True
                elif re.search(rf'\b{re.escape(token)}\b', slug_readable):
                    matched = True

                if matched:
                    quantity = extract_quantity_before(input_lower, token_start)
                    result.setdefault(attr_slug, []).append({
                        "slug": slug,
                        "display_name": opt.get("display_name", slug),
                        "quantity": quantity,
                        "price": opt.get("price_modifier", 0),
                        "category": opt.get("category"),
                    })
                    matched_options_per_attr.setdefault(attr_slug, set()).add(slug)
                    logger.debug(
                        "Phase 5 reverse match: token '%s' in option '%s' for attr '%s'",
                        token, display_lower or slug_readable, attr_slug
                    )
                    break

    logger.debug(
        "Extracted attribute values for %s: %s",
        item_type, result
    )
    return result


# =============================================================================
# Helper Functions
# =============================================================================

def _extract_modifiers_generic(
    text: str,
    item_type: str
) -> list[str]:
    """Extract modifiers for an item type from text.

    Uses the modifier category for the item type to determine which
    modifier groups to search. All logic is data-driven from the database.

    Skips categories that are handled via item type attributes (e.g., milk,
    sweetener for beverages) since those are extracted by extract_attribute_values.

    Args:
        text: User input text (lowercase)
        item_type: Item type slug

    Returns:
        List of matched modifier names (normalized/canonical)
    """
    text_lower = text.lower()
    found_modifiers = []

    # Get modifier category for this item type (data-driven from database)
    modifier_type = menu_cache.get_modifier_category(item_type)

    if not modifier_type:
        return found_modifiers

    # Build set of all attribute option slugs for this item type (normalized to match ingredients)
    # This lets us detect when an ingredient category overlaps with attribute options
    attr_option_slugs: set[str] = set()
    for attr_config in menu_cache.get_item_type_attributes(item_type).values():
        for opt in attr_config.get("options", []):
            slug = opt.get("slug", "")
            # Normalize: "oat_milk" -> "oat milk"
            attr_option_slugs.add(slug.replace("_", " ").lower())

    # Extract modifiers from categories that aren't handled as attributes
    for category in menu_cache.get_ordered_ingredient_categories(modifier_type):
        ingredients = menu_cache.get_ingredients(category)

        # Check if this category's ingredients overlap with attribute options
        # If so, skip - those are handled via extract_attribute_values
        category_overlaps_attrs = any(
            ing.lower() in attr_option_slugs or ing.lower().replace(" ", "_") in attr_option_slugs
            for ing in ingredients
        )
        if category_overlaps_attrs:
            continue

        for ingredient in ingredients:
            if ingredient.lower() in text_lower:
                found_modifiers.append(ingredient.lower())

    return found_modifiers


def _extract_quantity(text: str) -> int | None:
    """Extract quantity from text like '3', 'three', 'a couple of', 'a dozen'."""
    text = text.lower().strip()
    text = re.sub(r"\s+of$", "", text)
    # Normalize whitespace for compound expressions like "a  dozen" -> "a dozen"
    text = re.sub(r"\s+", " ", text)

    if text.isdigit():
        return int(text)

    return WORD_TO_NUM.get(text)


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


def _extract_boolean_global_attribute(text: str, attr_slug: str) -> bool | None:
    """Extract a boolean attribute value using global attribute options (data-driven).

    This function looks up boolean options (true/false) for the given attribute
    from global_attribute_options and matches the user input against aliases
    defined for those options using substring matching.

    Args:
        text: User input text
        attr_slug: The attribute slug

    Returns:
        True if matched to true option, False if matched to false option, None if no match.
    """
    text_lower = text.lower()

    # Try to resolve via global attribute options with aliases (substring matching)
    try:
        options = menu_cache.get_global_attribute_options(attr_slug)
        if options:
            # Build list of (alias, is_true) tuples sorted by length descending
            # so we match longer aliases first (e.g., "not toasted" before "toasted")
            alias_matches: list[tuple[str, bool]] = []
            for opt in options:
                is_true_option = opt["slug"] == "true"
                # Check the option's aliases from the linked ingredient
                aliases = opt.get("aliases", [])
                for alias in aliases:
                    alias_matches.append((alias.lower(), is_true_option))

            # Sort by length descending to match longer aliases first
            alias_matches.sort(key=lambda x: len(x[0]), reverse=True)

            # Check if any alias appears in the text
            for alias, is_true_option in alias_matches:
                if alias in text_lower:
                    return is_true_option
    except Exception:
        # No options configured for this attribute, fall through to fallback
        pass

    # Fallback: Use regex pattern matching based on the attribute slug itself
    # This handles cases where database options aren't configured
    slug_lower = attr_slug.lower()

    # Check for negative patterns first ("not {slug}", "un{slug}")
    if re.search(rf"\b(?:not\s+{re.escape(slug_lower)}(?:ed)?|un{re.escape(slug_lower)}(?:ed)?)\b", text_lower):
        return False

    # Check for positive pattern ("{slug}" or "{slug}ed")
    if re.search(rf"\b{re.escape(slug_lower)}(?:ed)?\b", text_lower):
        return True

    return None


