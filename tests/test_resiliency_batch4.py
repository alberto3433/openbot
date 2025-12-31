"""
Resiliency Test Batch 4: Edge Case Quantities

Tests the system's ability to handle various quantity expressions,
including words, large numbers, and quantity changes.
"""

import pytest
from sandwich_bot.tasks.state_machine import OrderStateMachine, OrderPhase
from sandwich_bot.tasks.models import OrderTask, BagelItemTask, CoffeeItemTask


class TestEdgeCaseQuantities:
    """Batch 4: Edge Case Quantities."""

    def test_half_dozen_bagels(self):
        """
        Test: User orders "half dozen bagels".

        Scenario:
        - User says: "half dozen plain bagels"
        - Expected: System adds 6 bagels
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("half dozen plain bagels", order)

        # Should have a response
        assert result.message is not None

        # Should have added bagels with quantity 6
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]
        total_quantity = sum(b.quantity for b in bagels)

        assert total_quantity == 6, f"Should have 6 bagels, got {total_quantity}"

    def test_dozen_bagels(self):
        """
        Test: User orders "a dozen bagels".

        Scenario:
        - User says: "a dozen everything bagels"
        - Expected: System adds 12 bagels
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("a dozen everything bagels", order)

        # Should have a response
        assert result.message is not None

        # Should have added bagels with quantity 12
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]
        total_quantity = sum(b.quantity for b in bagels)

        assert total_quantity == 12, f"Should have 12 bagels, got {total_quantity}"

    def test_couple_of_coffees(self):
        """
        Test: User orders "a couple of coffees".

        Scenario:
        - User says: "a couple of large iced lattes"
        - Expected: System adds 2 coffees
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("a couple of large iced lattes", order)

        # Should have a response
        assert result.message is not None

        # Should have added coffees with quantity 2
        coffees = [i for i in result.order.items.items if isinstance(i, CoffeeItemTask)]
        total_quantity = sum(c.quantity for c in coffees)

        assert total_quantity == 2, f"Should have 2 coffees, got {total_quantity}"

    def test_few_bagels(self):
        """
        Test: User orders "a few bagels".

        Scenario:
        - User says: "a few sesame bagels"
        - Expected: System either asks how many or adds a reasonable default (3)
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("a few sesame bagels", order)

        # Should have a response
        assert result.message is not None

        # Should either:
        # 1. Add bagels with reasonable quantity (3), OR
        # 2. Ask how many
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]
        total_quantity = sum(b.quantity for b in bagels)

        asks_quantity = any(word in result.message.lower() for word in [
            "how many", "how much", "quantity"
        ])

        # Either added bagels or asking
        assert total_quantity >= 1 or asks_quantity, \
            f"Should add bagels or ask quantity. Qty={total_quantity}, Message: {result.message}"

    def test_one_more_bagel(self):
        """
        Test: User has a bagel and says "one more".

        Scenario:
        - User has: 1 plain bagel
        - User says: "one more"
        - Expected: quantity becomes 2
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(
            bagel_type="plain",
            toasted=True,
        )
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("one more", order)

        # Should have a response
        assert result.message is not None

        # Should have 2 bagels total
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]
        total_quantity = sum(b.quantity for b in bagels)

        assert total_quantity == 2, f"Should have 2 bagels, got {total_quantity}"
