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


# Map field names to Pydantic model classes for dict→model coercion on restore.
# Module-level to avoid rebuilding on every _restore_flow_state() call.
_PYDANTIC_FIELDS: dict[str, type] = {
    "pending_attr_disambiguation": PendingAttrDisambiguation,
    "pending_change_clarification": PendingChangeClarification,
    "pending_dietary_followup": PendingDietaryFollowup,
    "pending_duplicate_selection": PendingDuplicateSelection,
    "pending_ingredient_search": PendingIngredientSearch,
    "pending_ingredient_suggestion": PendingIngredientSuggestion,
    "pending_order_history": PendingOrderHistory,
    "pending_same_thing_clarification": PendingSameThingClarification,
    "pending_switch_item": PendingSwitchItem,
    "pending_unmatched_pagination": PendingUnmatchedPagination,
}


# -----------------------------------------------------------------------------
# Flow State Helpers
# -----------------------------------------------------------------------------

# Single source of truth for all flow state fields serialized to/from
# state_machine_state. Each entry is (field_name, default_value).
# Adding a new field here automatically handles both serialize and restore.
# Note: pending_item_id is a computed property — do NOT include it here.
_FLOW_STATE_FIELDS: list[tuple[str, object]] = [
    ("phase", "greeting"),
    ("pending_item_ids", []),
    ("pending_field", None),
    ("last_bot_message", None),
    ("pending_config_queue", []),
    ("pending_item_modifiers", {}),
    ("pending_item_options", []),
    ("pending_item_quantity", 1),
    ("menu_query_pagination", None),
    ("config_options_page", 0),
    ("multi_item_config_names", []),
    ("pending_duplicate_selection", None),
    ("pending_same_thing_clarification", None),
    ("pending_suggested_item", None),
    ("pending_attr_disambiguation", None),
    ("pending_modifier_quantity", None),
    ("pending_modifier_is_additive", False),
    ("pending_modifier_target_item_index", None),
    ("pending_parsed_items", []),
    ("pending_dietary_followup", None),
    ("pending_quantity_addition", None),
    ("pending_order_history", None),
    ("pending_reorder_items", None),
    ("pending_reorder_offer_items", None),
    # Previously missing fields — were silently lost on session restore
    ("unknown_item_request", None),
    ("pending_change_clarification", None),
    ("pending_ingredient_suggestion", None),
    ("pending_ingredient_to_apply", None),
    ("pending_switch_item", None),
    ("pending_replace_item_id", None),
    ("pending_ingredient_search", None),
    ("pending_unmatched_pagination", None),
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
    for field_name, default in _FLOW_STATE_FIELDS:
        value = sm_state.get(field_name, default)
        # Coerce raw dicts back to Pydantic models after JSON round-trip
        model_cls = _PYDANTIC_FIELDS.get(field_name)
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
    for field_name, _ in _FLOW_STATE_FIELDS:
        value = getattr(order, field_name)
        # Convert Pydantic models to dicts for JSON serialization
        if isinstance(value, BaseModel):
            value = value.model_dump()
        result[field_name] = value
    return result


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

    # Restore conversation history if present
    task_state = order_dict.get("task_orchestrator_state", {})
    if task_state.get("conversation_history"):
        order.conversation_history = task_state["conversation_history"]

    # Restore flow state (pending fields) from state_machine_state
    sm_state = order_dict.get("state_machine_state", {})
    if sm_state:
        _restore_flow_state(sm_state, order)

    # Convert checkout state
    checkout_data = order_dict.get("checkout_state", {})
    if checkout_data.get("confirmed") or order_dict.get("status") == OrderStatus.CONFIRMED:
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
    items = []

    # Get ALL items including in-progress ones
    all_items = order.items.items

    for item in all_items:
        if item.status == TaskStatus.SKIPPED:
            continue

        item_dict = _unified_converter.to_dict(item, pricing)
        items.append(item_dict)

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
            "pickup_time": None,
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

    # Checkout state
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
    order_dict["state_machine_state"] = _build_flow_state_dict(order)

    return order_dict
