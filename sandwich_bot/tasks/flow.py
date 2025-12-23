"""
Flow Control for Order Capture.

This module provides deterministic flow control:
- State update logic (ParsedInput -> OrderTask updates)
- Next action selection (what to ask next)
- Modification and cancellation handling
"""

from typing import Any
from dataclasses import dataclass
from enum import Enum

from .models import (
    TaskStatus,
    OrderTask,
    BagelItemTask,
    CoffeeItemTask,
    MenuItemTask,
    ItemTask,
)
from .parsing import (
    ParsedInput,
    ParsedBagelItem,
    ParsedCoffeeItem,
    ParsedMenuItem,
    ItemModification,
)
from .field_config import (
    MenuFieldConfig,
    DEFAULT_BAGEL_FIELDS,
    DEFAULT_COFFEE_FIELDS,
    DEFAULT_DELIVERY_METHOD_FIELDS,
    DEFAULT_ADDRESS_FIELDS,
    DEFAULT_CUSTOMER_INFO_FIELDS,
    DEFAULT_PAYMENT_FIELDS,
)


# =============================================================================
# Default Prices
# =============================================================================

DEFAULT_BAGEL_PRICES = {
    "bagel_base": 2.50,
    "spread": 1.50,
    "proteins": {
        "ham": 2.00,
        "bacon": 2.00,
        "egg": 1.50,
        "lox": 5.00,
        "turkey": 2.50,
        "pastrami": 3.00,
    },
    "cheeses": {
        "american": 0.75,
        "swiss": 0.75,
        "cheddar": 0.75,
        "muenster": 0.75,
    },
    "extras": {
        "lox": 5.00,
        "bacon": 2.00,
        "egg": 1.50,
        "avocado": 2.00,
        "tomato": 0.50,
        "onion": 0.50,
    }
}

DEFAULT_COFFEE_PRICES = {
    "drip coffee": {"small": 2.00, "medium": 2.50, "large": 3.00},
    "cold brew": {"small": 3.50, "medium": 4.00, "large": 4.50},
    "latte": {"small": 4.00, "medium": 4.75, "large": 5.50},
    "cappuccino": {"small": 4.00, "medium": 4.50, "large": 5.00},
    "americano": {"small": 2.50, "medium": 3.00, "large": 3.50},
    "espresso": {"small": 2.50, "medium": 2.50, "large": 2.50},
    "macchiato": {"small": 3.50, "medium": 3.50, "large": 3.50},
    "mocha": {"small": 4.50, "medium": 5.25, "large": 6.00},
    "tea": {"small": 2.00, "medium": 2.50, "large": 3.00},
    "hot chocolate": {"small": 3.00, "medium": 3.50, "large": 4.00},
    "coffee": {"small": 2.00, "medium": 2.50, "large": 3.00},  # alias for drip
}


def _calculate_bagel_price(bagel: BagelItemTask, menu_data: dict | None = None) -> float:
    """
    Calculate price for a bagel item including all modifiers.

    Args:
        bagel: The bagel item to price
        menu_data: Optional menu data for dynamic pricing (falls back to defaults)

    Returns:
        Total price including base + protein + extras + spread
    """
    base_price = DEFAULT_BAGEL_PRICES["bagel_base"]

    # Calculate spread price (only if not "none")
    spread_price = 0
    if bagel.spread and bagel.spread.lower() != "none":
        spread_price = DEFAULT_BAGEL_PRICES["spread"]

    # Calculate protein price (sandwich_protein is the primary protein)
    protein_price = 0
    if bagel.sandwich_protein:
        protein_name = bagel.sandwich_protein.lower()
        protein_price = DEFAULT_BAGEL_PRICES["proteins"].get(protein_name, 0)
        # Also check extras dict for proteins not in proteins dict
        if protein_price == 0:
            protein_price = DEFAULT_BAGEL_PRICES["extras"].get(protein_name, 1.50)

    # Calculate extras price (cheeses, additional proteins, toppings)
    extras_total = 0
    for extra in (bagel.extras or []):
        extra_lower = extra.lower()
        # Check cheeses first
        if extra_lower in DEFAULT_BAGEL_PRICES["cheeses"]:
            extras_total += DEFAULT_BAGEL_PRICES["cheeses"][extra_lower]
        # Then proteins (for additional proteins beyond sandwich_protein)
        elif extra_lower in DEFAULT_BAGEL_PRICES["proteins"]:
            extras_total += DEFAULT_BAGEL_PRICES["proteins"][extra_lower]
        # Then generic extras
        elif extra_lower in DEFAULT_BAGEL_PRICES["extras"]:
            extras_total += DEFAULT_BAGEL_PRICES["extras"][extra_lower]
        else:
            # Default price for unknown extras
            extras_total += 0.50

    return round(base_price + spread_price + protein_price + extras_total, 2)


def _recalculate_bagel_price(bagel: BagelItemTask, menu_data: dict | None = None) -> None:
    """
    Recalculate and update a bagel's unit_price based on current modifiers.

    This should be called whenever a bagel's price-affecting fields change.
    """
    bagel.unit_price = _calculate_bagel_price(bagel, menu_data)


def _calculate_coffee_price(coffee: CoffeeItemTask) -> float:
    """Calculate price for a coffee item."""
    drink_type = (coffee.drink_type or "coffee").lower()
    size = (coffee.size or "medium").lower()

    # Find matching drink prices
    drink_prices = DEFAULT_COFFEE_PRICES.get(drink_type)
    if not drink_prices:
        # Try partial match
        for drink_name, prices in DEFAULT_COFFEE_PRICES.items():
            if drink_name in drink_type or drink_type in drink_name:
                drink_prices = prices
                break

    if not drink_prices:
        drink_prices = DEFAULT_COFFEE_PRICES["coffee"]  # default

    return drink_prices.get(size, drink_prices.get("medium", 3.00))


