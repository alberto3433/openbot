"""
Change Handler for Order State Machine.

Handles modifier change requests and clarifications during the ordering flow.
This includes "make it iced", "change the milk", and resolving ambiguous changes.

Extracted from config_helper_handler.py for better separation of concerns.
"""

import logging
import re
from typing import TYPE_CHECKING

from .models import OrderTask, MenuItemTask
from .models.pending_states import PendingChangeClarification
from .schemas import StateMachineResult
from .handler_utils import get_last_item
from orderbot.cache import menu_cache
from .utils.text import normalize_text, name_with_prefix
from .pending_fields import UNKNOWN_ATTRIBUTE_SLUG

if TYPE_CHECKING:
    from .modifier_change_handler import ModifierChangeHandler

logger = logging.getLogger(__name__)

# Pattern to detect weight/quantity specifications like "2 pounds", "half pound", "1/2 lb"
WEIGHT_QUANTITY_PATTERN = re.compile(
    r"""^(?:
        (?:a\s+)?half\s+(?:a\s+)?(?:pound|lb)s?     # half pound, a half pound
        |\d+(?:\s*/\s*\d+)?\s*(?:pound|lb)s?        # 2 pounds, 1/4 lb
        |(?:a\s+)?quarter\s+(?:pound|lb)s?          # quarter pound
        |a\s+(?:pound|lb)                           # a pound
    )$""",
    re.IGNORECASE | re.VERBOSE
)


class ConfigChangeHandler:
    """
    Handles modifier change requests and clarifications.

    Manages:
    - Change clarification responses ("the milk or the sweetener?")
    - Modifier change detection and application
    """

    def __init__(
        self,
        modifier_change_handler: "ModifierChangeHandler | None" = None,
    ):
        """
        Initialize the change handler.

        Args:
            modifier_change_handler: Handler for modifier changes.
        """
        self.modifier_change_handler = modifier_change_handler

    def handle_change_clarification_response(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """
        Handle user response to a change clarification question.

        When a change request is ambiguous (e.g., "change it to vanilla" could mean
        syrup or milk), we ask the user to clarify. This method handles their response.

        Returns StateMachineResult if handled, None if response wasn't understood.
        """
        clarification = order.pending_change_clarification
        if not clarification:
            return None

        if not self.modifier_change_handler:
            return None

        # Try to resolve the clarification
        attr_slug, error = self.modifier_change_handler.resolve_clarification(
            clarification, user_input
        )

        if attr_slug is None:
            # Couldn't understand the response
            logger.info("CHANGE CLARIFICATION: Couldn't understand response '%s'", user_input)
            # Build a generic clarification message from the possible attributes
            possible_attrs = clarification.possible_attributes
            if possible_attrs and len(possible_attrs) >= 2:
                # Format: "Would you like to change the X or the Y?"
                attr_names = [a.replace("_", " ") for a in possible_attrs]
                fallback_msg = f"I didn't catch that. Would you like to change the {attr_names[0]} or the {attr_names[1]}?"
            else:
                fallback_msg = "I didn't catch that. Which part would you like to change?"
            return StateMachineResult(
                message=error or fallback_msg,
                order=order,
            )

        # Clear the pending clarification
        order.pending_change_clarification = None

        # Apply the change
        item_id = clarification.item_id
        new_value = clarification.new_value
        target = clarification.target

        result = self.modifier_change_handler.apply_change(
            order=order,
            item_id=item_id,
            attr_slug=attr_slug,
            new_value=new_value,
            target=target,
        )

        if result.success:
            # Don't append "Anything else?" if message already ends with it
            msg = result.message
            if not msg.rstrip().endswith("Anything else?"):
                msg = f"{msg} Anything else?"
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

        Detects patterns like:
        - "make it iced"
        - "change the milk to oat"
        - "actually, make it a large"

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
            last_item = get_last_item(active_items)
            item_id = last_item.id if last_item else None

            # Store clarification state
            order.pending_change_clarification = PendingChangeClarification(
                new_value=change_request.new_value,
                possible_attributes=list(change_request.possible_attributes),
                item_id=item_id,
                target=change_request.target,
            )

            msg = self.modifier_change_handler.generate_clarification_message(change_request)
            return StateMachineResult(message=msg, order=order)

        # Unambiguous - apply the change directly
        if change_request.possible_attributes:
            attr_slug = change_request.possible_attributes[0]
            resolved_new_value = change_request.new_value  # May be updated if weight resolved

            # Find target item
            active_items = order.items.get_active_items()

            # If "unknown" modifier, check if it's a weight/quantity update for last item
            if attr_slug == UNKNOWN_ATTRIBUTE_SLUG:
                # Check if value looks like a weight specification (e.g., "2 pounds", "half lb")
                new_value_lower = normalize_text(change_request.new_value)
                if WEIGHT_QUANTITY_PATTERN.match(new_value_lower):
                    # Check if last item has a priced attribute (like "weight")
                    last_item = get_last_item(active_items)
                    if last_item and isinstance(last_item, MenuItemTask) and last_item.menu_item_type:
                        priced_attr = menu_cache.get_first_priced_attribute(last_item.menu_item_type)
                        if priced_attr:
                            # Direct lookup - aliases in DB handle variations like "pound" -> "1 lb"
                            option = menu_cache.resolve_option_by_alias(priced_attr, new_value_lower)
                            if option:
                                # This is a valid weight update - use the priced attribute
                                # and the resolved option slug for proper normalization
                                attr_slug = priced_attr
                                resolved_new_value = option.get("slug", change_request.new_value)
                                logger.info(
                                    "CHANGE REQUEST: '%s' resolved to %s=%s via alias for item type %s",
                                    change_request.new_value, priced_attr,
                                    resolved_new_value, last_item.menu_item_type
                                )

                # If still unknown, check if it's actually a menu item replacement
                if attr_slug == UNKNOWN_ATTRIBUTE_SLUG:
                    from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic
                    parsed = parse_open_input_deterministic(change_request.new_value)
                    if parsed and parsed.parsed_items:
                        # This is a menu item, not a modifier - defer to normal parsing
                        logger.info(
                            "CHANGE REQUEST: '%s' is a menu item, deferring to item replacement flow",
                            change_request.new_value
                        )
                        return None

                # If still unknown after all resolution, give a friendly message
                if attr_slug == UNKNOWN_ATTRIBUTE_SLUG:
                    last_item = get_last_item(active_items)
                    item_name = last_item.menu_item_name if last_item else "that item"
                    return StateMachineResult(
                        message=f"I'm not sure how to change {name_with_prefix('the', item_name)} that way. Could you tell me what you'd like instead?",
                        order=order,
                    )
            if not active_items:
                return StateMachineResult(
                    message="I don't see any items to change. What would you like to order?",
                    order=order,
                )

            result = self.modifier_change_handler.apply_change(
                order=order,
                item_id=None,  # Last item
                attr_slug=attr_slug,
                new_value=resolved_new_value,
                target=change_request.target,
            )

            if result.success:
                # Don't append "Anything else?" if message already ends with it
                msg = result.message
                if not msg.rstrip().endswith("Anything else?"):
                    msg = f"{msg} Anything else?"
                return StateMachineResult(message=msg, order=order)
            else:
                return StateMachineResult(message=result.message, order=order)

        return None
