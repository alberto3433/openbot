"""
Integration helpers for using the chain-based architecture with existing endpoints.

This module provides ready-to-use functions that can be called from
the VAPI and chat endpoints to process messages through the new
chain-based orchestrator.

Usage in voice_vapi.py:
    from sandwich_bot.chains.integration import process_voice_message

    # In the vapi_chat_completions endpoint, replace:
    #   llm_result = call_sandwich_bot(...)
    #   for action in actions:
    #       order_state = apply_intent_to_order_state(...)
    #
    # With:
    #   reply, order_state, actions = process_voice_message(
    #       user_message=user_message,
    #       order_state=order_state,
    #       history=history,
    #       session_id=session_id,
    #       menu_index=menu_index,
    #       store_info=store_info,
    #       returning_customer=returning_customer,
    #       # Pass original LLM function for fallback
    #       llm_fallback_fn=lambda msg, state, hist: call_sandwich_bot(hist, state, menu_index, msg, ...),
    #   )
"""

import logging
from typing import Any, Dict, List, Optional, Tuple, Callable

from .adapter import (
    is_chain_orchestrator_enabled,
    process_message_with_chains,
    process_message_hybrid,
)

from sandwich_bot.tasks.adapter import (
    is_task_orchestrator_enabled,
    process_message_with_tasks,
)

from sandwich_bot.tasks.state_machine_adapter import (
    is_state_machine_enabled,
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
    llm_fallback_fn: Callable = None,
    force_chain_orchestrator: bool = False,
    force_task_orchestrator: bool = False,
    force_state_machine: bool = False,
) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    """
    Process a voice message using the appropriate system.

    Priority order:
    1. State machine (if force_state_machine or STATE_MACHINE_ENABLED)
    2. Task-based orchestrator (if force_task_orchestrator or TASK_ORCHESTRATOR_ENABLED)
    3. Chain-based orchestrator (if force_chain_orchestrator or CHAIN_ORCHESTRATOR_ENABLED)
    4. LLM fallback function

    Args:
        user_message: The transcribed voice message
        order_state: Current order state dict
        history: Conversation history
        session_id: Session identifier
        menu_index: Menu data for pricing
        store_info: Store information
        returning_customer: Returning customer data if available
        llm_fallback_fn: Function to call for LLM-based processing
        force_chain_orchestrator: Override feature flag to force chain orchestrator
        force_task_orchestrator: Override feature flag to force task orchestrator
        force_state_machine: Override feature flag to force state machine

    Returns:
        Tuple of (reply, updated_order_state, actions)
    """
    use_state_machine = force_state_machine or is_state_machine_enabled()
    use_tasks = force_task_orchestrator or is_task_orchestrator_enabled()
    use_chains = force_chain_orchestrator or is_chain_orchestrator_enabled()

    # Priority 0: State machine
    if use_state_machine:
        logger.info("Using state machine for voice message")
        try:
            return process_message_with_state_machine(
                user_message=user_message,
                order_state_dict=order_state,
                history=history,
                session_id=session_id,
                menu_data=menu_index,
                store_info=store_info,
            )
        except Exception as e:
            logger.error("State machine failed, trying fallback: %s", e)
            # Fall through to task orchestrator or LLM

    # Priority 1: Task-based orchestrator
    if use_tasks:
        logger.info("Using task-based orchestrator for voice message")
        try:
            return process_message_with_tasks(
                user_message=user_message,
                order_state_dict=order_state,
                history=history,
                session_id=session_id,
                menu_data=menu_index,
                store_info=store_info,
            )
        except Exception as e:
            logger.error("Task orchestrator failed, trying fallback: %s", e)
            # Fall through to chain orchestrator or LLM

    # Priority 2: Chain-based orchestrator
    if use_chains or (use_tasks and not llm_fallback_fn):
        logger.info("Using chain-based orchestrator for voice message")
        try:
            return process_message_with_chains(
                user_message=user_message,
                order_state_dict=order_state,
                history=history,
                session_id=session_id,
                menu_data=menu_index,
                store_info=store_info,
            )
        except Exception as e:
            logger.error("Chain orchestrator failed, falling back to LLM: %s", e)
            if llm_fallback_fn:
                return _call_llm_fallback(
                    llm_fallback_fn,
                    user_message,
                    order_state,
                    history,
                    session_id,
                    menu_index,
                    returning_customer,
                )
            raise

    # Priority 3: LLM fallback
    if llm_fallback_fn:
        logger.debug("Using LLM-based processing for voice message")
        return _call_llm_fallback(
            llm_fallback_fn,
            user_message,
            order_state,
            history,
            session_id,
            menu_index,
            returning_customer,
        )

    # No fallback available, use chains as default
    return process_message_with_chains(
        user_message=user_message,
        order_state_dict=order_state,
        history=history,
        session_id=session_id,
        menu_data=menu_index,
        store_info=store_info,
    )


