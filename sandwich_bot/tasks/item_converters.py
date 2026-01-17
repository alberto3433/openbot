"""
Item Converters for Adapter Layer.

This module provides conversion between dict-based item representations
and ItemTask objects.

The UnifiedItemConverter handles all item types using a data-driven approach
based on database configuration. All item type slugs (bagel, coffee, sandwich,
sized_beverage, etc.) are aliases that map to the single UnifiedItemConverter.
"""

import logging
from typing import Any, Dict, TYPE_CHECKING

from .models import (
    TaskStatus,
    ItemTask,
    MenuItemTask,
    get_modifier_name,
)
from sandwich_bot.menu_data_cache import menu_cache

logger = logging.getLogger(__name__)


class UnifiedItemConverter:
    """
    Unified data-driven converter for all item types.

    This is the main converter that handles conversion between dict-based
    item representations and MenuItemTask objects. All item types use this
    single converter with data-driven behavior based on DB configuration.
    """

    @property
    def item_type(self) -> str:
        """The item type string this converter handles."""
        return "menu_item"

    def _restore_common_fields(self, item: ItemTask, item_dict: Dict[str, Any]) -> None:
        """Restore common fields shared by all item types."""
        if item_dict.get("id"):
            item.id = item_dict["id"]
        if item_dict.get("status"):
            item.status = TaskStatus(item_dict["status"])
        if item_dict.get("unit_price"):
            item.unit_price = item_dict["unit_price"]

    def _build_common_dict_fields(self, item: ItemTask) -> Dict[str, Any]:
        """Build common dict fields shared by all item types."""
        return {
            "item_type": self.item_type,
            "id": item.id,
            "status": item.status.value,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "line_total": (item.unit_price or 0) * item.quantity,
            "special_instructions": getattr(item, 'special_instructions', None),
        }

    def _process_selection_item(
        self,
        sel: dict,
        attr_slug: str,
        modifiers: list,
        free_details: list,
        pricing,
        price_lookup_fn,
        include_free_in_modifiers: bool,
    ) -> float:
        """Process a single selection item and return its price contribution."""
        sel_slug = get_modifier_name(sel)
        sel_display = sel.get("display_name") or sel_slug.replace("_", " ").title()
        sel_price = sel.get("price", 0) or 0.0
        sel_quantity = sel.get("quantity", 1) or 1

        # Try custom price lookup if price not set
        if sel_price == 0 and price_lookup_fn and pricing:
            sel_price = price_lookup_fn(attr_slug, sel_slug, pricing) or 0.0

        # Build display with qualifier
        if sel.get("qualifier"):
            sel_display = f"{sel_display} ({sel['qualifier']})"

        # Handle quantity
        if sel_quantity > 1:
            sel_display = f"{sel_quantity} {sel_display}"
            sel_price = sel_price * sel_quantity

        if not sel_display:
            return 0.0

        if sel_price > 0:
            modifiers.append({"name": sel_display, "price": sel_price})
            return sel_price
        elif include_free_in_modifiers:
            modifiers.append({"name": sel_display, "price": 0})
        else:
            free_details.append(sel_display)
        return 0.0

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
        """Process attribute_values into modifiers/free_details lists."""
        skip_slugs = skip_slugs or set()
        total_upcharges = 0.0
        processed_selections = set()

        for attr_slug, attr_value in attribute_values.items():
            # Skip metadata and internal keys
            if (attr_slug.endswith(("_price", "_upcharge", "_selections")) or
                attr_slug.startswith("pending_") or attr_slug in skip_slugs):
                continue
            if attr_value is None or attr_value is False or attr_value == "" or attr_value == []:
                continue

            # Handle multi-select with _selections data
            selections = attribute_values.get(f"{attr_slug}_selections")
            if selections and isinstance(selections, list):
                processed_selections.add(f"{attr_slug}_selections")
                for sel in selections:
                    total_upcharges += self._process_selection_item(
                        sel, attr_slug, modifiers, free_details,
                        pricing, price_lookup_fn, include_free_in_modifiers
                    )
                continue

            # Get price from stored values
            price = attribute_values.get(f"{attr_slug}_price", 0) or attribute_values.get(f"{attr_slug}_upcharge", 0) or 0.0

            # Try custom price lookup
            if price == 0 and price_lookup_fn and pricing and isinstance(attr_value, str):
                price = price_lookup_fn(attr_slug, attr_value, pricing) or 0.0

            # Build display name
            if attr_value is True:
                display_name = attr_slug.replace("_", " ").lower()
            elif isinstance(attr_value, list):
                for val in attr_value:
                    val_display = str(val).replace("_", " ").title()
                    if include_free_in_modifiers:
                        modifiers.append({"name": val_display, "price": 0})
                    else:
                        free_details.append(val_display)
                continue
            else:
                display_name = str(attr_value).replace("_", " ").title()

            if not display_name:
                continue

            if price > 0:
                modifiers.append({"name": display_name, "price": price})
                total_upcharges += price
            elif include_free_in_modifiers:
                modifiers.append({"name": display_name, "price": 0})
            else:
                free_details.append(display_name)

        # Process orphan _selections keys
        for attr_slug, attr_value in attribute_values.items():
            if not attr_slug.endswith("_selections") or attr_slug in processed_selections:
                continue
            if not isinstance(attr_value, list) or not attr_value:
                continue
            parent_slug = attr_slug[:-11]  # e.g., "bread_selections" -> "bread"
            # Skip if parent was in skip_slugs (prevents duplicates when parent is manually handled)
            if parent_slug in skip_slugs:
                continue
            for sel in attr_value:
                total_upcharges += self._process_selection_item(
                    sel, parent_slug, modifiers, free_details,
                    pricing, price_lookup_fn, include_free_in_modifiers
                )

        return total_upcharges

    def from_dict(self, item_dict: Dict[str, Any]) -> MenuItemTask:
        """Convert dict to MenuItemTask using data-driven attribute handling."""
        item_config = item_dict.get("item_config") or {}

        # Determine menu_item_type (data-driven via alias resolution)
        menu_item_type = (
            item_dict.get("menu_item_type")
            or item_config.get("menu_item_type")
            or item_dict.get("item_type")
        )

        # Resolve item type aliases from database (e.g., "drink" -> "sized_beverage")
        if menu_item_type:
            menu_item_type = menu_cache.resolve_item_type_slug(menu_item_type)

        # Build attribute_values from various sources (data-driven)
        attribute_values = dict(item_dict.get("attribute_values") or item_config.get("attribute_values") or {})

        # Get DB-defined attributes for this item type
        item_attrs = menu_cache.get_item_type_attributes(menu_item_type) if menu_item_type else {}

        # Data-driven: restore any top-level fields that match DB-defined attributes
        for attr_slug in item_attrs.keys():
            if attr_slug not in attribute_values:
                # Check top-level dict
                if attr_slug in item_dict and item_dict[attr_slug] is not None:
                    attribute_values[attr_slug] = item_dict[attr_slug]
                # Check item_config
                elif attr_slug in item_config and item_config[attr_slug] is not None:
                    attribute_values[attr_slug] = item_config[attr_slug]
            # Also check for {attr_slug}_price and {attr_slug}_upcharge companion fields
            for suffix in ("_price", "_upcharge"):
                price_key = f"{attr_slug}{suffix}"
                if price_key not in attribute_values:
                    if price_key in item_dict and item_dict[price_key] is not None:
                        attribute_values[price_key] = item_dict[price_key]
                    elif price_key in item_config and item_config[price_key] is not None:
                        attribute_values[price_key] = item_config[price_key]

        # Data-driven: restore any additional fields from item_dict/item_config
        # that aren't already in attribute_values (no hardcoded field list)
        structural_keys = {
            "id", "status", "quantity", "unit_price", "item_type", "menu_item_type",
            "menu_item_name", "menu_item_id", "modifications", "removed_ingredients",
            "special_instructions", "notes", "modifiers", "free_details", "base_price",
            "line_total", "item_config", "attribute_values", "customization_offered",
            "display_name", "needs_cheese_clarification",
        }
        for source in (item_dict, item_config):
            for key, value in source.items():
                if key in attribute_values or key in structural_keys:
                    continue
                # Skip metadata suffix keys (handled with their parent)
                if key.endswith(("_price", "_upcharge", "_selections")):
                    continue
                if value is not None:
                    attribute_values[key] = value

        # Extract prices from modifiers for any matching attribute value
        item_modifiers = item_dict.get("modifiers") or []
        for mod in item_modifiers:
            if not isinstance(mod, dict) or not mod.get("name") or not mod.get("price"):
                continue
            mod_name = mod["name"]
            # Check if this modifier matches any attribute value that needs a price
            for attr_slug, attr_val in list(attribute_values.items()):
                if attr_val == mod_name and f"{attr_slug}_price" not in attribute_values:
                    attribute_values[f"{attr_slug}_price"] = mod["price"]

        # Restore modifiers from item_config or attribute_values
        stored_modifiers = []
        # Check for modifiers in item_config (serialized unified modifiers)
        if item_config.get("item_modifiers"):
            stored_modifiers = item_config["item_modifiers"]
        # Also check attribute_values for legacy milk_sweetener_syrup_selections
        elif attribute_values.get("milk_sweetener_syrup_selections"):
            stored_modifiers = attribute_values.get("milk_sweetener_syrup_selections", [])

        menu_item = MenuItemTask(
            menu_item_name=item_dict.get("menu_item_name") or "Unknown",
            menu_item_id=item_dict.get("menu_item_id"),
            menu_item_type=menu_item_type,
            modifications=item_dict.get("modifications") or [],
            removed_ingredients=item_config.get("removed_ingredients") or item_dict.get("removed_ingredients") or [],
            quantity=item_dict.get("quantity", 1),
            special_instructions=item_dict.get("special_instructions") or item_dict.get("notes"),
            attribute_values=attribute_values,
            modifiers=stored_modifiers,
            customization_offered=item_dict.get("customization_offered", False),
        )
        self._restore_common_fields(menu_item, item_dict)
        return menu_item

    def to_dict(
        self,
        item: ItemTask,
        pricing: "PricingEngine | None" = None,
    ) -> Dict[str, Any]:
        """Convert ItemTask to dict using data-driven attribute handling."""
        menu_item_name = item.menu_item_name
        menu_item_type = getattr(item, 'menu_item_type', None)
        removed_ingredients = getattr(item, 'removed_ingredients', []) or []

        # Get DB-driven attribute values (source of truth for all customizations)
        attribute_values = getattr(item, 'attribute_values', {}) or {}

        # Read values from attribute_values (data-driven, no hardcoded field list)
        side_choice = attribute_values.get("side_choice")
        toasted = attribute_values.get("toasted")
        spread = attribute_values.get("spread")
        spread_type = attribute_values.get("spread_type")
        spread_price = attribute_values.get("spread_price")
        extra_protein = attribute_values.get("extra_protein")
        toppings_list = attribute_values.get("toppings") or []

        # Build display name (data-driven: bread and other attributes shown as modifiers)
        display_name = menu_item_name


        if side_choice:
            # Data-driven side choice display: check for {side_choice}_choice field
            choice_field = f"{side_choice}_choice"
            specific_choice = attribute_values.get(choice_field)
            if specific_choice:
                display_name = f"{display_name} with {specific_choice} {side_choice}"
            else:
                side_display = side_choice.replace("_", " ")
                display_name = f"{display_name} with {side_display}"

        # Build side config for items with configurable sides
        side_config = None
        if side_choice:
            choice_field = f"{side_choice}_choice"
            specific_choice = attribute_values.get(choice_field)
            if specific_choice:
                side_parts = [specific_choice, side_choice]
                if toasted is True:
                    side_parts.append("toasted")
                if spread and spread != "none":
                    side_parts.append(f"with {spread}")
                side_config = {
                    f"{side_choice}_type": specific_choice,
                    "toasted": toasted,
                    "spread": spread,
                    "description": " ".join(side_parts),
                }

        # Build modifiers list with prices
        # Note: bread is handled by _process_attribute_values_to_modifiers (data-driven)
        modifiers = []

        # Add spread to modifiers if set
        # For bagels, spread is stored as spread_type; for other items, could be either
        effective_spread = spread_type or spread
        if effective_spread and effective_spread.lower() != "none":
            # Look up spread price from pricing engine if not already set
            if spread_price is None and pricing and hasattr(pricing, 'lookup_modifier_price') and menu_item_type:
                # Try compound spread name first (e.g., "scallion_cream_cheese")
                if spread_type and spread and spread_type != spread:
                    compound_slug = f"{spread_type}_{spread}".replace(" ", "_").lower()
                    spread_price = pricing.lookup_modifier_price(compound_slug, menu_item_type)
                # Fall back to base spread name
                if not spread_price:
                    spread_price = pricing.lookup_modifier_price(effective_spread, menu_item_type)
                # Fall back to plain-prefixed name (e.g., "plain_cream_cheese")
                if not spread_price:
                    plain_slug = f"plain_{effective_spread.lower().replace(' ', '_')}"
                    spread_price = pricing.lookup_modifier_price(plain_slug, menu_item_type)
                spread_price = spread_price or 0
            spread_name = effective_spread
            if spread_type and spread and spread_type != spread and spread_type != "plain":
                spread_name = f"{spread_type} {spread}"
            modifiers.append({"name": spread_name, "price": spread_price or 0})

        item_modifications = getattr(item, 'modifications', []) or []
        for mod in item_modifications:
            modifiers.append({"name": mod, "price": 0})

        # Add extra_protein and toppings (with prices from pricing engine)
        if extra_protein and pricing and hasattr(pricing, 'lookup_modifier_price') and menu_item_type:
            protein_price = pricing.lookup_modifier_price(extra_protein, menu_item_type) or 0
            modifiers.append({"name": extra_protein, "price": protein_price})
        for extra in toppings_list:
            if pricing and hasattr(pricing, 'lookup_modifier_price') and menu_item_type:
                extra_price = pricing.lookup_modifier_price(extra, menu_item_type) or 0
                modifiers.append({"name": extra, "price": extra_price})

        # Process modifiers from the unified modifiers field
        item_modifiers = getattr(item, 'modifiers', []) or []
        for mod in item_modifiers:
            mod_slug = mod.get("slug", "")
            mod_display = mod.get("display_name") or mod_slug.replace("_", " ").title()
            mod_price = mod.get("price", 0) or 0.0
            mod_quantity = mod.get("quantity", 1) or 1

            # Handle quantity display
            if mod_quantity > 1:
                mod_display = f"{mod_quantity} {mod_display}"
                mod_price = mod_price * mod_quantity

            if mod_display:
                modifiers.append({"name": mod_display, "price": mod_price})

        # Convert DB-driven attribute_values to modifiers for cart display
        # (for attributes not in the unified modifiers field)
        self._process_attribute_values_to_modifiers(
            attribute_values=attribute_values,
            modifiers=modifiers,
            free_details=[],
            pricing=pricing,
            skip_slugs={"toasted"},  # toasted is manually handled above with item-type-specific logic
            include_free_in_modifiers=True,
        )

        customization_offered = getattr(item, 'customization_offered', False)

        # Get base_price from pricing engine if available, or from item
        base_price = getattr(item, 'base_price', None)
        if base_price is None and pricing:
            item_attrs = menu_cache.get_item_type_attributes(menu_item_type) if menu_item_type else {}
            if "bread" in item_attrs:
                try:
                    base_price = pricing.lookup_base_price("Bagel")
                except ValueError:
                    pass
            elif hasattr(pricing, 'lookup_menu_item_price') and menu_item_name:
                base_price = pricing.lookup_menu_item_price(menu_item_name)
        if base_price is None:
            base_price = item.unit_price or 0.0

        result = self._build_common_dict_fields(item)

        # Use the actual menu_item_type for backwards compatibility
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
            "removed_ingredients": removed_ingredients,
            "attribute_values": attribute_values,
            "customization_offered": customization_offered,
        })

        # Data-driven: output DB-defined attributes at top level
        if menu_item_type:
            item_attrs = menu_cache.get_item_type_attributes(menu_item_type)
            for attr_slug in item_attrs.keys():
                if attr_slug in attribute_values and attr_slug not in result:
                    result[attr_slug] = attribute_values[attr_slug]

        # Output all attribute_values at top level for backward compatibility
        # (data-driven, no hardcoded field list)
        for attr_key, attr_val in attribute_values.items():
            if attr_key not in result and attr_val is not None:
                result[attr_key] = attr_val

        # Add side_config if present
        if side_config:
            result["side_config"] = side_config

        # Build item_config (data-driven)
        item_config = {
            "menu_item_type": menu_item_type,
            "modifiers": modifiers,
            "item_modifiers": item_modifiers,  # Unified modifiers for persistence
            "attribute_values": attribute_values,
            "base_price": base_price,
            **{k: v for k, v in attribute_values.items() if v is not None},
        }
        result["item_config"] = item_config

        return result


# -----------------------------------------------------------------------------
# Converter Registry
# -----------------------------------------------------------------------------
# Module-level converter instance (singleton - all item types use unified converter)
# -----------------------------------------------------------------------------

_unified_converter = UnifiedItemConverter()


def get_converter(item_type: str) -> UnifiedItemConverter:
    """Get the unified converter (same for all item types)."""
    return _unified_converter


def get_converter_for_item(item: ItemTask) -> UnifiedItemConverter:
    """Get the unified converter for any ItemTask."""
    return _unified_converter
