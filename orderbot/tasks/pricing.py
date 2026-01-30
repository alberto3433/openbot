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

logger = logging.getLogger(__name__)


# =============================================================================
# Helper Functions for Option Matching
# =============================================================================

def _normalize_option_for_matching(option: dict) -> tuple[str, str]:
    """Normalize an option dict for matching against user input.

    Extracts and normalizes both slug and display_name from an option dict
    for consistent comparison during price lookups.

    Args:
        option: Option dict with optional "slug" and "display_name" keys

    Returns:
        Tuple of (normalized_slug, normalized_display_name) where both have
        dashes and spaces converted to underscores, lowercased.

    Examples:
        >>> _normalize_option_for_matching({"slug": "oat-milk", "display_name": "Oat Milk"})
        ("oat_milk", "oat_milk")
        >>> _normalize_option_for_matching({"slug": "vanilla_syrup"})
        ("vanilla_syrup", "")
    """
    opt_slug = (option.get("slug") or "").lower().replace("-", "_")
    opt_name = (option.get("display_name") or "").lower().replace("-", "_").replace(" ", "_")
    return opt_slug, opt_name


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
                from orderbot.menu_data_cache import menu_cache
                if not menu_cache.attribute_contains_modifier_category(attr_slug, modifier_type_hint):
                    continue

        options = attr.get("options", [])
        for opt in options:
            if not isinstance(opt, dict):
                continue

            opt_slug, opt_name = _normalize_option_for_matching(opt)
            opt_display_lower = (opt.get("display_name") or "").lower()

            # Match by normalized slug, normalized display_name, or raw lowercase value
            if (opt_slug == normalized_value or
                opt_name == normalized_value or
                opt_slug == raw_value_lower or
                opt_display_lower == raw_value_lower or
                raw_value_lower in opt_slug):
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
    ) -> float:
        """Look up price modifier for an attribute option.

        Generic method to get upcharges for any attribute option (size, bread type,
        milk, syrup, etc.) from the database.

        Args:
            item_type: Item type slug (e.g., "bagel", "sized_beverage")
            attr_slug: Attribute slug (e.g., "size", "bread", "milk")
            option_value: Selected option value (e.g., "large", "gluten_free", "oat")

        Returns:
            Price modifier (upcharge) for the option, or 0.0 if not found
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
            return price

        # Not found - log and return 0.0
        logger.debug(
            "Attribute option upcharge not found: %s.%s=%s",
            item_type, attr_slug, option_value
        )
        return 0.0

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
            ValueError: If menu_data is not loaded or item_type doesn't exist
        """
        if not modifier_name:
            return 0.0

        normalized = normalize_to_slug(modifier_name)
        modifier_lower = modifier_name.lower().strip()

        if not self._menu_data:
            raise ValueError(
                f"Cannot look up modifier price for '{modifier_name}'. "
                "menu_data is required. Ensure menu is loaded."
            )

        item_types = self._menu_data.get("item_types", {})

        if not item_types:
            raise ValueError(
                f"Cannot look up modifier price for '{modifier_name}'. "
                "menu_data must contain 'item_types' structure. "
                "Ensure menu is loaded with full item type configuration."
            )

        type_data = item_types.get(item_type)

        if not type_data or not isinstance(type_data, dict):
            raise ValueError(
                f"Item type '{item_type}' not found in menu_data. "
                f"Cannot look up modifier price for '{modifier_name}'. "
                f"Available item types: {list(item_types.keys())}"
            )

        attributes = type_data.get("attributes", [])

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
            ValueError: If menu_data is not available or item_type doesn't exist
        """
        modifier_lower = modifier_name.lower().strip()

        # First, normalize using database-driven alias lookup (e.g., "lox" -> "Nova Scotia Salmon")
        from orderbot.menu_data_cache import menu_cache
        canonical_name = menu_cache.normalize_modifier(modifier_lower)

        # Convert to slug format for matching
        normalized = normalize_to_slug(canonical_name)

        if not self._menu_data:
            raise ValueError(
                f"Cannot look up modifier price for '{modifier_name}'. "
                "menu_data is required. Ensure menu is loaded."
            )

        item_types = self._menu_data.get("item_types", {})

        if not item_types:
            raise ValueError(
                f"Cannot look up modifier price for '{modifier_name}'. "
                "menu_data must contain 'item_types' structure. "
                "Ensure menu is loaded with full item type configuration."
            )

        type_data = item_types.get(item_type)

        if not type_data or not isinstance(type_data, dict):
            raise ValueError(
                f"Item type '{item_type}' not found in menu_data. "
                f"Cannot look up modifier price for '{modifier_name}'. "
                f"Available item types: {list(item_types.keys())}"
            )

        attributes = type_data.get("attributes", [])

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

        # Not found in this item type - return 0.0 (modifier is free or unconfigured)
        logger.debug(
            "Modifier '%s' not found in item_type '%s'. Returning $0.00.",
            modifier_name, item_type
        )
        return 0.0

    # =========================================================================
    # Unified Price Recalculation (Generic, Data-Driven)
    # =========================================================================

    def recalculate_item_price(self, item) -> float:
        """Generic price recalculation for any menu item type.

        This is the single entry point for all price recalculation. It calculates
        price using a fully data-driven approach with no hardcoded attribute names:

        total = base_price + sum(attribute_option.price_modifier for all selected options)

        Args:
            item: Any item task (MenuItemTask)

        Returns:
            The new calculated price

        Raises:
            ValueError: If base price cannot be looked up or item_type is not set
        """
        # Require item_type - no fallbacks
        item_type = getattr(item, 'menu_item_type', None)
        if not item_type:
            raise ValueError(
                f"Cannot recalculate price for '{getattr(item, 'menu_item_name', 'unknown')}': "
                "menu_item_type is required but not set on item."
            )

        # Get attribute values and modifiers from the item
        attr_values = item.attribute_values or {}
        item_modifiers = item.modifiers or []

        # =====================================================================
        # 1. Determine base price (respecting variant-based pricing and sides)
        # =====================================================================

        # Side items have base_price = 0 (e.g., bagel side with omelette is free,
        # but modifiers like spread still cost extra)
        is_side_item = getattr(item, 'side_of_item_id', None) is not None

        if is_side_item:
            base_price = 0.0
            uses_variant_pricing = False
            variant_attr = None
        else:
            # Check if item has variant-based pricing (e.g., size_prices)
            # If so, the variant dimension is already factored into the base price
            uses_variant_pricing = False
            variant_attr = None  # The attribute covered by variant pricing

            # Look up menu item to check for size-based pricing
            menu_item = self._lookup_menu_item(item.menu_item_name)
            size_prices = menu_item.get("size_prices") if menu_item else None

            if size_prices:
                # Derive variant attribute from size_category_slug (e.g., "size")
                variant_attr = menu_item.get("size_category_slug")
                variant_value = attr_values.get(variant_attr) if variant_attr else None
                size_price, size_data = self.lookup_size_price(item.menu_item_name, variant_value)

                if size_price is not None:
                    base_price = size_price
                    uses_variant_pricing = True
                else:
                    # Traditional pricing: base_price from menu item
                    base_price = self.lookup_base_price(item.menu_item_name)
            else:
                # No variant pricing - use traditional base_price
                base_price = self.lookup_base_price(item.menu_item_name)

        total = base_price

        # =====================================================================
        # 2. Process attribute_values generically (no hardcoded attribute names)
        # =====================================================================

        skip_suffixes = ("_price", "_upcharge", "_choice")
        priced_slugs: set[str] = set()

        for attr_slug, attr_value in attr_values.items():
            # Skip metadata/computed fields
            if any(attr_slug.endswith(suffix) for suffix in skip_suffixes):
                continue
            if attr_slug.startswith("pending_"):
                continue

            # Skip if variant pricing covers this attribute
            if uses_variant_pricing and attr_slug == variant_attr:
                continue

            # Skip empty/none values
            if attr_value is None or attr_value is False or attr_value == "":
                continue
            if isinstance(attr_value, str) and attr_value.lower() == "none":
                continue

            # Handle different value types
            if isinstance(attr_value, bool) and attr_value is True:
                # Boolean attributes (e.g., toasted=True) - look up upcharge
                upcharge = self.lookup_attribute_option_upcharge(item_type, attr_slug, "true")
                total += upcharge

            elif isinstance(attr_value, list):
                # Multi-select: sum prices for each item
                for item_val in attr_value:
                    if isinstance(item_val, str) and item_val.lower() != "none":
                        # Try attribute option first, then modifier
                        upcharge = self.lookup_attribute_option_upcharge(item_type, attr_slug, item_val)
                        if upcharge > 0:
                            total += upcharge
                            priced_slugs.add(item_val)
                        else:
                            price = self.lookup_modifier_price(item_val, item_type)
                            total += price
                            priced_slugs.add(item_val)
                    elif isinstance(item_val, dict):
                        slug, qty = extract_modifier_slug_and_quantity(item_val)
                        if slug:
                            stored_price = extract_modifier_price(item_val)
                            if stored_price is not None:
                                price = stored_price
                            else:
                                price = self.lookup_modifier_price(slug, item_type)
                                if price > 0:
                                    item_val["price"] = price
                            total += price * qty
                            priced_slugs.add(slug)

            elif isinstance(attr_value, (int, float)):
                # Numeric values - skip direct pricing (handled via modifiers list)
                continue

            elif isinstance(attr_value, str):
                # Single string value - check attribute option first, then modifier
                # But first: check if this slug exists in item_modifiers with quantity > 1
                # If so, skip it here and let Section 3 handle it with proper quantity
                modifier_with_qty = next(
                    (m for m in item_modifiers
                     if m.get("slug") == attr_value and m.get("quantity", 1) > 1),
                    None
                )
                if modifier_with_qty:
                    # Skip - Section 3 will handle this with proper quantity multiplication
                    continue

                upcharge = self.lookup_attribute_option_upcharge(item_type, attr_slug, attr_value)
                if upcharge > 0:
                    total += upcharge
                    priced_slugs.add(attr_value)
                else:
                    price = self.lookup_modifier_price(attr_value, item_type)
                    total += price
                    priced_slugs.add(attr_value)

        # =====================================================================
        # 3. Process item.modifiers generically (no hardcoded categories)
        # =====================================================================

        for modifier in item_modifiers:
            if not isinstance(modifier, dict):
                continue

            slug, quantity = extract_modifier_slug_and_quantity(modifier)
            if not slug or slug in priced_slugs:
                continue

            # Use stored price if available; only look up from DB if missing
            stored_price = extract_modifier_price(modifier)
            if stored_price is not None:
                price = stored_price
            else:
                price = self.lookup_modifier_price(slug, item_type)
                # Update the modifier's stored price so it displays in UI
                if price > 0:
                    modifier["price"] = price

            total += price * quantity

        # =====================================================================
        # 4. Update item price
        # =====================================================================

        new_price = round(total, 2)
        item.unit_price = new_price

        logger.info(
            "Recalculated price for %s: base=$%.2f -> total=$%.2f",
            item.menu_item_name, base_price, new_price
        )

        return new_price

