"""
Quantity Change Parsing - Handles make-it-N and reduce-to-one patterns.

Parses user requests to change the quantity of items already in the cart,
such as "make it 2" or "just one bagel".
"""

import logging

from orderbot.cache import menu_cache
from orderbot.cache.base import singularize

from ...schemas import OpenInputResponse
from ..constants import REDUCE_TO_ONE, make_reduce_to_one_sentinel
from ..quantity_utils import extract_make_it_n_target, BASIC_WORD_TO_NUM
from ..intent_patterns import MAKE_IT_N_PATTERN, REDUCE_TO_ONE_PATTERN

logger = logging.getLogger(__name__)


def _try_parse_quantity_change(text: str) -> OpenInputResponse | None:
    """Check for make-it-N and reduce-to-one patterns.

    Args:
        text: Cleaned user input text.

    Returns:
        OpenInputResponse if matched, None otherwise.
    """
    # Check for "make it 2" patterns BEFORE replacement (since "make it X" could match both)
    make_it_n_match = MAKE_IT_N_PATTERN.match(text)
    if make_it_n_match:
        target_qty = extract_make_it_n_target(make_it_n_match)
        if target_qty is not None:
            # User says "make it 2" means they want 2 total, so add (target - 1) more
            additional = target_qty - 1
            logger.info(
                "Deterministic parse: 'make it N' detected, target=%d, adding %d more",
                target_qty, additional,
            )
            return OpenInputResponse(duplicate_last_item=additional)

    # Check for "just one" / "only one" patterns - reduces quantity to 1
    # e.g., "actually just one bagel", "only one", "just one"
    reduce_to_one_match = REDUCE_TO_ONE_PATTERN.match(text)
    if reduce_to_one_match:
        # Extract item type if specified (any of the capture groups)
        item_type = None
        all_item_type_slugs = menu_cache.get_configurable_item_types()
        for i in range(1, 6):  # Check all capture groups
            if reduce_to_one_match.group(i):
                item_type = reduce_to_one_match.group(i).lower()
                # Normalize plurals using data-driven approach:
                # Check if the word matches an item type, if not try singular form
                if item_type not in all_item_type_slugs:
                    singular = singularize(item_type)
                    if singular in all_item_type_slugs:
                        item_type = singular
                break

        # Return special cancel_item value to signal quantity reduction
        if item_type:
            cancel_value = make_reduce_to_one_sentinel(item_type)
        else:
            cancel_value = REDUCE_TO_ONE

        logger.info(
            "Deterministic parse: 'just/only one' detected, reducing to 1 (item_type=%s)",
            item_type or "any",
        )
        return OpenInputResponse(cancel_item=cancel_value)

    return None


def _parse_quantity_count(num_str: str) -> int:
    """Convert a digit string or number word to an integer count.

    Args:
        num_str: A digit string ("2") or number word ("two").

    Returns:
        The integer count, or 0 if unrecognized.
    """
    if num_str.isdigit():
        return int(num_str)
    return BASIC_WORD_TO_NUM.get(num_str.lower(), 0)
