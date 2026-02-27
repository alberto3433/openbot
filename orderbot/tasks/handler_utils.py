"""
Handler Utilities.

Shared utility functions used across multiple handlers for common patterns
like building item option lists, constructing selection questions, and
checking order state.

These utilities reduce code duplication and provide a single source of truth
for common handler operations.
"""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from .utils.pricing_utils import safe_recalculate_price
from .utils.text import normalize_text, name_with_prefix

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


def get_option_display_name(option: dict) -> str:
    """Get human-readable display name for an attribute option.

    Falls back to formatting the slug if no display_name is set.

    Args:
        option: Option dict with 'display_name' and/or 'slug' keys

    Returns:
        Human-readable display name
    """
    from .normalization import format_slug_for_display
    return option.get("display_name") or format_slug_for_display(option.get("slug", ""))


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
    question_parts = [name_with_prefix("another", opt['summary']) for opt in item_options]
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


def get_last_item(items: list) -> "ItemTask | None":
    """Safely get the last item from a list.

    Handles empty lists gracefully by returning None instead of raising IndexError.
    Common pattern used when getting the most recently added item.

    Args:
        items: List of items (can be empty)

    Returns:
        The last item in the list, or None if list is empty
    """
    return items[-1] if items else None


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
    import re  # noqa: F811 — local import for type hint

    from .parsers.quantity_utils import BASIC_WORD_TO_NUM
    from .schemas import StateMachineResult
    from .checkout_messages import already_have_n_anything_else

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


def is_configurable_menu_item(item: object) -> bool:
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
    pricing: "PricingEngine | None" = None,
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


def build_removal_response(
    order: "OrderTask",
    removed_name: str,
    configure_next_incomplete: Callable[["OrderTask"], "StateMachineResult"] | None = None,
) -> "StateMachineResult":
    """Build response after item removal, continuing config if needed.

    Shared logic for item_cancellation_handler and config_cancellation_handler.
    Checks remaining items and either continues configuration for an incomplete
    item, asks "Anything else?", or prompts for a new order.

    Args:
        order: The current order task
        removed_name: Display name of the removed item
        configure_next_incomplete: Optional callback to get config question
            for the next incomplete item

    Returns:
        StateMachineResult with appropriate message
    """
    from .models import MenuItemTask, TaskStatus
    from .schemas import StateMachineResult
    from .checkout_messages import ok_removed_anything_else

    remaining = order.items.get_active_items()

    if remaining and configure_next_incomplete:
        for item in remaining:
            if isinstance(item, MenuItemTask) and item.status == TaskStatus.IN_PROGRESS:
                config_result = configure_next_incomplete(order)
                return StateMachineResult(
                    message=f"OK, I've removed the {removed_name}. {config_result.message}",
                    order=order,
                )

    if remaining:
        return StateMachineResult(
            message=ok_removed_anything_else(removed_name),
            order=order,
        )
    else:
        return StateMachineResult(
            message=f"OK, I've removed the {removed_name}. What would you like to order?",
            order=order,
        )


def find_attr_option_match(
    modifier_lower: str,
    attrs: dict,
    use_fuzzy: bool = True,
) -> tuple[str, dict] | None:
    """Find first attribute option matching modifier_lower.

    Two-pass matching used by config_modification_handler:
    Pass 1: exact slug/display_name/alias match.
    Pass 2 (if use_fuzzy): OptionMatcher partial match.

    Args:
        modifier_lower: The modifier text, lowercased.
        attrs: Dict of attr_slug → attr_config from menu_cache.
        use_fuzzy: Whether to try OptionMatcher partial matching.

    Returns:
        Tuple of (attr_slug, matched_option_dict) or None if no match.
    """
    from .utils.option_matcher import OptionMatcher

    # Pass 1: Exact matching on slug, display_name, and aliases
    for attr_slug, attr_config in attrs.items():
        options = attr_config.get("options", [])
        for opt in options:
            opt_slug = opt.get("slug", "").lower()
            opt_display = opt.get("display_name", "").lower()
            aliases = opt.get("aliases") or []
            alias_list = [normalize_text(a) for a in aliases] if aliases else []
            if modifier_lower == opt_slug or modifier_lower == opt_display or modifier_lower in alias_list:
                return (attr_slug, opt)

    # Pass 2: Partial matching via OptionMatcher
    if use_fuzzy:
        matcher = OptionMatcher()
        for attr_slug, attr_config in attrs.items():
            options = attr_config.get("options", [])
            if not options:
                continue
            matched, _ = matcher.match_single(modifier_lower, options)
            if matched:
                return (attr_slug, matched)

    return None
