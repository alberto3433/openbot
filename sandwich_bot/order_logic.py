from copy import deepcopy
from typing import Dict, Any, Optional, List


def _find_menu_item(menu_index: Dict[str, Any], item_name: str) -> Optional[Dict[str, Any]]:
    """
    Find a menu item by name across all categories.
    Returns the full menu item dict including recipe and choice_groups.
    """
    if not menu_index or not item_name:
        return None

    # Search through all category lists
    categories = [
        "signature_sandwiches",
        "custom_sandwiches",
        "sides",
        "drinks",
        "desserts",
        "other",
    ]

    for category in categories:
        items = menu_index.get(category, [])
        for item in items:
            if item.get("name", "").lower() == item_name.lower():
                return item

    return None


def _get_custom_sandwich_base(menu_index: Dict[str, Any]) -> Dict[str, Any]:
    """Get the Custom Sandwich menu item for pricing non-signature sandwiches."""
    custom_sandwiches = menu_index.get("custom_sandwiches", [])
    for item in custom_sandwiches:
        if item.get("name", "").lower() == "custom sandwich":
            return item
    # Fallback with default price
    return {"name": "Custom Sandwich", "base_price": 5.99}


def _calculate_custom_sandwich_price(
    menu_index: Dict[str, Any],
    protein: str = None,
    bread: str = None,
) -> float:
    """
    Calculate the price for a custom/build-your-own sandwich.

    Price = Custom Sandwich base price + protein price + bread premium
    """
    custom_item = _get_custom_sandwich_base(menu_index)
    base_price = custom_item.get("base_price", 5.99)

    # Add protein price
    protein_prices = menu_index.get("protein_prices", {})
    if protein:
        protein_price = protein_prices.get(protein.lower(), 0.0)
        base_price += protein_price

    # Add bread premium
    bread_prices = menu_index.get("bread_prices", {})
    if bread:
        bread_price = bread_prices.get(bread.lower(), 0.0)
        base_price += bread_price

    return base_price


def _is_custom_sandwich_order(item_name: str, menu_index: Dict[str, Any]) -> bool:
    """
    Determine if an order should be treated as a custom sandwich.

    Returns True if:
    - The item name is explicitly "Custom Sandwich"
    - The item name contains a protein name (e.g., "turkey sandwich", "ham sub")
    - The item name is not found in the menu
    """
    if not item_name:
        return False

    name_lower = item_name.lower()

    # Explicit custom sandwich
    if "custom" in name_lower:
        return True

    # Check if it's a known menu item
    menu_item = _find_menu_item(menu_index, item_name)
    if menu_item and menu_item.get("is_signature"):
        return False  # It's a signature sandwich

    # Check if the name contains a protein (e.g., "turkey sandwich", "ham sub")
    protein_types = menu_index.get("protein_types", [])
    for protein in protein_types:
        if protein.lower() in name_lower:
            return True

    # If not found in menu at all, treat as custom
    if not menu_item:
        return True

    return False


def _extract_protein_from_name(item_name: str, menu_index: Dict[str, Any]) -> Optional[str]:
    """Extract protein name from a sandwich order like 'turkey sandwich'."""
    if not item_name:
        return None

    name_lower = item_name.lower()
    protein_types = menu_index.get("protein_types", [])

    for protein in protein_types:
        if protein.lower() in name_lower:
            return protein

    return None


