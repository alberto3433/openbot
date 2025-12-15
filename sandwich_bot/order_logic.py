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
    choice_value: str
) -> float:
    """
    Look up the extra_price for a specific customization choice.

    Args:
        menu_item: The menu item dict with recipe data
        choice_group_name: The group name (e.g., "Bread", "Cheese")
        choice_value: The selected choice name (e.g., "Wheat", "Swiss")

    Returns:
        The extra_price for this choice, or 0.0 if not found
    """
    if not menu_item or not choice_value:
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
) -> float:
    """
    Calculate the total extra price from all customization choices.
    """
    total_extra = 0.0

    if bread:
        total_extra += _get_extra_price_for_choice(menu_item, "Bread", bread)
    if cheese:
        total_extra += _get_extra_price_for_choice(menu_item, "Cheese", cheese)
    if protein:
        total_extra += _get_extra_price_for_choice(menu_item, "Protein", protein)

    # Toppings and sauces can have multiple selections
    for topping in (toppings or []):
        total_extra += _get_extra_price_for_choice(menu_item, "Toppings", topping)
    for sauce in (sauces or []):
        total_extra += _get_extra_price_for_choice(menu_item, "Sauce", sauce)

    return total_extra


def apply_intent_to_order_state(order_state, intent, slots, menu_index=None, returning_customer=None):
    state = deepcopy(order_state)

    if intent == "add_sandwich":
        return _add_sandwich(state, slots, menu_index)

    if intent == "add_drink":
        return _add_drink(state, slots, menu_index)

    if intent == "add_side":
        return _add_side(state, slots, menu_index)

    if intent == "update_sandwich":
        return _update_sandwich(state, slots, menu_index)

    if intent == "remove_item":
        return _remove_item(state, slots, menu_index)

    if intent == "confirm_order":
        return _confirm(state, slots, menu_index)

    if intent == "repeat_order":
        return _repeat_order(state, slots, menu_index, returning_customer)

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
    name = slots.get("menu_item_name")
    qty = slots.get("quantity") or 1

    # Get customization choices
    bread = slots.get("bread")
    protein = slots.get("protein")
    cheese = slots.get("cheese")
    toppings = slots.get("toppings") or []
    sauces = slots.get("sauces") or []

    # Check if this should be treated as a custom sandwich
    is_custom = _is_custom_sandwich_order(name, menu_index)

    if is_custom:
        # Custom sandwich pricing: base + protein + bread premium
        # If protein not provided but name contains one (e.g., "turkey sandwich"), extract it
        if not protein:
            protein = _extract_protein_from_name(name, menu_index)

        unit_price = _calculate_custom_sandwich_price(menu_index, protein, bread)
        display_name = "Custom Sandwich"

        # If we extracted a protein from the name, include it in display
        if protein:
            display_name = f"Custom {protein} Sandwich"
    else:
        # Signature sandwich pricing: base price + customization extras
        menu_item = _find_menu_item(menu_index, name)
        base = menu_item.get("base_price", 0) if menu_item else 0

        # Calculate extra price from customizations
        extras = _calculate_customization_extras(
            menu_item, bread, cheese, protein, toppings, sauces
        )

        unit_price = base + extras
        display_name = name

    line_total = unit_price * qty

    item = {
        "item_type": "sandwich",
        "menu_item_name": display_name,
        "size": slots.get("size"),
        "bread": bread,
        "protein": protein,
        "cheese": cheese,
        "toppings": toppings,
        "sauces": sauces,
        "toasted": slots.get("toasted"),
        "quantity": qty,
        "unit_price": unit_price,
        "line_total": line_total,
        "is_custom": is_custom,  # Track if this is a custom sandwich
    }

    state["items"].append(item)
    state["status"] = "collecting_items"
    return state


def _add_drink(state, slots, menu_index):
    name = slots.get("menu_item_name")
    qty = slots.get("quantity") or 1

    menu_item = _find_menu_item(menu_index, name)
    base = menu_item.get("base_price", 0) if menu_item else 0

    item = {
        "item_type": "drink",
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
    Update an existing sandwich item in the order.
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

    # Only update fields that are explicitly provided
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
        )

        item["unit_price"] = base + extras
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

        # Calculate extras for sandwiches with customizations
        extras = 0.0
        if it.get("item_type") == "sandwich":
            extras = _calculate_customization_extras(
                menu_item,
                it.get("bread"),
                it.get("cheese"),
                it.get("protein"),
                it.get("toppings"),
                it.get("sauces"),
            )

        it["unit_price"] = base + extras
        it["line_total"] = it["unit_price"] * it["quantity"]
        total += it["line_total"]

    state["total_price"] = total

    # *** ABSOLUTELY REQUIRED ***
    state["status"] = "confirmed"

    return state
