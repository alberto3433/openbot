"""
Attribute Pricing Lookup.

Handles price lookups for attribute option upcharges (bread type, milk, size, etc.).
Extracted from pricing.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from .normalization import normalize_to_slug
from .utils.cache_helpers import get_item_type_attributes
from .utils import OptionMatcher
from .utils.text import normalize_text

if TYPE_CHECKING:
    from .pricing import PricingEngine

logger = logging.getLogger(__name__)


class AttributePricingLookup:
    """Looks up price modifiers for attribute options.

    Handles upcharge calculations for attribute values like bread type,
    milk choice, size, etc. Considers included ingredient categories
    to waive upcharges when appropriate.
    """

    def __init__(self, pricing_engine: "PricingEngine") -> None:
        """Initialize with reference to pricing engine for shared lookups.

        Args:
            pricing_engine: PricingEngine instance for menu_data access
        """
        self._pricing = pricing_engine

    def lookup_attribute_option_upcharge(
        self,
        item_type: str,
        attr_slug: str,
        option_value: str,
        included_ingredient_categories: set[str] | None = None,
    ) -> float:
        """Look up price modifier for an attribute option.

        Generic method to get upcharges for any attribute option (size, bread type,
        milk, syrup, etc.) from the database.

        If the menu item already includes an ingredient in the same category as the
        selected option, the upcharge is skipped (returns 0.0). This handles cases
        like BEC where cheese is included - selecting cheese type shouldn't upcharge.

        Args:
            item_type: Item type slug (e.g., "bagel", "sized_beverage")
            attr_slug: Attribute slug (e.g., "size", "bread", "milk")
            option_value: Selected option value (e.g., "large", "gluten_free", "oat")
            included_ingredient_categories: Set of ingredient categories already
                included in the menu item's base price (e.g., {"cheese", "protein"})

        Returns:
            Price modifier (upcharge) for the option, or 0.0 if not found or if
            the option's category is already included in the menu item
        """
        if not option_value:
            return 0.0

        normalized = normalize_to_slug(option_value)
        option_lower = normalize_text(option_value)

        if not self._pricing._menu_data:
            logger.warning("No menu_data available for attribute upcharge lookup")
            return 0.0

        attributes = get_item_type_attributes(
            self._pricing._menu_data, item_type,
            f"look up attribute upcharge for '{option_value}'",
        )

        from .pricing import _lookup_option_price_in_attributes

        price, _ = _lookup_option_price_in_attributes(
            attributes,
            normalized,
            option_lower,
            target_attr_slug=attr_slug,
        )

        if price is not None:
            # Check inclusion BEFORE returning price — if the menu item already
            # includes an ingredient in this category, the upcharge is waived.
            if included_ingredient_categories and price > 0:
                option_category = self.get_option_ingredient_category(
                    item_type, attr_slug, option_value
                )
                if option_category and option_category in included_ingredient_categories:
                    min_price = self.get_min_option_price_for_attribute(
                        item_type, attr_slug, option_category
                    )
                    premium = max(0.0, price - min_price)
                    logger.debug(
                        "Category '%s' included for %s.%s=%s — price=$%.2f, min=$%.2f, premium=$%.2f",
                        option_category, item_type, attr_slug, option_value, price, min_price, premium
                    )
                    return premium
            return price

        # Not found - log and return 0.0
        logger.debug(
            "Attribute option upcharge not found: %s.%s=%s",
            item_type, attr_slug, option_value
        )
        return 0.0

    def lookup_attribute_option_upcharge_for_item(
        self,
        menu_item_name: str,
        item_type: str,
        attr_slug: str,
        option_value: str,
    ) -> float:
        """Look up upcharge for an attribute option, considering included ingredients.

        Convenience method that automatically looks up the menu item's included
        ingredient categories and applies the "included = no upcharge" logic.

        Use this method when you have the menu item name but don't have the
        included categories already computed.

        Args:
            menu_item_name: Name of the menu item (for looking up included categories)
            item_type: Item type slug
            attr_slug: Attribute slug
            option_value: Selected option value

        Returns:
            Price modifier (upcharge) for the option, or 0.0 if included
        """
        # Look up the menu item to get included ingredient categories
        menu_item = self._pricing._lookup_menu_item(menu_item_name)
        included_categories: set[str] = set()
        if menu_item:
            included_categories = set(
                menu_item.get("included_ingredient_categories", [])
            )

        return self.lookup_attribute_option_upcharge(
            item_type, attr_slug, option_value, included_categories
        )

    def get_options_for_attribute(
        self,
        item_type: str,
        attr_slug: str,
        context: str,
    ) -> list[dict]:
        """Return the options list for a specific attribute on an item type.

        Args:
            item_type: Item type slug (e.g., "sandwich")
            attr_slug: Attribute slug (e.g., "bread", "cheese")
            context: Description for error messages

        Returns:
            List of option dicts for the matching attribute, or empty list
        """
        attributes = get_item_type_attributes(
            self._pricing._menu_data, item_type, context,
        )
        for attr in attributes:
            if attr.get("slug") == attr_slug:
                return attr.get("options", [])
        return []

    def get_option_ingredient_category(
        self,
        item_type: str,
        attr_slug: str,
        option_value: str,
    ) -> str | None:
        """Get the ingredient_category for an attribute option.

        Used to determine if an option belongs to a category that's already
        included in the menu item's base price.

        Args:
            item_type: Item type slug
            attr_slug: Attribute slug
            option_value: Selected option value

        Returns:
            The ingredient category string (e.g., "cheese") or None if not found
        """
        normalized = normalize_to_slug(option_value)
        option_lower = normalize_text(option_value)

        for opt in self.get_options_for_attribute(
            item_type, attr_slug, f"get ingredient category for '{option_value}'"
        ):
            if OptionMatcher.matches_value(opt, normalized, option_lower):
                return opt.get("ingredient_category")

        return None

    def get_min_option_price_for_attribute(
        self,
        item_type: str,
        attr_slug: str,
        ingredient_category: str,
    ) -> float:
        """Get the minimum price_modifier among available options in the same
        ingredient category for a given attribute.

        Used to compute the premium when a category is included in the base price.
        For example, if bread options are $0 (regular) and $1.85 (GF), the minimum
        is $0, so ordering GF still carries a $1.85 premium even when bread is
        included.

        Args:
            item_type: Item type slug (e.g., "sandwich")
            attr_slug: Attribute slug (e.g., "bread")
            ingredient_category: The ingredient category to filter by (e.g., "bread")

        Returns:
            The minimum price_modifier among matching options, or 0.0 if none found
        """
        min_price: float | None = None

        for opt in self.get_options_for_attribute(
            item_type, attr_slug, f"get min option price for '{attr_slug}'"
        ):
            if not isinstance(opt, dict):
                continue
            if opt.get("ingredient_category") != ingredient_category:
                continue
            price = OptionMatcher.get_option_price(opt)
            if min_price is None or price < min_price:
                min_price = price

        return min_price if min_price is not None else 0.0
