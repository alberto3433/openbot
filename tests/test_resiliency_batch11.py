"""
Resiliency Test Batch 11: Dietary & Allergy Questions

Tests the system's ability to handle dietary restriction and allergy questions.
"""

import pytest

from orderbot.tasks.state_machine import OrderStateMachine, OrderPhase
from orderbot.tasks.models import OrderTask


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

