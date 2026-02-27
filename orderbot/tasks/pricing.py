"""
Pricing Engine for Order Items.

This module handles all price lookups and calculations for menu items.
All pricing is data-driven from the database - no hardcoded item types.

Generic pricing formula:
    total = base_price + sum(attribute_option.price_modifier) + conditional_modifiers + modifier_prices

Extracted from state_machine.py for better separation of concerns.

Sub-calculators:
- VariantPricingCalculator: size/variant-based pricing (variant_pricing.py)
- ModifierPricingCalculator: modifier price lookups (modifier_pricing.py)
- AttributePricingLookup: attribute option upcharges (attribute_pricing_lookup.py)
- AttributeUpchargeCalculator: attribute value upcharge application (attribute_upcharge_calculator.py)
"""

import logging
from functools import cached_property
from typing import Callable

from .mixins import MenuDataMixin
from .normalization import normalize_to_slug
from .modifier_utils import extract_modifier_slug_and_quantity
from .utils.cache_helpers import get_item_type_attributes
from .utils import OptionMatcher
from orderbot.cache import menu_cache
from orderbot.tasks.utils.text import normalize_text

logger = logging.getLogger(__name__)


# Note: Option matching functions are now in utils/option_matcher.py
# Use OptionMatcher.matches_value() and OptionMatcher.normalize_option()


def _matches_attribute_filter(
    attr: dict,
    target_attr_slug: str | None,
    modifier_type_hint: str | None,
) -> bool:
    """Check whether an attribute passes the target/type-hint filters.

    Args:
        attr: Attribute dict with a "slug" key.
        target_attr_slug: If set, only this slug passes.
        modifier_type_hint: If set, the attribute must relate to this type.

    Returns:
        True if the attribute should be searched, False to skip it.
    """
    attr_slug = attr.get("slug", "")

    if target_attr_slug and attr_slug != target_attr_slug:
        return False

    if modifier_type_hint:
        if modifier_type_hint not in attr_slug and attr_slug != modifier_type_hint:
            if not menu_cache.attribute_contains_modifier_category(attr_slug, modifier_type_hint):
                return False

    return True


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
            if not _matches_attribute_filter(attr, target_attr_slug, modifier_type_hint):
                continue

            for opt in attr.get("options", []):
                if not isinstance(opt, dict):
                    continue
                if OptionMatcher.matches_value(opt, normalized_value, raw_value_lower, exact_only=exact_only):
                    price = OptionMatcher.get_option_price(opt)
                    return price, attr.get("slug", "")

    return None, None


