"""
Order-Level Serialization Adapter.

This module handles ORDER-LEVEL conversion between:
- Dict-based order_state (database/API JSON format)
- OrderTask (internal Pydantic model used by state machine)

Architecture Layer: PERSISTENCE
┌─────────────────────────────────────────────────────────────────────────────┐
│                          API / Database Layer                               │
│                        (dict-based order_state)                             │
└─────────────────────────────────────────────────────────────────────────────┘
                    ▲                           │
                    │ order_task_to_dict()      │ dict_to_order_task()
                    │                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           THIS MODULE (adapter.py)                          │
│                         Order-level serialization                           │
└─────────────────────────────────────────────────────────────────────────────┘
                    ▲                           │
                    │ _unified_converter        │ _unified_converter
                    │ .to_dict()               │ .from_dict()
                    ▼                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        item_converters.py                                   │
│                      Item-level serialization                               │
└─────────────────────────────────────────────────────────────────────────────┘

Public API:
    dict_to_order_task(order_dict, session_id) -> OrderTask
        Deserialize a dict from database/API into an OrderTask for processing.

    order_task_to_dict(order, store_info, pricing) -> dict
        Serialize an OrderTask back to dict format for persistence/API response.

Related Modules:
    - item_converters.py: Handles individual item dict ↔ MenuItemTask conversion
    - state_machine_adapter.py: Uses this module to wrap state machine for API endpoints
    - order_item_builder.py: Creates initial item dicts (separate concern - item creation)
"""

import logging
from typing import Any

from pydantic import BaseModel

from .models import (
    TaskStatus,
    OrderTask,
)
from .models.pending_states import (
    PendingAttrDisambiguation,
    PendingChangeClarification,
    PendingDietaryFollowup,
    PendingDuplicateSelection,
    PendingIngredientSearch,
    PendingIngredientSuggestion,
    PendingOrderHistory,
    PendingSameThingClarification,
    PendingSwitchItem,
    PendingUnmatchedPagination,
)
from .item_converters import _unified_converter
from .pricing import PricingEngine
from ..schemas.enums import OrderStatus
from ..services.tax_utils import calculate_order_total

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Flow State Helpers
# -----------------------------------------------------------------------------

# Single source of truth for all flow state fields serialized to/from
# state_machine_state. Each entry is (field_name, default_value, pydantic_class).
# The optional third element is a Pydantic model class for dict→model coercion
# on restore (after JSON round-trip). Adding a new field here automatically
# handles both serialize and restore — no separate mapping needed.
# Note: first_pending_item_id is a computed property — do NOT include it here.
_FLOW_STATE_FIELDS: list[tuple[str, object, type | None]] = [
    ("phase", "greeting", None),
    ("pending_item_ids", [], None),
    ("pending_field", None, None),
    ("last_bot_message", None, None),
    ("pending_config_queue", [], None),
    ("pending_item_modifiers", {}, None),
    ("pending_item_options", [], None),
    ("pending_item_quantity", 1, None),
    ("menu_query_pagination", None, None),
    ("config_options_page", 0, None),
    ("multi_item_config_names", [], None),
    ("pending_duplicate_selection", None, PendingDuplicateSelection),
    ("pending_same_thing_clarification", None, PendingSameThingClarification),
    ("pending_suggested_item", None, None),
    ("pending_attr_disambiguation", None, PendingAttrDisambiguation),
    ("pending_modifier_quantity", None, None),
    ("pending_modifier_is_additive", False, None),
    ("pending_modifier_target_item_index", None, None),
    ("pending_parsed_items", [], None),
    ("pending_dietary_followup", None, PendingDietaryFollowup),
    ("pending_quantity_addition", None, None),
    ("pending_order_history", None, PendingOrderHistory),
    ("pending_reorder_items", None, None),
    ("pending_reorder_offer_items", None, None),
    # Previously missing fields — were silently lost on session restore
    ("unknown_item_request", None, None),
    ("pending_change_clarification", None, PendingChangeClarification),
    ("pending_ingredient_suggestion", None, PendingIngredientSuggestion),
    ("pending_ingredient_to_apply", None, None),
    ("pending_switch_item", None, PendingSwitchItem),
    ("pending_replace_item_id", None, None),
    ("pending_ingredient_search", None, PendingIngredientSearch),
    ("pending_unmatched_pagination", None, PendingUnmatchedPagination),
    ("return_to_phase", None, None),
    ("pending_store_change", False, None),
    ("pending_store_page", 0, None),
]


