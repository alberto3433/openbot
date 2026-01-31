"""
Item Converters for Adapter Layer.

This module provides conversion between dict-based item representations
and ItemTask objects.

The UnifiedItemConverter handles all item types using a data-driven approach
based on database configuration. All item type slugs (bagel, coffee, sandwich,
sized_beverage, etc.) are aliases that map to the single UnifiedItemConverter.
"""

import logging
from typing import Any, Dict

from .models import (
    TaskStatus,
    ItemTask,
    MenuItemTask,
    _pluralize_display_name,
)
from .normalization import format_slug_for_display
from .utils.constants import PRICE_SUFFIXES
from orderbot.menu_data_cache import menu_cache

logger = logging.getLogger(__name__)

# =============================================================================
# Constants for canonical slug values
# =============================================================================
# These are used for declined/negative selections and boolean attributes

DECLINED_SLUG = "_declined"
"""Marker for explicitly declined optional attributes."""

YES_SLUG = "yes"
"""Canonical slug for boolean True values."""

NO_SLUG = "no"
"""Canonical slug for boolean False values."""


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
        }

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
            for suffix in PRICE_SUFFIXES:
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
            "modifiers", "free_details", "base_price",
            "line_total", "item_config", "attribute_values", "customization_offered",
            "display_name", "item_modifiers",  # item_modifiers handled separately
            "is_signature",  # Metadata, not a configurable attribute
            "special_instructions",  # Handled separately, not an attribute
        }
        for source in (item_dict, item_config):
            for key, value in source.items():
                if key in attribute_values or key in structural_keys:
                    continue
                # Skip metadata suffix keys (handled with their parent)
                if key.endswith(PRICE_SUFFIXES):
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

        # Restore modifiers from item_config (source of truth for quantity/price)
        stored_modifiers = item_config.get("item_modifiers") or []

        # Start with stored_modifiers as the base (they have correct quantity/price)
        selections = []
        stored_keys = set()
        for mod in stored_modifiers:
            if isinstance(mod, dict):
                slug = mod.get("slug", "")
                category = mod.get("category", "")
                stored_keys.add((slug, category))
                selections.append({
                    "slug": slug,
                    "category": category,
                    "quantity": mod.get("quantity", 1),
                    "price": mod.get("price", 0),
                    "display_name": mod.get("display_name") or format_slug_for_display(slug, category),
                })

        # Add from attribute_values only if NOT already in stored_modifiers
        for category, value in attribute_values.items():
            # Skip price/upcharge companion keys
            if category.endswith(PRICE_SUFFIXES):
                continue
            if value is None:
                continue

            if isinstance(value, bool):
                # Boolean attributes: store as canonical yes/no slug
                slug = YES_SLUG if value else NO_SLUG
                cat_display = format_slug_for_display(category, check_cache=False)
                display_name = cat_display if value else f"Not {cat_display}"
                if (slug, category) not in stored_keys:
                    selections.append({
                        "slug": slug,
                        "category": category,
                        "quantity": 1,
                        "price": attribute_values.get(f"{category}_price", 0) or 0,
                        "display_name": display_name,
                    })
                    stored_keys.add((slug, category))
            elif isinstance(value, list):
                # Multi-select: each item becomes a selection
                for v in value:
                    if isinstance(v, dict):
                        v_slug = v.get("slug", "")
                        v_cat = v.get("category", category)
                        if (v_slug, v_cat) not in stored_keys:
                            selections.append(v)
                            stored_keys.add((v_slug, v_cat))
                    else:
                        v_slug = str(v)
                        if (v_slug, category) not in stored_keys:
                            selections.append({
                                "slug": v_slug,
                                "category": category,
                                "quantity": 1,
                                "price": 0,
                                "display_name": format_slug_for_display(str(v), check_cache=False),
                            })
                            stored_keys.add((v_slug, category))
            else:
                slug = str(value)
                if (slug, category) not in stored_keys:
                    display_name = format_slug_for_display(str(value), check_cache=False)
                    price = attribute_values.get(f"{category}_price", 0) or attribute_values.get(f"{category}_upcharge", 0) or 0
                    selections.append({
                        "slug": slug,
                        "category": category,
                        "quantity": 1,
                        "price": price,
                        "display_name": display_name,
                    })
                    stored_keys.add((slug, category))

        menu_item = MenuItemTask(
            menu_item_name=item_dict.get("menu_item_name") or "Unknown",
            menu_item_id=item_dict.get("menu_item_id"),
            menu_item_type=menu_item_type,
            modifications=item_dict.get("modifications") or [],
            removed_ingredients=item_config.get("removed_ingredients") or item_dict.get("removed_ingredients") or [],
            quantity=item_dict.get("quantity", 1),
            modifiers=selections,
            customization_offered=item_dict.get("customization_offered", False),
            is_signature=item_config.get("is_signature", item_dict.get("is_signature", False)),
            special_instructions=item_dict.get("special_instructions") or [],
        )
        self._restore_common_fields(menu_item, item_dict)
        return menu_item

    def to_dict(
        self,
        item: ItemTask,
        pricing: "PricingEngine | None" = None,
    ) -> Dict[str, Any]:
        """Convert ItemTask to dict using data-driven attribute handling.

        This method is fully data-driven with no hardcoded attribute names,
        menu item names, or domain-specific logic.
        """
        menu_item_name = item.menu_item_name
        menu_item_type = getattr(item, 'menu_item_type', None)
        removed_ingredients = getattr(item, 'removed_ingredients', []) or []

        # Get DB-driven attribute values (source of truth for all customizations)
        attribute_values = getattr(item, 'attribute_values', {}) or {}

        # Build display name using the item's get_display_name() method
        # which handles name-forming categories (e.g., bread type for bagels)
        display_name = item.get_display_name()

        # Add "(side)" suffix for items that are sides of another item
        is_side_item = getattr(item, 'side_of_item_id', None) is not None
        if is_side_item:
            display_name = f"{display_name} (side)"

        # Build modifiers list with prices
        modifiers = []

        # Add modifications (free, no price lookup needed)
        item_modifications = getattr(item, 'modifications', []) or []
        for mod in item_modifications:
            modifiers.append({"name": mod, "price": 0})

        # Add special instructions (e.g., "room for cream", "extra hot") - free, shown in cart
        item_special_instructions = getattr(item, 'special_instructions', []) or []
        for instruction in item_special_instructions:
            # Format for display: title case
            display_instruction = instruction.title() if instruction else instruction
            modifiers.append({"name": display_instruction, "price": 0})

        # Process modifiers from the unified modifiers field
        item_modifiers = item.modifiers or []
        for mod in item_modifiers:
            # Skip name-forming categories (e.g., bread) - already in display name
            # Exception: signature items keep their name, so show bread as a sub-line
            mod_category = mod.get("category", "")
            if menu_cache.is_name_forming_category(mod_category) and not item.is_signature:
                continue

            mod_slug = mod.get("slug", "")

            # Skip declined/negative selections - only show positive selections
            if mod_slug in (DECLINED_SLUG, NO_SLUG):
                continue

            mod_display = mod.get("display_name") or format_slug_for_display(mod_slug, mod_category)
            mod_price = mod.get("price", 0) or 0.0
            mod_quantity = mod.get("quantity", 1) or 1

            # Handle quantity display
            if mod_quantity > 1:
                # Use ingredient_category for quantity unit lookup (e.g., "syrup" has "pump")
                # Fall back to mod_category if ingredient_category not set
                ing_category = mod.get("ingredient_category") or mod_category
                quantity_unit = menu_cache.get_ingredient_category_quantity_unit(ing_category)
                if quantity_unit:
                    # Format: "2 pumps of Vanilla Syrup"
                    unit_plural = quantity_unit + "s" if mod_quantity > 1 else quantity_unit
                    mod_display = f"{mod_quantity} {unit_plural} of {mod_display}"
                else:
                    # Fallback: "2 Vanilla Syrups"
                    mod_display = f"{mod_quantity} {_pluralize_display_name(mod_display)}"
                mod_price = mod_price * mod_quantity

            if mod_display:
                modifiers.append({"name": mod_display, "price": mod_price})

        customization_offered = getattr(item, 'customization_offered', False)

        # Get base_price from pricing engine if available, or from item
        # Data-driven: lookup by menu_item_name and variant attribute (if present)
        base_price = getattr(item, 'base_price', None)
        if base_price is None and pricing and hasattr(pricing, 'lookup_base_price') and menu_item_name:
            try:
                # Derive variant attribute from menu_item's size_category_slug
                menu_item = pricing._lookup_menu_item(menu_item_name)
                variant_attr = menu_item.get("size_category_slug") if menu_item and menu_item.get("size_prices") else None
                variant_value = attribute_values.get(variant_attr) if variant_attr else None
                base_price = pricing.lookup_base_price(menu_item_name, variant_value)
            except (ValueError, KeyError):
                # Item not in menu data, will fall back to unit_price
                pass
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
            "special_instructions": getattr(item, 'special_instructions', []) or [],
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

        # Build item_config (data-driven)
        item_config = {
            "menu_item_type": menu_item_type,
            "modifiers": modifiers,
            "item_modifiers": item_modifiers,  # Unified modifiers for persistence
            "attribute_values": attribute_values,
            "base_price": base_price,
            "is_signature": getattr(item, 'is_signature', False),
            **{k: v for k, v in attribute_values.items() if v is not None},
        }
        result["item_config"] = item_config

        return result


# -----------------------------------------------------------------------------
# Module-level converter instance (singleton - all item types use unified converter)
# -----------------------------------------------------------------------------

_unified_converter = UnifiedItemConverter()
