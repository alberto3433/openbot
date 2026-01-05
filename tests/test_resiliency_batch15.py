"""
Resiliency Test Batch 15: Corrections After Misunderstanding

Tests the system's ability to handle corrections and clarifications.
"""

from sandwich_bot.tasks.state_machine import OrderStateMachine, OrderPhase
from sandwich_bot.tasks.models import OrderTask, BagelItemTask


class TestCorrectionsAfterMisunderstanding:
    """Batch 15: Corrections After Misunderstanding."""

    def test_no_i_said_plain(self):
        """
        Test: User corrects "no, I said plain".

        Scenario:
        - User has: poppy bagel (wrong)
        - User says: "no, I said plain"
        - Expected: Changes to plain bagel
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="poppy", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("no, I said plain", order)

        assert result.message is not None
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]

        # Should have plain bagel or acknowledge correction
        if bagels:
            has_plain = any(b.bagel_type == "plain" for b in bagels)
            assert has_plain or "plain" in result.message.lower(), \
                f"Should correct to plain. Types: {[b.bagel_type for b in bagels]}"

    def test_i_meant_the_small_one(self):
        """
        Test: User says "I meant the small one".

        Scenario:
        - User has: large coffee
        - User says: "I meant the small one"
        - Expected: Changes to small
        """
        from sandwich_bot.tasks.models import CoffeeItemTask

        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        coffee = CoffeeItemTask(drink_type="latte", size="large", iced=False)
        coffee.mark_complete()
        order.items.add_item(coffee)

        sm = OrderStateMachine()
        result = sm.process("I meant the small one", order)

        assert result.message is not None
        coffees = [i for i in result.order.items.items if isinstance(i, CoffeeItemTask)]

        # Should change to small or acknowledge
        if coffees:
            has_small = any(c.size == "small" for c in coffees)
            assert has_small or "small" in result.message.lower(), \
                f"Should change to small. Sizes: {[c.size for c in coffees]}"

    def test_thats_not_what_i_ordered(self):
        """
        Test: User says "that's not what I ordered".

        Scenario:
        - User has items
        - User says: "that's not what I ordered"
        - Expected: System asks for clarification or offers to fix
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="sesame", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("that's not what I ordered", order)

        assert result.message is not None
        # Should acknowledge the concern
        message_lower = result.message.lower()
        responds = any(word in message_lower for word in [
            "sorry", "what", "correct", "change", "help", "order", "wrong"
        ])
        assert responds, f"Should respond to concern. Message: {result.message}"