def _get_extra_price_for_choice(
    menu_item: Dict[str, Any],
    choice_group_name: str,
    choice_value: str,
    menu_index: Dict[str, Any] = None
) -> float:
    """
    Look up the extra_price for a specific customization choice.

    First tries the generic item_types system, then falls back to recipe data.

    Args:
        menu_item: The menu item dict with recipe data
        choice_group_name: The group name (e.g., "Bread", "Cheese")
        choice_value: The selected choice name (e.g., "Wheat", "Swiss")
        menu_index: Optional menu index dict containing generic item_types

    Returns:
        The extra_price for this choice, or 0.0 if not found
    """
    if not choice_value:
        return 0.0

    # Try generic item_types system first (if menu_index provided)
    if menu_index:
        item_types = menu_index.get("item_types", {})
        # Map choice_group_name to attribute slug
        attr_slug = choice_group_name.lower()
        if attr_slug == "sauce":
            attr_slug = "sauces"

        # Get the item type for the menu item (default to "sandwich")
        item_type_slug = "sandwich"
        if menu_item:
            item_type_slug = menu_item.get("item_type", "sandwich") or "sandwich"

        item_type_data = item_types.get(item_type_slug, {})
        if item_type_data.get("is_configurable"):
            for attr in item_type_data.get("attributes", []):
                if attr.get("slug") == attr_slug:
                    for opt in attr.get("options", []):
                        opt_name = opt.get("display_name", "").lower()
                        opt_slug = opt.get("slug", "").lower()
                        choice_lower = choice_value.lower()
                        if opt_name == choice_lower or opt_slug == choice_lower:
                            return float(opt.get("price_modifier", 0.0))

    # Fall back to recipe-based lookup
    if not menu_item:
        return 0.0

    recipe = menu_item.get("recipe")
    if not recipe:
        return 0.0

    choice_groups = recipe.get("choice_groups", [])
    for group in choice_groups:
        if group.get("name", "").lower() == choice_group_name.lower():
            for option in group.get("options", []):
                if option.get("name", "").lower() == choice_value.lower():
                    return float(option.get("extra_price", 0.0))

    return 0.0


def _calculate_customization_extras(
    menu_item: Dict[str, Any],
    bread: str = None,
    cheese: str = None,
    protein: str = None,
    toppings: List[str] = None,
    sauces: List[str] = None,
    menu_index: Dict[str, Any] = None,
) -> float:
    """
    Calculate the total extra price from all customization choices.

    Uses the generic item_types system when available, falls back to recipe data.
    """
    total_extra = 0.0

    if bread:
        total_extra += _get_extra_price_for_choice(menu_item, "Bread", bread, menu_index)
    if cheese:
        total_extra += _get_extra_price_for_choice(menu_item, "Cheese", cheese, menu_index)
    if protein:
        total_extra += _get_extra_price_for_choice(menu_item, "Protein", protein, menu_index)

    # Toppings and sauces can have multiple selections
    for topping in (toppings or []):
        total_extra += _get_extra_price_for_choice(menu_item, "Toppings", topping, menu_index)
    for sauce in (sauces or []):
        total_extra += _get_extra_price_for_choice(menu_item, "Sauce", sauce, menu_index)

    return total_extra


def apply_intent_to_order_state(order_state, intent, slots, menu_index=None, returning_customer=None):
    state = deepcopy(order_state)

    if intent == "add_sandwich":
        return _add_sandwich(state, slots, menu_index)

    if intent == "add_pizza":
        return _add_pizza(state, slots, menu_index)

    if intent in ("add_drink", "add_coffee", "add_sized_beverage", "add_beverage"):
        return _add_drink(state, slots, menu_index)

    if intent == "add_side":
        return _add_side(state, slots, menu_index)

    if intent == "update_sandwich":
        return _update_sandwich(state, slots, menu_index)

    if intent == "update_pizza":
        return _update_pizza(state, slots, menu_index)

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

    # Copy all items from the previous order
    total_price = 0.0
    for prev_item in last_order_items:
        item = {
            "item_type": prev_item.get("item_type", "sandwich"),
            "menu_item_name": prev_item.get("menu_item_name"),
            "bread": prev_item.get("bread"),
            "protein": prev_item.get("protein"),
            "cheese": prev_item.get("cheese"),
            "toppings": prev_item.get("toppings") or [],
            "sauces": prev_item.get("sauces") or [],
            "toasted": prev_item.get("toasted", False),
            "quantity": prev_item.get("quantity", 1),
            "unit_price": prev_item.get("price", 0.0),
        }
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


