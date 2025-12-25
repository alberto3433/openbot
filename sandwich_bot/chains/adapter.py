"""
Adapter layer to bridge the new chain-based architecture with existing endpoints.

This module provides:
1. State conversion between dict-based order_state and Pydantic OrderState
2. Feature flag for gradual rollout
3. Wrapper functions that can be used as drop-in replacements in endpoints
"""

import os
import logging
from typing import Any, Dict, List, Optional, Tuple

from .state import (
    OrderState,
    AddressState,
    BagelItem,
    BagelOrderState,
    CoffeeItem,
    CoffeeOrderState,
    CheckoutState,
    ChainName,
    ChainResult,
    OrderStatus,
)
from .orchestrator import Orchestrator
from .base import ChainRegistry
from .greeting_chain import GreetingChain
from .address_chain import AddressChain
from .bagel_chain import BagelChain
from .coffee_chain import CoffeeChain
from .checkout_chain import CheckoutChain

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Feature Flag
# -----------------------------------------------------------------------------

def is_chain_orchestrator_enabled() -> bool:
    """
    Check if the new chain-based orchestrator is enabled.

    Control via environment variable:
        CHAIN_ORCHESTRATOR_ENABLED=true|false|percentage

    Examples:
        CHAIN_ORCHESTRATOR_ENABLED=true      - Always use new system (default)
        CHAIN_ORCHESTRATOR_ENABLED=false     - Always use old system
        CHAIN_ORCHESTRATOR_ENABLED=50        - 50% of sessions use new system

    Note: When enabled, this routes to process_chat_message which then
    checks is_task_orchestrator_enabled() to decide between task-based
    and chain-based systems.
    """
    flag_value = os.environ.get("CHAIN_ORCHESTRATOR_ENABLED", "true").lower()

    if flag_value == "true":
        return True
    elif flag_value == "false":
        return False
    else:
        # Percentage-based rollout
        try:
            percentage = int(flag_value)
            import random
            return random.randint(1, 100) <= percentage
        except ValueError:
            return False


# -----------------------------------------------------------------------------
# State Conversion: Dict -> Pydantic
# -----------------------------------------------------------------------------

