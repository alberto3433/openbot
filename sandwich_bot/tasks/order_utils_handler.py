"""
Order Utilities Handler for Order State Machine.

This module handles order utility operations like quantity changes,
tax inquiries, and order status queries.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import re
from typing import Callable, TYPE_CHECKING

from .models import (
    OrderTask,
    MenuItemTask,
    BagelItemTask,
    CoffeeItemTask,
    EspressoItemTask,
    SpeedMenuBagelItemTask,
)
from .schemas import StateMachineResult
from ..services.tax_utils import calculate_taxes, round_money

if TYPE_CHECKING:
    from .handler_config import HandlerConfig
    from ..services.message_builder import MessageBuilder

logger = logging.getLogger(__name__)


class OrderUtilsHandler:
    """
    Handles order utility operations.

    Manages quantity changes, tax inquiries, and order status queries.
    """

    def __init__(
        self,
        config: "HandlerConfig | None" = None,
        build_order_summary: Callable[[OrderTask], str] | None = None,
        **kwargs,
    ):
        """
        Initialize the order utils handler.

        Args:
            config: HandlerConfig with shared dependencies.
            build_order_summary: Callback to build order summary string.
            **kwargs: Legacy parameter support.
        """
        if config:
            self._message_builder = config.message_builder
            self._store_info = config.store_info or {}
        else:
            # Legacy support for direct parameters
            self._message_builder = kwargs.get("message_builder")
            self._store_info = {}

        # Handler-specific callback
        self._build_order_summary = build_order_summary or kwargs.get("build_order_summary")

    def set_store_info(self, store_info: dict | None) -> None:
        """Set the store info for tax calculations (legacy method)."""
        self._store_info = store_info or {}

    def set_message_builder(self, message_builder: "MessageBuilder | None") -> None:
        """Set the message builder (for use when set post-init)."""
        self._message_builder = message_builder

    def handle_quantity_change(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle quantity change requests like 'make it two orange juices'.

        Returns StateMachineResult if handled, None otherwise.
        """
        user_lower = user_input.lower().strip()

        # Patterns for quantity changes
        # "make it two X", "can you make it 2 X", "two X instead", "change to two X"
        quantity_patterns = [
            r"make\s+it\s+(\w+)\s+(.+)",
            r"change\s+(?:it\s+)?to\s+(\w+)\s+(.+)",
            r"(\w+)\s+(.+?)\s+instead",
            r"can\s+(?:i\s+)?(?:you\s+)?(?:get|have|make\s+it)\s+(\w+)\s+(.+)",
            r"i(?:'d)?\s+(?:like|want)\s+(\w+)\s+(.+?)(?:\s+instead)?$",
        ]

        # Number word to int mapping
        number_map = {
            "two": 2, "2": 2,
            "three": 3, "3": 3,
            "four": 4, "4": 4,
            "five": 5, "5": 5,
        }

        target_quantity = None
        item_name = None

        for pattern in quantity_patterns:
            match = re.search(pattern, user_lower)
            if match:
                num_word = match.group(1)
                item_desc = match.group(2).strip()
                if num_word in number_map:
                    target_quantity = number_map[num_word]
                    item_name = item_desc
                    logger.info("QUANTITY_CHANGE: Detected pattern '%s' -> qty=%d, item='%s'",
                               pattern, target_quantity, item_name)
                    break

        if not target_quantity or not item_name:
            return None

        # Find matching items in the order
        active_items = order.items.get_active_items()
        matching_items = []

        # Build search terms including synonyms
        # (e.g., "orange juice" should also match "tropicana")
        drink_synonyms = {
            "orange juice": ["tropicana", "fresh squeezed"],
            "oj": ["orange juice", "tropicana", "fresh squeezed"],
            "apple juice": ["martinelli"],
            "lemonade": ["minute maid"],
        }
        search_terms = [item_name]
        for generic_term, synonyms in drink_synonyms.items():
            if generic_term in item_name:
                search_terms.extend(synonyms)

        for item in active_items:
            item_summary = item.get_summary().lower()
            item_type = getattr(item, 'drink_type', '') or getattr(item, 'menu_item_name', '') or ''
            item_type_lower = item_type.lower()

            # Check if any search term matches
            for search_term in search_terms:
                if (search_term in item_summary or
                    search_term in item_type_lower or
                    item_type_lower in search_term or
                    # Handle partial matches
                    any(word in item_summary for word in search_term.split() if len(word) > 3)):
                    matching_items.append(item)
                    break  # Don't add same item multiple times

        if not matching_items:
            logger.info("QUANTITY_CHANGE: No matching items found for '%s'", item_name)
            return None

        # Calculate how many to add
        current_count = len(matching_items)
        to_add = target_quantity - current_count

        if to_add <= 0:
            # Already have enough or more
            logger.info("QUANTITY_CHANGE: Already have %d items, target is %d", current_count, target_quantity)
            summary = self._build_order_summary(order) if self._build_order_summary else ""
            return StateMachineResult(
                message=f"You already have {current_count} in your order.\n\n{summary}\n\nDoes that look right?",
                order=order,
            )

        # Add copies of the first matching item
        template_item = matching_items[0]
        for _ in range(to_add):
            # Create a copy of the item
            if isinstance(template_item, CoffeeItemTask):
                new_item = CoffeeItemTask(
                    drink_type=template_item.drink_type,
                    size=template_item.size,
                    iced=template_item.iced,
                    milk=template_item.milk,
                    sweeteners=list(template_item.sweeteners) if template_item.sweeteners else [],
                    flavor_syrups=list(template_item.flavor_syrups) if template_item.flavor_syrups else [],
                    unit_price=template_item.unit_price,
                    special_instructions=template_item.special_instructions,
                )
                new_item.mark_complete()
                order.items.add_item(new_item)
                logger.info("QUANTITY_CHANGE: Added copy of '%s'", template_item.drink_type)
            elif isinstance(template_item, EspressoItemTask):
                new_item = EspressoItemTask(
                    shots=template_item.shots,
                    decaf=template_item.decaf,
                    unit_price=template_item.unit_price,
                    extra_shots_upcharge=template_item.extra_shots_upcharge,
                    special_instructions=template_item.special_instructions,
                )
                new_item.mark_complete()
                order.items.add_item(new_item)
                logger.info("QUANTITY_CHANGE: Added copy of espresso (%d shots)", template_item.shots)
            elif isinstance(template_item, BagelItemTask):
                new_item = BagelItemTask(
                    bagel_type=template_item.bagel_type,
                    toasted=template_item.toasted,
                    spread=template_item.spread,
                    spread_type=template_item.spread_type,
                    sandwich_protein=template_item.sandwich_protein,
                    extras=list(template_item.extras) if template_item.extras else [],
                    unit_price=template_item.unit_price,
                )
                new_item.mark_complete()
                order.items.add_item(new_item)
                logger.info("QUANTITY_CHANGE: Added copy of bagel")
            elif isinstance(template_item, MenuItemTask):
                new_item = MenuItemTask(
                    menu_item_name=template_item.menu_item_name,
                    unit_price=template_item.unit_price,
                    toasted=template_item.toasted,
                    bagel_choice=template_item.bagel_choice,
                    side_choice=template_item.side_choice,
                )
                new_item.mark_complete()
                order.items.add_item(new_item)
                logger.info("QUANTITY_CHANGE: Added copy of '%s'", template_item.menu_item_name)
            elif isinstance(template_item, SpeedMenuBagelItemTask):
                new_item = SpeedMenuBagelItemTask(
                    speed_menu_name=template_item.speed_menu_name,
                    toasted=template_item.toasted,
                    bagel_choice=template_item.bagel_choice,
                    unit_price=template_item.unit_price,
                )
                new_item.mark_complete()
                order.items.add_item(new_item)
                logger.info("QUANTITY_CHANGE: Added copy of '%s'", template_item.speed_menu_name)

        # Build updated summary
        summary = self._build_order_summary(order) if self._build_order_summary else ""
        if isinstance(template_item, CoffeeItemTask):
            item_display = template_item.drink_type
        elif isinstance(template_item, EspressoItemTask):
            item_display = template_item.get_display_name()
        else:
            item_display = template_item.get_summary()
        return StateMachineResult(
            message=f"Got it, {target_quantity} {item_display}.\n\n{summary}\n\nDoes that look right?",
            order=order,
        )

    def handle_tax_question(self, order: OrderTask) -> StateMachineResult:
        """Handle user asking about total with tax."""
        subtotal = order.items.get_subtotal()

        # Calculate taxes using centralized utility
        taxes = calculate_taxes(subtotal, self._store_info)
        total_with_tax = round_money(subtotal + taxes.total)

        # Format response
        if taxes.total > 0:
            message = f"Your subtotal is ${subtotal:.2f}. With tax, that comes to ${total_with_tax:.2f}. Does that look right?"
        else:
            # No tax configured - just show the subtotal
            message = f"Your total is ${subtotal:.2f}. Does that look right?"

        logger.info("TAX_QUESTION: subtotal=%.2f, city_tax=%.2f, state_tax=%.2f, total=%.2f",
                   subtotal, taxes.city_tax, taxes.state_tax, total_with_tax)

        return StateMachineResult(
            message=message,
            order=order,
        )

    def handle_order_status(self, order: OrderTask) -> StateMachineResult:
        """Handle user asking about their current order status."""
        items = order.items.get_active_items()

        if not items:
            message = "You haven't ordered anything yet. What can I get for you?"
            return StateMachineResult(
                message=message,
                order=order,
            )

        # Build item list with consolidated identical items
        from collections import defaultdict
        item_counts: dict[str, int] = defaultdict(int)
        for item in items:
            summary = item.get_summary()
            item_counts[summary] += 1

        lines = ["So far you have:"]
        for summary, count in item_counts.items():
            if count > 1:
                plural = f"{summary}s" if not summary.endswith("s") else summary
                lines.append(f"• {count} {plural}")
            else:
                lines.append(f"• {summary}")

        # Add total
        subtotal = order.items.get_subtotal()
        if subtotal > 0:
            lines.append(f"\nThat's ${subtotal:.2f} plus tax.")

        # Add phase-appropriate follow-up question
        if self._message_builder:
            follow_up = self._message_builder.get_phase_follow_up(order)
            lines.append(f"\n{follow_up}")

        message = "\n".join(lines)
        logger.info("ORDER_STATUS: %d items, subtotal=%.2f, phase=%s", len(items), subtotal, order.phase)

        return StateMachineResult(
            message=message,
            order=order,
        )
