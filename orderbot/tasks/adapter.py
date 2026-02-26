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
import types
from typing import Any, get_args, get_origin, Union

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from .models import (
    TaskStatus,
    OrderTask,
)
from .models.container_tasks import _get_field_default
from .item_converters import _unified_converter
from .pricing import PricingEngine
from .utils.text import format_pickup_time_display
from ..schemas.enums import OrderStatus
from ..services.tax_utils import calculate_order_total

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Flow State Helpers
# -----------------------------------------------------------------------------

def _get_flow_state_fields() -> frozenset[str]:
    """Derive the set of flow-state field names from OrderTask.model_fields.

    Flow-state fields = all OrderTask fields MINUS structural fields.
    This is auto-derived so adding a new field to OrderTask automatically
    includes it in serialization — no manual list to keep in sync.
    """
    return frozenset(OrderTask.model_fields) - OrderTask._STRUCTURAL_FIELDS


def _extract_pydantic_class(annotation: Any) -> type[BaseModel] | None:
    """Extract a Pydantic BaseModel subclass from a type annotation.

    Handles ``X | None`` (UnionType) and plain ``X`` annotations.
    Returns None if the annotation isn't a BaseModel subclass.
    """
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        for arg in get_args(annotation):
            if isinstance(arg, type) and issubclass(arg, BaseModel):
                return arg
    elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


# Pre-compute flow state metadata at import time for O(1) access
_FLOW_STATE_FIELD_NAMES: frozenset[str] = _get_flow_state_fields()

# Map field_name -> (default_value_or_factory, pydantic_model_class_or_None)
_FLOW_STATE_META: dict[str, tuple[Any, type[BaseModel] | None]] = {}
for _fname in _FLOW_STATE_FIELD_NAMES:
    _finfo = OrderTask.model_fields[_fname]
    _pydantic_cls = _extract_pydantic_class(_finfo.annotation)
    _FLOW_STATE_META[_fname] = (_finfo, _pydantic_cls)


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

    Fields are auto-derived from OrderTask.model_fields, so adding a new
    field to OrderTask automatically includes it here.

    Args:
        sm_state: The state_machine_state dict from order_dict
        order: The OrderTask to populate
    """
    for field_name, (field_info, model_cls) in _FLOW_STATE_META.items():
        default = _get_field_default(field_info)
        value = sm_state.get(field_name, default)
        # Coerce raw dicts back to Pydantic models after JSON round-trip
        if model_cls and isinstance(value, dict):
            value = model_cls.model_validate(value)
        setattr(order, field_name, value)


def _build_flow_state_dict(order: OrderTask) -> dict:
    """Build state_machine_state dict from OrderTask flow state fields.

    Fields are auto-derived from OrderTask.model_fields.

    Args:
        order: The OrderTask to serialize

    Returns:
        Dict containing all flow state fields
    """
    result = {}
    for field_name in _FLOW_STATE_FIELD_NAMES:
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


def _aggregate_special_instructions(items_list: list[dict]) -> str | None:
    """Aggregate per-item special instructions for DB/POS compatibility.

    Args:
        items_list: Serialized item dicts (already converted via to_dict).

    Returns:
        Combined string like "Item A: instr1; instr2 | Item B: instr3", or None.
    """
    all_instructions = []
    for item_dict in items_list:
        item_instrs = item_dict.get("special_instructions", [])
        if item_instrs:
            item_name = item_dict.get("display_name") or item_dict.get("menu_item_name", "")
            all_instructions.append(f"{item_name}: {'; '.join(item_instrs)}")
    return " | ".join(all_instructions) if all_instructions else None


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
        tz_str = store_info.get("timezone", "America/New_York")
        raw = format_pickup_time_display(pickup_time, timezone=tz_str)
        # Capitalize for frontend display ("today" -> "Today")
        pickup_time_display = raw[0].upper() + raw[1:] if raw else raw

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
        "special_instructions": _aggregate_special_instructions(items),
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

    # Store info for frontend badge (cached to avoid rebuilding on every call)
    if store_info:
        cached_badge = store_info.get("_frontend_badge")
        if cached_badge is None:
            raw_name = store_info.get("name", "")
            short = raw_name.split(" - ")[-1] if " - " in raw_name else raw_name
            cached_badge = {
                "store_id": store_info.get("store_id"),
                "name": raw_name,
                "short_name": short,
            }
            store_info["_frontend_badge"] = cached_badge
        order_dict["store"] = cached_badge

    # Preserve conversation history
    order_dict["task_orchestrator_state"] = {
        "conversation_history": order.conversation_history,
    }

    # Save flow state
    order_dict["state_machine_state"] = _build_flow_state_dict(order)

    return order_dict
