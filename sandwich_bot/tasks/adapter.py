"""
Adapter layer to bridge the TaskOrchestrator with existing endpoints.

This module provides:
1. State conversion between dict-based order_state and OrderTask
2. Feature flag for gradual rollout
3. Wrapper functions that can be used as drop-in replacements
"""

import os
import logging
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    TaskStatus,
    OrderTask,
    BagelItemTask,
    CoffeeItemTask,
    MenuItemTask,
    SpeedMenuBagelItemTask,
)
from .orchestrator import TaskOrchestrator, TaskOrchestratorResult
from .field_config import MenuFieldConfig

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Feature Flag
# -----------------------------------------------------------------------------

def is_task_orchestrator_enabled() -> bool:
    """
    Check if the task-based orchestrator is enabled.

    Control via environment variable:
        TASK_ORCHESTRATOR_ENABLED=true|false|percentage

    Examples:
        TASK_ORCHESTRATOR_ENABLED=true      - Always use task system (default)
        TASK_ORCHESTRATOR_ENABLED=false     - Don't use task system
        TASK_ORCHESTRATOR_ENABLED=50        - 50% of sessions use task system
    """
    flag_value = os.environ.get("TASK_ORCHESTRATOR_ENABLED", "true").lower()

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
# State Conversion: Dict -> OrderTask
# -----------------------------------------------------------------------------

