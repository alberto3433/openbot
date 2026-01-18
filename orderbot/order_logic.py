from copy import deepcopy
from typing import Dict, Any, Optional, List


def _find_menu_item(menu_index: Dict[str, Any], item_name: str) -> Optional[Dict[str, Any]]:
    """
    Find a menu item by name across all item types.
    Returns the full menu item dict including default_config.
    """
    if not menu_index or not item_name:
        return None

    # Search through items_by_type (data-driven from database)
    items_by_type = menu_index.get("items_by_type", {})
    for type_slug, items in items_by_type.items():
        if isinstance(items, list):
            for item in items:
                if item.get("name", "").lower() == item_name.lower():
                    return item

    return None


def _get_extra_price_for_choice(
    attr_slug: str,
    choice_value: str,
    item_type_slug: str,
    menu_index: Dict[str, Any],
) -> float:
    """
    Look up the price modifier for a specific attribute choice.

    Uses the generic item_types system to look up price modifiers.
    This is a pure data-driven function with no hardcoded item types or attributes.

    Args:
        attr_slug: The attribute slug (e.g., "bread", "cheese", "size")
        choice_value: The selected choice name (e.g., "wheat", "swiss")
        item_type_slug: The item type slug (e.g., "sandwich", "pizza")
        menu_index: Menu index dict containing item_types configuration

    Returns:
        The price_modifier for this choice, or 0.0 if not found
    """
    if not choice_value or not attr_slug or not item_type_slug or not menu_index:
        return 0.0

    item_types = menu_index.get("item_types", {})
    item_type_data = item_types.get(item_type_slug, {})

    if not item_type_data.get("is_configurable"):
        return 0.0

    for attr in item_type_data.get("attributes", []):
        if attr.get("slug") == attr_slug:
            choice_lower = choice_value.lower()
            for opt in attr.get("options", []):
                opt_name = opt.get("display_name", "").lower()
                opt_slug = opt.get("slug", "").lower()
                if opt_name == choice_lower or opt_slug == choice_lower:
                    return float(opt.get("price_modifier", 0.0))

    return 0.0


def _calculate_item_extras_generic(
    item: Dict[str, Any],
    menu_item: Dict[str, Any],
    menu_index: Dict[str, Any],
) -> float:
    """
    Calculate extras for any item type using the generic item_types system.

    Iterates through all attributes defined for the item's type and calculates
    price modifiers for any attribute values present on the item.

    This is the data-driven approach - no hardcoded item types.
    """
    if not menu_index:
        return 0.0

    item_type_slug = item.get("item_type")
    if not item_type_slug:
        # Fall back to menu_item's type if available
        item_type_slug = menu_item.get("item_type") if menu_item else None

    if not item_type_slug:
        return 0.0

    item_types = menu_index.get("item_types", {})
    item_type_data = item_types.get(item_type_slug, {})

    if not item_type_data.get("is_configurable"):
        return 0.0

    total_extra = 0.0
    item_config = item.get("item_config", {})

    for attr in item_type_data.get("attributes", []):
        attr_slug = attr.get("slug")
        if not attr_slug:
            continue

        # Check both item top-level and item_config for attribute values
        attr_value = item.get(attr_slug) or item_config.get(attr_slug)
        if not attr_value:
            continue

        # Handle list attributes (toppings, sauces, extras)
        if isinstance(attr_value, list):
            for val in attr_value:
                total_extra += _get_extra_price_for_choice(
                    attr_slug, val, item_type_slug, menu_index
                )
        else:
            total_extra += _get_extra_price_for_choice(
                attr_slug, attr_value, item_type_slug, menu_index
            )

    return total_extra


def _get_item_type_attribute_slugs(item_type_slug: str, menu_index: Dict[str, Any]) -> list[str]:
    """Get list of attribute slugs for an item type from menu_index."""
    if not menu_index or not item_type_slug:
        return []
    item_types = menu_index.get("item_types", {})
    item_type_data = item_types.get(item_type_slug, {})
    return [attr.get("slug") for attr in item_type_data.get("attributes", []) if attr.get("slug")]


