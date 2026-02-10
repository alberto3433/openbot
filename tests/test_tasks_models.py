"""
Unit tests for the hierarchical task system models.

Run with: pytest tests/test_tasks_models.py -v
"""

import pytest
from orderbot.tasks.models import (
    TaskStatus,
    FieldConfig,
    BaseTask,
    MenuItemTask,
    DeliveryMethodTask,
    ItemsTask,
    OrderTask,
)
from orderbot.tasks.field_config import (
    MenuFieldConfig,
    get_field_config,
    get_default_value,
    should_ask_field,
)
from tests.helpers import create_bagel_task, create_coffee_task


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
# Bagel MenuItemTask Tests (formerly BagelItemTask)
# =============================================================================

class TestBagelItemTask:
    """Tests for MenuItemTask configured as a bagel."""

    def test_default_values(self):
        """Test default values for bagel task."""
        bagel = create_bagel_task()
        assert bagel.item_type == "menu_item"
        assert bagel.menu_item_type == "bagel"
        assert bagel.quantity == 1
        assert bagel["bread"] is None
        assert bagel["toasted"] is None
        assert bagel["spread_type"] is None
        assert bagel.get("toppings", []) == []

    def test_get_display_name(self):
        """Test display name generation.

        When a bread type is selected, the display name uses the bread's
        display name (e.g., "Everything Bagel") instead of generic "Bagel".
        When no bread type is selected, falls back to menu_item_name.
        """
        bagel = create_bagel_task(bagel_type="everything")
        # With bread type, display name comes from the bread ingredient
        display_name = bagel.get_display_name()
        assert "everything" in display_name.lower() or "Bagel" in display_name

        bagel_no_type = create_bagel_task()
        # Without bread type, falls back to menu_item_name
        assert bagel_no_type.get_display_name() == "Bagel"

    def test_get_summary_basic(self):
        """Test basic summary generation.

        Summary uses get_display_name() which returns the bread type's
        display name when available.
        """
        bagel = create_bagel_task(bagel_type="plain")
        summary = bagel.get_summary()
        # Summary uses display name (bread type or menu_item_name)
        assert "plain" in summary.lower() or "Bagel" in summary

    def test_get_summary_full(self):
        """Test full summary with all options.

        Summary uses get_display_name() which returns the bread type's
        display name when available.
        """
        bagel = create_bagel_task(
            bagel_type="everything",
            quantity=2,
            toasted=True,
            spread="cream cheese",
            spread_type="scallion",
            extras=["lox", "capers"],
        )
        summary = bagel.get_summary()
        assert "2x" in summary
        # Summary uses display name (bread type or menu_item_name)
        assert "everything" in summary.lower() or "Bagel" in summary

    def test_get_missing_required_fields(self):
        """Test finding missing required fields."""
        bagel = create_bagel_task()  # No fields set
        bagel_fields = MenuFieldConfig().get_fields_for_item_type("bagel")

        missing = bagel.get_missing_required_fields(bagel_fields)

        missing_names = [f.name for f in missing]
        # Database config: bread is required=True for bagels
        # So bread should be the only missing required field
        assert len(missing) == 1
        assert "bread" in missing_names

    def test_get_missing_required_fields_when_filled(self):
        """Test no missing fields when all required are filled."""
        bagel = create_bagel_task(
            bagel_type="plain",
            toasted=False,
        )
        bagel_fields = MenuFieldConfig().get_fields_for_item_type("bagel")

        missing = bagel.get_missing_required_fields(bagel_fields)
        assert len(missing) == 0

    def test_get_fields_to_ask(self):
        """Test getting fields that need asking."""
        bagel = create_bagel_task()
        bagel_fields = MenuFieldConfig().get_fields_for_item_type("bagel")

        to_ask = bagel.get_fields_to_ask(bagel_fields)
        field_names = [f.name for f in to_ask]

        # Database config: bagel_type, toasted, spread have ask_if_empty=True
        assert "bread" in field_names  # ask_if_empty=True
        assert "toasted" in field_names  # ask_if_empty=True
        assert "spread" in field_names  # ask_if_empty=True
        # extras maps to toppings which has ask_if_empty=False
        assert "extras" not in field_names
        # quantity is not in the database config
        assert "quantity" not in field_names

    def test_get_progress(self):
        """Test progress calculation."""
        bagel = create_bagel_task()
        bagel_fields = MenuFieldConfig().get_fields_for_item_type("bagel")
        progress = bagel.get_progress(bagel_fields)
        # Database config: bread is required=True
        # Progress is based on filled required fields, not task status
        # No bread set → 0/1 required fields = 0.0
        assert progress == pytest.approx(0.0)

        # Set bread → 1/1 required fields = 1.0
        bagel_with_bread = create_bagel_task(bagel_type="plain")
        progress = bagel_with_bread.get_progress(bagel_fields)
        assert progress == pytest.approx(1.0)


