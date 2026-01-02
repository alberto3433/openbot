"""
Taking Items Handler for Order State Machine.

This module handles the taking items phase of the order flow including
greeting, processing new item orders, and multi-item order coordination.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import re
import uuid
from typing import Callable, TYPE_CHECKING

from .models import (
    OrderTask,
    BagelItemTask,
    CoffeeItemTask,
    MenuItemTask,
    SpeedMenuBagelItemTask,
    TaskStatus,
)
from .schemas import (
    StateMachineResult,
    OpenInputResponse,
    ExtractedModifiers,
    ExtractedCoffeeModifiers,
    CoffeeOrderDetails,
)
from .parsers import parse_open_input, extract_modifiers_from_input, extract_coffee_modifiers_from_input
from .parsers.constants import BAGEL_TYPES, BAGEL_SPREADS, MODIFIER_NORMALIZATIONS

if TYPE_CHECKING:
    from .pricing import PricingEngine
    from .coffee_config_handler import CoffeeConfigHandler
    from .item_adder_handler import ItemAdderHandler
    from .speed_menu_handler import SpeedMenuBagelHandler
    from .menu_inquiry_handler import MenuInquiryHandler
    from .store_info_handler import StoreInfoHandler
    from .by_pound_handler import ByPoundHandler
    from .checkout_utils_handler import CheckoutUtilsHandler
    from .checkout_handler import CheckoutHandler

logger = logging.getLogger(__name__)


class TakingItemsHandler:
    """
    Handles the taking items phase of order flow.

    Manages greeting, processing new item orders, and
    multi-item order coordination.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        pricing: "PricingEngine | None" = None,
        coffee_handler: "CoffeeConfigHandler | None" = None,
        item_adder_handler: "ItemAdderHandler | None" = None,
        speed_menu_handler: "SpeedMenuBagelHandler | None" = None,
        menu_inquiry_handler: "MenuInquiryHandler | None" = None,
        store_info_handler: "StoreInfoHandler | None" = None,
        by_pound_handler: "ByPoundHandler | None" = None,
        checkout_utils_handler: "CheckoutUtilsHandler | None" = None,
        checkout_handler: "CheckoutHandler | None" = None,
    ) -> None:
        """
        Initialize the taking items handler.

        Args:
            model: LLM model to use for parsing.
            pricing: Pricing engine.
            coffee_handler: Handler for coffee items.
            item_adder_handler: Handler for adding items.
            speed_menu_handler: Handler for speed menu items.
            menu_inquiry_handler: Handler for menu inquiries.
            store_info_handler: Handler for store info inquiries.
            by_pound_handler: Handler for by-pound items.
            checkout_utils_handler: Handler for checkout utilities.
            checkout_handler: Handler for checkout flow including confirmation/repeat orders.
        """
        self.model = model
        self.pricing = pricing
        self.coffee_handler = coffee_handler
        self.item_adder_handler = item_adder_handler
        self.speed_menu_handler = speed_menu_handler
        self.menu_inquiry_handler = menu_inquiry_handler
        self.store_info_handler = store_info_handler
        self.by_pound_handler = by_pound_handler
        self.checkout_utils_handler = checkout_utils_handler
        self.checkout_handler = checkout_handler

        # Context set per-request
        self._spread_types: list[str] = []
        self._returning_customer: dict | None = None
        self._set_repeat_info_callback: Callable[[bool, str | None], None] | None = None

    def set_context(
        self,
        spread_types: list[str],
        returning_customer: dict | None,
        set_repeat_info_callback: Callable[[bool, str | None], None] | None = None,
    ) -> None:
        """Set per-request context."""
        self._spread_types = spread_types
        self._returning_customer = returning_customer
        self._set_repeat_info_callback = set_repeat_info_callback

    def handle_greeting(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle greeting phase."""
        parsed = parse_open_input(user_input, model=self.model, spread_types=self._spread_types)

        logger.info(
            "Greeting phase parsed: is_greeting=%s, unclear=%s, new_bagel=%s, quantity=%d",
            parsed.is_greeting,
            parsed.unclear,
            parsed.new_bagel,
            parsed.new_bagel_quantity,
        )

        if parsed.is_greeting or parsed.unclear:
            # Phase will be derived as TAKING_ITEMS by orchestrator on next turn
            return StateMachineResult(
                message="Hi! Welcome to Zucker's. What can I get for you today?",
                order=order,
            )

        # User might have ordered something directly - pass the already parsed result
        # Also extract modifiers from the raw input
        extracted_modifiers = extract_modifiers_from_input(user_input)
        if extracted_modifiers.has_modifiers():
            logger.info("Extracted modifiers from greeting input: %s", extracted_modifiers)

        # Phase is derived from orchestrator, no need to set explicitly
        return self.handle_taking_items_with_parsed(parsed, order, extracted_modifiers, user_input)

    def handle_taking_items(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle taking new item orders."""
        # Check for "make it 2" pattern early (before LLM parsing)
        from .parsers.deterministic import MAKE_IT_N_PATTERN
        make_it_n_match = MAKE_IT_N_PATTERN.match(user_input.strip())
        if make_it_n_match:
            num_str = None
            for i in range(1, 8):
                if make_it_n_match.group(i):
                    num_str = make_it_n_match.group(i).lower()
                    break
            if num_str:
                word_to_num = {
                    "two": 2, "three": 3, "four": 4, "five": 5,
                    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
                }
                if num_str.isdigit():
                    target_qty = int(num_str)
                else:
                    target_qty = word_to_num.get(num_str, 0)

                if target_qty >= 2:
                    active_items = order.items.get_active_items()
                    if active_items:
                        last_item = active_items[-1]
                        last_item_name = last_item.get_summary()
                        added_count = target_qty - 1

                        for _ in range(added_count):
                            new_item = last_item.model_copy(deep=True)
                            new_item.id = str(uuid.uuid4())
                            new_item.mark_complete()
                            order.items.add_item(new_item)

                        logger.info("TAKING_ITEMS: Added %d more of '%s'", added_count, last_item_name)

                        if added_count == 1:
                            return StateMachineResult(
                                message=f"I've added a second {last_item_name}. Anything else?",
                                order=order,
                            )
                        else:
                            return StateMachineResult(
                                message=f"I've added {added_count} more {last_item_name}. Anything else?",
                                order=order,
                            )

        parsed = parse_open_input(user_input, model=self.model, spread_types=self._spread_types)

        # Extract modifiers from raw input (keyword-based, no LLM)
        extracted_modifiers = extract_modifiers_from_input(user_input)
        if extracted_modifiers.has_modifiers():
            logger.info("Extracted modifiers from input: %s", extracted_modifiers)

        return self.handle_taking_items_with_parsed(parsed, order, extracted_modifiers, user_input)

    def handle_taking_items_with_parsed(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        extracted_modifiers: ExtractedModifiers | None = None,
        raw_user_input: str | None = None,
    ) -> StateMachineResult:
        """Handle taking new item orders with already-parsed input."""
        logger.info(
            "Parsed open input: new_menu_item='%s', new_bagel=%s, quantity=%d, bagel_details=%d, done_ordering=%s",
            parsed.new_menu_item,
            parsed.new_bagel,
            parsed.new_bagel_quantity,
            len(parsed.bagel_details),
            parsed.done_ordering,
        )

        # Reset menu pagination on any non-"more items" request
        if not parsed.wants_more_menu_items:
            order.clear_menu_pagination()

        if parsed.done_ordering:
            return self.checkout_utils_handler.transition_to_checkout(order)

        # Handle "add [modifier]" patterns that should modify the last coffee
        # e.g., "add vanilla syrup", "add oat milk", "with caramel"
        if raw_user_input:
            input_lower = raw_user_input.lower().strip()
            active_items = order.items.get_active_items()

            # Check if this looks like a modifier addition for the last coffee
            # Patterns: "add X", "with X", "can I get X", "I'd like X added"
            add_modifier_patterns = [
                r"^add\s+",  # "add vanilla syrup"
                r"^with\s+",  # "with caramel"
                r"^can\s+(?:i|you)\s+(?:get|add)\s+",  # "can I get vanilla"
                r"^(?:i'?d?\s+)?like\s+(?:to\s+)?add\s+",  # "I'd like to add vanilla"
                r"^put\s+",  # "put vanilla in it"
                r"^can\s+you\s+put\s+",  # "can you put milk in that"
                r"put\s+.+?\s+in\s+(?:it|that|the|my)",  # "put milk in that"
            ]

            is_add_modifier_request = any(
                re.search(pattern, input_lower) for pattern in add_modifier_patterns
            )

            # Coffee modifiers that should trigger modification instead of new item
            coffee_modifiers = {
                # Syrups
                "vanilla", "caramel", "hazelnut", "mocha", "pumpkin spice",
                "cinnamon", "lavender", "almond", "syrup",
                # Milk options (when adding to existing coffee)
                "milk", "whole milk", "skim milk", "2% milk",
                "oat milk", "almond milk", "soy milk", "coconut milk",
                "oat", "soy", "coconut",
                # Sweeteners
                "sugar", "splenda", "stevia", "honey", "sweetener",
            }

            has_coffee_modifier = any(mod in input_lower for mod in coffee_modifiers)

            # If it's an "add modifier" pattern and the last item is a coffee, modify it
            if is_add_modifier_request and has_coffee_modifier and active_items:
                last_item = active_items[-1]
                if isinstance(last_item, CoffeeItemTask):
                    made_change = False

                    # Check for syrup
                    syrup_options = ["vanilla", "caramel", "hazelnut", "mocha", "pumpkin spice",
                                   "cinnamon", "lavender", "almond"]
                    for syrup in syrup_options:
                        if syrup in input_lower:
                            if last_item.flavor_syrup != syrup:
                                old_syrup = last_item.flavor_syrup or "none"
                                last_item.flavor_syrup = syrup
                                logger.info("Add modifier: added syrup '%s' to coffee (was '%s')", syrup, old_syrup)
                                made_change = True
                            break

                    # Check for milk options (alternatives and regular)
                    milk_options = [
                        ("oat milk", "oat"), ("almond milk", "almond"),
                        ("soy milk", "soy"), ("coconut milk", "coconut"),
                        ("whole milk", "whole"), ("skim milk", "skim"),
                        ("2% milk", "2%"), ("half and half", "half and half"),
                        ("oat", "oat"), ("almond", "almond"),
                        ("soy", "soy"), ("coconut", "coconut"),
                        ("milk", "whole"),  # Plain "milk" defaults to whole milk - must be last
                    ]
                    for pattern, milk_value in milk_options:
                        if pattern in input_lower:
                            if last_item.milk != milk_value:
                                old_milk = last_item.milk or "none"
                                last_item.milk = milk_value
                                logger.info("Add modifier: added milk '%s' to coffee (was '%s')", milk_value, old_milk)
                                made_change = True
                            break

                    # Check for sweeteners
                    sweetener_options = ["sugar", "splenda", "stevia", "honey", "equal", "sweet n low"]
                    for sweetener in sweetener_options:
                        if sweetener in input_lower:
                            if not last_item.sweetener:
                                last_item.sweetener = sweetener
                                last_item.sweetener_quantity = 1
                                # Check for quantity: "two sugars", "2 splenda"
                                qty_match = re.search(rf'(\d+|one|two|three|four|five)\s+{sweetener}', input_lower)
                                if qty_match:
                                    qty_str = qty_match.group(1)
                                    word_to_num = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
                                    last_item.sweetener_quantity = int(qty_str) if qty_str.isdigit() else word_to_num.get(qty_str, 1)
                                logger.info("Add modifier: added sweetener '%s' (qty=%d) to coffee",
                                          sweetener, last_item.sweetener_quantity)
                                made_change = True
                            break

                    if made_change:
                        self.pricing.recalculate_coffee_price(last_item)
                        updated_summary = last_item.get_summary()
                        return StateMachineResult(
                            message=f"Sure, I've added that to your {updated_summary}. Anything else?",
                            order=order,
                        )

        # Handle item replacement: "make it a coke instead", "change it to X", etc.
        replaced_item_name = None
        if parsed.replace_last_item:
            active_items = order.items.get_active_items()
            if active_items:
                last_item = active_items[-1]

                # Check if parsed result has any valid new items
                has_new_items = (
                    parsed.new_bagel or parsed.new_coffee or parsed.new_menu_item or
                    parsed.new_speed_menu_bagel or parsed.new_side_item or parsed.by_pound_items
                )

                # Special case: If last item is a bagel and the "menu item" is a cream cheese sandwich,
                # treat this as a spread change, not a menu item replacement.
                # e.g., "make it blueberry cream cheese" -> change spread, not add Blueberry Cream Cheese Sandwich
                if (has_new_items and parsed.new_menu_item and isinstance(last_item, BagelItemTask)
                    and "cream cheese sandwich" in parsed.new_menu_item.lower()):
                    # Extract the spread name from the menu item name
                    # "Blueberry Cream Cheese Sandwich" -> "blueberry cream cheese"
                    spread_name = parsed.new_menu_item.lower().replace(" sandwich", "")
                    old_spread = last_item.spread or "none"
                    last_item.spread = spread_name
                    logger.info("Replacement: interpreted '%s' as spread change from '%s' to '%s'",
                               parsed.new_menu_item, old_spread, spread_name)

                    # Recalculate price if needed
                    self.pricing.recalculate_bagel_price(last_item)

                    updated_summary = last_item.get_summary()
                    return StateMachineResult(
                        message=f"Sure, I've changed that to {updated_summary}. Anything else?",
                        order=order,
                    )

                # Special case: If last item is a bagel and user wants to change to a different bagel,
                # preserve the existing modifiers (spread, toasted, protein, etc.)
                # e.g., "make it pumpernickel" when they have "plain bagel toasted with cream cheese"
                if (has_new_items and parsed.new_bagel and isinstance(last_item, BagelItemTask)
                    and parsed.new_bagel_type):
                    old_type = last_item.bagel_type or "plain"
                    last_item.bagel_type = parsed.new_bagel_type
                    logger.info("Replacement: changed bagel type from '%s' to '%s', preserving modifiers",
                               old_type, parsed.new_bagel_type)

                    # Recalculate price if needed
                    self.pricing.recalculate_bagel_price(last_item)

                    updated_summary = last_item.get_summary()
                    return StateMachineResult(
                        message=f"Sure, I've changed that to {updated_summary}. Anything else?",
                        order=order,
                    )

                # If no new items parsed and last item is a bagel, try applying as modifiers
                if not has_new_items and isinstance(last_item, BagelItemTask) and raw_user_input:
                    modifiers = extract_modifiers_from_input(raw_user_input)
                    has_modifiers = modifiers.proteins or modifiers.cheeses or modifiers.toppings

                    if has_modifiers:
                        # Apply modifiers to existing bagel instead of replacing
                        logger.info("Replacement: applying modifiers to existing bagel: %s", modifiers)

                        # Update protein - replace existing
                        if modifiers.proteins:
                            last_item.sandwich_protein = modifiers.proteins[0]
                            # Additional proteins go to extras (replace existing extras)
                            last_item.extras = list(modifiers.proteins[1:])
                        else:
                            # Clear protein if not in new modifiers
                            last_item.sandwich_protein = None
                            last_item.extras = []

                        # Add cheeses and toppings to extras
                        last_item.extras.extend(modifiers.cheeses)
                        last_item.extras.extend(modifiers.toppings)

                        # Update spread if specified
                        if modifiers.spreads:
                            last_item.spread = modifiers.spreads[0]
                        else:
                            last_item.spread = "none"

                        # Recalculate price with new modifiers
                        self.pricing.recalculate_bagel_price(last_item)

                        # Return confirmation with updated item
                        updated_summary = last_item.get_summary()
                        return StateMachineResult(
                            message=f"Sure, I've changed that to {updated_summary}. Anything else?",
                            order=order,
                        )
                    else:
                        # Check if user is changing the spread or bagel type
                        # e.g., "make it blueberry cream cheese", "replace with everything"
                        input_lower = raw_user_input.lower()

                        # Check for spread changes FIRST (longer matches before shorter)
                        # e.g., "blueberry cream cheese" should match before "blueberry" (bagel type)
                        new_spread = None
                        for spread in sorted(BAGEL_SPREADS, key=len, reverse=True):
                            if spread in input_lower:
                                # Normalize the spread name
                                new_spread = MODIFIER_NORMALIZATIONS.get(spread, spread)
                                break

                        if new_spread:
                            old_spread = last_item.spread or "none"
                            last_item.spread = new_spread
                            logger.info("Replacement: changed spread from '%s' to '%s'", old_spread, new_spread)

                            # Recalculate price if needed
                            self.pricing.recalculate_bagel_price(last_item)

                            updated_summary = last_item.get_summary()
                            return StateMachineResult(
                                message=f"Sure, I've changed that to {updated_summary}. Anything else?",
                                order=order,
                            )

                        # Check if user is changing the bagel type
                        # e.g., "replace with everything", "can you make it sesame?"
                        new_bagel_type = None
                        for bagel_type in BAGEL_TYPES:
                            if bagel_type in input_lower:
                                new_bagel_type = bagel_type
                                break

                        if new_bagel_type:
                            old_type = last_item.bagel_type or "plain"
                            last_item.bagel_type = new_bagel_type
                            logger.info("Replacement: changed bagel type from '%s' to '%s'", old_type, new_bagel_type)

                            # Recalculate price if needed
                            self.pricing.recalculate_bagel_price(last_item)

                            updated_summary = last_item.get_summary()
                            return StateMachineResult(
                                message=f"Sure, I've changed that to {updated_summary}. Anything else?",
                                order=order,
                            )

                # If no new items parsed and last item is a coffee, check for size/style/milk changes
                if not has_new_items and isinstance(last_item, CoffeeItemTask) and raw_user_input:
                    input_lower = raw_user_input.lower()
                    made_change = False

                    # Check for size changes
                    new_size = None
                    for size in ["small", "large"]:
                        if size in input_lower:
                            new_size = size
                            break

                    if new_size and new_size != last_item.size:
                        old_size = last_item.size or "small"
                        last_item.size = new_size
                        logger.info("Replacement: changed coffee size from '%s' to '%s'", old_size, new_size)
                        made_change = True

                    # Check for style changes (hot/iced)
                    new_style = None
                    if "iced" in input_lower:
                        new_style = "iced"
                        last_item.iced = True
                    elif "hot" in input_lower:
                        new_style = "hot"
                        last_item.iced = False

                    if new_style:
                        logger.info("Replacement: changed coffee style to '%s'", new_style)
                        made_change = True

                    # Check for decaf changes
                    if "decaf" in input_lower:
                        if not last_item.decaf:
                            last_item.decaf = True
                            logger.info("Replacement: changed coffee to decaf")
                            made_change = True
                    elif "regular" in input_lower and last_item.decaf:
                        # "make it regular" means not decaf
                        last_item.decaf = None
                        logger.info("Replacement: changed coffee to regular (not decaf)")
                        made_change = True

                    # Check for milk changes - order matters, check longer patterns first
                    milk_options = [
                        ("oat milk", "oat"), ("almond milk", "almond"), ("whole milk", "whole"),
                        ("skim milk", "skim"), ("2% milk", "2%"), ("soy milk", "soy"),
                        ("coconut milk", "coconut"), ("half and half", "half and half"),
                        ("oat", "oat"), ("almond", "almond"), ("whole", "whole"),
                        ("skim", "skim"), ("soy", "soy"), ("coconut", "coconut"),
                        ("no milk", "none"), ("black", "none"),
                    ]
                    new_milk = None
                    for pattern, milk_value in milk_options:
                        if pattern in input_lower:
                            new_milk = milk_value
                            break

                    if new_milk and new_milk != last_item.milk:
                        old_milk = last_item.milk or "none"
                        last_item.milk = new_milk if new_milk != "none" else None
                        logger.info("Replacement: changed coffee milk from '%s' to '%s'", old_milk, new_milk)
                        made_change = True

                    # Check for flavor syrup changes
                    syrup_options = [
                        "vanilla", "caramel", "hazelnut", "mocha", "pumpkin spice",
                        "cinnamon", "lavender", "almond",
                    ]
                    new_syrup = None
                    for syrup in syrup_options:
                        if syrup in input_lower:
                            new_syrup = syrup
                            break

                    if new_syrup and new_syrup != last_item.flavor_syrup:
                        old_syrup = last_item.flavor_syrup or "none"
                        last_item.flavor_syrup = new_syrup
                        logger.info("Replacement: changed coffee syrup from '%s' to '%s'", old_syrup, new_syrup)
                        made_change = True

                    # Check for syrup removal: "no syrup", "remove the syrup"
                    if ("no syrup" in input_lower or "remove syrup" in input_lower or
                        "without syrup" in input_lower) and last_item.flavor_syrup:
                        old_syrup = last_item.flavor_syrup
                        last_item.flavor_syrup = None
                        logger.info("Replacement: removed coffee syrup '%s'", old_syrup)
                        made_change = True

                    # If any changes were made, recalculate price and return
                    if made_change:
                        self.pricing.recalculate_coffee_price(last_item)
                        updated_summary = last_item.get_summary()
                        return StateMachineResult(
                            message=f"Sure, I've changed that to {updated_summary}. Anything else?",
                            order=order,
                        )

                # Normal replacement: remove old item, new item will be added below
                replaced_item_name = last_item.get_summary()
                last_item_index = order.items.items.index(last_item)
                order.items.remove_item(last_item_index)
                logger.info("Replacement: removed last item '%s' from cart", replaced_item_name)
            else:
                logger.info("Replacement requested but no items in cart to replace")

        # Handle modifier removal: "remove the bacon", "no cheese", etc.
        # Check if cancel_item is actually a modifier on the last item
        if parsed.cancel_item:
            cancel_item_desc = parsed.cancel_item.lower().strip()
            active_items = order.items.get_active_items()

            # Known modifiers that can be removed from bagels
            removable_modifiers = {
                # Proteins
                "bacon", "ham", "sausage", "turkey", "salami", "pastrami", "corned beef",
                "lox", "nova", "salmon", "whitefish", "tuna",
                # Eggs
                "egg", "eggs", "fried egg", "scrambled egg",
                # Cheeses
                "cheese", "american", "american cheese", "swiss", "swiss cheese",
                "cheddar", "cheddar cheese", "muenster", "muenster cheese",
                "provolone", "provolone cheese",
                # Spreads
                "cream cheese", "butter", "mayo", "mayonnaise", "mustard",
                # Toppings
                "tomato", "tomatoes", "lettuce", "onion", "onions", "pickle", "pickles",
                "avocado", "capers",
            }

            # Check if this is a modifier removal on a bagel
            if active_items and cancel_item_desc in removable_modifiers:
                last_item = active_items[-1]
                if isinstance(last_item, BagelItemTask):
                    modifier_removed = False
                    removed_modifier_name = cancel_item_desc

                    # Check sandwich_protein
                    if last_item.sandwich_protein and cancel_item_desc in last_item.sandwich_protein.lower():
                        last_item.sandwich_protein = None
                        modifier_removed = True
                        logger.info("Modifier removal: removed protein '%s' from bagel", cancel_item_desc)

                    # Check extras list
                    if last_item.extras:
                        new_extras = []
                        for extra in last_item.extras:
                            if cancel_item_desc not in extra.lower():
                                new_extras.append(extra)
                            else:
                                modifier_removed = True
                                logger.info("Modifier removal: removed extra '%s' from bagel", extra)
                        last_item.extras = new_extras

                    # Check spread
                    if last_item.spread and cancel_item_desc in last_item.spread.lower():
                        last_item.spread = None
                        last_item.spread_type = None
                        modifier_removed = True
                        logger.info("Modifier removal: removed spread '%s' from bagel", cancel_item_desc)

                    if modifier_removed:
                        # Recalculate price
                        self.pricing.recalculate_bagel_price(last_item)
                        updated_summary = last_item.get_summary()
                        return StateMachineResult(
                            message=f"OK, I've removed the {removed_modifier_name}. Your order is now {updated_summary}. Anything else?",
                            order=order,
                        )

        # Handle item cancellation: "cancel the coke", "remove the bagel", etc.
        if parsed.cancel_item:
            cancel_item_desc = parsed.cancel_item.lower()
            active_items = order.items.get_active_items()
            if active_items:
                # Check if plural removal (e.g., "coffees", "bagels")
                is_plural = cancel_item_desc.endswith('s') and len(cancel_item_desc) > 2
                singular_desc = cancel_item_desc[:-1] if is_plural else cancel_item_desc

                # Find matching items
                items_to_remove = []
                for item in reversed(active_items):  # Search from most recent
                    item_summary = item.get_summary().lower()
                    item_name = getattr(item, 'menu_item_name', '') or ''
                    item_name_lower = item_name.lower()
                    item_type = getattr(item, 'item_type', '') or ''

                    # Check for matches - be careful with empty strings
                    matches = False
                    if cancel_item_desc in item_summary:
                        matches = True
                    elif singular_desc in item_summary:
                        matches = True
                    elif item_name_lower and cancel_item_desc in item_name_lower:
                        matches = True
                    elif item_name_lower and singular_desc in item_name_lower:
                        matches = True
                    elif item_name_lower and item_name_lower in cancel_item_desc:
                        matches = True
                    # Check item_type for "coffees" -> item_type="coffee"
                    elif item_type and (cancel_item_desc == item_type or singular_desc == item_type):
                        matches = True
                    elif any(word in item_summary for word in cancel_item_desc.split() if word):
                        matches = True

                    if matches:
                        items_to_remove.append(item)
                        # If not plural, only remove one item
                        if not is_plural:
                            break

                if items_to_remove:
                    # Remove all matching items
                    removed_names = []
                    for item in items_to_remove:
                        removed_names.append(item.get_summary())
                        idx = order.items.items.index(item)
                        order.items.remove_item(idx)

                    # Build response message
                    if len(removed_names) == 1:
                        removed_str = f"the {removed_names[0]}"
                    else:
                        removed_str = f"the {len(removed_names)} {singular_desc}s"

                    logger.info("Cancellation: removed %d item(s) from cart: %s", len(removed_names), removed_names)

                    remaining_items = order.items.get_active_items()
                    if remaining_items:
                        return StateMachineResult(
                            message=f"OK, I've removed {removed_str}. Anything else?",
                            order=order,
                        )
                    else:
                        return StateMachineResult(
                            message=f"OK, I've removed {removed_str}. What would you like to order?",
                            order=order,
                        )
                else:
                    # Item not found - let them know
                    logger.info("Cancellation: couldn't find item matching '%s'", cancel_item_desc)
                    return StateMachineResult(
                        message=f"I couldn't find {parsed.cancel_item} in your order. What would you like to do?",
                        order=order,
                    )
            else:
                # No items to cancel
                logger.info("Cancellation requested but no items in cart")
                return StateMachineResult(
                    message="There's nothing in your order yet. What can I get for you?",
                    order=order,
                )

        # Handle "make it 2" - add more of the last item
        if parsed.duplicate_last_item > 0:
            active_items = order.items.get_active_items()
            if active_items:
                last_item = active_items[-1]
                last_item_name = last_item.get_summary()
                added_count = parsed.duplicate_last_item

                # Add copies of the last item
                for _ in range(added_count):
                    # Create a copy of the item
                    new_item = last_item.model_copy(deep=True)
                    # Generate a new ID for the copy
                    new_item.id = str(uuid.uuid4())
                    new_item.mark_complete()
                    order.items.add_item(new_item)

                if added_count == 1:
                    logger.info("Added 1 more of '%s' to order", last_item_name)
                    return StateMachineResult(
                        message=f"I've added a second {last_item_name}. Anything else?",
                        order=order,
                    )
                else:
                    logger.info("Added %d more of '%s' to order", added_count, last_item_name)
                    return StateMachineResult(
                        message=f"I've added {added_count} more {last_item_name}. Anything else?",
                        order=order,
                    )
            else:
                logger.info("'Make it N' requested but no items in cart")
                return StateMachineResult(
                    message="There's nothing in your order yet. What can I get for you?",
                    order=order,
                )

        # Handle repeat order request
        if parsed.wants_repeat_order:
            return self.checkout_handler.handle_repeat_order(
                order,
                returning_customer=self._returning_customer,
                set_repeat_info_callback=self._set_repeat_info_callback,
            )

        # Check if user specified order type upfront (e.g., "I'd like to place a pickup order")
        if parsed.order_type:
            order.delivery_method.order_type = parsed.order_type
            logger.info("Order type set from upfront mention: %s", parsed.order_type)
            order_type_display = "pickup" if parsed.order_type == "pickup" else "delivery"
            # Check if they also ordered items in the same message
            has_items = (parsed.new_bagel or parsed.new_coffee or parsed.new_menu_item or
                        parsed.new_speed_menu_bagel or parsed.new_side_item or parsed.by_pound_items)
            if not has_items:
                # Just the order type, no items yet - acknowledge and ask what they want
                return StateMachineResult(
                    message=f"Great, I'll set this up for {order_type_display}. What can I get for you?",
                    order=order,
                )
            # If they also ordered items, continue processing below

        # Track items added for multi-item orders
        items_added = []
        last_result = None

        # Helper to build confirmation message (normal vs replacement)
        def make_confirmation(item_name: str) -> str:
            if replaced_item_name:
                return f"Sure, I've changed that to {item_name}. Anything else?"
            return f"Got it, {item_name}. Anything else?"

        if parsed.new_menu_item:
            # Check if this "menu item" is actually a coffee/beverage that was misparsed
            menu_item_lower = parsed.new_menu_item.lower()
            coffee_beverage_types = {
                "coffee", "latte", "cappuccino", "espresso", "americano", "macchiato",
                "mocha", "cold brew", "tea", "chai", "matcha", "hot chocolate",
                "iced coffee", "iced latte", "iced cappuccino", "iced americano",
            }
            if menu_item_lower in coffee_beverage_types or any(bev in menu_item_lower for bev in coffee_beverage_types):
                # Redirect to coffee handling
                # Extract coffee modifiers deterministically from raw input since LLM may have missed them
                coffee_mods = ExtractedCoffeeModifiers()
                if raw_user_input:
                    coffee_mods = extract_coffee_modifiers_from_input(raw_user_input)
                    logger.info("Extracted coffee modifiers from raw input: sweetener=%s (qty=%d), syrup=%s",
                               coffee_mods.sweetener, coffee_mods.sweetener_quantity, coffee_mods.flavor_syrup)

                # Use LLM-parsed values if available, otherwise use deterministically extracted values
                sweetener = parsed.new_coffee_sweetener or coffee_mods.sweetener
                sweetener_qty = parsed.new_coffee_sweetener_quantity if parsed.new_coffee_sweetener else coffee_mods.sweetener_quantity
                flavor_syrup = parsed.new_coffee_flavor_syrup or coffee_mods.flavor_syrup

                logger.info("Redirecting misparsed menu item '%s' to coffee handler (sweetener=%s, qty=%d, syrup=%s)",
                           parsed.new_menu_item, sweetener, sweetener_qty, flavor_syrup)
                last_result = self.coffee_handler.add_coffee(
                    parsed.new_menu_item,  # Use as coffee type
                    parsed.new_coffee_size,
                    parsed.new_coffee_iced,
                    parsed.new_coffee_milk,
                    sweetener,
                    sweetener_qty,
                    flavor_syrup,
                    parsed.new_menu_item_quantity,
                    order,
                    notes=parsed.new_coffee_notes,
                    decaf=parsed.new_coffee_decaf,
                )
                items_added.append(parsed.new_menu_item)
            else:
                last_result = self.item_adder_handler.add_menu_item(parsed.new_menu_item, parsed.new_menu_item_quantity, order, parsed.new_menu_item_toasted, parsed.new_menu_item_bagel_choice, parsed.new_menu_item_modifications)
                items_added.append(parsed.new_menu_item)
                # If there's also a side item, add it too
                if parsed.new_side_item:
                    side_name, side_error = self.item_adder_handler.add_side_item(parsed.new_side_item, parsed.new_side_item_quantity, order)
                    if side_name:
                        items_added.append(side_name)
                    elif side_error:
                        # Side item not found - return error with main item still added
                        return StateMachineResult(
                            message=f"I've added {parsed.new_menu_item} to your order. {side_error}",
                            order=order,
                        )

            # Add any additional menu items (from multi-item orders like "A Lexington and a BLT")
            if parsed.additional_menu_items:
                # Save whether primary item needs configuration BEFORE adding additional items
                primary_item_needs_config = order.is_configuring_item()
                primary_item_result = last_result
                saved_pending_item_id = order.pending_item_id
                saved_pending_field = order.pending_field
                saved_phase = order.phase

                for extra_item in parsed.additional_menu_items:
                    extra_result = self.item_adder_handler.add_menu_item(
                        extra_item.name,
                        extra_item.quantity,
                        order,
                        extra_item.toasted,
                        extra_item.bagel_choice,
                        extra_item.modifications,
                    )
                    items_added.append(extra_item.name)
                    logger.info("Multi-item order: added additional menu item '%s' (qty=%d)",
                                extra_item.name, extra_item.quantity)
                    # Use the last result to capture any configuration questions
                    if extra_result:
                        last_result = extra_result

                # If primary item needs configuration (e.g., spread sandwich toasted question),
                # ask primary item questions first (additional items were still added to cart)
                if primary_item_needs_config:
                    # Restore pending state for primary item
                    order.pending_item_id = saved_pending_item_id
                    order.pending_field = saved_pending_field
                    order.phase = saved_phase
                    logger.info("Multi-item order: primary item needs config, returning config question")
                    # Build combined confirmation with all items, then ask config question
                    combined_items = ", ".join(items_added)
                    config_question = primary_item_result.message if primary_item_result else "Would you like that toasted?"
                    return StateMachineResult(
                        message=f"Got it, {combined_items}. {config_question}",
                        order=order,
                    )

            # Check if there's ALSO a bagel order in the same message
            if parsed.new_bagel:
                # Save whether menu item needs configuration BEFORE adding bagel
                menu_item_needs_config = order.is_configuring_item()
                menu_item_result = last_result

                # Save pending state - _add_bagel may change it
                saved_pending_item_id = order.pending_item_id
                saved_pending_field = order.pending_field
                saved_phase = order.phase

                # Extract modifiers from raw input for bagel
                bagel_extracted_modifiers = None
                if raw_user_input:
                    bagel_extracted_modifiers = extract_modifiers_from_input(raw_user_input)

                # Add bagel(s) using _add_bagels for quantity support
                bagel_result = self.item_adder_handler.add_bagels(
                    quantity=parsed.new_bagel_quantity,
                    bagel_type=parsed.new_bagel_type,
                    toasted=parsed.new_bagel_toasted,
                    spread=parsed.new_bagel_spread,
                    spread_type=parsed.new_bagel_spread_type,
                    order=order,
                    extracted_modifiers=bagel_extracted_modifiers,
                )
                bagel_desc = f"{parsed.new_bagel_quantity} bagel{'s' if parsed.new_bagel_quantity > 1 else ''}"
                items_added.append(bagel_desc)
                logger.info("Multi-item order: added bagel (type=%s, qty=%d)", parsed.new_bagel_type, parsed.new_bagel_quantity)

                # If menu item needs configuration (e.g., spread sandwich toasted question),
                # ask menu item questions first (bagels were still added to cart)
                if menu_item_needs_config:
                    # Queue bagel for configuration after menu item is done
                    for item in order.items.items:
                        if isinstance(item, BagelItemTask) and item.status == TaskStatus.IN_PROGRESS:
                            order.queue_item_for_config(item.id, "bagel")
                            logger.info("Multi-item order: queued bagel %s for config after menu item", item.id[:8])

                    # Restore pending state
                    order.pending_item_id = saved_pending_item_id
                    order.pending_field = saved_pending_field
                    order.phase = saved_phase
                    logger.info("Multi-item order: menu item needs config, returning menu item config question")
                    return menu_item_result

                # If bagel needs configuration, ask bagel questions first
                if order.is_configuring_item():
                    # If menu item is in progress too, queue it for later
                    for item in order.items.items:
                        if isinstance(item, MenuItemTask) and item.status == TaskStatus.IN_PROGRESS:
                            order.queue_item_for_config(item.id, "menu_item")
                            logger.info("Multi-item order: queued menu item %s for config after bagel", item.id[:8])
                    logger.info("Multi-item order: bagel needs config, returning bagel config question")
                    return bagel_result

                # Neither needs config - combine the messages
                combined_items = ", ".join(items_added)
                last_result = StateMachineResult(
                    message=f"Got it, {combined_items}. Anything else?",
                    order=order,
                )

            # Check if there's ALSO a coffee order in the same message
            if parsed.new_coffee or parsed.coffee_details:
                # Save whether menu item needs configuration BEFORE adding coffee
                # (coffee might change pending_item_id)
                menu_item_needs_config = order.is_configuring_item()
                menu_item_result = last_result  # Save menu item's configuration result

                # Save pending state - _add_coffee may clear it for sodas
                saved_pending_item_id = order.pending_item_id
                saved_pending_field = order.pending_field
                saved_phase = order.phase

                # Add all coffees from coffee_details (or just the single one)
                coffee_result = None
                coffees_to_add = parsed.coffee_details if parsed.coffee_details else []
                if not coffees_to_add and parsed.new_coffee:
                    # Fallback to single coffee if no coffee_details
                    coffees_to_add = [CoffeeOrderDetails(
                        drink_type=parsed.new_coffee_type or "coffee",
                        size=parsed.new_coffee_size,
                        iced=parsed.new_coffee_iced,
                        decaf=parsed.new_coffee_decaf,
                        quantity=parsed.new_coffee_quantity,
                    )]

                for coffee_detail in coffees_to_add:
                    # Use milk/notes from coffee_detail if available, otherwise fall back to parsed values
                    coffee_milk = coffee_detail.milk if coffee_detail.milk else parsed.new_coffee_milk
                    coffee_notes = coffee_detail.notes if coffee_detail.notes else parsed.new_coffee_notes
                    coffee_decaf = getattr(coffee_detail, 'decaf', None) or parsed.new_coffee_decaf
                    coffee_result = self.coffee_handler.add_coffee(
                        coffee_detail.drink_type,
                        coffee_detail.size,
                        coffee_detail.iced,
                        coffee_milk,
                        parsed.new_coffee_sweetener,  # Use shared sweetener
                        parsed.new_coffee_sweetener_quantity,
                        parsed.new_coffee_flavor_syrup,
                        coffee_detail.quantity,
                        order,
                        notes=coffee_notes,
                        decaf=coffee_decaf,
                    )
                    items_added.append(coffee_detail.drink_type)
                    logger.info("Multi-item order: added coffee '%s' (qty=%d, milk=%s, notes=%s)", coffee_detail.drink_type, coffee_detail.quantity, coffee_milk, coffee_notes)

                # If menu item needs configuration (e.g., spread sandwich toasted question),
                # ask menu item questions first (coffees were still added to cart)
                if menu_item_needs_config:
                    # Check if coffees also need configuration (not sodas)
                    # If so, queue them for configuration after menu item is done
                    for item in order.items.items:
                        if isinstance(item, CoffeeItemTask) and item.status == TaskStatus.IN_PROGRESS:
                            order.queue_item_for_config(item.id, "coffee")
                            logger.info("Multi-item order: queued coffee %s for config after menu item", item.id[:8])

                    # Restore pending state that _add_coffee may have cleared
                    order.pending_item_id = saved_pending_item_id
                    order.pending_field = saved_pending_field
                    order.phase = saved_phase
                    logger.info("Multi-item order: menu item needs config, returning menu item config question")
                    return menu_item_result

                # If coffee needs configuration (not a soda), ask coffee questions
                if order.is_configuring_item():
                    logger.info("Multi-item order: coffee needs config, returning coffee config question")
                    return coffee_result

                # Neither needs config - combine the messages
                if last_result and coffee_result:
                    combined_items = ", ".join(items_added)
                    last_result = StateMachineResult(
                        message=f"Got it, {combined_items}. Anything else?",
                        order=order,
                    )

            if last_result:
                # If this was a replacement, modify the message
                if replaced_item_name and "Got it" in last_result.message:
                    last_result = StateMachineResult(
                        message=last_result.message.replace("Got it", "Sure, I've changed that to").rstrip(". Anything else?") + ". Anything else?",
                        order=last_result.order,
                    )
                return last_result

        if parsed.new_side_item and not parsed.new_bagel:
            # Standalone side item order (no bagel)
            return self.item_adder_handler.add_side_item_with_response(parsed.new_side_item, parsed.new_side_item_quantity, order)

        if parsed.new_bagel:
            # Check if we have multiple bagels with different configs
            if parsed.bagel_details and len(parsed.bagel_details) > 0:
                # Multiple bagels with different configurations
                # Pass extracted_modifiers to apply to the first bagel
                result = self.item_adder_handler.add_bagels_from_details(
                    parsed.bagel_details, order, extracted_modifiers
                )
            elif parsed.new_bagel_quantity > 1:
                # Multiple bagels with same (or no) configuration
                # Pass extracted_modifiers to apply to the first bagel
                result = self.item_adder_handler.add_bagels(
                    quantity=parsed.new_bagel_quantity,
                    bagel_type=parsed.new_bagel_type,
                    toasted=parsed.new_bagel_toasted,
                    spread=parsed.new_bagel_spread,
                    spread_type=parsed.new_bagel_spread_type,
                    order=order,
                    extracted_modifiers=extracted_modifiers,
                )
            else:
                # Single bagel
                result = self.item_adder_handler.add_bagel(
                    bagel_type=parsed.new_bagel_type,
                    toasted=parsed.new_bagel_toasted,
                    spread=parsed.new_bagel_spread,
                    spread_type=parsed.new_bagel_spread_type,
                    order=order,
                    extracted_modifiers=extracted_modifiers,
                )
            # If there's also a side item, add it too
            side_name = None
            side_error = None
            if parsed.new_side_item:
                side_name, side_error = self.item_adder_handler.add_side_item(parsed.new_side_item, parsed.new_side_item_quantity, order)

            # Check if there's ALSO a coffee in the same message
            if parsed.new_coffee or parsed.coffee_details:
                # Save whether bagel needs configuration BEFORE adding coffee
                # (coffee might change pending_item_id)
                bagel_needs_config = order.is_configuring_item()
                bagel_result = result  # Save bagel's configuration result

                # Save pending state - _add_coffee may clear it for sodas
                saved_pending_item_id = order.pending_item_id
                saved_pending_field = order.pending_field
                saved_phase = order.phase

                # Add all coffees from coffee_details (or just the single one)
                coffee_result = None
                coffees_to_add = parsed.coffee_details if parsed.coffee_details else []
                if not coffees_to_add and parsed.new_coffee:
                    # Fallback to single coffee if no coffee_details
                    coffees_to_add = [CoffeeOrderDetails(
                        drink_type=parsed.new_coffee_type or "coffee",
                        size=parsed.new_coffee_size,
                        iced=parsed.new_coffee_iced,
                        decaf=parsed.new_coffee_decaf,
                        quantity=parsed.new_coffee_quantity,
                    )]

                for coffee_detail in coffees_to_add:
                    # Use milk/notes from coffee_detail if available, otherwise fall back to parsed values
                    coffee_milk = coffee_detail.milk if coffee_detail.milk else parsed.new_coffee_milk
                    coffee_notes = coffee_detail.notes if coffee_detail.notes else parsed.new_coffee_notes
                    coffee_decaf = getattr(coffee_detail, 'decaf', None) or parsed.new_coffee_decaf
                    coffee_result = self.coffee_handler.add_coffee(
                        coffee_detail.drink_type,
                        coffee_detail.size,
                        coffee_detail.iced,
                        coffee_milk,
                        parsed.new_coffee_sweetener,  # Use shared sweetener
                        parsed.new_coffee_sweetener_quantity,
                        parsed.new_coffee_flavor_syrup,
                        coffee_detail.quantity,
                        order,
                        notes=coffee_notes,
                        decaf=coffee_decaf,
                    )
                    logger.info("Multi-item order: added coffee '%s' (qty=%d, milk=%s, notes=%s)", coffee_detail.drink_type, coffee_detail.quantity, coffee_milk, coffee_notes)

                # If bagel needs configuration, ask bagel questions first
                # (coffees were still added to cart, we'll configure them after bagel)
                if bagel_needs_config:
                    # Check if coffee needs disambiguation (multiple matches like Coffee, Latte, etc.)
                    # In this case, no CoffeeItemTask was created yet - we need to queue the disambiguation
                    if order.pending_drink_options:
                        order.queue_item_for_config(None, "coffee_disambiguation")
                        logger.info("Multi-item order: queued coffee disambiguation for after bagel config")

                    # Check if coffees also need configuration (not sodas)
                    # If so, queue them for configuration after bagel is done
                    for item in order.items.items:
                        if isinstance(item, CoffeeItemTask) and item.status == TaskStatus.IN_PROGRESS:
                            order.queue_item_for_config(item.id, "coffee")
                            logger.info("Multi-item order: queued coffee %s for config after bagel", item.id[:8])

                    # Restore pending state that _add_coffee may have cleared
                    order.pending_item_id = saved_pending_item_id
                    order.pending_field = saved_pending_field
                    order.phase = saved_phase
                    logger.info("Multi-item order: bagel needs config, returning bagel config question")
                    return bagel_result

                # If coffee needs configuration (not a soda), ask coffee questions
                # Check if coffee set up pending configuration
                if order.is_configuring_item():
                    logger.info("Multi-item order: coffee needs config, returning coffee config question")
                    return coffee_result

                # Neither needs config - return combined confirmation
                bagel_desc = f"{parsed.new_bagel_quantity} bagel{'s' if parsed.new_bagel_quantity > 1 else ''}"
                coffee_descs = [c.drink_type for c in coffees_to_add] if coffees_to_add else [parsed.new_coffee_type or "drink"]
                items_list = [bagel_desc]
                if side_name:
                    items_list.append(side_name)
                items_list.extend(coffee_descs)
                combined_items = ", ".join(items_list)
                # If side item was requested but not found, report the error
                if side_error:
                    return StateMachineResult(
                        message=f"Got it, {combined_items}. {side_error}",
                        order=order,
                    )
                return StateMachineResult(
                    message=f"Got it, {combined_items}. Anything else?",
                    order=order,
                )

            # Check if there's ALSO a speed menu bagel in the same message
            if parsed.new_speed_menu_bagel:
                # Save whether bagel needs configuration BEFORE adding speed menu bagel
                bagel_needs_config = order.is_configuring_item()
                bagel_result = result  # Save bagel's configuration result

                # Save pending state - add_speed_menu_bagel may change it
                saved_pending_item_id = order.pending_item_id
                saved_pending_field = order.pending_field
                saved_phase = order.phase

                speed_result = self.speed_menu_handler.add_speed_menu_bagel(
                    parsed.new_speed_menu_bagel_name,
                    parsed.new_speed_menu_bagel_quantity,
                    parsed.new_speed_menu_bagel_toasted,
                    order,
                    bagel_choice=parsed.new_speed_menu_bagel_bagel_choice,
                    modifications=parsed.new_speed_menu_bagel_modifications,
                )

                # If bagel needs configuration, ask bagel questions first
                # (speed menu bagel was still added to cart, we'll configure it after bagel)
                if bagel_needs_config:
                    # Queue speed menu bagel for configuration after bagel is done
                    for item in order.items.items:
                        if isinstance(item, SpeedMenuBagelItemTask) and item.status == TaskStatus.IN_PROGRESS:
                            order.queue_item_for_config(item.id, "speed_menu_bagel")
                            logger.info("Multi-item order: queued speed menu bagel %s for config after bagel", item.id[:8])

                    # Restore pending state for bagel
                    order.pending_item_id = saved_pending_item_id
                    order.pending_field = saved_pending_field
                    order.phase = saved_phase
                    logger.info("Multi-item order: bagel needs config, returning bagel config question")
                    return bagel_result

                # If speed menu bagel needs configuration, ask those questions
                if order.is_configuring_item():
                    # Queue bagel for configuration after speed menu bagel is done
                    for item in order.items.items:
                        if isinstance(item, BagelItemTask) and item.status == TaskStatus.IN_PROGRESS:
                            order.queue_item_for_config(item.id, "bagel")
                            logger.info("Multi-item order: queued bagel %s for config after speed menu bagel", item.id[:8])
                    logger.info("Multi-item order: speed menu bagel needs config, returning config question")
                    return speed_result

                # Neither needs config - return combined confirmation
                bagel_desc = f"{parsed.new_bagel_quantity} bagel{'s' if parsed.new_bagel_quantity > 1 else ''}"
                speed_menu_name = parsed.new_speed_menu_bagel_name or "sandwich"
                combined_items = f"{bagel_desc} and {speed_menu_name}"
                if side_name:
                    combined_items = f"{bagel_desc}, {side_name}, and {speed_menu_name}"
                return StateMachineResult(
                    message=f"Got it, {combined_items}. Anything else?",
                    order=order,
                )

            # If there's a side item but no coffee, update the result message to include it
            if side_name:
                bagel_desc = f"{parsed.new_bagel_quantity} bagel{'s' if parsed.new_bagel_quantity > 1 else ''}"
                return StateMachineResult(
                    message=f"Got it, {bagel_desc} and {side_name}. Anything else?",
                    order=order,
                )
            # If side item was requested but not found, report the error while keeping the bagel
            if side_error:
                return StateMachineResult(
                    message=side_error,
                    order=order,
                )
            return result

        if parsed.new_coffee or parsed.coffee_details:
            # Handle multiple coffees from coffee_details, or fall back to single coffee
            coffees_to_add = parsed.coffee_details if parsed.coffee_details else []
            if not coffees_to_add and parsed.new_coffee:
                # Fallback to single coffee if no coffee_details
                coffees_to_add = [CoffeeOrderDetails(
                    drink_type=parsed.new_coffee_type or "coffee",
                    size=parsed.new_coffee_size,
                    iced=parsed.new_coffee_iced,
                    decaf=parsed.new_coffee_decaf,
                    quantity=parsed.new_coffee_quantity,
                    milk=parsed.new_coffee_milk,
                    notes=parsed.new_coffee_notes,
                )]

            coffee_result = None
            for coffee_detail in coffees_to_add:
                logger.info(
                    "PARSED COFFEE: type=%s, size=%s, QUANTITY=%d",
                    coffee_detail.drink_type, coffee_detail.size, coffee_detail.quantity or 1
                )
                # Use milk/notes from coffee_detail if available, otherwise fall back to parsed values
                coffee_milk = coffee_detail.milk if coffee_detail.milk else parsed.new_coffee_milk
                coffee_notes = coffee_detail.notes if coffee_detail.notes else parsed.new_coffee_notes
                coffee_decaf = getattr(coffee_detail, 'decaf', None) or parsed.new_coffee_decaf
                coffee_result = self.coffee_handler.add_coffee(
                    coffee_detail.drink_type,
                    coffee_detail.size,
                    coffee_detail.iced,
                    coffee_milk,
                    parsed.new_coffee_sweetener,
                    parsed.new_coffee_sweetener_quantity,
                    parsed.new_coffee_flavor_syrup,
                    coffee_detail.quantity or 1,
                    order,
                    notes=coffee_notes,
                    decaf=coffee_decaf,
                )
                items_added.append(coffee_detail.drink_type or "drink")

            # Check if there's ALSO a menu item in the same message
            if parsed.new_menu_item:
                menu_result = self.item_adder_handler.add_menu_item(parsed.new_menu_item, parsed.new_menu_item_quantity, order, parsed.new_menu_item_toasted, parsed.new_menu_item_bagel_choice, parsed.new_menu_item_modifications)
                items_added.append(parsed.new_menu_item)
                # Let get_next_question handle the configuration flow for all items
                return self.checkout_utils_handler.get_next_question(order)

            # Check if there's ALSO a speed menu bagel in the same message
            if parsed.new_speed_menu_bagel:
                self.speed_menu_handler.add_speed_menu_bagel(
                    parsed.new_speed_menu_bagel_name,
                    parsed.new_speed_menu_bagel_quantity,
                    parsed.new_speed_menu_bagel_toasted,
                    order,
                    bagel_choice=parsed.new_speed_menu_bagel_bagel_choice,
                    modifications=parsed.new_speed_menu_bagel_modifications,
                )
                items_added.append(parsed.new_speed_menu_bagel_name)
                # Let get_next_question handle the configuration flow for all items
                return self.checkout_utils_handler.get_next_question(order)

            # If this was a replacement, modify the message
            if replaced_item_name and coffee_result and "Got it" in coffee_result.message:
                coffee_result = StateMachineResult(
                    message=coffee_result.message.replace("Got it", "Sure, I've changed that to"),
                    order=coffee_result.order,
                )
            return coffee_result

        if parsed.new_speed_menu_bagel:
            speed_result = self.speed_menu_handler.add_speed_menu_bagel(
                parsed.new_speed_menu_bagel_name,
                parsed.new_speed_menu_bagel_quantity,
                parsed.new_speed_menu_bagel_toasted,
                order,
                bagel_choice=parsed.new_speed_menu_bagel_bagel_choice,
                modifications=parsed.new_speed_menu_bagel_modifications,
            )
            items_added.append(parsed.new_speed_menu_bagel_name)

            # Check if there's ALSO a coffee in the same message
            if parsed.new_coffee:
                self.coffee_handler.add_coffee(
                    parsed.new_coffee_type,
                    parsed.new_coffee_size,
                    parsed.new_coffee_iced,
                    parsed.new_coffee_milk,
                    parsed.new_coffee_sweetener,
                    parsed.new_coffee_sweetener_quantity,
                    parsed.new_coffee_flavor_syrup,
                    parsed.new_coffee_quantity,
                    order,
                    notes=parsed.new_coffee_notes,
                    decaf=parsed.new_coffee_decaf,
                )
                items_added.append(parsed.new_coffee_type or "drink")
                # Let get_next_question handle the configuration flow for all items
                return self.checkout_utils_handler.get_next_question(order)
            return speed_result

        if parsed.needs_soda_clarification:
            return self.menu_inquiry_handler.handle_soda_clarification(order)

        # Handle price inquiries for specific items
        if parsed.asks_about_price and parsed.price_query_item:
            return self.menu_inquiry_handler.handle_price_inquiry(parsed.price_query_item, order)

        # Handle store info inquiries
        if parsed.asks_store_hours:
            return self.store_info_handler.handle_store_hours_inquiry(order)

        if parsed.asks_store_location:
            return self.store_info_handler.handle_store_location_inquiry(order)

        if parsed.asks_delivery_zone:
            return self.store_info_handler.handle_delivery_zone_inquiry(parsed.delivery_zone_query, order)

        if parsed.asks_recommendation:
            return self.store_info_handler.handle_recommendation_inquiry(parsed.recommendation_category, order)

        if parsed.asks_item_description:
            return self.menu_inquiry_handler.handle_item_description_inquiry(parsed.item_description_query, order)

        if parsed.asks_modifier_options:
            return self.store_info_handler.handle_modifier_inquiry(
                parsed.modifier_query_item, parsed.modifier_query_category, order
            )

        if parsed.menu_query:
            return self.menu_inquiry_handler.handle_menu_query(parsed.menu_query_type, order, show_prices=parsed.asks_about_price)

        if parsed.wants_more_menu_items:
            return self.menu_inquiry_handler.handle_more_menu_items(order)

        if parsed.asking_signature_menu:
            return self.menu_inquiry_handler.handle_signature_menu_inquiry(parsed.signature_menu_type, order)

        if parsed.asking_by_pound:
            return self.by_pound_handler.handle_by_pound_inquiry(parsed.by_pound_category, order)

        if parsed.by_pound_items:
            return self.by_pound_handler.add_by_pound_items(parsed.by_pound_items, order)

        if parsed.is_gratitude:
            return StateMachineResult(
                message="You're welcome! Anything else I can get for you?",
                order=order,
            )

        if parsed.is_help_request:
            return StateMachineResult(
                message="I can help you order bagels, coffee, sandwiches, and more from our menu. Just tell me what you'd like! For example, you can say 'plain bagel with cream cheese' or 'large iced latte'.",
                order=order,
            )

        if parsed.unclear or parsed.is_greeting:
            return StateMachineResult(
                message="What can I get for you?",
                order=order,
            )

        return StateMachineResult(
            message="I didn't catch that. What would you like to order?",
            order=order,
        )