def _add_item(state, slots, menu_index):
    """
    Generic handler to add any item type to the order.

    Uses data-driven approach: looks up item type from menu, gets valid attributes
    for that type, and copies matching slot values. No hardcoded item types.
    """
    name = slots.get("menu_item_name")
    qty = slots.get("quantity") or 1

    # Look up the menu item to get item_type and base_price
    menu_item = _find_menu_item(menu_index, name)
    item_type = menu_item.get("item_type") if menu_item else slots.get("item_type")
    base_price = menu_item.get("base_price", 0) if menu_item else 0

    # Build item dict with common fields
    item = {
        "item_type": item_type,
        "menu_item_name": name,
        "quantity": qty,
    }

    # Get valid attributes for this item type and copy from slots
    if item_type and menu_index:
        attr_slugs = _get_item_type_attribute_slugs(item_type, menu_index)
        for attr_slug in attr_slugs:
            if attr_slug in slots:
                value = slots[attr_slug]
                # Ensure list attributes are lists
                if attr_slug in ("toppings", "sauces", "extras") and value is None:
                    value = []
                item[attr_slug] = value

    # Also check item_config dict (used by some callers like drinks)
    item_config = slots.get("item_config") or {}
    if item_config:
        item["item_config"] = item_config
        # Merge item_config values into item for pricing calculation
        for key, val in item_config.items():
            if key not in item and val is not None:
                item[key] = val

    # Handle sauce → sauces normalization
    if "sauce" in slots and slots["sauce"] and "sauces" not in item:
        item["sauces"] = [slots["sauce"]]

    # Calculate price using generic data-driven approach
    extras = _calculate_item_extras_generic(item, menu_item, menu_index)
    unit_price = base_price + extras

    item["unit_price"] = unit_price
    item["line_total"] = unit_price * qty

    state["items"].append(item)
    state["status"] = "collecting_items"
    return state


def _update_item(state, slots, menu_index):
    """
    Generic handler to update any item in the order.

    Finds the item by index or by finding the last item of the target type.
    Updates only the attributes that are provided in slots.
    """
    item_index = slots.get("item_index")
    target_type = slots.get("item_type")  # Optional: find by item type

    # If no index provided, find the last matching item
    if item_index is None:
        for i in range(len(state["items"]) - 1, -1, -1):
            candidate = state["items"][i]
            # If target_type specified, match on that
            if target_type and candidate.get("item_type") == target_type:
                item_index = i
                break
            # Otherwise, just use the last item
            elif not target_type:
                item_index = i
                break

    # Validate index
    if item_index is None or item_index < 0 or item_index >= len(state["items"]):
        return state

    item = state["items"][item_index]
    item_type = item.get("item_type")

    # Track if customization changed for price recalculation
    customization_changed = False

    # Get valid attributes for this item type from config
    attr_slugs = set(_get_item_type_attribute_slugs(item_type, menu_index) if item_type else [])

    # Also include item's existing keys as valid attributes (handles cases where
    # item_types config doesn't include all attributes like 'toasted')
    system_fields = {"item_type", "menu_item_name", "quantity", "unit_price", "line_total", "item_config"}
    attr_slugs.update(k for k in item.keys() if k not in system_fields)

    # Update attributes that are provided in slots
    for attr_slug in attr_slugs:
        if slots.get(attr_slug) is not None:
            item[attr_slug] = slots[attr_slug]
            customization_changed = True

    # Handle common fields
    if slots.get("quantity") is not None:
        item["quantity"] = slots["quantity"]
    if slots.get("menu_item_name") is not None:
        item["menu_item_name"] = slots["menu_item_name"]
        customization_changed = True

    # Handle sauce → sauces normalization
    if slots.get("sauce") is not None:
        item["sauces"] = [slots["sauce"]]
        customization_changed = True

    # Recalculate price if needed
    if customization_changed or slots.get("quantity") is not None:
        menu_item = _find_menu_item(menu_index, item["menu_item_name"])
        base = menu_item.get("base_price", 0) if menu_item else item.get("unit_price", 0)
        extras = _calculate_item_extras_generic(item, menu_item, menu_index)
        item["unit_price"] = base + extras
        item["line_total"] = item["unit_price"] * item["quantity"]

    return state


