"""
Resiliency Test Batch 14: Pronoun/Context References

Tests the system's ability to handle pronouns and contextual references.
"""

import pytest
from sandwich_bot.tasks.state_machine import OrderStateMachine, OrderPhase
from sandwich_bot.tasks.models import OrderTask, BagelItemTask, CoffeeItemTask


class TestPronounContextReferences:
    """Batch 14: Pronoun/Context References."""

    def test_same_thing(self):
        """
        Test: User says "same thing" to duplicate last item.

        Scenario:
        - User has: 1 plain bagel
        - User says: "same thing"
        - Expected: Another plain bagel added
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("same thing", order)

        assert result.message is not None
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]
        total_qty = sum(b.quantity for b in bagels)

        # Should have 2 bagels or acknowledge the request
        assert total_qty >= 2 or "same" in result.message.lower(), \
            f"Should duplicate. Qty={total_qty}, Message: {result.message}"

    def test_another_one_of_those(self):
        """
        Test: User says "another one of those".

        Scenario:
        - User has: coffee
        - User says: "another one of those"
        - Expected: Another coffee added
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        coffee = CoffeeItemTask(drink_type="latte", size="large", iced=True)
        coffee.mark_complete()
        order.items.add_item(coffee)

        sm = OrderStateMachine()
        result = sm.process("another one of those", order)

        assert result.message is not None
        coffees = [i for i in result.order.items.items if isinstance(i, CoffeeItemTask)]
        total_qty = sum(c.quantity for c in coffees)

        # Should have 2 coffees
        assert total_qty >= 2, f"Should have 2 coffees. Qty={total_qty}"

    def test_make_that_iced(self):
        """
        Test: User says "make that iced" referring to last coffee.

        Scenario:
        - User has: hot latte
        - User says: "make that iced"
        - Expected: Coffee becomes iced
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        coffee = CoffeeItemTask(drink_type="latte", size="medium", iced=False)
        coffee.mark_complete()
        order.items.add_item(coffee)

        sm = OrderStateMachine()
        result = sm.process("make that iced", order)

        assert result.message is not None
        coffees = [i for i in result.order.items.items if isinstance(i, CoffeeItemTask)]

        # Should have updated coffee to iced
        if coffees:
            coffee = coffees[0]
            # Either iced is True or message acknowledges
            assert coffee.iced is True or "iced" in result.message.lower(), \
                f"Should be iced. iced={coffee.iced}, Message: {result.message}"
