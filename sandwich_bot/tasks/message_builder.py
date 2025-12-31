"""
Message Builder for Order State Machine.

This module handles message and description generation for the order flow,
including order summaries, follow-up questions, and item descriptions.

Extracted from state_machine.py for better separation of concerns.
"""

from collections import defaultdict

from .models import OrderTask
from .schemas import OrderPhase


class MessageBuilder:
    """
    Handles message construction for the order state machine.

    Provides methods for building order summaries, follow-up questions,
    and various text descriptions used in the conversation flow.
    """

    # Ordinal number mappings
    ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}

    def get_ordinal(self, n: int) -> str:
        """Convert number to ordinal (1 -> 'first', 2 -> 'second', etc.)."""
        return self.ORDINALS.get(n, f"#{n}")

    def get_phase_follow_up(self, order: OrderTask) -> str:
        """Get the appropriate follow-up question based on current order phase."""
        phase = order.phase

        if phase == OrderPhase.GREETING.value or phase == OrderPhase.TAKING_ITEMS.value:
            return "Anything else?"
        elif phase == OrderPhase.CONFIGURING_ITEM.value:
            # If configuring an item, ask about the pending field
            return "Anything else?"  # Will return to item config after this
        elif phase == OrderPhase.CHECKOUT_DELIVERY.value:
            return "Is this for pickup or delivery?"
        elif phase == OrderPhase.CHECKOUT_NAME.value:
            return "Can I get a name for the order?"
        elif phase == OrderPhase.CHECKOUT_CONFIRM.value:
            return "Does that look right?"
        elif phase == OrderPhase.CHECKOUT_PAYMENT_METHOD.value:
            return "Would you like your order details sent by text or email?"
        elif phase == OrderPhase.CHECKOUT_PHONE.value:
            return "What's the best phone number to reach you?"
        elif phase == OrderPhase.CHECKOUT_EMAIL.value:
            return "What's your email address?"
        else:
            return "Anything else?"

    def build_order_summary(self, order: OrderTask) -> str:
        """Build order summary string with consolidated identical items and total."""
        lines = ["Here's your order:"]

        # Group items by their summary string to consolidate identical items
        item_data: dict[str, dict] = defaultdict(lambda: {"count": 0, "total_price": 0.0})
        for item in order.items.get_active_items():
            summary = item.get_summary()
            price = item.unit_price * getattr(item, 'quantity', 1)
            item_data[summary]["count"] += 1
            item_data[summary]["total_price"] += price

        # Build consolidated lines (no individual prices, just total at end)
        for summary, data in item_data.items():
            count = data["count"]
            if count > 1:
                # Pluralize: "3 cokes" instead of "3× coke"
                plural = f"{summary}s" if not summary.endswith("s") else summary
                lines.append(f"• {count} {plural}")
            else:
                lines.append(f"• {summary}")

        # Add "plus tax" note
        subtotal = order.items.get_subtotal()
        if subtotal > 0:
            lines.append(f"\nThat's ${subtotal:.2f} plus tax.")

        return "\n".join(lines)

    def get_delivery_question(
        self,
        is_repeat_order: bool = False,
        last_order_type: str | None = None,
    ) -> str:
        """Get the delivery/pickup question, personalized for repeat orders.

        Args:
            is_repeat_order: Whether this is a repeat order from a known customer.
            last_order_type: The last order type ('pickup' or 'delivery').

        Returns:
            The appropriate delivery/pickup question.
        """
        if is_repeat_order and last_order_type == "pickup":
            return "Is this for pickup again, or delivery?"
        elif is_repeat_order and last_order_type == "delivery":
            return "Is this for delivery again, or pickup?"
        else:
            return "Is this for pickup or delivery?"
