"""
Pricing Engine for Order Items.

This module handles all price lookups and calculations for menu items,
including bagels, coffee, by-the-pound items, and their modifiers.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import re
from typing import Callable

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
    # Bagel type upcharges are also stored in the database under the "bagel_type"
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
    # Bagel Pricing
    # =========================================================================

    def lookup_bagel_price(self, bagel_type: str | None) -> float:
        """
        Look up price for a bagel type.

        For regular bagel types (plain, everything, sesame, etc.), returns the
        generic "Bagel" price from the menu. Only specialty bagels like
        "Gluten Free" get their specific price.

        Args:
            bagel_type: The bagel type (e.g., "plain", "everything", "gluten free")

        Returns:
            Price for the bagel

        Raises:
            ValueError: If bagel price is not found in the database
        """
        if not bagel_type:
            # Look up generic bagel price
            menu_item = self._lookup_menu_item("Bagel")
            if menu_item and menu_item.get("base_price"):
                return menu_item["base_price"]
            raise ValueError(
                "No price found for bagels. Ensure 'Bagel' menu item exists in database with a base_price."
            )

        bagel_type_lower = bagel_type.lower()

        # Specialty bagels that have their own menu items
        specialty_bagels = ["gluten free", "gluten-free"]

        if any(specialty in bagel_type_lower for specialty in specialty_bagels):
            # Look for specific specialty bagel as menu item first
            bagel_name = f"{bagel_type.title()} Bagel" if "bagel" not in bagel_type_lower else bagel_type
            menu_item = self._lookup_menu_item(bagel_name)
            if menu_item and menu_item.get("base_price"):
                logger.info("Found specialty bagel: %s ($%.2f)", menu_item.get("name"), menu_item["base_price"])
                return menu_item["base_price"]

            # Try bread_prices from menu_data (ingredients table)
            if self._menu_data:
                bread_prices = self._menu_data.get("bread_prices", {})
                # Try exact match
                bagel_key = bagel_name.lower()
                if bagel_key in bread_prices:
                    price = bread_prices[bagel_key]
                    logger.info("Found specialty bagel in bread_prices: %s ($%.2f)", bagel_name, price)
                    return price
                # Try partial match for specialty type (e.g., "gluten free bagel")
                for bread_name, price in bread_prices.items():
                    if any(specialty in bread_name for specialty in specialty_bagels):
                        logger.info("Found specialty bagel in bread_prices (partial): %s ($%.2f)", bread_name, price)
                        return price

        # For regular bagels, look for the generic "Bagel" item
        menu_item = self._lookup_menu_item("Bagel")
        if menu_item and menu_item.get("base_price"):
            logger.info("Using generic bagel price: $%.2f", menu_item["base_price"])
            return menu_item["base_price"]

        # No price found - raise error
        raise ValueError(
            f"No price found for bagel type '{bagel_type}'. "
            "Ensure bagel menu items exist in database with base_price."
        )

    def get_bagel_base_price(self) -> float:
        """
        Get the base price for a regular bagel (without any specialty upcharge).

        Returns:
            Base bagel price from the database

        Raises:
            ValueError: If bagel price is not found in the database
        """
        menu_item = self._lookup_menu_item("Bagel")
        if menu_item and menu_item.get("base_price"):
            return menu_item["base_price"]
        raise ValueError(
            "No base price found for bagels. Ensure 'Bagel' menu item exists in database with a base_price."
        )

    def get_bagel_type_upcharge(self, bagel_type: str | None) -> float:
        """
        Get the upcharge for a specialty bagel type.

        Regular bagels (plain, everything, sesame, etc.) have no upcharge.
        Specialty bagels like gluten free have an upcharge.

        Bagel type upcharges are stored in the database under the "bagel_type"
        attribute definition (e.g., gluten_free has price_modifier=0.80).

        Args:
            bagel_type: The bagel type (e.g., "plain", "gluten free")

        Returns:
            Upcharge amount (e.g., $0.80 for gluten free, $0.00 for regular)
        """
        if not bagel_type:
            return 0.0

        bagel_type_lower = bagel_type.lower().strip()
        normalized = bagel_type_lower.replace("-", "_").replace(" ", "_")

        # Check partial match for "gluten free" variations (e.g., "gluten free everything")
        if "gluten" in bagel_type_lower and "free" in bagel_type_lower:
            normalized = "gluten_free"

        if not self._menu_data:
            logger.warning("No menu_data available for bagel type upcharge lookup")
            return 0.0

        item_types = self._menu_data.get("item_types", {})
        bagel_type_data = item_types.get("bagel", {})
        attributes = bagel_type_data.get("attributes", [])

        # Look for the bagel_type attribute
        for attr in attributes:
            if attr.get("slug") == "bagel_type":
                options = attr.get("options", [])
                for opt in options:
                    opt_slug = opt.get("slug", "").lower().replace("-", "_")
                    opt_name = opt.get("display_name", "").lower().replace("-", "_").replace(" ", "_")

                    # Match by slug or display_name
                    if opt_slug == normalized or opt_name == normalized or \
                       opt_slug == bagel_type_lower.replace(" ", "_"):
                        upcharge = opt.get("price_modifier", 0.0)
                        if upcharge > 0:
                            logger.debug("Bagel type upcharge: %s = +$%.2f", bagel_type, upcharge)
                        return upcharge

        # Not found in database - regular bagels have no upcharge
        logger.debug("Bagel type '%s' not found in database, assuming no upcharge", bagel_type)
        return 0.0

    def lookup_modifier_price(self, modifier_name: str, item_type: str = "bagel") -> float:
        """
        Look up price modifier for a bagel add-on (protein, cheese, topping).

        Searches the item_types attribute options for matching modifier prices.
        Prices are stored in the database and must be present.

        Args:
            modifier_name: Name of the modifier (e.g., "ham", "egg", "american")
            item_type: Item type to look up (default "bagel", falls back to "sandwich")

        Returns:
            Price modifier (e.g., 2.00 for ham) or 0.0 if modifier is free

        Raises:
            ValueError: If menu_data is not available
        """
        modifier_lower = modifier_name.lower().strip()

        # Normalize common variations
        normalized = modifier_lower.replace("-", "_").replace(" ", "_")
        # Handle lox/nova variations
        if modifier_lower in ("lox", "nova"):
            normalized = "nova_scotia_salmon"

        if not self._menu_data:
            raise ValueError(
                f"Cannot look up modifier price for '{modifier_name}'. "
                "menu_data is required. Ensure menu is loaded."
            )

        item_types = self._menu_data.get("item_types", {})

        # Try the specified item type first, then fall back to sandwich
        types_to_check = [item_type, "sandwich"] if item_type != "sandwich" else ["sandwich"]

        for type_slug in types_to_check:
            type_data = item_types.get(type_slug, {})
            attributes = type_data.get("attributes", [])

            # Search through modifier attributes (protein, cheese, toppings, spread, etc.)
            # Skip bagel_type attribute - it's for bagel variety upcharges, not add-on modifiers
            # (e.g., "egg bagel" is a bagel type, "egg" protein is a modifier)
            for attr in attributes:
                if attr.get("slug") == "bagel_type":
                    continue  # Skip - bagel types are handled by get_bagel_type_upcharge()
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
                            modifier_name, price, type_slug, attr.get("slug")
                        )
                        return price

        # Not found in database - return 0.0 for unknown modifiers
        # This allows new modifiers to be added without code changes
        logger.warning(
            "Modifier '%s' not found in database for item_type '%s'. Returning $0.00.",
            modifier_name, item_type
        )
        return 0.0

    def lookup_spread_price(self, spread: str, spread_type: str | None = None) -> float:
        """
        Look up upcharge price for adding a spread to a bagel.

        NOTE: This returns the UPCHARGE for adding spread to a bagel, not the per-pound
        retail price. Spread upcharges are stored in the database under the "spread"
        attribute definition (e.g., cream_cheese has price_modifier=1.50).

        Args:
            spread: Base spread name (e.g., "cream cheese")
            spread_type: Spread flavor/variant (e.g., "tofu", "scallion")

        Returns:
            Upcharge price for the spread (e.g., $1.50 for cream cheese, $1.75 for scallion)
        """
        # Build full spread name for specialty spreads (e.g., "scallion cream cheese")
        if spread_type and spread_type.lower() not in ("plain", "regular"):
            full_spread_name = f"{spread_type}_{spread}".replace(" ", "_").lower()
            # Check if we have a specific price for this specialty spread
            specialty_price = self.lookup_modifier_price(full_spread_name, "bagel")
            if specialty_price > 0:
                logger.debug(
                    "Found specialty spread upcharge: %s = $%.2f",
                    full_spread_name, specialty_price
                )
                return specialty_price

        # Look up the base spread price from the database
        # (e.g., "cream cheese" -> $1.50, "butter" -> $0.50)
        spread_price = self.lookup_modifier_price(spread, "bagel")
        if spread_price > 0:
            logger.debug(
                "Using spread upcharge: %s = $%.2f",
                spread, spread_price
            )
        return spread_price

    def calculate_bagel_price_with_modifiers(
        self,
        base_price: float,
        sandwich_protein: str | None,
        extras: list[str] | None,
        spread: str | None,
        spread_type: str | None = None,
    ) -> float:
        """
        Calculate total bagel price including modifiers.

        Args:
            base_price: Base bagel price
            sandwich_protein: Primary protein (e.g., "ham")
            extras: Additional modifiers (e.g., ["egg", "american"])
            spread: Spread choice (e.g., "cream cheese")
            spread_type: Spread flavor/variant (e.g., "tofu", "scallion")

        Returns:
            Total price including all modifiers
        """
        total = base_price

        # Add protein price
        if sandwich_protein:
            total += self.lookup_modifier_price(sandwich_protein)

        # Add extras prices
        if extras:
            for extra in extras:
                total += self.lookup_modifier_price(extra)

        # Add spread price (if not "none")
        if spread and spread.lower() != "none":
            total += self.lookup_spread_price(spread, spread_type)

        return round(total, 2)

    def recalculate_bagel_price(self, item) -> float:
        """
        Recalculate and update a bagel item's price based on its current modifiers.

        This should be called whenever a bagel's modifiers change (spread, protein, extras)
        to ensure price is always in sync with the item's state.

        Args:
            item: The bagel item (BagelItemTask) to update

        Returns:
            The new calculated price
        """
        # Get base bagel price (regular bagel, not specialty)
        base_price = self.get_bagel_base_price()

        # Calculate and store bagel type upcharge (e.g., gluten free +$0.80)
        bagel_type_upcharge = self.get_bagel_type_upcharge(item.bagel_type)
        item.bagel_type_upcharge = bagel_type_upcharge

        # Start with base + bagel type upcharge
        total = base_price + bagel_type_upcharge

        # Add protein price
        if item.sandwich_protein:
            total += self.lookup_modifier_price(item.sandwich_protein)

        # Add extras prices
        if item.extras:
            for extra in item.extras:
                total += self.lookup_modifier_price(extra)

        # Add spread price (if not "none")
        if item.spread and item.spread.lower() != "none":
            total += self.lookup_spread_price(item.spread, item.spread_type)

        # Update the item's price
        new_price = round(total, 2)
        item.unit_price = new_price

        logger.info(
            "Recalculated bagel price: base=$%.2f + type_upcharge=$%.2f + modifiers -> total=$%.2f",
            base_price, bagel_type_upcharge, new_price
        )

        return new_price

    # =========================================================================
    # Coffee Pricing
    # =========================================================================

    def lookup_coffee_price(self, coffee_type: str | None) -> float:
        """
        Look up price for a coffee type from the database.

        Args:
            coffee_type: Name of the coffee drink (e.g., "Coffee", "Latte", "Espresso")

        Returns:
            Base price for the coffee type

        Raises:
            ValueError: If coffee price not found in database
        """
        if not coffee_type:
            # Look for generic "Coffee" item
            menu_item = self._lookup_menu_item("Coffee")
            if menu_item and menu_item.get("base_price"):
                return menu_item["base_price"]
            raise ValueError(
                "No price found for coffee. Ensure 'Coffee' menu item exists in database with a base_price."
            )

        # Look up from menu
        menu_item = self._lookup_menu_item(coffee_type)
        if menu_item and menu_item.get("base_price"):
            return menu_item["base_price"]

        # Try variations (e.g., "Latte" vs "latte")
        menu_item = self._lookup_menu_item(coffee_type.title())
        if menu_item and menu_item.get("base_price"):
            return menu_item["base_price"]

        raise ValueError(
            f"No price found for coffee type '{coffee_type}'. "
            "Ensure the menu item exists in database with a base_price."
        )

    def lookup_coffee_modifier_price(self, modifier_name: str, modifier_type: str = "syrup") -> float:
        """
        Look up price modifier for a coffee add-on (syrup, milk, size).

        Searches the attribute_options in the database for matching modifier prices.
        Modifier prices are stored under the sized_beverage item type with
        attributes like "milk", "syrup", and "size".

        Args:
            modifier_name: Name of the modifier (e.g., "oat", "vanilla", "large")
            modifier_type: Type of modifier to look for ("syrup", "milk", "size")

        Returns:
            Price modifier or 0.0 if free/not found

        Raises:
            ValueError: If menu_data is not available
        """
        if not modifier_name:
            return 0.0

        modifier_lower = modifier_name.lower().strip()
        normalized = modifier_lower.replace(" ", "_").replace("-", "_")
        # Remove "milk" or "syrup" suffix for matching (e.g., "oat milk" -> "oat")
        if normalized.endswith("_milk"):
            normalized = normalized[:-5]
        if normalized.endswith("_syrup"):
            normalized = normalized[:-6]

        if not self._menu_data:
            raise ValueError(
                f"Cannot look up coffee modifier price for '{modifier_name}'. "
                "menu_data is required. Ensure menu is loaded."
            )

        item_types = self._menu_data.get("item_types", {})

        # Try sized_beverage first, then any item type
        types_to_check = ["sized_beverage"] + [t for t in item_types.keys() if t != "sized_beverage"]

        for type_slug in types_to_check:
            type_data = item_types.get(type_slug, {})
            if not isinstance(type_data, dict):
                continue
            attrs = type_data.get("attributes", [])
            for attr in attrs:
                if not isinstance(attr, dict):
                    continue
                attr_slug = attr.get("slug", "")
                # Match by modifier type (syrup, milk, size)
                if modifier_type in attr_slug or attr_slug == modifier_type:
                    options = attr.get("options", [])
                    for opt in options:
                        if not isinstance(opt, dict):
                            continue
                        opt_slug = opt.get("slug", "").lower()
                        opt_name = opt.get("display_name", "").lower().replace(" ", "_")

                        if opt_slug == normalized or opt_name == normalized or \
                           modifier_lower in opt_slug or opt_slug in modifier_lower:
                            price = opt.get("price_modifier", 0.0)
                            logger.debug(
                                "Found coffee modifier price: %s = $%.2f (from %s.%s)",
                                modifier_name, price, type_slug, attr_slug
                            )
                            return price

        # Not found - return 0.0 for unknown modifiers
        logger.warning(
            "Coffee modifier '%s' (type=%s) not found in database. Returning $0.00.",
            modifier_name, modifier_type
        )
        return 0.0

    def lookup_iced_upcharge_by_size(self, size: str | None) -> float:
        """
        Look up the iced upcharge for a given size.

        The iced upcharge is stored per size in the attribute_options table
        as iced_price_modifier. Different sizes may have different iced upcharges.
        This was populated by migration 2b9737e29757_seed_coffee_sizes_with_iced_upcharges.py

        Args:
            size: Size selection (small, large)

        Returns:
            The iced upcharge for that size, or 0.0 if not found

        Raises:
            ValueError: If menu_data is not available
        """
        if not size:
            return 0.0

        size_lower = size.lower().strip()

        if not self._menu_data:
            raise ValueError(
                f"Cannot look up iced upcharge for size '{size}'. "
                "menu_data is required. Ensure menu is loaded."
            )

        item_types = self._menu_data.get("item_types", {})

        # Search through item types for size attribute with iced_price_modifier
        for type_slug, type_data in item_types.items():
            if not isinstance(type_data, dict):
                continue
            attrs = type_data.get("attributes", [])
            for attr in attrs:
                if not isinstance(attr, dict):
                    continue
                attr_slug = attr.get("slug", "")
                # Look for size attribute
                if attr_slug == "size":
                    options = attr.get("options", [])
                    for opt in options:
                        if not isinstance(opt, dict):
                            continue
                        opt_slug = opt.get("slug", "").lower()
                        if opt_slug == size_lower or size_lower in opt_slug:
                            iced_price = opt.get("iced_price_modifier", 0.0)
                            logger.debug(
                                "Found iced upcharge for size %s: $%.2f",
                                size, iced_price
                            )
                            return iced_price

        # Not found - log warning and return 0.0
        logger.warning(
            "Iced upcharge for size '%s' not found in database. Returning $0.00.",
            size
        )
        return 0.0

    def calculate_coffee_price_with_modifiers(
        self,
        base_price: float,
        size: str | None,
        milk: str | None,
        flavor_syrup: str | None,
    ) -> float:
        """
        Calculate total coffee price including modifiers.

        Args:
            base_price: Base coffee price (usually for small size)
            size: Size selection (small, medium, large)
            milk: Milk choice (regular, oat, almond, soy)
            flavor_syrup: Flavor syrup (vanilla, hazelnut, etc.)

        Returns:
            Total price including all modifiers
        """
        total = base_price

        # Add size upcharge (small is base price, medium/large have upcharges)
        if size and size.lower() not in ("small", "s"):
            size_upcharge = self.lookup_coffee_modifier_price(size, "size")
            total += size_upcharge
            if size_upcharge > 0:
                logger.debug("Coffee size upcharge: %s = +$%.2f", size, size_upcharge)

        # Add milk alternative upcharge (regular milk is free)
        if milk and milk.lower() not in ("regular", "whole", "2%", "skim", "none", "no milk"):
            milk_upcharge = self.lookup_coffee_modifier_price(milk, "milk")
            total += milk_upcharge
            if milk_upcharge > 0:
                logger.debug("Coffee milk upcharge: %s = +$%.2f", milk, milk_upcharge)

        # Add flavor syrup upcharge
        if flavor_syrup:
            syrup_upcharge = self.lookup_coffee_modifier_price(flavor_syrup, "syrup")
            total += syrup_upcharge
            if syrup_upcharge > 0:
                logger.debug("Coffee syrup upcharge: %s = +$%.2f", flavor_syrup, syrup_upcharge)

        return total

    def recalculate_coffee_price(self, item) -> float:
        """
        Recalculate and update a coffee item's price based on its current modifiers.

        Args:
            item: The CoffeeItemTask to recalculate

        Returns:
            The new calculated price
        """
        # Get base price from drink type
        base_price = self.lookup_coffee_price(item.drink_type)
        total = base_price

        # Calculate and store individual upcharges
        # Size upcharge (small is base price)
        size_upcharge = 0.0
        if item.size and item.size.lower() not in ("small", "s"):
            size_upcharge = self.lookup_coffee_modifier_price(item.size, "size")
            total += size_upcharge
        item.size_upcharge = size_upcharge

        # Milk alternative upcharge (regular milk is free)
        milk_upcharge = 0.0
        if item.milk and item.milk.lower() not in ("regular", "whole", "2%", "skim", "none", "no milk"):
            milk_upcharge = self.lookup_coffee_modifier_price(item.milk, "milk")
            total += milk_upcharge
        item.milk_upcharge = milk_upcharge

        # Flavor syrups upcharge (sum of all syrups * quantities)
        syrup_upcharge = 0.0
        if item.flavor_syrups:
            for syrup in item.flavor_syrups:
                flavor = syrup.get("flavor", "")
                qty = syrup.get("quantity", 1) or 1
                single_syrup_price = self.lookup_coffee_modifier_price(flavor, "syrup")
                syrup_upcharge += single_syrup_price * qty
            total += syrup_upcharge
        item.syrup_upcharge = syrup_upcharge

        # Iced upcharge (varies by size)
        iced_upcharge = 0.0
        if item.iced is True and item.size:
            iced_upcharge = self.lookup_iced_upcharge_by_size(item.size)
            total += iced_upcharge
        item.iced_upcharge = iced_upcharge

        # Update the item's price
        item.unit_price = total

        logger.info(
            "Recalculated coffee price: base=$%.2f + size=$%.2f + milk=$%.2f + syrup=$%.2f + iced=$%.2f -> total=$%.2f",
            base_price, size_upcharge, milk_upcharge, syrup_upcharge, iced_upcharge, total
        )

        return total

    # =========================================================================
    # Category Pricing
    # =========================================================================

    def get_min_price_for_category(self, item_type: str) -> float:
        """
        Get the minimum (starting) price for a category of items.

        Args:
            item_type: The item type slug (e.g., 'bagel', 'sized_beverage', 'egg_sandwich')

        Returns:
            Minimum price found for the category, or 0 if not found
        """
        if not self._menu_data:
            # Return sensible defaults for common categories
            defaults = {
                "bagel": 2.50,
                "sized_beverage": 2.50,
                "beverage": 2.00,
                "egg_sandwich": 6.95,
                "omelette": 8.95,
                "side": 1.50,
            }
            return defaults.get(item_type, 0)

        items_by_type = self._menu_data.get("items_by_type", {})

        # Special handling for bagels - use lookup_bagel_price
        if item_type == "bagel":
            return self.lookup_bagel_price(None)

        # Get items for this category
        items = items_by_type.get(item_type, [])
        if not items:
            return 0

        # Find minimum price
        prices = []
        for item in items:
            price = item.get("price") or item.get("base_price") or 0
            if price > 0:
                prices.append(price)

        return min(prices) if prices else 0
