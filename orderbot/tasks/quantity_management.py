"""
Quantity Management Utilities.

Functions for duplicating items and handling quantity-related patterns
like "make it 2" and "already at target" responses.

Extracted from handler_utils.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from .utils.text import normalize_text

if TYPE_CHECKING:
    from .models import OrderTask
    from .schemas import StateMachineResult

logger = logging.getLogger(__name__)


def duplicate_last_item_to_qty(
    order: "OrderTask",
    target_qty: int,
    *,
    mark_complete: bool = False,
    count_existing: bool = True,
) -> tuple[int, str, int] | None:
    """Duplicate the last active item until the order has target_qty copies.

    Core logic shared by make-it-N handlers across state machine, checkout,
    and early_pattern_handler.

    Args:
        order: The current order task
        target_qty: Desired total quantity
        mark_complete: If True, duplicates are marked complete (checkout flow)
        count_existing: If True, counts existing copies and only adds the difference.
                        If False, always adds (target_qty - 1) copies.

    Returns:
        Tuple of (target_qty, last_item_name, added_count) or None if no active items.
        added_count may be 0 or negative if already at/over target.
    """
    from .handler_utils import get_last_item

    active_items = order.items.get_active_items()
    if not active_items:
        return None

    last_item = get_last_item(active_items)
    last_item_name = last_item.get_summary()

    if count_existing:
        current_count = sum(
            1 for item in active_items
            if item.get_summary() == last_item_name
        )
        added_count = target_qty - current_count
    else:
        added_count = target_qty - 1

    if added_count > 0:
        for _ in range(added_count):
            order.items.add_item(last_item.duplicate(mark_complete=mark_complete))
        logger.info("Added %d more of '%s' (now %d total)", added_count, last_item_name, target_qty)

    return target_qty, last_item_name, added_count


def handle_make_it_one(
    match: "re.Match",
    order: "OrderTask",
) -> "StateMachineResult | None":
    """Handle the 'make it 1' edge case where target quantity is 1.

    When ``extract_make_it_n_target`` returns ``None`` (qty < 2), check
    whether the user explicitly said "one" and respond with an
    "already have N" message instead of silently falling through.

    Returns:
        A result if qty == 1 was detected, ``None`` otherwise.
    """
    from .parsers.quantity_utils import BASIC_WORD_TO_NUM
    from .schemas import StateMachineResult
    from .checkout_messages import already_have_n_anything_else
    from .handler_utils import get_last_item

    for i in range(1, 15):
        try:
            group = match.group(i)
        except IndexError:
            break
        if group:
            raw = normalize_text(group)
            qty = int(raw) if raw.isdigit() else BASIC_WORD_TO_NUM.get(raw, 0)
            if qty == 1:
                active_items = order.items.get_active_items()
                if active_items:
                    last_item = get_last_item(active_items)
                    last_name = last_item.get_summary()
                    current_count = sum(
                        1 for it in active_items if it.get_summary() == last_name
                    )
                    return StateMachineResult(
                        message=already_have_n_anything_else(current_count, last_name),
                        order=order,
                    )
            break
    return None


def handle_already_at_target(
    order: "OrderTask",
    target_qty: int,
    added_count: int,
    last_item_name: str,
) -> "StateMachineResult | None":
    """Return an 'already have N' response when the user asks for a quantity
    they already have (or less).

    Returns:
        A result if ``added_count <= 0``, ``None`` otherwise.
    """
    if added_count > 0:
        return None

    from .schemas import StateMachineResult
    from .checkout_messages import already_have_n_anything_else

    current_count = target_qty - added_count  # reconstruct actual count
    return StateMachineResult(
        message=already_have_n_anything_else(current_count, last_item_name),
        order=order,
    )