# =============================================================================
# Action Types
# =============================================================================

class ActionType(str, Enum):
    """Types of actions the bot can take."""
    ASK_QUESTION = "ask_question"  # Ask a specific question
    CONFIRM_ITEM = "confirm_item"  # Confirm an item was added
    SHOW_ORDER = "show_order"  # Show order summary
    ASK_CHECKOUT = "ask_checkout"  # Ask if ready to checkout
    PROCESS_CHECKOUT = "process_checkout"  # Process the checkout
    ASK_PAYMENT = "ask_payment"  # Ask about payment method
    COMPLETE_ORDER = "complete_order"  # Order is complete
    GREETING = "greeting"  # Initial greeting
    CLARIFY = "clarify"  # Need clarification
    ACKNOWLEDGE_CANCEL = "acknowledge_cancel"  # Acknowledge cancellation
    MENU_RESPONSE = "menu_response"  # Responding to a menu query
    OPTIONS_RESPONSE = "options_response"  # Responding to an options inquiry


@dataclass
class NextAction:
    """Represents the next action for the bot to take."""
    action_type: ActionType
    question: str | None = None
    field_name: str | None = None
    target_item: ItemTask | None = None
    message: str | None = None
    context: dict | None = None


# =============================================================================
# State Update
# =============================================================================

def update_order_state(
    order: OrderTask,
    parsed: ParsedInput,
    menu_config: MenuFieldConfig | None = None,
    menu_data: dict | None = None,
) -> OrderTask:
    """
    Update order state based on parsed input.

    This is the core state update function that takes parsed user input
    and applies it to the order task tree.

    Args:
        order: The current order state
        parsed: Parsed user input
        menu_config: Optional menu configuration for field defaults
        menu_data: Optional menu data for looking up menu item prices

    Returns:
        Updated order state
    """
    if menu_config is None:
        menu_config = MenuFieldConfig()

    # 1. Handle cancellations first
    if parsed.wants_cancel_order:
        _cancel_order(order)
        return order

    if parsed.cancel_item_index is not None:
        _cancel_item(order, parsed.cancel_item_index)

    if parsed.cancel_item_description:
        _cancel_item_by_description(order, parsed.cancel_item_description)

    # 2. Get current item BEFORE adding new items (for applying answers)
    current_item = order.items.get_current_item()

    # 3. CRITICAL: Check if there's an incomplete menu item (omelette) BEFORE applying answers
    # We need to remember this state because answers might complete the item, but we still
    # want to block new bagels if they're meant for the omelette's side choice
    omelette_was_incomplete = (
        isinstance(current_item, MenuItemTask)
        and current_item.requires_side_choice
        and not current_item.is_fully_customized()
    )
    omelette_missing_fields = current_item.get_missing_customizations() if omelette_was_incomplete else []

    # 4. Apply answers to the CURRENT item (before adding new items)
    # This prevents answers from being incorrectly applied to newly created items
    _apply_answers(order, parsed.answers, menu_config)

    # 5. Add new items (but check if they should be applied to current menu item instead)
    for bagel in parsed.new_bagels:
        # SAFETY CHECK: If we HAD an incomplete omelette, ANY bagel input is for the omelette
        # This catches cases where parser returns BOTH answers AND new_bagels
        if omelette_was_incomplete and isinstance(current_item, MenuItemTask):
            # Apply bagel as omelette's side/bagel choice (if not already set by answers)
            if "side_choice" in omelette_missing_fields and not current_item.side_choice:
                current_item.side_choice = "bagel"
            if not current_item.bagel_choice:
                current_item.bagel_choice = bagel.bagel_type or "plain"
            continue  # NEVER create a separate bagel when omelette was waiting for side choice

        # Also check current state (for cases where we just started with the omelette)
        if isinstance(current_item, MenuItemTask) and not current_item.is_fully_customized():
            missing = current_item.get_missing_customizations()
            if "side_choice" in missing:
                current_item.side_choice = "bagel"
                if bagel.bagel_type:
                    current_item.bagel_choice = bagel.bagel_type
                continue
            elif "bagel_choice" in missing:
                current_item.bagel_choice = bagel.bagel_type or "plain"
                continue

        _add_bagel(order, bagel, menu_config)

    for coffee in parsed.new_coffees:
        _add_coffee(order, coffee, menu_config)

    for menu_item in parsed.new_menu_items:
        _add_menu_item(order, menu_item, menu_data)

    # 6. Apply modifications (or detect split pattern)
    split_detected = _detect_and_apply_split_modifications(order, parsed.modifications, menu_config, menu_data)

    # If not a split, apply modifications normally
    if not split_detected:
        for mod in parsed.modifications:
            _apply_modification(order, mod, menu_data)

    # 7. Handle split item answers (e.g., "butter on one, cream cheese on the other")
    if parsed.split_item_answers:
        _apply_split_item_answers(order, parsed.split_item_answers, menu_config)

    # 8. Update delivery/pickup
    if parsed.order_type:
        order.delivery_method.order_type = parsed.order_type
        if parsed.order_type == "pickup":
            order.delivery_method.mark_complete()

    if parsed.delivery_address:
        _parse_and_set_address(order, parsed.delivery_address)

    # 9. Update customer info
    if parsed.customer_name:
        order.customer_info.name = parsed.customer_name
    if parsed.customer_phone:
        order.customer_info.phone = parsed.customer_phone
    if parsed.customer_email:
        order.customer_info.email = parsed.customer_email

    # 10. Update payment
    if parsed.payment_method:
        order.payment.method = parsed.payment_method

    # 11. Handle order confirmation
    if parsed.confirms_order:
        order.checkout.order_reviewed = True

    # 12. Handle payment link preference
    if parsed.wants_payment_link is not None:
        if parsed.wants_payment_link:
            order.payment.method = "card_link"
        else:
            # Pay in person - depends on order type
            if order.delivery_method.order_type == "delivery":
                order.payment.method = "cash_delivery"
            else:
                order.payment.method = "in_store"

    # 13. Handle checkout intent
    if parsed.wants_checkout or parsed.no_more_items:
        _finalize_current_items(order, menu_config)

    # 14. Recalculate task statuses
    _recalculate_statuses(order, menu_config)

    return order


