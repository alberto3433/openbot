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

if TYPE_CHECKING:
    from .models import OrderTask, MenuItemTask
    from .schemas import StateMachineResult

logger = logging.getLogger(__name__)


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


def format_numbered_options(
    options: list[dict],
    name_key: str = "name",
    max_options: int = 6,
) -> str:
    """Format a list of options as numbered choices.

    Common pattern used for disambiguation, item selection, and menu displays.
    Creates output like:
        1. Plain Bagel
        2. Everything Bagel
        3. Sesame Bagel

    Args:
        options: List of option dicts
        name_key: Key to use for the display name (default: "name")
        max_options: Maximum number of options to show (default: 6)

    Returns:
        Formatted string with numbered options, newline-separated
    """
    option_list = [
        f"{i}. {item.get(name_key, 'Unknown')}"
        for i, item in enumerate(options[:max_options], 1)
    ]
    return "\n".join(option_list)


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


def find_items_by_keyword(
    items: list,
    keyword: str,
    variants: list[str] | None = None,
) -> list:
    """Find items matching a keyword by name or summary.

    Searches both item summary and menu_item_name for matches.
    Handles singular/plural variants automatically.

    Args:
        items: List of items to search
        keyword: The keyword to search for
        variants: Optional list of variants to check (e.g., singular/plural forms).
                  If not provided, generates variants from keyword.

    Returns:
        List of matching items
    """
    from orderbot.cache.base import get_singular_plural_variants

    if not items or not keyword:
        return []

    if variants is None:
        variants = list(get_singular_plural_variants(keyword.lower()))
    else:
        variants = [v.lower() for v in variants]

    matches = []
    for item in items:
        item_summary = item.get_summary().lower()
        item_name = getattr(item, 'menu_item_name', '') or ''
        item_name_lower = item_name.lower()

        if any(v in item_summary or v in item_name_lower for v in variants):
            matches.append(item)

    return matches


def resolve_and_normalize(text: str) -> str:
    """Resolve alias and return normalized (lowercase) name.

    Combines alias resolution with text normalization. If the text
    is a known alias, returns the resolved name; otherwise returns
    the original text, always lowercase.

    Args:
        text: The text to resolve and normalize

    Returns:
        Normalized name (lowercase), resolved if it was an alias
    """
    from orderbot.menu_data_cache import menu_cache

    text_lower = (text or "").lower().strip()
    if not text_lower:
        return ""

    resolved, _ = menu_cache.resolve_alias(text_lower)
    return (resolved or text_lower).lower()


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
    from orderbot.menu_data_cache import menu_cache

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
    if pricing:
        pricing.recalculate_item_price(item)
    return item.get_summary()


def get_newly_added_items(
    order: "OrderTask",
    items_before_count: int,
) -> list:
    """Get items added to order since a given count.

    Used to track items added during a multi-step operation.

    Args:
        order: The order to check
        items_before_count: Number of items before the operation

    Returns:
        List of newly added items
    """
    return order.items.items[items_before_count:]
