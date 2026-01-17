"""
Pricing Engine for Order Items.

This module handles all price lookups and calculations for menu items.
All pricing is data-driven from the database - no hardcoded item types.

Generic pricing formula:
    total = base_price + sum(attribute_option.price_modifier) + conditional_modifiers + modifier_prices

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import re
from typing import Any, Callable

from .models import get_modifier_name

logger = logging.getLogger(__name__)


class PricingEngine:
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
        self._menu_data = menu_data
        self._lookup_menu_item = menu_lookup_func

    @property
    def menu_data(self) -> dict | None:
        """Get current menu data."""
        return self._menu_data

    @menu_data.setter
    def menu_data(self, value: dict | None):
        """Update menu data."""
        self._menu_data = value

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

    def get_size_options(self, menu_item_name: str) -> list[dict] | None:
        """Get all available size options for a menu item.

        Returns a list of size options with price, or None if item doesn't
        have size-based pricing.

        Args:
            menu_item_name: Name of the menu item

        Returns:
            List of dicts with {size_id, size_name, price, display_order},
            or None if no size-based pricing
        """
        menu_item = self._lookup_menu_item(menu_item_name)
        if not menu_item:
            menu_item = self._lookup_menu_item(menu_item_name.title())
        if not menu_item:
            return None

        return menu_item.get("size_prices")

    def get_size_question(self, menu_item_name: str) -> str | None:
        """Get the question text to ask for size selection.

        Args:
            menu_item_name: Name of the menu item

        Returns:
            Question text (e.g., "What size?") or None if no size-based pricing
        """
        menu_item = self._lookup_menu_item(menu_item_name)
        if not menu_item:
            menu_item = self._lookup_menu_item(menu_item_name.title())
        if not menu_item:
            return None

        return menu_item.get("size_question_text")

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

        option_lower = option_value.lower().strip()
        normalized = option_lower.replace(" ", "_").replace("-", "_")

        if not self._menu_data:
            logger.warning("No menu_data available for attribute upcharge lookup")
            return 0.0

        item_types = self._menu_data.get("item_types", {})
        type_data = item_types.get(item_type, {})
        attributes = type_data.get("attributes", [])

        for attr in attributes:
            if attr.get("slug") == attr_slug:
                options = attr.get("options", [])
                for opt in options:
                    opt_slug = opt.get("slug", "").lower().replace("-", "_")
                    opt_name = opt.get("display_name", "").lower().replace(" ", "_")

                    if opt_slug == normalized or opt_name == normalized or \
                       opt_slug == option_lower:
                        return opt.get("price_modifier", 0.0)

        # Not found - log and return 0.0
        logger.debug(
            "Attribute option upcharge not found: %s.%s=%s",
            item_type, attr_slug, option_value
        )
        return 0.0

    def lookup_conditional_upcharge(
        self,
        item_type: str,
        source_attr: str,
        source_value: str,
        modifier_column: str,
    ) -> float:
        """Look up a conditional price modifier from another attribute's options.

        This handles cases where a price upcharge depends on another attribute value.
        The pattern is: {condition_value}_price_modifier on the source attribute options.

        Args:
            item_type: Item type slug (e.g., "sized_beverage")
            source_attr: Attribute to look up the modifier from (e.g., "size")
            source_value: Selected value of source attribute (e.g., "large")
            modifier_column: Column name for the conditional modifier

        Returns:
            Conditional upcharge or 0.0 if not found
        """
        if not source_value:
            return 0.0

        source_lower = source_value.lower().strip()

        if not self._menu_data:
            raise ValueError(
                f"Cannot look up conditional upcharge for '{source_attr}.{modifier_column}'. "
                "menu_data is required. Ensure menu is loaded."
            )

        item_types = self._menu_data.get("item_types", {})

        if not item_types:
            raise ValueError(
                f"Cannot look up conditional upcharge for '{source_attr}.{modifier_column}'. "
                "menu_data must contain 'item_types' structure. "
                "Ensure menu is loaded with full item type configuration."
            )

        type_data = item_types.get(item_type)

        if not type_data or not isinstance(type_data, dict):
            raise ValueError(
                f"Item type '{item_type}' not found in menu_data. "
                f"Cannot look up conditional upcharge for '{source_attr}.{modifier_column}'. "
                f"Available item types: {list(item_types.keys())}"
            )

        attrs = type_data.get("attributes", [])
        for attr in attrs:
            if not isinstance(attr, dict):
                continue
            if attr.get("slug") == source_attr:
                options = attr.get("options", [])
                for opt in options:
                    if not isinstance(opt, dict):
                        continue
                    opt_slug = opt.get("slug", "").lower()
                    if opt_slug == source_lower or source_lower in opt_slug:
                        upcharge = opt.get(modifier_column, 0.0)
                        if upcharge > 0:
                            logger.debug(
                                "Found conditional upcharge: %s.%s.%s = $%.2f",
                                source_attr, source_value, modifier_column, upcharge
                            )
                        return upcharge

        # Attribute or option not found - return 0.0 (this is valid, not all options have upcharges)
        logger.debug(
            "Conditional upcharge not found: %s.%s.%s for item_type '%s'",
            source_attr, source_value, modifier_column, item_type
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

        modifier_lower = modifier_name.lower().strip()
        normalized = modifier_lower.replace(" ", "_").replace("-", "_")

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
        for attr in attributes:
            if not isinstance(attr, dict):
                continue

            attr_slug = attr.get("slug", "")

            # If modifier_type specified, only check matching attributes
            if modifier_type and modifier_type not in attr_slug and attr_slug != modifier_type:
                # Also check attributes that contain options with this modifier category
                # (e.g., milk_sweetener_syrup contains milk, syrup, and sweetener options)
                from sandwich_bot.menu_data_cache import menu_cache
                if not menu_cache.attribute_contains_modifier_category(attr_slug, modifier_type):
                    continue

            options = attr.get("options", [])
            for opt in options:
                if not isinstance(opt, dict):
                    continue

                opt_slug = opt.get("slug", "").lower().replace("-", "_")
                opt_name = opt.get("display_name", "").lower().replace(" ", "_")

                if opt_slug == normalized or opt_name == normalized or \
                   opt_slug == modifier_lower or modifier_lower in opt_slug:
                    price = opt.get("price_modifier", 0.0)
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
    # Quantity Parsing (for by-the-pound items)
    # =========================================================================

    def parse_quantity_to_pounds(self, quantity_str: str) -> float:
        """Parse a quantity string to pounds.

        Examples:
            "1 lb" -> 1.0
            "2 lbs" -> 2.0
            "half lb" -> 0.5
            "half pound" -> 0.5
            "quarter lb" -> 0.25
            "1/2 lb" -> 0.5
            "1/4 lb" -> 0.25
            "3/4 lb" -> 0.75
        """
        quantity_lower = quantity_str.lower().strip()

        # Handle fractional words
        if "half" in quantity_lower:
            return 0.5
        if "quarter" in quantity_lower:
            return 0.25
        if "three quarter" in quantity_lower or "3/4" in quantity_lower:
            return 0.75
        if "1/2" in quantity_lower:
            return 0.5
        if "1/4" in quantity_lower:
            return 0.25

        # Try to extract a number
        match = re.search(r"(\d+(?:\.\d+)?)", quantity_lower)
        if match:
            return float(match.group(1))

        # Default to 1 pound
        return 1.0

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
        from sandwich_bot.menu_data_cache import menu_cache
        canonical_name = menu_cache.normalize_modifier(modifier_lower)

        # Convert to slug format for matching: lowercase + spaces/dashes to underscores
        normalized = canonical_name.lower().replace("-", "_").replace(" ", "_")

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

        # Search through all attributes for this item type
        for attr in attributes:
            options = attr.get("options", [])
            for opt in options:
                opt_slug = opt.get("slug", "").lower().replace("-", "_")
                opt_name = opt.get("display_name", "").lower().replace("-", "_").replace(" ", "_")

                # Match by slug or display_name (normalized)
                if opt_slug == normalized or opt_name == normalized or \
                   opt_slug == modifier_lower or opt.get("display_name", "").lower() == modifier_lower:
                    price = opt.get("price_modifier", 0.0)
                    logger.debug(
                        "Found modifier price: %s = $%.2f (from %s.%s)",
                        modifier_name, price, item_type, attr.get("slug")
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

        This is the preferred entry point for price recalculation. It calculates
        price using a data-driven approach:

        total = base_price
              + sum(attribute_option.price_modifier for selected attributes)
              + conditional_modifiers (e.g., iced upcharge varies by size)
              + sum(modifier prices for proteins, spreads, extras, syrups)

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

        # Get attribute values from the item
        attr_values = getattr(item, 'attribute_values', {})

        # Get size value early - needed for both base price lookup and upcharge calc
        size_value = attr_values.get("size")

        # Check if item has size-based pricing (explicit prices per size)
        # If so, get base price using size; otherwise use traditional base_price + upcharge
        uses_size_pricing = False
        size_price, size_data = self.lookup_size_price(item.menu_item_name, size_value)

        if size_price is not None:
            # Item uses size-based pricing - price already includes size
            base_price = size_price
            uses_size_pricing = True
        else:
            # Traditional pricing: base_price from menu item
            base_price = self.lookup_base_price(item.menu_item_name)

        total = base_price

        # =====================================================================
        # 1. Attribute option upcharges (size, bread type, etc.)
        # =====================================================================

        # Size upcharge - only apply for items WITHOUT size-based pricing
        # (items with size-based pricing already have size factored into base_price)
        size_upcharge = 0.0
        if not uses_size_pricing and size_value and size_value.lower() not in ("small", "s"):
            size_upcharge = self.lookup_attribute_option_upcharge(
                item_type, "size", size_value
            )
            total += size_upcharge

        # Store on item if property exists
        if hasattr(item, 'size_upcharge'):
            item.size_upcharge = size_upcharge

        # Bread type upcharge (for items with bread attribute)
        bread_value = attr_values.get("bagel_type") or attr_values.get("bread")
        bread_upcharge = 0.0
        if bread_value:
            bread_upcharge = self.lookup_attribute_option_upcharge(
                item_type, "bread", bread_value
            )
            total += bread_upcharge

        if hasattr(item, 'bread_upcharge'):
            item.bread_upcharge = bread_upcharge

        # =====================================================================
        # 2. Modifier upcharges (milk, syrup, protein, spread, extras)
        # =====================================================================
        # Note: Temperature (hot/iced) is now part of the menu item name itself
        # (e.g., "Iced Latte" vs "Hot Latte"), not a modifier with upcharge.

        # Milk upcharge - get from unified modifiers list
        modifiers = getattr(item, 'modifiers', []) or []
        milk_entries = [m for m in modifiers if m.get("category") == "milk"]
        milk_value = milk_entries[0].get("slug") if milk_entries else attr_values.get("milk")
        milk_upcharge = 0.0
        if milk_value:
            milk_upcharge = self.lookup_generic_modifier_price(
                milk_value, item_type, "milk"
            )
            total += milk_upcharge

        attr_values["milk_upcharge"] = milk_upcharge

        # Syrup upcharge (sum of all syrups * quantities)
        # Get from unified modifiers list (category="syrup")
        syrup_selections = [m for m in modifiers if m.get("category") == "syrup"] or attr_values.get("syrup_selections", [])
        syrup_upcharge = 0.0
        for syrup in syrup_selections:
            if isinstance(syrup, dict):
                # Use get_modifier_name to handle all key formats ("slug", "type", "flavor")
                flavor = get_modifier_name(syrup)
                qty = syrup.get("quantity", 1) or 1
                single_price = self.lookup_generic_modifier_price(
                    flavor, item_type, "syrup"
                )
                entry_upcharge = single_price * qty
                syrup_upcharge += entry_upcharge
                syrup["price"] = entry_upcharge  # Store for adapter display
        total += syrup_upcharge

        attr_values["syrup_upcharge"] = syrup_upcharge

        # Extra shots upcharge (for espresso drinks)
        extra_shots = attr_values.get("extra_shots", 0)
        extra_shots_upcharge = 0.0
        if extra_shots > 0:
            if extra_shots == 1:
                extra_shots_upcharge = self.lookup_generic_modifier_price(
                    "double_shot", item_type, "extras"
                )
            elif extra_shots >= 2:
                extra_shots_upcharge = self.lookup_generic_modifier_price(
                    "triple_shot", item_type, "extras"
                )
            total += extra_shots_upcharge

        attr_values["extra_shots_upcharge"] = extra_shots_upcharge

        # Protein upcharge
        protein = attr_values.get("extra_protein")
        if protein:
            protein_price = self.lookup_generic_modifier_price(
                protein, item_type
            )
            total += protein_price

        # Toppings upcharge (toppings, cheese, etc.)
        toppings = attr_values.get("toppings")
        if toppings:
            for extra in toppings:
                extra_price = self.lookup_generic_modifier_price(
                    extra, item_type
                )
                total += extra_price

        # Spread upcharge - try compound name, then base, then plain-prefixed
        spread = attr_values.get("spread") or attr_values.get("spread_type")
        spread_type = attr_values.get("spread_type")
        spread_upcharge = 0.0
        if spread and spread.lower() != "none":
            # Try compound spread name first (e.g., "scallion_cream_cheese")
            if spread_type:
                compound_slug = f"{spread_type}_{spread}".replace(" ", "_").lower()
                spread_upcharge = self.lookup_modifier_price(compound_slug, item_type)
            # Fall back to base spread name
            if spread_upcharge == 0.0:
                spread_upcharge = self.lookup_modifier_price(spread, item_type)
            # Fall back to plain-prefixed name (e.g., "plain_cream_cheese")
            if spread_upcharge == 0.0:
                plain_slug = f"plain_{spread.lower().replace(' ', '_')}"
                spread_upcharge = self.lookup_modifier_price(plain_slug, item_type)
            total += spread_upcharge

        attr_values["spread_price"] = spread_upcharge if spread_upcharge > 0 else None

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

    # =========================================================================
    # Display Name Helpers
    # =========================================================================

    def lookup_size_display_name(self, size_slug: str, item_type: str) -> str:
        """
        Look up the display name for a size from the database.

        Args:
            size_slug: The size slug (e.g., "small", "medium", "large")
            item_type: Item type to look up size options for

        Returns:
            The display name from the database (e.g., "Small", "Medium", "Large"),
            or the original slug if not found.

        Raises:
            ValueError: If menu_data is not loaded or item_type doesn't exist
        """
        if not size_slug:
            return size_slug

        size_lower = size_slug.lower().strip()

        if not self._menu_data:
            raise ValueError(
                f"Cannot look up size display name for '{size_slug}'. "
                "menu_data is required. Ensure menu is loaded."
            )

        item_types = self._menu_data.get("item_types", {})

        if not item_types:
            raise ValueError(
                f"Cannot look up size display name for '{size_slug}'. "
                "menu_data must contain 'item_types' structure. "
                "Ensure menu is loaded with full item type configuration."
            )

        type_data = item_types.get(item_type)

        if not type_data:
            raise ValueError(
                f"Item type '{item_type}' not found in menu_data. "
                f"Cannot look up size display name. "
                f"Available item types: {list(item_types.keys())}"
            )

        for attr in type_data.get("attributes", []):
            if attr.get("slug") == "size":
                for opt in attr.get("options", []):
                    opt_slug = opt.get("slug", "").lower()
                    if opt_slug == size_lower or size_lower in opt_slug:
                        display_name = opt.get("display_name")
                        if display_name:
                            return display_name

        # Not found - return the original slug as fallback (this is display, not pricing)
        return size_slug

    # =========================================================================
    # Menu Item Price Recalculation
    # =========================================================================

    def recalculate_menu_item_price(self, item) -> float:
        """
        Recalculate and update a menu item's price based on its current modifiers.

        For menu items like omelettes, the base price is the menu item price
        plus any spread upcharge for the side bagel.

        Args:
            item: The MenuItemTask to recalculate

        Returns:
            The new calculated price
        """
        # Get base price from menu item
        menu_item_data = None
        if hasattr(item, 'menu_item_id') and item.menu_item_id:
            from sandwich_bot.menu_data_cache import menu_cache
            menu_index = menu_cache.get_menu_index()
            if menu_index:
                # Search through all categories for the menu item
                for category_data in menu_index.get("categories", {}).values():
                    for mi in category_data.get("items", []):
                        if mi.get("id") == item.menu_item_id:
                            menu_item_data = mi
                            break
                    if menu_item_data:
                        break

        if not menu_item_data:
            raise ValueError(
                f"Cannot recalculate price for menu item '{getattr(item, 'menu_item_name', 'unknown')}'. "
                f"Menu item with id={getattr(item, 'menu_item_id', None)} not found in menu index. "
                "Ensure menu is loaded and item exists in database."
            )

        base_price = menu_item_data.get("base_price", 0.0)

        if base_price == 0:
            raise ValueError(
                f"Cannot recalculate price for menu item '{getattr(item, 'menu_item_name', 'unknown')}'. "
                f"base_price is missing or zero. "
                "Ensure menu item has a valid base_price in the database."
            )

        total = base_price

        # Determine item type for modifier price lookups (data-driven from DB)
        item_type_slug = (
            getattr(item, 'menu_item_type', None) or
            menu_item_data.get("item_type")
        )

        # Add spread upcharge if spread is set - try compound, base, then plain-prefixed
        if item.spread and item_type_slug:
            spread_type = getattr(item, 'spread_type', None)
            spread_price = 0.0
            # Try compound spread name first (e.g., "scallion_cream_cheese")
            if spread_type:
                compound_slug = f"{spread_type}_{item.spread}".replace(" ", "_").lower()
                spread_price = self.lookup_modifier_price(compound_slug, item_type_slug)
            # Fall back to base spread name
            if spread_price == 0.0:
                spread_price = self.lookup_modifier_price(item.spread, item_type_slug)
            # Fall back to plain-prefixed name (e.g., "plain_cream_cheese")
            if spread_price == 0.0:
                plain_slug = f"plain_{item.spread.lower().replace(' ', '_')}"
                spread_price = self.lookup_modifier_price(plain_slug, item_type_slug)
            item.spread_price = spread_price if spread_price > 0 else None
            total += spread_price
        else:
            item.spread_price = None

        # Update the item's price
        item.unit_price = round(total, 2)

        logger.info(
            "Recalculated menu item price: %s base=$%.2f + spread=$%.2f -> total=$%.2f",
            getattr(item, 'menu_item_name', 'unknown'),
            base_price,
            item.spread_price or 0.0,
            item.unit_price
        )

        return item.unit_price

    # =========================================================================
    # Category Pricing
    # =========================================================================

    def get_min_price_for_category(self, item_type: str) -> float:
        """
        Get the minimum (starting) price for a category of items.

        Args:
            item_type: The item type slug (e.g., 'bagel', 'sized_beverage', 'egg_sandwich')

        Returns:
            Minimum price found for the category

        Raises:
            ValueError: If menu_data is not loaded or no items found for category
        """
        if not self._menu_data:
            raise ValueError(
                f"Cannot get min price for category '{item_type}'. "
                "menu_data is required. Ensure menu is loaded."
            )

        items_by_type = self._menu_data.get("items_by_type", {})

        if not items_by_type:
            raise ValueError(
                f"Cannot get min price for category '{item_type}'. "
                "menu_data must contain 'items_by_type' structure. "
                "Ensure menu is loaded with full item configuration."
            )

        # Get items for this category
        items = items_by_type.get(item_type, [])
        if not items:
            raise ValueError(
                f"No items found for category '{item_type}'. "
                f"Available categories: {list(items_by_type.keys())}"
            )

        # Find minimum price
        prices = []
        for item in items:
            price = item.get("price") or item.get("base_price") or 0
            if price > 0:
                prices.append(price)

        if not prices:
            raise ValueError(
                f"No prices found for items in category '{item_type}'. "
                "Ensure menu items have base_price configured."
            )

        return min(prices)