def _add_sandwich(state, slots, menu_index):
    """
    Add a sandwich to the order.

    Handles both signature sandwiches and custom/build-your-own sandwiches.
    """
    name = slots.get("menu_item_name")
    qty = slots.get("quantity") or 1

    # Get sandwich-specific customization choices
    bread = slots.get("bread")
    protein = slots.get("protein")
    cheese = slots.get("cheese")
    toppings = slots.get("toppings") or []
    sauces = slots.get("sauces") or []
    size = slots.get("size")

    # Check if this should be treated as a custom sandwich
    is_custom = _is_custom_sandwich_order(name, menu_index)

    if is_custom:
        # Custom sandwich pricing: base + protein + bread premium
        if not protein:
            protein = _extract_protein_from_name(name, menu_index)
        unit_price = _calculate_custom_sandwich_price(menu_index, protein, bread)
        display_name = "Custom Sandwich"
        if protein:
            display_name = f"Custom {protein} Sandwich"
    else:
        # Signature sandwich pricing: base price + customization extras
        menu_item = _find_menu_item(menu_index, name)
        base = menu_item.get("base_price", 0) if menu_item else 0

        # Calculate extra price from customizations
        extras = _calculate_customization_extras(
            menu_item, bread, cheese, protein, toppings, sauces, menu_index
        )

        unit_price = base + extras
        display_name = name

    line_total = unit_price * qty

    item = {
        "item_type": "sandwich",
        "menu_item_name": display_name,
        "size": size,
        "bread": bread,
        "protein": protein,
        "cheese": cheese,
        "toppings": toppings,
        "sauces": sauces,
        "toasted": slots.get("toasted"),
        "quantity": qty,
        "unit_price": unit_price,
        "line_total": line_total,
        "is_custom": is_custom,
    }

    state["items"].append(item)
    state["status"] = "collecting_items"
    return state


def _add_pizza(state, slots, menu_index):
    """
    Add a pizza to the order.

    Handles both signature pizzas and custom/build-your-own pizzas.
    Pizza-specific attributes: size, crust, sauce, cheese, toppings.
    """
    name = slots.get("menu_item_name")
    qty = slots.get("quantity") or 1

    # Get pizza-specific customization choices
    size = slots.get("size")
    crust = slots.get("crust")
    cheese = slots.get("cheese")
    toppings = slots.get("toppings") or []
    # Handle both single sauce (typical for pizza) and sauces array
    sauce = slots.get("sauce")
    sauces = slots.get("sauces") or []
    if sauce and not sauces:
        sauces = [sauce]

    # Check if this is a custom/build-your-own pizza
    is_custom = _is_custom_pizza_order(name, menu_index)

    if is_custom:
        # For custom pizza, use Build Your Own Pizza as the base
        menu_item = _find_menu_item(menu_index, "Build Your Own Pizza")
        base = menu_item.get("base_price", 10.99) if menu_item else 10.99

        # Calculate price adjustments for size
        size_extra = _get_size_price_adjustment(size, menu_item, menu_index)

        # Calculate extras for toppings, cheese, etc.
        extras = _calculate_pizza_extras(menu_item, crust, cheese, toppings, sauces, menu_index)

        unit_price = base + size_extra + extras
        display_name = "Build Your Own Pizza"
    else:
        # Signature pizza pricing: base price + customization extras
        menu_item = _find_menu_item(menu_index, name)
        base = menu_item.get("base_price", 0) if menu_item else 0

        # Calculate price adjustments for size (signature pizzas also vary by size)
        size_extra = _get_size_price_adjustment(size, menu_item, menu_index)

        # Calculate extras for additional toppings, cheese upgrades, etc.
        extras = _calculate_pizza_extras(menu_item, crust, cheese, toppings, sauces, menu_index)

        unit_price = base + size_extra + extras
        display_name = name

    line_total = unit_price * qty

    item = {
        "item_type": "pizza",
        "menu_item_name": display_name,
        "size": size,
        "crust": crust,
        "cheese": cheese,
        "toppings": toppings,
        "sauces": sauces,
        "quantity": qty,
        "unit_price": unit_price,
        "line_total": line_total,
        "is_custom": is_custom,
    }

    state["items"].append(item)
    state["status"] = "collecting_items"
    return state


