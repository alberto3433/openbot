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
from .pricing import PricingEngine
from ..services.tax_utils import calculate_order_total

logger = logging.getLogger(__name__)

# Import modifier prices from PricingEngine to avoid duplication
DEFAULT_MODIFIER_PRICES = PricingEngine.DEFAULT_MODIFIER_PRICES
DEFAULT_BAGEL_BASE_PRICE = PricingEngine.DEFAULT_BAGEL_BASE_PRICE


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
            # Extract spread_price from modifiers if present
            spread_price = None
            item_modifiers = item.get("modifiers") or []
            for mod in item_modifiers:
                if isinstance(mod, dict) and mod.get("name") == item.get("spread"):
                    spread_price = mod.get("price")
                    break
            menu_item = MenuItemTask(
                menu_item_name=item.get("menu_item_name") or "Unknown",
                menu_item_id=item.get("menu_item_id"),
                menu_item_type=item.get("menu_item_type"),
                modifications=item.get("modifications") or [],
                side_choice=item.get("side_choice"),
                bagel_choice=item.get("bagel_choice"),
                toasted=item.get("toasted"),  # For spread/salad sandwiches and omelette side bagels
                spread=item.get("spread"),  # For omelette side bagels
                spread_price=spread_price,  # For itemized display
                requires_side_choice=item.get("requires_side_choice", False),
                quantity=item.get("quantity", 1),
                special_instructions=item.get("special_instructions") or item.get("notes"),
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
                scooped=item.get("scooped"),
                spread=item.get("spread"),
                spread_type=item.get("spread_type"),
                sandwich_protein=item.get("sandwich_protein"),
                extras=item.get("extras") or [],
                special_instructions=item.get("special_instructions") or item.get("notes"),
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
                special_instructions=item.get("special_instructions") or item.get("notes"),
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
            # Handle sweeteners - support both old format (single) and new format (list)
            sweeteners = item_config.get("sweeteners", [])
            if not sweeteners and item_config.get("sweetener"):
                # Convert old format to new format
                sweeteners = [{
                    "type": item_config["sweetener"],
                    "quantity": item_config.get("sweetener_quantity", 1)
                }]

            # Handle flavor syrups - support both old format (single) and new format (list)
            flavor_syrups = item_config.get("flavor_syrups", [])
            if not flavor_syrups and item_config.get("flavor_syrup"):
                # Convert old format to new format
                flavor_syrups = [{
                    "flavor": item_config["flavor_syrup"],
                    "quantity": item_config.get("syrup_quantity", 1)
                }]

            coffee = CoffeeItemTask(
                drink_type=item.get("menu_item_name") or "coffee",
                size=item.get("size") or item_config.get("size"),  # Don't default to medium for skip_config drinks
                milk=item_config.get("milk"),
                cream_level=item_config.get("cream_level"),  # Restore cream level (dark, light, regular)
                sweeteners=sweeteners,
                flavor_syrups=flavor_syrups,
                iced=iced_value,
                decaf=item_config.get("decaf"),  # Restore decaf flag
                # Restore upcharge tracking fields
                size_upcharge=item_config.get("size_upcharge", 0.0),
                milk_upcharge=item_config.get("milk_upcharge", 0.0),
                syrup_upcharge=item_config.get("syrup_upcharge", 0.0),
                iced_upcharge=item_config.get("iced_upcharge", 0.0),
                # Restore pending syrup state for multi-turn syrup ordering
                wants_syrup=item_config.get("wants_syrup", False),
                pending_syrup_quantity=item_config.get("pending_syrup_quantity", 1),
                special_instructions=item.get("special_instructions") or item.get("notes"),
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
            # Restore modifications from item_config (where it's serialized) or top-level
            item_config = item.get("item_config") or {}
            speed_menu_item = SpeedMenuBagelItemTask(
                menu_item_name=item.get("menu_item_name") or "Unknown",
                menu_item_id=item.get("menu_item_id"),
                toasted=item.get("toasted"),
                bagel_choice=item.get("bagel_choice"),
                bagel_choice_upcharge=item.get("bagel_choice_upcharge", 0.0),
                cheese_choice=item.get("cheese_choice"),
                modifications=item_config.get("modifications") or item.get("modifications") or [],
                quantity=item.get("quantity", 1),
                special_instructions=item.get("special_instructions") or item.get("notes"),
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
        order.pending_item_options = sm_state.get("pending_item_options", [])
        order.pending_item_quantity = sm_state.get("pending_item_quantity", 1)
        order.menu_query_pagination = sm_state.get("menu_query_pagination")
        order.config_options_page = sm_state.get("config_options_page", 0)
        order.multi_item_config_names = sm_state.get("multi_item_config_names", [])

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
            spread = getattr(item, 'spread', None)
            menu_item_name = item.menu_item_name
            menu_item_type = getattr(item, 'menu_item_type', None)

            # Build display name with bagel choice and side choice
            # Note: toasted status is shown as a modifier line item, not in display_name
            display_name = menu_item_name
            if menu_item_type in ("spread_sandwich", "salad_sandwich", "fish_sandwich") and bagel_choice:
                display_name = f"{menu_item_name} on {bagel_choice} bagel"
            # Add side choice for omelettes (bagel or fruit salad)
            elif side_choice == "fruit_salad":
                display_name = f"{display_name} with fruit salad"
            elif side_choice == "bagel":
                # Build side bagel description with all details
                if bagel_choice:
                    display_name = f"{display_name} with {bagel_choice} bagel"
                else:
                    display_name = f"{display_name} with bagel"
                # Note: toasted status is shown in modifiers list, not display_name

            # Build side bagel config for omelettes (shown as modifier)
            side_bagel_config = None
            if side_choice == "bagel" and bagel_choice:
                side_bagel_parts = [bagel_choice, "bagel"]
                if toasted is True:
                    side_bagel_parts.append("toasted")
                if spread and spread != "none":
                    side_bagel_parts.append(f"with {spread}")
                side_bagel_config = {
                    "bagel_type": bagel_choice,
                    "toasted": toasted,
                    "spread": spread,
                    "description": " ".join(side_bagel_parts),
                }

            # Build modifiers list with prices for itemized display (like standalone bagels)
            modifiers = []
            # Add toasted as a modifier (no price) for omelette side bagels and spread/salad sandwiches
            if toasted is True and (
                side_choice == "bagel" or
                menu_item_type in ("spread_sandwich", "salad_sandwich", "fish_sandwich")
            ):
                modifiers.append({
                    "name": "Toasted",
                    "price": 0,
                })
            # Add spread with price
            spread_price = getattr(item, 'spread_price', None)
            if spread and spread != "none" and spread_price and spread_price > 0:
                modifiers.append({
                    "name": spread,
                    "price": spread_price,
                })

            # Add user modifications (e.g., "with mayo and mustard") as modifiers with $0 price
            item_modifications = getattr(item, 'modifications', []) or []
            for mod in item_modifications:
                modifiers.append({
                    "name": mod,
                    "price": 0,
                })

            item_dict = {
                "item_type": "menu_item",
                "id": item.id,  # Preserve item ID
                "status": item.status.value,
                "menu_item_name": menu_item_name,  # Keep original name (no side choice)
                "display_name": display_name,  # Full display with bagel choice (toasted shown as modifier)
                "menu_item_id": getattr(item, 'menu_item_id', None),
                "menu_item_type": menu_item_type,
                "modifications": getattr(item, 'modifications', []),
                "modifiers": modifiers,  # Itemized price breakdown (spread, etc.)
                "side_choice": side_choice,
                "bagel_choice": bagel_choice,
                "toasted": toasted,  # For spread/salad sandwiches
                "spread": spread,  # For omelette side bagels
                "side_bagel_config": side_bagel_config,  # Full side bagel details as modifier
                "requires_side_choice": getattr(item, 'requires_side_choice', False),
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_total": item.unit_price * item.quantity if item.unit_price else 0,
                "special_instructions": getattr(item, 'special_instructions', None),
                "item_config": {
                    "menu_item_type": menu_item_type,
                    "side_choice": side_choice,
                    "bagel_choice": bagel_choice,
                    "toasted": toasted,
                    "spread": spread,
                    "modifications": getattr(item, 'modifications', []),
                    # Include modifiers in item_config for database persistence
                    "modifiers": modifiers,
                },
            }
            items.append(item_dict)

        elif item.item_type == "bagel":
            bagel_type = getattr(item, 'bagel_type', None)
            bagel_type_upcharge = getattr(item, 'bagel_type_upcharge', 0.0) or 0.0
            spread = getattr(item, 'spread', None)
            spread_type = getattr(item, 'spread_type', None)
            toasted = getattr(item, 'toasted', None)
            scooped = getattr(item, 'scooped', None)
            sandwich_protein = getattr(item, 'sandwich_protein', None)
            extras = getattr(item, 'extras', []) or []

            # Display name is just "Bagel" - bagel type shown as modifier
            display_name = "Bagel"

            # Build modifiers list with prices for itemized cart display
            modifiers = []

            # Add bagel type as first modifier (always shown, upcharge only for specialty)
            if bagel_type:
                bagel_type_modifier = {
                    "name": bagel_type.title(),  # e.g., "Plain", "Everything", "Gluten Free"
                    "price": bagel_type_upcharge,  # $0.00 for regular, $0.80 for gluten free
                }
                modifiers.append(bagel_type_modifier)

            # Add toasted as a modifier (no price)
            if toasted:
                modifiers.append({
                    "name": "Toasted",
                    "price": 0,
                })

            # Add scooped as a modifier (no price)
            if scooped:
                modifiers.append({
                    "name": "Scooped",
                    "price": 0,
                })

            # Add protein modifier
            if sandwich_protein:
                protein_price = (
                    pricing.lookup_modifier_price(sandwich_protein)
                    if pricing
                    else DEFAULT_MODIFIER_PRICES.get(sandwich_protein.lower(), 0.0)
                )
                modifiers.append({
                    "name": sandwich_protein,
                    "price": protein_price,
                })

            # Add extras (additional proteins, cheeses, toppings)
            for extra in extras:
                extra_price = (
                    pricing.lookup_modifier_price(extra)
                    if pricing
                    else DEFAULT_MODIFIER_PRICES.get(extra.lower(), 0.0)
                )
                modifiers.append({
                    "name": extra,
                    "price": extra_price,
                })

            # Add spread if not "none"
            if spread and spread.lower() != "none":
                spread_name = spread
                if spread_type and spread_type != "plain":
                    spread_name = f"{spread_type} {spread}"
                spread_price = (
                    pricing.lookup_spread_price(spread, spread_type)
                    if pricing
                    else DEFAULT_MODIFIER_PRICES.get(spread.lower(), 0.0)
                )
                modifiers.append({
                    "name": spread_name,
                    "price": spread_price,
                })

            # Base price is the regular bagel price (without specialty upcharge)
            base_price = DEFAULT_BAGEL_BASE_PRICE

            item_dict = {
                "item_type": "bagel",
                "id": item.id,  # Preserve item ID
                "status": item.status.value,
                "display_name": display_name,
                "menu_item_name": display_name,  # For backwards compatibility
                "bagel_type": bagel_type,
                "bagel_type_upcharge": bagel_type_upcharge,
                "spread": spread,
                "spread_type": spread_type,
                "toasted": toasted,
                "scooped": scooped,
                "sandwich_protein": getattr(item, 'sandwich_protein', None),
                "extras": getattr(item, 'extras', []),
                "needs_cheese_clarification": getattr(item, 'needs_cheese_clarification', False),
                "base_price": base_price,
                "modifiers": modifiers,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_total": item.unit_price * item.quantity if item.unit_price else 0,
                "special_instructions": getattr(item, 'special_instructions', None),
                "item_config": {
                    "bagel_type": bagel_type,
                    "bagel_type_upcharge": bagel_type_upcharge,
                    "spread": spread,
                    "spread_type": spread_type,
                    "toasted": toasted,
                    "scooped": scooped,
                    "sandwich_protein": sandwich_protein,
                    "extras": extras,
                    # Include modifiers and base_price for database persistence
                    "modifiers": modifiers,
                    "base_price": base_price,
                },
            }
            items.append(item_dict)

        elif item.item_type == "coffee":
            # Get coffee attributes
            drink_type = getattr(item, 'drink_type', 'coffee')
            size = getattr(item, 'size', None)
            milk = getattr(item, 'milk', None)
            # New list-based fields
            flavor_syrups = getattr(item, 'flavor_syrups', []) or []
            sweeteners = getattr(item, 'sweeteners', []) or []
            iced = getattr(item, 'iced', None)
            decaf = getattr(item, 'decaf', None)
            cream_level = getattr(item, 'cream_level', None)

            # Get upcharges
            size_upcharge = getattr(item, 'size_upcharge', 0.0) or 0.0
            milk_upcharge = getattr(item, 'milk_upcharge', 0.0) or 0.0
            syrup_upcharge = getattr(item, 'syrup_upcharge', 0.0) or 0.0
            iced_upcharge = getattr(item, 'iced_upcharge', 0.0) or 0.0

            # Build modifiers list for itemized display (only items with upcharges)
            modifiers = []
            free_details = []  # Free modifiers go on one line

            # Size with upcharge
            if size:
                if size_upcharge > 0:
                    modifiers.append({"name": size, "price": size_upcharge})
                else:
                    free_details.append(size)

            # Style (hot/iced) - iced has upcharge when applicable
            if iced is True:
                if iced_upcharge > 0:
                    modifiers.append({"name": "iced", "price": iced_upcharge})
                else:
                    free_details.append("iced")
            elif iced is False:
                free_details.append("hot")

            # Decaf - always free
            if decaf is True:
                free_details.append("decaf")

            # Milk with upcharge
            if milk and milk.lower() not in ("none", "black"):
                if milk_upcharge > 0:
                    modifiers.append({"name": f"{milk} milk", "price": milk_upcharge})
                else:
                    free_details.append(f"{milk} milk")
            elif milk and milk.lower() in ("none", "black"):
                free_details.append("black")

            # Flavor syrups with upcharge (show quantity if > 1)
            for syrup_entry in flavor_syrups:
                flavor = syrup_entry.get("flavor", "")
                qty = syrup_entry.get("quantity", 1)
                if flavor:
                    syrup_name = f"{qty} {flavor} syrups" if qty > 1 else f"{flavor} syrup"
                    if syrup_upcharge > 0:
                        modifiers.append({"name": syrup_name, "price": syrup_upcharge})
                    else:
                        free_details.append(syrup_name)

            # Sweeteners - always free
            for sweetener_entry in sweeteners:
                s_type = sweetener_entry.get("type", "")
                s_qty = sweetener_entry.get("quantity", 1)
                if s_type:
                    if s_qty > 1:
                        free_details.append(f"{s_qty} {s_type}s")
                    else:
                        free_details.append(s_type)

            # Cream level (dark, light, regular) - always free
            if cream_level:
                free_details.append(cream_level)

            # Calculate base price (total - upcharges)
            total_price = item.unit_price or 0
            base_price = total_price - size_upcharge - milk_upcharge - syrup_upcharge - iced_upcharge

            item_dict = {
                "item_type": "drink",
                "id": item.id,  # Preserve item ID
                "status": item.status.value,
                "menu_item_name": drink_type,
                "size": size,
                "base_price": base_price,
                "modifiers": modifiers,
                "free_details": free_details,  # Free modifiers for single-line display
                "item_config": {
                    "size": size,
                    "milk": milk,
                    "cream_level": cream_level,
                    "sweeteners": sweeteners,
                    "flavor_syrups": flavor_syrups,
                    "decaf": decaf,
                    # Only set style if iced is explicitly True/False (not None)
                    # skip_config drinks (sodas, bottled) don't need iced/hot labels
                    "style": "iced" if iced is True else ("hot" if iced is False else None),
                    # Upcharge tracking for display
                    "size_upcharge": size_upcharge,
                    "milk_upcharge": milk_upcharge,
                    "syrup_upcharge": syrup_upcharge,
                    "iced_upcharge": iced_upcharge,
                    # Pending syrup state for multi-turn syrup ordering (e.g., "2 syrups" -> "caramel")
                    "wants_syrup": getattr(item, 'wants_syrup', False),
                    "pending_syrup_quantity": getattr(item, 'pending_syrup_quantity', 1),
                    # Computed display fields for admin/email
                    "modifiers": modifiers,
                    "free_details": free_details,
                    "base_price": base_price,
                },
                "quantity": 1,
                "unit_price": item.unit_price,
                "line_total": item.unit_price if item.unit_price else 0,
                "special_instructions": getattr(item, 'special_instructions', None),
            }
            items.append(item_dict)

        elif item.item_type == "speed_menu_bagel":
            # Speed menu bagel (pre-configured sandwiches)
            toasted = getattr(item, 'toasted', None)
            bagel_choice = getattr(item, 'bagel_choice', None)
            bagel_choice_upcharge = getattr(item, 'bagel_choice_upcharge', 0.0) or 0.0
            cheese_choice = getattr(item, 'cheese_choice', None)
            menu_item_name = getattr(item, 'menu_item_name', 'Unknown')
            modifications = getattr(item, 'modifications', []) or []

            # Display name is just the menu item name - modifiers shown separately
            display_name = menu_item_name

            # Build modifiers list for itemized display
            modifiers = []

            # Add bagel choice as modifier (with upcharge if specialty like gluten free)
            if bagel_choice:
                modifiers.append({
                    "name": f"{bagel_choice.title()} Bagel",
                    "price": bagel_choice_upcharge,
                })

            # Add cheese choice if specified (no extra charge typically)
            if cheese_choice:
                modifiers.append({
                    "name": f"{cheese_choice.title()} Cheese",
                    "price": 0,
                })

            # Add toasted as a modifier (no price)
            if toasted is True:
                modifiers.append({
                    "name": "Toasted",
                    "price": 0,
                })

            # Add user modifications as modifiers (no price)
            for mod in modifications:
                modifiers.append({
                    "name": mod,
                    "price": 0,
                })

            # Base price is total minus any upcharges (for display purposes)
            total_price = item.unit_price or 0
            base_price = total_price - bagel_choice_upcharge

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
                "bagel_choice_upcharge": bagel_choice_upcharge,
                "cheese_choice": cheese_choice,
                "base_price": base_price,
                "modifiers": modifiers,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_total": item.unit_price * item.quantity if item.unit_price else 0,
                "special_instructions": getattr(item, 'special_instructions', None),
                "item_config": {
                    "toasted": toasted,
                    "bagel_choice": bagel_choice,
                    "bagel_choice_upcharge": bagel_choice_upcharge,
                    "cheese_choice": cheese_choice,
                    "modifications": modifications,
                    "base_price": base_price,
                    "modifiers": modifiers,
                },
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
        # Calculate taxes using centralized utility
        is_delivery = order.delivery_method.order_type == "delivery"
        totals = calculate_order_total(subtotal, store_info, is_delivery)
        city_tax = totals["city_tax"]
        state_tax = totals["state_tax"]
        tax = totals["tax"]
        delivery_fee = totals["delivery_fee"]
        total = totals["total"]

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
        "pending_item_options": order.pending_item_options,  # Generic item options for disambiguation (cookies, etc.)
        "pending_item_quantity": order.pending_item_quantity,  # Quantity stored during item disambiguation
        "menu_query_pagination": order.menu_query_pagination,  # Pagination state for "show more" menu listings
        "config_options_page": order.config_options_page,  # Pagination for "what else" during field config
        "multi_item_config_names": order.multi_item_config_names,  # Names for multi-item summary
    }

    return order_dict
