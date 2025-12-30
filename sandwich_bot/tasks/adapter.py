"""
Adapter layer for state conversion.

This module provides bidirectional conversion between:
- Dict-based order_state (used by database/API layer)
- OrderTask (used by state machine)
"""

import logging
from typing import Any, Dict, List, Optional

from .models import (
    TaskStatus,
    OrderTask,
    BagelItemTask,
    CoffeeItemTask,
    MenuItemTask,
    SpeedMenuBagelItemTask,
)
from .field_config import MenuFieldConfig

logger = logging.getLogger(__name__)

# Default modifier prices for cart display breakdown
# These should match the values in state_machine.py DEFAULT_MODIFIER_PRICES
DEFAULT_MODIFIER_PRICES = {
    # Proteins
    "ham": 2.00,
    "bacon": 2.00,
    "egg": 1.50,
    "turkey": 2.50,
    "pastrami": 3.00,
    "sausage": 2.00,
    "lox": 5.00,
    "nova": 5.00,
    # Cheeses
    "american": 0.75,
    "swiss": 0.75,
    "cheddar": 0.75,
    "muenster": 0.75,
    "provolone": 0.75,
    # Spreads
    "cream cheese": 1.50,
    "butter": 0.50,
    # Toppings
    "tomato": 0.50,
    "onion": 0.50,
    "lettuce": 0.50,
    "avocado": 2.00,
}

# Base bagel price
DEFAULT_BAGEL_BASE_PRICE = 2.50


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
                needs_cheese_clarification=item.get("needs_cheese_clarification", False),
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

    # Restore conversation history if present
    task_state = order_dict.get("task_orchestrator_state", {})  # Legacy key name
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
            menu_item_name = item.menu_item_name
            menu_item_type = getattr(item, 'menu_item_type', None)

            # Build display name with bagel choice, side choice, and toasted status
            display_name = menu_item_name
            if menu_item_type in ("spread_sandwich", "salad_sandwich") and bagel_choice:
                display_name = f"{menu_item_name} on {bagel_choice} bagel"
            # Add side choice for omelettes (bagel or fruit salad)
            if side_choice == "fruit_salad":
                display_name = f"{display_name} with fruit salad"
            elif side_choice == "bagel" and bagel_choice:
                display_name = f"{display_name} with {bagel_choice} bagel"
            elif side_choice == "bagel":
                display_name = f"{display_name} with bagel"
            if toasted is True:
                display_name = f"{display_name} toasted"
            elif toasted is False and menu_item_type in ("spread_sandwich", "salad_sandwich"):
                display_name = f"{display_name} not toasted"

            item_dict = {
                "item_type": "menu_item",
                "id": item.id,  # Preserve item ID
                "status": item.status.value,
                "menu_item_name": menu_item_name,  # Keep original name (no side choice)
                "display_name": display_name,  # Full display with bagel choice and toasted
                "menu_item_id": getattr(item, 'menu_item_id', None),
                "menu_item_type": menu_item_type,
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

            # Build display name (just the base bagel, modifiers shown separately)
            display_name = f"{bagel_type} bagel" if bagel_type else "bagel"
            if toasted:
                display_name += " toasted"

            # Build modifiers list with prices for itemized cart display
            modifiers = []

            # Add protein modifier
            if sandwich_protein:
                protein_price = DEFAULT_MODIFIER_PRICES.get(sandwich_protein.lower(), 0.0)
                modifiers.append({
                    "name": sandwich_protein,
                    "price": protein_price,
                })

            # Add extras (additional proteins, cheeses, toppings)
            for extra in extras:
                extra_price = DEFAULT_MODIFIER_PRICES.get(extra.lower(), 0.0)
                modifiers.append({
                    "name": extra,
                    "price": extra_price,
                })

            # Add spread if not "none"
            if spread and spread.lower() != "none":
                spread_name = spread
                if spread_type and spread_type != "plain":
                    spread_name = f"{spread_type} {spread}"
                spread_price = DEFAULT_MODIFIER_PRICES.get(spread.lower(), 0.0)
                modifiers.append({
                    "name": spread_name,
                    "price": spread_price,
                })

            # Calculate base price (total - modifiers)
            total_price = item.unit_price or 0
            modifiers_total = sum(m["price"] for m in modifiers)
            base_price = max(total_price - modifiers_total, DEFAULT_BAGEL_BASE_PRICE)

            item_dict = {
                "item_type": "bagel",
                "id": item.id,  # Preserve item ID
                "status": item.status.value,
                "display_name": display_name,
                "menu_item_name": display_name,  # For backwards compatibility
                "bagel_type": bagel_type,
                "spread": spread,
                "spread_type": spread_type,
                "toasted": toasted,
                "sandwich_protein": getattr(item, 'sandwich_protein', None),
                "extras": getattr(item, 'extras', []),
                "needs_cheese_clarification": getattr(item, 'needs_cheese_clarification', False),
                "base_price": base_price,
                "modifiers": modifiers,
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

    # Preserve conversation history (legacy key name for compatibility)
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
        "pending_drink_options": order.pending_drink_options,  # Multiple drink options for disambiguation
    }

    return order_dict
