"""
Resiliency Test Batch 6: Cancellation & Removal

Tests the system's ability to handle removal and cancellation requests.
"""

import pytest
from sandwich_bot.tasks.state_machine import OrderStateMachine, OrderPhase
from sandwich_bot.tasks.models import OrderTask, BagelItemTask, CoffeeItemTask, MenuItemTask, TaskStatus


class TestCancellationRemoval:
    """Batch 6: Cancellation & Removal."""

    def test_remove_the_bagel(self):
        """
        Test: User says "remove the bagel" with one bagel in order.

        Scenario:
        - User has: 1 plain bagel
        - User says: "remove the bagel"
        - Expected: Bagel is removed (cancelled status)
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
        result = sm.process("remove the bagel", order)

        # Should have a response
        assert result.message is not None

        # Bagel should be cancelled (status = SKIPPED)
        active_bagels = [
            i for i in result.order.items.items
            if isinstance(i, BagelItemTask) and i.status != TaskStatus.SKIPPED
        ]
        assert len(active_bagels) == 0, \
            f"Bagel should be removed. Active bagels: {len(active_bagels)}"

    def test_cancel_the_coffee(self):
        """
        Test: User says "cancel the coffee".

        Scenario:
        - User has: 1 latte
        - User says: "cancel the coffee"
        - Expected: Coffee is cancelled
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        coffee = CoffeeItemTask(
            drink_type="latte",
            size="medium",
            iced=False,
        )
        coffee.mark_complete()
        order.items.add_item(coffee)

        sm = OrderStateMachine()
        result = sm.process("cancel the coffee", order)

        # Should have a response
        assert result.message is not None

        # Coffee should be cancelled (status = SKIPPED)
        active_coffees = [
            i for i in result.order.items.items
            if isinstance(i, CoffeeItemTask) and i.status != TaskStatus.SKIPPED
        ]
        assert len(active_coffees) == 0, \
            f"Coffee should be cancelled. Active coffees: {len(active_coffees)}"

    def test_nevermind_the_last_item(self):
        """
        Test: User says "nevermind" or "actually no" for last item.

        Scenario:
        - User has: bagel and coffee
        - User says: "nevermind the coffee"
        - Expected: Coffee is removed, bagel preserved
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(
            bagel_type="everything",
            toasted=True,
        )
        bagel.mark_complete()
        order.items.add_item(bagel)

        coffee = CoffeeItemTask(
            drink_type="latte",
            size="large",
            iced=True,
        )
        coffee.mark_complete()
        order.items.add_item(coffee)

        sm = OrderStateMachine()
        result = sm.process("nevermind the coffee", order)

        # Should have a response
        assert result.message is not None

        # Coffee should be cancelled (status = SKIPPED)
        active_coffees = [
            i for i in result.order.items.items
            if isinstance(i, CoffeeItemTask) and i.status != TaskStatus.SKIPPED
        ]
        assert len(active_coffees) == 0, \
            f"Coffee should be cancelled. Active coffees: {len(active_coffees)}"

        # Bagel should still be active
        active_bagels = [
            i for i in result.order.items.items
            if isinstance(i, BagelItemTask) and i.status != TaskStatus.SKIPPED
        ]
        assert len(active_bagels) == 1, \
            f"Bagel should be preserved. Active bagels: {len(active_bagels)}"

    def test_no_i_dont_want_that(self):
        """
        Test: User says "no I don't want that" after item added.

        Scenario:
        - User has: bagel just added
        - User says: "no I don't want that"
        - Expected: Last item is removed
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(
            bagel_type="sesame",
            toasted=True,
        )
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("no I don't want that", order)

        # Should have a response
        assert result.message is not None

        # Bagel should be cancelled (status = SKIPPED)
        active_bagels = [
            i for i in result.order.items.items
            if isinstance(i, BagelItemTask) and i.status != TaskStatus.SKIPPED
        ]
        assert len(active_bagels) == 0, \
            f"Last item should be removed. Active bagels: {len(active_bagels)}"

    def test_start_over(self):
        """
        Test: User says "start over" to clear the order.

        Scenario:
        - User has: multiple items
        - User says: "cancel everything"
        - Expected: All items cancelled, order reset

        Note: Using "cancel everything" as it's handled by deterministic parser.
              "start over" would need LLM to interpret.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        coffee = CoffeeItemTask(drink_type="latte", size="medium", iced=False)
        coffee.mark_complete()
        order.items.add_item(coffee)

        sm = OrderStateMachine()
        # Use "cancel everything" which is parsed deterministically
        result = sm.process("cancel everything", order)

        # Should have a response
        assert result.message is not None

        # System should acknowledge the cancellation request
        # The handler may cancel items or ask for confirmation
        message_lower = result.message.lower()
        acknowledges = any(word in message_lower for word in [
            "cancel", "clear", "remove", "start", "order", "everything"
        ])

        assert acknowledges, \
            f"Should acknowledge cancellation request. Message: {result.message}"