def _is_custom_pizza_order(item_name: str, menu_index: Dict[str, Any]) -> bool:
    """
    Determine if a pizza order should be treated as a custom/build-your-own pizza.

    Returns True if:
    - The item name explicitly indicates custom/build-your-own
    - The item name is not found in the menu as a signature pizza
    """
    if not item_name:
        return True  # No name = custom pizza

    name_lower = item_name.lower()

    # Explicit custom indicators
    if "custom" in name_lower or "build your own" in name_lower or "create your own" in name_lower:
        return True

    # Check if it's a known signature menu item
    menu_item = _find_menu_item(menu_index, item_name)
    if menu_item and menu_item.get("is_signature"):
        return False

    # If not found in menu at all, treat as custom
    if not menu_item:
        return True

    return False


def _calculate_pizza_extras(
    menu_item: Dict[str, Any],
    crust: str = None,
    cheese: str = None,
    toppings: List[str] = None,
    sauces: List[str] = None,
    menu_index: Dict[str, Any] = None
) -> float:
    """
    Calculate extra price for pizza customizations.

    Premium crusts, extra cheese, and premium toppings may have additional costs.
    """
    total_extra = 0.0

    # Crust upgrades (e.g., Stuffed Crust might cost extra)
    if crust:
        total_extra += _get_extra_price_for_choice(menu_item, "Crust", crust, menu_index)

    # Cheese upgrades (e.g., Extra Mozzarella)
    if cheese:
        total_extra += _get_extra_price_for_choice(menu_item, "Cheese", cheese, menu_index)

    # Toppings (each topping may have a price)
    for topping in (toppings or []):
        total_extra += _get_extra_price_for_choice(menu_item, "Toppings", topping, menu_index)

    # Sauce (usually no extra charge, but premium sauces might)
    for sauce in (sauces or []):
        total_extra += _get_extra_price_for_choice(menu_item, "Sauce", sauce, menu_index)

    return total_extra


def _get_size_price_adjustment(size: str, menu_item: Dict[str, Any], menu_index: Dict[str, Any]) -> float:
    """
    Get the price adjustment for a specific size.

    Sizes typically have price modifiers (e.g., Small=0, Medium=+2, Large=+4).
    """
    if not size:
        return 0.0

    return _get_extra_price_for_choice(menu_item, "Size", size, menu_index)


def _add_drink(state, slots, menu_index):
    name = slots.get("menu_item_name")
    qty = slots.get("quantity") or 1
    size = slots.get("size")
    item_config = slots.get("item_config") or {}

    # LLM might put coffee attributes directly in slots instead of item_config
    # Merge them into item_config for consistent handling
    coffee_attrs = ["style", "milk", "syrup", "sweetener", "extras"]
    for attr in coffee_attrs:
        if attr in slots and slots[attr] and attr not in item_config:
            item_config[attr] = slots[attr]

    # Size can come from slots directly or from item_config
    if not size and item_config:
        size = item_config.get("size")

    menu_item = _find_menu_item(menu_index, name)
    base = menu_item.get("base_price", 0) if menu_item else 0

    # Check if this is a configurable drink (like coffee with sizes and customizations)
    item_type_slug = menu_item.get("item_type") if menu_item else None
    total_modifier = 0.0

    if item_type_slug:
        item_type_data = menu_index.get("item_types", {}).get(item_type_slug, {})
        if item_type_data.get("is_configurable"):
            # Calculate price modifiers for ALL selected options
            for attr in item_type_data.get("attributes", []):
                attr_slug = attr.get("slug")
                # Check item_config first, then direct slots
                attr_value = item_config.get(attr_slug) or slots.get(attr_slug)

                # Also check direct slots for size
                if attr_slug == "size" and not attr_value:
                    attr_value = size

                if not attr_value:
                    continue

                # Handle both single values and lists (for multi_select)
                values = attr_value if isinstance(attr_value, list) else [attr_value]

                for val in values:
                    if not val or str(val).lower() == "none":
                        continue
                    # Normalize the value for matching
                    val_normalized = str(val).lower().replace(" ", "_")
                    # Also try without common suffixes like "_syrup", "_milk"
                    val_base = val_normalized.replace("_syrup", "").replace("_milk", "")

                    for opt in attr.get("options", []):
                        opt_slug = opt.get("slug", "")
                        # Match on exact slug, normalized value, or base value
                        if opt_slug == val_normalized or opt_slug == val_base or opt_slug in val_normalized:
                            total_modifier += opt.get("price_modifier", 0.0)
                            break

    unit_price = base + total_modifier

    # Build a display-friendly item config
    display_config = {}
    if size:
        display_config["size"] = size
    if item_config:
        for key, val in item_config.items():
            if val and str(val).lower() != "none" and key != "size":
                display_config[key] = val

    item = {
        "item_type": "drink",
        "menu_item_name": name,
        "size": size,
        "item_config": display_config if display_config else None,
        "bread": None,
        "protein": None,
        "cheese": None,
        "toppings": [],
        "sauces": [],
        "toasted": None,
        "quantity": qty,
        "unit_price": unit_price,
        "line_total": unit_price * qty,
    }

    state["items"].append(item)
    state["status"] = "collecting_items"
    return state