def _calculate_subtotal(order: OrderTask) -> float:
    """Calculate order subtotal from active items.

    Args:
        order: The OrderTask to calculate subtotal for

    Returns:
        Sum of (unit_price * quantity) for all active items
    """
    return sum(
        (item.unit_price or 0) * item.quantity
        for item in order.items.get_active_items()
    )


def _restore_flow_state(sm_state: dict, order: OrderTask) -> None:
    """Restore flow state fields from state_machine_state dict to OrderTask.

    Args:
        sm_state: The state_machine_state dict from order_dict
        order: The OrderTask to populate
    """
    for field_name, default, model_cls in _FLOW_STATE_FIELDS:
        value = sm_state.get(field_name, default)
        # Coerce raw dicts back to Pydantic models after JSON round-trip
        if model_cls and isinstance(value, dict):
            value = model_cls.model_validate(value)
        setattr(order, field_name, value)


def _build_flow_state_dict(order: OrderTask) -> dict:
    """Build state_machine_state dict from OrderTask flow state fields.

    Args:
        order: The OrderTask to serialize

    Returns:
        Dict containing all flow state fields
    """
    result = {}
    for field_name, _, _ in _FLOW_STATE_FIELDS:
        value = getattr(order, field_name)
        # Convert Pydantic models to dicts for JSON serialization
        if isinstance(value, BaseModel):
            value = value.model_dump()
        result[field_name] = value
    return result


# -----------------------------------------------------------------------------
# State Conversion: Dict -> OrderTask (helpers)
# -----------------------------------------------------------------------------

def _restore_customer_info(order_dict: dict, order: OrderTask) -> None:
    """Restore customer name, phone, and email from order dict."""
    customer = order_dict.get("customer", {})
    if customer.get("name"):
        order.customer_info.name = customer["name"]
    if customer.get("phone"):
        order.customer_info.phone = customer["phone"]
    if customer.get("email"):
        order.customer_info.email = customer["email"]
    if order.customer_info.name:
        order.customer_info.mark_complete()


def _restore_order_type(order_dict: dict, order: OrderTask) -> None:
    """Restore delivery method and address from order dict."""
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

    # Restore pickup_time from customer block or scheduling block
    customer = order_dict.get("customer", {})
    scheduling = order_dict.get("scheduling", {})
    pickup_time = customer.get("pickup_time") or scheduling.get("pickup_time")
    if pickup_time:
        order.delivery_method.pickup_time = pickup_time


def _restore_items(order_dict: dict, order: OrderTask) -> None:
    """Convert item dicts to MenuItemTasks and add to order."""
    for item in order_dict.get("items", []):
        item_type = item.get("item_type")
        if not item_type:
            logger.error(
                "Item missing required 'item_type' field in dict_to_order_task. "
                "Item data: %s",
                item
            )
            continue

        item_task = _unified_converter.from_dict(item)
        order.items.add_item(item_task)


def _restore_checkout_state(order_dict: dict, order: OrderTask) -> None:
    """Restore checkout confirmation, review status, and payment from order dict."""
    checkout_data = order_dict.get("checkout_state", {})
    if checkout_data.get("confirmed") or order_dict.get("status") == OrderStatus.CONFIRMED:
        order.checkout.confirmed = True
        order.checkout.mark_complete()
    if checkout_data.get("order_reviewed"):
        order.checkout.order_reviewed = True
    if checkout_data.get("order_number"):
        order.checkout.order_number = checkout_data["order_number"]

    if order_dict.get("payment_method"):
        order.payment.method = order_dict["payment_method"]
        if order_dict.get("payment_link"):
            order.payment.payment_link_sent = True
        if order.payment.method:
            order.payment.mark_complete()


# -----------------------------------------------------------------------------
# State Conversion: Dict -> OrderTask
# -----------------------------------------------------------------------------

def dict_to_order_task(order_dict: dict[str, Any], session_id: str | None = None) -> OrderTask:
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

    # Restore order-level special instructions
    if order_dict.get("special_instructions"):
        order.special_instructions = order_dict["special_instructions"]

    _restore_customer_info(order_dict, order)
    _restore_order_type(order_dict, order)
    _restore_items(order_dict, order)

    # Restore conversation history if present
    task_state = order_dict.get("task_orchestrator_state", {})
    if task_state.get("conversation_history"):
        order.conversation_history = task_state["conversation_history"]

    # Restore flow state (pending fields) from state_machine_state
    sm_state = order_dict.get("state_machine_state", {})
    if sm_state:
        _restore_flow_state(sm_state, order)

    _restore_checkout_state(order_dict, order)

    return order


