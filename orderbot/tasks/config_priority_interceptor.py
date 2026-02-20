"""
Priority Interceptor for Configuring Item Handler.

Handles priority-level intercepts during item configuration:
- Done ordering / checkout requests
- Cancellation requests
- Quantity change requests ("make it two")
- "Another item" / "one more" requests
- "The same" / repeat order patterns

These run first because they change the overall order flow
(finishing, cancelling, or duplicating) rather than modifying the current item.
"""

import logging
import re
from typing import TYPE_CHECKING

from .models import OrderTask, MenuItemTask, TaskStatus
from .normalization import singularize
from .schemas import StateMachineResult
from .parsers.intent_patterns import (
    ANOTHER_ITEM_PATTERN, ONE_MORE_PATTERN, MAKE_IT_N_CONFIG_PATTERN,
    DONE_ORDERING_DURING_CONFIG_PATTERN, strip_conversational_fillers,
)
from .parsers.constants import REPEAT_ORDER_PATTERNS
from .parsers.quantity_utils import parse_make_it_n_quantity
from .utils.pricing_utils import safe_recalculate_price

if TYPE_CHECKING:
    from .config_helper_handler import ConfigHelperHandler
    from .checkout_utils_handler import CheckoutUtilsHandler
    from .modifier_change_handler import ModifierChangeHandler
    from .modifier_addition_handler import ModifierAdditionHandler

logger = logging.getLogger(__name__)


