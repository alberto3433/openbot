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

                # Account for base quantity (default items included in base price).
                # _base_quantity tracks original default quantity before user modifications
                # (e.g., "extra avocado" sets quantity=2, _base_quantity=1 → charge for 1).
                base_quantity = matching_modifier.get("_base_quantity", 0) if matching_modifier else 0
                effective_quantity = max(0, quantity - base_quantity) if base_quantity > 0 else quantity

                # Default ingredients in included categories are always free.
                # Check this BEFORE upcharge lookup so premium calculations
                # don't accidentally charge defaults (e.g., corned beef on The Reuben).
                # Exception: if user asked for extra (effective_quantity > 0), charge for extras.
                is_default = matching_modifier.get("is_default", False) if matching_modifier else False
                logger.info(
                    "LIST_ATTR_PRICING: attr=%s val=%s qty=%d base_qty=%d eff_qty=%d "
                    "is_default=%s modifier=%s included_cats=%s",
                    attr_slug, item_val, quantity, base_quantity, effective_quantity,
                    is_default, matching_modifier, included_categories
                )
                if is_default and included_categories:
                    option_category = self._pricing._get_option_ingredient_category(
                        item_type, attr_slug, item_val
                    )
                    # Fall back to the modifier's stored ingredient_category when
                    # the option isn't linked to an ingredient in the DB
                    if not option_category and matching_modifier:
                        option_category = matching_modifier.get("ingredient_category")
                    if option_category and option_category in included_categories:
                        if base_quantity == 0:
                            # Default ingredient, not user-modified → entirely free
                            priced_slugs.add(item_val_normalized)
                            if matching_modifier:
                                matching_modifier["price"] = 0.0
                            continue
                        # else: user asked for extra → fall through to charge for extras

                # Non-default additions in multi-select get full price, not premium.
                # included_categories discount is for replacements of default ingredients
                # (e.g., swapping cheddar for swiss), not new additions (e.g., adding bacon).
                lookup_cats = included_categories if (is_default and base_quantity == 0) else None
                upcharge = self._pricing.lookup_attribute_option_upcharge(
                    item_type, attr_slug, item_val, lookup_cats
                )
                if upcharge > 0:
                    total += upcharge * effective_quantity
                    priced_slugs.add(item_val_normalized)
                    if matching_modifier:
                        # Set display price so adapter's price×quantity gives correct total
                        matching_modifier["price"] = (
                            upcharge * effective_quantity / quantity if quantity > 0 else 0.0
                        )
                else:
                    price = self._pricing.lookup_modifier_price(item_val, item_type)
                    total += price * effective_quantity
                    priced_slugs.add(item_val_normalized)
                    if matching_modifier:
                        matching_modifier["price"] = (
                            price * effective_quantity / quantity if quantity > 0 else 0.0
                        )

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
        base_quantity = matching_modifier.get("_base_quantity", 0) if matching_modifier else 0
        effective_quantity = max(0, quantity - base_quantity) if base_quantity > 0 else quantity

        # Debug: trace all pricing decision inputs
        is_default = matching_modifier.get("is_default", False) if matching_modifier else False
        logger.info(
            "STRING_ATTR_PRICING: attr=%s val=%s qty=%d base_qty=%d eff_qty=%d "
            "is_default=%s modifier=%s included_cats=%s",
            attr_slug, attr_value, quantity, base_quantity, effective_quantity,
            is_default, matching_modifier, included_categories
        )

        # Default ingredients in included categories are always free.
        # Check BEFORE upcharge lookup so premium calculations don't accidentally
        # charge defaults (e.g., spinach on The Lexington).
        if is_default and included_categories:
            option_category = self._pricing._get_option_ingredient_category(
                item_type, attr_slug, attr_value
            )
            # Fall back to the modifier's stored ingredient_category when
            # the option isn't linked to an ingredient in the DB
            if not option_category and matching_modifier:
                option_category = matching_modifier.get("ingredient_category")
            if option_category and option_category in included_categories:
                base_quantity = matching_modifier.get("_base_quantity", 0) if matching_modifier else 0
                if base_quantity == 0:
                    # Pure default, no user modification → entirely free
                    priced_slugs.add(attr_value_normalized)
                    if matching_modifier:
                        matching_modifier["price"] = 0.0
                    return 0.0, priced_slugs
                # else: user asked for extra → fall through to charge for extras

        # Always look up price from DB - this is the single source of truth
        lookup_cats = None if base_quantity > 0 else included_categories
        upcharge = self._pricing.lookup_attribute_option_upcharge(
            item_type, attr_slug, attr_value, lookup_cats
        )
        logger.info(
            "STRING_ATTR_UPCHARGE: attr=%s val=%s upcharge=%.2f lookup_cats=%s "
            "base_qty=%d eff_qty=%d",
            attr_slug, attr_value, upcharge, lookup_cats, base_quantity,
            effective_quantity
        )

        if upcharge > 0:
            # Mark as priced using normalized slug
            priced_slugs.add(attr_value_normalized)
            # Set display price so adapter's price×quantity gives correct total
            if matching_modifier:
                matching_modifier["price"] = (
                    upcharge * effective_quantity / quantity if quantity > 0 else 0.0
                )
            return upcharge * effective_quantity, priced_slugs

        # Check if category is included (no charge).
        # If the item's base price already includes this ingredient category,
        # any option in that category is free (user is just picking their preference).
        option_category = self._pricing._get_option_ingredient_category(
            item_type, attr_slug, attr_value
        )
        logger.info(
            "STRING_ATTR_FALLBACK: attr=%s val=%s option_category=%s "
            "in_included=%s base_qty=%d",
            attr_slug, attr_value, option_category,
            option_category in included_categories if option_category else False,
            base_quantity
        )
        if option_category and option_category in included_categories and base_quantity == 0:
            if quantity <= 1:
                # Simple replacement in included category - no charge
                priced_slugs.add(attr_value_normalized)
                if matching_modifier:
                    matching_modifier["price"] = 0.0
                return 0.0, priced_slugs
            # quantity > 1: 1 unit free (replacement slot), extras at full price
            extra_qty = quantity - 1
            full_price = self._pricing.lookup_attribute_option_upcharge(
                item_type, attr_slug, attr_value, None
            )
            if full_price <= 0:
                full_price = self._pricing.lookup_modifier_price(attr_value, item_type)
            logger.info(
                "STRING_ATTR_EXTRA: attr=%s val=%s extra_qty=%d full_price=%.2f",
                attr_slug, attr_value, extra_qty, full_price
            )
            priced_slugs.add(attr_value_normalized)
            if matching_modifier:
                # Set display price so adapter's price×quantity gives correct total
                matching_modifier["price"] = (
                    full_price * extra_qty / quantity if quantity > 0 else 0.0
                )
            return full_price * extra_qty, priced_slugs

        # Not an included category - try modifier price lookup from DB
        price = self._pricing.lookup_modifier_price(attr_value, item_type)
        # Always mark as priced (even if price is 0) to prevent double-counting
        priced_slugs.add(attr_value_normalized)
        # Set display price so adapter's price×quantity gives correct total
        if matching_modifier:
            matching_modifier["price"] = (
                price * effective_quantity / quantity if quantity > 0 else 0.0
            )
        return price * effective_quantity, priced_slugs