def _call_llm_fallback(
    llm_fn: Callable,
    user_message: str,
    order_state: Dict[str, Any],
    history: List[Dict[str, str]],
    session_id: str,
    menu_index: Dict[str, Any],
    returning_customer: Dict[str, Any],
) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    """
    Call the LLM fallback function and format the result.

    This wraps the existing call_sandwich_bot + apply_intent_to_order_state
    pattern to return a consistent format.
    """
    # The actual LLM call would happen here via llm_fn
    # This is a placeholder that shows the expected interface
    result = llm_fn(user_message, order_state, history)

    if isinstance(result, tuple) and len(result) == 3:
        return result

    # If result is the llm_result dict format
    reply = result.get("reply", "")
    actions = result.get("actions", [])

    # Actions need to be applied to state by the caller
    return reply, order_state, actions


def process_chat_message(
    user_message: str,
    order_state: Dict[str, Any],
    history: List[Dict[str, str]],
    session_id: str,
    menu_index: Dict[str, Any] = None,
    store_info: Dict[str, Any] = None,
    returning_customer: Dict[str, Any] = None,
    llm_fallback_fn: Callable = None,
    force_task_orchestrator: bool = False,
    force_state_machine: bool = False,
) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    """
    Process a chat message using the appropriate system.

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
        llm_fallback_fn=llm_fallback_fn,
        force_task_orchestrator=force_task_orchestrator,
        force_state_machine=force_state_machine,
    )


# Example usage showing how to integrate with voice_vapi.py
INTEGRATION_EXAMPLE = """
# In sandwich_bot/voice_vapi.py, update the vapi_chat_completions function:

# At the top of the file, add:
from sandwich_bot.chains.integration import process_voice_message

# Then in the endpoint, replace this section:
#
#     llm_result = call_sandwich_bot(
#         history,
#         order_state,
#         menu_index,
#         enhanced_user_message,
#         ...
#     )
#     ...
#     for action in actions:
#         order_state = apply_intent_to_order_state(...)
#
# With:

    # Create a fallback function that wraps the existing LLM call
    def llm_fallback(msg, state, hist):
        llm_result = call_sandwich_bot(
            hist,
            state,
            menu_index,
            msg,
            include_menu_in_system=include_menu,
            returning_customer=returning_customer,
            caller_id=phone_number,
            bot_name=bot_name,
            company_name=company_name,
            db=db,
            use_dynamic_prompt=True,
        )
        return llm_result

    # Process the message through the new system
    reply, order_state, actions = process_voice_message(
        user_message=enhanced_user_message,
        order_state=order_state,
        history=history,
        session_id=session_id,
        menu_index=menu_index,
        store_info={"name": company_name, "store_id": session_store_id},
        returning_customer=returning_customer,
        llm_fallback_fn=llm_fallback,
    )

    # The rest of the code (payment link, persistence, etc.) remains the same
    # because it uses the same order_state dict format
"""
