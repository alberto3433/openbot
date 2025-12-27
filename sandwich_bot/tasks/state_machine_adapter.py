"""
Adapter layer to bridge the OrderStateMachine with existing endpoints.

This module provides:
1. Feature flag for enabling the state machine
2. Wrapper functions that match the existing API signatures
"""

import os
import logging
from typing import Any, Dict, List, Tuple

from .state_machine import (
    OrderStateMachine,
    OrderPhase,
    StateMachineResult,
)
from .models import OrderTask
from .adapter import (
    dict_to_order_task,
    order_task_to_dict,
)

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Feature Flag
# -----------------------------------------------------------------------------

def is_state_machine_enabled() -> bool:
    """
    Check if the state machine is enabled.

    Control via environment variable:
        STATE_MACHINE_ENABLED=true|false

    Examples:
        STATE_MACHINE_ENABLED=true   - Use state machine (default)
        STATE_MACHINE_ENABLED=false  - Don't use state machine
    """
    flag_value = os.environ.get("STATE_MACHINE_ENABLED", "true").lower()
    return flag_value == "true"


# -----------------------------------------------------------------------------
# State Machine Wrapper
# -----------------------------------------------------------------------------

# Global state machine instance (lazy initialized)
_state_machine: OrderStateMachine | None = None


def get_state_machine(menu_data: Dict = None) -> OrderStateMachine:
    """
    Get or create the global OrderStateMachine instance.

    Args:
        menu_data: Optional menu data for configuration

    Returns:
        Configured OrderStateMachine instance
    """
    global _state_machine

    if _state_machine is None:
        _state_machine = OrderStateMachine(menu_data=menu_data)
        logger.info("Created new state machine instance")
    elif menu_data:
        # Update menu_data on each call to ensure fresh menu items
        _state_machine.menu_data = menu_data

    return _state_machine


def process_message_with_state_machine(
    user_message: str,
    order_state_dict: Dict[str, Any],
    history: List[Dict[str, str]],
    session_id: str = None,
    menu_data: Dict = None,
    store_info: Dict = None,
    returning_customer: Dict[str, Any] = None,
) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    """
    Process a user message using the state machine.

    This is designed to be a drop-in replacement for the other orchestrators.

    Args:
        user_message: The user's input message
        order_state_dict: Current order state in dict format
        history: Conversation history
        session_id: Session identifier
        menu_data: Menu data for pricing
        store_info: Store information (currently unused)
        returning_customer: Returning customer data (name, phone, last_order_items)

    Returns:
        Tuple of (reply, updated_order_state_dict, actions)
    """
    logger.info(
        "STATE MACHINE: Processing message '%s', menu_data has %d keys",
        user_message[:50],
        len(menu_data) if menu_data else 0,
    )

    # Convert dict state to OrderTask
    order = dict_to_order_task(order_state_dict, session_id)

    # Copy conversation history if not already present
    if not order.conversation_history and history:
        order.conversation_history = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in history
        ]

    # Get state machine and process
    sm = get_state_machine(menu_data)
    result: StateMachineResult = sm.process(
        user_input=user_message,
        order=order,
        returning_customer=returning_customer,
        store_info=store_info,
    )

    # Convert state back to dict (phase and pending fields are stored in OrderTask)
    updated_dict = order_task_to_dict(result.order)

    # Build actions list for compatibility
    actions = _infer_actions_from_result(order_state_dict, updated_dict, result)

    logger.info(
        "State machine processed message - phase: %s, pending_field: %s, complete: %s",
        result.order.phase,
        result.order.pending_field,
        result.is_complete,
    )

    return result.message, updated_dict, actions


def _infer_actions_from_result(
    old_state: Dict[str, Any],
    new_state: Dict[str, Any],
    result: StateMachineResult,
) -> List[Dict[str, Any]]:
    """
    Infer actions taken by comparing old and new state.

    This provides backward compatibility with code that expects
    discrete actions like "add_sandwich", "confirm_order", etc.
    """
    actions = []

    old_items = old_state.get("items", [])
    new_items = new_state.get("items", [])

    # Check for added items
    if len(new_items) > len(old_items):
        for i in range(len(old_items), len(new_items)):
            item = new_items[i]
            item_type = item.get("item_type", "sandwich")

            # All items are already handled by the state machine.
            # Use "conversation" intent to prevent duplicate processing by order_logic.
            # The state machine has already added the item to order_state, so we don't
            # want apply_intent_to_order_state to add another copy.
            intent = "conversation"

            actions.append({
                "intent": intent,
                "slots": {
                    "menu_item_name": item.get("menu_item_name"),
                    "quantity": item.get("quantity", 1),
                    "item_type": item_type,  # Include for debugging/logging
                }
            })

    # Check for order type change
    old_type = old_state.get("order_type")
    new_type = new_state.get("order_type")
    if new_type and new_type != old_type:
        actions.append({
            "intent": "set_order_type",
            "slots": {"order_type": new_type}
        })

    # Check for confirmation
    if result.is_complete:
        actions.append({
            "intent": "confirm_order",
            "slots": {}
        })

    # If no specific actions detected, use a generic "conversation" action
    if not actions:
        actions.append({
            "intent": "conversation",
            "slots": {}
        })

    return actions