def dict_to_order_task(order_dict: Dict[str, Any], session_id: str = None) -> OrderTask:
    """
    Convert a dict-based order state to OrderTask.

    Args:
        order_dict: The existing dict-based order state
        session_id: Optional session ID to preserve

    Returns:
        OrderTask instance
    """
    if not order_dict:
        return OrderTask()

    order = OrderTask()

    # Preserve database order ID if present
    if order_dict.get("db_order_id"):
        order.db_order_id = order_dict["db_order_id"]

    # Convert customer info
    customer = order_dict.get("customer", {})
    if customer.get("name"):
        order.customer_info.name = customer["name"]
    if customer.get("phone"):
        order.customer_info.phone = customer["phone"]
    if customer.get("email"):
        order.customer_info.email = customer["email"]
    # Mark customer info complete if we have name
    if order.customer_info.name:
        order.customer_info.mark_complete()

    # Convert order type and address
    order_type = order_dict.get("order_type")
    if order_type:
        order.delivery_method.order_type = order_type
        if order_type == "pickup":
            order.delivery_method.mark_complete()
        elif order_type == "delivery":
            delivery_address = order_dict.get("delivery_address", "")
            if delivery_address:
                order.delivery_method.address.street = delivery_address
                order.delivery_method.address.is_validated = True
                order.delivery_method.address.mark_complete()
            # Mark delivery method in progress if address provided
            if order.delivery_method.address.street:
                order.delivery_method.mark_complete()

    # Convert items
    for item in order_dict.get("items", []):
        item_type = item.get("item_type", "sandwich")

        if item_type == "menu_item":
            # MenuItemTask (omelettes, sandwiches, etc.)
            menu_item = MenuItemTask(
                menu_item_name=item.get("menu_item_name") or "Unknown",
                menu_item_id=item.get("menu_item_id"),
                menu_item_type=item.get("menu_item_type"),
                modifications=item.get("modifications") or [],
                side_choice=item.get("side_choice"),
                bagel_choice=item.get("bagel_choice"),
                toasted=item.get("toasted"),  # For spread/salad sandwiches
                requires_side_choice=item.get("requires_side_choice", False),
                quantity=item.get("quantity", 1),
                notes=item.get("notes"),
            )
            # Preserve item ID if provided
            if item.get("id"):
                menu_item.id = item["id"]
            # Restore status
            if item.get("status"):
                menu_item.status = TaskStatus(item["status"])
            # Set price if available
            if item.get("unit_price"):
                menu_item.unit_price = item["unit_price"]
            order.items.add_item(menu_item)

        elif item_type == "bagel":
            # New bagel format from state machine
            # Note: bagel_type can be None if we haven't asked yet
            bagel = BagelItemTask(
                bagel_type=item.get("bagel_type"),  # Allow None for incomplete bagels
                quantity=item.get("quantity", 1),
                toasted=item.get("toasted"),
                spread=item.get("spread"),
                spread_type=item.get("spread_type"),
                sandwich_protein=item.get("sandwich_protein"),
                extras=item.get("extras") or [],
                notes=item.get("notes"),
            )
            # Preserve item ID if provided
            if item.get("id"):
                bagel.id = item["id"]
            # Restore status
            if item.get("status"):
                bagel.status = TaskStatus(item["status"])
            # Set price if available
            if item.get("unit_price"):
                bagel.unit_price = item["unit_price"]
            order.items.add_item(bagel)

        elif item_type == "sandwich":
            # Legacy sandwich format - treat as bagel for now
            bagel = BagelItemTask(
                bagel_type=item.get("bread") or item.get("menu_item_name") or "unknown",
                quantity=item.get("quantity", 1),
                toasted=item.get("toasted"),
                spread=item.get("cheese"),
                extras=item.get("toppings") or [],
                notes=item.get("notes"),
            )
            # Preserve item ID if provided
            if item.get("id"):
                bagel.id = item["id"]
            # Restore status
            if item.get("status"):
                bagel.status = TaskStatus(item["status"])
            # Set price if available
            if item.get("unit_price"):
                bagel.unit_price = item["unit_price"]
            # Mark complete if has all required fields
            if bagel.bagel_type and bagel.toasted is not None:
                bagel.mark_complete()
            order.items.add_item(bagel)

        elif item_type == "drink":
            item_config = item.get("item_config") or {}
            # Determine iced value from item_config.style, not drink name
            # style="iced" → True, style="hot" → False, style=None → None (skip_config drinks)
            style = item_config.get("style")
            if style == "iced":
                iced_value = True
            elif style == "hot":
                iced_value = False
            else:
                # For skip_config drinks (sodas, etc.) or unspecified, keep as None
                iced_value = None
            coffee = CoffeeItemTask(
                drink_type=item.get("menu_item_name") or "coffee",
                size=item.get("size") or item_config.get("size"),  # Don't default to medium for skip_config drinks
                milk=item_config.get("milk"),
                sweetener=item_config.get("sweetener"),
                sweetener_quantity=item_config.get("sweetener_quantity", 1),
                flavor_syrup=item_config.get("flavor_syrup"),
                iced=iced_value,
                # Restore upcharge tracking fields
                size_upcharge=item_config.get("size_upcharge", 0.0),
                milk_upcharge=item_config.get("milk_upcharge", 0.0),
                syrup_upcharge=item_config.get("syrup_upcharge", 0.0),
                notes=item.get("notes"),
            )
            # Preserve item ID if provided
            if item.get("id"):
                coffee.id = item["id"]
            # Restore status
            if item.get("status"):
                coffee.status = TaskStatus(item["status"])
            # Set price if available
            if item.get("unit_price"):
                coffee.unit_price = item["unit_price"]
            # Mark complete if has required fields
            if coffee.drink_type and coffee.iced is not None:
                coffee.mark_complete()
            order.items.add_item(coffee)

        elif item_type == "speed_menu_bagel":
            # Speed menu bagel (pre-configured sandwiches like "The Classic")
            speed_menu_item = SpeedMenuBagelItemTask(
                menu_item_name=item.get("menu_item_name") or "Unknown",
                menu_item_id=item.get("menu_item_id"),
                toasted=item.get("toasted"),
                bagel_choice=item.get("bagel_choice"),
                quantity=item.get("quantity", 1),
                notes=item.get("notes"),
            )
            # Preserve item ID if provided
            if item.get("id"):
                speed_menu_item.id = item["id"]
            # Restore status
            if item.get("status"):
                speed_menu_item.status = TaskStatus(item["status"])
            # Set price if available
            if item.get("unit_price"):
                speed_menu_item.unit_price = item["unit_price"]
            order.items.add_item(speed_menu_item)

    # Restore task orchestrator state if present
    task_state = order_dict.get("task_orchestrator_state", {})
    if task_state.get("conversation_history"):
        order.conversation_history = task_state["conversation_history"]

    # Restore flow state (pending fields) from state_machine_state
    sm_state = order_dict.get("state_machine_state", {})
    if sm_state:
        # Handle pending_item_ids (list) or legacy pending_item_id (single)
        pending_item_ids = sm_state.get("pending_item_ids", [])
        if not pending_item_ids:
            legacy_id = sm_state.get("pending_item_id")
            if legacy_id:
                pending_item_ids = [legacy_id]
        order.pending_item_ids = pending_item_ids
        order.pending_field = sm_state.get("pending_field")
        order.last_bot_message = sm_state.get("last_bot_message")
        order.phase = sm_state.get("phase", "greeting")
        order.pending_config_queue = sm_state.get("pending_config_queue", [])

    # Convert checkout state
    checkout_data = order_dict.get("checkout_state", {})
    if checkout_data.get("confirmed") or order_dict.get("status") == "confirmed":
        order.checkout.confirmed = True
        order.checkout.mark_complete()
    # Restore order_reviewed flag
    if checkout_data.get("order_reviewed"):
        order.checkout.order_reviewed = True

    # Payment
    if order_dict.get("payment_method"):
        order.payment.method = order_dict["payment_method"]
        if order_dict.get("payment_link"):
            order.payment.payment_link_sent = True
        if order.payment.method:
            order.payment.mark_complete()

    return order