def apply_intent_to_order_state(order_state, intent, slots, menu_index=None, returning_customer=None):
    state = deepcopy(order_state)

    # Generic item handling - route all add/update intents to generic handlers
    if intent == "add_item":
        return _add_item(state, slots, menu_index)

    if intent == "update_item":
        return _update_item(state, slots, menu_index)

    # Backward-compatible aliases for specific item types
    # These all route to the generic handlers
    if intent == "add_sandwich":
        return _add_item(state, slots, menu_index)

    if intent == "add_pizza":
        return _add_item(state, slots, menu_index)

    if intent in ("add_drink", "add_coffee", "add_sized_beverage", "add_beverage"):
        return _add_item(state, slots, menu_index)

    if intent == "add_side":
        return _add_item(state, slots, menu_index)

    if intent == "update_sandwich":
        return _update_item(state, slots, menu_index)

    if intent == "update_pizza":
        return _update_item(state, slots, menu_index)

    if intent == "remove_item":
        return _remove_item(state, slots, menu_index)

    if intent == "confirm_order":
        return _confirm(state, slots, menu_index)

    if intent == "repeat_order":
        return _repeat_order(state, slots, menu_index, returning_customer)

    if intent == "collect_customer_info":
        return _collect_customer_info(state, slots)

    if intent == "set_order_type":
        return _set_order_type(state, slots)

    if intent == "collect_delivery_address":
        return _collect_delivery_address(state, slots)

    if intent == "request_payment_link":
        return _request_payment_link(state, slots)

    if intent == "collect_card_payment":
        return _collect_card_payment(state, slots)

    if intent == "pay_at_pickup":
        return _pay_at_pickup(state, slots)

    return state


def _collect_customer_info(state, slots):
    """
    Store customer name, phone, and email in the order state.
    """
    customer_name = slots.get("customer_name")
    phone = slots.get("phone")
    email = slots.get("customer_email")

    if customer_name or phone or email:
        state.setdefault("customer", {})
        if customer_name:
            state["customer"]["name"] = customer_name
        if phone:
            state["customer"]["phone"] = phone
        if email:
            state["customer"]["email"] = email

    return state


def _set_order_type(state, slots):
    """
    Set whether the order is for pickup or delivery.
    """
    order_type = slots.get("order_type")
    if order_type in ("pickup", "delivery"):
        state["order_type"] = order_type
    return state


def _collect_delivery_address(state, slots):
    """
    Store the delivery address for delivery orders.
    """
    address = slots.get("delivery_address")
    if address:
        state["delivery_address"] = address
        # Ensure order type is set to delivery
        state["order_type"] = "delivery"
    return state


def _request_payment_link(state, slots):
    """
    Customer requested to pay via payment link (SMS or email).
    Sets payment_method to 'card_link' and payment_status to 'pending_payment'.
    Also stores the delivery method (sms or email).
    """
    state["payment_method"] = "card_link"
    state["payment_status"] = "pending_payment"

    # Store the delivery method for the payment link
    link_delivery_method = slots.get("link_delivery_method")
    if link_delivery_method in ("sms", "email"):
        state["link_delivery_method"] = link_delivery_method

    return state


def _collect_card_payment(state, slots):
    """
    Customer provided card details over the phone.
    In production, this would process the payment via Stripe/etc.
    For now, we mock it as successful.
    """
    card_number = slots.get("card_number")
    card_expiry = slots.get("card_expiry")
    card_cvv = slots.get("card_cvv")

    if card_number and card_expiry and card_cvv:
        # Mock payment processing - in production, call payment processor here
        # DO NOT store card details - pass directly to processor
        state["payment_method"] = "card_phone"
        state["payment_status"] = "paid"  # Mock: assume success
    return state


