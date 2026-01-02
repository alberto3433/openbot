"""
Unit tests for the hierarchical task system models.

Run with: pytest tests/test_tasks_models.py -v
"""

import pytest
from sandwich_bot.tasks.models import (
    TaskStatus,
    FieldConfig,
    BaseTask,
    BagelItemTask,
    CoffeeItemTask,
    DeliveryMethodTask,
    CustomerInfoTask,
    CheckoutTask,
    PaymentTask,
    ItemsTask,
    OrderTask,
)
from sandwich_bot.tasks.field_config import (
    MenuFieldConfig,
    DEFAULT_BAGEL_FIELDS,
    DEFAULT_COFFEE_FIELDS,
    get_field_config,
    get_default_value,
    should_ask_field,
)


# =============================================================================
# TaskStatus Tests
# =============================================================================

class TestTaskStatus:
    """Tests for TaskStatus enum."""

    def test_status_values(self):
        """Test all status values exist."""
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.IN_PROGRESS == "in_progress"
        assert TaskStatus.COMPLETE == "complete"
        assert TaskStatus.SKIPPED == "skipped"


# =============================================================================
# FieldConfig Tests
# =============================================================================

class TestFieldConfig:
    """Tests for FieldConfig model."""

    def test_required_field_needs_asking(self):
        """Required field with no default needs asking."""
        config = FieldConfig(name="test", required=True, default=None, ask_if_empty=True)
        assert config.needs_asking(None) is True
        assert config.needs_asking("value") is False

    def test_field_with_default_doesnt_need_asking(self):
        """Field with default value doesn't need asking."""
        config = FieldConfig(name="test", required=True, default="default_val", ask_if_empty=True)
        assert config.needs_asking(None) is False

    def test_optional_field_with_ask_if_empty(self):
        """Optional field with ask_if_empty=True needs asking."""
        config = FieldConfig(name="test", required=False, ask_if_empty=True)
        assert config.needs_asking(None) is True

    def test_optional_field_without_ask_if_empty(self):
        """Optional field with ask_if_empty=False doesn't need asking."""
        config = FieldConfig(name="test", required=False, ask_if_empty=False)
        assert config.needs_asking(None) is False

    def test_field_with_value_doesnt_need_asking(self):
        """Field that already has a value doesn't need asking."""
        config = FieldConfig(name="test", required=True, ask_if_empty=True)
        assert config.needs_asking("already_set") is False


# =============================================================================
# BaseTask Tests
# =============================================================================

class TestBaseTask:
    """Tests for BaseTask model."""

    def test_default_status_is_pending(self):
        """New tasks start in pending status."""
        task = BaseTask()
        assert task.status == TaskStatus.PENDING

    def test_mark_in_progress(self):
        """Can mark task as in progress."""
        task = BaseTask()
        task.mark_in_progress()
        assert task.status == TaskStatus.IN_PROGRESS

    def test_mark_complete(self):
        """Can mark task as complete with timestamp."""
        task = BaseTask()
        assert task.completed_at is None
        task.mark_complete()
        assert task.status == TaskStatus.COMPLETE
        assert task.completed_at is not None

    def test_mark_skipped(self):
        """Can mark task as skipped."""
        task = BaseTask()
        task.mark_skipped()
        assert task.status == TaskStatus.SKIPPED

    def test_is_actionable(self):
        """Task is actionable if pending or in progress."""
        task = BaseTask()
        assert task.is_actionable() is True

        task.mark_in_progress()
        assert task.is_actionable() is True

        task.mark_complete()
        assert task.is_actionable() is False

        task.status = TaskStatus.SKIPPED
        assert task.is_actionable() is False


# =============================================================================
# BagelItemTask Tests
# =============================================================================