class PricingEngine(MenuDataMixin):
    """
    Handles price lookups and calculations for all order items.

    Requires menu_data and a menu_lookup function to resolve item prices
    from the menu database.

    Delegates to sub-calculators for specific pricing concerns:
    - variant_calculator: size/variant-based pricing
    - modifier_calculator: modifier price lookups
    - attribute_lookup: attribute option upcharges
    - upcharge_calculator: attribute value upcharge application
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

    @cached_property
    def upcharge_calculator(self):
        """Attribute upcharge calculator (lazy-loaded to avoid circular imports)."""
        from .attribute_upcharge_calculator import AttributeUpchargeCalculator
        return AttributeUpchargeCalculator(self)

    @cached_property
    def variant_calculator(self):
        """Variant pricing calculator (lazy-loaded to avoid circular imports)."""
        from .variant_pricing import VariantPricingCalculator
        return VariantPricingCalculator(self)

    @cached_property
    def modifier_calculator(self):
        """Modifier pricing calculator (lazy-loaded to avoid circular imports)."""
        from .modifier_pricing import ModifierPricingCalculator
        return ModifierPricingCalculator(self)

    @cached_property
    def attribute_lookup(self):
        """Attribute pricing lookup (lazy-loaded to avoid circular imports)."""
        from .attribute_pricing_lookup import AttributePricingLookup
        return AttributePricingLookup(self)

    # =========================================================================
    # Shared Helper
    # =========================================================================

    def _resolve_menu_item(self, name: str) -> dict | None:
        """Look up a menu item by name, falling back to title-case."""
        return self._lookup_menu_item(name) or self._lookup_menu_item(name.title())

    # =========================================================================
    # Delegate Methods — Variant Pricing
    # =========================================================================

    def get_size_category_slug(self, menu_item_name: str) -> str | None:
        """Return the size_category_slug for a menu item, or None."""
        return self.variant_calculator.get_size_category_slug(menu_item_name)

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
        return self.variant_calculator.lookup_size_price(menu_item_name, size_name)

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
        return self.variant_calculator.lookup_size_upcharge(menu_item_name, size_name)

    def get_default_variant_for_item(
        self,
        menu_item_name: str,
    ) -> dict | None:
        """Get the default variant for an item with variant-based pricing.

        For items with size/weight-based pricing (e.g., spreads, coffee), this returns
        the default variant that determines the base price. The default is the first
        variant by display_order.

        Args:
            menu_item_name: Name of the menu item

        Returns:
            Dict with variant info {"slug": str, "display_name": str} or None if:
            - Item doesn't have variant pricing
            - Item has only one variant (no need to display "each" for bagels, etc.)
        """
        return self.variant_calculator.get_default_variant_for_item(menu_item_name)

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
        return self.variant_calculator.lookup_base_price(menu_item_name, size_name)

    # =========================================================================
    # Delegate Methods — Attribute Pricing Lookup
    # =========================================================================

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
        return self.attribute_lookup.lookup_attribute_option_upcharge(
            item_type, attr_slug, option_value, included_ingredient_categories
        )

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
        return self.attribute_lookup.lookup_attribute_option_upcharge_for_item(
            menu_item_name, item_type, attr_slug, option_value
        )

    def _get_options_for_attribute(
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
        return self.attribute_lookup._get_options_for_attribute(
            item_type, attr_slug, context
        )

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
        return self.attribute_lookup._get_option_ingredient_category(
            item_type, attr_slug, option_value
        )

    def _get_min_option_price_for_attribute(
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
        return self.attribute_lookup._get_min_option_price_for_attribute(
            item_type, attr_slug, ingredient_category
        )

    # =========================================================================
    # Delegate Methods — Modifier Pricing
    # =========================================================================

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
        return self.modifier_calculator.lookup_generic_modifier_price(
            modifier_name, item_type, modifier_type
        )

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
        return self.modifier_calculator.lookup_modifier_price(modifier_name, item_type)

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
        bundle_price_rule = item.bundle_price_rule
        bundle_included_price = item.bundle_included_price

        if bundle_price_rule == 'included':
            if bundle_included_price is None:
                # Full inclusion: base price is $0, upcharges still apply
                return 0.0, False, None, included_categories
            # Differential pricing: calculate actual base price first, then subtract included amount

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

        Always looks up prices from GlobalAttributeOption.price_modifier - this is
        the single source of truth for all pricing. Stored prices on modifiers are
        for display purposes only and are updated by this method.

        Args:
            item_modifiers: List of modifier dicts on the item
            item_type: The item type slug
            priced_slugs: Set of NORMALIZED slugs already priced (to avoid double-counting)

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

            # Normalize slug for consistent comparison with priced_slugs
            # (priced_slugs contains normalized slugs from apply_upcharges)
            slug_normalized = normalize_to_slug(slug)

            # Skip if already priced via attribute upcharges
            if slug_normalized in priced_slugs:
                continue

            # Always look up price from DB - this is the single source of truth
            # The stored price on the modifier is for display only and gets updated here
            price = self.lookup_modifier_price(slug, item_type)
            modifier["price"] = price  # Update for display purposes

            total += price * quantity

        return total

    def recalculate_item_price(self, item) -> float:
        """Generic price recalculation for any menu item type.

        This is the single entry point for all price recalculation. It calculates
        price using a fully data-driven approach with no hardcoded attribute names:

            total = base_price + attr_upcharges + modifier_prices

        **Price sources and their database tables:**

        1. Base price — from ``menu_item_size_prices.price`` (variant/size pricing)
           or ``menu_items.base_price`` (flat pricing). Resolved in
           ``_calculate_base_price()``. Bundle pricing rules
           (``component_slot_options.fixed_price`` / ``included_price_cents``)
           may reduce or zero out the base.

        2. Attribute upcharges — from ``global_attribute_options.price_modifier``,
           looked up via ``AttributeUpchargeCalculator.apply_upcharges()``.
           Each attribute value (bread type, size, iced, etc.) is matched to its
           option row and the price_modifier is summed. The variant attribute
           (e.g. "size") is skipped here because it's already covered by #1.

        3. Modifier prices — also from ``global_attribute_options.price_modifier``,
           but for modifiers not already priced in step 2 (tracked via
           ``priced_slugs``). Falls back to ingredient price contexts (built from
           the same ``global_attribute_options`` table but indexed by ingredient
           name) via ``menu_cache.get_ingredient_price_for_item_type()``.

        The ``priced_slugs`` set prevents double-counting across steps 2 and 3.
        See ``tests/test_pricing_audit.py`` for data-level consistency guards.

        Args:
            item: Any item task (MenuItemTask)

        Returns:
            The new calculated price

        Raises:
            ValueError: If item_type is not set on the item
        """
        # Require item_type - no fallbacks
        item_type = item.menu_item_type
        if not item_type:
            raise ValueError(
                f"Cannot recalculate price for '{item.menu_item_name}': "
                "menu_item_type is required but not set on item."
            )

        # Note: Bundle-included items have base_price=$0 but can still have upcharges
        # (e.g., cream cheese on a bundled bagel). The base_price=$0 is handled in
        # _calculate_base_price(); upcharges are still calculated below.

        # Get attribute values and selections from the item
        attr_values = item.attribute_values or {}
        item_modifiers = item.selections or []

        # Look up menu item for pricing data
        menu_item = self._lookup_menu_item(item.menu_item_name)

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
