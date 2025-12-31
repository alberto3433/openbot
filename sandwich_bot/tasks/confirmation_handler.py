"""
Confirmation Handler for Order State Machine.

This module handles order confirmation and repeat order operations.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import uuid
from typing import Callable, TYPE_CHECKING

from .models import (
    OrderTask,
    MenuItemTask,
    BagelItemTask,
    CoffeeItemTask,
    TaskStatus,
)
from .schemas import OrderPhase, StateMachineResult, ExtractedModifiers, OpenInputResponse
from .parsers import (
    parse_confirmation,
    parse_open_input,
    extract_modifiers_from_input,
    TAX_QUESTION_PATTERN,
)
from .parsers.deterministic import MAKE_IT_N_PATTERN
from .slot_orchestrator import SlotOrchestrator, SlotCategory

if TYPE_CHECKING:
    from .order_utils_handler import OrderUtilsHandler
    from .checkout_utils_handler import CheckoutUtilsHandler

logger = logging.getLogger(__name__)


class ConfirmationHandler:
    """
    Handles order confirmation and repeat order operations.

    Manages order confirmation, quantity changes during confirmation,
    adding items during confirmation, and repeat order processing.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        order_utils_handler: "OrderUtilsHandler | None" = None,
        checkout_utils_handler: "CheckoutUtilsHandler | None" = None,
        transition_to_next_slot: Callable[[OrderTask], None] | None = None,
        handle_taking_items_with_parsed: Callable[
            [OpenInputResponse, OrderTask, ExtractedModifiers, str], StateMachineResult
        ] | None = None,
    ):
        """
        Initialize the confirmation handler.

        Args:
            model: LLM model to use for parsing.
            order_utils_handler: Handler for order utilities.
            checkout_utils_handler: Handler for checkout utilities.
            transition_to_next_slot: Callback to transition to next slot.
            handle_taking_items_with_parsed: Callback to handle parsed items.
        """
        self.model = model
        self.order_utils_handler = order_utils_handler
        self.checkout_utils_handler = checkout_utils_handler
        self._transition_to_next_slot = transition_to_next_slot
        self._handle_taking_items_with_parsed = handle_taking_items_with_parsed
        self._spread_types: list[str] = []
        self._returning_customer: dict | None = None

    def set_context(
        self,
        spread_types: list[str] | None = None,
        returning_customer: dict | None = None,
    ) -> None:
        """Set context for the handler."""
        self._spread_types = spread_types or []
        self._returning_customer = returning_customer

    def handle_confirmation(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle order confirmation."""
        logger.info("CONFIRMATION: handling input '%s', current items: %s",
                   user_input[:50], [i.get_summary() for i in order.items.items])

        # Check for tax question first (deterministic pattern match)
        if TAX_QUESTION_PATTERN.search(user_input):
            logger.info("CONFIRMATION: Tax question detected")
            if self.order_utils_handler:
                return self.order_utils_handler.handle_tax_question(order)

        # Check for quantity change patterns (e.g., "make it two orange juices")
        if self.order_utils_handler:
            quantity_result = self.order_utils_handler.handle_quantity_change(user_input, order)
            if quantity_result:
                return quantity_result

        # Check for "make it 2" pattern (duplicate last item) - deterministic, no LLM needed
        make_it_n_match = MAKE_IT_N_PATTERN.match(user_input.strip())
        if make_it_n_match:
            result = self._handle_make_it_n(make_it_n_match, order)
            if result:
                return result

        parsed = parse_confirmation(user_input, model=self.model)
        logger.info("CONFIRMATION: parse result - wants_changes=%s, confirmed=%s, asks_about_tax=%s",
                   parsed.wants_changes, parsed.confirmed, parsed.asks_about_tax)

        # Handle tax question from LLM parse as fallback
        if parsed.asks_about_tax:
            logger.info("CONFIRMATION: Tax question detected (LLM)")
            if self.order_utils_handler:
                return self.order_utils_handler.handle_tax_question(order)

        if parsed.wants_changes:
            return self._handle_wants_changes(user_input, order)

        if parsed.confirmed:
            return self._handle_confirmed(order)

        return StateMachineResult(
            message="Does the order look correct?",
            order=order,
        )

    def _handle_make_it_n(self, match, order: OrderTask) -> StateMachineResult | None:
        """Handle 'make it N' pattern to duplicate items."""
        num_str = None
        for i in range(1, 8):
            if match.group(i):
                num_str = match.group(i).lower()
                break

        if not num_str:
            return None

        word_to_num = {
            "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
        }
        if num_str.isdigit():
            target_qty = int(num_str)
        else:
            target_qty = word_to_num.get(num_str, 0)

        if target_qty < 2:
            return None

        active_items = order.items.get_active_items()
        if not active_items:
            return None

        last_item = active_items[-1]
        last_item_name = last_item.get_summary()
        added_count = target_qty - 1

        for _ in range(added_count):
            new_item = last_item.model_copy(deep=True)
            new_item.id = str(uuid.uuid4())
            new_item.mark_complete()
            order.items.add_item(new_item)

        logger.info("CONFIRMATION: Added %d more of '%s'", added_count, last_item_name)

        # Return to confirmation with updated summary
        summary = ""
        if self.checkout_utils_handler:
            summary = self.checkout_utils_handler.build_order_summary(order)

        if added_count == 1:
            return StateMachineResult(
                message=f"I've added a second {last_item_name}.\n\n{summary}\n\nDoes that look right?",
                order=order,
            )
        else:
            return StateMachineResult(
                message=f"I've added {added_count} more {last_item_name}.\n\n{summary}\n\nDoes that look right?",
                order=order,
            )

    def _handle_wants_changes(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user wanting to make changes during confirmation."""
        # User wants to make changes - reset order_reviewed so orchestrator knows
        order.checkout.order_reviewed = False

        # Try to parse the input for new items
        item_parsed = parse_open_input(user_input, model=self.model, spread_types=self._spread_types)
        logger.info("CONFIRMATION: parse_open_input result - new_menu_item=%s, new_bagel=%s, new_coffee=%s, new_coffee_type=%s, new_speed_menu_bagel=%s",
                   item_parsed.new_menu_item, item_parsed.new_bagel, item_parsed.new_coffee, item_parsed.new_coffee_type, item_parsed.new_speed_menu_bagel)

        # If they mentioned a new item, process it
        if item_parsed.new_menu_item or item_parsed.new_bagel or item_parsed.new_coffee or item_parsed.new_speed_menu_bagel:
            logger.info("CONFIRMATION: Detected new item! Processing via _handle_taking_items_with_parsed")
            extracted_modifiers = extract_modifiers_from_input(user_input)

            # Use orchestrator to determine phase before processing
            if self._transition_to_next_slot:
                self._transition_to_next_slot(order)

            if self._handle_taking_items_with_parsed:
                result = self._handle_taking_items_with_parsed(item_parsed, order, extracted_modifiers, user_input)

                # Log items in result.order vs original order
                logger.info("CONFIRMATION: result.order items = %s", [i.get_summary() for i in result.order.items.items])
                logger.info("CONFIRMATION: original order items = %s", [i.get_summary() for i in order.items.items])
                logger.info("CONFIRMATION: result.order.phase = %s", result.order.phase)

                # If there are pending drink options awaiting clarification, return that result
                if result.order.pending_drink_options:
                    logger.info("CONFIRMATION: Pending drink options, returning clarification message")
                    return result

                # Use orchestrator to determine if we should go back to confirmation
                orchestrator = SlotOrchestrator(result.order)
                next_slot = orchestrator.get_next_slot()

                if (next_slot and next_slot.category == SlotCategory.ORDER_CONFIRM and
                    result.order.customer_info.name and
                    result.order.delivery_method.order_type):
                    logger.info("CONFIRMATION: Item added, returning to confirmation (orchestrator says ORDER_CONFIRM)")
                    if self._transition_to_next_slot:
                        self._transition_to_next_slot(result.order)
                    summary = ""
                    if self.checkout_utils_handler:
                        summary = self.checkout_utils_handler.build_order_summary(result.order)
                    logger.info("CONFIRMATION: Built summary, items count = %d", len(result.order.items.items))
                    return StateMachineResult(
                        message=f"{summary}\n\nDoes that look right?",
                        order=result.order,
                    )

                return result

        # No new item detected, use orchestrator to determine phase
        if self._transition_to_next_slot:
            self._transition_to_next_slot(order)
        return StateMachineResult(
            message="No problem. What would you like to change?",
            order=order,
        )

    def _handle_confirmed(self, order: OrderTask) -> StateMachineResult:
        """Handle user confirming the order."""
        # Mark order as reviewed but not yet fully confirmed
        order.checkout.order_reviewed = True

        # For returning customers, auto-send to their last used contact method
        if self._returning_customer:
            # Prefer email if available, otherwise use phone
            email = self._returning_customer.get("email") or order.customer_info.email
            phone = self._returning_customer.get("phone") or order.customer_info.phone

            if email:
                # Auto-send to email
                order.payment.method = "card_link"
                order.customer_info.email = email
                order.payment.payment_link_destination = email
                order.checkout.generate_order_number()
                order.checkout.confirmed = True
                if self._transition_to_next_slot:
                    self._transition_to_next_slot(order)
                return StateMachineResult(
                    message=f"An email with a payment link has been sent to {email}. "
                           f"Your order number is {order.checkout.short_order_number}. "
                           f"Thank you, {order.customer_info.name}!",
                    order=order,
                    is_complete=True,
                )
            elif phone:
                # Auto-send to phone
                order.payment.method = "card_link"
                order.customer_info.phone = phone
                order.payment.payment_link_destination = phone
                order.checkout.generate_order_number()
                order.checkout.confirmed = True
                if self._transition_to_next_slot:
                    self._transition_to_next_slot(order)
                return StateMachineResult(
                    message=f"A text with a payment link has been sent to {phone}. "
                           f"Your order number is {order.checkout.short_order_number}. "
                           f"Thank you, {order.customer_info.name}!",
                    order=order,
                    is_complete=True,
                )

        # Use orchestrator to determine next phase (should be PAYMENT_METHOD)
        if self._transition_to_next_slot:
            self._transition_to_next_slot(order)
        return StateMachineResult(
            message="Would you like your order details sent by text or email?",
            order=order,
        )

    def handle_repeat_order(
        self,
        order: OrderTask,
        returning_customer: dict | None = None,
        set_repeat_info_callback: Callable[[bool, str | None], None] | None = None,
    ) -> StateMachineResult:
        """
        Handle a request to repeat the customer's previous order.

        Copies items from returning_customer.last_order_items to the current order.
        """
        customer = returning_customer or self._returning_customer

        if not customer:
            logger.info("Repeat order requested but no returning customer data")
            return StateMachineResult(
                message="I don't have a previous order on file for you. What can I get for you today?",
                order=order,
            )

        last_order_items = customer.get("last_order_items", [])
        if not last_order_items:
            logger.info("Repeat order requested but no last_order_items in returning_customer")
            return StateMachineResult(
                message="I don't have a previous order on file for you. What can I get for you today?",
                order=order,
            )

        # Copy items from previous order
        items_added = []
        for prev_item in last_order_items:
            item_type = prev_item.get("item_type", "sandwich")
            menu_item_name = prev_item.get("menu_item_name")
            quantity = prev_item.get("quantity", 1)
            qty_word = self._quantity_to_words(quantity)

            # Add each item based on type
            if item_type == "bagel":
                self._add_repeat_bagel(prev_item, order, quantity, qty_word, items_added)
            elif item_type in ("coffee", "drink"):
                self._add_repeat_coffee(prev_item, order, quantity, qty_word, items_added)
            elif menu_item_name:
                self._add_repeat_menu_item(prev_item, order, quantity, qty_word, items_added)

        # Copy customer info if available (name, phone, email)
        if customer.get("name") and not order.customer_info.name:
            order.customer_info.name = customer["name"]
        if customer.get("phone") and not order.customer_info.phone:
            order.customer_info.phone = customer["phone"]
        if customer.get("email") and not order.customer_info.email:
            order.customer_info.email = customer["email"]

        # Store last order type for "pickup again?" / "delivery again?" prompt
        if customer.get("last_order_type") and set_repeat_info_callback:
            set_repeat_info_callback(True, customer["last_order_type"])

        logger.info("Repeat order: added %d item types from previous order", len(items_added))

        # Build confirmation message
        if items_added:
            items_str = ", ".join(items_added)
            order.phase = OrderPhase.TAKING_ITEMS.value
            return StateMachineResult(
                message=f"Got it, I've added your previous order: {items_str}. Anything else?",
                order=order,
            )
        else:
            return StateMachineResult(
                message="I couldn't find any items in your previous order. What can I get for you today?",
                order=order,
            )

    def _add_repeat_bagel(
        self,
        prev_item: dict,
        order: OrderTask,
        quantity: int,
        qty_word: str,
        items_added: list[str],
    ) -> None:
        """Add a repeated bagel item to the order."""
        bagel_type = prev_item.get("bread")
        toasted = prev_item.get("toasted")
        spread = prev_item.get("spread")
        spread_type = prev_item.get("spread_type")
        price = prev_item.get("price", 0)

        bagel = BagelItemTask(
            bagel_type=bagel_type,
            toasted=toasted,
            spread=spread,
            spread_type=spread_type,
            unit_price=price,
        )
        bagel.status = TaskStatus.COMPLETE
        for _ in range(quantity):
            order.items.add_item(bagel)

        # Build descriptive name with modifiers
        desc_parts = [bagel_type or "bagel"]
        if toasted is True:
            desc_parts.append("toasted")
        if spread:
            desc_parts.append(f"with {spread}")
        items_added.append(f"{qty_word} {' '.join(desc_parts)}")

    def _add_repeat_coffee(
        self,
        prev_item: dict,
        order: OrderTask,
        quantity: int,
        qty_word: str,
        items_added: list[str],
    ) -> None:
        """Add a repeated coffee/drink item to the order."""
        menu_item_name = prev_item.get("menu_item_name")
        drink_type = prev_item.get("coffee_type") or prev_item.get("drink_type") or menu_item_name

        # Convert style ("iced"/"hot") to iced boolean
        style = prev_item.get("style")
        if style == "iced":
            iced = True
        elif style == "hot":
            iced = False
        else:
            iced = prev_item.get("iced")

        size = prev_item.get("size")
        milk = prev_item.get("milk")
        sweetener = prev_item.get("sweetener")
        flavor_syrup = prev_item.get("flavor_syrup")
        price = prev_item.get("price", 0)

        coffee = CoffeeItemTask(
            drink_type=drink_type,
            size=size,
            iced=iced,
            milk=milk,
            sweetener=sweetener,
            sweetener_quantity=prev_item.get("sweetener_quantity", 1),
            flavor_syrup=flavor_syrup,
            unit_price=price,
        )
        coffee.status = TaskStatus.COMPLETE
        for _ in range(quantity):
            order.items.add_item(coffee)

        # Build descriptive name with modifiers
        desc_parts = []
        if size:
            desc_parts.append(size)
        if iced is True:
            desc_parts.append("iced")
        elif iced is False:
            desc_parts.append("hot")
        desc_parts.append(drink_type or "coffee")
        if milk:
            desc_parts.append(f"with {milk} milk")
        if flavor_syrup:
            desc_parts.append(f"with {flavor_syrup}")

        items_added.append(f"{qty_word} {' '.join(desc_parts)}")

    def _add_repeat_menu_item(
        self,
        prev_item: dict,
        order: OrderTask,
        quantity: int,
        qty_word: str,
        items_added: list[str],
    ) -> None:
        """Add a repeated generic menu item to the order."""
        menu_item_name = prev_item.get("menu_item_name")
        price = prev_item.get("price", 0)

        item = MenuItemTask(
            menu_item_name=menu_item_name,
            unit_price=price,
        )
        item.status = TaskStatus.COMPLETE
        for _ in range(quantity):
            order.items.add_item(item)
        items_added.append(f"{qty_word} {menu_item_name}")

    @staticmethod
    def _quantity_to_words(n: int) -> str:
        """Convert quantity to words for natural speech."""
        words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
                 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}
        return words.get(n, str(n))

    @staticmethod
    def get_ordinal(n: int) -> str:
        """Convert number to ordinal (1 -> 'first', 2 -> 'second', etc.)."""
        ordinals = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}
        return ordinals.get(n, f"#{n}")