# -----------------------------------------------------------------------------
# State Conversion: OrderTask -> Dict
# -----------------------------------------------------------------------------

def order_task_to_dict(order: OrderTask, store_info: Dict = None) -> Dict[str, Any]:
    """
    Convert an OrderTask back to dict format for compatibility.

    Args:
        order: The OrderTask instance
        store_info: Optional store info for tax calculation

    Returns:
        Dict in the legacy format expected by existing code
    """
    items = []

    # Get ALL items including in-progress ones (important for state machine)
    all_items = order.items.items  # Include in-progress items, not just active/complete

    for item in all_items:
        if item.status == TaskStatus.SKIPPED:
            continue  # Don't include skipped items

        # Use item_type attribute instead of isinstance for robustness
        if item.item_type == "menu_item":
            # MenuItemTask (omelettes, sandwiches, etc.)
            side_choice = getattr(item, 'side_choice', None)
            bagel_choice = getattr(item, 'bagel_choice', None)
            toasted = getattr(item, 'toasted', None)

            item_dict = {
                "item_type": "menu_item",
                "id": item.id,  # Preserve item ID
                "status": item.status.value,
                "menu_item_name": item.menu_item_name,  # Keep original name (no side choice)
                "menu_item_id": getattr(item, 'menu_item_id', None),
                "menu_item_type": getattr(item, 'menu_item_type', None),
                "modifications": getattr(item, 'modifications', []),
                "side_choice": side_choice,
                "bagel_choice": bagel_choice,
                "toasted": toasted,  # For spread/salad sandwiches
                "requires_side_choice": getattr(item, 'requires_side_choice', False),
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_total": item.unit_price * item.quantity if item.unit_price else 0,
                "notes": getattr(item, 'notes', None),
            }
            items.append(item_dict)

        elif item.item_type == "bagel":
            bagel_type = getattr(item, 'bagel_type', None)
            spread = getattr(item, 'spread', None)
            spread_type = getattr(item, 'spread_type', None)
            toasted = getattr(item, 'toasted', None)
            sandwich_protein = getattr(item, 'sandwich_protein', None)
            extras = getattr(item, 'extras', []) or []

            # Build display name like "plain bagel toasted with ham, egg, american"
            display_parts = []
            if bagel_type:
                display_parts.append(f"{bagel_type} bagel")
            else:
                display_parts.append("bagel")
            if toasted:
                display_parts.append("toasted")

            # Build the "with X" part - combine spread, protein, and extras
            with_parts = []
            if spread and spread.lower() != "none":
                spread_desc = spread
                if spread_type and spread_type != "plain":
                    spread_desc = f"{spread_type} {spread}"
                with_parts.append(spread_desc)
            if sandwich_protein:
                with_parts.append(sandwich_protein)
            if extras:
                with_parts.extend(extras)

            if with_parts:
                display_parts.append(f"with {', '.join(with_parts)}")
            elif spread and spread.lower() == "none":
                # Only say "with nothing on it" if there's truly nothing
                display_parts.append("with nothing on it")

            item_dict = {
                "item_type": "bagel",
                "id": item.id,  # Preserve item ID
                "status": item.status.value,
                "menu_item_name": " ".join(display_parts),
                "bagel_type": bagel_type,
                "spread": spread,
                "spread_type": spread_type,
                "toasted": toasted,
                "sandwich_protein": getattr(item, 'sandwich_protein', None),
                "extras": getattr(item, 'extras', []),
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_total": item.unit_price * item.quantity if item.unit_price else 0,
                "notes": getattr(item, 'notes', None),
            }
            items.append(item_dict)

        elif item.item_type == "coffee":
            item_dict = {
                "item_type": "drink",
                "id": item.id,  # Preserve item ID
                "status": item.status.value,
                "menu_item_name": getattr(item, 'drink_type', 'coffee'),
                "size": getattr(item, 'size', None),  # Don't default to medium for skip_config drinks
                "item_config": {
                    "size": getattr(item, 'size', None),  # Don't default to medium
                    "milk": getattr(item, 'milk', None),
                    "sweetener": getattr(item, 'sweetener', None),
                    "sweetener_quantity": getattr(item, 'sweetener_quantity', 1),
                    "flavor_syrup": getattr(item, 'flavor_syrup', None),
                    # Only set style if iced is explicitly True/False (not None)
                    # skip_config drinks (sodas, bottled) don't need iced/hot labels
                    "style": "iced" if getattr(item, 'iced', None) is True else ("hot" if getattr(item, 'iced', None) is False else None),
                    # Upcharge tracking for display
                    "size_upcharge": getattr(item, 'size_upcharge', 0.0),
                    "milk_upcharge": getattr(item, 'milk_upcharge', 0.0),
                    "syrup_upcharge": getattr(item, 'syrup_upcharge', 0.0),
                },
                "quantity": 1,
                "unit_price": item.unit_price,
                "line_total": item.unit_price if item.unit_price else 0,
                "notes": getattr(item, 'notes', None),
            }
            items.append(item_dict)

        elif item.item_type == "speed_menu_bagel":
            # Speed menu bagel (pre-configured sandwiches)
            toasted = getattr(item, 'toasted', None)
            bagel_choice = getattr(item, 'bagel_choice', None)
            menu_item_name = getattr(item, 'menu_item_name', 'Unknown')

            # Build display name with bagel choice and toasted status (for UI only)
            display_name = menu_item_name
            if bagel_choice:
                display_name = f"{menu_item_name} on {bagel_choice} bagel"
            if toasted is True:
                display_name = f"{display_name} toasted"
            elif toasted is False:
                display_name = f"{display_name} not toasted"

            item_dict = {
                "item_type": "speed_menu_bagel",
                "id": item.id,
                "status": item.status.value,
                # Keep original menu_item_name for round-trip preservation
                "menu_item_name": menu_item_name,
                # Add display_name separately for UI purposes
                "display_name": display_name,
                "menu_item_id": getattr(item, 'menu_item_id', None),
                "toasted": toasted,
                "bagel_choice": bagel_choice,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_total": item.unit_price * item.quantity if item.unit_price else 0,
                "notes": getattr(item, 'notes', None),
            }
            items.append(item_dict)

        else:
            # Unknown item type - log and skip
            logger.warning(f"Unknown item type: {item.item_type}, type: {type(item)}")

    # Determine status
    if order.checkout.confirmed:
        status = "confirmed"
    elif order.items.get_item_count() > 0:
        status = "collecting_items"
    else:
        status = "pending"

    # Calculate total - use checkout total if calculated, otherwise sum items
    if order.checkout.total > 0:
        total_price = order.checkout.total
    else:
        total_price = sum(
            (item.unit_price or 0) * getattr(item, 'quantity', 1)
            for item in order.items.get_active_items()
        )

    order_dict = {
        "status": status,
        "items": items,
        "total_price": total_price,
        "order_type": order.delivery_method.order_type,
        "customer": {
            "name": order.customer_info.name,
            "phone": order.customer_info.phone,
            "email": order.customer_info.email,
            "pickup_time": None,
        },
    }

    # Preserve database order ID if present
    if order.db_order_id:
        order_dict["db_order_id"] = order.db_order_id

    # Delivery address
    if order.delivery_method.order_type == "delivery" and order.delivery_method.address.street:
        order_dict["delivery_address"] = order.delivery_method.address.street

    # Payment
    if order.payment.method:
        order_dict["payment_method"] = order.payment.method
    if order.payment.payment_link_sent and order.payment.payment_link_destination:
        order_dict["payment_link"] = order.payment.payment_link_destination

    # Calculate taxes if store_info is available
    # This ensures the order panel shows taxes in real-time, not just at checkout
    subtotal = sum(
        (item.unit_price or 0) * getattr(item, 'quantity', 1)
        for item in order.items.get_active_items()
    )

    city_tax = order.checkout.city_tax
    state_tax = order.checkout.state_tax
    tax = order.checkout.tax
    delivery_fee = order.checkout.delivery_fee
    total = order.checkout.total

    if store_info and subtotal > 0:
        # Calculate taxes using store's tax rates
        city_tax_rate = store_info.get("city_tax_rate", 0.0)
        state_tax_rate = store_info.get("state_tax_rate", 0.0)
        city_tax = round(subtotal * city_tax_rate, 2)
        state_tax = round(subtotal * state_tax_rate, 2)
        tax = city_tax + state_tax

        # Calculate delivery fee if applicable
        is_delivery = order.delivery_method.order_type == "delivery"
        delivery_fee = store_info.get("delivery_fee", 2.99) if is_delivery else 0.0

        # Calculate total
        total = round(subtotal + tax + delivery_fee, 2)

    # Checkout state for compatibility (include tax breakdown)
    order_dict["checkout_state"] = {
        "confirmed": order.checkout.confirmed,
        "order_reviewed": order.checkout.order_reviewed,
        "name_collected": order.customer_info.name is not None,
        "contact_collected": order.customer_info.phone is not None or order.customer_info.email is not None,
        "subtotal": subtotal,
        "city_tax": city_tax,
        "state_tax": state_tax,
        "tax": tax,
        "delivery_fee": delivery_fee,
        "total": total,
    }

    # Preserve task orchestrator state
    order_dict["task_orchestrator_state"] = {
        "conversation_history": order.conversation_history,
    }

    # Save flow state (pending fields) - OrderTask is now the source of truth
    order_dict["state_machine_state"] = {
        "phase": order.phase,
        "pending_item_ids": order.pending_item_ids,
        "pending_item_id": order.pending_item_id,  # Legacy compat
        "pending_field": order.pending_field,
        "last_bot_message": order.last_bot_message,
        "pending_config_queue": order.pending_config_queue,  # Queue of items needing config
    }

    return order_dict