def _add_side(state, slots, menu_index):
    name = slots.get("menu_item_name")
    qty = slots.get("quantity") or 1

    menu_item = _find_menu_item(menu_index, name)
    base = menu_item.get("base_price", 0) if menu_item else 0

    item = {
        "item_type": "side",
        "menu_item_name": name,
        "size": None,
        "bread": None,
        "protein": None,
        "cheese": None,
        "toppings": [],
        "sauces": [],
        "toasted": None,
        "quantity": qty,
        "unit_price": base,
        "line_total": base * qty,
    }

    state["items"].append(item)
    state["status"] = "collecting_items"
    return state


def _update_sandwich(state, slots, menu_index):
    """
    Update an existing sandwich in the order.
    Uses item_index to identify which item to update.
    Only updates fields that are provided (non-None) in slots.
    Recalculates price including any extra_price from customizations.
    """
    item_index = slots.get("item_index")

    # If no index provided, try to find the last sandwich in the order
    if item_index is None:
        for i in range(len(state["items"]) - 1, -1, -1):
            if state["items"][i].get("item_type") == "sandwich":
                item_index = i
                break

    # Validate index
    if item_index is None or item_index < 0 or item_index >= len(state["items"]):
        # Can't update - no valid item found
        return state

    item = state["items"][item_index]

    # Track if any customization changed (for price recalculation)
    customization_changed = False

    # Only update sandwich-specific fields that are explicitly provided
    if slots.get("bread") is not None:
        item["bread"] = slots["bread"]
        customization_changed = True
    if slots.get("protein") is not None:
        item["protein"] = slots["protein"]
        customization_changed = True
    if slots.get("cheese") is not None:
        item["cheese"] = slots["cheese"]
        customization_changed = True
    if slots.get("toppings") is not None:
        item["toppings"] = slots["toppings"]
        customization_changed = True
    if slots.get("sauces") is not None:
        item["sauces"] = slots["sauces"]
        customization_changed = True
    if slots.get("toasted") is not None:
        item["toasted"] = slots["toasted"]
    if slots.get("size") is not None:
        item["size"] = slots["size"]
    if slots.get("quantity") is not None:
        item["quantity"] = slots["quantity"]

    # If changing to a different menu item
    if slots.get("menu_item_name") is not None:
        item["menu_item_name"] = slots["menu_item_name"]
        customization_changed = True

    # Recalculate price if customizations changed
    if customization_changed or slots.get("quantity") is not None:
        menu_item = _find_menu_item(menu_index, item["menu_item_name"])
        base = menu_item.get("base_price", 0) if menu_item else item.get("unit_price", 0)

        extras = _calculate_customization_extras(
            menu_item,
            item.get("bread"),
            item.get("cheese"),
            item.get("protein"),
            item.get("toppings"),
            item.get("sauces"),
            menu_index,
        )

        item["unit_price"] = base + extras
        item["line_total"] = item["unit_price"] * item["quantity"]

    return state


