"""
Resiliency Test Batch 3: Natural Language Variation

Tests the system's ability to handle informal phrasings, typos, and
various ordering syntax variations.
"""

from sandwich_bot.tasks.state_machine import OrderStateMachine, OrderPhase
from sandwich_bot.tasks.models import OrderTask
from tests.test_helpers import BagelItemTask, CoffeeItemTask


class TestNaturalLanguageVariation:
    """Batch 3: Natural Language Variation."""

    def test_gimme_a_bagel(self):
        """
        Test: User uses informal "gimme" phrasing.

        Scenario:
        - User says: "gimme a plain bagel"
        - Expected: System adds a plain bagel
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("gimme a plain bagel", order)

        # Should have a response
        assert result.message is not None

        # Should have added a bagel
        bagels = [i for i in result.order.items.items if getattr(i, 'is_bagel', False)]
        assert len(bagels) >= 1, f"Should have added a bagel. Message: {result.message}"

        # Should be a plain bagel
        bagel = bagels[0]
        assert bagel.bagel_type == "plain", f"Should be plain bagel, got: {bagel.bagel_type}"

    def test_lemme_get_a_coffee(self):
        """
        Test: User uses informal "lemme get" phrasing.

        Scenario:
        - User says: "lemme get a large iced latte"
        - Expected: System asks for clarification between Latte and Seasonal Matcha Latte
        - User clarifies: "regular latte"
        - Expected: System adds a large iced latte
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("lemme get a large iced latte", order)

        # Should have a response
        assert result.message is not None

        # Check if clarification is needed (multiple latte types exist)
        coffees = [i for i in result.order.items.items if getattr(i, 'is_sized_beverage', False)]
        if len(coffees) == 0:
            # System correctly asks for clarification between latte types
            assert "latte" in result.message.lower() or "matcha" in result.message.lower(), \
                f"Should ask about latte type. Message: {result.message}"

            # User clarifies they want regular latte
            result = sm.process("regular latte", result.order)
            coffees = [i for i in result.order.items.items if getattr(i, 'is_sized_beverage', False)]

        assert len(coffees) >= 1, f"Should have added a coffee. Message: {result.message}"

        coffee = coffees[0]
        assert coffee.drink_type.lower() == "latte", f"Should be latte, got: {coffee.drink_type}"
        assert coffee.size == "large", f"Should be large, got: {coffee.size}"
        assert coffee.iced is True, f"Should be iced, got: {coffee.iced}"

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

    def test_typo_tosted_bagel(self):
        """
        Test: User makes typo "tosted" instead of "toasted".

        Scenario:
        - User says: "plain bagel tosted"
        - Expected: System understands this as toasted
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("plain bagel tosted", order)

        # Should have a response
        assert result.message is not None

        # Should have added a bagel
        bagels = [i for i in result.order.items.items if getattr(i, 'is_bagel', False)]
        assert len(bagels) >= 1, f"Should have added a bagel. Message: {result.message}"

        bagel = bagels[0]
        # Should understand tosted as toasted
        assert bagel.toasted is True, f"Should be toasted, got: {bagel.toasted}"

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
        coffees = [i for i in result.order.items.items if getattr(i, 'is_sized_beverage', False)]

        if coffees:
            coffee = coffees[0]
            # Should be espresso
            assert coffee.drink_type == "espresso", \
                f"Should be espresso, got: {coffee.drink_type}"
        else:
            # Or should be asking about espresso
            assert "espresso" in result.message.lower() or "expresso" in result.message.lower(), \
                f"Should reference espresso. Message: {result.message}"