def _cancel_order(order: OrderTask) -> None:
    """Cancel the entire order."""
    order.mark_skipped()
    for item in order.items.items:
        item.mark_skipped()


def _cancel_item(order: OrderTask, index: int) -> None:
    """Cancel item at specific index."""
    order.items.skip_item(index)


def _cancel_item_by_description(order: OrderTask, description: str) -> None:
    """Cancel item matching description."""
    description_lower = description.lower()
    for i, item in enumerate(order.items.items):
        if item.status == TaskStatus.SKIPPED:
            continue
        item_summary = item.get_summary().lower()
        if description_lower in item_summary or item_summary in description_lower:
            order.items.skip_item(i)
            return


def _add_bagel(
    order: OrderTask,
    parsed_bagel: ParsedBagelItem,
    menu_config: MenuFieldConfig,
) -> BagelItemTask:
    """Add a new bagel to the order."""
    bagel = BagelItemTask(
        bagel_type=parsed_bagel.bagel_type,
        quantity=parsed_bagel.quantity,
        toasted=parsed_bagel.toasted,
        spread=parsed_bagel.spread,
        spread_type=parsed_bagel.spread_type,
        extras=parsed_bagel.extras,
        sandwich_protein=parsed_bagel.sandwich_protein,
    )

    # Apply defaults from menu config
    fields = menu_config.bagel_fields
    for field_name, config in fields.items():
        current = getattr(bagel, field_name, None)
        if current is None and config.default is not None:
            setattr(bagel, field_name, config.default)

    bagel.mark_in_progress()
    order.items.add_item(bagel)
    return bagel


def _add_coffee(
    order: OrderTask,
    parsed_coffee: ParsedCoffeeItem,
    menu_config: MenuFieldConfig,
) -> CoffeeItemTask:
    """Add a new coffee to the order."""
    coffee = CoffeeItemTask(
        drink_type=parsed_coffee.drink_type,
        quantity=parsed_coffee.quantity,
        size=parsed_coffee.size,
        iced=parsed_coffee.iced,
        milk=parsed_coffee.milk,
        sweetener=parsed_coffee.sweetener,
        sweetener_quantity=parsed_coffee.sweetener_quantity,
        flavor_syrup=parsed_coffee.flavor_syrup,
        extra_shots=parsed_coffee.extra_shots,
    )

    # Apply defaults from menu config
    fields = menu_config.coffee_fields
    for field_name, config in fields.items():
        current = getattr(coffee, field_name, None)
        if current is None and config.default is not None:
            setattr(coffee, field_name, config.default)

    coffee.mark_in_progress()
    order.items.add_item(coffee)
    return coffee


def _add_menu_item(
    order: OrderTask,
    parsed_item: ParsedMenuItem,
    menu_data: dict | None = None,
) -> MenuItemTask:
    """Add a menu item ordered by name to the order."""
    # Look up the item in menu data to get price and type
    price = 0.0
    menu_item_id = None
    menu_item_type = None

    if menu_data:
        # Search all categories for the item by name
        item_name_lower = parsed_item.item_name.lower()
        items_by_type = menu_data.get("items_by_type", {})

        for type_slug, items in items_by_type.items():
            for item in items:
                if item.get("name", "").lower() == item_name_lower:
                    price = item.get("base_price", 0.0)
                    menu_item_id = item.get("id")
                    menu_item_type = type_slug
                    break
            if menu_item_id:
                break

        # Also check signature items and other top-level categories
        for category in ["signature_bagels", "signature_sandwiches", "sides", "drinks", "desserts", "other"]:
            if menu_item_id:
                break
            for item in menu_data.get(category, []):
                if item.get("name", "").lower() == item_name_lower:
                    price = item.get("base_price", 0.0)
                    menu_item_id = item.get("id")
                    menu_item_type = item.get("item_type")
                    break

    # Determine if this item type requires side choice (e.g., omelettes)
    # Check by item_type first, then fall back to name-based detection
    requires_side = menu_item_type == "omelette"
    if not requires_side:
        # Fallback: detect omelettes by name
        item_name_lower = parsed_item.item_name.lower()
        if "omelette" in item_name_lower or "omelet" in item_name_lower:
            requires_side = True
            menu_item_type = "omelette"

    menu_item = MenuItemTask(
        menu_item_name=parsed_item.item_name,
        menu_item_id=menu_item_id,
        menu_item_type=menu_item_type,
        quantity=parsed_item.quantity,
        modifications=parsed_item.modifications,
        unit_price=price,
        requires_side_choice=requires_side,
    )

    # Only mark complete if no customization needed
    if menu_item.is_fully_customized():
        menu_item.mark_complete()
    else:
        menu_item.mark_in_progress()

    order.items.add_item(menu_item)
    return menu_item


# Fields that affect bagel pricing - when modified, price needs recalculation
BAGEL_PRICE_AFFECTING_FIELDS = {"spread", "sandwich_protein", "extras"}


