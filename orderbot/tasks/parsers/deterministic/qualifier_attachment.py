"""
Qualifier Attachment and Duplicate Filtering.

This module contains post-parse functions for attaching qualifiers
(position, amount) to selections and filtering duplicate special
instructions. Also handles partial modifier split detection.

Split from item_parsing.py during refactoring.
"""

import re
import logging

from orderbot.cache import menu_cache

from ...schemas import (
    OpenInputResponse,
    Selection,
    ParsedItemEntry,
)
from ..constants import (
    WORD_TO_NUM,
    get_items_with_defaults_aliases,
)
from ..quantity_utils import extract_quantity_for_pattern

# Import from specialized modules
from .item_building import build_parsed_item

logger = logging.getLogger(__name__)


def _filter_duplicate_instructions(
    special_instructions: list[str],
    attr_result,
    modifier_selections: list[Selection],
    item_name: str = "",
) -> list[str]:
    """Filter out special instructions already captured as attribute or modifier selections.

    For example, if "shot" is in attr_result.values, the instruction "extra shot" is
    redundant and should be removed. Also filters instructions whose base word matches
    the item name itself (e.g., "coffee on the side" when ordering a Hot Coffee).

    Returns:
        Filtered list of special instructions with duplicates removed.
    """
    # Build set of all selection slugs from attr_result.values and modifiers
    captured_slugs: set[str] = set()
    for attr_key, attr_val in attr_result.values.items():
        if isinstance(attr_val, list):
            # Multi-select: extract slugs from list items
            for item in attr_val:
                if isinstance(item, dict) and item.get("slug"):
                    captured_slugs.add(item["slug"].lower())
        elif isinstance(attr_val, str):
            captured_slugs.add(attr_val.lower())
    for sel in modifier_selections:
        captured_slugs.add(sel.slug.lower())

    # Build set of item name words for filtering instructions that reference the item itself
    # e.g., "Hot Coffee" -> {"hot", "coffee"}
    item_name_words = {w.lower() for w in item_name.split()} if item_name else set()

    # Filter instructions: remove if the item word matches a captured slug
    # "extra shot" -> check if "shot" is captured
    # "light cream cheese" -> check if "cream cheese" is captured
    filtered_instructions = []
    for instr in special_instructions:
        # Extract the item part from instruction (e.g., "extra shot" -> "shot")
        instr_lower = instr.lower()
        item_word = instr_lower
        for prefix in ["extra ", "light ", "no ", "heavy "]:
            if instr_lower.startswith(prefix):
                item_word = instr_lower[len(prefix):].strip()
                break
        # Check if suffix is a position qualifier (e.g., "on the side") and remove
        # These are loaded from the database via modifier_qualifiers table
        for pattern in menu_cache.get_qualifier_patterns():
            qualifier_info = menu_cache.get_qualifier_info(pattern)
            if qualifier_info and qualifier_info.get("category") == "position":
                suffix = f" {pattern}"
                if item_word.endswith(suffix):
                    item_word = item_word[:-len(suffix)].strip()
                    break

        # If item_word is already captured as a selection, skip this instruction
        # Also check suffix match (e.g., "cheese" matches "blueberry_cream_cheese")
        # Also filter if item_word matches the item name itself (e.g., "coffee" for "Hot Coffee")
        item_word_slug = item_word.replace(" ", "_")
        if (item_word_slug in captured_slugs
                or any(s.endswith(f"_{item_word_slug}") for s in captured_slugs)
                or any(s.startswith(f"{item_word_slug}_") for s in captured_slugs)):
            logger.debug("Filtering duplicate instruction '%s' - already captured as selection", instr)
            continue
        if item_name_words and any(
            w in item_name_words for w in item_word.split() if len(w) >= 3
        ):
            logger.debug("Filtering instruction '%s' - references the item itself ('%s')", instr, item_name)
            continue
        filtered_instructions.append(instr)
    return filtered_instructions


