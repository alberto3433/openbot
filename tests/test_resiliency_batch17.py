"""
Resiliency Test Batch 17: Availability Questions

Tests the system's ability to handle questions about item availability.
"""

from sandwich_bot.tasks.state_machine import OrderStateMachine, OrderPhase
from sandwich_bot.tasks.models import OrderTask


class TestAvailabilityQuestions:
    """Batch 17: Availability Questions."""

    def test_is_salmon_available(self):
        """
        Test: User asks about specific item availability.

        Scenario:
        - User says: "is the salmon available?"
        - Expected: System responds about salmon availability
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("is the salmon available?", order)

        assert result.message is not None
        # Should respond about availability
        message_lower = result.message.lower()
        responds = any(word in message_lower for word in [
            "salmon", "lox", "nova", "yes", "no", "available", "have", "fish"
        ])
        assert responds, f"Should respond about salmon. Message: {result.message}"

    def test_are_you_out_of_everything_bagels(self):
        """
        Test: User asks if they're out of something.

        Scenario:
        - User says: "are you out of everything bagels?"
        - Expected: System responds about availability
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("are you out of everything bagels?", order)

        assert result.message is not None
        # Should respond about bagel availability
        message_lower = result.message.lower()
        responds = any(word in message_lower for word in [
            "everything", "bagel", "yes", "no", "have", "available", "out"
        ])
        assert responds, f"Should respond about availability. Message: {result.message}"

    def test_any_specials_today(self):
        """
        Test: User asks about specials.

        Scenario:
        - User says: "do you have any specials today?"
        - Expected: System responds about specials
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("do you have any specials today?", order)

        assert result.message is not None
        # Should respond about specials or menu
        message_lower = result.message.lower()
        responds = any(word in message_lower for word in [
            "special", "menu", "recommend", "popular", "today", "have", "sorry"
        ])
        assert responds, f"Should respond about specials. Message: {result.message}"