def _update_pizza(state, slots, menu_index):
    """
    Update an existing pizza in the order.
    Uses item_index to identify which item to update.
    Only updates fields that are provided (non-None) in slots.
    Recalculates price including size and customization extras.
    """
    item_index = slots.get("item_index")

    # If no index provided, try to find the last pizza in the order
    if item_index is None:
        for i in range(len(state["items"]) - 1, -1, -1):
            if state["items"][i].get("item_type") == "pizza":
                item_index = i
                break

    # Validate index
    if item_index is None or item_index < 0 or item_index >= len(state["items"]):
        # Can't update - no valid item found
        return state

    item = state["items"][item_index]

    # Track if any customization changed (for price recalculation)
    customization_changed = False

    # Only update pizza-specific fields that are explicitly provided
    if slots.get("size") is not None:
        item["size"] = slots["size"]
        customization_changed = True
    if slots.get("crust") is not None:
        item["crust"] = slots["crust"]
        customization_changed = True
    if slots.get("cheese") is not None:
        item["cheese"] = slots["cheese"]
        customization_changed = True
    if slots.get("toppings") is not None:
        item["toppings"] = slots["toppings"]
        customization_changed = True
    # Handle both single sauce and sauces array
    if slots.get("sauce") is not None:
        item["sauces"] = [slots["sauce"]]
        customization_changed = True
    if slots.get("sauces") is not None:
        item["sauces"] = slots["sauces"]
        customization_changed = True
    if slots.get("quantity") is not None:
        item["quantity"] = slots["quantity"]

    # If changing to a different menu item
    if slots.get("menu_item_name") is not None:
        item["menu_item_name"] = slots["menu_item_name"]
        customization_changed = True

    # Recalculate price if customizations changed
    if customization_changed or slots.get("quantity") is not None:
        menu_item = _find_menu_item(menu_index, item["menu_item_name"])
        base = menu_item.get("base_price", 0) if menu_item else item.get("unit_price", 0)

        # Calculate size adjustment
        size_extra = _get_size_price_adjustment(item.get("size"), menu_item, menu_index)

        # Calculate pizza-specific extras
        extras = _calculate_pizza_extras(
            menu_item,
            item.get("crust"),
            item.get("cheese"),
            item.get("toppings"),
            item.get("sauces"),
            menu_index,
        )

        item["unit_price"] = base + size_extra + extras
        item["line_total"] = item["unit_price"] * item["quantity"]

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
    """

    total = 0
    for it in state["items"]:
        menu_item = _find_menu_item(menu_index, it["menu_item_name"])
        base = menu_item.get("base_price", 0) if menu_item else it.get("unit_price", 0)

        # Calculate extras based on item type
        extras = 0.0
        item_type = it.get("item_type")

        if item_type == "pizza":
            # Pizza-specific pricing: size + crust + cheese + toppings + sauce
            size_extra = _get_size_price_adjustment(it.get("size"), menu_item, menu_index)
            extras = size_extra + _calculate_pizza_extras(
                menu_item,
                it.get("crust"),
                it.get("cheese"),
                it.get("toppings"),
                it.get("sauces"),
                menu_index,
            )
        elif item_type == "sandwich":
            # Sandwich-specific pricing: bread + cheese + protein + toppings + sauces
            extras = _calculate_customization_extras(
                menu_item,
                it.get("bread"),
                it.get("cheese"),
                it.get("protein"),
                it.get("toppings"),
                it.get("sauces"),
                menu_index,
            )
        elif item_type == "drink":
            # Drink-specific pricing: use item_config for coffee modifiers
            # Keep the existing unit_price which was calculated correctly in _add_drink
            extras = it.get("unit_price", base) - base  # Preserve existing extras

        it["unit_price"] = base + extras
        it["line_total"] = it["unit_price"] * it["quantity"]
        total += it["line_total"]

    state["total_price"] = total

    # *** ABSOLUTELY REQUIRED ***
    state["status"] = "confirmed"

    return state