def _apply_modification(
    order: OrderTask,
    mod: ItemModification,
    menu_data: dict | None = None,
) -> None:
    """
    Apply a modification to an existing item.

    If the modification affects a price-related field on a bagel,
    the price will be automatically recalculated.
    """
    target_item = None

    if mod.item_index is not None:
        if 0 <= mod.item_index < len(order.items.items):
            target_item = order.items.items[mod.item_index]
    elif mod.item_type:
        # Find first matching item type
        for item in reversed(order.items.items):  # Most recent first
            if item.status == TaskStatus.SKIPPED:
                continue
            if item.item_type == mod.item_type:
                target_item = item
                break
    else:
        # Default to current/last active item
        target_item = order.items.get_current_item()
        if target_item is None:
            active = order.items.get_active_items()
            if active:
                target_item = active[-1]

    if target_item and hasattr(target_item, mod.field):
        setattr(target_item, mod.field, mod.new_value)

        # Recalculate price if this is a bagel and a price-affecting field was modified
        if isinstance(target_item, BagelItemTask) and mod.field in BAGEL_PRICE_AFFECTING_FIELDS:
            _recalculate_bagel_price(target_item, menu_data)


def _detect_and_apply_split_modifications(
    order: OrderTask,
    modifications: list[ItemModification],
    menu_config: MenuFieldConfig,
    menu_data: dict | None = None,
) -> bool:
    """
    Detect and handle split modifications for multi-quantity items.

    When a user orders "two bagels" and says "butter on one, cream cheese on the other",
    the LLM may return modifications targeting indices 0 and 1, but those indices
    may not exist or may be different items. This function detects that pattern
    and splits the multi-quantity item instead.

    Returns:
        True if split was detected and handled, False otherwise
    """
    if len(modifications) < 2:
        return False

    # Group modifications by field name
    field_mods: dict[str, list[ItemModification]] = {}
    for mod in modifications:
        if mod.field not in field_mods:
            field_mods[mod.field] = []
        field_mods[mod.field].append(mod)

    # Look for a field that has multiple modifications with different values
    for field_name, mods in field_mods.items():
        if len(mods) < 2:
            continue

        # Check if all modifications are for the same field with different values
        values = [mod.new_value for mod in mods]
        if len(set(str(v) for v in values)) < 2:
            # Same value for all modifications, not a split
            continue

        # Find the current multi-quantity item that should be split
        current_item = order.items.get_current_item()
        if current_item is None:
            current_item = order.items.get_next_pending_item()

        if current_item is None:
            # Try to find a recent item with matching quantity
            active_items = order.items.get_active_items()
            for item in reversed(active_items):
                if item.quantity >= len(mods) and hasattr(item, field_name):
                    current_item = item
                    break

        if current_item is None:
            continue

        if not hasattr(current_item, field_name):
            continue

        # Check if the item has sufficient quantity to split
        if current_item.quantity < len(mods):
            continue

        # This looks like a split! Apply it.
        _split_item_with_modifications(order, current_item, field_name, mods, menu_data)
        return True

    return False


def _split_item_with_modifications(
    order: OrderTask,
    item: ItemTask,
    field_name: str,
    modifications: list[ItemModification],
    menu_data: dict | None = None,
) -> None:
    """
    Split a multi-quantity item into separate items with different field values.

    Args:
        order: The order task
        item: The item to split
        field_name: The field that varies between split items
        modifications: The modifications with different values for each split
        menu_data: Optional menu data for price recalculation
    """
    num_splits = len(modifications)

    # Reduce original item quantity to 1 and apply first modification
    item.quantity = 1
    setattr(item, field_name, modifications[0].new_value)

    # Recalculate price for original item if it's a bagel with price-affecting field
    if isinstance(item, BagelItemTask) and field_name in BAGEL_PRICE_AFFECTING_FIELDS:
        _recalculate_bagel_price(item, menu_data)

    # Create new items for remaining modifications
    for mod in modifications[1:]:
        if isinstance(item, BagelItemTask):
            new_item = BagelItemTask(
                bagel_type=item.bagel_type,
                quantity=1,
                toasted=item.toasted,
                spread=item.spread,
                spread_type=item.spread_type,
                sandwich_protein=item.sandwich_protein,
                extras=list(item.extras) if item.extras else [],
                unit_price=item.unit_price,  # Start with original price
            )
        elif isinstance(item, CoffeeItemTask):
            new_item = CoffeeItemTask(
                drink_type=item.drink_type,
                size=item.size,
                iced=item.iced,
                milk=item.milk,
                sweetener=item.sweetener,
                sweetener_quantity=item.sweetener_quantity,
                flavor_syrup=item.flavor_syrup,
                extra_shots=item.extra_shots,
            )
        else:
            continue

        # Apply this modification's value
        setattr(new_item, field_name, mod.new_value)

        # Recalculate price if this is a bagel with price-affecting field
        if isinstance(new_item, BagelItemTask) and field_name in BAGEL_PRICE_AFFECTING_FIELDS:
            _recalculate_bagel_price(new_item, menu_data)

        # Copy the status from original
        if item.status == TaskStatus.IN_PROGRESS:
            new_item.mark_in_progress()
        elif item.status == TaskStatus.COMPLETE:
            new_item.mark_complete()

        order.items.add_item(new_item)


def _apply_answers(
    order: OrderTask,
    answers: dict[str, Any],
    menu_config: MenuFieldConfig,
) -> None:
    """Apply answers to the current item being worked on."""
    if not answers:
        return

    # Find the current item being worked on
    current_item = order.items.get_current_item()
    if current_item is None:
        current_item = order.items.get_next_pending_item()

    if current_item is None:
        # Check non-item fields (delivery method, customer info, etc.)
        _apply_answers_to_non_items(order, answers)
        return

    # Apply answers to current item
    for field_name, value in answers.items():
        if hasattr(current_item, field_name):
            setattr(current_item, field_name, value)


