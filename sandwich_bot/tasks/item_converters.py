"""
Item Converters for Adapter Layer.

This module provides the Strategy pattern implementation for converting
between dict-based item representations and ItemTask objects.

Each item type (bagel, coffee, espresso, menu_item, signature_item) has
its own converter class that handles bidirectional conversion.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, TYPE_CHECKING

from .models import (
    TaskStatus,
    ItemTask,
    MenuItemTask,
)
from sandwich_bot.menu_data_cache import menu_cache

if TYPE_CHECKING:
    from .pricing import PricingEngine

logger = logging.getLogger(__name__)


class ItemConverter(ABC):
    """Abstract base class for item type converters."""

    @property
    @abstractmethod
    def item_type(self) -> str:
        """The item type string this converter handles."""
        pass

    @abstractmethod
    def from_dict(self, item_dict: Dict[str, Any]) -> ItemTask:
        """
        Convert a dict representation to an ItemTask.

        Args:
            item_dict: The dict-based item representation

        Returns:
            The appropriate ItemTask subclass instance
        """
        pass

    @abstractmethod
    def to_dict(
        self,
        item: ItemTask,
        pricing: "PricingEngine | None" = None,
    ) -> Dict[str, Any]:
        """
        Convert an ItemTask to dict representation.

        Args:
            item: The ItemTask instance
            pricing: Optional PricingEngine for price lookups

        Returns:
            Dict representation of the item
        """
        pass

    def _restore_common_fields(self, item: ItemTask, item_dict: Dict[str, Any]) -> None:
        """Restore common fields shared by all item types."""
        if item_dict.get("id"):
            item.id = item_dict["id"]
        if item_dict.get("status"):
            item.status = TaskStatus(item_dict["status"])
        if item_dict.get("unit_price"):
            item.unit_price = item_dict["unit_price"]

    @property
    def output_item_type(self) -> str:
        """The item_type to use in dict output. Override for backwards compatibility."""
        return self.item_type

    def _build_common_dict_fields(self, item: ItemTask) -> Dict[str, Any]:
        """Build common dict fields shared by all item types."""
        return {
            "item_type": self.output_item_type,
            "id": item.id,
            "status": item.status.value,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "line_total": (item.unit_price or 0) * item.quantity,
            "special_instructions": getattr(item, 'special_instructions', None),
        }

    def _process_attribute_values_to_modifiers(
        self,
        attribute_values: Dict[str, Any],
        modifiers: list,
        free_details: list,
        pricing: "PricingEngine | None" = None,
        skip_slugs: set | None = None,
        price_lookup_fn=None,
        include_free_in_modifiers: bool = False,
    ) -> float:
        """
        Generic data-driven processing of attribute_values into modifiers/free_details.

        Iterates through all attribute_values and builds modifier entries for priced
        attributes and free_details entries for non-priced ones.

        Args:
            attribute_values: Dict of attribute slug -> value
            modifiers: List to append priced modifiers to (mutated)
            free_details: List to append free details to (mutated)
            pricing: Optional PricingEngine for price and display name lookups
            skip_slugs: Set of attribute slugs to skip (e.g., "bread" for sandwiches)
            price_lookup_fn: Optional function(attr_slug, attr_value, pricing) -> float
                             for custom price lookups (e.g., coffee-specific lookups)
            include_free_in_modifiers: If True, add free items to modifiers with price=0
                                       instead of to free_details (useful for cart display)

        Returns:
            Total upcharge amount from all processed attributes
        """
        skip_slugs = skip_slugs or set()
        total_upcharges = 0.0
        processed_selections = set()  # Track which _selections keys we've processed

        for attr_slug, attr_value in attribute_values.items():
            # Skip metadata keys (price/upcharge and selections are processed with their parent)
            if attr_slug.endswith("_price") or attr_slug.endswith("_upcharge") or attr_slug.endswith("_selections"):
                continue
            if attr_slug in skip_slugs:
                continue
            # Skip internal state fields (pending_ prefix) - not for display
            if attr_slug.startswith("pending_"):
                continue
            if attr_value is None or attr_value is False or attr_value == "" or attr_value == []:
                continue  # Skip empty/false values

            # Check if this is a multi-select attribute with _selections data
            selections = attribute_values.get(f"{attr_slug}_selections")
            if selections and isinstance(selections, list):
                processed_selections.add(f"{attr_slug}_selections")
                # Multi-select: create a modifier for each selection
                for sel in selections:
                    # Check for slug, flavor (for syrups), or type (for sweeteners)
                    sel_slug = sel.get("slug", "") or sel.get("flavor", "") or sel.get("type", "")
                    sel_display = sel.get("display_name") or sel_slug.replace("_", " ").title()
                    sel_price = sel.get("price", 0) or 0.0
                    sel_quantity = sel.get("quantity", 1) or 1
                    sel_qualifier = sel.get("qualifier")

                    # Try custom price lookup if price not set
                    if sel_price == 0 and price_lookup_fn and pricing:
                        sel_price = price_lookup_fn(attr_slug, sel_slug, pricing) or 0.0

                    # Build display with qualifier
                    if sel_qualifier:
                        sel_display = f"{sel_display} ({sel_qualifier})"

                    # Handle quantity
                    if sel_quantity > 1:
                        sel_display = f"{sel_quantity} {sel_display}"
                        sel_price = sel_price * sel_quantity

                    # Skip if display name is empty
                    if not sel_display:
                        continue

                    if sel_price > 0:
                        modifiers.append({"name": sel_display, "price": sel_price})
                        total_upcharges += sel_price
                    elif include_free_in_modifiers:
                        modifiers.append({"name": sel_display, "price": 0})
                    else:
                        free_details.append(sel_display)
                continue

            # Single-select or scalar attribute
            # Get associated price (stored as {attr_slug}_price or {attr_slug}_upcharge)
            price = attribute_values.get(f"{attr_slug}_price", 0) or 0.0
            if price == 0:
                # Also check for {attr_slug}_upcharge (legacy storage format)
                price = attribute_values.get(f"{attr_slug}_upcharge", 0) or 0.0

            # Try custom price lookup if price not stored
            if price == 0 and price_lookup_fn and pricing and isinstance(attr_value, str):
                price = price_lookup_fn(attr_slug, attr_value, pricing) or 0.0

            # Build display name
            if attr_value is True:
                # Boolean attribute (e.g., decaf, toasted) - keep lowercase
                display_name = attr_slug.replace("_", " ").lower()
            elif isinstance(attr_value, list):
                # List without _selections (legacy fallback) - add each item
                for val in attr_value:
                    val_display = str(val).replace("_", " ").title()
                    if include_free_in_modifiers:
                        modifiers.append({"name": val_display, "price": 0})
                    else:
                        free_details.append(val_display)
                continue
            else:
                # String attribute (e.g., size: "large", milk: "oat")
                display_name = str(attr_value).replace("_", " ").title()
                # Use pricing engine display name lookup if available
                if pricing:
                    if attr_slug == "size" and hasattr(pricing, 'lookup_size_display_name'):
                        display_name = pricing.lookup_size_display_name(attr_value) or display_name
                    elif attr_slug == "temperature" and hasattr(pricing, 'lookup_temperature_display_name'):
                        display_name = pricing.lookup_temperature_display_name(attr_value) or display_name

            # Skip if display name is empty
            if not display_name:
                continue

            # Add to modifiers (if priced) or free_details
            if price > 0:
                modifiers.append({"name": display_name, "price": price})
                total_upcharges += price
            elif include_free_in_modifiers:
                modifiers.append({"name": display_name, "price": 0})
            else:
                free_details.append(display_name)

        # Second pass: process orphan _selections keys that weren't processed above
        # (e.g., syrup_selections without a parent "syrup" key)
        for attr_slug, attr_value in attribute_values.items():
            if not attr_slug.endswith("_selections"):
                continue
            if attr_slug in processed_selections:
                continue  # Already processed with its parent
            if not isinstance(attr_value, list) or not attr_value:
                continue

            # Process this orphan selections list
            for sel in attr_value:
                # Check for slug, flavor (for syrups), or type (for sweeteners)
                sel_slug = sel.get("slug", "") or sel.get("flavor", "") or sel.get("type", "")
                sel_display = sel.get("display_name") or sel_slug.replace("_", " ").title()
                sel_price = sel.get("price", 0) or 0.0
                sel_quantity = sel.get("quantity", 1) or 1
                sel_qualifier = sel.get("qualifier")

                # Derive parent slug from selections key (e.g., "syrup_selections" -> "syrup")
                parent_slug = attr_slug[:-11]  # Remove "_selections" suffix

                # Try custom price lookup if price not set
                if sel_price == 0 and price_lookup_fn and pricing:
                    sel_price = price_lookup_fn(parent_slug, sel_slug, pricing) or 0.0

                # Build display with qualifier
                if sel_qualifier:
                    sel_display = f"{sel_display} ({sel_qualifier})"

                # Handle quantity
                if sel_quantity > 1:
                    sel_display = f"{sel_quantity} {sel_display}"
                    sel_price = sel_price * sel_quantity

                # Skip if display name is empty
                if not sel_display:
                    continue

                if sel_price > 0:
                    modifiers.append({"name": sel_display, "price": sel_price})
                    total_upcharges += sel_price
                elif include_free_in_modifiers:
                    modifiers.append({"name": sel_display, "price": 0})
                else:
                    free_details.append(sel_display)

        return total_upcharges


class MenuItemConverter(ItemConverter):
    """Converter for MenuItemTask (omelettes, sandwiches, etc.)."""

    @property
    def item_type(self) -> str:
        return "menu_item"

    def from_dict(self, item_dict: Dict[str, Any]) -> MenuItemTask:
        # Extract spread_price from modifiers if present
        spread_price = None
        item_modifiers = item_dict.get("modifiers") or []
        for mod in item_modifiers:
            if isinstance(mod, dict) and mod.get("name") == item_dict.get("spread"):
                spread_price = mod.get("price")
                break

        item_config = item_dict.get("item_config") or {}

        # Determine menu_item_type - map legacy "drink" to "sized_beverage"
        item_type = item_dict.get("item_type")
        menu_item_type = item_dict.get("menu_item_type") or item_config.get("menu_item_type")
        if not menu_item_type and item_type in ("drink", "coffee", "sized_beverage", "espresso"):
            menu_item_type = "sized_beverage"

        # Build attribute_values from various sources
        attribute_values = item_dict.get("attribute_values") or item_config.get("attribute_values") or {}

        # Restore beverage properties from item_config (legacy format)
        # Data-driven check: item type has size attribute (sized beverages)
        # with fallback to string comparison if database not available
        item_attrs = menu_cache.get_item_type_attributes(menu_item_type) if menu_item_type else {}
        if ("size" in item_attrs or menu_item_type == "sized_beverage") and item_config:
            # Restore size
            if item_config.get("size") and "size" not in attribute_values:
                attribute_values["size"] = item_config["size"]
            # Restore temperature/style
            if item_config.get("style") and "temperature" not in attribute_values:
                attribute_values["temperature"] = item_config["style"]
            # Restore decaf
            if item_config.get("decaf") and "decaf" not in attribute_values:
                attribute_values["decaf"] = item_config["decaf"]
            # Restore milk
            if item_config.get("milk") and "milk" not in attribute_values:
                attribute_values["milk"] = item_config["milk"]
            # Restore sweeteners
            if item_config.get("sweeteners") and "sweetener_selections" not in attribute_values:
                attribute_values["sweetener_selections"] = item_config["sweeteners"]

        # Also check top-level dict for size (common in legacy format)
        if item_dict.get("size") and "size" not in attribute_values:
            attribute_values["size"] = item_dict["size"]

        menu_item = MenuItemTask(
            menu_item_name=item_dict.get("menu_item_name") or "Unknown",
            menu_item_id=item_dict.get("menu_item_id"),
            menu_item_type=menu_item_type,
            modifications=item_dict.get("modifications") or [],
            removed_ingredients=item_config.get("removed_ingredients") or item_dict.get("removed_ingredients") or [],
            side_choice=item_dict.get("side_choice"),
            bagel_choice=item_dict.get("bagel_choice"),
            toasted=item_dict.get("toasted"),
            spread=item_dict.get("spread"),
            spread_price=spread_price,
            requires_side_choice=item_dict.get("requires_side_choice", False),
            quantity=item_dict.get("quantity", 1),
            special_instructions=item_dict.get("special_instructions") or item_dict.get("notes"),
            attribute_values=attribute_values,
            customization_offered=item_dict.get("customization_offered", False),
        )
        self._restore_common_fields(menu_item, item_dict)
        return menu_item

    def to_dict(
        self,
        item: ItemTask,
        pricing: "PricingEngine | None" = None,
    ) -> Dict[str, Any]:
        side_choice = getattr(item, 'side_choice', None)
        bagel_choice = getattr(item, 'bagel_choice', None)
        toasted = getattr(item, 'toasted', None)
        spread = getattr(item, 'spread', None)
        menu_item_name = item.menu_item_name
        menu_item_type = getattr(item, 'menu_item_type', None)
        removed_ingredients = getattr(item, 'removed_ingredients', []) or []

        # Get DB-driven attribute values early (needed for display_name)
        attribute_values = getattr(item, 'attribute_values', {}) or {}

        # Build display name with bagel choice and side choice
        # For beverages (espresso, coffee), use the base menu item name
        # All attributes (shots, decaf, milk, etc.) become modifier line items
        display_name = menu_item_name

        # Handle DB-driven bread attribute for deli_sandwich, etc.
        bread_attr = attribute_values.get("bread")
        if bread_attr:
            bread_display = bread_attr.replace("_", " ").title()
            display_name = f"{menu_item_name} on {bread_display}"
        elif side_choice == "fruit_salad":
            display_name = f"{display_name} with fruit salad"
        elif side_choice == "bagel":
            if bagel_choice:
                display_name = f"{display_name} with {bagel_choice} bagel"
            else:
                display_name = f"{display_name} with bagel"

        # Build side bagel config for omelettes
        side_bagel_config = None
        if side_choice == "bagel" and bagel_choice:
            side_bagel_parts = [bagel_choice, "bagel"]
            if toasted is True:
                side_bagel_parts.append("toasted")
            if spread and spread != "none":
                side_bagel_parts.append(f"with {spread}")
            side_bagel_config = {
                "bagel_type": bagel_choice,
                "toasted": toasted,
                "spread": spread,
                "description": " ".join(side_bagel_parts),
            }

        # Build modifiers list with prices
        modifiers = []
        if toasted is True and side_choice == "bagel":
            modifiers.append({"name": "Toasted", "price": 0})

        # Add spread to modifiers if set
        spread_price = getattr(item, 'spread_price', None)
        spread_type = getattr(item, 'spread_type', None) or attribute_values.get("spread_type")
        if spread and spread.lower() != "none":
            # Look up spread price from pricing engine if not already set
            if spread_price is None and pricing and hasattr(pricing, 'lookup_spread_price'):
                spread_price = pricing.lookup_spread_price(spread, spread_type) or 0
            spread_name = spread
            if spread_type and spread_type != "plain":
                spread_name = f"{spread_type} {spread}"
            modifiers.append({"name": spread_name, "price": spread_price or 0})

        item_modifications = getattr(item, 'modifications', []) or []
        for mod in item_modifications:
            modifiers.append({"name": mod, "price": 0})

        # Add sandwich_protein and extras for bagels (with prices from pricing engine)
        sandwich_protein = getattr(item, 'sandwich_protein', None)
        extras = getattr(item, 'extras', []) or []
        if sandwich_protein and pricing and hasattr(pricing, 'lookup_modifier_price'):
            protein_price = pricing.lookup_modifier_price(sandwich_protein) or 0
            modifiers.append({"name": sandwich_protein, "price": protein_price})
        for extra in extras:
            if pricing and hasattr(pricing, 'lookup_modifier_price'):
                extra_price = pricing.lookup_modifier_price(extra) or 0
                modifiers.append({"name": extra, "price": extra_price})

        # Convert DB-driven attribute_values to modifiers for cart display
        # Use the shared generic processing method
        # Pass include_free=True so all customizations appear in cart (with price=0)
        self._process_attribute_values_to_modifiers(
            attribute_values=attribute_values,
            modifiers=modifiers,
            free_details=[],  # Not used when include_free=True
            pricing=pricing,
            skip_slugs={"bread"},  # bread is in display_name
            include_free_in_modifiers=True,  # Add free items to modifiers with price=0
        )

        customization_offered = getattr(item, 'customization_offered', False)

        # Get base_price from pricing engine if available, or from item
        base_price = getattr(item, 'base_price', None)
        if base_price is None and pricing:
            # For bagels (items with bread attribute), look up base price from pricing engine
            # with fallback to string comparison if database not available
            item_attrs = menu_cache.get_item_type_attributes(menu_item_type) if menu_item_type else {}
            if "bread" in item_attrs or menu_item_type == "bagel":
                base_price = pricing.get_bagel_base_price()
            elif hasattr(pricing, 'lookup_menu_item_price') and menu_item_name:
                base_price = pricing.lookup_menu_item_price(menu_item_name)
        if base_price is None:
            base_price = item.unit_price or 0.0

        # For bagels, include bagel-specific fields in item_config for backwards compatibility
        bagel_type = attribute_values.get("bagel_type")
        bagel_type_upcharge = attribute_values.get("bagel_type_upcharge", 0.0) or 0.0
        spread_type = attribute_values.get("spread_type")
        scooped = attribute_values.get("scooped")
        sandwich_protein = getattr(item, 'sandwich_protein', None)
        extras = getattr(item, 'extras', []) or []

        result = self._build_common_dict_fields(item)
        # Use the actual menu_item_type for backwards compatibility
        # (bagels should output item_type="bagel", not "menu_item")
        if menu_item_type:
            result["item_type"] = menu_item_type
        result.update({
            "menu_item_name": menu_item_name,
            "display_name": display_name,
            "menu_item_id": getattr(item, 'menu_item_id', None),
            "menu_item_type": menu_item_type,
            "modifications": getattr(item, 'modifications', []),
            "modifiers": modifiers,
            "free_details": [],
            "base_price": base_price,
            "side_choice": side_choice,
            "bagel_choice": bagel_choice,
            "toasted": toasted if toasted is not None else attribute_values.get("toasted"),
            "spread": spread,
            # Bagel-specific fields at top level for backwards compatibility
            "bagel_type": bagel_type,
            "extras": extras,
            "side_bagel_config": side_bagel_config,
            "requires_side_choice": getattr(item, 'requires_side_choice', False),
            "removed_ingredients": removed_ingredients,
            # DB-driven attribute values
            "attribute_values": attribute_values,
            "customization_offered": customization_offered,
            # item_config with both generic and bagel-specific fields for backwards compatibility
            "item_config": {
                "menu_item_type": menu_item_type,
                "modifiers": modifiers,
                "attribute_values": attribute_values,
                "base_price": base_price,
                # Bagel-specific fields (for backwards compatibility)
                "bagel_type": bagel_type,
                "bagel_type_upcharge": bagel_type_upcharge,
                "spread": spread,
                "spread_type": spread_type,
                "toasted": toasted if toasted is not None else attribute_values.get("toasted"),
                "scooped": scooped,
                "sandwich_protein": sandwich_protein,
                "extras": extras,
            },
        })
        return result


class BagelConverter(ItemConverter):
    """Converter for bagel items (MenuItemTask with menu_item_type='bagel')."""

    @property
    def item_type(self) -> str:
        return "bagel"

    def from_dict(self, item_dict: Dict[str, Any]) -> MenuItemTask:
        """Convert dict to MenuItemTask with menu_item_type='bagel'."""
        bagel = MenuItemTask(
            menu_item_name="Bagel",
            menu_item_type="bagel",
            quantity=item_dict.get("quantity", 1),
            toasted=item_dict.get("toasted"),
            spread=item_dict.get("spread"),
            special_instructions=item_dict.get("special_instructions") or item_dict.get("notes"),
        )

        # Set bagel-specific fields via property setters (stored in attribute_values)
        if item_dict.get("bagel_type"):
            bagel.bagel_type = item_dict.get("bagel_type")
        if item_dict.get("bagel_type_upcharge"):
            bagel.bagel_type_upcharge = item_dict.get("bagel_type_upcharge", 0.0)
        if item_dict.get("scooped") is not None:
            bagel.scooped = item_dict.get("scooped")
        if item_dict.get("spread_type"):
            bagel.spread_type = item_dict.get("spread_type")
        if item_dict.get("sandwich_protein"):
            bagel.sandwich_protein = item_dict.get("sandwich_protein")
        if item_dict.get("extras"):
            bagel.extras = item_dict.get("extras") or []
        if item_dict.get("needs_cheese_clarification"):
            bagel.needs_cheese_clarification = item_dict.get("needs_cheese_clarification", False)

        self._restore_common_fields(bagel, item_dict)
        return bagel

    def to_dict(
        self,
        item: ItemTask,
        pricing: "PricingEngine | None" = None,
    ) -> Dict[str, Any]:
        bagel_type = getattr(item, 'bagel_type', None)
        bagel_type_upcharge = getattr(item, 'bagel_type_upcharge', 0.0) or 0.0
        spread = getattr(item, 'spread', None)
        spread_type = getattr(item, 'spread_type', None)
        toasted = getattr(item, 'toasted', None)
        scooped = getattr(item, 'scooped', None)
        sandwich_protein = getattr(item, 'sandwich_protein', None)
        extras = getattr(item, 'extras', []) or []

        display_name = "Bagel"

        # Build modifiers list with prices
        modifiers = []

        if bagel_type:
            modifiers.append({
                "name": bagel_type.title(),
                "price": bagel_type_upcharge,
            })

        if toasted:
            modifiers.append({"name": "Toasted", "price": 0})

        if scooped:
            modifiers.append({"name": "Scooped", "price": 0})

        if sandwich_protein:
            if not pricing:
                raise ValueError(
                    "Pricing engine required for protein modifier price. "
                    "Ensure pricing parameter is passed to order_task_to_dict."
                )
            protein_price = pricing.lookup_modifier_price(sandwich_protein)
            modifiers.append({"name": sandwich_protein, "price": protein_price})

        for extra in extras:
            if not pricing:
                raise ValueError(
                    "Pricing engine required for modifier prices. "
                    "Ensure pricing parameter is passed to order_task_to_dict."
                )
            extra_price = pricing.lookup_modifier_price(extra)
            modifiers.append({"name": extra, "price": extra_price})

        if spread and spread.lower() != "none":
            spread_name = spread
            if spread_type and spread_type != "plain":
                spread_name = f"{spread_type} {spread}"
            if not pricing:
                raise ValueError(
                    "Pricing engine required for spread price. "
                    "Ensure pricing parameter is passed to order_task_to_dict."
                )
            spread_price = pricing.lookup_spread_price(spread, spread_type)
            modifiers.append({"name": spread_name, "price": spread_price})

        if pricing:
            base_price = pricing.get_bagel_base_price()
        else:
            raise ValueError(
                "Pricing engine required to get bagel base price. "
                "Ensure pricing parameter is passed to order_task_to_dict."
            )

        result = self._build_common_dict_fields(item)
        result.update({
            "display_name": display_name,
            "menu_item_name": display_name,
            "bagel_type": bagel_type,
            "bagel_type_upcharge": bagel_type_upcharge,
            "spread": spread,
            "spread_type": spread_type,
            "toasted": toasted,
            "scooped": scooped,
            "sandwich_protein": sandwich_protein,
            "extras": extras,
            "needs_cheese_clarification": getattr(item, 'needs_cheese_clarification', False),
            "base_price": base_price,
            "modifiers": modifiers,
            "free_details": [],
            "item_config": {
                "bagel_type": bagel_type,
                "bagel_type_upcharge": bagel_type_upcharge,
                "spread": spread,
                "spread_type": spread_type,
                "toasted": toasted,
                "scooped": scooped,
                "sandwich_protein": sandwich_protein,
                "extras": extras,
                "modifiers": modifiers,
                "base_price": base_price,
            },
        })
        return result


class SandwichConverter(ItemConverter):
    """Converter for legacy sandwich format (treated as bagel)."""

    @property
    def item_type(self) -> str:
        return "sandwich"

    def from_dict(self, item_dict: Dict[str, Any]) -> MenuItemTask:
        """Convert dict to MenuItemTask with menu_item_type='bagel'."""
        bagel_type = item_dict.get("bread") or item_dict.get("menu_item_name") or "unknown"
        bagel = MenuItemTask(
            menu_item_name="Bagel",
            menu_item_type="bagel",
            quantity=item_dict.get("quantity", 1),
            toasted=item_dict.get("toasted"),
            spread=item_dict.get("cheese"),
            special_instructions=item_dict.get("special_instructions") or item_dict.get("notes"),
        )

        # Set bagel-specific fields via property setters
        bagel.bagel_type = bagel_type
        if item_dict.get("toppings"):
            bagel.extras = item_dict.get("toppings") or []

        self._restore_common_fields(bagel, item_dict)
        if bagel.bagel_type and bagel.toasted is not None:
            bagel.mark_complete()
        return bagel

    def to_dict(
        self,
        item: ItemTask,
        pricing: "PricingEngine | None" = None,
    ) -> Dict[str, Any]:
        # Sandwich is converted as bagel on output
        return BagelConverter().to_dict(item, pricing)




# -----------------------------------------------------------------------------
# Unified Converter
# -----------------------------------------------------------------------------

class UnifiedItemConverter(ItemConverter):
    """
    Unified converter that dispatches to specialized converters based on item type.

    This provides a single entry point for item conversion while maintaining
    specialized logic for different item types. Use this class when you want
    automatic dispatch based on item type.
    """

    @property
    def item_type(self) -> str:
        return "unified"

    def from_dict(self, item_dict: Dict[str, Any]) -> ItemTask:
        """Convert dict to appropriate ItemTask based on item_type."""
        item_type = item_dict.get("item_type") or item_dict.get("menu_item_type") or "menu_item"

        # Route to specialized converter using data-driven attribute checks
        # with fallback to string comparison if database not available
        item_attrs = menu_cache.get_item_type_attributes(item_type)
        if "bread" in item_attrs or item_type == "bagel":
            # Items with bread attribute (bagels) use BagelConverter
            return BagelConverter().from_dict(item_dict)
        elif item_type == "sandwich":
            return SandwichConverter().from_dict(item_dict)
        else:
            # All other types (menu_item, coffee, drink, sized_beverage, espresso)
            # use MenuItemConverter
            return MenuItemConverter().from_dict(item_dict)

    def to_dict(
        self,
        item: ItemTask,
        pricing: "PricingEngine | None" = None,
    ) -> Dict[str, Any]:
        """Convert ItemTask to dict based on its type."""
        # Use data-driven attribute check for routing
        # with fallback to string comparison if database not available
        menu_item_type = getattr(item, 'menu_item_type', None)
        if menu_item_type:
            item_attrs = menu_cache.get_item_type_attributes(menu_item_type)
            if "bread" in item_attrs or menu_item_type == "bagel":
                # Items with bread attribute (bagels) use BagelConverter
                return BagelConverter().to_dict(item, pricing)
        # All other types (menu_item, sized_beverage, espresso, etc.)
        # use MenuItemConverter
        return MenuItemConverter().to_dict(item, pricing)


# -----------------------------------------------------------------------------
# Converter Registry
# -----------------------------------------------------------------------------

class ItemConverterRegistry:
    """
    Registry for item type converters.

    Provides centralized lookup of converters by item_type string.
    """

    _converters: Dict[str, ItemConverter] = {}

    @classmethod
    def register(cls, converter: ItemConverter) -> None:
        """Register a converter for its item type."""
        cls._converters[converter.item_type] = converter

    @classmethod
    def get(cls, item_type: str) -> ItemConverter | None:
        """Get converter for an item type, or None if not found."""
        return cls._converters.get(item_type)

    @classmethod
    def get_for_item(cls, item: ItemTask) -> ItemConverter | None:
        """
        Get converter for an ItemTask based on its type.

        For MenuItemTask, routes based on menu_item_type using data-driven attribute checks:
        - Items with bread attribute (bagels) -> BagelConverter
        - otherwise -> MenuItemConverter (handles all types including sized_beverage)
        """
        # Check if it's a MenuItemTask with specific menu_item_type
        if isinstance(item, MenuItemTask):
            menu_item_type = item.menu_item_type
            if menu_item_type:
                # Data-driven check with string fallback
                item_attrs = menu_cache.get_item_type_attributes(menu_item_type)
                if "bread" in item_attrs or menu_item_type == "bagel":
                    return cls._converters.get("bagel")
            # All other MenuItemTask types use MenuItemConverter
            return cls._converters.get("menu_item")

        return cls._converters.get(item.item_type)

    @classmethod
    def all_types(cls) -> list[str]:
        """Get all registered item types."""
        return list(cls._converters.keys())


# Register all converters
ItemConverterRegistry.register(MenuItemConverter())
ItemConverterRegistry.register(BagelConverter())
ItemConverterRegistry.register(SandwichConverter())
ItemConverterRegistry.register(UnifiedItemConverter())

# Other item types use MenuItemConverter (unified data-driven approach)
# Note: BagelConverter is kept separate for proper bagel item_type preservation
ItemConverterRegistry._converters["coffee"] = ItemConverterRegistry._converters["menu_item"]
ItemConverterRegistry._converters["drink"] = ItemConverterRegistry._converters["menu_item"]
ItemConverterRegistry._converters["sized_beverage"] = ItemConverterRegistry._converters["menu_item"]
ItemConverterRegistry._converters["espresso"] = ItemConverterRegistry._converters["menu_item"]

# For backwards compatibility, treat signature_item as menu_item
ItemConverterRegistry._converters["signature_item"] = ItemConverterRegistry._converters["menu_item"]
ItemConverterRegistry._converters["speed_menu_bagel"] = ItemConverterRegistry._converters["menu_item"]
