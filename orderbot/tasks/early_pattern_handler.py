"""
Early Pattern Handler for Order State Machine.

This module handles early pattern detection in the taking items phase,
before LLM parsing is invoked. These patterns can be handled deterministically
for lower latency:
- "make it 2" / "make it three" (quantity changes)
- "add 3" / "add 3 more" (add more of existing cart items)
- "make 2 vanilla syrups" (modifier quantity changes)
- "add vanilla syrup" (pure modifier additions)

Extracted from taking_items_handler.py for better separation of concerns.
"""

import logging
import re
from typing import TYPE_CHECKING

from .pending_fields import PendingField

from orderbot.cache import menu_cache

from .models import OrderTask, MenuItemTask
from .schemas import StateMachineResult
from .parsers.deterministic import MAKE_IT_N_PATTERN
from .parsers.quantity_utils import parse_make_it_n_quantity
from .parsers.constants import ADD_MODIFIER_PATTERNS
from .parsers.intent_patterns import strip_conversational_fillers
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
from .utils.pricing_utils import safe_recalculate_price
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

# Pattern: "add 3", "add 5 more" - explicitly adds N more of existing cart items
# NOTE: "get N" and "give me N" are handled by MAKE_IT_N_PATTERN which sets total to N
# This pattern is for "add N" which ADDS N more (additive, not absolute)
ADD_QUANTITY_PATTERN = re.compile(
    r"^add\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
    r"(?:\s+more)?(?:\s+(?:of\s+those|of\s+them|of\s+these))?(?:\s+please)?$",
    re.IGNORECASE
)

