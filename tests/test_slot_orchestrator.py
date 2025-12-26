"""
Unit tests for the SlotOrchestrator.

These tests verify the slot-filling logic in isolation,
without involving the full state machine.
"""

import pytest
from sandwich_bot.tasks.models import (
    OrderTask,
    BagelItemTask,
    CoffeeItemTask,
    SpeedMenuBagelItemTask,
    MenuItemTask,
    TaskStatus,
)
from sandwich_bot.tasks.slot_orchestrator import (
    SlotOrchestrator,
    SlotCategory,
    SlotDefinition,
    ItemSlotOrchestrator,
    get_item_slots,
    sync_db_order_to_task,
)


class TestSlotOrchestratorBasics:
    """Test basic slot orchestration flow."""

    def test_empty_order_needs_items(self):
        """First slot should be items when order is empty."""
        order = OrderTask()
        orch = SlotOrchestrator(order)
        slot = orch.get_next_slot()

        assert slot is not None
        assert slot.category == SlotCategory.ITEMS

    def test_with_incomplete_item_still_needs_items(self):
        """Items slot not filled until items are complete."""
        order = OrderTask()
        # Add bagel without toasted preference
        bagel = BagelItemTask(bagel_type="plain", toasted=None)
        bagel.status = TaskStatus.IN_PROGRESS
        order.items.add_item(bagel)

        orch = SlotOrchestrator(order)
        slot = orch.get_next_slot()

        assert slot is not None
        assert slot.category == SlotCategory.ITEMS

    def test_with_complete_item_needs_delivery(self):
        """After complete items, should ask delivery method."""
        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)

        orch = SlotOrchestrator(order)
        slot = orch.get_next_slot()

        assert slot is not None
        assert slot.category == SlotCategory.DELIVERY_METHOD

    def test_pickup_skips_address(self):
        """Pickup orders should skip address slot."""
        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)
        order.delivery_method.order_type = "pickup"

        orch = SlotOrchestrator(order)
        slot = orch.get_next_slot()

        assert slot is not None
        assert slot.category == SlotCategory.CUSTOMER_NAME  # Skipped address

    def test_delivery_needs_address(self):
        """Delivery orders should ask for address."""
        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)
        order.delivery_method.order_type = "delivery"

        orch = SlotOrchestrator(order)
        slot = orch.get_next_slot()

        assert slot is not None
        assert slot.category == SlotCategory.DELIVERY_ADDRESS

    def test_after_address_needs_name(self):
        """After address, should ask for name."""
        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)
        order.delivery_method.order_type = "delivery"
        order.delivery_method.address.street = "123 Main St"

        orch = SlotOrchestrator(order)
        slot = orch.get_next_slot()

        assert slot is not None
        assert slot.category == SlotCategory.CUSTOMER_NAME

    def test_after_name_needs_confirm(self):
        """After name, should ask for confirmation."""
        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)
        order.delivery_method.order_type = "pickup"
        order.customer_info.name = "John"

        orch = SlotOrchestrator(order)
        slot = orch.get_next_slot()

        assert slot is not None
        assert slot.category == SlotCategory.ORDER_CONFIRM

    def test_after_confirm_needs_payment(self):
        """After order reviewed (user said 'yes'), should ask for payment method."""
        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)
        order.delivery_method.order_type = "pickup"
        order.customer_info.name = "John"
        order.checkout.order_reviewed = True  # User confirmed summary

        orch = SlotOrchestrator(order)
        slot = orch.get_next_slot()

        assert slot is not None
        assert slot.category == SlotCategory.PAYMENT_METHOD

    def test_in_store_payment_completes_order(self):
        """In-store payment should complete the order (no notification needed)."""
        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)
        order.delivery_method.order_type = "pickup"
        order.customer_info.name = "John"
        order.checkout.order_reviewed = True  # User confirmed summary
        order.payment.method = "in_store"

        orch = SlotOrchestrator(order)
        slot = orch.get_next_slot()

        assert slot is None
        assert orch.is_complete()

    def test_card_link_needs_notification(self):
        """Card link payment should require notification method."""
        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)
        order.delivery_method.order_type = "pickup"
        order.customer_info.name = "John"
        order.checkout.order_reviewed = True  # User confirmed summary
        order.payment.method = "card_link"

        orch = SlotOrchestrator(order)
        slot = orch.get_next_slot()

        assert slot is not None
        assert slot.category == SlotCategory.NOTIFICATION

    def test_notification_with_phone_completes(self):
        """Providing phone for notification completes order."""
        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)
        order.delivery_method.order_type = "pickup"
        order.customer_info.name = "John"
        order.customer_info.phone = "555-1234"
        order.checkout.order_reviewed = True  # User confirmed summary
        order.payment.method = "card_link"

        orch = SlotOrchestrator(order)
        assert orch.is_complete()

    def test_notification_with_email_completes(self):
        """Providing email for notification completes order."""
        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)
        order.delivery_method.order_type = "pickup"
        order.customer_info.name = "John"
        order.customer_info.email = "john@example.com"
        order.checkout.order_reviewed = True  # User confirmed summary
        order.payment.method = "card_link"

        orch = SlotOrchestrator(order)
        assert orch.is_complete()


