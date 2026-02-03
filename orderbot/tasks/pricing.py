"""
Pricing Engine for Order Items.

This module handles all price lookups and calculations for menu items.
All pricing is data-driven from the database - no hardcoded item types.

Generic pricing formula:
    total = base_price + sum(attribute_option.price_modifier) + conditional_modifiers + modifier_prices

Extracted from state_machine.py for better separation of concerns.
"""

import logging
from typing import Callable

from .mixins import MenuDataMixin
from .normalization import normalize_to_slug
from .modifier_utils import extract_modifier_slug_and_quantity, extract_modifier_price
from .utils.cache_helpers import get_item_type_attributes
from .utils import OptionMatcher
from orderbot.cache import menu_cache

logger = logging.getLogger(__name__)


# Note: Option matching functions are now in utils/option_matcher.py
# Use OptionMatcher.matches_value() and OptionMatcher.normalize_option()


def _lookup_option_price_in_attributes(
    attributes: list[dict],
    normalized_value: str,
    raw_value_lower: str,
    *,
    target_attr_slug: str | None = None,
    modifier_type_hint: str | None = None,
) -> tuple[float | None, str | None]:
    """Search attributes for an option matching the given value and return its price.

    This is the unified option price lookup used by all pricing methods. It searches
    through attribute options for a match by slug or display_name.

    Uses two-pass matching:
    1. First pass: Look for exact matches only (e.g., "egg" matches option slug "egg")
    2. Second pass: Look for prefix matches (e.g., "vanilla" matches "vanilla_syrup")

    This ensures that an exact match like "egg" -> "egg" option is preferred over
    a prefix match like "egg" -> "egg_bagel" option.

    Args:
        attributes: List of attribute dicts, each with "slug" and "options" keys
        normalized_value: Value normalized via normalize_to_slug() for slug matching
        raw_value_lower: Original value lowercased for display_name matching
        target_attr_slug: If provided, only search this specific attribute
        modifier_type_hint: If provided, filter attributes by this type hint

    Returns:
        Tuple of (price, attr_slug) where price is the found price_modifier/price,
        or (None, None) if no match found.

    Examples:
        >>> attrs = [{"slug": "size", "options": [{"slug": "large", "price_modifier": 0.90}]}]
        >>> _lookup_option_price_in_attributes(attrs, "large", "large")
        (0.90, "size")
    """
    # Two-pass matching: exact matches first, then prefix matches
    for exact_only in (True, False):
        for attr in attributes:
            if not isinstance(attr, dict):
                continue

            attr_slug = attr.get("slug", "")

            # Filter by target attribute if specified
            if target_attr_slug and attr_slug != target_attr_slug:
                continue

            # Filter by modifier type hint if specified
            if modifier_type_hint:
                if modifier_type_hint not in attr_slug and attr_slug != modifier_type_hint:
                    # Also check if attribute contains options with this modifier category
                    if not menu_cache.attribute_contains_modifier_category(attr_slug, modifier_type_hint):
                        continue

            options = attr.get("options", [])
            for opt in options:
                if not isinstance(opt, dict):
                    continue

                if OptionMatcher.matches_value(opt, normalized_value, raw_value_lower, exact_only=exact_only):
                    # Check both keys: "price_modifier" for attribute options,
                    # "price" for ingredient-based options
                    price = opt.get("price_modifier") or opt.get("price") or 0.0
                    return price, attr_slug

    return None, None


