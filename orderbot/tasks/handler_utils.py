"""
Handler Utilities.

Shared utility functions used across multiple handlers for common patterns
like building item option lists, constructing selection questions, and
checking order state.

These utilities reduce code duplication and provide a single source of truth
for common handler operations.
"""

import logging
from typing import TYPE_CHECKING

from .utils.pricing_utils import safe_recalculate_price

if TYPE_CHECKING:
    from .models import OrderTask, MenuItemTask
    from .schemas import StateMachineResult
    from .pricing import PricingEngine

logger = logging.getLogger(__name__)


def build_quick_replies(names: list[str]) -> list[dict[str, str]]:
    """Build quick reply dicts from a list of display names.

    Covers the most common pattern: label and value are both the name.
    For custom label/value mappings, use a list comprehension instead.
    """
    return [{"label": name, "value": name} for name in names]


def build_item_options_list(active_items: list) -> list[dict]:
    """Build a list of item options for selection UI.

    Creates a standardized list of item information dicts suitable for
    disambiguation, duplicate selection, and other multi-item scenarios.

    Args:
        active_items: List of active items in the order (MenuItemTask instances)

    Returns:
        List of dicts with id, summary, and quantity for each item,
        in reverse order (most recent first)
    """
    item_options = []
    for item in reversed(active_items):
        item_options.append({
            "id": item.id,
            "summary": item.get_summary(),
            "quantity": item.quantity,
        })
    return item_options


def build_item_selection_question(
    item_options: list[dict],
    all_option_text: str = "all the items in your order",
) -> str:
    """Build a question asking user to select from multiple items.

    Creates a formatted question like:
    "Another Plain Bagel, another Iced Latte, or all the items in your order?"

    Args:
        item_options: List of item dicts with 'summary' key
        all_option_text: Text for the "all items" option (default: "all the items in your order")

    Returns:
        Formatted question string with first letter capitalized
    """
    question_parts = [f"another {opt['summary']}" for opt in item_options]
    question = ", ".join(question_parts) + f", or {all_option_text}?"
    # Capitalize first letter
    return question[0].upper() + question[1:]


def check_has_active_items(order: "OrderTask") -> tuple[list, "StateMachineResult | None"]:
    """Check if order has active items, returning error result if empty.

    Common pattern used throughout handlers to verify the order has items
    before performing operations on them.

    Args:
        order: The current order

    Returns:
        Tuple of (active_items, error_result):
        - If items exist: (list of items, None)
        - If no items: (empty list, StateMachineResult with error message)
    """
    from .schemas import StateMachineResult
    from .checkout_messages import ErrorMessages

    active_items = order.items.get_active_items()
    if not active_items:
        return [], StateMachineResult(
            message=ErrorMessages.NO_ITEMS_YET,
            order=order,
        )
    return active_items, None


def get_last_item(items: list) -> any:
    """Safely get the last item from a list.

    Handles empty lists gracefully by returning None instead of raising IndexError.
    Common pattern used when getting the most recently added item.

    Args:
        items: List of items (can be empty)

    Returns:
        The last item in the list, or None if list is empty
    """
    return items[-1] if items else None


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
    from orderbot.cache import menu_cache

    menu_items = [i for i in items if isinstance(i, MenuItemTask)]
    if not target_desc or not menu_items:
        return None

    target = target_desc.strip()

    # 1. Exact name match
    for item in menu_items:
        if item.menu_item_name and item.menu_item_name.lower() == target:
            return item

    # 2. Summary match (substring both directions)
    for item in menu_items:
        summary = item.get_summary().lower()
        if target in summary or summary in target:
            return item

    # 3. Word-boundary suffix on name
    for item in menu_items:
        name_lower = (item.menu_item_name or "").lower()
        if not name_lower:
            continue
        if name_lower.endswith(target) and (
            len(name_lower) == len(target)
            or name_lower[-(len(target) + 1)] == " "
        ):
            return item

    # 4. Name substring (both directions)
    for item in menu_items:
        name_lower = (item.menu_item_name or "").lower()
        if name_lower and (target in name_lower or name_lower in target):
            return item

    # 5. Word-level match (any word >2 chars from target in summary)
    for item in menu_items:
        summary = item.get_summary().lower()
        if any(word in summary for word in target.split() if len(word) > 2):
            return item

    # 6. Category reference (e.g. "the bagel" when only one bagel in order)
    target_category = menu_cache.is_category_reference(target)
    if target_category:
        matching = [i for i in menu_items if i.menu_item_type == target_category]
        if len(matching) == 1:
            return matching[0]

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

    text = user_input.strip().lower()

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


def is_configurable_menu_item(item: any) -> bool:
    """Check if item is a configurable MenuItemTask with a type.

    Common check used before accessing menu_item_type or applying
    type-specific configuration logic.

    Args:
        item: Any item to check

    Returns:
        True if item is a MenuItemTask with menu_item_type set
    """
    from .models import MenuItemTask
    return isinstance(item, MenuItemTask) and item.menu_item_type is not None


def recalculate_and_summarize(
    item: "MenuItemTask",
    pricing: any = None,
) -> str:
    """Recalculate item price and return its summary.

    Common pattern after modifying an item - recalculate its price
    and get the updated summary for display.

    Args:
        item: The item to update
        pricing: Optional PricingEngine for recalculation

    Returns:
        The item's summary string
    """
    safe_recalculate_price(pricing, item, "during recalculate_and_summarize")
    return item.get_summary()


def remove_item_from_order(order: "OrderTask", item: "MenuItemTask") -> bool:
    """Remove an item from the order by reference.

    Finds the item's index and removes it. This is a common pattern
    used throughout cancellation handlers.

    Args:
        order: The order containing the item
        item: The item to remove

    Returns:
        True if item was found and removed, False otherwise
    """
    try:
        idx = order.items.items.index(item)
        order.items.remove_item(idx)
        return True
    except ValueError:
        return False


def process_next_queued_item(
    order: "OrderTask",
    menu_item_handler,
    log_context: str = "",
) -> "StateMachineResult | None":
    """Process the next queued item for configuration.

    Common pattern used across handlers when completing one item's configuration
    and needing to check if there are more items waiting in the queue.

    Args:
        order: The current order with potential queued config items
        menu_item_handler: Handler with get_first_question() method
        log_context: Optional context string for logging (e.g., "after disambiguation")

    Returns:
        StateMachineResult if a queued item was processed, None otherwise
    """
    from .models import MenuItemTask, TaskStatus

    if not menu_item_handler:
        return None

    while order.has_queued_config_items():
        next_config = order.pop_next_config_item()
        if not next_config:
            return None

        next_item = order.items.get_item_by_id(next_config["item_id"])
        if not isinstance(next_item, MenuItemTask):
            continue

        # Skip already-complete items - they may have been completed via
        # _get_next_question path while still sitting in the queue
        if next_item.status == TaskStatus.COMPLETE:
            logger.info(
                "%sSkipping already-complete queued item %s (%s)",
                f"{log_context}: " if log_context else "",
                next_config.get("item_name"),
                next_config["item_id"][:8]
            )
            continue

        context_str = f"{log_context}: " if log_context else ""
        logger.info(
            "%sProcessing queued item %s (%s)",
            context_str,
            next_config.get("item_name"),
            next_config["item_id"][:8]
        )
        return menu_item_handler.get_first_question(next_item, order)

    return None
