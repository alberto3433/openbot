"""
Configuration Helper Handler for Order State Machine.

This module handles configuration-related helper operations including
cancellation during config, change clarifications, modifier changes,
and side choice handling.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import re
from typing import Callable, Optional, TYPE_CHECKING

from .models import OrderTask, MenuItemTask, ItemTask
from .schemas import OrderPhase, StateMachineResult
from .parsers import parse_side_choice

if TYPE_CHECKING:
    from .modifier_change_handler import ModifierChangeHandler

logger = logging.getLogger(__name__)

# Pattern to detect cancel/remove requests during configuration
CANCEL_ITEM_PATTERN = re.compile(
    r"^(?:(?:can\s+you\s+)?(?:please\s+)?)?(?:remove|cancel|delete|take\s+off|get\s+rid\s+of|forget|nevermind|never\s+mind)"
    r"(?:\s+(?:the|my|that|this))?\s*(.+?)(?:\s+please)?$",
    re.IGNORECASE
)


def _check_redirect_to_pending_item(
    user_input: str,
    item: "ItemTask",
    order: OrderTask,
    question: str,
    valid_answers: set[str] | None = None,
) -> StateMachineResult | None:
    """
    Check if user input looks like a new order attempt rather than an answer.

    If it looks like a new order attempt (e.g., "can I also get a latte"),
    return a redirect message asking them to answer the current question first.

    Returns None if input appears to be a valid answer to the current question.
    """
    # Import here to avoid circular dependency
    from .state_machine import _looks_like_new_order_attempt

    # If it's in the valid answers set, don't redirect
    if valid_answers:
        user_lower = user_input.lower().strip()
        for valid in valid_answers:
            if valid in user_lower:
                return None

    # Check if it looks like a new order attempt
    if _looks_like_new_order_attempt(user_input):
        return StateMachineResult(
            message=f"Let me just finish up with this item first. {question}",
            order=order,
        )

    return None


class ConfigHelperHandler:
    """
    Handles configuration helper operations.

    Manages cancellation during config, change clarifications,
    modifier changes, and side choice handling.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        modifier_change_handler: "ModifierChangeHandler | None" = None,
        get_next_question: Callable[[OrderTask], StateMachineResult] | None = None,
    ):
        """
        Initialize the config helper handler.

        Args:
            model: LLM model to use for parsing.
            modifier_change_handler: Handler for modifier changes.
            get_next_question: Callback to get next question.
        """
        self.model = model
        self.modifier_change_handler = modifier_change_handler
        self._get_next_question = get_next_question

    def check_cancellation_during_config(
        self,
        user_input: str,
        current_item: MenuItemTask,
        order: OrderTask,
    ) -> Optional[StateMachineResult]:
        """
        Check if user wants to cancel/remove items while in configuration phase.

        This allows users to say things like "remove the coffee" or "cancel this"
        while they're being asked for coffee size, instead of being forced to answer.

        Returns StateMachineResult if cancellation handled, None otherwise.
        """
        cancel_match = CANCEL_ITEM_PATTERN.match(user_input.strip())
        if not cancel_match:
            return None

        # Extract what they want to cancel from any of the capture groups
        cancel_desc = None
        for group in cancel_match.groups():
            if group:
                cancel_desc = group.strip().lower()
                break

        if not cancel_desc:
            return None

        logger.info("Cancel request during config: '%s'", cancel_desc)

        # Handle "this" or "it" - cancel the current item being configured
        if cancel_desc in ("this", "it", "that", "this one", "that one"):
            item_name = current_item.get_summary()
            current_item.mark_skipped()
            order.clear_pending()
            order.phase = OrderPhase.TAKING_ITEMS.value
            remaining = order.items.get_active_items()
            if remaining:
                return StateMachineResult(
                    message=f"OK, I've removed the {item_name}. Anything else?",
                    order=order,
                )
            else:
                return StateMachineResult(
                    message=f"OK, I've removed the {item_name}. What would you like to order?",
                    order=order,
                )

        # Get all active items to search through
        active_items = order.items.get_active_items()
        if not active_items:
            order.clear_pending()
            return StateMachineResult(
                message="There's nothing in your order yet. What can I get for you?",
                order=order,
            )

        # Check if this is a plural removal (e.g., "coffees", "bagels")
        # If plural, we remove ALL matching items
        is_plural = cancel_desc.endswith('s') and len(cancel_desc) > 2
        singular_desc = cancel_desc[:-1] if is_plural else cancel_desc

        # Find matching items
        items_to_remove = []
        for item in active_items:
            item_summary = item.get_summary().lower()
            item_name = getattr(item, 'menu_item_name', '') or ''
            item_name_lower = item_name.lower()
            item_type = getattr(item, 'item_type', '') or ''

            # Check for matches - be careful with empty strings
            matches = False
            if cancel_desc in item_summary:
                matches = True
            elif singular_desc in item_summary:
                matches = True
            elif item_name_lower and cancel_desc in item_name_lower:
                matches = True
            elif item_name_lower and singular_desc in item_name_lower:
                matches = True
            elif item_name_lower and item_name_lower in cancel_desc:
                matches = True
            # Check item_type for things like "coffee" -> matches item_type="coffee"
            elif item_type and (cancel_desc == item_type or singular_desc == item_type):
                matches = True
            elif any(word in item_summary for word in cancel_desc.split() if word):
                matches = True

            if matches:
                items_to_remove.append(item)
                # If not plural, only remove one item
                if not is_plural:
                    break

        if items_to_remove:
            # Remove the items
            removed_names = []
            for item in items_to_remove:
                removed_names.append(item.get_summary())
                idx = order.items.items.index(item)
                order.items.remove_item(idx)

            # Clear pending state since we're leaving config phase
            order.clear_pending()
            order.phase = OrderPhase.TAKING_ITEMS.value

            # Build response message
            remaining = order.items.get_active_items()
            if len(removed_names) == 1:
                removed_str = f"the {removed_names[0]}"
            else:
                removed_str = f"the {len(removed_names)} {singular_desc}s"

            logger.info("Removed %d item(s) during config: %s", len(removed_names), removed_names)

            if remaining:
                return StateMachineResult(
                    message=f"OK, I've removed {removed_str}. Anything else?",
                    order=order,
                )
            else:
                return StateMachineResult(
                    message=f"OK, I've removed {removed_str}. What would you like to order?",
                    order=order,
                )
        else:
            # Couldn't find a matching item
            return StateMachineResult(
                message=f"I couldn't find {cancel_desc} in your order. What would you like to do?",
                order=order,
            )

    def get_current_config_question(
        self,
        order: OrderTask,
        item: ItemTask,
    ) -> str | None:
        """Get the current configuration question being asked."""
        field = order.pending_field
        if field == "toasted":
            return "Would you like that toasted?"
        elif field == "spread":
            return "What would you like on it?"
        elif field == "bagel_choice":
            return "What kind of bagel would you like?"
        elif field == "coffee_size":
            return "What size would you like?"
        elif field == "coffee_style":
            return "Would you like that hot or iced?"
        elif field == "cheese_choice":
            return "What kind of cheese would you like?"
        elif field == "side_choice":
            return "Would you like a bagel or fruit salad with it?"
        return None

    def handle_change_clarification_response(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """
        Handle user response to a change clarification question.

        Returns StateMachineResult if handled, None if response wasn't understood.
        """
        clarification = order.pending_change_clarification
        if not clarification:
            return None

        if not self.modifier_change_handler:
            return None

        # Try to resolve the clarification
        category, error = self.modifier_change_handler.resolve_clarification(
            clarification, user_input
        )

        if category is None:
            # Couldn't understand the response
            logger.info("CHANGE CLARIFICATION: Couldn't understand response '%s'", user_input)
            return StateMachineResult(
                message=error or "I didn't catch that. Would you like to change the bagel type or the cream cheese?",
                order=order,
            )

        # Clear the pending clarification
        order.pending_change_clarification = None

        # Apply the change
        item_id = clarification.get("item_id")
        new_value = clarification.get("new_value", "")

        result = self.modifier_change_handler.apply_change(
            order=order,
            item_id=item_id,
            category=category,
            new_value=new_value,
        )

        if result.success:
            msg = f"{result.message} Anything else?"
            return StateMachineResult(message=msg, order=order)
        else:
            return StateMachineResult(message=result.message, order=order)

    def handle_modifier_change_request(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """
        Handle a modifier change request when not mid-configuration.

        Returns StateMachineResult if handled, None otherwise.
        """
        if not self.modifier_change_handler:
            return None

        change_request = self.modifier_change_handler.detect_change_request(user_input)
        if not change_request:
            return None

        logger.info(
            "CHANGE REQUEST: Detected: target=%s, new_value=%s, ambiguous=%s",
            change_request.target,
            change_request.new_value,
            change_request.is_ambiguous,
        )

        # If ambiguous, ask for clarification
        if change_request.is_ambiguous:
            # Find the target item
            active_items = order.items.get_active_items()
            item_id = active_items[-1].id if active_items else None

            # Store clarification state
            order.pending_change_clarification = {
                "new_value": change_request.new_value,
                "possible_categories": [c.value for c in change_request.possible_categories],
                "item_id": item_id,
            }

            msg = self.modifier_change_handler.generate_clarification_message(change_request)
            return StateMachineResult(message=msg, order=order)

        # Unambiguous - apply the change directly
        if change_request.possible_categories:
            category = change_request.possible_categories[0]

            # Find target item
            active_items = order.items.get_active_items()
            if not active_items:
                return StateMachineResult(
                    message="I don't see any items to change. What would you like to order?",
                    order=order,
                )

            result = self.modifier_change_handler.apply_change(
                order=order,
                item_id=None,  # Last item
                category=category,
                new_value=change_request.new_value,
            )

            if result.success:
                msg = f"{result.message} Anything else?"
                return StateMachineResult(message=msg, order=order)
            else:
                return StateMachineResult(message=result.message, order=order)

        return None

    def handle_side_choice(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle side choice for omelette - uses constrained parser."""
        # "bagel" and "fruit salad" are valid answers, not new order attempts
        redirect = _check_redirect_to_pending_item(
            user_input, item, order, "Would you like a bagel or fruit salad with it?",
            valid_answers={"bagel", "fruit", "fruit salad"}
        )
        if redirect:
            return redirect

        # This parser can ONLY return side choice - no new items possible!
        parsed = parse_side_choice(user_input, item.menu_item_name, model=self.model)

        if parsed.wants_cancel:
            item.mark_skipped()
            order.clear_pending()
            order.phase = OrderPhase.TAKING_ITEMS.value
            return StateMachineResult(
                message="No problem, I've removed that. Anything else?",
                order=order,
            )

        if parsed.choice == "unclear":
            return StateMachineResult(
                message=f"Would you like a bagel or fruit salad with your {item.menu_item_name}?",
                order=order,
            )

        # Apply the choice
        item.side_choice = parsed.choice

        if parsed.choice == "bagel":
            if parsed.bagel_type:
                # User specified bagel type upfront (e.g., "plain bagel")
                # Set bagel_choice but don't mark complete - still need toasted/spread questions
                item.bagel_choice = parsed.bagel_type

                # Also apply toasted if specified (e.g., "plain bagel toasted")
                if parsed.toasted is not None:
                    item.toasted = parsed.toasted

                # Also apply spread if specified (e.g., "with cream cheese")
                # Note: spread price will be calculated by bagel_config_handler when spread is set
                if parsed.spread:
                    item.spread = parsed.spread

                order.clear_pending()
                # Continue to ask remaining questions via configure_next_incomplete_bagel
                # This will handle toasted, spread, and pricing
                if self._get_next_question:
                    return self._get_next_question(order)
                # Fallback: ask about toasted if not specified, otherwise spread
                if item.toasted is None:
                    order.pending_field = "toasted"
                    return StateMachineResult(
                        message=f"Ok, {parsed.bagel_type} bagel. Would you like that toasted?",
                        order=order,
                    )
                elif item.spread is None:
                    order.pending_field = "spread"
                    toasted_desc = " toasted" if item.toasted else ""
                    return StateMachineResult(
                        message=f"Ok, {parsed.bagel_type} bagel{toasted_desc}. Would you like butter or cream cheese on that?",
                        order=order,
                    )
                else:
                    # All fields filled - mark complete
                    item.mark_complete()
                    return StateMachineResult(
                        message="Got it. Anything else?",
                        order=order,
                    )
            else:
                # Need to ask for bagel type
                order.pending_field = "bagel_choice"
                return StateMachineResult(
                    message="What kind of bagel would you like?",
                    order=order,
                )
        else:
            # Fruit salad - omelette is complete
            order.clear_pending()
            item.mark_complete()
            if self._get_next_question:
                return self._get_next_question(order)
            return StateMachineResult(
                message="Got it. Anything else?",
                order=order,
            )
