"""
Item Matching Utilities.

Functions for matching user-described items against items in the order,
using multiple strategies from most specific to least specific.

Extracted from handler_utils.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from .utils.text import normalize_text

if TYPE_CHECKING:
    from .models import MenuItemTask

logger = logging.getLogger(__name__)


def _match_by_exact_name(target: str, menu_items: list) -> "MenuItemTask | None":
    """Strategy 1: exact name match."""
    for item in menu_items:
        if item.menu_item_name and item.menu_item_name.lower() == target:
            return item
    return None


def _match_by_summary(target: str, menu_items: list) -> "MenuItemTask | None":
    """Strategy 2: substring match in both directions against get_summary()."""
    for item in menu_items:
        summary = item.get_summary().lower()
        if target in summary or summary in target:
            return item
    return None


def _match_by_name_suffix(target: str, menu_items: list) -> "MenuItemTask | None":
    """Strategy 3: word-boundary suffix match on menu_item_name."""
    for item in menu_items:
        name_lower = (item.menu_item_name or "").lower()
        if not name_lower:
            continue
        if name_lower.endswith(target) and (
            len(name_lower) == len(target)
            or name_lower[-(len(target) + 1)] == " "
        ):
            return item
    return None


def _match_by_name_substring(target: str, menu_items: list) -> "MenuItemTask | None":
    """Strategy 4: substring match in both directions against menu_item_name."""
    for item in menu_items:
        name_lower = (item.menu_item_name or "").lower()
        if name_lower and (target in name_lower or name_lower in target):
            return item
    return None


def _match_by_word(target: str, menu_items: list) -> "MenuItemTask | None":
    """Strategy 5: any word >2 chars from target appears in summary."""
    for item in menu_items:
        summary = item.get_summary().lower()
        if any(word in summary for word in target.split() if len(word) > 2):
            return item
    return None


def _match_by_category(target: str, menu_items: list) -> "MenuItemTask | None":
    """Strategy 6: category reference (e.g. 'the bagel' when only one bagel in order)."""
    from orderbot.cache import menu_cache

    target_category = menu_cache.is_category_reference(target)
    if target_category:
        matching = [i for i in menu_items if i.menu_item_type == target_category]
        if len(matching) == 1:
            return matching[0]
    return None


# Ordered list of matching strategies (most specific → least specific)
_MATCH_STRATEGIES = [
    _match_by_exact_name,
    _match_by_summary,
    _match_by_name_suffix,
    _match_by_name_substring,
    _match_by_word,
    _match_by_category,
]


def find_matching_item(
    target_desc: str,
    items: list,
) -> "MenuItemTask | None":
    """Find an item matching a target description using multiple strategies.

    Does NOT handle pronoun resolution or implicit/empty targets — callers
    handle those concerns before calling.

    Matching order (most specific to least specific):
    1. Exact name match
    2. Summary match (substring both directions)
    3. Word-boundary suffix on name
    4. Name substring (both directions)
    5. Word-level match (any word >2 chars from target in summary)
    6. Category reference (single item of that type)

    Args:
        target_desc: Lowercased target description to match against.
        items: List of items to search (filters to MenuItemTask internally).

    Returns:
        The matching MenuItemTask, or None if no match found.
    """
    from .models import MenuItemTask

    menu_items = [i for i in items if isinstance(i, MenuItemTask)]
    if not target_desc or not menu_items:
        return None

    target = target_desc.strip()

    for strategy in _MATCH_STRATEGIES:
        result = strategy(target, menu_items)
        if result is not None:
            return result

    return None


def match_item_from_options(
    user_input: str,
    item_options: list[dict],
) -> dict | None:
    """Match user input to one of the provided item options.

    Uses multiple matching strategies:
    1. Exact summary match
    2. Numeric selection (1, 2, 3...)
    3. Word-based partial matching with scoring

    Args:
        user_input: The user's input text
        item_options: List of item dicts with 'id', 'summary', 'quantity' keys

    Returns:
        The matched item dict, or None if no match found
    """
    from orderbot.cache import menu_cache

    if not item_options or not user_input:
        return None

    text = normalize_text(user_input)

    # Try numeric selection first (1, 2, 3, etc.)
    if text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < len(item_options):
            return item_options[idx]

    # Try alias resolution
    resolved_name, _ = menu_cache.resolve_alias(text)
    normalized_text = (resolved_name or text).lower()

    # Try exact match on summary
    for item_info in item_options:
        summary_lower = item_info["summary"].lower()
        if normalized_text == summary_lower:
            return item_info

    # Score-based matching
    matched_item = None
    best_match_score = 0

    for item_info in item_options:
        summary_lower = item_info["summary"].lower()
        score = 0

        # Check if input is contained in summary or vice versa
        if normalized_text in summary_lower:
            score += 3
        if summary_lower in normalized_text:
            score += 2

        # Word-level matching
        input_words = set(normalized_text.split())
        summary_words = set(summary_lower.split())
        common_words = input_words & summary_words
        # Filter out common stop words
        meaningful_common = {w for w in common_words if len(w) > 2}
        score += len(meaningful_common)

        if score > best_match_score:
            best_match_score = score
            matched_item = item_info

    # Only return if we have a reasonable match
    if best_match_score >= 2:
        return matched_item

    return None