def _pay_at_pickup(state, slots):
    """
    Customer will pay at pickup/delivery (cash or card).
    """
    state["payment_method"] = "pay_later"  # Will pay at store/delivery
    state["payment_status"] = "unpaid"
    return state


def _repeat_order(state, slots, menu_index, returning_customer):
    """
    Repeat the customer's previous order by copying all items.
    """
    if not returning_customer:
        return state

    last_order_items = returning_customer.get("last_order_items", [])
    if not last_order_items:
        return state

    # Clear any existing items before adding the repeat order
    # This prevents duplication if the intent is called multiple times
    state["items"] = []

    # Copy all items from the previous order (passthrough all attributes)
    total_price = 0.0
    for prev_item in last_order_items:
        # Copy all attributes from the previous item
        item = dict(prev_item)

        # Normalize field names: stored orders use "price", state uses "unit_price"
        if "price" in item and "unit_price" not in item:
            item["unit_price"] = item.pop("price")

        # Ensure required fields have defaults
        item.setdefault("quantity", 1)
        item.setdefault("unit_price", 0.0)

        state["items"].append(item)
        total_price += item["unit_price"] * item["quantity"]

    state["total_price"] = total_price
    state["status"] = "building"

    # Also copy the customer info from the returning customer
    if returning_customer.get("name"):
        state["customer"]["name"] = returning_customer["name"]
    if returning_customer.get("phone"):
        state["customer"]["phone"] = returning_customer["phone"]

    return state


def _remove_item(state, slots, menu_index):
    """
    Remove an item from the order.

    Resolution order:
    1. If item_index is provided and valid, remove that item
    2. If menu_item_name is provided, find and remove the first matching item
    3. If neither is provided, remove the last item (original behavior)
    """
    item_index = slots.get("item_index")
    menu_item_name = slots.get("menu_item_name")

    # If no items, nothing to remove
    if not state["items"]:
        return state

    # 1. If explicit index is provided, use it
    if item_index is not None:
        if 0 <= item_index < len(state["items"]):
            state["items"].pop(item_index)
        # else: invalid index, do nothing

    # 2. If menu_item_name is provided, find by name
    elif menu_item_name:
        target_name = menu_item_name.lower()
        for i, item in enumerate(state["items"]):
            item_name = (item.get("menu_item_name") or "").lower()
            if item_name == target_name:
                state["items"].pop(i)
                break
        # If not found, don't remove anything

    # 3. Default: remove the last item
    else:
        state["items"].pop()

    # Update status if cart is now empty
    if not state["items"]:
        state["status"] = "pending"

    return state


def _confirm(state, slots, menu_index):
    """
    Confirm the order:
    - Recalculate all prices including customization extras
    - Always mark status as confirmed when we receive confirm_order

    Uses data-driven pricing - no hardcoded item types.
    """

    total = 0
    for it in state["items"]:
        menu_item = _find_menu_item(menu_index, it["menu_item_name"])
        base = menu_item.get("base_price", 0) if menu_item else it.get("unit_price", 0)

        # Check if this item already has a calculated unit_price (e.g., from _add_drink)
        # that should be preserved. This happens when pricing was calculated at add time.
        existing_price = it.get("unit_price", 0)
        if existing_price > 0 and existing_price != base:
            # Item already has extras calculated - preserve them
            extras = existing_price - base
        else:
            # Calculate extras using the generic data-driven approach
            extras = _calculate_item_extras_generic(it, menu_item, menu_index)

        it["unit_price"] = base + extras
        it["line_total"] = it["unit_price"] * it["quantity"]
        total += it["line_total"]

    state["total_price"] = total

    # *** ABSOLUTELY REQUIRED ***
    state["status"] = "confirmed"

    return state