def _apply_answers_to_non_items(order: OrderTask, answers: dict[str, Any]) -> None:
    """Apply answers to non-item tasks."""
    for field_name, value in answers.items():
        # Check delivery method
        if hasattr(order.delivery_method, field_name):
            setattr(order.delivery_method, field_name, value)
        elif hasattr(order.delivery_method.address, field_name):
            setattr(order.delivery_method.address, field_name, value)
        # Check customer info
        elif hasattr(order.customer_info, field_name):
            setattr(order.customer_info, field_name, value)
        # Check payment
        elif hasattr(order.payment, field_name):
            setattr(order.payment, field_name, value)


def _apply_split_item_answers(
    order: OrderTask,
    split_answers: list[dict[str, Any]],
    menu_config: MenuFieldConfig,
) -> None:
    """
    Handle split item answers for multi-quantity items.

    When a user orders "two bagels" and says "butter on one, cream cheese on the other",
    we need to split the single item (quantity=2) into two separate items with different attributes.
    """
    if not split_answers:
        return

    # Find the current item being worked on
    current_item = order.items.get_current_item()
    if current_item is None:
        current_item = order.items.get_next_pending_item()

    # Also check recently completed items with quantity > 1
    if current_item is None or current_item.quantity < len(split_answers):
        for item in reversed(order.items.items):
            if item.quantity >= len(split_answers) and item.status != TaskStatus.SKIPPED:
                current_item = item
                break

    if current_item is None:
        return

    # Only split if quantity matches the number of split answers
    if current_item.quantity < len(split_answers):
        return

    # Find the index of the current item
    current_index = None
    for i, item in enumerate(order.items.items):
        if item is current_item:
            current_index = i
            break

    if current_index is None:
        return

    # Reduce original item quantity to 1 and apply first answer set
    current_item.quantity = 1
    for field_name, value in split_answers[0].items():
        if hasattr(current_item, field_name):
            setattr(current_item, field_name, value)

    # Create new items for the remaining split answers
    for answer_set in split_answers[1:]:
        # Create a copy of the current item
        if isinstance(current_item, BagelItemTask):
            new_item = BagelItemTask(
                bagel_type=current_item.bagel_type,
                quantity=1,
                toasted=current_item.toasted,
                spread=current_item.spread,
                spread_type=current_item.spread_type,
                extras=list(current_item.extras) if current_item.extras else [],
            )
        elif isinstance(current_item, CoffeeItemTask):
            new_item = CoffeeItemTask(
                drink_type=current_item.drink_type,
                size=current_item.size,
                iced=current_item.iced,
                milk=current_item.milk,
                sweetener=current_item.sweetener,
                sweetener_quantity=current_item.sweetener_quantity,
                flavor_syrup=current_item.flavor_syrup,
                extra_shots=current_item.extra_shots,
            )
        else:
            continue

        # Apply this answer set to the new item
        for field_name, value in answer_set.items():
            if hasattr(new_item, field_name):
                setattr(new_item, field_name, value)

        # Insert after the current item
        order.items.add_item(new_item)


def _parse_and_set_address(order: OrderTask, address_str: str) -> None:
    """Parse and set delivery address from string."""
    # Simple parsing - just set street for now
    # TODO: Use proper address parsing library
    order.delivery_method.address.street = address_str
    order.delivery_method.order_type = "delivery"


def _finalize_current_items(order: OrderTask, menu_config: MenuFieldConfig) -> None:
    """Finalize current items (apply defaults for missing optional fields)."""
    for item in order.items.items:
        if item.status == TaskStatus.IN_PROGRESS:
            # Check if all required fields are filled
            if isinstance(item, BagelItemTask):
                fields = menu_config.bagel_fields
            elif isinstance(item, CoffeeItemTask):
                fields = menu_config.coffee_fields
            else:
                continue

            missing = item.get_missing_required_fields(fields)
            if not missing:
                item.mark_complete()


def _recalculate_statuses(order: OrderTask, menu_config: MenuFieldConfig) -> None:
    """Recalculate task statuses based on field values."""
    # Check each item
    for item in order.items.items:
        if item.status == TaskStatus.SKIPPED:
            continue

        if isinstance(item, BagelItemTask):
            fields = menu_config.bagel_fields
            # Always recalculate price based on current attributes (spread, extras, etc.)
            item.unit_price = _calculate_bagel_price(item)
            missing = item.get_missing_required_fields(fields)
            if not missing and item.status != TaskStatus.COMPLETE:
                item.mark_complete()
        elif isinstance(item, CoffeeItemTask):
            fields = menu_config.coffee_fields
            # Always recalculate price based on current attributes (size, drink type, etc.)
            item.unit_price = _calculate_coffee_price(item)
            missing = item.get_missing_required_fields(fields)
            if not missing and item.status != TaskStatus.COMPLETE:
                item.mark_complete()
        elif isinstance(item, MenuItemTask):
            # Check if menu item customizations are complete
            if item.is_fully_customized() and item.status != TaskStatus.COMPLETE:
                item.mark_complete()

    # Check items container
    if order.items.all_items_complete():
        order.items.mark_complete()

    # Check delivery method
    if order.delivery_method.is_complete():
        order.delivery_method.mark_complete()

    # Check customer info (just name for now)
    if order.customer_info.name:
        order.customer_info.mark_complete()


# =============================================================================
# Next Action Selection
# =============================================================================

