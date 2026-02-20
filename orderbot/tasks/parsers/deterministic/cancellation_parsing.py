"""
Cancellation Parsing - Handles cancel all/last/N items and 'add more' patterns.

Parses user requests to remove items from the cart, including cancelling
specific items, the last item, all items, or the last N items.
"""

import re
import logging

from ...schemas import OpenInputResponse
from ..constants import CANCEL_LAST_ITEM, CANCEL_ALL_ITEMS, make_last_n_sentinel
from ..quantity_utils import QTY_WORDS_RE
from ..intent_patterns import CANCEL_ITEM_PATTERN
from ...config_flow_utils import LAST_ITEM_PRONOUNS_EXTENDED
from .modification_parsing import _parse_add_more_request
from .quantity_change_parsing import _parse_quantity_count

logger = logging.getLogger(__name__)


def _try_parse_cancellation(text: str) -> OpenInputResponse | None:
    """Check for cancel all/last/N items and 'add more' patterns.

    Args:
        text: Cleaned user input text.

    Returns:
        OpenInputResponse if matched, None otherwise.
    """
    # Check for cancellation phrases
    cancel_match = CANCEL_ITEM_PATTERN.match(text)
    if cancel_match:
        cancel_item = None
        # Check all capture groups dynamically (pattern may have varying number of groups)
        for i in range(1, CANCEL_ITEM_PATTERN.groups + 1):
            if cancel_match.group(i):
                cancel_item = cancel_match.group(i)
                break
        if cancel_item:
            cancel_item = cancel_item.strip()
            # Handle "all" / "everything" to clear entire order
            all_items_phrases = {
                "all", "everything", "all of it", "the order", "my order",
                "the whole order", "my whole order", "all items", "all the items",
                "the whole thing", "it all", "them all",
                # Without "the" prefix (pattern strips "the")
                "order", "whole order", "whole thing",
                # Cart-based phrases
                "cart", "the cart", "my cart",
            }
            if cancel_item.lower() in all_items_phrases:
                logger.info("Deterministic parse: cancel ALL items detected (phrase='%s')", cancel_item)
                return OpenInputResponse(cancel_item=CANCEL_ALL_ITEMS)
            if cancel_item.lower() in LAST_ITEM_PRONOUNS_EXTENDED:
                logger.info("Deterministic parse: cancellation of last item detected (pronoun='%s')", cancel_item)
                return OpenInputResponse(cancel_item=CANCEL_LAST_ITEM)

            # Handle "last N" or "last N items" - remove the last N items from cart
            last_n_match = re.match(
                rf"^last\s+(\d+|{QTY_WORDS_RE})"
                r"(?:\s+(?:items?|ones?))?$",
                cancel_item.lower()
            )
            if last_n_match:
                count = _parse_quantity_count(last_n_match.group(1))
                if count >= 1:
                    logger.info("Deterministic parse: remove last %d items detected", count)
                    return OpenInputResponse(cancel_item=make_last_n_sentinel(count))

            # Handle "N" or "N more" or "N items" - remove N items from the end
            # e.g., "remove 2", "remove 2 more", "remove two items"
            just_n_match = re.match(
                rf"^(\d+|{QTY_WORDS_RE})"
                r"(?:\s+(?:more|items?|ones?))?$",
                cancel_item.lower()
            )
            if just_n_match:
                count = _parse_quantity_count(just_n_match.group(1))
                if count >= 1:
                    logger.info("Deterministic parse: remove %d items detected", count)
                    return OpenInputResponse(cancel_item=make_last_n_sentinel(count))

            logger.info("Deterministic parse: cancellation detected, item='%s'", cancel_item)
            return OpenInputResponse(cancel_item=cancel_item)

    # Check for "add more" requests (add a third, add another, etc.)
    add_more_result = _parse_add_more_request(text)
    if add_more_result:
        return add_more_result

    return None