class ConfigPriorityInterceptor:
    """Handles priority intercepts during item configuration.

    Priority intercepts include done-ordering, cancellation, quantity changes,
    and "another item" requests. They run before modification and fallback checks.
    """

    def __init__(
        self,
        config_helper_handler: "ConfigHelperHandler",
        checkout_utils_handler: "CheckoutUtilsHandler",
        modifier_change_handler: "ModifierChangeHandler",
        modifier_addition_handler: "ModifierAdditionHandler",
        get_current_config_result_fn=None,
    ) -> None:
        """Initialize the priority interceptor.

        Args:
            config_helper_handler: Handler for config helpers (cancellation, questions).
            checkout_utils_handler: Handler for checkout utilities.
            modifier_change_handler: Handler for modifier changes (used for pricing).
            modifier_addition_handler: Handler for adding items during config.
            get_current_config_result_fn: Callback to get current config result with quick_replies.
        """
        self.config_helper_handler = config_helper_handler
        self.checkout_utils_handler = checkout_utils_handler
        self.modifier_change_handler = modifier_change_handler
        self.modifier_addition_handler = modifier_addition_handler
        self._get_current_config_result_fn = get_current_config_result_fn

    def check_priority_intercepts(
        self, user_input: str, item, order: OrderTask
    ) -> StateMachineResult | None:
        """Check for priority intercepts: done ordering, cancellation, quantity change, another item.

        These checks run first because they change the overall order flow
        (finishing, cancelling, or duplicating) rather than modifying the current item.
        """
        # Check for "finish my order" / "checkout" during config FIRST.
        # Must run before cancellation and valid-answer checks to prevent
        # partial matches (e.g., "checkout" being interpreted as a config answer).
        done_result = self._check_done_ordering_during_config(user_input, item, order)
        if done_result:
            return done_result

        # Check for cancellation requests BEFORE routing to field-specific handlers
        # This allows "remove the coffee", "cancel this", "remove the coffees" etc. during configuration
        cancel_result = self.config_helper_handler.check_cancellation_during_config(user_input, item, order)
        if cancel_result:
            return cancel_result

        # Check for quantity change requests like "make it two hot teas"
        # This allows users to change the quantity of the item being configured
        quantity_result = self._handle_quantity_change_during_config(user_input, item, order)
        if quantity_result:
            return quantity_result

        # Check for "the same" / "I'll have the same" — duplicate the current item
        if isinstance(item, MenuItemTask) and REPEAT_ORDER_PATTERNS.match(user_input.strip()):
            item_name = item.menu_item_name or item.get_display_name()
            add_result = self.modifier_addition_handler.handle_add_item_during_config(
                item_name, item, order, require_prefix=False
            )
            if add_result:
                return add_result

        # Check for "another item" request
        # e.g., "another latte" or "one more bagel" while configuring size
        another_match = ANOTHER_ITEM_PATTERN.match(user_input)
        one_more_match = ONE_MORE_PATTERN.match(user_input)

        if another_match:
            # "another X" / "add another X" — try to add the named item to cart
            extracted_name = another_match.group(1).strip()
            if isinstance(item, MenuItemTask):
                add_result = self.modifier_addition_handler.handle_add_item_during_config(
                    extracted_name, item, order, require_prefix=False
                )
                if add_result:
                    return add_result

        if another_match or one_more_match:
            # Fallback: couldn't add item, or ONE_MORE with no name — finish current config
            item_name = item.get_display_name()
            current_question = self.config_helper_handler.get_current_config_question(order, item)
            if current_question:
                message = f"Let's finish customizing the {item_name}. {current_question}"
            else:
                message = f"Let's finish customizing the {item_name} first."
            return StateMachineResult(message=message, order=order)

        return None

    def _check_done_ordering_during_config(
        self, user_input: str, item, order: OrderTask
    ) -> StateMachineResult | None:
        """Check for explicit "finish my order" / "checkout" signals during config.

        Only matches unambiguous phrases containing order/checkout/pay language.
        Short patterns like "done" or "that's it" are intentionally NOT matched
        because they're ambiguous during configuration (could mean "done with
        this item's options").

        Args:
            user_input: Raw user input string.
            item: The current item being configured.
            order: Current order state.

        Returns:
            StateMachineResult if done-ordering detected, None otherwise.
        """
        if not DONE_ORDERING_DURING_CONFIG_PATTERN.match(user_input.strip()):
            return None

        # Guard: must have at least 1 item in the order
        if not order.items.items:
            return None

        logger.info(
            "DONE ORDERING during config: '%s' (configuring %s)",
            user_input[:50], item.get_display_name() if hasattr(item, 'get_display_name') else "item"
        )

        # Mark the current item complete with whatever attributes were already set
        if isinstance(item, MenuItemTask):
            safe_recalculate_price(
                self.modifier_change_handler.pricing if self.modifier_change_handler else None,
                item,
                "done ordering during config",
            )
        item.mark_complete()

        # Also mark any other in-progress items as complete and clear the config queue.
        # User said "finish my order" — they don't want more config questions.
        for other_item in order.items.items:
            if other_item is not item and other_item.status == TaskStatus.IN_PROGRESS:
                if isinstance(other_item, MenuItemTask):
                    safe_recalculate_price(
                        self.modifier_change_handler.pricing if self.modifier_change_handler else None,
                        other_item,
                        "done ordering during config (queued item)",
                    )
                other_item.mark_complete()
        order.pending_config_queue = []

        return self.checkout_utils_handler.transition_to_checkout(order)

    def _handle_quantity_change_during_config(
        self, user_input: str, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult | None:
        """Handle quantity change requests during item configuration.

        Detects patterns like "make it two hot teas" or "I want 3 of those"
        and duplicates the current item being configured.

        Args:
            user_input: Raw user input string.
            item: The current item being configured.
            order: Current order state.

        Returns:
            StateMachineResult if quantity change handled, None otherwise.
        """
        if not isinstance(item, MenuItemTask):
            return None

        input_stripped = strip_conversational_fillers(user_input.strip())
        # Strip mid-sentence "like" filler (e.g., "actually like make it three")
        # Can't add to MID_SENTENCE_HESITATION_FILLERS globally because "like" is
        # meaningful in "I'd like" / "I would like". Negative lookbehind protects those.
        input_stripped = re.sub(
            r"(?<!'d\s)(?<!would\s)\blike\s+", '', input_stripped, count=1, flags=re.IGNORECASE
        )
        match = MAKE_IT_N_CONFIG_PATTERN.match(input_stripped)
        if not match:
            return None

        # Extract the quantity from capture groups
        num_str = None
        matched_group_idx = None
        for i in range(1, (match.lastindex or 0) + 1):
            group = match.group(i)
            if group:
                num_str = group.lower()
                matched_group_idx = i
                break

        if not num_str or matched_group_idx is None:
            return None

        # Check for trailing text after the number (e.g., "pounds" in "make it 2 pounds").
        # If the trailing text doesn't reference the current item name, this is likely
        # an attribute answer (e.g., weight=2lb), not a quantity change request.
        trailing = input_stripped[match.end(matched_group_idx):].strip().rstrip("!.,? ")
        # Strip quantity-reference words that indicate "more of this item"
        trailing_cleaned = re.sub(
            r'^(?:of\s+(?:those|them|that)|more)\b\s*', '', trailing, flags=re.IGNORECASE
        ).strip()
        if trailing_cleaned:
            item_name_lower = item.get_display_name().lower()
            trailing_words = set(trailing_cleaned.lower().split())
            item_words = set(item_name_lower.split())
            # Add singularized forms to handle plurals (e.g., "bagels" matches "bagel")
            trailing_words_singular = trailing_words | {singularize(w) for w in trailing_words}
            if not (trailing_words_singular & item_words):
                logger.debug(
                    "QUANTITY CHANGE skipped: trailing '%s' doesn't reference item '%s', "
                    "likely an attribute answer for %s",
                    trailing_cleaned, item_name_lower, order.pending_field
                )
                return None

        target_qty = parse_make_it_n_quantity(num_str)
        if not target_qty:
            return None

        # Duplicate the current item to reach target quantity
        # Use mark_complete=False so duplicates stay IN_PROGRESS and get configured
        # after the current item is complete
        item_name = item.get_display_name()
        added_count = target_qty - 1

        for _ in range(added_count):
            order.items.add_item(item.duplicate(mark_complete=False))

        logger.info(
            "QUANTITY CHANGE during config: Added %d more of '%s' (target: %d)",
            added_count, item_name, target_qty
        )

        # Continue with the current config question, preserving quick_replies
        # for inline linkification on the frontend.
        if self._get_current_config_result_fn:
            config_result = self._get_current_config_result_fn(item, order)
        else:
            config_result = None
        if config_result:
            return StateMachineResult(
                message=f"Sure, that's {target_qty} total. {config_result.message}",
                order=config_result.order,
                quick_replies=config_result.quick_replies,
            )
        # Fallback to text-only if we can't get a full result
        current_question = self.config_helper_handler.get_current_config_question(order, item)
        suffix = current_question or "Anything else?"
        return StateMachineResult(
            message=f"Sure, that's {target_qty} total. {suffix}",
            order=order,
        )