def get_next_action(
    order: OrderTask,
    parsed: ParsedInput | None = None,
    menu_config: MenuFieldConfig | None = None,
) -> NextAction:
    """
    Determine the next action for the bot.

    This is the core flow control function that decides what to do next
    based on the current order state.

    Args:
        order: Current order state
        parsed: Most recent parsed input (for context)
        menu_config: Optional menu configuration

    Returns:
        NextAction describing what the bot should do
    """
    if menu_config is None:
        menu_config = MenuFieldConfig()

    # Handle greeting
    if parsed and parsed.is_greeting and len(order.items.items) == 0:
        return NextAction(
            action_type=ActionType.GREETING,
            message="Hi! Welcome to Zucker's Bagels. What can I get for you today?"
        )

    # Handle clarification needed
    if parsed and parsed.needs_clarification:
        # Validate the clarification message - must be a short question
        clarification_msg = parsed.clarification_needed
        default_msg = "I didn't quite catch that. Could you repeat?"

        # Use default if: no message, too long, or doesn't look like a question
        if (not clarification_msg or
            len(clarification_msg) > 100 or
            not clarification_msg.strip().endswith("?")):
            clarification_msg = default_msg

        return NextAction(
            action_type=ActionType.CLARIFY,
            message=clarification_msg,
        )

    # 1. If no items yet, prompt for order
    if len(order.items.items) == 0:
        return NextAction(
            action_type=ActionType.ASK_QUESTION,
            question="What can I get for you today?",
        )

    # 2. Complete current in-progress item before moving to next
    current_item = order.items.get_current_item()
    if current_item:
        next_question = _get_next_question_for_item(current_item, menu_config, order)
        if next_question:
            return next_question

        # Current item is complete, mark it
        current_item.mark_complete()

    # 3. Start next pending item
    next_item = order.items.get_next_pending_item()
    if next_item:
        next_item.mark_in_progress()
        next_question = _get_next_question_for_item(next_item, menu_config, order)
        if next_question:
            return next_question

        # Item is complete immediately (all fields have values or defaults)
        next_item.mark_complete()
        # Recurse to check for more items
        return get_next_action(order, parsed, menu_config)

    # 4. All items complete - check if we should ask for more items
    # Skip asking if:
    # - User explicitly said no more items or wants checkout
    # - We've already moved past items (delivery method is set)
    already_past_items = order.delivery_method.order_type is not None
    if parsed and (parsed.no_more_items or parsed.wants_checkout):
        # Proceed to delivery method
        pass
    elif already_past_items:
        # Already moved past items phase, don't ask again
        pass
    else:
        # Ask if they want anything else
        return NextAction(
            action_type=ActionType.ASK_QUESTION,
            question="Anything else?",
            context={"asking_for_more": True},
        )

    # 5. Check delivery method
    if not order.delivery_method.is_complete():
        if order.delivery_method.order_type is None:
            return NextAction(
                action_type=ActionType.ASK_QUESTION,
                question="Is this for pickup or delivery?",
                field_name="order_type",
            )
        if order.delivery_method.order_type == "delivery":
            if not order.delivery_method.address.street:
                return NextAction(
                    action_type=ActionType.ASK_QUESTION,
                    question="What's your delivery address?",
                    field_name="street",
                )
            if not order.delivery_method.address.zip_code:
                return NextAction(
                    action_type=ActionType.ASK_QUESTION,
                    question="And the zip code?",
                    field_name="zip_code",
                )

    # 6. Get customer name if not set
    if not order.customer_info.name:
        return NextAction(
            action_type=ActionType.ASK_QUESTION,
            question="Can I get a name for the order?",
            field_name="name",
        )

    # 7. Show order summary and confirm
    if not order.checkout.order_reviewed:
        return NextAction(
            action_type=ActionType.SHOW_ORDER,
            message=_build_order_summary(order),
            context={"awaiting_confirmation": True},
        )

    # 8. Ask about payment link
    if not order.payment.method:
        return NextAction(
            action_type=ActionType.ASK_PAYMENT,
            question="Do you want me to email you or text you a payment link?",
            field_name="wants_payment_link",
        )

    # 9. Complete the order
    # Calculate totals
    subtotal = order.items.get_subtotal()
    is_delivery = order.delivery_method.order_type == "delivery"
    order.checkout.calculate_total(
        subtotal=subtotal,
        is_delivery=is_delivery,
        city_tax_rate=0.045,  # NYC tax rate
        state_tax_rate=0.04,  # NY state tax rate
        delivery_fee=2.99,
    )
    order.checkout.confirmed = True
    order.checkout.mark_complete()
    return NextAction(
        action_type=ActionType.COMPLETE_ORDER,
        message=_build_completion_message(order),
    )


def _get_next_question_for_item(
    item: ItemTask,
    menu_config: MenuFieldConfig,
    order: OrderTask | None = None,
) -> NextAction | None:
    """Get the next question to ask for an item."""
    # Handle MenuItemTask separately - it has different customization logic
    if isinstance(item, MenuItemTask):
        return _get_next_question_for_menu_item(item, order)

    if isinstance(item, BagelItemTask):
        fields = menu_config.bagel_fields
    elif isinstance(item, CoffeeItemTask):
        fields = menu_config.coffee_fields
    else:
        return None

    # Get fields that need asking
    to_ask = item.get_fields_to_ask(fields)
    if not to_ask:
        return None

    # Return the first field that needs asking
    field_config = to_ask[0]
    question = field_config.question

    # Add context if there are multiple similar items
    if order is not None:
        question = _add_item_context_to_question(item, question, order)

    return NextAction(
        action_type=ActionType.ASK_QUESTION,
        question=question,
        field_name=field_config.name,
        target_item=item,
    )


def _get_next_question_for_menu_item(
    item: MenuItemTask,
    order: OrderTask | None = None,
) -> NextAction | None:
    """Get the next question to ask for a menu item (e.g., omelette)."""
    missing = item.get_missing_customizations()
    if not missing:
        return None

    # Ask about the first missing customization
    field_name = missing[0]

    if field_name == "side_choice":
        return NextAction(
            action_type=ActionType.ASK_QUESTION,
            question=f"Would you like a bagel or fruit salad with your {item.menu_item_name}?",
            field_name="side_choice",
            target_item=item,
        )
    elif field_name == "bagel_choice":
        return NextAction(
            action_type=ActionType.ASK_QUESTION,
            question="What kind of bagel would you like?",
            field_name="bagel_choice",
            target_item=item,
        )

    return None