# -----------------------------------------------------------------------------
# Orchestrator Wrapper
# -----------------------------------------------------------------------------

# Global orchestrator instance (lazy initialized)
_task_orchestrator: Optional[TaskOrchestrator] = None


def get_task_orchestrator(menu_data: Dict = None) -> TaskOrchestrator:
    """
    Get or create the global TaskOrchestrator instance.

    Args:
        menu_data: Optional menu data for configuration

    Returns:
        Configured TaskOrchestrator instance
    """
    global _task_orchestrator

    if _task_orchestrator is None:
        menu_config = MenuFieldConfig.from_menu_data(menu_data) if menu_data else None
        _task_orchestrator = TaskOrchestrator(
            menu_config=menu_config,
            menu_data=menu_data,
        )
        logger.info("Created new task orchestrator instance")

    return _task_orchestrator


def process_message_with_tasks(
    user_message: str,
    order_state_dict: Dict[str, Any],
    history: List[Dict[str, str]],
    session_id: str = None,
    menu_data: Dict = None,
    store_info: Dict = None,
) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    """
    Process a user message using the task-based orchestrator.

    This is designed to be a drop-in replacement for the other orchestrators.

    Args:
        user_message: The user's input message
        order_state_dict: Current order state in dict format
        history: Conversation history
        session_id: Session identifier
        menu_data: Menu data for pricing
        store_info: Store information (currently unused)

    Returns:
        Tuple of (reply, updated_order_state_dict, actions)
    """
    # Convert dict state to OrderTask
    order = dict_to_order_task(order_state_dict, session_id)

    # Copy conversation history if not already present
    if not order.conversation_history and history:
        order.conversation_history = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in history
        ]

    # Get the pending question for context
    orchestrator = get_task_orchestrator(menu_data)
    pending_question = orchestrator.get_pending_question(order)

    # Process the message
    result: TaskOrchestratorResult = orchestrator.process(
        user_input=user_message,
        order=order,
        pending_question=pending_question,
    )

    # Convert state back to dict (pass store_info for tax calculation)
    updated_dict = order_task_to_dict(result.order, store_info=store_info)

    # Build actions list for compatibility
    actions = _infer_actions_from_result(order_state_dict, updated_dict, result)

    logger.info(
        "Task orchestrator processed message - action: %s, complete: %s",
        result.action_type,
        result.is_complete
    )

    return result.message, updated_dict, actions


