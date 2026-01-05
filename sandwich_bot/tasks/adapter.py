"""
Adapter layer for state conversion.

This module provides bidirectional conversion between:
- Dict-based order_state (used by database/API layer)
- OrderTask (used by state machine)

Item type conversions are delegated to ItemConverter classes via the
ItemConverterRegistry (see item_converters.py).
"""

import logging
from typing import Any, Dict

from .models import (
    TaskStatus,
    OrderTask,
)
from .item_converters import ItemConverterRegistry
from .pricing import PricingEngine
from ..services.tax_utils import calculate_order_total

logger = logging.getLogger(__name__)


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
            if order.delivery_method.address.street:
                order.delivery_method.mark_complete()

    # Convert items using converters
    for item in order_dict.get("items", []):
        item_type = item.get("item_type", "sandwich")
        converter = ItemConverterRegistry.get(item_type)

        if converter:
            item_task = converter.from_dict(item)
            order.items.add_item(item_task)
        else:
            logger.warning(f"Unknown item type in dict_to_order_task: {item_type}")

    # Restore conversation history if present
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
        order.pending_drink_options = sm_state.get("pending_drink_options", [])
        order.pending_coffee_modifiers = sm_state.get("pending_coffee_modifiers", {})
        order.pending_item_options = sm_state.get("pending_item_options", [])
        order.pending_item_quantity = sm_state.get("pending_item_quantity", 1)
        order.menu_query_pagination = sm_state.get("menu_query_pagination")
        order.config_options_page = sm_state.get("config_options_page", 0)
        order.multi_item_config_names = sm_state.get("multi_item_config_names", [])
        order.pending_duplicate_selection = sm_state.get("pending_duplicate_selection")
        order.pending_same_thing_clarification = sm_state.get("pending_same_thing_clarification")
        order.pending_suggested_item = sm_state.get("pending_suggested_item")

    # Convert checkout state
    checkout_data = order_dict.get("checkout_state", {})
    if checkout_data.get("confirmed") or order_dict.get("status") == "confirmed":
        order.checkout.confirmed = True
        order.checkout.mark_complete()
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

def order_task_to_dict(
    order: OrderTask,
    store_info: Dict = None,
    pricing: PricingEngine = None,
) -> Dict[str, Any]:
    """
    Convert an OrderTask back to dict format for compatibility.

    Args:
        order: The OrderTask instance
        store_info: Optional store info for tax calculation
        pricing: Optional PricingEngine for modifier price lookups

    Returns:
        Dict in the legacy format expected by existing code
    """
    items = []

    # Get ALL items including in-progress ones
    all_items = order.items.items

    for item in all_items:
        if item.status == TaskStatus.SKIPPED:
            continue

        converter = ItemConverterRegistry.get_for_item(item)
        if converter:
            item_dict = converter.to_dict(item, pricing)
            items.append(item_dict)
        else:
            logger.warning(f"Unknown item type: {item.item_type}, type: {type(item)}")

    # Determine status
    if order.checkout.confirmed:
        status = "confirmed"
    elif order.items.get_item_count() > 0:
        status = "collecting_items"
    else:
        status = "pending"

    # Calculate total
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
        is_delivery = order.delivery_method.order_type == "delivery"
        totals = calculate_order_total(subtotal, store_info, is_delivery)
        city_tax = totals["city_tax"]
        state_tax = totals["state_tax"]
        tax = totals["tax"]
        delivery_fee = totals["delivery_fee"]
        total = totals["total"]

    # Checkout state for compatibility
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

    # Preserve conversation history
    order_dict["task_orchestrator_state"] = {
        "conversation_history": order.conversation_history,
    }

    # Save flow state
    order_dict["state_machine_state"] = {
        "phase": order.phase,
        "pending_item_ids": order.pending_item_ids,
        "pending_item_id": order.pending_item_id,
        "pending_field": order.pending_field,
        "last_bot_message": order.last_bot_message,
        "pending_config_queue": order.pending_config_queue,
        "pending_drink_options": order.pending_drink_options,
        "pending_coffee_modifiers": order.pending_coffee_modifiers,
        "pending_item_options": order.pending_item_options,
        "pending_item_quantity": order.pending_item_quantity,
        "menu_query_pagination": order.menu_query_pagination,
        "config_options_page": order.config_options_page,
        "multi_item_config_names": order.multi_item_config_names,
        "pending_duplicate_selection": order.pending_duplicate_selection,
        "pending_same_thing_clarification": order.pending_same_thing_clarification,
        "pending_suggested_item": order.pending_suggested_item,
    }

    return order_dict
