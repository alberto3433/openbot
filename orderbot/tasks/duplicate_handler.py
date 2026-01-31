"""
Duplicate Handler Module.

Handles duplicate/repeat item logic including:
- "another one" / "one more" requests
- "make it 2" pattern
- "same thing" clarification
- Duplicate all items
- Repeat order requests

Extracted from taking_items_handler.py for better separation of concerns.
"""

import logging
from typing import Callable, TYPE_CHECKING

from orderbot.cache import menu_cache
from .pending_fields import PendingField
from .schemas import StateMachineResult
from .checkout_messages import ErrorMessages, item_added_anything_else
from .handler_utils import (
    build_item_options_list,
    build_item_selection_question,
    check_has_active_items,
    match_item_from_options,
    get_last_item,
)

if TYPE_CHECKING:
    from .models import OrderTask
    from .schemas import OpenInputResponse
    from .checkout_handler import CheckoutHandler
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
    ) -> None:
        """Initialize the duplicate handler.

        Args:
            pricing: PricingEngine for price calculations.
            checkout_handler: Handler for checkout operations (repeat order).
        """
        self.pricing = pricing
        self.checkout_handler = checkout_handler

        # Context set per-request
        self._returning_customer: dict | None = None
        self._set_repeat_info_callback: Callable[[bool, str | None], None] | None = None

    def set_context(
        self,
        ctx: "OrderContext | None" = None,
        # Legacy kwargs for backward compatibility
        returning_customer: dict | None = None,
        set_repeat_info_callback: Callable[[bool, str | None], None] | None = None,
    ) -> None:
        """Set per-request context from unified OrderContext."""
        if ctx is not None:
            self._returning_customer = ctx.returning_customer
            self._set_repeat_info_callback = ctx.set_repeat_info_callback
        else:
            self._returning_customer = returning_customer
            self._set_repeat_info_callback = set_repeat_info_callback

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
        from .parsers.deterministic import DUPLICATE_ALL_PATTERN

        pending_info = order.pending_duplicate_selection
        if not pending_info:
            order.pending_field = None
            return StateMachineResult(
                message=ErrorMessages.WHAT_CAN_I_GET,
                order=order,
            )

        items = pending_info.get("items", [])
        count = pending_info.get("count", 1)
        text = user_input.strip().lower()

        # Check for "all items" / "everything" response
        if DUPLICATE_ALL_PATTERN.match(text):
            order.pending_duplicate_selection = None
            order.pending_field = None
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
                score = 100
            # Normalized text matches item exactly
            elif normalized_text in summary_lower and len(normalized_text) == len(summary_lower):
                score = 90
            # User text is the full item name
            elif text == summary_lower:
                score = 85
            # Normalized text starts with item or item starts with normalized text
            elif summary_lower.startswith(normalized_text) or normalized_text.startswith(summary_lower):
                score = 70
            # Original text is substring of item name (but check it's not a partial match like "coke" in "diet coke")
            elif text in summary_lower:
                # Penalize if there's a more specific match possible
                # "coke" in "diet coke" should score lower than "coke" matching "coca-cola" via alias
                score = 30
            # Check for partial word matches (e.g., "bagel" matches "plain bagel toasted")
            else:
                words = text.split()
                matching_words = sum(1 for word in words if len(word) > 2 and word in summary_lower)
                if matching_words > 0:
                    score = 20 + matching_words * 5

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
            question_parts = [f"another {opt['summary']}" for opt in items]
            question = ", ".join(question_parts) + ", or all the items in your order?"
            question = "I didn't catch that. " + question[0].upper() + question[1:]
            return StateMachineResult(
                message=question,
                order=order,
            )

        # Found the item to duplicate - find it in the order and duplicate it
        order.pending_duplicate_selection = None
        order.pending_field = None

        # Find the actual item by ID
        item_to_duplicate = None
        for item in order.items.get_active_items():
            if item.id == matched_item["id"]:
                item_to_duplicate = item
                break

        if not item_to_duplicate:
            return StateMachineResult(
                message="I couldn't find that item. What else can I get you?",
                order=order,
            )

        # Duplicate the item
        item_name = item_to_duplicate.get_summary()
        for _ in range(count):
            order.items.add_item(item_to_duplicate.duplicate())

        if count == 1:
            logger.info("Added 1 more of '%s' to order (from clarification)", item_name)
            return StateMachineResult(
                message=item_added_anything_else(1, item_name),
                order=order,
            )
        else:
            logger.info("Added %d more of '%s' to order (from clarification)", count, item_name)
            return StateMachineResult(
                message=item_added_anything_else(count, item_name),
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
        from .parsers.deterministic import DUPLICATE_ALL_PATTERN

        pending_info = order.pending_same_thing_clarification
        if not pending_info:
            order.pending_field = None
            return StateMachineResult(
                message=ErrorMessages.WHAT_CAN_I_GET,
                order=order,
            )

        cart_items = pending_info.get("cart_items", [])
        text = user_input.strip().lower()

        # Check if user wants to repeat previous order
        previous_order_patterns = [
            "previous", "last order", "my order", "repeat", "the order",
            "what i had", "before", "last time"
        ]
        if any(pattern in text for pattern in previous_order_patterns):
            order.pending_same_thing_clarification = None
            order.pending_field = None
            return self.checkout_handler.handle_repeat_order(
                order,
                returning_customer=self._returning_customer,
                set_repeat_info_callback=self._set_repeat_info_callback,
            )

        # Check if user wants to duplicate all items in cart
        if DUPLICATE_ALL_PATTERN.match(text) or "all" in text or "everything" in text:
            order.pending_same_thing_clarification = None
            order.pending_field = None
            active_items = order.items.get_active_items()
            return self._duplicate_all_items(order, active_items)

        # Check if user wants to duplicate something from cart (single item case or specific item)
        cart_patterns = ["cart", "current", "another", "duplicate", "one more"]
        if any(pattern in text for pattern in cart_patterns):
            order.pending_same_thing_clarification = None
            order.pending_field = None
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
                item_options = build_item_options_list(active_items)
                order.pending_duplicate_selection = {
                    "count": 1,
                    "items": item_options,
                }
                order.pending_field = PendingField.DUPLICATE_SELECTION
                question = build_item_selection_question(item_options, "all the items")
                return StateMachineResult(
                    message=question,
                    order=order,
                )

        # Try to match user's response to one of the cart items directly
        matched_item = match_item_from_options(text, cart_items)

        if matched_item:
            order.pending_same_thing_clarification = None
            order.pending_field = None

            # Find the actual item by ID
            item_to_duplicate = None
            for item in order.items.get_active_items():
                if item.id == matched_item["id"]:
                    item_to_duplicate = item
                    break

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
            cart_option = f"another {active_items[0].get_summary()}"
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

        # Single item in cart - duplicate silently
        if len(active_items) == 1:
            last_item = get_last_item(active_items)
            last_item_name = last_item.get_summary()

            # Add copies of the last item
            for _ in range(added_count):
                order.items.add_item(last_item.duplicate())

            if added_count == 1:
                logger.info("Added 1 more of '%s' to order", last_item_name)
                return StateMachineResult(
                    message=f"I've added a second {last_item_name}. Anything else?",
                    order=order,
                )
            else:
                logger.info("Added %d more of '%s' to order", added_count, last_item_name)
                return StateMachineResult(
                    message=f"I've added {added_count} more {last_item_name}. Anything else?",
                    order=order,
                )

        # Multiple items in cart - ask which one to duplicate
        else:
            # Build the clarifying question: "Another [last], another [second-to-last], ... or all items?"
            item_options = build_item_options_list(active_items)

            # Store pending state
            order.pending_duplicate_selection = {
                "count": added_count,
                "items": item_options,
            }
            order.pending_field = PendingField.DUPLICATE_SELECTION

            # Build the question text
            question = build_item_selection_question(item_options)

            logger.info("Asking for duplicate clarification with %d items", len(active_items))
            return StateMachineResult(
                message=question,
                order=order,
            )

    def handle_repeat_order_request(
        self,
        parsed: "OpenInputResponse",
        order: "OrderTask",
    ) -> StateMachineResult | None:
        """Handle repeat order / "same thing" request.

        Args:
            parsed: The parsed open input response.
            order: The current order task.

        Returns:
            StateMachineResult if handled, None if not a repeat order request.
        """
        if not parsed.wants_repeat_order:
            return None

        active_items = order.items.get_active_items()
        has_cart_items = len(active_items) > 0
        has_previous_order = (
            self._returning_customer
            and self._returning_customer.get("last_order_items")
        )

        # Case 1: Both previous order AND items in cart - ask for clarification
        if has_previous_order and has_cart_items:
            item_options = build_item_options_list(active_items)

            order.pending_same_thing_clarification = {
                "has_previous_order": True,
                "cart_items": item_options,
            }
            order.pending_field = PendingField.SAME_THING_CLARIFICATION

            # Build the question
            if len(active_items) == 1:
                cart_option = f"another {active_items[0].get_summary()}"
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
                item_options = build_item_options_list(active_items)
                order.pending_duplicate_selection = {
                    "count": 1,
                    "items": item_options,
                }
                order.pending_field = PendingField.DUPLICATE_SELECTION
                question = build_item_selection_question(item_options)
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
                message="I've duplicated everything in your order. Anything else?",
                order=order,
            )