class TestSlotOrchestratorPhaseDerivation:
    """Test that phases are correctly derived from slot state."""

    def test_empty_order_phase_is_taking_items(self):
        order = OrderTask()
        orch = SlotOrchestrator(order)
        assert orch.get_current_phase() == "taking_items"

    def test_with_items_phase_is_checkout_delivery(self):
        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)

        orch = SlotOrchestrator(order)
        assert orch.get_current_phase() == "checkout_delivery"

    def test_delivery_phase_is_checkout_address(self):
        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)
        order.delivery_method.order_type = "delivery"

        orch = SlotOrchestrator(order)
        assert orch.get_current_phase() == "checkout_address"

    def test_pickup_phase_is_checkout_name(self):
        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)
        order.delivery_method.order_type = "pickup"

        orch = SlotOrchestrator(order)
        assert orch.get_current_phase() == "checkout_name"

    def test_complete_order_phase_is_complete(self):
        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)
        order.delivery_method.order_type = "pickup"
        order.customer_info.name = "John"
        order.checkout.order_reviewed = True  # User confirmed summary
        order.payment.method = "in_store"

        orch = SlotOrchestrator(order)
        assert orch.get_current_phase() == "complete"

    def test_configuring_item_phase(self):
        """When an item is in_progress, phase should be configuring_item."""
        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=None)
        bagel.status = TaskStatus.IN_PROGRESS
        order.items.add_item(bagel)

        orch = SlotOrchestrator(order)
        assert orch.get_current_phase() == "configuring_item"


class TestSlotOrchestratorProgress:
    """Test progress tracking."""

    def test_empty_order_progress(self):
        order = OrderTask()
        orch = SlotOrchestrator(order)
        progress = orch.get_progress()

        assert progress["items"] is False
        # delivery_method not in progress because its condition requires items
        assert "delivery_method" not in progress

    def test_partial_progress(self):
        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)
        order.delivery_method.order_type = "pickup"
        order.customer_info.name = "John"

        orch = SlotOrchestrator(order)
        progress = orch.get_progress()

        assert progress["items"] is True
        assert progress["delivery_method"] is True
        assert progress["customer_name"] is True
        assert progress["order_confirm"] is False


class TestItemSlotOrchestrator:
    """Test item-level slot orchestration."""

    def test_bagel_needs_type_first(self):
        bagel = BagelItemTask()
        orch = ItemSlotOrchestrator(bagel)
        slot = orch.get_next_slot()

        assert slot is not None
        assert slot.field_name == "bagel_type"

    def test_bagel_needs_toasted_after_type(self):
        bagel = BagelItemTask(bagel_type="plain")
        orch = ItemSlotOrchestrator(bagel)
        slot = orch.get_next_slot()

        assert slot is not None
        assert slot.field_name == "toasted"

    def test_bagel_complete_with_type_and_toasted(self):
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        orch = ItemSlotOrchestrator(bagel)

        # No more required slots
        assert orch.is_complete()

    def test_coffee_needs_size_first(self):
        coffee = CoffeeItemTask(drink_type="latte")
        orch = ItemSlotOrchestrator(coffee)
        slot = orch.get_next_slot()

        assert slot is not None
        assert slot.field_name == "size"

    def test_coffee_needs_iced_after_size(self):
        coffee = CoffeeItemTask(drink_type="latte", size="medium")
        orch = ItemSlotOrchestrator(coffee)
        slot = orch.get_next_slot()

        assert slot is not None
        assert slot.field_name == "iced"

    def test_coffee_complete_with_size_and_iced(self):
        coffee = CoffeeItemTask(drink_type="latte", size="medium", iced=True)
        orch = ItemSlotOrchestrator(coffee)

        assert orch.is_complete()

    def test_speed_menu_bagel_only_needs_toasted(self):
        item = SpeedMenuBagelItemTask(menu_item_name="The Classic")
        orch = ItemSlotOrchestrator(item)
        slot = orch.get_next_slot()

        assert slot is not None
        assert slot.field_name == "toasted"

    def test_speed_menu_bagel_complete_with_toasted(self):
        item = SpeedMenuBagelItemTask(menu_item_name="The Classic", toasted=True)
        orch = ItemSlotOrchestrator(item)

        assert orch.is_complete()

    def test_menu_item_needs_side_choice_when_required(self):
        item = MenuItemTask(
            menu_item_name="Chipotle Omelette",
            requires_side_choice=True,
        )
        orch = ItemSlotOrchestrator(item)
        slot = orch.get_next_slot()

        assert slot is not None
        assert slot.field_name == "side_choice"

    def test_menu_item_needs_bagel_choice_after_bagel_side(self):
        item = MenuItemTask(
            menu_item_name="Chipotle Omelette",
            requires_side_choice=True,
            side_choice="bagel",
        )
        orch = ItemSlotOrchestrator(item)
        slot = orch.get_next_slot()

        assert slot is not None
        assert slot.field_name == "bagel_choice"

    def test_menu_item_complete_with_fruit_salad_side(self):
        item = MenuItemTask(
            menu_item_name="Chipotle Omelette",
            requires_side_choice=True,
            side_choice="fruit_salad",
        )
        orch = ItemSlotOrchestrator(item)

        assert orch.is_complete()


