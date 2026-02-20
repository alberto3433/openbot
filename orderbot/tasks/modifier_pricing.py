"""
Modifier Pricing Calculator.

Handles price lookups for modifiers (proteins, spreads, syrups, etc.).
Extracted from pricing.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from .normalization import normalize_to_slug
from .utils.cache_helpers import get_item_type_attributes
from .utils import OptionMatcher
from .utils.text import normalize_text
from orderbot.cache import menu_cache

if TYPE_CHECKING:
    from .pricing import PricingEngine

logger = logging.getLogger(__name__)


class ModifierPricingCalculator:
    """Calculates prices for item modifiers (add-ons like proteins, spreads, syrups).

    Looks up modifier prices from the item type's attribute options in the database,
    with a fallback to ingredient price contexts.
    """

    def __init__(self, pricing_engine: "PricingEngine") -> None:
        """Initialize with reference to pricing engine for shared lookups.

        Args:
            pricing_engine: PricingEngine instance for menu_data access
        """
        self._pricing = pricing_engine

    def lookup_generic_modifier_price(
        self,
        modifier_name: str,
        item_type: str,
        modifier_type: str | None = None,
    ) -> float:
        """Look up price for any modifier (protein, spread, syrup, etc.).

        Searches the specified item_type's attributes for a matching option.
        Does NOT fall back to other item types - if the modifier isn't configured
        for this item type, it returns 0.0 (free modifier) or the caller should
        ensure the modifier is configured in the database.

        Args:
            modifier_name: Name of the modifier (e.g., "ham", "oat milk", "vanilla")
            item_type: Item type to search (e.g., "bagel", "sized_beverage")
            modifier_type: Optional hint for which attribute to search (e.g., "milk", "syrup")

        Returns:
            Price modifier or 0.0 if not found (modifier is free or unconfigured)

        Raises:
            MenuDataNotLoadedError: If menu_data is not loaded or item_type doesn't exist
        """
        if not modifier_name:
            return 0.0

        normalized = normalize_to_slug(modifier_name)
        modifier_lower = normalize_text(modifier_name)

        # Use cache helper for validated attribute lookup (raises MenuDataNotLoadedError)
        attributes = get_item_type_attributes(
            self._pricing._menu_data,
            item_type,
            f"look up modifier price for '{modifier_name}'",
        )

        # Import the module-level helper from pricing
        from .pricing import _lookup_option_price_in_attributes

        price, attr_slug = _lookup_option_price_in_attributes(
            attributes,
            normalized,
            modifier_lower,
            modifier_type_hint=modifier_type,
        )

        if price is not None:
            logger.debug(
                "Found modifier price: %s = $%.2f (from %s.%s)",
                modifier_name, price, item_type, attr_slug
            )
            return price

        # Fallback: Check ingredient price contexts (for ingredients not in attribute options)
        ing_price = menu_cache.get_ingredient_price_for_item_type(modifier_name, item_type)
        if ing_price is not None and ing_price > 0:
            logger.debug(
                "Found ingredient price: %s = $%.2f (from ingredient contexts for %s)",
                modifier_name, ing_price, item_type
            )
            return ing_price

        # Not found in this item type - return 0.0 (modifier is free or unconfigured)
        # This is not an error - some modifiers may not have prices
        logger.debug(
            "Modifier '%s' not found in item_type '%s'. Returning $0.00.",
            modifier_name, item_type
        )
        return 0.0

    def lookup_modifier_price(self, modifier_name: str, item_type: str) -> float:
        """Look up price modifier for an item add-on (protein, cheese, topping).

        Like lookup_generic_modifier_price, but first resolves database aliases
        (e.g., "lox" -> "Nova Scotia Salmon") before looking up the price.

        Args:
            modifier_name: Name of the modifier (e.g., "ham", "egg", "lox")
            item_type: Item type to look up (required, no default)

        Returns:
            Price modifier (e.g., 2.00 for ham) or 0.0 if modifier is free/unconfigured

        Raises:
            MenuDataNotLoadedError: If menu_data is not available or item_type doesn't exist
        """
        # Resolve database alias (e.g., "lox" -> "Nova Scotia Salmon")
        canonical_name = menu_cache.normalize_modifier(modifier_name.lower().strip())
        return self.lookup_generic_modifier_price(canonical_name, item_type)
