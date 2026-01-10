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
    BagelItemTask,
    CoffeeItemTask,
    MenuItemTask,
)

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
        menu_item = MenuItemTask(
            menu_item_name=item_dict.get("menu_item_name") or "Unknown",
            menu_item_id=item_dict.get("menu_item_id"),
            menu_item_type=item_dict.get("menu_item_type"),
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
            # DB-driven attribute values for deli sandwiches, etc.
            attribute_values=item_dict.get("attribute_values") or item_config.get("attribute_values") or {},
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

        # Add spread to modifiers if set (show even if price is 0 or not set)
        spread_price = getattr(item, 'spread_price', None) or 0
        if spread and spread != "none":
            modifiers.append({"name": spread, "price": spread_price})

        item_modifications = getattr(item, 'modifications', []) or []
        for mod in item_modifications:
            modifiers.append({"name": mod, "price": 0})

        # Convert DB-driven attribute_values to modifiers for cart display
        # (attribute_values was loaded earlier for display_name)
        for attr_slug, attr_value in attribute_values.items():
            # Skip fields that shouldn't be modifiers
            if attr_slug in ("bread",) or attr_slug.endswith("_price") or attr_slug.endswith("_selections"):
                continue  # bread is in display_name, price and selections fields are metadata
            if attr_value is None or attr_value is False:
                continue  # Skip empty/false values

            # Check if this is a multi-select attribute with _selections data
            selections = attribute_values.get(f"{attr_slug}_selections")
            if selections and isinstance(selections, list):
                # Multi-select: create a modifier for each selection, respecting quantity and qualifier
                for sel in selections:
                    sel_display = sel.get("display_name") or sel.get("slug", "").replace("_", " ").title()
                    sel_price = sel.get("price", 0) or 0
                    sel_quantity = sel.get("quantity", 1) or 1
                    sel_qualifier = sel.get("qualifier")

                    # Include qualifier (extra, light, on the side, etc.) in display
                    if sel_qualifier:
                        sel_display = f"{sel_display} ({sel_qualifier})"

                    # Show quantity in display name and multiply price
                    if sel_quantity > 1:
                        sel_display = f"{sel_display} (x{sel_quantity})"
                        sel_price = sel_price * sel_quantity

                    modifiers.append({"name": sel_display, "price": sel_price})
                continue

            # Get associated price if any (for single-select)
            price = attribute_values.get(f"{attr_slug}_price", 0) or 0

            if attr_value is True:
                # Boolean attribute (e.g., toasted, scooped)
                display_name_mod = attr_slug.replace("_", " ").title()
                modifiers.append({"name": display_name_mod, "price": price})
            elif isinstance(attr_value, list):
                # List attribute without _selections data (fallback)
                for val in attr_value:
                    value_display = str(val).replace("_", " ").title()
                    modifiers.append({"name": value_display, "price": 0})
            else:
                # String attribute (e.g., extra_protein: "turkey_bacon")
                value_display = str(attr_value).replace("_", " ").title()
                modifiers.append({"name": value_display, "price": price})

        customization_offered = getattr(item, 'customization_offered', False)

        result = self._build_common_dict_fields(item)
        result.update({
            "menu_item_name": menu_item_name,
            "display_name": display_name,
            "menu_item_id": getattr(item, 'menu_item_id', None),
            "menu_item_type": menu_item_type,
            "modifications": getattr(item, 'modifications', []),
            "modifiers": modifiers,
            "free_details": [],
            "side_choice": side_choice,
            "bagel_choice": bagel_choice,
            "toasted": toasted,
            "spread": spread,
            "side_bagel_config": side_bagel_config,
            "requires_side_choice": getattr(item, 'requires_side_choice', False),
            "removed_ingredients": removed_ingredients,
            # DB-driven attribute values for deli sandwiches, etc.
            "attribute_values": attribute_values,
            "customization_offered": customization_offered,
            "item_config": {
                "menu_item_type": menu_item_type,
                "side_choice": side_choice,
                "bagel_choice": bagel_choice,
                "toasted": toasted,
                "spread": spread,
                "modifications": getattr(item, 'modifications', []),
                "removed_ingredients": removed_ingredients,
                "modifiers": modifiers,
                "attribute_values": attribute_values,
            },
        })
        return result


class BagelConverter(ItemConverter):
    """Converter for BagelItemTask."""

    @property
    def item_type(self) -> str:
        return "bagel"

    def from_dict(self, item_dict: Dict[str, Any]) -> BagelItemTask:
        bagel = BagelItemTask(
            bagel_type=item_dict.get("bagel_type"),
            quantity=item_dict.get("quantity", 1),
            toasted=item_dict.get("toasted"),
            scooped=item_dict.get("scooped"),
            spread=item_dict.get("spread"),
            spread_type=item_dict.get("spread_type"),
            sandwich_protein=item_dict.get("sandwich_protein"),
            extras=item_dict.get("extras") or [],
            special_instructions=item_dict.get("special_instructions") or item_dict.get("notes"),
            needs_cheese_clarification=item_dict.get("needs_cheese_clarification", False),
        )
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

    def from_dict(self, item_dict: Dict[str, Any]) -> BagelItemTask:
        bagel = BagelItemTask(
            bagel_type=item_dict.get("bread") or item_dict.get("menu_item_name") or "unknown",
            quantity=item_dict.get("quantity", 1),
            toasted=item_dict.get("toasted"),
            spread=item_dict.get("cheese"),
            extras=item_dict.get("toppings") or [],
            special_instructions=item_dict.get("special_instructions") or item_dict.get("notes"),
        )
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


class CoffeeConverter(ItemConverter):
    """Converter for CoffeeItemTask."""

    @property
    def item_type(self) -> str:
        return "coffee"

    @property
    def output_item_type(self) -> str:
        """The item_type to use in dict output (for backwards compatibility)."""
        return "drink"

    def from_dict(self, item_dict: Dict[str, Any]) -> CoffeeItemTask:
        item_config = item_dict.get("item_config") or {}

        # Determine iced value from style
        style = item_config.get("style")
        if style == "iced":
            iced_value = True
        elif style == "hot":
            iced_value = False
        else:
            iced_value = None

        # Handle sweeteners
        sweeteners = item_config.get("sweeteners", [])
        if not sweeteners and item_config.get("sweetener"):
            sweeteners = [{
                "type": item_config["sweetener"],
                "quantity": item_config.get("sweetener_quantity", 1)
            }]

        # Handle flavor syrups
        flavor_syrups = item_config.get("flavor_syrups", [])
        if not flavor_syrups and item_config.get("flavor_syrup"):
            flavor_syrups = [{
                "flavor": item_config["flavor_syrup"],
                "quantity": item_config.get("syrup_quantity", 1)
            }]

        coffee = CoffeeItemTask(
            drink_type=item_dict.get("menu_item_name") or "coffee",
            size=item_dict.get("size") or item_config.get("size"),
            milk=item_config.get("milk"),
            cream_level=item_config.get("cream_level"),
            sweeteners=sweeteners,
            flavor_syrups=flavor_syrups,
            iced=iced_value,
            decaf=item_config.get("decaf"),
            size_upcharge=item_config.get("size_upcharge", 0.0),
            milk_upcharge=item_config.get("milk_upcharge", 0.0),
            syrup_upcharge=item_config.get("syrup_upcharge", 0.0),
            iced_upcharge=item_config.get("iced_upcharge", 0.0),
            wants_syrup=item_config.get("wants_syrup", False),
            pending_syrup_quantity=item_config.get("pending_syrup_quantity", 1),
            special_instructions=item_dict.get("special_instructions") or item_dict.get("notes"),
        )
        self._restore_common_fields(coffee, item_dict)
        if coffee.drink_type and coffee.iced is not None:
            coffee.mark_complete()
        return coffee

    def to_dict(
        self,
        item: ItemTask,
        pricing: "PricingEngine | None" = None,
    ) -> Dict[str, Any]:
        drink_type = getattr(item, 'drink_type', 'coffee')
        size = getattr(item, 'size', None)
        milk = getattr(item, 'milk', None)
        flavor_syrups = getattr(item, 'flavor_syrups', []) or []
        sweeteners = getattr(item, 'sweeteners', []) or []
        iced = getattr(item, 'iced', None)
        decaf = getattr(item, 'decaf', None)
        cream_level = getattr(item, 'cream_level', None)

        size_upcharge = getattr(item, 'size_upcharge', 0.0) or 0.0
        milk_upcharge = getattr(item, 'milk_upcharge', 0.0) or 0.0
        syrup_upcharge = getattr(item, 'syrup_upcharge', 0.0) or 0.0
        iced_upcharge = getattr(item, 'iced_upcharge', 0.0) or 0.0

        modifiers = []
        free_details = []

        if size:
            # Get display name from database via pricing engine
            size_label = pricing.lookup_size_display_name(size) if pricing else size
            if size_upcharge > 0:
                modifiers.append({"name": size_label, "price": size_upcharge})
            else:
                free_details.append(size_label)

        if iced is True:
            # Get display name from database via pricing engine
            iced_label = pricing.lookup_temperature_display_name(True) if pricing else "iced"
            if iced_upcharge > 0:
                modifiers.append({"name": iced_label, "price": iced_upcharge})
            else:
                free_details.append(iced_label)
        elif iced is False:
            hot_label = pricing.lookup_temperature_display_name(False) if pricing else "hot"
            free_details.append(hot_label)

        if decaf is True:
            free_details.append("decaf")

        if milk and milk.lower() not in ("none", "black"):
            if milk_upcharge > 0:
                modifiers.append({"name": f"{milk} milk", "price": milk_upcharge})
            else:
                free_details.append(f"{milk} milk")
        elif milk and milk.lower() in ("none", "black"):
            free_details.append("black")

        for syrup_entry in flavor_syrups:
            flavor = syrup_entry.get("flavor", "")
            qty = syrup_entry.get("quantity", 1)
            # Use individual syrup price stored by pricing engine, fall back to total upcharge
            entry_price = syrup_entry.get("price", 0.0)
            if flavor:
                syrup_name = f"{qty} {flavor} syrups" if qty > 1 else f"{flavor} syrup"
                if entry_price > 0:
                    modifiers.append({"name": syrup_name, "price": entry_price})
                else:
                    free_details.append(syrup_name)

        for sweetener_entry in sweeteners:
            s_type = sweetener_entry.get("type", "")
            s_qty = sweetener_entry.get("quantity", 1)
            if s_type:
                if s_qty > 1:
                    free_details.append(f"{s_qty} {s_type}s")
                else:
                    free_details.append(s_type)

        if cream_level:
            free_details.append(cream_level)

        total_price = item.unit_price or 0
        base_price = total_price - size_upcharge - milk_upcharge - syrup_upcharge - iced_upcharge

        result = self._build_common_dict_fields(item)
        result["quantity"] = 1  # Coffee is always quantity 1
        result["line_total"] = item.unit_price if item.unit_price else 0
        result.update({
            "menu_item_name": drink_type,
            "size": size,
            "base_price": base_price,
            "modifiers": modifiers,
            "free_details": free_details,
            "item_config": {
                "size": size,
                "milk": milk,
                "cream_level": cream_level,
                "sweeteners": sweeteners,
                "flavor_syrups": flavor_syrups,
                "decaf": decaf,
                "style": "iced" if iced is True else ("hot" if iced is False else None),
                "size_upcharge": size_upcharge,
                "milk_upcharge": milk_upcharge,
                "syrup_upcharge": syrup_upcharge,
                "iced_upcharge": iced_upcharge,
                "wants_syrup": getattr(item, 'wants_syrup', False),
                "pending_syrup_quantity": getattr(item, 'pending_syrup_quantity', 1),
                "modifiers": modifiers,
                "free_details": free_details,
                "base_price": base_price,
            },
        })
        return result


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
        """Get converter for an ItemTask based on its item_type attribute."""
        return cls._converters.get(item.item_type)

    @classmethod
    def all_types(cls) -> list[str]:
        """Get all registered item types."""
        return list(cls._converters.keys())


# Register all converters
ItemConverterRegistry.register(MenuItemConverter())
ItemConverterRegistry.register(BagelConverter())
ItemConverterRegistry.register(SandwichConverter())
ItemConverterRegistry.register(CoffeeConverter())

# Register CoffeeConverter under "drink" as well (for dict input compatibility)
ItemConverterRegistry._converters["drink"] = ItemConverterRegistry._converters["coffee"]

# For backwards compatibility, treat signature_item as menu_item
# (signature items are now MenuItemTask with is_signature=True)
ItemConverterRegistry._converters["signature_item"] = ItemConverterRegistry._converters["menu_item"]
ItemConverterRegistry._converters["speed_menu_bagel"] = ItemConverterRegistry._converters["menu_item"]

# Espresso now uses MenuItemConverter (data-driven via MenuItemTask)
ItemConverterRegistry._converters["espresso"] = ItemConverterRegistry._converters["menu_item"]
