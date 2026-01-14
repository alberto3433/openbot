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

    def lookup_base_price(self, menu_item_name: str) -> float:
        """Look up base price for any menu item by name.

        This is the generic way to get base prices - works for bagels, coffee,
        sandwiches, or any other menu item type.

        Args:
            menu_item_name: Name of the menu item (e.g., "Bagel", "Latte", "BLT")

        Returns:
            Base price for the menu item

        Raises:
            ValueError: If menu item not found in database
        """
        if not menu_item_name:
            raise ValueError("menu_item_name is required for base price lookup")

        menu_item = self._lookup_menu_item(menu_item_name)
        if menu_item and menu_item.get("base_price"):
            return menu_item["base_price"]

        # Try title case variation
        menu_item = self._lookup_menu_item(menu_item_name.title())
        if menu_item and menu_item.get("base_price"):
            return menu_item["base_price"]

        raise ValueError(
            f"No price found for menu item '{menu_item_name}'. "
            "Ensure the menu item exists in database with a base_price."
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

        This handles cases like iced drinks where the upcharge depends on size:
        - When temperature="iced", look up "iced_price_modifier" from size options

        The pattern is: {condition_value}_price_modifier on the source attribute options.

        Args:
            item_type: Item type slug (e.g., "sized_beverage")
            source_attr: Attribute to look up the modifier from (e.g., "size")
            source_value: Selected value of source attribute (e.g., "large")
            modifier_column: Column name for the conditional modifier (e.g., "iced_price_modifier")

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

        # Backwards compatibility: if item_types is not in menu_data, return 0
        # (legacy test fixtures don't have item_types structure)
        if "item_types" not in self._menu_data:
            logger.debug(
                "No item_types in menu_data. Returning $0.00 for conditional upcharge '%s.%s'.",
                source_attr, modifier_column
            )
            return 0.0

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

        # Remove common suffixes for matching
        if normalized.endswith("_milk"):
            normalized = normalized[:-5]
        if normalized.endswith("_syrup"):
            normalized = normalized[:-6]

        if not self._menu_data:
            raise ValueError(
                f"Cannot look up modifier price for '{modifier_name}'. "
                "menu_data is required. Ensure menu is loaded."
            )

        item_types = self._menu_data.get("item_types", {})

        # Backwards compatibility: if item_types is not in menu_data, return 0
        # (legacy test fixtures don't have item_types structure)
        if "item_types" not in self._menu_data:
            logger.debug(
                "No item_types in menu_data. Returning $0.00 for modifier '%s'.",
                modifier_name
            )
            return 0.0

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
                # Also check consolidated attribute "milk_sweetener_syrup"
                if attr_slug != "milk_sweetener_syrup" or modifier_type not in ("milk", "syrup", "sweetener"):
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
    # By-the-Pound Pricing
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

    def lookup_by_pound_price(self, item_name: str) -> float:
        """Look up the per-pound price for a by-the-pound item.

        Args:
            item_name: Name of the item (e.g., "Muenster", "Nova", "Tuna Salad")

        Returns:
            Price per pound

        Raises:
            ValueError: If price not found for the item
        """
        item_lower = item_name.lower().strip()

        # Get by-pound prices from menu_data
        by_pound_prices = self._menu_data.get("by_pound_prices", {}) if self._menu_data else {}

        if not by_pound_prices:
            raise ValueError(
                f"No by_pound_prices in menu_data. Cannot look up price for '{item_name}'. "
                "Ensure menu is populated with by-the-pound items."
            )

        # Direct lookup
        if item_lower in by_pound_prices:
            return by_pound_prices[item_lower]

        # Try partial matching for items like "Nova" -> "nova scotia salmon"
        for price_key, price in by_pound_prices.items():
            if item_lower in price_key or price_key in item_lower:
                return price

        # Not found - raise error
        available_items = list(by_pound_prices.keys())[:10]  # Show first 10 for debugging
        raise ValueError(
            f"No price found for by-pound item: '{item_name}'. "
            f"Available items include: {available_items}"
        )

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

        # Normalize common variations
        normalized = modifier_lower.replace("-", "_").replace(" ", "_")
        # Handle lox/nova variations (common aliases)
        if modifier_lower in ("lox", "nova"):
            normalized = "nova_scotia_salmon"

        if not self._menu_data:
            raise ValueError(
                f"Cannot look up modifier price for '{modifier_name}'. "
                "menu_data is required. Ensure menu is loaded."
            )

        item_types = self._menu_data.get("item_types", {})

        # Backwards compatibility: if item_types is not in menu_data, return 0
        # (legacy test fixtures don't have item_types structure)
        if "item_types" not in self._menu_data:
            logger.debug(
                "No item_types in menu_data. Returning $0.00 for modifier '%s'.",
                modifier_name
            )
            return 0.0

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

    def lookup_spread_price(
        self,
        spread: str,
        spread_type: str | None = None,
        item_type: str = "bagel",
    ) -> float:
        """
        Look up upcharge price for adding a spread to an item.

        NOTE: This returns the UPCHARGE for adding spread, not the per-pound
        retail price. Spread upcharges are stored in the database under the "spread"
        attribute definition (e.g., cream_cheese has price_modifier=1.50).

        Args:
            spread: Base spread name (e.g., "cream cheese")
            spread_type: Spread flavor/variant (e.g., "tofu", "scallion")
            item_type: Item type to look up spread price for (default "bagel")

        Returns:
            Upcharge price for the spread (e.g., $1.50 for cream cheese, $1.75 for scallion)
        """
        # Build full spread name for specialty spreads (e.g., "scallion cream cheese")
        if spread_type and spread_type.lower() not in ("plain", "regular"):
            full_spread_name = f"{spread_type}_{spread}".replace(" ", "_").lower()
            # Check if we have a specific price for this specialty spread
            specialty_price = self.lookup_modifier_price(full_spread_name, item_type)
            if specialty_price > 0:
                logger.debug(
                    "Found specialty spread upcharge: %s = $%.2f",
                    full_spread_name, specialty_price
                )
                return specialty_price

        # Look up the base spread price from the database
        # (e.g., "cream cheese" -> $1.50, "butter" -> $0.50)
        spread_price = self.lookup_modifier_price(spread, item_type)
        if spread_price > 0:
            logger.debug(
                "Using spread upcharge: %s = $%.2f",
                spread, spread_price
            )
            return spread_price

        # For cream cheese without a type, try "plain_cream_cheese" (database canonical name)
        spread_normalized = spread.lower().replace(" ", "_")
        if spread_normalized == "cream_cheese":
            spread_price = self.lookup_modifier_price("plain_cream_cheese", item_type)
            if spread_price > 0:
                logger.debug(
                    "Using plain cream cheese upcharge: $%.2f",
                    spread_price
                )
                return spread_price

        return spread_price

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

        # Get base price from menu item name - fail if not found
        base_price = self.lookup_base_price(item.menu_item_name)

        total = base_price

        # Get attribute values from the item
        attr_values = getattr(item, 'attribute_values', {})

        # =====================================================================
        # 1. Attribute option upcharges (size, bread type, etc.)
        # =====================================================================

        # Size upcharge (for items with size attribute)
        size_value = attr_values.get("size")
        size_upcharge = 0.0
        if size_value and size_value.lower() not in ("small", "s"):
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
        # 2. Conditional upcharges (iced depends on size)
        # =====================================================================

        # Iced upcharge - varies by size, stored as iced_price_modifier on size options
        temperature_value = attr_values.get("temperature")
        iced_upcharge = 0.0
        if temperature_value == "iced" and size_value:
            iced_upcharge = self.lookup_conditional_upcharge(
                item_type,
                "size",
                size_value,
                "iced_price_modifier"
            )
            total += iced_upcharge

        if hasattr(item, 'iced_upcharge'):
            item.iced_upcharge = iced_upcharge

        # =====================================================================
        # 3. Modifier upcharges (milk, syrup, protein, spread, extras)
        # =====================================================================

        # Milk upcharge - use item.milk property (handles unified storage)
        milk_value = item.milk if hasattr(item, 'milk') else attr_values.get("milk")
        milk_upcharge = 0.0
        if milk_value:
            milk_upcharge = self.lookup_generic_modifier_price(
                milk_value, item_type, "milk"
            )
            total += milk_upcharge

        if hasattr(item, 'milk_upcharge'):
            item.milk_upcharge = milk_upcharge

        # Syrup upcharge (sum of all syrups * quantities)
        # Use item.flavor_syrups property (handles unified storage with category filtering)
        syrup_selections = item.flavor_syrups if hasattr(item, 'flavor_syrups') else attr_values.get("syrup_selections", [])
        syrup_upcharge = 0.0
        for syrup in syrup_selections:
            if isinstance(syrup, dict):
                # Support both old format ("flavor") and new unified format ("slug")
                flavor = syrup.get("slug") or syrup.get("flavor", "")
                qty = syrup.get("quantity", 1) or 1
                single_price = self.lookup_generic_modifier_price(
                    flavor, item_type, "syrup"
                )
                entry_upcharge = single_price * qty
                syrup_upcharge += entry_upcharge
                syrup["price"] = entry_upcharge  # Store for adapter display
        total += syrup_upcharge

        if hasattr(item, 'syrup_upcharge'):
            item.syrup_upcharge = syrup_upcharge

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

        if hasattr(item, 'extra_shots_upcharge'):
            item.extra_shots_upcharge = extra_shots_upcharge

        # Protein upcharge
        protein = getattr(item, 'extra_protein', None)
        if protein:
            protein_price = self.lookup_generic_modifier_price(
                protein, item_type
            )
            total += protein_price

        # Toppings upcharge (toppings, cheese, etc.)
        toppings = getattr(item, 'toppings', None)
        if toppings:
            for extra in toppings:
                extra_price = self.lookup_generic_modifier_price(
                    extra, item_type
                )
                total += extra_price

        # Spread upcharge
        spread = getattr(item, 'spread', None)
        spread_type = getattr(item, 'spread_type', None)
        spread_upcharge = 0.0
        if spread and spread.lower() != "none":
            spread_upcharge = self.lookup_spread_price(spread, spread_type, item_type)
            total += spread_upcharge

        if hasattr(item, 'spread_price'):
            item.spread_price = spread_upcharge if spread_upcharge > 0 else None

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

    def lookup_temperature_display_name(
        self,
        temperature: str | bool,
        item_type: str,
    ) -> str:
        """
        Look up the display name for temperature (hot/iced) from the database.

        Args:
            temperature: "iced", "hot", True (for iced), or False (for hot)
            item_type: Item type to look up temperature options for

        Returns:
            The display name from the database (e.g., "Iced", "Hot"),
            or the slug if not found.

        Raises:
            ValueError: If menu_data is not loaded or item_type doesn't exist
        """
        # Support both string and legacy boolean format
        if isinstance(temperature, bool):
            target_slug = "iced" if temperature else "hot"
        else:
            target_slug = temperature  # Already "iced" or "hot"

        if not self._menu_data:
            raise ValueError(
                f"Cannot look up temperature display name for '{target_slug}'. "
                "menu_data is required. Ensure menu is loaded."
            )

        item_types = self._menu_data.get("item_types", {})

        # Backwards compatibility: if item_types is not in menu_data, return slug as-is
        # (legacy test fixtures don't have item_types structure)
        if "item_types" not in self._menu_data:
            return target_slug

        type_data = item_types.get(item_type)

        if not type_data:
            raise ValueError(
                f"Item type '{item_type}' not found in menu_data. "
                f"Cannot look up temperature display name. "
                f"Available item types: {list(item_types.keys())}"
            )

        for attr in type_data.get("attributes", []):
            if attr.get("slug") == "temperature":
                for opt in attr.get("options", []):
                    if opt.get("slug") == target_slug:
                        display_name = opt.get("display_name")
                        if display_name:
                            return display_name

        # Not found - return the slug as fallback (this is display, not pricing)
        return target_slug

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

        # Backwards compatibility: if item_types is not in menu_data, return slug as-is
        # (legacy test fixtures don't have item_types structure)
        if "item_types" not in self._menu_data:
            return size_slug

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

        base_price = menu_item_data.get("base_price", 0.0) if menu_item_data else 0.0

        # Fallback: if we don't have menu data, calculate base from current price minus spread
        if base_price == 0 and item.unit_price:
            base_price = item.unit_price
            if item.spread_price:
                base_price -= item.spread_price

        total = base_price

        # Add spread upcharge if spread is set
        if item.spread:
            spread_price = self.lookup_spread_price(item.spread)
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

        # Backwards compatibility: if items_by_type is not in menu_data, return 0
        # (legacy test fixtures don't have items_by_type structure)
        if "items_by_type" not in self._menu_data:
            logger.debug(
                "No items_by_type in menu_data. Returning $0.00 for min price of '%s'.",
                item_type
            )
            return 0.0

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
