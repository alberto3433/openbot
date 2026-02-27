"""
Duplicate Handler Module.

Handles duplicate/repeat item logic including:
- "another one" / "one more" requests
- "make it 2" pattern
- "same thing" clarification
- Duplicate all items
- Repeat order requests
- Cart item reference duplication ("more chips")

Extracted from taking_items_handler.py for better separation of concerns.
"""

import logging
import re
from typing import Callable, TYPE_CHECKING

from orderbot.cache import menu_cache
from orderbot.cache.base import singularize
from orderbot.constants import (
    SCORE_EXACT_MATCH,
    SCORE_NORMALIZED_EXACT,
    SCORE_FULL_NAME_MATCH,
    SCORE_PREFIX_MATCH,
    SCORE_SUBSTRING_MATCH,
    SCORE_WORD_MATCH_BASE,
    SCORE_WORD_MATCH_BONUS,
)
from .models.pending_states import PendingDuplicateSelection, PendingSameThingClarification
from .pending_fields import PendingField
from .schemas import StateMachineResult
from .checkout_messages import ErrorMessages, item_added_anything_else, duplicated_order_anything_else
from .handler_utils import (
    build_item_options_list,
    build_item_selection_question,
    check_has_active_items,
    get_last_item,
)
from .item_matching import match_item_from_options
from .parsers.inquiry_patterns import (
    MODIFICATION_EXTRACTOR,
    REORDER_ITEM_PATTERNS,
)
from .parsers.deterministic import DUPLICATE_ALL_PATTERN
from .utils.text import normalize_text, name_with_prefix

if TYPE_CHECKING:
    from .models import OrderTask
    from .schemas import OpenInputResponse
    from .checkout_handler import CheckoutHandler
    from .order_history_handler import OrderHistoryHandler
    from .pricing import PricingEngine
    from .context import OrderContext

logger = logging.getLogger(__name__)

__all__ = ["DuplicateHandler"]


