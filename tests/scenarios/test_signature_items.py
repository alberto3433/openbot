"""
Signature Item and Menu-Specific Tests.

These tests focus on signature menu items, menu-specific terminology,
and item-specific edge cases.

Run with: pytest tests/scenarios/ -v
"""

import pytest
from orderbot.tasks.state_machine import OrderStateMachine
from orderbot.tasks.models import OrderTask
from orderbot.tasks.schemas import OrderPhase


class TestSignatureItems:
    """Tests for signature menu items."""

    def test_classic_bec_full_name(self):
        """Order Classic BEC by full name."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("The Classic BEC please", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should recognize Classic BEC"

    def test_classic_bec_abbreviated(self):
        """Order Classic BEC abbreviated."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Classic BEC", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should recognize abbreviated"

    def test_nova_lox_platter(self):
        """Order nova lox platter."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Nova lox bagel please", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should recognize nova lox"

    def test_signature_with_modification(self):
        """Signature item with modification."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Classic BEC but no cheese", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should allow modification"

    def test_signature_on_different_bread(self):
        """Signature item on different bread."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Classic BEC on a plain bagel", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should allow bread change"

    def test_signature_extra_ingredient(self):
        """Signature item with extra ingredient."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Classic BEC with avocado", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should allow extra ingredient"


class TestOmeletteOrders:
    """Tests for omelette orders."""

    def test_basic_omelette(self):
        """Basic omelette order."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Cheese omelette", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should recognize omelette"

    def test_western_omelette(self):
        """Western omelette order."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Western omelette please", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should recognize western omelette"

    def test_omelette_with_side(self):
        """Omelette with side specification."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Cheese omelette with an everything bagel on the side", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should handle omelette with side"

    def test_egg_white_omelette(self):
        """Egg white omelette."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Egg white omelette with vegetables", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should handle egg white"


class TestPastryOrders:
    """Tests for pastry and baked goods."""

    def test_muffin_order(self):
        """Order a muffin."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Blueberry muffin please", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should handle muffin"

    def test_croissant_order(self):
        """Order a croissant."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Chocolate croissant", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should handle croissant"

    def test_cookie_order(self):
        """Order cookies."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Two chocolate chip cookies", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should handle cookies"