# -----------------------------------------------------------------------------
# State Conversion: OrderTask -> Dict (helpers)
# -----------------------------------------------------------------------------

def _serialize_items(order: OrderTask, pricing: PricingEngine | None) -> list[dict]:
    """Serialize all non-skipped items to dict format."""
    items = []
    for item in order.items.items:
        if item.status == TaskStatus.SKIPPED:
            continue
        items.append(_unified_converter.to_dict(item, pricing))
    return items


def _build_checkout_state(
    order: OrderTask, subtotal: float, store_info: dict | None
) -> dict:
    """Build the checkout_state sub-dict with tax calculations."""
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

    return {
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
        "order_number": order.checkout.order_number,
    }


def _build_scheduling_dict(
    pickup_time: str | None,
    store_info: dict | None,
) -> dict:
    """Build the scheduling sub-dict for the API response.

    Args:
        pickup_time: ISO-8601 datetime string or None (ASAP).
        store_info: Store info dict with is_open, timezone, etc.

    Returns:
        Scheduling dict for frontend consumption.
    """
    store_info = store_info or {}
    is_scheduled = pickup_time is not None
    pickup_time_display = None

    if is_scheduled and pickup_time:
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            tz_str = store_info.get("timezone", "America/New_York")
            tz = ZoneInfo(tz_str)
            dt = datetime.fromisoformat(pickup_time)
            now = datetime.now(tz)
            days_ahead = (dt.date() - now.date()).days
            try:
                time_str = dt.strftime("%-I:%M %p")
            except ValueError:
                time_str = dt.strftime("%I:%M %p").lstrip("0")
            if days_ahead == 0:
                pickup_time_display = f"Today at {time_str}"
            elif days_ahead == 1:
                pickup_time_display = f"Tomorrow at {time_str}"
            else:
                pickup_time_display = f"{dt.strftime('%A')} at {time_str}"
        except (ValueError, TypeError):
            pickup_time_display = pickup_time

    return {
        "pickup_time": pickup_time,
        "pickup_time_display": pickup_time_display,
        "is_scheduled": is_scheduled,
        "store_is_open": store_info.get("is_open", True),
        "editable": True,
    }


# -----------------------------------------------------------------------------
# State Conversion: OrderTask -> Dict
# -----------------------------------------------------------------------------

def order_task_to_dict(
    order: OrderTask,
    store_info: dict | None = None,
    pricing: PricingEngine | None = None,
) -> dict[str, Any]:
    """
    Convert an OrderTask to dict format for API responses and persistence.

    Args:
        order: The OrderTask instance
        store_info: Optional store info for tax calculation
        pricing: Optional PricingEngine for modifier price lookups

    Returns:
        Dict format used for API responses and database storage
    """
    items = _serialize_items(order, pricing)

    # Determine status
    if order.checkout.confirmed:
        status = OrderStatus.CONFIRMED
    elif order.items.get_item_count() > 0:
        status = "collecting_items"
    else:
        status = OrderStatus.PENDING

    # Calculate subtotal once and reuse
    subtotal = _calculate_subtotal(order)

    # Calculate total
    if order.checkout.total > 0:
        total_price = order.checkout.total
    else:
        total_price = subtotal

    order_dict = {
        "status": status,
        "items": items,
        "total_price": total_price,
        "order_type": order.delivery_method.order_type,
        "customer": {
            "name": order.customer_info.name,
            "phone": order.customer_info.phone,
            "email": order.customer_info.email,
            "pickup_time": order.delivery_method.pickup_time,
        },
        "special_instructions": order.special_instructions,
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

    order_dict["checkout_state"] = _build_checkout_state(order, subtotal, store_info)

    # Scheduling data for frontend
    pickup_time = order.delivery_method.pickup_time
    order_dict["scheduling"] = _build_scheduling_dict(pickup_time, store_info)

    # Store info for frontend badge
    if store_info:
        raw_name = store_info.get("name", "")
        short = raw_name.split(" - ")[-1] if " - " in raw_name else raw_name
        order_dict["store"] = {
            "store_id": store_info.get("store_id"),
            "name": raw_name,
            "short_name": short,
        }

    # Preserve conversation history
    order_dict["task_orchestrator_state"] = {
        "conversation_history": order.conversation_history,
    }

    # Save flow state
    order_dict["state_machine_state"] = _build_flow_state_dict(order)

    return order_dict