class DuplicateHandler:
    """
    Handler for duplicate/repeat item logic.

    Manages:
    - Duplicate selection clarification
    - "Same thing" clarification
    - Duplicate all items
    - Duplicate last item requests
    - Repeat order requests
    """

    def __init__(
        self,
        pricing: "PricingEngine | None" = None,
        checkout_handler: "CheckoutHandler | None" = None,
        order_history_handler: "OrderHistoryHandler | None" = None,
    ) -> None:
        """Initialize the duplicate handler.

        Args:
            pricing: PricingEngine for price calculations.
            checkout_handler: Handler for checkout operations (repeat order).
            order_history_handler: Handler for order history operations.
        """
        self.pricing = pricing
        self.checkout_handler = checkout_handler
        self.order_history_handler = order_history_handler

        # Context set per-request
        self._returning_customer: dict | None = None
        self._set_repeat_info_callback: Callable[[bool, str | None], None] | None = None

    def set_context(
        self,
        ctx: "OrderContext | None" = None,
    ) -> None:
        """Set per-request context from unified OrderContext."""
        if ctx is not None:
            self._returning_customer = ctx.returning_customer
            self._set_repeat_info_callback = ctx.set_repeat_info_callback

    def _setup_duplicate_disambiguation(
        self,
        order: "OrderTask",
        active_items: list,
        count: int,
        all_option_text: str = "all the items in your order",
    ) -> str:
        """Set up pending state for duplicate disambiguation and return the question.

        Args:
            order: The current order task.
            active_items: List of active items to build options from.
            count: How many copies to duplicate.
            all_option_text: Text for the "all" option in the question.

        Returns:
            The disambiguation question string.
        """
        item_options = build_item_options_list(active_items)
        order.pending_duplicate_selection = PendingDuplicateSelection(
            count=count,
            items=item_options,
        )
        order.pending_field = PendingField.DUPLICATE_SELECTION
        return build_item_selection_question(item_options, all_option_text)

    def handle_duplicate_selection(
        self,
        user_input: str,
        order: "OrderTask",
    ) -> StateMachineResult:
        """Handle user's response to duplicate clarification question.

        Called when user said "another one" with multiple items in cart,
        and we asked which item to duplicate.

        Args:
            user_input: The user's response.
            order: The current order task.

        Returns:
            StateMachineResult with appropriate message.
        """
        pending_info = order.pending_duplicate_selection
        if not pending_info:
            order.clear_pending()
            return StateMachineResult(
                message=ErrorMessages.WHAT_CAN_I_GET,
                order=order,
            )

        items = pending_info.items
        count = pending_info.count
        text = normalize_text(user_input)

        # Check for "all items" / "everything" response
        if DUPLICATE_ALL_PATTERN.match(text):
            order.pending_duplicate_selection = None
            order.clear_pending()
            active_items = order.items.get_active_items()
            return self._duplicate_all_items(order, active_items)

        # Try to match user's response to one of the item options
        # First, normalize common aliases using unified resolver (data-driven)
        resolved_name, _ = menu_cache.resolve_alias(text)
        normalized_text = (resolved_name or text).lower()

        matched_item = None
        best_match_score = 0

        for item_info in items:
            summary_lower = item_info["summary"].lower()
            score = 0

            # Exact match (highest priority)
            if normalized_text == summary_lower:
                score = SCORE_EXACT_MATCH
            # Normalized text matches item exactly
            elif normalized_text in summary_lower and len(normalized_text) == len(summary_lower):
                score = SCORE_NORMALIZED_EXACT
            # User text is the full item name
            elif text == summary_lower:
                score = SCORE_FULL_NAME_MATCH
            # Normalized text starts with item or item starts with normalized text
            elif summary_lower.startswith(normalized_text) or normalized_text.startswith(summary_lower):
                score = SCORE_PREFIX_MATCH
            # Original text is substring of item name (but check it's not a partial match like "coke" in "diet coke")
            elif text in summary_lower:
                # Penalize if there's a more specific match possible
                # "coke" in "diet coke" should score lower than "coke" matching "coca-cola" via alias
                score = SCORE_SUBSTRING_MATCH
            # Check for partial word matches (e.g., "bagel" matches "plain bagel toasted")
            else:
                words = text.split()
                matching_words = sum(1 for word in words if len(word) > 2 and word in summary_lower)
                if matching_words > 0:
                    score = SCORE_WORD_MATCH_BASE + matching_words * SCORE_WORD_MATCH_BONUS

            if score > best_match_score:
                best_match_score = score
                matched_item = item_info

        # Also check for ordinal responses: "the first one", "the second", "1", "2", etc.
        if not matched_item:
            ordinal_map = {
                "1": 0, "first": 0, "the first": 0, "the first one": 0,
                "2": 1, "second": 1, "the second": 1, "the second one": 1,
                "3": 2, "third": 2, "the third": 2, "the third one": 2,
                "4": 3, "fourth": 3, "the fourth": 3, "the fourth one": 3,
                "5": 4, "fifth": 4, "the fifth": 4, "the fifth one": 4,
            }
            for key, idx in ordinal_map.items():
                if text == key or text.startswith(key + " "):
                    if idx < len(items):
                        matched_item = items[idx]
                        break

        if not matched_item:
            # Didn't understand - repeat the question
            question_parts = [name_with_prefix("another", opt['summary']) for opt in items]
            question = ", ".join(question_parts) + ", or all the items in your order?"
            question = "I didn't catch that. " + question[0].upper() + question[1:]
            # Build quick replies from item summaries
            qr = [{"label": opt["summary"], "value": opt["summary"]} for opt in items]
            return StateMachineResult(
                message=question,
                order=order,
                quick_replies=qr,
            )

        # Found the item to duplicate - find it in the order and duplicate it
        order.pending_duplicate_selection = None
        order.clear_pending()

        # Find the actual item by ID
        item_to_duplicate = order.items.get_active_item_by_id(matched_item["id"])

        if not item_to_duplicate:
            return StateMachineResult(
                message="I couldn't find that item. What else can I get you?",
                order=order,
            )

        # Duplicate the item
        item_name = item_to_duplicate.get_summary()
        for _ in range(count):
            order.items.add_item(item_to_duplicate.duplicate())

        total_qty = sum(
            1 for it in order.items.get_active_items()
            if it.get_summary() == item_name
        )
        logger.info("Added %d more of '%s' to order (from clarification)", count, item_name)
        return StateMachineResult(
            message=f"Sure, that's {total_qty} {item_name} total. Anything else?",
            order=order,
        )

    def handle_same_thing_clarification(
        self,
        user_input: str,
        order: "OrderTask",
    ) -> StateMachineResult:
        """Handle user's response to 'same thing' clarification question.

        Called when user said "same thing" and we have both a previous order
        AND items in the current cart, so we asked which they meant.

        Args:
            user_input: The user's response.
            order: The current order task.

        Returns:
            StateMachineResult with appropriate message.
        """
        pending_info = order.pending_same_thing_clarification
        if not pending_info:
            order.pending_field = None
            return StateMachineResult(
                message=ErrorMessages.WHAT_CAN_I_GET,
                order=order,
            )

        cart_items = pending_info.cart_items
        text = normalize_text(user_input)

        # Check if user wants to repeat previous order
        previous_order_patterns = [
            "previous", "last order", "my order", "repeat", "the order",
            "what i had", "before", "last time"
        ]
        if any(pattern in text for pattern in previous_order_patterns):
            order.pending_same_thing_clarification = None
            order.clear_pending()
            return self.checkout_handler.handle_repeat_order(
                order,
                returning_customer=self._returning_customer,
                set_repeat_info_callback=self._set_repeat_info_callback,
            )

        # Check if user wants to duplicate all items in cart
        if DUPLICATE_ALL_PATTERN.match(text) or "all" in text or "everything" in text:
            order.pending_same_thing_clarification = None
            order.clear_pending()
            active_items = order.items.get_active_items()
            return self._duplicate_all_items(order, active_items)

        # Check if user wants to duplicate something from cart (single item case or specific item)
        cart_patterns = ["cart", "current", "another", "duplicate", "one more"]
        if any(pattern in text for pattern in cart_patterns):
            order.pending_same_thing_clarification = None
            order.clear_pending()
            active_items = order.items.get_active_items()

            if len(active_items) == 1:
                # Single item - duplicate it
                last_item = get_last_item(active_items)
                last_item_name = last_item.get_summary()
                order.items.add_item(last_item.duplicate())
                logger.info("'Same thing' clarified: duplicated single cart item '%s'", last_item_name)
                return StateMachineResult(
                    message=item_added_anything_else(1, last_item_name),
                    order=order,
                )
            else:
                # Multiple items - ask which one
                question = self._setup_duplicate_disambiguation(
                    order, active_items, count=1, all_option_text="all the items",
                )
                return StateMachineResult(
                    message=question,
                    order=order,
                )

        # Try to match user's response to one of the cart items directly
        matched_item = match_item_from_options(text, cart_items)

        if matched_item:
            order.pending_same_thing_clarification = None
            order.clear_pending()

            # Find the actual item by ID
            item_to_duplicate = order.items.get_active_item_by_id(matched_item["id"])

            if item_to_duplicate:
                item_name = item_to_duplicate.get_summary()
                order.items.add_item(item_to_duplicate.duplicate())
                logger.info("'Same thing' clarified: duplicated specific item '%s'", item_name)
                return StateMachineResult(
                    message=item_added_anything_else(1, item_name),
                    order=order,
                )

        # Didn't understand - repeat the question
        active_items = order.items.get_active_items()
        if len(active_items) == 1:
            cart_option = name_with_prefix("another", active_items[0].get_summary())
        else:
            cart_option = "duplicate something from your current order"

        return StateMachineResult(
            message=f"I didn't catch that. Would you like to repeat your previous order, or {cart_option}?",
            order=order,
        )

    def handle_duplicate_request(
        self,
        parsed: "OpenInputResponse",
        order: "OrderTask",
    ) -> StateMachineResult | None:
        """Handle "make it 2" / "another one" / "one more" requests.

        Args:
            parsed: The parsed open input response.
            order: The current order task.

        Returns:
            StateMachineResult if handled, None if not a duplicate request.
        """
        if parsed.duplicate_last_item <= 0:
            return None

        active_items, error_result = check_has_active_items(order)
        if error_result:
            logger.info("'Make it N' / 'another one' requested but no items in cart")
            return error_result

        added_count = parsed.duplicate_last_item

        # All items identical - duplicate silently (covers single item and N identical items)
        unique_summaries = {item.get_summary() for item in active_items}
        if len(unique_summaries) == 1:
            last_item = get_last_item(active_items)
            last_item_name = last_item.get_summary()

            # Add copies of the last item
            for _ in range(added_count):
                order.items.add_item(last_item.duplicate())

            total_qty = len(active_items) + added_count
            logger.info("Added %d more of '%s' to order", added_count, last_item_name)
            return StateMachineResult(
                message=f"Sure, that's {total_qty} total. Anything else?",
                order=order,
            )

        # Multiple different items in cart - ask which one to duplicate
        else:
            question = self._setup_duplicate_disambiguation(order, active_items, count=added_count)
            logger.info("Asking for duplicate clarification with %d items", len(active_items))
            return StateMachineResult(
                message=question,
                order=order,
            )

    def handle_duplicate_by_reference(
        self,
        parsed: "OpenInputResponse",
        order: "OrderTask",
    ) -> StateMachineResult | None:
        """Handle 'more chips' style requests by looking up cart item.

        When user says "more chips", "another bag of chips", or "make that two bags
        of chips", we try to find a matching item in the cart and duplicate it.

        Args:
            parsed: The parsed open input response.
            order: The current order task.

        Returns:
            StateMachineResult if a cart item matched, None to fall through to other handlers.
        """
        if not parsed.duplicate_by_reference:
            return None

        item_ref = parsed.duplicate_by_reference.lower()
        active_items = order.items.get_active_items()

        if not active_items:
            # No items in cart - fall through to other handlers
            # (might be a menu query after all)
            return None

        # Find cart item matching the reference (most recent first)
        # Try both original and singularized form (e.g., "bagels" -> "bagel")
        item_ref_singular = singularize(item_ref)
        ref_candidates = [item_ref] if item_ref == item_ref_singular else [item_ref, item_ref_singular]

        matched_item = None
        for item in reversed(active_items):
            item_name = item.get_display_name().lower()
            for ref in ref_candidates:
                # Use word-boundary matching to find the reference in item name
                # e.g., "chips" matches "Kettle Chips", "bagel" matches "Plain Bagel"
                if re.search(rf'\b{re.escape(ref)}\b', item_name):
                    matched_item = item
                    break
                # Also check if ref is a subset of words in item_name
                # e.g., "chips" in "Bag of Kettle Chips"
                item_words = set(item_name.split())
                ref_words = set(ref.split())
                if ref_words and ref_words.issubset(item_words):
                    matched_item = item
                    break
            if matched_item:
                break

        if not matched_item:
            # No cart item matched - fall through to other handlers
            # This allows "more options" to still trigger menu inquiry
            return None

        # Duplicate count: use duplicate_last_item if set, else 1
        count = max(parsed.duplicate_last_item, 1)
        item_name = matched_item.get_summary()

        for _ in range(count):
            order.items.add_item(matched_item.duplicate())

        logger.info("Duplicated cart item '%s' (count=%d) by reference '%s'", item_name, count, item_ref)
        return StateMachineResult(
            message=item_added_anything_else(count, item_name),
            order=order,
        )

    def handle_repeat_order_request(
        self,
        parsed: "OpenInputResponse",
        order: "OrderTask",
        raw_user_input: str | None = None,
    ) -> StateMachineResult | None:
        """Handle repeat order / "same thing" request.

        Args:
            parsed: The parsed open input response.
            order: The current order task.
            raw_user_input: Original user input (for detecting modifications).

        Returns:
            StateMachineResult if handled, None if not a repeat order request.
        """
        if not parsed.wants_repeat_order:
            return None

        # Check for modifications ("same as before but iced")
        if raw_user_input and self.order_history_handler:
            is_modified, modification_text = self.order_history_handler.is_reorder_with_modifications(raw_user_input)
            if is_modified and modification_text:
                logger.info("Repeat order with modifications detected: '%s'", modification_text)
                return self.order_history_handler.handle_reorder_with_modifications(
                    modification_text, order
                )

            # Check for specific item reorder ("just the bagel from last time")
            is_specific, item_ref = self.order_history_handler.is_reorder_specific_item(raw_user_input)
            if is_specific and item_ref:
                logger.info("Reorder specific item detected: '%s'", item_ref)
                return self.order_history_handler.handle_reorder_specific_item(item_ref, order)

        active_items = order.items.get_active_items()
        has_cart_items = len(active_items) > 0
        has_previous_order = (
            self._returning_customer
            and self._returning_customer.get("last_order_items")
        )

        # Case 1: Both previous order AND items in cart - ask for clarification
        if has_previous_order and has_cart_items:
            item_options = build_item_options_list(active_items)

            order.pending_same_thing_clarification = PendingSameThingClarification(
                has_previous_order=True,
                cart_items=item_options,
            )
            order.pending_field = PendingField.SAME_THING_CLARIFICATION

            # Build the question
            if len(active_items) == 1:
                cart_option = name_with_prefix("another", active_items[0].get_summary())
            else:
                cart_option = "duplicate something from your current order"

            logger.info("'Same thing' ambiguous: has previous order AND %d cart items", len(active_items))
            return StateMachineResult(
                message=f"Would you like to repeat your previous order, or {cart_option}?",
                order=order,
            )

        # Case 2: Only previous order (no cart items) - repeat previous order
        if has_previous_order:
            return self.checkout_handler.handle_repeat_order(
                order,
                returning_customer=self._returning_customer,
                set_repeat_info_callback=self._set_repeat_info_callback,
            )

        # Case 3: Only cart items (no previous order) - treat as duplicate
        if has_cart_items:
            # Reuse duplicate logic: single item = duplicate it, multiple = ask which one
            if len(active_items) == 1:
                last_item = get_last_item(active_items)
                last_item_name = last_item.get_summary()
                order.items.add_item(last_item.duplicate())
                logger.info("'Same thing' with single cart item: duplicated '%s'", last_item_name)
                return StateMachineResult(
                    message=item_added_anything_else(1, last_item_name),
                    order=order,
                )
            else:
                # Multiple items - ask which one to duplicate
                question = self._setup_duplicate_disambiguation(order, active_items, count=1)
                logger.info("'Same thing' with %d cart items: asking which to duplicate", len(active_items))
                return StateMachineResult(
                    message=question,
                    order=order,
                )

        # Case 4: Neither previous order nor cart items
        logger.info("'Same thing' requested but no previous order and no cart items")
        return StateMachineResult(
            message="I don't have a previous order on file for you. What can I get for you today?",
            order=order,
        )

    def handle_wants_duplicate_all(
        self,
        parsed: "OpenInputResponse",
        order: "OrderTask",
    ) -> StateMachineResult | None:
        """Handle "all items" duplicate request.

        Args:
            parsed: The parsed open input response.
            order: The current order task.

        Returns:
            StateMachineResult if handled, None otherwise.
        """
        if not parsed.wants_duplicate_all:
            return None

        active_items, error_result = check_has_active_items(order)
        if error_result:
            return error_result
        return self._duplicate_all_items(order, active_items)

    def _duplicate_all_items(
        self,
        order: "OrderTask",
        active_items: list,
    ) -> StateMachineResult:
        """Duplicate all items in the cart, matching original quantities.

        Args:
            order: The current order task.
            active_items: List of active items to duplicate.

        Returns:
            StateMachineResult with confirmation message.
        """
        if not active_items:
            return StateMachineResult(
                message=ErrorMessages.NO_ITEMS_YET,
                order=order,
            )

        # Duplicate each item, respecting its quantity
        total_added = 0
        for item in active_items:
            qty = item.quantity
            for _ in range(qty):
                order.items.add_item(item.duplicate())
                total_added += 1

        logger.info("Duplicated all items in cart, added %d items total", total_added)

        if len(active_items) == 1:
            item_name = active_items[0].get_summary()
            return StateMachineResult(
                message=item_added_anything_else(1, item_name),
                order=order,
            )
        else:
            return StateMachineResult(
                message=duplicated_order_anything_else(),
                order=order,
            )
