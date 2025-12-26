"""
Integration tests for slot orchestrator comparison logging.

These tests verify that the slot orchestrator is correctly tracking
order state and capturing phase transitions.
"""

import pytest
import logging
from unittest.mock import patch, MagicMock

from sandwich_bot.tasks.state_machine import OrderStateMachine, OrderPhase
from sandwich_bot.tasks.models import OrderTask, BagelItemTask, CoffeeItemTask, TaskStatus


class TestSlotComparisonLogging:
    """Test that slot comparison logging works correctly."""

    @pytest.fixture
    def state_machine(self):
        """Create a state machine with mock menu data."""
        menu_data = {
            "bagel_types": ["plain", "everything", "sesame"],
            "cheese_types": ["plain", "scallion", "veggie"],
            "menu_items": [],
        }
        return OrderStateMachine(menu_data=menu_data)

    @pytest.fixture
    def capture_slot_logs(self):
        """Capture slot comparison logs."""
        logs = []

        class LogCapture(logging.Handler):
            def emit(self, record):
                logs.append(record)

        handler = LogCapture()
        handler.setLevel(logging.DEBUG)

        logger = logging.getLogger("sandwich_bot.tasks.state_machine.slot_comparison")
        original_level = logger.level
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)

        yield logs

        logger.removeHandler(handler)
        logger.setLevel(original_level)

    def test_slot_logging_on_greeting(self, state_machine, capture_slot_logs):
        """Verify slot comparison runs on greeting."""
        order = OrderTask()

        # Process a greeting
        with patch("sandwich_bot.tasks.state_machine.parse_open_input") as mock_parse:
            mock_parse.return_value = MagicMock(
                is_greeting=True,
                unclear=False,
                new_bagel=False,
                new_bagel_quantity=0,
                new_coffee=False,
                new_coffee_quantity=0,
                new_menu_item=None,
                wants_checkout=False,
            )
            result = state_machine.process("hi", order)

        # Should have logged slot comparison
        assert len(capture_slot_logs) > 0
        log_messages = [r.getMessage() for r in capture_slot_logs]
        assert any("SLOT" in msg for msg in log_messages)

    def test_slot_logging_on_order_flow(self, state_machine, capture_slot_logs):
        """Verify slot comparison logs throughout an order flow."""
        from sandwich_bot.tasks.slot_orchestrator import SlotOrchestrator

        order = OrderTask()

        # Simulate adding a complete item
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)

        # Directly test the log comparison method (order now has phase)
        order.phase = OrderPhase.CHECKOUT_DELIVERY.value
        state_machine._log_slot_comparison(order)

        # Check logs
        log_messages = [r.getMessage() for r in capture_slot_logs]
        # Should have slot progress logged
        assert any("SLOT" in msg for msg in log_messages)


class TestSlotPhaseAlignment:
    """Test that OrderTask phases align with SlotOrchestrator phases."""

    def test_greeting_phase_aligns(self):
        """Greeting phase should map to taking_items."""
        from sandwich_bot.tasks.slot_orchestrator import SlotOrchestrator

        order = OrderTask()
        orch = SlotOrchestrator(order)

        # With no items, orchestrator says we need items (taking_items)
        phase = orch.get_current_phase()
        assert phase == "taking_items"

    def test_checkout_delivery_aligns(self):
        """Checkout delivery phase should align with orchestrator."""
        from sandwich_bot.tasks.slot_orchestrator import SlotOrchestrator

        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)

        orch = SlotOrchestrator(order)
        phase = orch.get_current_phase()
        assert phase == "checkout_delivery"

    def test_checkout_name_aligns(self):
        """Checkout name phase should align with orchestrator."""
        from sandwich_bot.tasks.slot_orchestrator import SlotOrchestrator

        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)
        order.delivery_method.order_type = "pickup"

        orch = SlotOrchestrator(order)
        phase = orch.get_current_phase()
        assert phase == "checkout_name"

    def test_checkout_confirm_aligns(self):
        """Checkout confirm phase should align with orchestrator."""
        from sandwich_bot.tasks.slot_orchestrator import SlotOrchestrator

        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)
        order.delivery_method.order_type = "pickup"
        order.customer_info.name = "John"

        orch = SlotOrchestrator(order)
        phase = orch.get_current_phase()
        assert phase == "checkout_confirm"

    def test_complete_order_aligns(self):
        """Complete order should have complete phase."""
        from sandwich_bot.tasks.slot_orchestrator import SlotOrchestrator

        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)
        order.delivery_method.order_type = "pickup"
        order.customer_info.name = "John"
        order.checkout.order_reviewed = True  # User confirmed summary
        order.payment.method = "in_store"

        orch = SlotOrchestrator(order)
        phase = orch.get_current_phase()
        assert phase == "complete"


class TestEndToEndFlowWithSlots:
    """Test complete order flows with slot tracking."""

    @pytest.fixture
    def state_machine(self):
        menu_data = {
            "bagel_types": ["plain", "everything"],
            "cheese_types": ["plain"],
            "menu_items": [],
        }
        return OrderStateMachine(menu_data=menu_data)

    def test_simple_pickup_flow_slots(self, state_machine):
        """Verify slots are correctly filled through a simple pickup flow."""
        from sandwich_bot.tasks.slot_orchestrator import SlotOrchestrator

        order = OrderTask()

        # Simulate a completed flow
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)
        order.delivery_method.order_type = "pickup"
        order.customer_info.name = "Alice"
        order.checkout.order_reviewed = True  # User confirmed summary
        order.payment.method = "in_store"

        # Verify orchestrator sees this as complete
        orch = SlotOrchestrator(order)
        assert orch.is_complete()

        progress = orch.get_progress()
        assert progress["items"] is True
        assert progress["delivery_method"] is True
        assert progress["customer_name"] is True
        assert progress["order_confirm"] is True
        assert progress["payment_method"] is True

    def test_delivery_flow_includes_address_slot(self, state_machine):
        """Verify delivery flow requires address slot."""
        from sandwich_bot.tasks.slot_orchestrator import SlotOrchestrator, SlotCategory

        order = OrderTask()

        # Add complete item
        bagel = BagelItemTask(bagel_type="everything", toasted=False)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)

        # Set delivery
        order.delivery_method.order_type = "delivery"

        # Without address, should need address slot
        orch = SlotOrchestrator(order)
        next_slot = orch.get_next_slot()
        assert next_slot is not None
        assert next_slot.category == SlotCategory.DELIVERY_ADDRESS

        # Add address
        order.delivery_method.address.street = "123 Main St"

        # Now should need name
        orch = SlotOrchestrator(order)
        next_slot = orch.get_next_slot()
        assert next_slot.category == SlotCategory.CUSTOMER_NAME
