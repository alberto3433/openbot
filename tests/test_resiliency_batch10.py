"""
Resiliency Test Batch 10: Gratitude & Social Responses

Tests the system's ability to handle thank you, sorry, and social responses.
"""

import pytest
from sandwich_bot.tasks.state_machine import OrderStateMachine, OrderPhase
from sandwich_bot.tasks.models import OrderTask, BagelItemTask


class TestGratitudeSocialResponses:
    """Batch 10: Gratitude & Social Responses."""

    def test_thank_you_response(self):
        """
        Test: User says "thank you" after ordering.

        Scenario:
        - User has items in order
        - User says: "thank you"
        - Expected: Polite acknowledgment, doesn't add items
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("thank you", order)

        assert result.message is not None
        # Should acknowledge politely
        message_lower = result.message.lower()
        is_polite = any(word in message_lower for word in [
            "welcome", "thank", "pleasure", "glad", "help", "else", "anything"
        ])
        assert is_polite, f"Should respond politely. Message: {result.message}"

    def test_thanks_response(self):
        """
        Test: User says "thanks" shorthand.

        Scenario:
        - User says: "thanks"
        - Expected: Polite response
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="everything", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("thanks", order)

        assert result.message is not None
        # Should not error or misinterpret
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]
        assert len(bagels) == 1, "Should not add extra items"

    def test_sorry_response(self):
        """
        Test: User says "sorry" (maybe after confusion).

        Scenario:
        - User says: "sorry, I meant plain bagel"
        - Expected: System handles gracefully, possibly interprets the order
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("sorry, I meant plain bagel", order)

        assert result.message is not None
        # Should either add the bagel or ask for clarification
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]
        has_bagel = len(bagels) >= 1
        mentions_bagel = "bagel" in result.message.lower()

        assert has_bagel or mentions_bagel, \
            f"Should handle the bagel order. Message: {result.message}"