async def process_message_with_tasks_async(
    user_message: str,
    order_state_dict: Dict[str, Any],
    history: List[Dict[str, str]],
    session_id: str = None,
    menu_data: Dict = None,
    store_info: Dict = None,
) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    """
    Process a user message asynchronously using the task-based orchestrator.

    Args:
        user_message: The user's input message
        order_state_dict: Current order state in dict format
        history: Conversation history
        session_id: Session identifier
        menu_data: Menu data for pricing
        store_info: Store information (currently unused)

    Returns:
        Tuple of (reply, updated_order_state_dict, actions)
    """
    # Convert dict state to OrderTask
    order = dict_to_order_task(order_state_dict, session_id)

    # Copy conversation history if not already present
    if not order.conversation_history and history:
        order.conversation_history = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in history
        ]

    # Get the pending question for context
    orchestrator = get_task_orchestrator(menu_data)
    pending_question = orchestrator.get_pending_question(order)

    # Process the message asynchronously
    result: TaskOrchestratorResult = await orchestrator.process_async(
        user_input=user_message,
        order=order,
        pending_question=pending_question,
    )

    # Convert state back to dict (pass store_info for tax calculation)
    updated_dict = order_task_to_dict(result.order, store_info=store_info)

    # Build actions list for compatibility
    actions = _infer_actions_from_result(order_state_dict, updated_dict, result)

    logger.info(
        "Task orchestrator (async) processed message - action: %s, complete: %s",
        result.action_type,
        result.is_complete
    )

    return result.message, updated_dict, actions


def _infer_actions_from_result(
    old_state: Dict[str, Any],
    new_state: Dict[str, Any],
    result: TaskOrchestratorResult,
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