def _attach_position_qualifiers(parsed_item: ParsedItemEntry, text_lower: str) -> None:
    """Attach position qualifiers (e.g., 'on the side') to matching selections.

    When a user says 'blueberry cream cheese on the side', the qualifier should
    attach to the spread selection rather than creating a separate instruction.

    Mutates parsed_item in place: updates selection display_name and removes
    redundant special instructions.

    Args:
        parsed_item: The parsed item entry to modify
        text_lower: Lowercased original user input text
    """
    qualifier_patterns = menu_cache.get_qualifier_patterns()

    for pattern in qualifier_patterns:
        qualifier_info = menu_cache.get_qualifier_info(pattern)
        if not qualifier_info or qualifier_info.get("category") != "position":
            continue

        # Check if this qualifier appears in the text at all
        if pattern not in text_lower:
            continue

        normalized_form = qualifier_info.get("normalized_form", pattern)

        # For each selection, check if "{slug_as_words} {qualifier}" appears in text
        for sel in parsed_item.selections:
            slug_words = sel.slug.replace("_", " ")
            words = slug_words.split()
            # Try full slug, then progressively shorter suffixes
            # e.g., "whole milk" -> try "whole milk", then "milk"
            matched = False
            for i in range(len(words)):
                suffix = " ".join(words[i:])
                combined = rf'\b{re.escape(suffix)}\s+{re.escape(pattern)}\b'
                if re.search(combined, text_lower):
                    matched = True
                    break
            if not matched:
                continue

            # Match found - attach qualifier to this selection's display_name
            display_name = sel.display_name
            if not display_name:
                display_name = menu_cache.get_global_option_display_name(
                    sel.category, sel.slug
                )
            if not display_name:
                display_name = sel.slug.replace("_", " ").title()

            qualifier_tag = f"({normalized_form})"
            if qualifier_tag not in display_name:
                sel.display_name = f"{display_name} {qualifier_tag}"
            else:
                sel.display_name = display_name

            # Remove redundant special instructions whose base word is part
            # of the matched slug (e.g., "cheese on the side" where "cheese"
            # is a component of "blueberry_cream_cheese")
            slug_parts = sel.slug.lower().split("_")
            kept = []
            for instr in parsed_item.special_instructions:
                instr_lower = instr.lower()
                if pattern in instr_lower:
                    base_word = instr_lower.replace(pattern, "").strip()
                    if base_word in slug_parts:
                        logger.debug(
                            "Removing redundant instruction '%s' - covered by '%s'",
                            instr, sel.display_name,
                        )
                        continue
                kept.append(instr)
            parsed_item.special_instructions = kept

            logger.debug(
                "Attached qualifier '%s' to selection '%s' -> '%s'",
                normalized_form, sel.slug, sel.display_name,
            )


def _attach_amount_qualifiers(parsed_item: ParsedItemEntry, text_lower: str) -> None:
    """Attach amount qualifiers (e.g., 'extra', 'light') to matching selections.

    When a user says 'coffee with extra milk', the qualifier should attach to the
    milk selection rather than creating a separate instruction. Amount qualifiers
    appear BEFORE the modifier (e.g., "extra milk") unlike position qualifiers
    which appear after ("milk on the side").

    Mutates parsed_item in place: updates selection display_name and removes
    redundant special instructions.

    Args:
        parsed_item: The parsed item entry to modify
        text_lower: Lowercased original user input text
    """
    qualifier_patterns = menu_cache.get_qualifier_patterns()

    for pattern in qualifier_patterns:
        qualifier_info = menu_cache.get_qualifier_info(pattern)
        if not qualifier_info or qualifier_info.get("category") == "position":
            continue  # Only handle non-position (amount) qualifiers

        if pattern not in text_lower:
            continue

        normalized_form = qualifier_info.get("normalized_form", pattern)

        for sel in parsed_item.selections:
            slug_words = sel.slug.replace("_", " ")
            words = slug_words.split()
            matched = False
            for i in range(len(words)):
                suffix = " ".join(words[i:])
                # Amount qualifiers come BEFORE the modifier: "extra milk", "lots of milk"
                # Allow optional filler words between qualifier and modifier
                combined = rf'\b{re.escape(pattern)}\s+(?:\w+\s+)*?{re.escape(suffix)}\b'
                if re.search(combined, text_lower):
                    matched = True
                    break
            if not matched:
                continue

            # Attach qualifier to display_name
            display_name = sel.display_name
            if not display_name:
                display_name = menu_cache.get_global_option_display_name(
                    sel.category, sel.slug
                )
            if not display_name:
                display_name = sel.slug.replace("_", " ").title()

            qualifier_tag = f"({normalized_form})"
            if qualifier_tag not in display_name:
                sel.display_name = f"{display_name} {qualifier_tag}"
            else:
                sel.display_name = display_name

            # Remove redundant special instructions whose base word is part
            # of the matched slug (e.g., "extra milk" where "milk" is in slug_parts)
            slug_parts = sel.slug.lower().split("_")
            kept = []
            for instr in parsed_item.special_instructions:
                instr_lower = instr.lower()
                if normalized_form in instr_lower or pattern in instr_lower:
                    base_word = instr_lower
                    for prefix in [f"{normalized_form} ", f"{pattern} "]:
                        if base_word.startswith(prefix):
                            base_word = base_word[len(prefix):].strip()
                            break
                    base_words = base_word.split()
                    if base_words and all(w in slug_parts for w in base_words):
                        logger.debug(
                            "Removing redundant instruction '%s' - covered by '%s'",
                            instr, sel.display_name,
                        )
                        continue
                kept.append(instr)
            parsed_item.special_instructions = kept

            logger.debug(
                "Attached amount qualifier '%s' to selection '%s' -> '%s'",
                normalized_form, sel.slug, sel.display_name,
            )


