"""
Resiliency Test Batch 11: Dietary & Allergy Questions

Tests the system's ability to handle dietary restriction and allergy questions.
"""

from sandwich_bot.tasks.state_machine import OrderStateMachine, OrderPhase
from sandwich_bot.tasks.models import OrderTask


class TestDietaryAllergyQuestions:
    """Batch 11: Dietary & Allergy Questions."""

    def test_gluten_free_options(self):
        """
        Test: User asks about gluten-free options.

        Scenario:
        - User says: "do you have gluten-free options?"
        - Expected: System responds about gluten-free availability
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("do you have gluten-free options?", order)

        assert result.message is not None
        # Should acknowledge the question
        message_lower = result.message.lower()
        responds = any(word in message_lower for word in [
            "gluten", "free", "option", "bagel", "have", "yes", "no", "sorry"
        ])
        assert responds, f"Should respond about gluten-free. Message: {result.message}"

    def test_dairy_free_cream_cheese(self):
        """
        Test: User asks about dairy-free cream cheese.

        Scenario:
        - User says: "is the cream cheese dairy-free?"
        - Expected: System responds about dairy content
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("is the cream cheese dairy-free?", order)

        assert result.message is not None
        # Should respond about cream cheese
        message_lower = result.message.lower()
        responds = any(word in message_lower for word in [
            "cream cheese", "dairy", "no", "yes", "sorry", "contain"
        ])
        assert responds, f"Should respond about dairy. Message: {result.message}"