class TestBagelItemTask:
    """Tests for BagelItemTask model."""

    def test_default_values(self):
        """Test default values for bagel task."""
        bagel = BagelItemTask()
        assert bagel.item_type == "bagel"
        assert bagel.quantity == 1
        assert bagel.bagel_type is None
        assert bagel.toasted is None
        assert bagel.spread is None
        assert bagel.extras == []

    def test_get_display_name(self):
        """Test display name generation."""
        bagel = BagelItemTask(bagel_type="everything")
        assert bagel.get_display_name() == "everything bagel"

        bagel_no_type = BagelItemTask()
        assert bagel_no_type.get_display_name() == "bagel"

    def test_get_summary_basic(self):
        """Test basic summary generation."""
        bagel = BagelItemTask(bagel_type="plain")
        assert "plain" in bagel.get_summary()

    def test_get_summary_full(self):
        """Test full summary with all options."""
        bagel = BagelItemTask(
            bagel_type="everything",
            quantity=2,
            toasted=True,
            spread="cream cheese",
            spread_type="scallion",
            extras=["lox", "capers"],
        )
        summary = bagel.get_summary()
        assert "2x" in summary
        assert "everything" in summary
        assert "toasted" in summary
        assert "scallion cream cheese" in summary
        assert "lox" in summary
        assert "capers" in summary

    def test_get_missing_required_fields(self):
        """Test finding missing required fields."""
        bagel = BagelItemTask()  # No fields set

        missing = bagel.get_missing_required_fields(DEFAULT_BAGEL_FIELDS)

        missing_names = [f.name for f in missing]
        # bagel_type now has a default of "plain bagel", so only toasted is missing
        assert "bagel_type" not in missing_names  # has default
        assert "toasted" in missing_names
        # quantity has default, so not missing
        assert "quantity" not in missing_names

    def test_get_missing_required_fields_when_filled(self):
        """Test no missing fields when all required are filled."""
        bagel = BagelItemTask(
            bagel_type="plain",
            toasted=False,
        )

        missing = bagel.get_missing_required_fields(DEFAULT_BAGEL_FIELDS)
        assert len(missing) == 0

    def test_get_fields_to_ask(self):
        """Test getting fields that need asking."""
        bagel = BagelItemTask()

        to_ask = bagel.get_fields_to_ask(DEFAULT_BAGEL_FIELDS)
        field_names = [f.name for f in to_ask]

        # bagel_type has a default now, so we don't ask
        assert "bagel_type" not in field_names
        # toasted is required with no default
        assert "toasted" in field_names
        # spread is optional with ask_if_empty=True
        assert "spread" in field_names
        # extras now has ask_if_empty=False, so we don't ask
        assert "extras" not in field_names
        # quantity has default, so we don't ask
        assert "quantity" not in field_names

    def test_get_progress(self):
        """Test progress calculation."""
        bagel = BagelItemTask()
        progress = bagel.get_progress(DEFAULT_BAGEL_FIELDS)
        # bagel_type and quantity have defaults, only toasted is missing
        # So 2/3 of required fields are filled
        assert progress == pytest.approx(2/3, rel=0.1)

        bagel.toasted = True
        progress = bagel.get_progress(DEFAULT_BAGEL_FIELDS)
        # All required fields now filled
        assert progress == pytest.approx(1.0)


# =============================================================================
# CoffeeItemTask Tests
# =============================================================================

class TestCoffeeItemTask:
    """Tests for CoffeeItemTask model."""

    def test_default_values(self):
        """Test default values for coffee task."""
        coffee = CoffeeItemTask()
        assert coffee.item_type == "coffee"
        assert coffee.drink_type is None
        assert coffee.size is None
        assert coffee.iced is None
        assert coffee.milk is None
        assert coffee.extra_shots == 0

    def test_get_display_name(self):
        """Test display name generation."""
        coffee = CoffeeItemTask(drink_type="latte", size="large", iced=True)
        assert coffee.get_display_name() == "large iced latte"

    def test_get_summary_with_modifiers(self):
        """Test summary with milk and sweetener."""
        coffee = CoffeeItemTask(
            drink_type="latte",
            size="medium",
            iced=True,
            milk="oat",
            sweeteners=[{"type": "vanilla", "quantity": 1}],
            extra_shots=2,
        )
        summary = coffee.get_summary()
        assert "medium" in summary
        assert "iced" in summary
        assert "latte" in summary
        assert "oat milk" in summary
        assert "vanilla" in summary
        assert "2 extra shots" in summary

    def test_coffee_fields_with_size_config(self):
        """Test that size field is configured to always ask."""
        # Size must be explicitly asked (no default, always ask)
        assert DEFAULT_COFFEE_FIELDS["size"].default is None
        assert DEFAULT_COFFEE_FIELDS["size"].ask_if_empty is True
        assert "small or large" in DEFAULT_COFFEE_FIELDS["size"].question.lower()