class PricingEngine(MenuDataMixin):
    """
    Handles price lookups and calculations for all order items.

    Requires menu_data and a menu_lookup function to resolve item prices
    from the menu database.
    """

    # Modifier prices are now stored in the database (AttributeOption.price_modifier)
    # and looked up via the item_types structure in menu_data.
    # See migration m7n8o9p0q1r2_populate_modifier_prices.py for initial data.
    #
    # Bagel type upcharges are also stored in the database under the "bread"
    # attribute definition (e.g., gluten_free has price_modifier=0.80).

    def __init__(
        self,
        menu_data: dict | None,
        menu_lookup_func: Callable[[str], dict | None],
    ):
        """
        Initialize the pricing engine.

        Args:
            menu_data: Menu data dictionary containing prices, item_types, etc.
            menu_lookup_func: Function to look up menu items by name.
                             Signature: (item_name: str) -> dict | None
        """
        self._menu_data = menu_data or {}
        self._lookup_menu_item = menu_lookup_func

        # Lazy-loaded calculator to avoid circular imports
        self._upcharge_calculator = None

    @property
    def upcharge_calculator(self):
        """Get the attribute upcharge calculator (lazy-loaded)."""
        if self._upcharge_calculator is None:
            from .attribute_upcharge_calculator import AttributeUpchargeCalculator
            self._upcharge_calculator = AttributeUpchargeCalculator(self)
        return self._upcharge_calculator

    # =========================================================================
    # Generic Pricing Methods (Data-Driven)
    # =========================================================================

    def lookup_size_price(
        self,
        menu_item_name: str,
        size_name: str | None = None,
    ) -> tuple[float | None, dict | None]:
        """Look up price for a menu item with size-based pricing.

        For items with variant-based pricing (e.g., coffee, deli items), this
        returns the price for a specific size. If size_name is None and the item
        has only one size, returns that price.

        Args:
            menu_item_name: Name of the menu item
            size_name: Optional size name (e.g., "small", "large", "1/4 lb")

        Returns:
            Tuple of (price, size_data) where size_data contains size info,
            or (None, None) if item doesn't have size-based pricing
        """
        menu_item = self._lookup_menu_item(menu_item_name)
        if not menu_item:
            menu_item = self._lookup_menu_item(menu_item_name.title())
        if not menu_item:
            return None, None

        size_prices = menu_item.get("size_prices")
        if not size_prices:
            return None, None

        # If only one size, return it (no disambiguation needed)
        if len(size_prices) == 1:
            sp = size_prices[0]
            return sp["price"], sp

        # If size_name provided, find matching size
        if size_name:
            size_lower = size_name.lower().strip()
            for sp in size_prices:
                if sp["size_name"] and sp["size_name"].lower() == size_lower:
                    return sp["price"], sp

        # No size specified and multiple sizes - return None to trigger disambiguation
        return None, None

    def lookup_size_upcharge(
        self,
        menu_item_name: str,
        size_name: str,
    ) -> float:
        """Calculate the upcharge for a size relative to the smallest/base size.

        For sized items (coffee, deli), the smallest size (by display_order) is
        considered the base. This returns the difference between the selected
        size and the base size.

        Args:
            menu_item_name: Name of the menu item
            size_name: The selected size name (e.g., "large")

        Returns:
            Upcharge amount (0.0 if this is the base size or not a sized item)
        """
        menu_item = self._lookup_menu_item(menu_item_name)
        if not menu_item:
            menu_item = self._lookup_menu_item(menu_item_name.title())
        if not menu_item:
            return 0.0

        size_prices = menu_item.get("size_prices")
        if not size_prices or len(size_prices) <= 1:
            return 0.0

        # Sort by display_order to find the base (smallest) size
        sorted_sizes = sorted(size_prices, key=lambda sp: sp.get("display_order", 999))
        base_price = sorted_sizes[0]["price"]

        # Find the selected size price
        size_lower = size_name.lower().strip()
        for sp in size_prices:
            if sp["size_name"] and sp["size_name"].lower() == size_lower:
                return sp["price"] - base_price

        return 0.0

    def lookup_base_price(self, menu_item_name: str, size_name: str | None = None) -> float:
        """Look up base price for any menu item by name.

        This is the generic way to get base prices - works for bagels, coffee,
        sandwiches, or any other menu item type.

        For items with size-based pricing, pass the size_name to get the correct
        price. If size_name is None and the item has only one size, that price
        is returned. If multiple sizes exist and no size_name is provided, falls
        back to base_price if available.

        Args:
            menu_item_name: Name of the menu item (e.g., "Bagel", "Latte", "BLT")
            size_name: Optional size name for size-based pricing

        Returns:
            Base price for the menu item

        Raises:
            ValueError: If menu item not found in database
        """
        if not menu_item_name:
            raise ValueError("menu_item_name is required for base price lookup")

        # Try size-based pricing first
        size_price, _ = self.lookup_size_price(menu_item_name, size_name)
        if size_price is not None:
            return size_price

        # Fall back to base_price
        menu_item = self._lookup_menu_item(menu_item_name)
        if menu_item and menu_item.get("base_price"):
            return menu_item["base_price"]

        # Try title case variation
        menu_item = self._lookup_menu_item(menu_item_name.title())
        if menu_item and menu_item.get("base_price"):
            return menu_item["base_price"]

        raise ValueError(
            f"No price found for menu item '{menu_item_name}'. "
            "Ensure the menu item exists in database with a base_price or size_prices."
        )

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
        option_lower = option_value.lower().strip()

        if not self._menu_data:
            logger.warning("No menu_data available for attribute upcharge lookup")
            return 0.0

        item_types = self._menu_data.get("item_types", {})
        type_data = item_types.get(item_type, {})
        attributes = type_data.get("attributes", [])

        price, _ = _lookup_option_price_in_attributes(
            attributes,
            normalized,
            option_lower,
            target_attr_slug=attr_slug,
        )

        if price is not None:
            # Check if this option's ingredient category is already included
            if included_ingredient_categories:
                option_category = self._get_option_ingredient_category(
                    item_type, attr_slug, option_value
                )
                if option_category and option_category in included_ingredient_categories:
                    logger.debug(
                        "Skipping upcharge for %s.%s=%s - category '%s' is included",
                        item_type, attr_slug, option_value, option_category
                    )
                    return 0.0
            return price

        # Not found - log and return 0.0
        logger.debug(
            "Attribute option upcharge not found: %s.%s=%s",
            item_type, attr_slug, option_value
        )
        return 0.0

    def _get_option_ingredient_category(
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
        option_lower = option_value.lower().strip()

        item_types = self._menu_data.get("item_types", {})
        type_data = item_types.get(item_type, {})
        attributes = type_data.get("attributes", [])

        for attr in attributes:
            if attr.get("slug") != attr_slug:
                continue
            for opt in attr.get("options", []):
                if OptionMatcher.matches_value(opt, normalized, option_lower):
                    return opt.get("ingredient_category")

        return None

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
        menu_item = self._lookup_menu_item(menu_item_name)
        included_categories: set[str] = set()
        if menu_item:
            included_categories = set(
                menu_item.get("included_ingredient_categories", [])
            )

        return self.lookup_attribute_option_upcharge(
            item_type, attr_slug, option_value, included_categories
        )

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
        modifier_lower = modifier_name.lower().strip()

        # Use cache helper for validated attribute lookup (raises MenuDataNotLoadedError)
        attributes = get_item_type_attributes(
            self._menu_data,
            item_type,
            f"look up modifier price for '{modifier_name}'",
        )

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

    # =========================================================================
    # Modifier Pricing (Used by generic pricing)
    # =========================================================================

    def lookup_modifier_price(self, modifier_name: str, item_type: str) -> float:
        """
        Look up price modifier for an item add-on (protein, cheese, topping).

        Searches the specified item_type's attribute options for matching modifier prices.
        Does NOT fall back to other item types - modifiers must be configured for
        each item type that uses them.

        Args:
            modifier_name: Name of the modifier (e.g., "ham", "egg", "american")
            item_type: Item type to look up (required, no default)

        Returns:
            Price modifier (e.g., 2.00 for ham) or 0.0 if modifier is free/unconfigured

        Raises:
            MenuDataNotLoadedError: If menu_data is not available or item_type doesn't exist
        """
        modifier_lower = modifier_name.lower().strip()

        # First, normalize using database-driven alias lookup (e.g., "lox" -> "Nova Scotia Salmon")
        canonical_name = menu_cache.normalize_modifier(modifier_lower)

        # Convert to slug format for matching
        normalized = normalize_to_slug(canonical_name)

        # Use cache helper for validated attribute lookup (raises MenuDataNotLoadedError)
        attributes = get_item_type_attributes(
            self._menu_data,
            item_type,
            f"look up modifier price for '{modifier_name}'",
        )

        price, attr_slug = _lookup_option_price_in_attributes(
            attributes,
            normalized,
            modifier_lower,
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
        logger.debug(
            "Modifier '%s' not found in item_type '%s'. Returning $0.00.",
            modifier_name, item_type
        )
        return 0.0

    # =========================================================================
    # Unified Price Recalculation (Generic, Data-Driven)
    # =========================================================================

    def _calculate_base_price(
        self, item, menu_item: dict | None
    ) -> tuple[float, bool, str | None, set[str]]:
        """Calculate base price for an item, handling variant pricing and bundle pricing.

        Args:
            item: The menu item task
            menu_item: Menu item data from cache lookup (may be None)

        Returns:
            Tuple of (base_price, uses_variant_pricing, variant_attr, included_categories)
            - base_price: The calculated base price
            - uses_variant_pricing: True if size/variant pricing was used
            - variant_attr: The attribute slug covered by variant pricing (e.g., "size")
            - included_categories: Set of ingredient categories included at no extra charge
        """
        attr_values = item.attribute_values or {}

        # Get included ingredient categories (for skipping upcharges on included items)
        included_categories: set[str] = set()
        if menu_item:
            included_categories = set(
                menu_item.get("included_ingredient_categories", [])
            )

        # Check bundle pricing rules (replaces legacy side_of_item_id check)
        bundle_price_rule = getattr(item, 'bundle_price_rule', None)
        bundle_included_price = getattr(item, 'bundle_included_price', None)

        if bundle_price_rule == 'included':
            if bundle_included_price is None:
                # Full inclusion: base price is $0, upcharges still apply
                return 0.0, False, None, included_categories
            # Differential pricing: calculate actual base price first, then subtract included amount

        # Legacy support: side items have base_price = 0
        is_side_item = getattr(item, 'side_of_item_id', None) is not None
        if is_side_item:
            return 0.0, False, None, included_categories

        # Check for variant-based pricing (e.g., size_prices)
        size_prices = menu_item.get("size_prices") if menu_item else None

        if size_prices:
            variant_attr = menu_item.get("size_category_slug")
            variant_value = attr_values.get(variant_attr) if variant_attr else None
            size_price, _ = self.lookup_size_price(item.menu_item_name, variant_value)

            if size_price is not None:
                # Apply differential pricing if applicable
                if bundle_price_rule == 'included' and bundle_included_price is not None:
                    return max(0.0, size_price - bundle_included_price), True, variant_attr, included_categories
                return size_price, True, variant_attr, included_categories

        # Traditional pricing: base_price from menu item
        base_price = self.lookup_base_price(item.menu_item_name)

        # Apply differential pricing if applicable
        if bundle_price_rule == 'included' and bundle_included_price is not None:
            return max(0.0, base_price - bundle_included_price), False, None, included_categories

        return base_price, False, None, included_categories

    def _apply_modifier_prices(
        self,
        item_modifiers: list,
        item_type: str,
        priced_slugs: set[str],
    ) -> float:
        """Apply prices for modifiers not already priced via attributes.

        Args:
            item_modifiers: List of modifier dicts on the item
            item_type: The item type slug
            priced_slugs: Set of slugs already priced (to avoid double-counting)

        Returns:
            Total price from modifiers
        """
        total = 0.0

        for modifier in item_modifiers:
            if not isinstance(modifier, dict):
                continue

            slug, quantity = extract_modifier_slug_and_quantity(modifier)
            # Skip boolean answer markers - these aren't actual modifiers to price
            if not slug or slug in ("yes", "no", "_declined"):
                continue

            # Check if this is a default ingredient (included in base price)
            is_default = modifier.get("is_default", False)
            if slug in priced_slugs and is_default:
                # Default ingredients are already accounted for in base price
                continue
            # Non-default modifiers should be priced even if slug is in priced_slugs
            # (e.g., user added "extra bacon" to a sandwich that already has bacon)

            # Use stored price if available; only look up from DB if missing
            stored_price = extract_modifier_price(modifier)
            if stored_price is not None:
                price = stored_price
            else:
                price = self.lookup_modifier_price(slug, item_type)
                if price > 0:
                    modifier["price"] = price

            total += price * quantity

        return total

    def recalculate_item_price(self, item) -> float:
        """Generic price recalculation for any menu item type.

        This is the single entry point for all price recalculation. It calculates
        price using a fully data-driven approach with no hardcoded attribute names:

        total = base_price + sum(attribute_option.price_modifier) + modifier_prices

        Args:
            item: Any item task (MenuItemTask)

        Returns:
            The new calculated price

        Raises:
            ValueError: If item_type is not set on the item
        """
        # Require item_type - no fallbacks
        item_type = getattr(item, 'menu_item_type', None)
        if not item_type:
            raise ValueError(
                f"Cannot recalculate price for '{getattr(item, 'menu_item_name', 'unknown')}': "
                "menu_item_type is required but not set on item."
            )

        # Note: Bundle-included items have base_price=$0 but can still have upcharges
        # (e.g., cream cheese on a bundled bagel). The base_price=$0 is handled in
        # _calculate_base_price(); upcharges are still calculated below.

        # Get attribute values and modifiers from the item
        attr_values = item.attribute_values or {}
        item_modifiers = item.modifiers or []

        # Look up menu item for pricing data
        menu_item = self._lookup_menu_item(item.menu_item_name)

        logger.debug(
            "recalculate_item_price: item=%s, menu_item_found=%s",
            item.menu_item_name, menu_item is not None
        )

        # 1. Calculate base price
        base_price, uses_variant_pricing, variant_attr, included_categories = \
            self._calculate_base_price(item, menu_item)

        # 2. Apply attribute upcharges (via calculator)
        attr_upcharge, priced_slugs = self.upcharge_calculator.apply_upcharges(
            item_type, attr_values, item_modifiers,
            uses_variant_pricing, variant_attr, included_categories
        )

        # 3. Apply modifier prices (for items not already priced)
        modifier_total = self._apply_modifier_prices(
            item_modifiers, item_type, priced_slugs
        )

        # 4. Calculate and update final price
        total = base_price + attr_upcharge + modifier_total
        new_price = round(total, 2)
        item.unit_price = new_price

        logger.info(
            "Recalculated price for %s: base=$%.2f + attrs=$%.2f + mods=$%.2f = $%.2f",
            item.menu_item_name, base_price, attr_upcharge, modifier_total, new_price
        )

        return new_price

