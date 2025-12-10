from copy import deepcopy
from typing import Dict, Any, Optional


def apply_intent_to_order_state(order_state, intent, slots, menu_index=None):
    state = deepcopy(order_state)

    if intent == "add_sandwich":
        return _add_sandwich(state, slots, menu_index)

    if intent == "add_drink":
        return _add_drink(state, slots, menu_index)

    if intent == "confirm_order":
        return _confirm(state, slots, menu_index)

    return state


def _add_sandwich(state, slots, menu_index):
    name = slots.get("menu_item_name")
    qty = slots.get("quantity") or 1
    base = menu_index.get(name, {}).get("base_price", 0)
    line_total = base * qty

    item = {
        "item_type": "sandwich",
        "menu_item_name": name,
        "size": slots.get("size"),
        "bread": slots.get("bread"),
        "protein": slots.get("protein"),
        "cheese": slots.get("cheese"),
        "toppings": slots.get("toppings") or [],
        "sauces": slots.get("sauces") or [],
        "toasted": slots.get("toasted"),
        "quantity": qty,
        "unit_price": base,
        "line_total": line_total,
    }

    state["items"].append(item)
    state["status"] = "collecting_items"
    return state


def _add_drink(state, slots, menu_index):
    name = slots.get("menu_item_name")
    qty = slots.get("quantity") or 1
    base = menu_index.get(name, {}).get("base_price", 0)

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


def _confirm(state, slots, menu_index):
    """
    FINAL FIX:
    - Always mark status as confirmed when we receive confirm_order
    - Recalculate totals deterministically
    - LLM does NOT reliably send slots.confirm=True, so we do NOT depend on it
    """

    total = 0
    for it in state["items"]:
        base = menu_index.get(it["menu_item_name"], {}).get("base_price", it["unit_price"])
        it["unit_price"] = base
        it["line_total"] = base * it["quantity"]
        total += it["line_total"]

    state["total_price"] = total

    # *** ABSOLUTELY REQUIRED ***
    state["status"] = "confirmed"

    return state
