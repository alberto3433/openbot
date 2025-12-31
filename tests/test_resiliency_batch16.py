"""
Resiliency Test Batch 16: Partial/Incomplete Orders

Tests the system's ability to handle incomplete or multi-turn orders.
"""

import pytest
from sandwich_bot.tasks.state_machine import OrderStateMachine, OrderPhase
from sandwich_bot.tasks.models import OrderTask, BagelItemTask, CoffeeItemTask


class TestPartialIncompleteOrders:
    """Batch 16: Partial/Incomplete Orders."""

    def test_incomplete_i_want_a(self):
        """
        Test: User says incomplete "I want a..."

        Scenario:
        - User says: "I want a"
        - Expected: System asks what they want
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("I want a", order)

        assert result.message is not None
        # Should ask for clarification
        message_lower = result.message.lower()
        asks = any(word in message_lower for word in [
            "what", "which", "help", "like", "order", "?"
        ])
        assert asks, f"Should ask what they want. Message: {result.message}"

    def test_and_also_continuation(self):
        """
        Test: User says "and also..." to add more.

        Scenario:
        - User has: bagel
        - User says: "and also a coffee"
        - Expected: Coffee added to order
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("and also a coffee", order)

        assert result.message is not None
        coffees = [i for i in result.order.items.items if isinstance(i, CoffeeItemTask)]

        # Should add coffee or ask about it
        has_coffee = len(coffees) >= 1
        mentions_coffee = "coffee" in result.message.lower()

        assert has_coffee or mentions_coffee, \
            f"Should add or ask about coffee. Message: {result.message}"

    def test_multi_turn_coffee_then_large(self):
        """
        Test: User orders in multiple turns - "coffee" then "large".

        Scenario:
        - User says: "coffee"
        - System asks about size
        - User says: "large"
        - Expected: Size is set to large
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        # First turn - order coffee
        result1 = sm.process("coffee", order)
        assert result1.message is not None

        # Second turn - specify size
        result2 = sm.process("large", result1.order)
        assert result2.message is not None

        coffees = [i for i in result2.order.items.items if isinstance(i, CoffeeItemTask)]
        if coffees:
            coffee = coffees[0]
            # Should have large size or be asking about it
            assert coffee.size == "large" or "large" in result2.message.lower(), \
                f"Should be large. Size={coffee.size}"
