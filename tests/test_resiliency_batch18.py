"""
Resiliency Test Batch 18: Help & Confusion

Tests the system's ability to handle help requests and confusion.
"""

import pytest
from sandwich_bot.tasks.state_machine import OrderStateMachine, OrderPhase
from sandwich_bot.tasks.models import OrderTask, BagelItemTask


class TestHelpConfusion:
    """Batch 18: Help & Confusion."""

    def test_help_request(self):
        """
        Test: User says "help".

        Scenario:
        - User says: "help"
        - Expected: System provides helpful guidance
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("help", order)

        assert result.message is not None
        # Should provide helpful response
        message_lower = result.message.lower()
        helps = any(word in message_lower for word in [
            "help", "order", "bagel", "coffee", "menu", "can", "would", "like"
        ])
        assert helps, f"Should provide help. Message: {result.message}"

    def test_im_confused(self):
        """
        Test: User says "I'm confused".

        Scenario:
        - User says: "I'm confused"
        - Expected: System offers assistance
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("I'm confused", order)

        assert result.message is not None
        # Should offer help
        message_lower = result.message.lower()
        helps = any(word in message_lower for word in [
            "help", "sorry", "let me", "can", "would", "order", "what"
        ])
        assert helps, f"Should offer help. Message: {result.message}"

    def test_what_can_you_do(self):
        """
        Test: User asks "what can you do?".

        Scenario:
        - User says: "what can you do?"
        - Expected: System explains its capabilities
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("what can you do?", order)

        assert result.message is not None
        # Should explain capabilities
        message_lower = result.message.lower()
        explains = any(word in message_lower for word in [
            "order", "bagel", "coffee", "help", "can", "menu", "food", "drink"
        ])
        assert explains, f"Should explain capabilities. Message: {result.message}"
