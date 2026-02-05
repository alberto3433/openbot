"""
Early Pattern Handler for Order State Machine.

This module handles early pattern detection in the taking items phase,
before LLM parsing is invoked. These patterns can be handled deterministically
for lower latency:
- "make it 2" / "make it three" (quantity changes)
- "make 2 vanilla syrups" (modifier quantity changes)
- "add vanilla syrup" (pure modifier additions)

Extracted from taking_items_handler.py for better separation of concerns.
"""

import logging
import re
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache

from .models import OrderTask, MenuItemTask
from .schemas import StateMachineResult
from .parsers.deterministic import MAKE_IT_N_PATTERN
from .parsers.quantity_utils import parse_make_it_n_quantity
from .parsers.constants import ADD_MODIFIER_PATTERNS
from .handler_utils import (
    is_configurable_menu_item,
    get_last_item,
    recalculate_and_summarize,
)
from .modifier_input_handler import (
    get_all_modifier_patterns_for_item,
    add_modifiers_from_input,
    match_category_removal_pattern,
    remove_modifiers_by_category,
)
from .checkout_messages import (
    item_added_anything_else,
    sure_added_to_anything_else,
    sure_removed_anything_else,
    sure_updated_anything_else,
)

if TYPE_CHECKING:
    from .pricing import PricingEngine
    from .modifier_change_handler import ModifierChangeHandler

logger = logging.getLogger(__name__)