def dict_to_order_state(order_dict: Dict[str, Any], session_id: str = None) -> OrderState:
    """
    Convert a dict-based order state to Pydantic OrderState.

    Args:
        order_dict: The existing dict-based order state
        session_id: Optional session ID to preserve

    Returns:
        OrderState Pydantic model instance
    """
    if not order_dict:
        state = OrderState()
        if session_id:
            state.session_id = session_id
        return state

    # Convert customer info
    customer = order_dict.get("customer", {})

    # Convert address info
    order_type = order_dict.get("order_type")
    delivery_address = order_dict.get("delivery_address", "")

    address_state = AddressState(
        order_type=order_type,
        store_location_confirmed=order_type == "pickup",
    )

    # Parse delivery address if present
    if order_type == "delivery" and delivery_address:
        # Simple parsing - in production, use a proper address parser
        address_state.street = delivery_address
        address_state.is_validated = True

    # Convert bagel items
    bagel_items = []
    coffee_items = []

    for item in order_dict.get("items", []):
        item_type = item.get("item_type", "sandwich")

        if item_type in ("sandwich", "bagel"):
            bagel_item = BagelItem(
                bagel_type=item.get("bread") or item.get("menu_item_name") or "unknown",
                quantity=item.get("quantity", 1),
                toasted=item.get("toasted"),  # None if not asked, True/False if answered
                spread=item.get("cheese"),  # Map cheese to spread for bagels
                extras=item.get("toppings") or [],
                sandwich_protein=item.get("protein"),
                unit_price=item.get("unit_price", 0.0),
            )
            bagel_items.append(bagel_item)

        elif item_type == "drink":
            # Determine if it's coffee-like
            item_config = item.get("item_config") or {}
            coffee_item = CoffeeItem(
                drink_type=item.get("menu_item_name") or "coffee",
                size=item.get("size") or item_config.get("size"),
                milk=item_config.get("milk"),
                sweetener=item_config.get("sweetener"),
                sweetener_quantity=item_config.get("sweetener_quantity", 1),
                flavor_syrup=item_config.get("flavor_syrup"),
                iced="iced" in (item.get("menu_item_name") or "").lower(),
                unit_price=item.get("unit_price", 0.0),
            )
            coffee_items.append(coffee_item)

    # Restore bagel chain conversation state
    bagel_chain_data = order_dict.get("bagel_chain_state", {})
    current_bagel_item = None
    if bagel_chain_data.get("current_item"):
        current_bagel_item = BagelItem(**bagel_chain_data["current_item"])

    bagel_state = BagelOrderState(
        items=bagel_items,
        current_item=current_bagel_item,
        awaiting=bagel_chain_data.get("awaiting"),
    )

    # Restore coffee chain conversation state
    coffee_chain_data = order_dict.get("coffee_chain_state", {})
    current_coffee_item = None
    if coffee_chain_data.get("current_item"):
        current_coffee_item = CoffeeItem(**coffee_chain_data["current_item"])

    coffee_state = CoffeeOrderState(
        items=coffee_items,
        current_item=current_coffee_item,
        awaiting=coffee_chain_data.get("awaiting"),
    )

    # Convert checkout state
    checkout_data = order_dict.get("checkout_state", {})
    checkout_state = CheckoutState(
        confirmed=order_dict.get("status") == "confirmed",
        payment_method=order_dict.get("payment_method"),
        # Preserve conversation flow state
        order_reviewed=checkout_data.get("order_reviewed", False),
        awaiting=checkout_data.get("awaiting"),
        name_collected=checkout_data.get("name_collected", False),
        contact_collected=checkout_data.get("contact_collected", False),
        subtotal=checkout_data.get("subtotal", 0.0),
        city_tax=checkout_data.get("city_tax", 0.0),
        state_tax=checkout_data.get("state_tax", 0.0),
        tax=checkout_data.get("tax", 0.0),
        delivery_fee=checkout_data.get("delivery_fee", 0.0),
    )

    if order_dict.get("total_price"):
        checkout_state.total = order_dict.get("total_price", 0.0)
        checkout_state.total_calculated = True
    elif checkout_data.get("total"):
        checkout_state.total = checkout_data.get("total", 0.0)
        checkout_state.total_calculated = True

    # Determine current chain based on state
    current_chain = _infer_current_chain(order_dict)

    # Map status
    status_map = {
        "pending": OrderStatus.IN_PROGRESS,
        "collecting_items": OrderStatus.IN_PROGRESS,
        "building": OrderStatus.IN_PROGRESS,
        "confirmed": OrderStatus.CONFIRMED,
        "cancelled": OrderStatus.CANCELLED,
    }
    status = status_map.get(order_dict.get("status", "pending"), OrderStatus.IN_PROGRESS)

    # Build the OrderState
    state = OrderState(
        customer_name=customer.get("name"),
        customer_phone=customer.get("phone"),
        customer_email=customer.get("email"),
        address=address_state,
        bagels=bagel_state,
        coffee=coffee_state,
        checkout=checkout_state,
        current_chain=current_chain,
        status=status,
        pending_coffee=order_dict.get("pending_coffee", False),
    )

    if session_id:
        state.session_id = session_id

    return state


def _infer_current_chain(order_dict: Dict[str, Any]) -> ChainName:
    """Infer the current chain based on the order state."""
    # First check if we have a preserved current_chain value
    if order_dict.get("current_chain"):
        try:
            return ChainName(order_dict["current_chain"])
        except ValueError:
            pass  # Fall through to inference

    status = order_dict.get("status", "pending")
    order_type = order_dict.get("order_type")
    items = order_dict.get("items", [])
    checkout_state = order_dict.get("checkout_state", {})

    # If checkout has been reviewed, stay in checkout
    if checkout_state.get("order_reviewed") or checkout_state.get("awaiting"):
        return ChainName.CHECKOUT

    if status == "confirmed":
        return ChainName.CHECKOUT

    if status == "pending" and not order_type:
        return ChainName.GREETING

    if order_type and not items:
        # Have order type but no items - ready to order
        return ChainName.BAGEL

    if items:
        # Have items, could be ordering more or checking out
        return ChainName.BAGEL

    return ChainName.GREETING


# -----------------------------------------------------------------------------
# State Conversion: Pydantic -> Dict
# -----------------------------------------------------------------------------

