"""
Pricing utilities.

Helper functions for safe price operations across handlers.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import MenuItemTask
    from ..pricing import PricingEngine

logger = logging.getLogger(__name__)


def safe_recalculate_price(
    pricing: "PricingEngine | None",
    item: "MenuItemTask",
    log_context: str = "",
) -> float:
    """Safely recalculate an item's price, handling missing pricing engine.

    Unlike the direct call to pricing.recalculate_item_price() which assumes
    pricing is always available, this helper:
    - Returns the current price if pricing engine is None
    - Logs a warning (not an error) for debugging
    - Never raises an exception

    Use this in places where pricing is optional or when you want
    graceful degradation without breaking the flow.

    Args:
        pricing: The PricingEngine instance, may be None
        item: The MenuItemTask to recalculate price for
        log_context: Optional context string for the log message
            (e.g., "during modifier change" or "at checkout")

    Returns:
        The recalculated price, or current unit_price if pricing unavailable
    """
    if pricing is None:
        context_str = f" {log_context}" if log_context else ""
        logger.warning(
            "Cannot recalculate price for '%s'%s: PricingEngine not available. "
            "Using current unit_price: %.2f",
            item.menu_item_name or item.id,
            context_str,
            item.unit_price,
        )
        return item.unit_price

    return pricing.recalculate_item_price(item)


def safe_lookup_modifier_price(
    pricing: "PricingEngine | None",
    slug: str,
    item_type: str,
    category: str | None = None,
) -> float:
    """Safely look up a modifier price, handling missing pricing engine.

    Args:
        pricing: The PricingEngine instance, may be None
        slug: The modifier slug
        item_type: The item type slug
        category: Optional category for the modifier

    Returns:
        The modifier price, or 0.0 if pricing unavailable
    """
    if pricing is None:
        logger.debug(
            "Cannot lookup modifier price for '%s' (type=%s): PricingEngine not available",
            slug,
            item_type,
        )
        return 0.0

    return pricing.lookup_generic_modifier_price(slug, item_type, category) or 0.0