class EarlyPatternHandler:
    """
    Handles early pattern detection in the taking items phase.

    These patterns are detected before LLM parsing for lower latency:
    - "make it 2" / "make it three" quantity changes
    - "make 2 vanilla syrups" modifier quantity changes
    - "add vanilla syrup" pure modifier additions
    """

    def __init__(
        self,
        pricing: "PricingEngine | None" = None,
        modifier_change_handler: "ModifierChangeHandler | None" = None,
    ) -> None:
        """
        Initialize the early pattern handler.

        Args:
            pricing: Pricing engine for recalculating item prices.
            modifier_change_handler: Handler for modifier quantity changes.
        """
        self.pricing = pricing
        self._modifier_change_handler = modifier_change_handler

    def handle_make_it_n(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle 'make it 2' / 'make it three' pattern to duplicate last item.

        Args:
            user_input: Raw user input string.
            order: Current order state.

        Returns:
            StateMachineResult if pattern matched, None otherwise.
        """
        make_it_n_match = MAKE_IT_N_PATTERN.match(user_input.strip())
        if not make_it_n_match:
            return None

        num_str = None
        for i in range(1, 8):
            if make_it_n_match.group(i):
                num_str = make_it_n_match.group(i).lower()
                break

        if not num_str:
            return None

        target_qty = parse_make_it_n_quantity(num_str)
        if not target_qty:
            return None

        active_items = order.items.get_active_items()
        if not active_items:
            return None

        last_item = get_last_item(active_items)
        last_item_name = last_item.get_summary()
        added_count = target_qty - 1

        for _ in range(added_count):
            order.items.add_item(last_item.duplicate())

        logger.info("TAKING_ITEMS: Added %d more of '%s'", added_count, last_item_name)

        return StateMachineResult(
            message=item_added_anything_else(added_count, last_item_name),
            order=order,
        )

    def handle_modifier_change_request(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle modifier quantity change patterns like 'make 2 vanilla syrups'.

        Args:
            user_input: Raw user input string.
            order: Current order state.

        Returns:
            StateMachineResult if pattern matched and change applied, None otherwise.
        """
        active_items = order.items.get_active_items()
        if not active_items or not self._modifier_change_handler:
            return None

        change_request = self._modifier_change_handler.detect_change_request(user_input)
        if not change_request:
            return None

        if not change_request.possible_attributes:
            return None

        if change_request.possible_attributes[0] == "unknown":
            return None

        # Apply the change directly
        result = self._modifier_change_handler.apply_change(
            order=order,
            item_id=None,  # Apply to last item
            attr_slug=change_request.possible_attributes[0],
            new_value=change_request.new_value,
            target=change_request.target,
        )

        if not result.success:
            return None

        last_item = get_last_item(active_items)
        updated_summary = recalculate_and_summarize(last_item, self.pricing)
        return StateMachineResult(
            message=sure_updated_anything_else(updated_summary),
            order=order,
        )

    def handle_early_modifier_input(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle 'add [modifier]' patterns and pure modifier inputs.

        Detects and handles:
        - "add vanilla syrup" patterns
        - Pure modifier inputs like "vanilla" when the last item accepts modifiers

        Args:
            user_input: Raw user input string.
            order: Current order state.

        Returns:
            StateMachineResult if modifier added, None otherwise.
        """
        input_lower = user_input.lower().strip()
        active_items = order.items.get_active_items()

        is_add_modifier_request = any(
            re.search(pattern, input_lower) for pattern in ADD_MODIFIER_PATTERNS
        )

        # Check if this is a pure modifier input for the last item (data-driven)
        is_pure_modifier_input = False
        has_item_modifier = False
        item_modifier_patterns: set[str] = set()

        if active_items:
            last_item = get_last_item(active_items)
            if is_configurable_menu_item(last_item):
                # Get modifier patterns for this specific item type (data-driven)
                item_modifier_patterns = get_all_modifier_patterns_for_item(last_item.menu_item_type)
                has_item_modifier = any(mod in input_lower for mod in item_modifier_patterns)

        logger.info(
            "EARLY_MOD_DETECT: has_item_modifier=%s, active_items=%d",
            has_item_modifier, len(active_items)
        )

        if has_item_modifier and active_items:
            last_item = get_last_item(active_items)
            # Check if item accepts input modifiers (data-driven)
            accepts_modifiers = (
                isinstance(last_item, MenuItemTask) and
                last_item.menu_item_type and
                menu_cache.item_accepts_input_modifiers(last_item.menu_item_type)
            )
            logger.info("EARLY_MOD_DETECT: accepts_modifiers=%s", accepts_modifiers)
            if accepts_modifiers:
                # Check if input is ONLY a modifier (no other item keywords)
                item_keywords = menu_cache.get_item_keywords()
                non_modifier_keywords = {kw for kw in item_keywords if kw not in item_modifier_patterns}
                has_other_item = any(
                    re.search(rf'\b{re.escape(kw)}\b', input_lower)
                    for kw in non_modifier_keywords
                )
                logger.info("EARLY_MOD_DETECT: has_other_item=%s", has_other_item)
                if not has_other_item:
                    is_pure_modifier_input = True
                    logger.info("EARLY_MOD_DETECT: Setting is_pure_modifier_input=True")

        # If it's an "add modifier" pattern OR pure modifier input, modify the last item
        if not (is_add_modifier_request or is_pure_modifier_input):
            return None

        if not has_item_modifier or not active_items:
            return None

        last_item = get_last_item(active_items)
        # Check if item accepts input modifiers (data-driven)
        accepts_modifiers = (
            is_configurable_menu_item(last_item) and
            menu_cache.item_accepts_input_modifiers(last_item.menu_item_type)
        )

        if not accepts_modifiers:
            return None

        # Check for category-level modifier removal first
        removed_category = match_category_removal_pattern(input_lower, last_item.menu_item_type)
        if removed_category:
            if remove_modifiers_by_category(last_item, removed_category):
                updated_summary = recalculate_and_summarize(last_item, self.pricing)
                category_display = menu_cache.get_ingredient_category_display_name(removed_category)
                return StateMachineResult(
                    message=sure_removed_anything_else(category_display.lower(), updated_summary),
                    order=order,
                )

        # Try adding modifiers
        made_change = add_modifiers_from_input(last_item, input_lower)

        if made_change:
            updated_summary = recalculate_and_summarize(last_item, self.pricing)
            return StateMachineResult(
                message=sure_added_to_anything_else(updated_summary),
                order=order,
            )

        return None

    def handle_all_early_patterns(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Try all early pattern handlers in sequence.

        Convenience method that tries each pattern handler in order:
        1. "make it N" quantity changes
        2. Modifier quantity changes
        3. Add modifier / pure modifier input

        Args:
            user_input: Raw user input string.
            order: Current order state.

        Returns:
            StateMachineResult if any pattern matched, None otherwise.
        """
        # 1. Check for "make it 2" pattern
        result = self.handle_make_it_n(user_input, order)
        if result:
            return result

        # 2. Check for modifier change requests like "make 2 vanilla syrups"
        result = self.handle_modifier_change_request(user_input, order)
        if result:
            return result

        # 3. Check for "add [modifier]" patterns
        result = self.handle_early_modifier_input(user_input, order)
        if result:
            return result

        return None