def order_state_to_dict(state: OrderState) -> Dict[str, Any]:
    """
    Convert a Pydantic OrderState back to dict format for compatibility.

    Args:
        state: The Pydantic OrderState

    Returns:
        Dict in the legacy format expected by existing code
    """
    # Convert items back to legacy format
    items = []

    for bagel in state.bagels.items:
        item = {
            "item_type": "sandwich",
            "menu_item_name": bagel.bagel_type,
            "bread": bagel.bagel_type if "bagel" in bagel.bagel_type.lower() else None,
            "protein": bagel.sandwich_protein,
            "cheese": bagel.spread,
            "toppings": bagel.extras,
            "sauces": [],
            "toasted": bagel.toasted,
            "quantity": bagel.quantity,
            "unit_price": bagel.unit_price,
            "line_total": bagel.unit_price * bagel.quantity,
        }
        items.append(item)

    for coffee in state.coffee.items:
        item = {
            "item_type": "drink",
            "menu_item_name": coffee.drink_type,
            "size": coffee.size,
            "item_config": {
                "size": coffee.size,
                "milk": coffee.milk,
                "sweetener": coffee.sweetener,
                "sweetener_quantity": coffee.sweetener_quantity,
                "flavor_syrup": coffee.flavor_syrup,
                "style": "iced" if coffee.iced else "hot",
            },
            "quantity": 1,
            "unit_price": coffee.unit_price,
            "line_total": coffee.unit_price,
        }
        items.append(item)

    # Map status back
    status_map = {
        OrderStatus.IN_PROGRESS: "collecting_items" if items else "pending",
        OrderStatus.CONFIRMED: "confirmed",
        OrderStatus.CANCELLED: "cancelled",
    }

    # Calculate total
    total_price = state.get_subtotal()

    order_dict = {
        "status": status_map.get(state.status, "pending"),
        "items": items,
        "total_price": total_price,
        "order_type": state.address.order_type,
        "customer": {
            "name": state.customer_name,
            "phone": state.customer_phone,
            "email": state.customer_email,
            "pickup_time": None,
        },
    }

    if state.address.order_type == "delivery" and state.address.street:
        order_dict["delivery_address"] = state.address.get_formatted_address()

    if state.checkout.payment_method:
        order_dict["payment_method"] = state.checkout.payment_method

    if state.checkout.order_number:
        order_dict["order_number"] = state.checkout.order_number

    # Preserve bagel chain state for conversation flow
    order_dict["bagel_chain_state"] = {
        "awaiting": state.bagels.awaiting,
        "current_item": state.bagels.current_item.model_dump() if state.bagels.current_item else None,
    }

    # Preserve coffee chain state for conversation flow
    order_dict["coffee_chain_state"] = {
        "awaiting": state.coffee.awaiting,
        "current_item": state.coffee.current_item.model_dump() if state.coffee.current_item else None,
    }

    # Preserve checkout state for conversation flow
    order_dict["checkout_state"] = {
        "order_reviewed": state.checkout.order_reviewed,
        "awaiting": state.checkout.awaiting,
        "name_collected": state.checkout.name_collected,
        "contact_collected": state.checkout.contact_collected,
        "subtotal": state.checkout.subtotal,
        "city_tax": state.checkout.city_tax,
        "state_tax": state.checkout.state_tax,
        "tax": state.checkout.tax,
        "delivery_fee": state.checkout.delivery_fee,
        "total": state.checkout.total,
        "total_calculated": state.checkout.total_calculated,
        "confirmed": state.checkout.confirmed,
    }

    # Preserve current chain for routing
    order_dict["current_chain"] = state.current_chain.value

    # Preserve pending intents
    order_dict["pending_coffee"] = state.pending_coffee

    return order_dict


# -----------------------------------------------------------------------------
# Orchestrator Wrapper
# -----------------------------------------------------------------------------

# Global orchestrator instance (lazy initialized)
_orchestrator: Optional[Orchestrator] = None


