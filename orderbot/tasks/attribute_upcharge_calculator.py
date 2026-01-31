"""
Attribute Upcharge Calculator.

Handles calculation of price contributions from attribute values.
Extracted from pricing.py for better separation of concerns.
"""

import logging

from .modifier_utils import extract_modifier_slug_and_quantity, extract_modifier_price
from .utils.constants import ATTR_METADATA_SUFFIXES, ATTR_PENDING_PREFIX

logger = logging.getLogger(__name__)


class AttributeUpchargeCalculator:
    """Calculates price contributions from attribute values.

    This class is used by PricingEngine to process attribute values
    and determine their price contributions.
    """

    def __init__(self, pricing_engine):
        """Initialize with reference to pricing engine for lookups.

        Args:
            pricing_engine: PricingEngine instance for price lookups
        """
        self._pricing = pricing_engine

    def apply_upcharges(
        self,
        item_type: str,
        attr_values: dict,
        item_modifiers: list,
        uses_variant_pricing: bool,
        variant_attr: str | None,
        included_categories: set[str],
    ) -> tuple[float, set[str]]:
        """Apply upcharges for attribute values.

        Processes all attribute values and calculates their price contributions.

        Args:
            item_type: The item type slug
            attr_values: Dict of attribute slug -> value
            item_modifiers: List of modifier dicts on the item
            uses_variant_pricing: Whether variant pricing covers an attribute
            variant_attr: The attribute covered by variant pricing
            included_categories: Ingredient categories that don't incur charges

        Returns:
            Tuple of (total_upcharge, priced_slugs)
            - total_upcharge: Sum of all attribute upcharges
            - priced_slugs: Set of slugs that have been priced (to avoid double-counting)
        """
        total = 0.0
        priced_slugs: set[str] = set()

        for attr_slug, attr_value in attr_values.items():
            # Skip metadata/computed fields
            if any(attr_slug.endswith(suffix) for suffix in ATTR_METADATA_SUFFIXES):
                continue
            if attr_slug.startswith(ATTR_PENDING_PREFIX):
                continue

            # Skip if variant pricing covers this attribute
            if uses_variant_pricing and attr_slug == variant_attr:
                continue

            # Skip empty/none values
            if attr_value is None or attr_value is False or attr_value == "":
                continue
            if isinstance(attr_value, str) and attr_value.lower() == "none":
                continue

            # Dispatch to type-specific handler
            upcharge, slugs = self._process_attribute_value(
                item_type, attr_slug, attr_value, item_modifiers, included_categories
            )
            total += upcharge
            priced_slugs.update(slugs)

        return total, priced_slugs

    def _process_attribute_value(
        self,
        item_type: str,
        attr_slug: str,
        attr_value,
        item_modifiers: list,
        included_categories: set[str],
    ) -> tuple[float, set[str]]:
        """Process a single attribute value and return its price contribution.

        Handles different value types: bool, list, str, int/float.

        Returns:
            Tuple of (upcharge, priced_slugs)
        """
        priced_slugs: set[str] = set()

        if isinstance(attr_value, bool) and attr_value is True:
            # Boolean attributes (e.g., toasted=True)
            upcharge = self._pricing.lookup_attribute_option_upcharge(
                item_type, attr_slug, "true", included_categories
            )
            return upcharge, priced_slugs

        if isinstance(attr_value, list):
            # Multi-select: sum prices for each item
            return self._process_list_attribute(
                item_type, attr_slug, attr_value, included_categories
            )

        if isinstance(attr_value, (int, float)):
            # Numeric values - skip (handled via modifiers list)
            return 0.0, priced_slugs

        if isinstance(attr_value, str):
            # Single string value
            return self._process_string_attribute(
                item_type, attr_slug, attr_value, item_modifiers, included_categories
            )

        return 0.0, priced_slugs

    def _process_list_attribute(
        self,
        item_type: str,
        attr_slug: str,
        values: list,
        included_categories: set[str],
    ) -> tuple[float, set[str]]:
        """Process a multi-select attribute value list."""
        total = 0.0
        priced_slugs: set[str] = set()

        for item_val in values:
            if isinstance(item_val, str) and item_val.lower() != "none":
                upcharge = self._pricing.lookup_attribute_option_upcharge(
                    item_type, attr_slug, item_val, included_categories
                )
                if upcharge > 0:
                    total += upcharge
                    priced_slugs.add(item_val)
                else:
                    # Check if category is included
                    option_category = self._pricing._get_option_ingredient_category(
                        item_type, attr_slug, item_val
                    )
                    if option_category and option_category in included_categories:
                        priced_slugs.add(item_val)
                    else:
                        price = self._pricing.lookup_modifier_price(item_val, item_type)
                        total += price
                        priced_slugs.add(item_val)

            elif isinstance(item_val, dict):
                slug, qty = extract_modifier_slug_and_quantity(item_val)
                if slug:
                    stored_price = extract_modifier_price(item_val)
                    if stored_price is not None:
                        price = stored_price
                    else:
                        price = self._pricing.lookup_modifier_price(slug, item_type)
                        if price > 0:
                            item_val["price"] = price
                    total += price * qty
                    priced_slugs.add(slug)

        return total, priced_slugs

    def _process_string_attribute(
        self,
        item_type: str,
        attr_slug: str,
        attr_value: str,
        item_modifiers: list,
        included_categories: set[str],
    ) -> tuple[float, set[str]]:
        """Process a single string attribute value."""
        priced_slugs: set[str] = set()

        # Check if this slug exists in item_modifiers with a stored price
        # If so, skip - Section 3 will handle it using stored price x quantity
        modifier_with_price = next(
            (m for m in item_modifiers
             if m.get("slug") == attr_value and m.get("price", 0) > 0),
            None
        )
        if modifier_with_price:
            logger.debug(
                "recalc: skipping %s=%s (has modifier with price)",
                attr_slug, attr_value
            )
            return 0.0, priced_slugs

        upcharge = self._pricing.lookup_attribute_option_upcharge(
            item_type, attr_slug, attr_value, included_categories
        )
        logger.debug(
            "recalc: %s=%s upcharge=%.2f (included_categories=%s)",
            attr_slug, attr_value, upcharge, included_categories
        )

        if upcharge > 0:
            priced_slugs.add(attr_value)
            # Update the modifier's price so it displays in UI
            for mod in item_modifiers:
                if mod.get("slug") == attr_value and not mod.get("price"):
                    mod["price"] = upcharge
                    break
            return upcharge, priced_slugs

        # Check if category is included
        option_category = self._pricing._get_option_ingredient_category(
            item_type, attr_slug, attr_value
        )
        if option_category and option_category in included_categories:
            priced_slugs.add(attr_value)
            return 0.0, priced_slugs

        # Not an included category - try modifier price lookup
        price = self._pricing.lookup_modifier_price(attr_value, item_type)
        priced_slugs.add(attr_value)
        if price > 0:
            for mod in item_modifiers:
                if mod.get("slug") == attr_value and not mod.get("price"):
                    mod["price"] = price
                    break
        return price, priced_slugs