# =============================================================================
# DeliveryMethodTask Tests
# =============================================================================

class TestDeliveryMethodTask:
    """Tests for DeliveryMethodTask model."""

    def test_pickup_is_complete_immediately(self):
        """Pickup order type completes the task."""
        task = DeliveryMethodTask(order_type="pickup")
        assert task.is_complete() is True

    def test_delivery_requires_address(self):
        """Delivery order type requires address."""
        task = DeliveryMethodTask(order_type="delivery")
        assert task.is_complete() is False

        task.address.street = "123 Main St"
        assert task.is_complete() is False  # Still need zip

        task.address.zip_code = "10001"
        assert task.is_complete() is True

    def test_no_order_type_not_complete(self):
        """Task with no order type is not complete."""
        task = DeliveryMethodTask()
        assert task.is_complete() is False


# =============================================================================
# ItemsTask Tests
# =============================================================================

class TestItemsTask:
    """Tests for ItemsTask container."""

    def test_add_item(self):
        """Test adding items."""
        items_task = ItemsTask()
        bagel = BagelItemTask(bagel_type="plain")

        items_task.add_item(bagel)

        assert len(items_task.items) == 1
        assert items_task.status == TaskStatus.IN_PROGRESS

    def test_skip_item(self):
        """Test skipping items."""
        items_task = ItemsTask()
        bagel = BagelItemTask(bagel_type="plain")
        items_task.add_item(bagel)

        items_task.skip_item(0)

        assert items_task.items[0].status == TaskStatus.SKIPPED

    def test_get_active_items_excludes_skipped(self):
        """Active items excludes skipped items."""
        items_task = ItemsTask()
        bagel1 = BagelItemTask(bagel_type="plain")
        bagel2 = BagelItemTask(bagel_type="everything")

        items_task.add_item(bagel1)
        items_task.add_item(bagel2)
        items_task.skip_item(0)

        active = items_task.get_active_items()
        assert len(active) == 1
        assert active[0].bagel_type == "everything"

    def test_get_current_item(self):
        """Get item that's in progress."""
        items_task = ItemsTask()
        bagel = BagelItemTask(bagel_type="plain")
        coffee = CoffeeItemTask(drink_type="latte")

        items_task.add_item(bagel)
        items_task.add_item(coffee)

        bagel.mark_in_progress()

        current = items_task.get_current_item()
        assert current == bagel

    def test_get_next_pending_item(self):
        """Get next pending item."""
        items_task = ItemsTask()
        bagel = BagelItemTask(bagel_type="plain")
        coffee = CoffeeItemTask(drink_type="latte")

        items_task.add_item(bagel)
        items_task.add_item(coffee)

        bagel.mark_complete()

        next_item = items_task.get_next_pending_item()
        assert next_item == coffee

    def test_all_items_complete(self):
        """Test checking if all items complete."""
        items_task = ItemsTask()
        bagel = BagelItemTask(bagel_type="plain")
        coffee = CoffeeItemTask(drink_type="latte")

        items_task.add_item(bagel)
        items_task.add_item(coffee)

        assert items_task.all_items_complete() is False

        bagel.mark_complete()
        assert items_task.all_items_complete() is False

        coffee.mark_complete()
        assert items_task.all_items_complete() is True

    def test_get_subtotal(self):
        """Test subtotal calculation."""
        items_task = ItemsTask()
        bagel = BagelItemTask(bagel_type="plain", unit_price=4.50, quantity=2)
        coffee = CoffeeItemTask(drink_type="latte", unit_price=5.00)

        items_task.add_item(bagel)
        items_task.add_item(coffee)

        subtotal = items_task.get_subtotal()
        assert subtotal == 14.00  # (4.50 * 2) + 5.00


# =============================================================================
# OrderTask Tests
# =============================================================================