# Word-to-number mapping for quantity parsing
_WORD_TO_NUM: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _parse_quantity(num_str: str) -> int | None:
    """Parse quantity from numeric or word string.

    Args:
        num_str: Number as digit or word (e.g., "3", "three")

    Returns:
        Integer quantity (>= 1) if valid, None otherwise.
    """
    num_str = num_str.lower().strip()
    if num_str.isdigit():
        qty = int(num_str)
        return qty if qty >= 1 else None
    return _WORD_TO_NUM.get(num_str)


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

        # Use mark_complete=False so duplicates preserve the original's status
        # This ensures incomplete items get configured after the original is done
        for _ in range(added_count):
            order.items.add_item(last_item.duplicate(mark_complete=False))

        logger.info("TAKING_ITEMS: Added %d more of '%s'", added_count, last_item_name)

        return StateMachineResult(
            message=f"Sure, that's {target_qty} total. Anything else?",
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
        input_lower = strip_conversational_fillers(user_input.lower().strip())

        # Don't treat "do you have X" questions as modifier inputs
        # These are availability inquiries, not order requests
        if re.search(r'\bdo\s+you\s+have\b', input_lower):
            return None

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

    def handle_add_quantity_to_cart(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle 'add 3' pattern to add more of existing cart items.

        When user says "add 3" (or similar):
        - 0 unique items in cart → return None (fall through to normal parsing)
        - 1 unique item type in cart → add 3 more of that item
        - 2+ unique item types → ask which item to add more of

        Args:
            user_input: Raw user input string.
            order: Current order state.

        Returns:
            StateMachineResult if pattern matched, None otherwise.
        """
        match = ADD_QUANTITY_PATTERN.match(user_input.strip())
        if not match:
            return None

        quantity = _parse_quantity(match.group(1))
        if not quantity:
            return None

        # Get unique item types currently in cart
        unique_items = self._get_unique_cart_items(order)

        if len(unique_items) == 0:
            # No items in cart - fall through to normal parsing
            return None

        if len(unique_items) == 1:
            # Single item type - add N more of it
            return self._add_copies_of_item(order, unique_items[0], quantity)

        # Multiple item types - need disambiguation
        return self._start_quantity_addition_disambiguation(order, unique_items, quantity)

    def handle_quantity_addition_disambiguation(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle user response to quantity addition disambiguation.

        Called when user is answering "Which item would you like to add N more of?"

        Args:
            user_input: User's selection (number or item name).
            order: Current order state with pending_quantity_addition set.

        Returns:
            StateMachineResult if selection resolved, None otherwise.
        """
        if order.pending_quantity_addition is None:
            return None

        quantity = order.pending_quantity_addition
        options = order.pending_item_options

        if not options:
            # Clear state and fall through
            order.pending_quantity_addition = None
            return None

        input_stripped = user_input.strip()

        # Try to match by number selection (e.g., "1", "2")
        if input_stripped.isdigit():
            selection_idx = int(input_stripped) - 1  # Convert to 0-indexed
            if 0 <= selection_idx < len(options):
                selected_option = options[selection_idx]
                return self._resolve_quantity_addition_selection(order, selected_option, quantity)

        # Try to match by item name
        input_lower = input_stripped.lower()
        for option in options:
            option_name = option.get("name", "").lower()
            if input_lower in option_name or option_name in input_lower:
                return self._resolve_quantity_addition_selection(order, option, quantity)

        # No match - re-prompt
        return self._reprompt_quantity_addition(order, quantity)

    def _get_unique_cart_items(self, order: OrderTask) -> list[MenuItemTask]:
        """Get list of unique item types in cart (by menu_item_id).

        Returns one representative item for each unique menu_item_id.

        Args:
            order: Current order state.

        Returns:
            List of MenuItemTask items, one per unique menu_item_id.
        """
        active_items = order.items.get_active_items()
        seen_ids: set[int] = set()
        unique: list[MenuItemTask] = []

        for item in active_items:
            if isinstance(item, MenuItemTask) and item.menu_item_id:
                if item.menu_item_id not in seen_ids:
                    seen_ids.add(item.menu_item_id)
                    unique.append(item)

        return unique

    def _add_copies_of_item(
        self,
        order: OrderTask,
        template_item: MenuItemTask,
        quantity: int,
    ) -> StateMachineResult:
        """Add N copies of an existing item to the cart.

        Args:
            order: Current order state.
            template_item: Item to duplicate.
            quantity: Number of copies to add.

        Returns:
            StateMachineResult confirming the addition.
        """
        # Clone the item N times (preserving all attributes/modifiers)
        for _ in range(quantity):
            new_item = template_item.duplicate(mark_complete=True)
            order.items.items.append(new_item)

            # Recalculate pricing for the new item
            safe_recalculate_price(self.pricing, new_item, "for duplicated item")

        total_qty = sum(
            1 for it in order.items.get_active_items()
            if it.menu_item_name == template_item.menu_item_name
        )
        return StateMachineResult(
            message=f"Sure, that's {total_qty} total. Anything else?",
            order=order,
        )

    def _start_quantity_addition_disambiguation(
        self,
        order: OrderTask,
        items: list[MenuItemTask],
        quantity: int,
    ) -> StateMachineResult:
        """Start disambiguation flow when multiple item types exist.

        Args:
            order: Current order state.
            items: List of unique items to choose from.
            quantity: How many to add after selection.

        Returns:
            StateMachineResult with disambiguation question.
        """
        # Store pending state for disambiguation
        order.pending_quantity_addition = quantity
        order.pending_item_options = [
            {"id": item.id, "name": item.get_display_name(), "menu_item_id": item.menu_item_id}
            for item in items
        ]
        order.pending_field = PendingField.QUANTITY_ADDITION_SELECTION

        # Build disambiguation message
        options_text = "\n".join(
            f"{i + 1}. {opt['name']}"
            for i, opt in enumerate(order.pending_item_options)
        )
        return StateMachineResult(
            message=f"Which item would you like to add {quantity} more of?\n{options_text}",
            order=order,
        )

    def _resolve_quantity_addition_selection(
        self,
        order: OrderTask,
        selected_option: dict,
        quantity: int,
    ) -> StateMachineResult:
        """Resolve a quantity addition disambiguation selection.

        Args:
            order: Current order state.
            selected_option: The selected option dict with id and name.
            quantity: How many to add.

        Returns:
            StateMachineResult confirming the addition.
        """
        # Clear pending state
        order.pending_quantity_addition = None
        order.pending_item_options = []
        order.pending_field = None

        # Find the template item by menu_item_id
        menu_item_id = selected_option.get("menu_item_id")
        template_item = None
        for item in order.items.get_active_items():
            if isinstance(item, MenuItemTask) and item.menu_item_id == menu_item_id:
                template_item = item
                break

        if not template_item:
            # Fallback: try to find by item id
            item_id = selected_option.get("id")
            template_item = order.items.get_item_by_id(item_id)

        if not template_item or not isinstance(template_item, MenuItemTask):
            return StateMachineResult(
                message="Sorry, I couldn't find that item. What else can I get for you?",
                order=order,
            )

        return self._add_copies_of_item(order, template_item, quantity)

    def _reprompt_quantity_addition(
        self,
        order: OrderTask,
        quantity: int,
    ) -> StateMachineResult:
        """Re-prompt for quantity addition selection.

        Args:
            order: Current order state (with options already set).
            quantity: How many to add.

        Returns:
            StateMachineResult with disambiguation question.
        """
        options = order.pending_item_options
        options_text = "\n".join(
            f"{i + 1}. {opt['name']}"
            for i, opt in enumerate(options)
        )
        return StateMachineResult(
            message=f"Sorry, I didn't catch that. Which item would you like {quantity} more of?\n{options_text}",
            order=order,
        )

    def handle_all_early_patterns(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Try all early pattern handlers in sequence.

        Convenience method that tries each pattern handler in order:
        1. Quantity addition disambiguation response (if pending)
        2. "make it N" quantity changes
        3. "add N" / "add N more" to add more of existing cart items
        4. Modifier quantity changes
        5. Add modifier / pure modifier input

        Args:
            user_input: Raw user input string.
            order: Current order state.

        Returns:
            StateMachineResult if any pattern matched, None otherwise.
        """
        # 1. Check for pending quantity addition disambiguation
        if order.pending_quantity_addition is not None:
            result = self.handle_quantity_addition_disambiguation(user_input, order)
            if result:
                return result

        # 2. Check for "make it 2" pattern
        result = self.handle_make_it_n(user_input, order)
        if result:
            return result

        # 3. Check for "add N" / "add N more" pattern
        result = self.handle_add_quantity_to_cart(user_input, order)
        if result:
            return result

        # 4. Check for modifier change requests like "make 2 vanilla syrups"
        result = self.handle_modifier_change_request(user_input, order)
        if result:
            return result

        # 5. Check for "add [modifier]" patterns
        result = self.handle_early_modifier_input(user_input, order)
        if result:
            return result

        return None
