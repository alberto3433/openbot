"""
Resiliency Test Batch 3: Natural Language Variation

Tests the system's ability to handle informal phrasings, typos, and
various ordering syntax variations.
"""

from orderbot.tasks.state_machine import OrderStateMachine, OrderPhase
from orderbot.tasks.models import OrderTask
from tests.helpers import BagelItemTask, CoffeeItemTask


class TestNaturalLanguageVariation:
    """Batch 3: Natural Language Variation."""

    def test_throw_in_a_muffin(self):
        """
        Test: User uses informal "throw in" phrasing.

        Scenario:
        - User says: "throw in a blueberry muffin"
        - Expected: System adds a blueberry muffin
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("throw in a blueberry muffin", order)

        # Should have a response
        assert result.message is not None

        # Check the message mentions muffin or asks which one
        message_lower = result.message.lower()
        items = result.order.items.get_active_items()

        # Should either add the muffin or ask for clarification
        has_item = len(items) > 0
        mentions_muffin = "muffin" in message_lower or "blueberry" in message_lower

        assert has_item or mentions_muffin, \
            f"Should add muffin or reference it. Message: {result.message}"

    def test_typo_expresso(self):
        """
        Test: User makes common typo "expresso" instead of "espresso".

        Scenario:
        - User says: "expresso please"
        - Expected: System understands this as espresso
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("expresso please", order)

        # Should have a response
        assert result.message is not None

        # Should have added espresso (as coffee)
        coffees = [i for i in result.order.items.items if i.has_attribute('size')]

        if coffees:
            coffee = coffees[0]
            # Should be espresso
            assert coffee.menu_item_name.lower() == "espresso", \
                f"Should be espresso, got: {coffee.menu_item_name}"
        else:
            # Or should be asking about espresso
            assert "espresso" in result.message.lower() or "expresso" in result.message.lower(), \
                f"Should reference espresso. Message: {result.message}"