def get_orchestrator(menu_data: Dict = None, store_info: Dict = None) -> Orchestrator:
    """
    Get or create the global Orchestrator instance.

    Args:
        menu_data: Optional menu data for pricing
        store_info: Optional store information

    Returns:
        Configured Orchestrator instance
    """
    global _orchestrator

    if _orchestrator is None:
        # Create the registry and register all chains
        registry = ChainRegistry()
        registry.register(GreetingChain(menu_data=menu_data, store_info=store_info))
        registry.register(AddressChain(menu_data=menu_data, store_info=store_info))
        registry.register(BagelChain(menu_data=menu_data))
        registry.register(CoffeeChain(menu_data=menu_data))
        registry.register(CheckoutChain(menu_data=menu_data))

        _orchestrator = Orchestrator(
            chain_registry=registry,
            menu_data=menu_data,
        )
        logger.info("Created new chain orchestrator instance")

    return _orchestrator


def process_message_with_chains(
    user_message: str,
    order_state_dict: Dict[str, Any],
    history: List[Dict[str, str]],
    session_id: str = None,
    menu_data: Dict = None,
    store_info: Dict = None,
) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    """
    Process a user message using the new chain-based orchestrator.

    This is designed to be a drop-in replacement for the LLM-based processing.

    Args:
        user_message: The user's input message
        order_state_dict: Current order state in dict format
        history: Conversation history
        session_id: Session identifier
        menu_data: Menu data for pricing
        store_info: Store information

    Returns:
        Tuple of (reply, updated_order_state_dict, actions)
        - reply: The bot's response message
        - updated_order_state_dict: Updated order state in dict format
        - actions: List of actions taken (for compatibility)
    """
    # Convert dict state to Pydantic
    state = dict_to_order_state(order_state_dict, session_id)

    # Copy conversation history to state
    state.conversation_history = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in history
    ]

    # Get orchestrator and process
    orchestrator = get_orchestrator(menu_data, store_info)
    result: ChainResult = orchestrator.process(user_message, state)

    # Convert state back to dict
    updated_dict = order_state_to_dict(result.state)

    # Build actions list for compatibility
    # The new system doesn't use discrete actions, but we can infer them
    actions = _infer_actions_from_result(order_state_dict, updated_dict, result)

    logger.info(
        "Chain orchestrator processed message - chain: %s, complete: %s",
        result.state.current_chain,
        result.chain_complete
    )

    return result.message, updated_dict, actions


def _infer_actions_from_result(
    old_state: Dict[str, Any],
    new_state: Dict[str, Any],
    result: ChainResult,
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

            if item_type == "drink":
                intent = "add_drink"
            else:
                intent = "add_sandwich"

            actions.append({
                "intent": intent,
                "slots": {
                    "menu_item_name": item.get("menu_item_name"),
                    "quantity": item.get("quantity", 1),
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
    old_status = old_state.get("status")
    new_status = new_state.get("status")
    if new_status == "confirmed" and old_status != "confirmed":
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


# -----------------------------------------------------------------------------
# Hybrid Processing (Fallback Support)
# -----------------------------------------------------------------------------

def process_message_hybrid(
    user_message: str,
    order_state_dict: Dict[str, Any],
    history: List[Dict[str, str]],
    session_id: str,
    menu_data: Dict,
    store_info: Dict,
    llm_fallback_fn: callable,
) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    """
    Process a message with fallback to LLM for complex cases.

    Uses the chain orchestrator for deterministic flows, but falls back
    to the LLM for cases the orchestrator can't handle confidently.

    Args:
        user_message: The user's input message
        order_state_dict: Current order state
        history: Conversation history
        session_id: Session identifier
        menu_data: Menu data
        store_info: Store information
        llm_fallback_fn: Function to call for LLM-based processing

    Returns:
        Tuple of (reply, updated_order_state_dict, actions)
    """
    # First, try the chain orchestrator
    state = dict_to_order_state(order_state_dict, session_id)
    orchestrator = get_orchestrator(menu_data, store_info)

    # Classify intent to determine confidence
    from .orchestrator import Intent
    intent = orchestrator.classify_intent(user_message, state)

    # For unknown intents or complex cases, use LLM
    if intent == Intent.UNKNOWN:
        logger.info("Chain orchestrator couldn't classify intent, falling back to LLM")
        return llm_fallback_fn(
            user_message,
            order_state_dict,
            history,
            session_id,
            menu_data,
            store_info,
        )

    # Use chain orchestrator for classified intents
    return process_message_with_chains(
        user_message,
        order_state_dict,
        history,
        session_id,
        menu_data,
        store_info,
    )
