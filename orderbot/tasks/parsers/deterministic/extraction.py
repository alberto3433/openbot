"""
Extraction Functions for Deterministic Parsing.

This module contains functions for extracting structured data from user input,
including attributes, modifiers, quantities, and special instructions.
"""

import re
import logging
from collections import namedtuple

from orderbot.menu_data_cache import menu_cache

from ..constants import (
    WORD_TO_NUM,
    QUALIFIER_PATTERNS,
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
            skip_words = {'the', 'a', 'an', 'and', 'or', 'on', 'with', 'please', 'thanks'}
            if item.lower() in skip_words:
                continue
            if qualifier == 'no':
                instruction = f"no {item}"
            elif qualifier == 'on the side':
                instruction = f"{item} on the side"
            else:
                instruction = f"{qualifier} {item}"
            if instruction not in instructions:
                instructions.append(instruction)
                logger.debug(f"Extracted special instruction: '{instruction}' from input")

    # Check standalone patterns (e.g., "leave room", "cut in half", "melted")
    # Data-driven: patterns loaded from database via menu_cache
    for pattern in menu_cache.get_standalone_instruction_patterns():
        match = pattern.search(input_lower)  # Already compiled with IGNORECASE
        if match:
            instruction = match.group(0).strip()
            if instruction and instruction not in instructions:
                instructions.append(instruction)
                logger.debug(f"Extracted standalone instruction: '{instruction}' from input")

    return instructions


# =============================================================================
# Generic Attribute Value Extraction (Data-Driven)
# =============================================================================

def extract_attribute_values(
    user_input: str,
    item_type: str,
) -> dict[str, any]:
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
        # Match patterns like "no spread", "without spread", "skip spread"
        negation_pattern = rf'\b(?:no|without|skip)\s+{re.escape(attr_display)}\b'
        if re.search(negation_pattern, input_lower, re.IGNORECASE):
            # For multi_select, set to empty list; for others, set to None
            if attr_config.get("input_type") == "multi_select":
                result[attr_slug] = []
            else:
                result[attr_slug] = None
            negated_attrs.add(attr_slug)
            logger.debug(
                "Negation detected for attribute '%s': setting to %s",
                attr_slug, result[attr_slug]
            )

    def is_word_boundary(text: str, start: int, end: int) -> bool:
        """Check if the match is at word boundaries."""
        before_ok = start == 0 or not text[start - 1].isalnum()
        after_ok = end >= len(text) or not text[end].isalnum()
        return before_ok and after_ok

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
        If must_match is set, ALL patterns must be present.
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

        return all(pattern in text for pattern in must_match_list)

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
                    if is_word_boundary(input_lower, pos, end) and check_must_match(opt, input_lower):
                        candidates.append(CandidateMatch(
                            attr_slug=attr_slug,
                            option=opt,
                            pattern=pattern,
                            start=pos,
                            end=end,
                            length=len(pattern),
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

        # Record the match
        matched_spans.append((cand.start, cand.end))
        matched_options_per_attr.setdefault(cand.attr_slug, set()).add(slug)

        quantity = extract_quantity_before(input_lower, cand.start)
        match_data = {
            "slug": slug,
            "display_name": cand.option.get("display_name", slug),
            "quantity": quantity,
            "price": cand.option.get("price", 0),
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

def _slug_to_display(slug: str | None) -> str | None:
    """Convert slug to display format (underscores to spaces).

    Args:
        slug: Database slug (e.g., 'cinnamon_raisin', 'sun_dried_tomato')

    Returns:
        Display format (e.g., 'cinnamon raisin', 'sun dried tomato')
    """
    return slug.replace("_", " ") if slug else slug


def _extract_attribute_value(
    text: str,
    item_type: str,
    attr_slug: str
) -> str | bool | None:
    """Extract attribute value by looking up valid options from database.

    This is a generic replacement for item-specific extractors like
    _extract_size, _extract_iced, etc.

    Args:
        text: User input text (will be lowercased)
        item_type: Item type slug
        attr_slug: Attribute slug

    Returns:
        Matched option value (slug or boolean), or None if no match

    """
    text_lower = text.lower()

    # Get attribute config for this item type
    attrs = menu_cache.get_item_type_attributes(item_type)
    attr_config = attrs.get(attr_slug)

    if not attr_config:
        return None

    input_type = attr_config.get("input_type", "single_select")

    # Boolean attributes (toasted, decaf, scooped, etc.)
    # Use alias-based lookup via GlobalAttributeOptions (data-driven)
    if input_type == "boolean":
        # Try to resolve via global attribute options with aliases
        try:
            options = menu_cache.get_global_attribute_options(attr_slug)
            if options:
                matched = menu_cache.resolve_option_by_alias(attr_slug, text_lower)
                if matched:
                    return matched["slug"] == "true"
        except Exception:
            # No options configured for this boolean attribute, fall through to fallback
            pass

        # Fallback to generic yes/no patterns from response_patterns table
        if menu_cache.is_negative(text_lower):
            return False
        if menu_cache.is_affirmative(text_lower):
            return True
        return None

    # Single/multi select attributes - check options
    options = attr_config.get("options", [])

    # Sort by length descending to match longer options first
    # (e.g., "cinnamon raisin" before "plain")
    options_sorted = sorted(options, key=lambda o: len(o.get("slug", "")), reverse=True)

    for option in options_sorted:
        slug = option.get("slug", "").lower()
        display = option.get("display_name", "").lower()

        # Check canonical slug
        if slug and slug in text_lower:
            return slug

        # Check display name
        if display and display in text_lower:
            return slug

        # Check aliases
        for alias in option.get("aliases", []):
            alias_lower = alias.lower()
            if alias_lower in text_lower:
                return slug

    return None


def _extract_modifiers_generic(
    text: str,
    item_type: str
) -> list[str]:
    """Extract all modifiers for an item type from text.

    Uses the modifier category for the item type (food or beverage)
    to determine which modifier groups to search.

    Args:
        text: User input text (lowercase)
        item_type: Item type slug

    Returns:
        List of matched modifier names (normalized/canonical)
    """
    text_lower = text.lower()
    found_modifiers = []

    # Get modifier category for this item type (food or beverage)
    modifier_type = menu_cache.get_modifier_category(item_type)

    if modifier_type == "food":
        # Food modifiers: extracted in database-defined order (proteins, cheeses, toppings, spreads)
        for category in menu_cache.get_ordered_ingredient_categories("food"):
            # Get ingredients for this category
            ingredients = menu_cache.get_ingredients(category)
            for ingredient in ingredients:
                if ingredient.lower() in text_lower:
                    found_modifiers.append(ingredient.lower())

    elif modifier_type == "beverage":
        # Beverage modifiers are handled differently (syrups, sweeteners, milk)
        # These have quantities so they're extracted separately
        pass

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


def _extract_single_select_global_attribute(text: str, attr_slug: str) -> str | None:
    """Extract a single-select global attribute value from text (data-driven).

    This function looks up options for the given attribute from global_attribute_options
    and matches the user input against aliases defined for those options.

    Args:
        text: User input text
        attr_slug: The attribute slug (e.g., "bread", "spread", "size")

    Returns:
        The matched option slug if found, None otherwise.
    """
    text_lower = text.lower()

    try:
        options = menu_cache.get_global_attribute_options(attr_slug)
        if not options:
            return None

        # Build list of (alias, slug) tuples sorted by length descending
        alias_matches: list[tuple[str, str]] = []
        for opt in options:
            slug = opt.get("slug", "")
            # Add display_name as an alias
            display_name = opt.get("display_name", "").lower()
            if display_name:
                alias_matches.append((display_name, slug))
            # Add slug as words (underscores to spaces)
            slug_words = slug.replace("_", " ").lower()
            alias_matches.append((slug_words, slug))
            # Check the option's aliases
            aliases = opt.get("aliases", [])
            for alias in aliases:
                alias_matches.append((alias.lower(), slug))

        # Sort by length descending to match longer aliases first
        alias_matches.sort(key=lambda x: len(x[0]), reverse=True)

        # Check if any alias appears in the text
        for alias, slug in alias_matches:
            if alias in text_lower:
                return slug
    except Exception:
        # No options configured for this attribute
        pass

    return None


def _extract_side_item(text: str) -> tuple[str | None, int]:
    """Extract side item from text. Returns (side_item_name, quantity).

    Uses database lookup via menu_cache.resolve_side_alias() to map user input
    to canonical menu item names. If no match is found, returns None to allow
    graceful failure handling by the caller.

    Note: This replaces the hardcoded SIDE_ITEM_MAP constant.
    """
    text_lower = text.lower()

    side_match = re.search(r'\bside\s+of\s+(\w+(?:\s+\w+){0,2})', text_lower)
    if not side_match:
        return None, 1

    side_text = side_match.group(1).strip()

    # Try to resolve via database lookup
    canonical = menu_cache.resolve_side_alias(side_text)
    if canonical:
        return canonical, 1

    # Not found in database - return None for graceful failure
    # The caller should handle this case (e.g., show "we don't have that")
    logger.debug("Side item not found in database: %s", side_text)
    return None, 1