def _handle_partial_modifier_split(
    text: str,
    text_lower: str,
    detected_item_type: str,
    item_name: str,
    quantity: int,
    has_defaults: bool,
    special_instructions: list[str],
) -> OpenInputResponse | None:
    """Check for and handle partial-modifier split patterns.

    Detects patterns like "4 coffees 2 with milk" where a subset of items should
    have modifiers applied (2 with milk, 2 plain).

    Returns:
        OpenInputResponse with split items if a split was detected, None otherwise.
    """
    from .item_parsing import _detect_partial_modifier_split

    # Try to find the item name in text. Item name like "Hot Coffee" may appear as "coffees".
    # First try full name match, then try individual words.
    item_name_lower = item_name.lower()
    item_name_match = re.search(rf'\b{re.escape(item_name_lower)}s?\b', text_lower)
    if not item_name_match:
        # Try matching individual words (e.g., "coffee" from "Hot Coffee")
        for word in item_name_lower.split():
            if len(word) >= 3:  # Skip short words like "a", "an", "the"
                item_name_match = re.search(rf'\b{re.escape(word)}s?\b', text_lower)
                if item_name_match:
                    break
    if not item_name_match:
        return None

    text_after_item = text_lower[item_name_match.end():]
    split_result = _detect_partial_modifier_split(text_after_item, quantity)
    if not split_result:
        return None

    split_qty, modifier_text = split_result
    remaining_qty = quantity - split_qty

    logger.info(
        "PARTIAL_SPLIT: detected %d with '%s', %d unmodified",
        split_qty, modifier_text, remaining_qty
    )

    # Extract BASE attributes from text BEFORE the split point
    # e.g., "4 large hot coffees 2 with milk" -> base text is "4 large hot coffees"
    from .pipeline import get_pipeline
    text_before_split = text_lower[:item_name_match.end()]
    base_attr_result = get_pipeline().extract_attributes(text_before_split, detected_item_type)

    # Also extract any attribute values from modifier text
    split_attr_result = get_pipeline().extract_attributes(modifier_text, detected_item_type)
    split_matched_spans = [(s.start, s.end) for s in split_attr_result.matched_spans]

    # Extract modifiers from "with X" portion only
    # Pass exclude_spans to avoid double-extraction of attributes
    split_modifiers = get_pipeline().extract_modifiers_raw(modifier_text, detected_item_type, exclude_spans=split_matched_spans)
    modifier_selections_split: list[Selection] = []
    for mod in split_modifiers:
        category = menu_cache.get_ingredient_category(mod)
        mod_qty = extract_quantity_for_pattern(modifier_text, mod)
        modifier_selections_split.append(Selection(
            slug=mod, category=category, quantity=mod_qty
        ))

    # Merge base + split attributes: split overrides base
    merged_attr_result = base_attr_result.merge_with(split_attr_result)

    # Build items WITH modifiers
    items_with_mods = build_parsed_item(
        item_type=detected_item_type,
        item_name=item_name,
        quantity=split_qty,
        attr_result=merged_attr_result,
        modifiers=modifier_selections_split,
        original_text=text,
        special_instructions=special_instructions,
    )

    # Build items WITHOUT modifiers (plain)
    items_plain = build_parsed_item(
        item_type=detected_item_type,
        item_name=item_name,
        quantity=remaining_qty,
        attr_result=base_attr_result,
        modifiers=[],
        original_text=text,
        special_instructions=[],
    )

    return OpenInputResponse(parsed_items=[items_with_mods, items_plain])