class TestOrderTask:
    """Tests for OrderTask root model."""

    def test_default_structure(self):
        """Test default order structure."""
        order = OrderTask()

        assert order.delivery_method is not None
        assert order.items is not None
        assert order.customer_info is not None
        assert order.checkout is not None
        assert order.payment is not None
        assert order.session_id is not None

    def test_add_message(self):
        """Test adding conversation messages."""
        order = OrderTask()
        order.add_message("user", "Hello")
        order.add_message("assistant", "Hi there!")

        assert len(order.conversation_history) == 2
        assert order.conversation_history[0]["role"] == "user"
        assert order.conversation_history[0]["content"] == "Hello"

    def test_is_complete(self):
        """Test order completion check."""
        order = OrderTask()
        assert order.is_complete() is False

        # Add and complete an item
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        # Set delivery method
        order.delivery_method.order_type = "pickup"

        # Confirm checkout
        order.checkout.confirmed = True

        assert order.is_complete() is True

    def test_get_order_summary(self):
        """Test order summary generation."""
        order = OrderTask()
        bagel = BagelItemTask(bagel_type="everything", toasted=True, unit_price=4.50)
        coffee = CoffeeItemTask(drink_type="latte", size="large", iced=True, unit_price=5.00)

        order.items.add_item(bagel)
        order.items.add_item(coffee)

        summary = order.get_order_summary()
        assert "everything" in summary
        assert "latte" in summary
        assert "$4.50" in summary
        assert "$5.00" in summary

    def test_get_progress_summary(self):
        """Test progress summary."""
        order = OrderTask()
        order.delivery_method.order_type = "pickup"
        order.delivery_method.mark_complete()  # Explicitly mark as complete

        progress = order.get_progress_summary()
        assert "✅" in progress["delivery_method"]  # Complete
        assert "⏳" in progress["items"]  # Pending


# =============================================================================
# MenuFieldConfig Tests
# =============================================================================

class TestMenuFieldConfig:
    """Tests for menu-based field configuration."""

    def test_default_config(self):
        """Test default configuration."""
        config = MenuFieldConfig()

        assert "bagel_type" in config.bagel_fields
        assert "drink_type" in config.coffee_fields
        assert config.bagel_fields["toasted"].required is True

    def test_from_menu_data_with_overrides(self):
        """Test loading config with menu overrides."""
        menu_data = {
            "field_config": {
                "bagel": {
                    "toasted": {"default": False, "ask_if_empty": False},
                },
                "coffee": {
                    "size": {"default": "large", "ask_if_empty": True, "question": "What size?"},
                },
            }
        }

        config = MenuFieldConfig.from_menu_data(menu_data)

        # Bagel toasted should now have default
        assert config.bagel_fields["toasted"].default is False
        assert config.bagel_fields["toasted"].ask_if_empty is False

        # Coffee size should now be large and ask
        assert config.coffee_fields["size"].default == "large"
        assert config.coffee_fields["size"].ask_if_empty is True
        assert config.coffee_fields["size"].question == "What size?"

    def test_get_fields_for_item_type(self):
        """Test getting fields for specific item types."""
        config = MenuFieldConfig()

        bagel_fields = config.get_fields_for_item_type("bagel")
        assert "bagel_type" in bagel_fields

        coffee_fields = config.get_fields_for_item_type("coffee")
        assert "drink_type" in coffee_fields

        unknown_fields = config.get_fields_for_item_type("unknown")
        assert unknown_fields == {}


class TestFieldConfigHelpers:
    """Tests for field config helper functions."""

    def test_get_field_config(self):
        """Test getting field config."""
        config = get_field_config("bagel", "toasted")
        assert config is not None
        assert config.name == "toasted"

    def test_get_default_value(self):
        """Test getting default values."""
        # Coffee size no longer has a default - must be asked explicitly
        size_default = get_default_value("coffee", "size")
        assert size_default is None

        # bagel_type now has a default of "plain bagel"
        bagel_type_default = get_default_value("bagel", "bagel_type")
        assert bagel_type_default == "plain bagel"

    def test_should_ask_field(self):
        """Test should_ask_field function."""
        # Bagel type with no value should NOT be asked (has default, ask_if_empty=False)
        assert should_ask_field("bagel", "bagel_type", None) is False

        # Toasted with no value should be asked (required, no default)
        assert should_ask_field("bagel", "toasted", None) is True

        # Toasted with value should not be asked
        assert should_ask_field("bagel", "toasted", True) is False

        # Size with no value SHOULD be asked (no default, ask_if_empty=True)
        assert should_ask_field("coffee", "size", None) is True