def _add_item_context_to_question(
    item: ItemTask,
    question: str,
    order: OrderTask,
) -> str:
    """
    Add distinguishing context to a question when there are multiple similar items.

    For example, if there are two plain bagels with different spreads, the question
    "Would you like that toasted?" becomes "For the one with butter, would you like that toasted?"
    """
    # Count similar items (same type)
    similar_items = [
        i for i in order.items.get_active_items()
        if type(i) == type(item) and i is not item
    ]

    if not similar_items:
        # No other similar items, no need to add context
        return question

    # Build a distinguishing description for this item
    distinguisher = _get_item_distinguisher(item)
    if not distinguisher:
        return question

    # Reformat the question to include context
    # "Would you like that toasted?" -> "For the one with butter, would you like that toasted?"
    question_lower = question.lower()
    if question_lower.startswith("would you like"):
        return f"For {distinguisher}, {question[0].lower()}{question[1:]}"
    else:
        return f"For {distinguisher}: {question}"


def _get_item_distinguisher(item: ItemTask) -> str | None:
    """
    Get a distinguishing description for an item based on its already-set attributes.

    Returns something like "the one with butter" or "the plain bagel".
    """
    if isinstance(item, BagelItemTask):
        parts = []

        # Use spread if set (most common distinguisher after split)
        if item.spread:
            return f"the one with {item.spread}"

        # Use bagel type if set
        if item.bagel_type:
            parts.append(item.bagel_type)

        # Use toasted status if set
        if item.toasted is True:
            parts.append("toasted")
        elif item.toasted is False:
            parts.append("not toasted")

        if parts:
            return f"the {' '.join(parts)} bagel"

    elif isinstance(item, CoffeeItemTask):
        parts = []

        # Use iced/hot status
        if item.iced is True:
            parts.append("iced")
        elif item.iced is False:
            parts.append("hot")

        # Use size if set
        if item.size:
            parts.append(item.size)

        # Use drink type
        if item.drink_type:
            parts.append(item.drink_type)

        if parts:
            return f"the {' '.join(parts)}"

    return None


def _build_order_summary(order: OrderTask) -> str:
    """Build a human-readable order summary with consolidated identical items."""
    from collections import defaultdict

    lines = ["Here's your order:"]

    # Group items by their summary string to consolidate identical items
    # Track count and total price for each unique item summary
    item_data: dict[str, dict] = defaultdict(lambda: {"count": 0, "total_price": 0.0})
    for item in order.items.get_active_items():
        summary = item.get_summary()
        price = item.unit_price * item.quantity
        item_data[summary]["count"] += 1
        item_data[summary]["total_price"] += price

    # Build consolidated lines
    for summary, data in item_data.items():
        count = data["count"]
        total_price = data["total_price"]
        if count > 1:
            display = f"• {count}× {summary}"
        else:
            display = f"• {summary}"

        if total_price > 0:
            lines.append(f"{display} - ${total_price:.2f}")
        else:
            lines.append(display)

    subtotal = order.items.get_subtotal()
    if subtotal > 0:
        lines.append(f"\nSubtotal: ${subtotal:.2f}")

    if order.delivery_method.order_type == "delivery":
        lines.append("Delivery fee: $2.99")

    lines.append("\nDoes that look right?")
    return "\n".join(lines)


def _build_completion_message(order: OrderTask) -> str:
    """Build the order completion message based on order type and payment method."""
    # Generate and store full order number, but display only last 2 characters
    full_order_number = order.checkout.generate_order_number()
    display_number = full_order_number[-2:] if full_order_number else "00"
    name = order.customer_info.name or "there"
    is_delivery = order.delivery_method.order_type == "delivery"
    payment_method = order.payment.method

    if payment_method == "card_link":
        # User wants payment link sent
        if is_delivery:
            return (
                f"Your order is confirmed, {name}! "
                f"I'll send you a payment link by email. "
                f"Your order #{display_number} will be on its way soon!"
            )
        else:
            return (
                f"Your order is confirmed, {name}! "
                f"I'll send you a payment link by email. "
                f"Your order #{display_number} will be ready for pickup shortly!"
            )
    elif is_delivery:
        # Delivery, pay on delivery
        return (
            f"Your order is confirmed, {name}! "
            f"You can pay when your order is delivered. "
            f"Order #{display_number} will be on its way soon!"
        )
    else:
        # Pickup, pay in store
        return (
            f"Your order is confirmed, {name}! "
            f"You can pay when you pick up your order. "
            f"Order #{display_number} will be ready shortly!"
        )


# =============================================================================
# Convenience Functions
# =============================================================================

