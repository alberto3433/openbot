"""
Resiliency Test Batch 8: Menu Inquiries

Tests the system's ability to handle questions about the menu,
prices, and store information.
"""

import pytest
from sandwich_bot.tasks.state_machine import OrderStateMachine, OrderPhase
from sandwich_bot.tasks.models import OrderTask


class TestMenuInquiries:
    """Batch 8: Menu Inquiries."""

    def test_what_bagels_do_you_have(self):
        """
        Test: User asks about available bagels.

        Scenario:
        - User says: "what bagels do you have?"
        - Expected: System lists available bagel types
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("what bagels do you have?", order)

        # Should have a response
        assert result.message is not None

        # Should mention bagels or list options
        message_lower = result.message.lower()
        mentions_bagels = any(word in message_lower for word in [
            "plain", "everything", "sesame", "poppy", "bagel", "have", "offer"
        ])

        assert mentions_bagels, \
            f"Should list bagel options. Message: {result.message}"

    def test_how_much_is_a_latte(self):
        """
        Test: User asks about latte price.

        Scenario:
        - User says: "how much is a latte?"
        - Expected: System responds about pricing (may not have info)
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("how much is a latte?", order)

        # Should have a response
        assert result.message is not None

        # Should acknowledge the price question (even if no info available)
        message_lower = result.message.lower()
        responds = any(word in message_lower for word in [
            "$", "price", "cost", "latte", "small", "medium", "large",
            "pricing", "sorry", "don't have", "information"
        ])

        assert responds, \
            f"Should respond to price question. Message: {result.message}"

    def test_whats_on_the_classic(self):
        """
        Test: User asks what's on a menu item.

        Scenario:
        - User says: "what's on the classic?"
        - Expected: System describes The Classic
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("what's on the classic?", order)

        # Should have a response
        assert result.message is not None

        # Should describe the item
        message_lower = result.message.lower()
        describes = any(word in message_lower for word in [
            "classic", "bacon", "egg", "cheese", "cream cheese", "comes with"
        ])

        assert describes, \
            f"Should describe The Classic. Message: {result.message}"

    def test_what_drinks_do_you_have(self):
        """
        Test: User asks about available drinks.

        Scenario:
        - User says: "what drinks do you have?"
        - Expected: System lists drink options
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("what drinks do you have?", order)

        # Should have a response
        assert result.message is not None

        # Should list drinks or categories
        message_lower = result.message.lower()
        mentions_drinks = any(word in message_lower for word in [
            "coffee", "latte", "espresso", "tea", "juice", "soda",
            "drink", "beverage", "have", "offer"
        ])

        assert mentions_drinks, \
            f"Should list drink options. Message: {result.message}"

    def test_what_sandwiches_do_you_have(self):
        """
        Test: User asks about sandwiches.

        Scenario:
        - User says: "what sandwiches do you have?"
        - Expected: System lists sandwich options
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("what sandwiches do you have?", order)

        # Should have a response
        assert result.message is not None

        # Should mention sandwiches
        message_lower = result.message.lower()
        mentions_sandwiches = any(word in message_lower for word in [
            "sandwich", "blt", "tuna", "egg", "classic", "have", "offer"
        ])

        assert mentions_sandwiches, \
            f"Should list sandwich options. Message: {result.message}"
