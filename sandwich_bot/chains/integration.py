"""
Integration helpers for using the state machine with existing endpoints.

This module provides ready-to-use functions that can be called from
the VAPI and chat endpoints to process messages through the state machine.
"""

import logging
from typing import Any, Dict, List, Tuple

from sandwich_bot.tasks.state_machine_adapter import (
    process_message_with_state_machine,
)

logger = logging.getLogger(__name__)


def process_voice_message(
    user_message: str,
    order_state: Dict[str, Any],
    history: List[Dict[str, str]],
    session_id: str,
    menu_index: Dict[str, Any] = None,
    store_info: Dict[str, Any] = None,
    returning_customer: Dict[str, Any] = None,
) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    """
    Process a voice message using the state machine.

    Args:
        user_message: The transcribed voice message
        order_state: Current order state dict
        history: Conversation history
        session_id: Session identifier
        menu_index: Menu data for pricing
        store_info: Store information
        returning_customer: Returning customer data if available

    Returns:
        Tuple of (reply, updated_order_state, actions)
    """
    logger.info("Using state machine for voice message")
    return process_message_with_state_machine(
        user_message=user_message,
        order_state_dict=order_state,
        history=history,
        session_id=session_id,
        menu_data=menu_index,
        store_info=store_info,
        returning_customer=returning_customer,
    )


def process_chat_message(
    user_message: str,
    order_state: Dict[str, Any],
    history: List[Dict[str, str]],
    session_id: str,
    menu_index: Dict[str, Any] = None,
    store_info: Dict[str, Any] = None,
    returning_customer: Dict[str, Any] = None,
) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    """
    Process a chat message using the state machine.

    Same as process_voice_message but for web chat endpoints.
    """
    return process_voice_message(
        user_message=user_message,
        order_state=order_state,
        history=history,
        session_id=session_id,
        menu_index=menu_index,
        store_info=store_info,
        returning_customer=returning_customer,
    )