def _generate_options_response(
    item_type: str | None,
    attribute: str | None,
    menu_data: dict | None,
) -> str:
    """
    Generate a response listing available options for a specific attribute.

    Args:
        item_type: The type of item (e.g., 'omelette', 'bagel')
        attribute: The attribute being asked about (e.g., 'cheese', 'filling')
        menu_data: Menu data containing attribute options

    Returns:
        Response message listing the options
    """
    if not menu_data:
        return "I'm sorry, I don't have the options information available right now. What would you like on your order?"

    # Get item_types data from menu - this contains all attribute definitions and options
    item_types = menu_data.get("item_types", {})

    # Normalize attribute name for lookup
    attr_mappings = {
        "cheese": "filling",  # Cheese is part of filling for omelettes
        "fillings": "filling",
        "cheeses": "filling",
        "bagel": "bagel_choice",
        "bagels": "bagel_choice",
        "side": "side_choice",
        "sides": "side_choice",
        "egg": "egg_style",
        "eggs": "egg_style",
        "extra": "extras",
    }
    normalized_attr = attr_mappings.get(attribute, attribute) if attribute else None

    options = []
    attr_display_name = attribute

    # Try to find matching attribute in the specified item type
    if item_type and item_type in item_types:
        type_data = item_types[item_type]
        for attr in type_data.get("attributes", []):
            if attr.get("slug") == normalized_attr:
                options = attr.get("options", [])
                attr_display_name = attr.get("display_name", attribute)
                break

    # If not found with item_type, try to find in any configurable item type
    if not options and normalized_attr:
        for type_slug, type_data in item_types.items():
            if not type_data.get("is_configurable"):
                continue
            for attr in type_data.get("attributes", []):
                if attr.get("slug") == normalized_attr:
                    options = attr.get("options", [])
                    attr_display_name = attr.get("display_name", attribute)
                    item_type = type_slug
                    break
            if options:
                break

    if not options:
        # Provide a helpful response even without specific options
        if attribute and "cheese" in attribute.lower():
            return "For cheese options, we have American, Cheddar, Swiss, and Muenster. Which would you like?"
        return f"I'm not sure about the available options for that. What would you like?"

    # Format the options list - filter to just cheese options if they asked about cheese
    if attribute and "cheese" in attribute.lower():
        cheese_options = [
            opt for opt in options
            if "cheese" in (opt.get("display_name") or opt.get("slug", "")).lower()
        ]
        if cheese_options:
            options = cheese_options

    option_names = []
    for opt in options[:15]:  # Limit to avoid overwhelming response
        name = opt.get("display_name") or opt.get("slug", "Unknown")
        price = opt.get("price_modifier", 0)
        if price > 0:
            option_names.append(f"{name} (+${price:.2f})")
        else:
            option_names.append(name)

    if len(options) > 15:
        option_names.append(f"...and {len(options) - 15} more")

    return f"For {attr_display_name or 'options'}, you can choose: {', '.join(option_names)}. Which would you like?"


def _generate_menu_response(menu_query_type: str, menu_data: dict | None) -> str:
    """
    Generate a response listing menu items for a specific type.

    Args:
        menu_query_type: The type of item being queried (e.g., 'egg_sandwich', 'fish_sandwich')
        menu_data: Menu data containing items_by_type

    Returns:
        Response message listing the items
    """
    if not menu_data:
        return "I'm sorry, I don't have the menu information available right now. What would you like to order?"

    items_by_type = menu_data.get("items_by_type", {})

    # Handle "all" query
    if menu_query_type == "all":
        # List all available types with item counts
        type_counts = []
        for type_slug, items in items_by_type.items():
            if items:
                type_name = type_slug.replace("_", " ").title()
                type_counts.append(f"{type_name}s ({len(items)})")
        if type_counts:
            return f"We have: {', '.join(type_counts)}. What would you like to order?"
        return "I'm sorry, I don't have menu items available right now."

    # Look up items for the specific type
    items = items_by_type.get(menu_query_type, [])

    # If not found, try some common mappings
    if not items:
        type_mappings = {
            "egg_sandwiches": "egg_sandwich",
            "fish_sandwiches": "fish_sandwich",
            "sandwiches": "sandwich",
            "bagels": "bagel",
            "drinks": "drink",
            "sides": "side",
            "signature_sandwiches": "signature_sandwich",
        }
        mapped_type = type_mappings.get(menu_query_type)
        if mapped_type:
            items = items_by_type.get(mapped_type, [])

    if not items:
        # Try to suggest what we do have
        available_types = [t.replace("_", " ") for t, i in items_by_type.items() if i]
        if available_types:
            return f"I don't have any {menu_query_type.replace('_', ' ')}s on the menu. We do have: {', '.join(available_types)}. What would you like?"
        return f"I'm sorry, I don't have any {menu_query_type.replace('_', ' ')}s on the menu. What else can I help you with?"

    # Format the items list
    type_name = menu_query_type.replace("_", " ")
    item_list = []
    for item in items[:10]:  # Limit to 10 items to avoid overwhelming
        name = item.get("name", "Unknown")
        price = item.get("base_price", 0)
        if price > 0:
            item_list.append(f"{name} (${price:.2f})")
        else:
            item_list.append(name)

    if len(items) > 10:
        item_list.append(f"...and {len(items) - 10} more")

    return f"Our {type_name}s include: {', '.join(item_list)}. Would you like to order any of these?"


def process_message(
    order: OrderTask,
    parsed: ParsedInput,
    menu_config: MenuFieldConfig | None = None,
    menu_data: dict | None = None,
) -> tuple[OrderTask, NextAction]:
    """
    Process a parsed message and get the next action.

    This is the main entry point for processing user messages.

    Args:
        order: Current order state
        parsed: Parsed user input
        menu_config: Optional menu configuration
        menu_data: Optional menu data for menu queries

    Returns:
        Tuple of (updated order, next action)
    """
    # Handle options inquiries first (before updating state)
    if parsed.options_inquiry:
        response = _generate_options_response(
            parsed.options_inquiry_item_type,
            parsed.options_inquiry_attribute,
            menu_data,
        )
        return order, NextAction(
            action_type=ActionType.OPTIONS_RESPONSE,
            message=response,
        )

    # Handle menu queries (before updating state)
    if parsed.menu_query and parsed.menu_query_type:
        response = _generate_menu_response(parsed.menu_query_type, menu_data)
        return order, NextAction(
            action_type=ActionType.MENU_RESPONSE,
            message=response,
        )

    # Update state
    order = update_order_state(order, parsed, menu_config, menu_data)

    # Get next action
    next_action = get_next_action(order, parsed, menu_config)

    return order, next_action