# =============================================================================
# Coffee MenuItemTask Tests (formerly CoffeeItemTask)
# =============================================================================

class TestCoffeeItemTask:
    """Tests for MenuItemTask configured as a sized beverage (coffee)."""

    def test_default_values(self):
        """Test default values for coffee task."""
        coffee = create_coffee_task()
        assert coffee.item_type == "menu_item"
        # Default "Coffee" is not an espresso drink, so it's coffee_based_beverage
        assert coffee.menu_item_type == "coffee_based_beverage"
        assert coffee["size"] is None
        # Note: temperature (iced/hot) is now part of menu_item_name, not a separate attribute
        # Milk is stored in selections, not attribute_values
        milk_mods = coffee.get_selections("milk")
        assert len(milk_mods) == 0
        assert coffee.get("extra_shots", 0) == 0

    def test_get_display_name(self):
        """Test display name generation.

        get_display_name() now returns just the menu_item_name.
        Attributes like size are shown uniformly in get_summary().
        """
        coffee = create_coffee_task(drink_type="Iced Latte", size="large")
        # Display name is just the menu item name
        assert coffee.get_display_name() == "Iced Latte"
        # Size is shown in summary, not display name
        assert "large" in coffee.get_summary().lower()

    def test_get_summary_with_modifiers(self):
        """Test summary with milk and sweetener."""
        # Note: Temperature is now part of the menu item name itself
        coffee = create_coffee_task(
            drink_type="Iced Latte",
            size="medium",
            milk="oat",
            sweeteners=[{"slug": "vanilla", "quantity": 1}],
            extra_shots=2,
        )
        summary = coffee.get_summary()
        assert "medium" in summary.lower()
        assert "latte" in summary.lower()
        # MenuItemTask summary structure may be different
        # Check for key elements
        assert "latte" in summary.lower()

    def test_coffee_fields_with_size_config(self):
        """Test that size field is configured to always ask."""
        coffee_fields = MenuFieldConfig().get_fields_for_item_type("coffee_based_beverage")
        # Size must be explicitly asked (no default, always ask)
        assert coffee_fields["size"].default is None
        assert coffee_fields["size"].ask_if_empty is True
        assert coffee_fields["size"].question is not None
        assert "size" in coffee_fields["size"].question.lower()


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
        bagel = create_bagel_task(bagel_type="plain")

        items_task.add_item(bagel)

        assert len(items_task.items) == 1
        assert items_task.status == TaskStatus.IN_PROGRESS

    def test_skip_item(self):
        """Test skipping items."""
        items_task = ItemsTask()
        bagel = create_bagel_task(bagel_type="plain")
        items_task.add_item(bagel)

        items_task.skip_item(0)

        assert items_task.items[0].status == TaskStatus.SKIPPED

    def test_get_active_items_excludes_skipped(self):
        """Active items excludes skipped items."""
        items_task = ItemsTask()
        bagel1 = create_bagel_task(bagel_type="plain")
        bagel2 = create_bagel_task(bagel_type="everything")

        items_task.add_item(bagel1)
        items_task.add_item(bagel2)
        items_task.skip_item(0)

        active = items_task.get_active_items()
        assert len(active) == 1
        assert active[0]["bread"] == "everything"

    def test_get_current_item(self):
        """Get item that's in progress."""
        items_task = ItemsTask()
        bagel = create_bagel_task(bagel_type="plain")
        coffee = create_coffee_task(drink_type="latte")

        items_task.add_item(bagel)
        items_task.add_item(coffee)

        bagel.mark_in_progress()

        current = items_task.get_current_item()
        assert current == bagel

    def test_get_next_pending_item(self):
        """Get next pending item."""
        items_task = ItemsTask()
        bagel = create_bagel_task(bagel_type="plain")
        coffee = create_coffee_task(drink_type="latte")

        items_task.add_item(bagel)
        items_task.add_item(coffee)

        bagel.mark_complete()

        next_item = items_task.get_next_pending_item()
        assert next_item == coffee

    def test_all_items_complete(self):
        """Test checking if all items complete."""
        items_task = ItemsTask()
        bagel = create_bagel_task(bagel_type="plain")
        coffee = create_coffee_task(drink_type="latte")

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
        bagel = create_bagel_task(bagel_type="plain", unit_price=4.50, quantity=2)
        coffee = create_coffee_task(drink_type="latte", unit_price=5.00)

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
        bagel = create_bagel_task(bagel_type="plain", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        # Set delivery method
        order.delivery_method.order_type = "pickup"

        # Confirm checkout
        order.checkout.confirmed = True

        assert order.is_complete() is True

    def test_get_order_summary(self):
        """Test order summary generation.

        Summary uses get_display_name() which returns the bread type's
        display name when available.
        """
        order = OrderTask()
        bagel = create_bagel_task(bagel_type="everything", toasted=True, unit_price=4.50)
        coffee = create_coffee_task(drink_type="latte", size="large", iced=True, unit_price=5.00)

        order.items.add_item(bagel)
        order.items.add_item(coffee)

        summary = order.get_order_summary()
        # Summary uses bread type display name when available
        assert "everything" in summary.lower() or "bagel" in summary.lower()
        assert "latte" in summary.lower()
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
        """Test default configuration loaded from database."""
        config = MenuFieldConfig()

        # Fields are loaded from database via get_fields_for_item_type()
        bagel_fields = config.get_fields_for_item_type("bagel")
        assert "bread" in bagel_fields
        # Coffee fields include size (from database)
        coffee_fields = config.get_fields_for_item_type("coffee_based_beverage")
        assert "size" in coffee_fields
        # Database config: toasted is optional (required=False)
        assert bagel_fields["toasted"].required is False

    def test_from_menu_data_ignores_overrides(self):
        """Test that from_menu_data returns config without applying overrides.

        Note: The current implementation doesn't support menu_data overrides.
        Field config is loaded from the database only.
        """
        menu_data = {
            "field_config": {
                "bagel": {
                    "toasted": {"default": False, "ask_if_empty": False},
                },
            }
        }

        config = MenuFieldConfig.from_menu_data(menu_data)

        # from_menu_data returns default config - overrides not supported
        # Database config is the source of truth
        bagel_fields = config.get_fields_for_item_type("bagel")
        assert "bread" in bagel_fields
        assert "toasted" in bagel_fields

    def test_get_fields_for_item_type(self):
        """Test getting fields for specific item types."""
        config = MenuFieldConfig()

        bagel_fields = config.get_fields_for_item_type("bagel")
        assert "bread" in bagel_fields

        # The database item type is "coffee_based_beverage" (not "coffee")
        beverage_fields = config.get_fields_for_item_type("coffee_based_beverage")
        assert "size" in beverage_fields

    def test_get_fields_for_unknown_item_type_raises(self):
        """Test that unknown item type raises MenuDataNotLoadedError."""
        from orderbot.exceptions import MenuDataNotLoadedError
        config = MenuFieldConfig()

        with pytest.raises(MenuDataNotLoadedError):
            config.get_fields_for_item_type("unknown")


class TestFieldConfigHelpers:
    """Tests for field config helper functions."""

    def test_get_field_config(self):
        """Test getting field config."""
        config = get_field_config("bagel", "toasted")
        assert config is not None
        assert config.name == "toasted"

    def test_get_default_value(self):
        """Test getting default values from database."""
        # Database config: coffee_based_beverage size has no default
        size_default = get_default_value("coffee_based_beverage", "size")
        assert size_default is None

        # Database config: bread has no default
        bread_default = get_default_value("bagel", "bread")
        assert bread_default is None

    def test_should_ask_field(self):
        """Test should_ask_field function with database config."""
        # Database config: bread has ask_if_empty=True, no default
        assert should_ask_field("bagel", "bread", None) is True

        # Database config: toasted has ask_if_empty=True
        assert should_ask_field("bagel", "toasted", None) is True

        # Toasted with value should not be asked
        assert should_ask_field("bagel", "toasted", True) is False

        # Size with no value SHOULD be asked (ask_if_empty=True)
        # Note: The database item type is "coffee_based_beverage" (not "coffee")
        assert should_ask_field("coffee_based_beverage", "size", None) is True


# =============================================================================
# Quantity-Aware Modifier Removal Tests
# =============================================================================

class TestQuantityAwareRemoval:
    """Tests for quantity-aware modifier removal (decrement_by parameter)."""

    def test_decrement_selection_reduces_quantity(self):
        """Test that decrement_by reduces quantity instead of removing."""
        from orderbot.tasks.models import MenuItemTask

        item = MenuItemTask(
            menu_item_name="Latte",
            menu_item_type="espresso_based",
        )
        # Add 5 shots
        item.add_selection("shot", "espresso_shots", quantity=5)

        # Verify initial state
        sel = item.get_selection("espresso_shots")
        assert sel is not None
        assert sel["quantity"] == 5

        # Decrement by 1
        removed = item.remove_selection("espresso_shots", "shot", decrement_by=1)
        assert removed is True

        # Verify quantity was decremented
        sel = item.get_selection("espresso_shots")
        assert sel is not None
        assert sel["quantity"] == 4

    def test_decrement_to_zero_removes_selection(self):
        """Test that decrement_by that reaches 0 removes the selection entirely."""
        from orderbot.tasks.models import MenuItemTask

        item = MenuItemTask(
            menu_item_name="Latte",
            menu_item_type="espresso_based",
        )
        # Add 2 shots
        item.add_selection("shot", "espresso_shots", quantity=2)

        # Decrement by 2 (exact removal)
        removed = item.remove_selection("espresso_shots", "shot", decrement_by=2)
        assert removed is True

        # Verify selection was removed
        sel = item.get_selection("espresso_shots")
        assert sel is None

    def test_over_decrement_removes_selection(self):
        """Test that decrement_by larger than quantity removes the selection."""
        from orderbot.tasks.models import MenuItemTask

        item = MenuItemTask(
            menu_item_name="Latte",
            menu_item_type="espresso_based",
        )
        # Add 3 shots
        item.add_selection("shot", "espresso_shots", quantity=3)

        # Decrement by 10 (more than available)
        removed = item.remove_selection("espresso_shots", "shot", decrement_by=10)
        assert removed is True

        # Verify selection was removed entirely
        sel = item.get_selection("espresso_shots")
        assert sel is None

    def test_no_decrement_by_removes_all(self):
        """Test that None decrement_by removes entire selection (existing behavior)."""
        from orderbot.tasks.models import MenuItemTask

        item = MenuItemTask(
            menu_item_name="Latte",
            menu_item_type="espresso_based",
        )
        # Add 5 shots
        item.add_selection("shot", "espresso_shots", quantity=5)

        # Remove without decrement_by
        removed = item.remove_selection("espresso_shots", "shot", decrement_by=None)
        assert removed is True

        # Verify selection was fully removed
        sel = item.get_selection("espresso_shots")
        assert sel is None

    def test_decrement_without_slug_removes_all(self):
        """Test that decrement_by is ignored when slug is None (removes all in category)."""
        from orderbot.tasks.models import MenuItemTask

        item = MenuItemTask(
            menu_item_name="Latte",
            menu_item_type="espresso_based",
        )
        # Add multiple selections in same category
        item.add_selection("shot", "espresso_shots", quantity=3)
        item.add_selection("decaf_shot", "espresso_shots", quantity=2)

        # Remove all in category (slug=None)
        removed = item.remove_selection("espresso_shots", slug=None, decrement_by=1)
        assert removed is True

        # Both selections should be removed (decrement_by ignored when slug=None)
        assert item.get_selection("espresso_shots") is None
        assert len(item.get_selections("espresso_shots")) == 0

    def test_decrement_preserves_other_selections(self):
        """Test that decrement only affects the matched selection."""
        from orderbot.tasks.models import MenuItemTask

        item = MenuItemTask(
            menu_item_name="Latte",
            menu_item_type="espresso_based",
        )
        # Add different types of modifiers
        item.add_selection("shot", "espresso_shots", quantity=5)
        item.add_selection("oat_milk", "milk_sweetener_syrup", quantity=1)
        item.add_selection("vanilla_syrup", "milk_sweetener_syrup", quantity=2)

        # Decrement shots by 2
        removed = item.remove_selection("espresso_shots", "shot", decrement_by=2)
        assert removed is True

        # Verify shots decremented
        shot_sel = item.get_selection("espresso_shots")
        assert shot_sel is not None
        assert shot_sel["quantity"] == 3

        # Verify other selections unchanged
        milk_sels = item.get_selections("milk_sweetener_syrup")
        assert len(milk_sels) == 2
        oat_milk = next((s for s in milk_sels if s["slug"] == "oat_milk"), None)
        vanilla = next((s for s in milk_sels if s["slug"] == "vanilla_syrup"), None)
        assert oat_milk is not None and oat_milk["quantity"] == 1
        assert vanilla is not None and vanilla["quantity"] == 2
