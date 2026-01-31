"""
Item Replacement Handler.

This module handles item replacement operations including:
- Attribute value replacement (e.g., "double" for shots)
- Single-select attribute updates (e.g., "make it pumpernickel")
- Full item replacement with modifier preservation
- Selection-based updates from raw input

Extracted from taking_items_handler.py for better separation of concerns.
"""

import logging
import re
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache

from .models import OrderTask, MenuItemTask
from .schemas import StateMachineResult, OpenInputResponse, Selection
from .parsers import extract_attribute_values
from .parsers.intent_patterns import REPLACE_ITEM_PATTERN
from .normalization import format_slug_for_display
from .checkout_messages import changed_to_anything_else
from .handler_utils import get_last_item, recalculate_and_summarize

if TYPE_CHECKING:
    from .pricing import PricingEngine

logger = logging.getLogger(__name__)


class ItemReplacementHandler:
    """
    Handles item replacement operations.

    Manages replacement of items in the cart based on various user patterns
    like "make it a coke instead", "change to double shot", etc.
    """

    def __init__(self, pricing: "PricingEngine"):
        """
        Initialize the item replacement handler.

        Args:
            pricing: PricingEngine for recalculating prices after modifications.
        """
        self.pricing = pricing

    def handle_item_replacement(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        raw_user_input: str | None,
    ) -> tuple[StateMachineResult | None, str | None]:
        """Handle item replacement: 'make it a coke instead', 'change it to X', etc.

        Handles:
        - Attribute value replacement (e.g., "double" for shots)
        - Single-select attribute updates (e.g., "make it pumpernickel")
        - Full item replacement with modifier preservation
        - Selection-based updates from raw input

        Returns:
            Tuple of (StateMachineResult if handled, replaced_item_name if item was removed).
            If result is not None, caller should return it.
            If result is None but replaced_item_name is set, caller should add new items.
        """
        if not parsed.replace_last_item:
            return None, None

        active_items = order.items.get_active_items()
        if not active_items:
            logger.info("Replacement requested but no items in cart to replace")
            return None, None

        last_item = get_last_item(active_items)
        has_new_items = bool(parsed.parsed_items)

        # Try attribute value replacement (e.g., "double" for shots)
        result = self._try_attribute_value_replacement(last_item, raw_user_input, order)
        if result:
            return result, None

        # Try single-select attribute update from parsed items
        result = self._try_single_select_update(last_item, parsed, order)
        if result:
            return result, None

        # Try applying input as selections to last item
        result = self._try_selection_based_update(last_item, raw_user_input, has_new_items, order)
        if result:
            return result, None

        # Normal replacement: remove old item, new item will be added by caller
        replaced_item_name = last_item.get_summary()
        last_item_index = order.items.items.index(last_item)
        order.items.remove_item(last_item_index)
        logger.info("Replacement: removed last item '%s' from cart", replaced_item_name)

        return None, replaced_item_name

    def _try_attribute_value_replacement(
        self,
        last_item,
        raw_user_input: str | None,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Try to replace an attribute value (e.g., "double" for shots).

        This takes priority over item parsing to avoid false matches like
        "double" -> "Double-Chocolate Muffin" when user meant "double shot".
        """
        if not isinstance(last_item, MenuItemTask) or not raw_user_input:
            return None

        replace_match = REPLACE_ITEM_PATTERN.match(raw_user_input)
        if not replace_match:
            return None

        replacement_text = None
        for i in range(1, 11):
            if replace_match.group(i):
                replacement_text = replace_match.group(i)
                break

        if not replacement_text:
            return None

        replacement_text = replacement_text.strip().lower()
        replacement_text = re.sub(r"^(?:a|an)\s+", "", replacement_text)

        item_type = last_item.menu_item_type
        if not item_type:
            return None

        attrs = menu_cache.get_item_type_attributes(item_type)
        for attr_slug, attr_config in attrs.items():
            for opt in attr_config.get("options", []):
                opt_slug = opt.get("slug", "").lower()
                opt_display = opt.get("display_name", "").lower()
                matches = (
                    replacement_text == opt_slug or
                    replacement_text == opt_slug.replace("_", " ") or
                    replacement_text == opt_display or
                    replacement_text in [w.lower() for w in opt_display.split()]
                )
                if matches:
                    logger.info(
                        "REPLACE_AS_ATTR_PRIORITY: '%s' matches attr %s option '%s'",
                        replacement_text, attr_slug, opt["slug"]
                    )

                    # Remove existing selections for this attribute
                    last_item.modifiers = [
                        m for m in last_item.modifiers
                        if m.get("category") != attr_slug
                    ]

                    # Add the new selection
                    last_item.add_selection(
                        opt["slug"],
                        attr_slug,
                        quantity=1,
                        price=opt.get("price_modifier", 0),
                        display_name=opt.get("display_name", opt["slug"]),
                    )

                    if self.pricing:
                        self.pricing.recalculate_item_price(last_item)

                    return StateMachineResult(
                        message=changed_to_anything_else(opt.get('display_name', opt['slug'])),
                        order=order,
                    )

        return None

    def _try_single_select_update(
        self,
        last_item,
        parsed: OpenInputResponse,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Try to update single-select attribute from parsed items.

        E.g., "make it pumpernickel" when they have "plain bagel toasted with cream cheese".
        """
        if not parsed.parsed_items or not isinstance(last_item, MenuItemTask):
            return None

        item_type = last_item.menu_item_type
        if not item_type:
            return None

        attrs_updated = []

        # Check each parsed item for single_select attribute values we can transfer
        for parsed_item in parsed.parsed_items:
            if not hasattr(parsed_item, 'attribute_values'):
                continue
            parsed_attrs = getattr(parsed_item, 'attribute_values', {}) or {}
            for attr_slug, new_value in parsed_attrs.items():
                if not new_value:
                    continue
                # Check if this is a single_select attribute on the target item
                input_type = menu_cache.get_attribute_input_type(item_type, attr_slug)
                if input_type == "single_select" and last_item.has_attribute(attr_slug):
                    old_value = last_item.get(attr_slug)
                    last_item[attr_slug] = new_value
                    attrs_updated.append((attr_slug, old_value, new_value))

        if attrs_updated:
            for attr_slug, old_value, new_value in attrs_updated:
                logger.info("Replacement: changed %s from '%s' to '%s', preserving modifiers",
                           attr_slug, old_value, new_value)

            # Recalculate price if needed
            updated_summary = recalculate_and_summarize(last_item, self.pricing)
            return StateMachineResult(
                message=changed_to_anything_else(updated_summary),
                order=order,
            )

        return None

    def _try_selection_based_update(
        self,
        last_item,
        raw_user_input: str | None,
        has_new_items: bool,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Try applying input as selections to last item."""
        if has_new_items or not isinstance(last_item, MenuItemTask) or not raw_user_input:
            return None

        item_type = last_item.menu_item_type
        if not item_type:
            return None

        # Check if item accepts any modifiers (data-driven from DB)
        if menu_cache.item_accepts_input_modifiers(item_type):
            result = self._apply_selections_from_input(last_item, raw_user_input, item_type, order)
            if result:
                return result
        else:
            # Check if user is changing a single_select attribute value
            result = self._apply_single_select_from_input(last_item, raw_user_input, item_type, order)
            if result:
                return result

        return None

    def _apply_selections_from_input(
        self,
        last_item: MenuItemTask,
        raw_user_input: str,
        item_type: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Apply selections extracted from user input to the last item."""
        # Extract attribute values and convert to selections
        attr_values = extract_attribute_values(raw_user_input, item_type)
        selections: list[Selection] = []
        if attr_values:
            for attr_slug, value in attr_values.items():
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict) and item.get("slug"):
                            selections.append(Selection(
                                slug=item["slug"],
                                category=item.get("category") or attr_slug,
                                quantity=item.get("quantity", 1),
                            ))
                elif isinstance(value, str) and value:
                    selections.append(Selection(slug=value, category=attr_slug))

        if not selections:
            return None

        # Clear only modifiers in categories being modified (preserve others)
        categories = {sel.category for sel in selections}
        logger.info("Replacement: applying selections to item from categories: %s", categories)
        for category in categories:
            last_item.remove_selection(category)  # Clear only this category

        # Apply all selections
        for sel in selections:
            last_item.add_selection(
                slug=sel.slug,
                category=sel.category,
                quantity=sel.quantity or 1,
                display_name=format_slug_for_display(sel.slug, check_cache=False),
            )

        # Update single_select attributes from selections (e.g., spread)
        # Data-driven lookup for attribute storage
        for category in menu_cache.get_all_ingredient_categories():
            attr_slug = menu_cache.get_attribute_for_category(item_type, category)
            if attr_slug:
                input_type = menu_cache.get_attribute_input_type(item_type, attr_slug)
                if input_type == "single_select":
                    # Find selections with this category
                    cat_selections = [s.slug for s in selections if s.category == category]
                    if cat_selections:
                        last_item[attr_slug] = cat_selections[0]
                    # Don't clear unmentioned attributes - only update what was explicitly specified

        # Recalculate price with new modifiers and return confirmation
        updated_summary = recalculate_and_summarize(last_item, self.pricing)
        return StateMachineResult(
            message=changed_to_anything_else(updated_summary),
            order=order,
        )

    def _apply_single_select_from_input(
        self,
        last_item: MenuItemTask,
        raw_user_input: str,
        item_type: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Apply single-select attribute change from raw input.

        E.g., "make it blueberry cream cheese".
        """
        input_lower = raw_user_input.lower()

        # Data-driven: check all ingredient categories that map to single_select attributes
        for category in menu_cache.get_all_ingredient_categories():
            attr_slug = menu_cache.get_attribute_for_category(item_type, category)
            if not attr_slug:
                continue
            input_type = menu_cache.get_attribute_input_type(item_type, attr_slug)
            if input_type != "single_select":
                continue

            # Check if input contains a modifier from this category
            new_value = None
            for modifier in sorted(menu_cache.get_ingredients(category), key=len, reverse=True):
                if modifier in input_lower:
                    new_value = menu_cache.normalize_modifier(modifier)
                    break

            if new_value:
                old_value = last_item.get(attr_slug)
                last_item[attr_slug] = new_value
                category_display = menu_cache.get_ingredient_category_display_name(category)
                logger.info("Replacement: changed %s from '%s' to '%s'", category, old_value, new_value)

                # Recalculate price if needed
                updated_summary = recalculate_and_summarize(last_item, self.pricing)
                return StateMachineResult(
                    message=changed_to_anything_else(updated_summary),
                    order=order,
                )

        return None
