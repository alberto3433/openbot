"""
Shared utilities for item configuration handlers.

Contains common functions used by config_modification_handler,
bundle_modification_handler, and modifier_addition_handler to avoid
code duplication.
"""

import logging
from typing import TYPE_CHECKING

from .models import OrderTask, MenuItemTask
from .schemas import StateMachineResult
from .pending_fields import PendingField
from .utils.pricing_utils import safe_recalculate_price
from orderbot.cache import menu_cache

if TYPE_CHECKING:
    from .config_helper_handler import ConfigHelperHandler
    from .checkout_utils_handler import CheckoutUtilsHandler
    from .modifier_change_handler import ModifierChangeHandler

logger = logging.getLogger(__name__)

# Pronouns that refer to the last item in the order.
# Used by item_modification_handler and parsers/deterministic/core.py.
LAST_ITEM_PRONOUNS = frozenset({
    "that", "it", "this", "last", "the last one", "the last item",
    "last one", "last item",
})

# Extended set that also includes order-level phrases used in cancellation parsing.
LAST_ITEM_PRONOUNS_EXTENDED = LAST_ITEM_PRONOUNS | frozenset({
    "from the order", "from my order",
})


def continue_config_with_message(
    config_helper_handler: "ConfigHelperHandler",
    checkout_utils_handler: "CheckoutUtilsHandler",
    message: str,
    item: MenuItemTask,
    order: OrderTask,
) -> StateMachineResult:
    """Return message + next config question, or proceed if item complete."""
    current_question = config_helper_handler.get_current_config_question(order, item)
    if current_question:
        return StateMachineResult(message=f"{message} {current_question}", order=order)
    return checkout_utils_handler.get_next_question(order)


def start_modifier_disambiguation(
    new_value: str,
    matches: list[dict],
    item: MenuItemTask,
    order: OrderTask,
) -> StateMachineResult:
    """Start disambiguation flow for a modifier with multiple matches."""
    order.pending_item_options = matches
    order.pending_field = PendingField.MODIFIER_SELECTION
    order.pending_modifier_target_item_index = order.items.items.index(item)

    option_lines = []
    for i, match in enumerate(matches[:6], 1):
        price_str = ""
        if match.get("base_price", 0) > 0:
            price_str = f" (+${match['base_price']:.2f})"
        option_lines.append(f"{i}. {match['name']}{price_str}")

    options_str = "\n".join(option_lines)
    qr = [{"label": m["name"], "value": m["name"]} for m in matches[:6] if m.get("name")]
    return StateMachineResult(
        message=f"Which {new_value} would you like?\n{options_str}",
        order=order,
        quick_replies=qr,
    )


def replace_or_add_modifier(
    item: MenuItemTask,
    match: dict,
    pricing: object | None,
    quantity: int = 1,
) -> None:
    """Replace existing modifier of same category, or add if none exists."""
    category = match["category"]
    item.remove_selection(category)
    item.add_selection(
        slug=match["slug"],
        category=category,
        display_name=match["name"],
        quantity=quantity,
        price=match.get("base_price", 0.0),
    )
    safe_recalculate_price(pricing, item, "after ingredient match")


def apply_attribute_option_to_item(
    modifier_lower: str,
    item: MenuItemTask,
) -> str | None:
    """Try to match and apply an attribute option to an item.

    Returns the display name of the matched option if applied, None if no match.
    """
    from .handler_utils import find_attr_option_match, get_option_display_name

    item_type = item.menu_item_type
    if not item_type:
        return None
    try:
        attrs = menu_cache.get_item_type_attributes(item_type)
        result = find_attr_option_match(modifier_lower, attrs)
        if result:
            attr_slug, opt = result
            item[attr_slug] = opt.get("slug")
            return get_option_display_name(opt)
    except (KeyError, AttributeError) as e:
        logger.debug("Error matching attribute option: %s", e)
    return None
