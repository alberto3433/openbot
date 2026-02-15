"""
Attribute Upcharge Calculator.

Handles calculation of price contributions from attribute values.
Extracted from pricing.py for better separation of concerns.
"""

import logging

from .modifier_utils import extract_modifier_slug_and_quantity
from .normalization import normalize_to_slug
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
                item_type, attr_slug, attr_value, item_modifiers, included_categories
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
        item_modifiers: list,
        included_categories: set[str],
    ) -> tuple[float, set[str]]:
        """Process a multi-select attribute value list.

        Always looks up prices from GlobalAttributeOption.price_modifier - this is
        the single source of truth for all pricing.
        """
        total = 0.0
        priced_slugs: set[str] = set()

        for item_val in values:
            if isinstance(item_val, str) and item_val.lower() != "none":
                # Normalize for consistent tracking
                item_val_normalized = normalize_to_slug(item_val)

                # Look up quantity from item_modifiers
                matching_modifier = next(
                    (m for m in item_modifiers
                     if normalize_to_slug(m.get("slug") or "") == item_val_normalized),
                    None
                )
                quantity = matching_modifier.get("quantity", 1) if matching_modifier else 1

                # Default ingredients in included categories are always free.
                # Check this BEFORE upcharge lookup so premium calculations
                # don't accidentally charge defaults (e.g., corned beef on The Reuben).
                is_default = matching_modifier.get("is_default", False) if matching_modifier else False
                if is_default and included_categories:
                    option_category = self._pricing._get_option_ingredient_category(
                        item_type, attr_slug, item_val
                    )
                    if option_category and option_category in included_categories:
                        priced_slugs.add(item_val_normalized)
                        if matching_modifier:
                            matching_modifier["price"] = 0.0
                        continue

                # Look up upcharge from DB - single source of truth
                upcharge = self._pricing.lookup_attribute_option_upcharge(
                    item_type, attr_slug, item_val, included_categories
                )
                if upcharge > 0:
                    total += upcharge * quantity
                    priced_slugs.add(item_val_normalized)
                    if matching_modifier:
                        matching_modifier["price"] = upcharge
                else:
                    price = self._pricing.lookup_modifier_price(item_val, item_type)
                    total += price * quantity
                    priced_slugs.add(item_val_normalized)
                    if matching_modifier:
                        matching_modifier["price"] = price

            elif isinstance(item_val, dict):
                slug, qty = extract_modifier_slug_and_quantity(item_val)
                if slug:
                    # Normalize for consistent tracking
                    slug_normalized = normalize_to_slug(slug)
                    # Always look up from DB - single source of truth
                    # (stored prices are for display only, updated below)
                    price = self._pricing.lookup_modifier_price(slug, item_type)
                    item_val["price"] = price  # Update for display purposes
                    total += price * qty
                    priced_slugs.add(slug_normalized)

        return total, priced_slugs

    def _process_string_attribute(
        self,
        item_type: str,
        attr_slug: str,
        attr_value: str,
        item_modifiers: list,
        included_categories: set[str],
    ) -> tuple[float, set[str]]:
        """Process a single string attribute value.

        Always looks up prices from GlobalAttributeOption.price_modifier - this is
        the single source of truth for all pricing. Stored prices on modifiers are
        for display purposes only and are updated by this method.
        """
        priced_slugs: set[str] = set()

        # Normalize attr_value for consistent comparison
        attr_value_normalized = normalize_to_slug(attr_value)

        # Find the modifier entry for this attribute value (if any) for quantity lookup
        # Note: We no longer use stored prices - always look up from DB
        matching_modifier = next(
            (m for m in item_modifiers
             if normalize_to_slug(m.get("slug") or "") == attr_value_normalized),
            None
        )
        quantity = matching_modifier.get("quantity", 1) if matching_modifier else 1

        # Default ingredients in included categories are always free.
        # Check BEFORE upcharge lookup so premium calculations don't accidentally
        # charge defaults (e.g., spinach on The Lexington).
        is_default = matching_modifier.get("is_default", False) if matching_modifier else False
        if is_default and included_categories:
            option_category = self._pricing._get_option_ingredient_category(
                item_type, attr_slug, attr_value
            )
            if option_category and option_category in included_categories:
                priced_slugs.add(attr_value_normalized)
                if matching_modifier:
                    matching_modifier["price"] = 0.0
                return 0.0, priced_slugs

        # Always look up price from DB - this is the single source of truth
        upcharge = self._pricing.lookup_attribute_option_upcharge(
            item_type, attr_slug, attr_value, included_categories
        )
        logger.debug(
            "recalc: %s=%s upcharge=%.2f (included_categories=%s)",
            attr_slug, attr_value, upcharge, included_categories
        )

        if upcharge > 0:
            # Mark as priced using normalized slug
            priced_slugs.add(attr_value_normalized)
            # Update the modifier's price for display purposes
            if matching_modifier:
                matching_modifier["price"] = upcharge
            return upcharge * quantity, priced_slugs

        # Check if category is included (no charge).
        # If the item's base price already includes this ingredient category,
        # any option in that category is free (user is just picking their preference).
        option_category = self._pricing._get_option_ingredient_category(
            item_type, attr_slug, attr_value
        )
        if option_category and option_category in included_categories:
            # This is a default ingredient in an included category - no charge
            priced_slugs.add(attr_value_normalized)
            if matching_modifier:
                matching_modifier["price"] = 0.0
            return 0.0, priced_slugs

        # Not an included category - try modifier price lookup from DB
        price = self._pricing.lookup_modifier_price(attr_value, item_type)
        # Always mark as priced (even if price is 0) to prevent double-counting
        priced_slugs.add(attr_value_normalized)
        # Update the modifier's price for display purposes
        if matching_modifier:
            matching_modifier["price"] = price
        return price * quantity, priced_slugs