class TestFillSlot:
    """Test slot filling functionality."""

    def test_fill_simple_slot(self):
        order = OrderTask()
        orch = SlotOrchestrator(order)

        slot = SlotDefinition(
            category=SlotCategory.CUSTOMER_NAME,
            field_path="customer_info.name",
            question="Name?",
        )
        orch.fill_slot(slot, "John")

        assert order.customer_info.name == "John"

    def test_fill_nested_slot(self):
        order = OrderTask()
        orch = SlotOrchestrator(order)

        slot = SlotDefinition(
            category=SlotCategory.DELIVERY_ADDRESS,
            field_path="delivery_method.address.street",
            question="Address?",
        )
        orch.fill_slot(slot, "123 Main St")

        assert order.delivery_method.address.street == "123 Main St"

    def test_fill_item_slot(self):
        bagel = BagelItemTask()
        orch = ItemSlotOrchestrator(bagel)

        slot = orch.get_next_slot()  # bagel_type
        orch.fill_slot(slot, "everything")

        assert bagel.bagel_type == "everything"


class TestSyncDbOrderToTask:
    """Test syncing from DB Order to OrderTask."""

    def test_sync_order_type(self):
        class MockDbOrder:
            order_type = "pickup"
            customer_name = None
            customer_phone = None
            customer_email = None
            delivery_address = None
            status = "pending"

        order_task = OrderTask()
        sync_db_order_to_task(MockDbOrder(), order_task)

        assert order_task.delivery_method.order_type == "pickup"

    def test_sync_customer_info(self):
        class MockDbOrder:
            order_type = None
            customer_name = "Jane Doe"
            customer_phone = "555-1234"
            customer_email = "jane@example.com"
            delivery_address = None
            status = "pending"

        order_task = OrderTask()
        sync_db_order_to_task(MockDbOrder(), order_task)

        assert order_task.customer_info.name == "Jane Doe"
        assert order_task.customer_info.phone == "555-1234"
        assert order_task.customer_info.email == "jane@example.com"

    def test_sync_delivery_address(self):
        class MockDbOrder:
            order_type = "delivery"
            customer_name = None
            customer_phone = None
            customer_email = None
            delivery_address = "456 Oak Ave"
            status = "pending"

        order_task = OrderTask()
        sync_db_order_to_task(MockDbOrder(), order_task)

        assert order_task.delivery_method.address.street == "456 Oak Ave"

    def test_sync_confirmed_status(self):
        class MockDbOrder:
            order_type = None
            customer_name = None
            customer_phone = None
            customer_email = None
            delivery_address = None
            status = "confirmed"

        order_task = OrderTask()
        sync_db_order_to_task(MockDbOrder(), order_task)

        assert order_task.checkout.confirmed is True

    def test_sync_none_order(self):
        """Syncing None should not raise."""
        order_task = OrderTask()
        sync_db_order_to_task(None, order_task)
        # Should not raise, task unchanged
        assert order_task.delivery_method.order_type is None


class TestMultipleItems:
    """Test orchestration with multiple items."""

    def test_multiple_items_all_must_complete(self):
        order = OrderTask()

        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)

        coffee = CoffeeItemTask(drink_type="latte", size="medium", iced=None)
        coffee.status = TaskStatus.IN_PROGRESS
        order.items.add_item(coffee)

        orch = SlotOrchestrator(order)
        slot = orch.get_next_slot()

        # Items slot still not filled because coffee is incomplete
        assert slot is not None
        assert slot.category == SlotCategory.ITEMS

    def test_multiple_items_all_complete_moves_to_delivery(self):
        order = OrderTask()

        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)

        coffee = CoffeeItemTask(drink_type="latte", size="medium", iced=True)
        coffee.status = TaskStatus.COMPLETE
        order.items.add_item(coffee)

        orch = SlotOrchestrator(order)
        slot = orch.get_next_slot()

        assert slot is not None
        assert slot.category == SlotCategory.DELIVERY_METHOD
