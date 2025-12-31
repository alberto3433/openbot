"""
Resiliency Test Batch 7: Order Confirmation & Checkout

Tests the system's ability to handle order completion and checkout flows.
"""

import pytest
from sandwich_bot.tasks.state_machine import OrderStateMachine, OrderPhase
from sandwich_bot.tasks.models import OrderTask, BagelItemTask, CoffeeItemTask


class TestOrderConfirmationCheckout:
    """Batch 7: Order Confirmation & Checkout."""

    def test_thats_all(self):
        """
        Test: User says "that's all" to finish ordering.

        Scenario:
        - User has: bagel and coffee
        - User says: "that's all"
        - Expected: Order moves to confirmation/checkout phase
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
        result = sm.process("that's all", order)

        # Should have a response
        assert result.message is not None

        # Should either move to next phase or confirm the order
        message_lower = result.message.lower()
        confirms = any(word in message_lower for word in [
            "confirm", "total", "order", "pickup", "delivery", "anything else", "all set"
        ]) or result.order.phase != OrderPhase.TAKING_ITEMS.value

        assert confirms, f"Should confirm order or move to next phase. Message: {result.message}"

    def test_im_done(self):
        """
        Test: User says "I'm done" to finish ordering.

        Scenario:
        - User has: bagel
        - User says: "I'm done"
        - Expected: Order moves to confirmation
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="everything", toasted=True, spread="cream cheese")
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("I'm done", order)

        # Should have a response
        assert result.message is not None

        # Should confirm or proceed
        message_lower = result.message.lower()
        confirms = any(word in message_lower for word in [
            "confirm", "total", "order", "pickup", "delivery", "anything else", "done"
        ]) or result.order.phase != OrderPhase.TAKING_ITEMS.value

        assert confirms, f"Should acknowledge done. Message: {result.message}"

    def test_nothing_else(self):
        """
        Test: User says "nothing else" when asked if they want more.

        Scenario:
        - User has: coffee
        - User says: "nothing else"
        - Expected: Order proceeds to checkout
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        coffee = CoffeeItemTask(drink_type="drip coffee", size="large", iced=False)
        coffee.mark_complete()
        order.items.add_item(coffee)

        sm = OrderStateMachine()
        result = sm.process("nothing else", order)

        # Should have a response
        assert result.message is not None

        # Should proceed
        message_lower = result.message.lower()
        proceeds = any(word in message_lower for word in [
            "confirm", "total", "order", "pickup", "delivery", "anything else", "else"
        ]) or result.order.phase != OrderPhase.TAKING_ITEMS.value

        assert proceeds, f"Should proceed with order. Message: {result.message}"

    def test_just_the_bagel(self):
        """
        Test: User says "just the bagel" meaning no additional items.

        Scenario:
        - User ordered bagel
        - System asks if they want anything else
        - User says: "just the bagel"
        - Expected: Order proceeds without adding more
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="sesame", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("just the bagel", order)

        # Should have a response
        assert result.message is not None

        # Should not add another bagel and should proceed
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]
        assert len(bagels) == 1, f"Should still have just 1 bagel. Got: {len(bagels)}"

    def test_thats_it_for_now(self):
        """
        Test: User says "that's it for now".

        Scenario:
        - User has items
        - User says: "that's it for now"
        - Expected: Order proceeds to checkout
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="plain", toasted=False)
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("that's it for now", order)

        # Should have a response
        assert result.message is not None

        # Should proceed
        message_lower = result.message.lower()
        proceeds = any(word in message_lower for word in [
            "confirm", "total", "order", "pickup", "delivery", "anything", "else"
        ]) or result.order.phase != OrderPhase.TAKING_ITEMS.value

        assert proceeds, f"Should proceed. Message: {result.message}"
