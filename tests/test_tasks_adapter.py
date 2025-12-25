"""
Tests for the task orchestrator adapter module.

Tests state conversion between dict-based order state and OrderTask.
"""

import pytest
import os
from unittest.mock import patch

from sandwich_bot.tasks.adapter import (
    is_task_orchestrator_enabled,
    dict_to_order_task,
    order_task_to_dict,
    process_message_with_tasks,
)
from sandwich_bot.tasks.models import (
    TaskStatus,
    OrderTask,
    BagelItemTask,
    CoffeeItemTask,
)


# =============================================================================
# Feature Flag Tests
# =============================================================================

class TestFeatureFlag:
    """Tests for is_task_orchestrator_enabled."""

    def test_enabled_by_default(self):
        """Test that feature is enabled by default."""
        with patch.dict(os.environ, {}, clear=True):
            assert is_task_orchestrator_enabled() is True

    def test_enabled_when_true(self):
        """Test enabling with 'true'."""
        with patch.dict(os.environ, {"TASK_ORCHESTRATOR_ENABLED": "true"}):
            assert is_task_orchestrator_enabled() is True

    def test_disabled_when_false(self):
        """Test explicit disable with 'false'."""
        with patch.dict(os.environ, {"TASK_ORCHESTRATOR_ENABLED": "false"}):
            assert is_task_orchestrator_enabled() is False

    def test_percentage_rollout(self):
        """Test percentage-based rollout."""
        with patch.dict(os.environ, {"TASK_ORCHESTRATOR_ENABLED": "100"}):
            assert is_task_orchestrator_enabled() is True

        with patch.dict(os.environ, {"TASK_ORCHESTRATOR_ENABLED": "0"}):
            assert is_task_orchestrator_enabled() is False


# =============================================================================
# Dict to OrderTask Conversion Tests
# =============================================================================

class TestDictToOrderTask:
    """Tests for dict_to_order_task conversion."""

    def test_empty_dict(self):
        """Test converting empty dict."""
        order = dict_to_order_task({})
        assert isinstance(order, OrderTask)
        assert order.items.get_item_count() == 0

    def test_none_input(self):
        """Test converting None."""
        order = dict_to_order_task(None)
        assert isinstance(order, OrderTask)

    def test_customer_info(self):
        """Test converting customer info."""
        order_dict = {
            "customer": {
                "name": "John Doe",
                "phone": "555-1234",
                "email": "john@example.com",
            }
        }
        order = dict_to_order_task(order_dict)

        assert order.customer_info.name == "John Doe"
        assert order.customer_info.phone == "555-1234"
        assert order.customer_info.email == "john@example.com"

    def test_pickup_order_type(self):
        """Test converting pickup order type."""
        order_dict = {"order_type": "pickup"}
        order = dict_to_order_task(order_dict)

        assert order.delivery_method.order_type == "pickup"
        assert order.delivery_method.status == TaskStatus.COMPLETE

    def test_delivery_order_type(self):
        """Test converting delivery order type with address."""
        order_dict = {
            "order_type": "delivery",
            "delivery_address": "123 Main St, New York",
        }
        order = dict_to_order_task(order_dict)

        assert order.delivery_method.order_type == "delivery"
        assert order.delivery_method.address.street == "123 Main St, New York"

    def test_bagel_item(self):
        """Test converting a bagel item."""
        order_dict = {
            "items": [{
                "item_type": "sandwich",
                "menu_item_name": "everything bagel",
                "toasted": True,
                "cheese": "cream cheese",
                "toppings": ["lox", "capers"],
                "quantity": 2,
                "unit_price": 5.99,
            }]
        }
        order = dict_to_order_task(order_dict)

        # get_item_count returns sum of quantities, not number of items
        assert len(order.items.items) == 1
        assert order.items.get_item_count() == 2  # quantity is 2
        item = order.items.items[0]
        assert isinstance(item, BagelItemTask)
        assert item.bagel_type == "everything bagel"
        assert item.toasted is True
        assert item.spread == "cream cheese"
        assert item.extras == ["lox", "capers"]
        assert item.quantity == 2
        assert item.unit_price == 5.99

    def test_coffee_item(self):
        """Test converting a coffee item."""
        order_dict = {
            "items": [{
                "item_type": "drink",
                "menu_item_name": "iced latte",
                "size": "large",
                "item_config": {
                    "milk": "oat",
                    "sweetener": "vanilla",
                    "style": "iced",
                },
                "unit_price": 6.50,
            }]
        }
        order = dict_to_order_task(order_dict)

        assert order.items.get_item_count() == 1
        item = order.items.items[0]
        assert isinstance(item, CoffeeItemTask)
        assert item.drink_type == "iced latte"
        assert item.size == "large"
        assert item.iced is True  # inferred from "iced" in name
        assert item.milk == "oat"
        assert item.sweetener == "vanilla"

    def test_multiple_items(self):
        """Test converting multiple items."""
        order_dict = {
            "items": [
                {"item_type": "sandwich", "menu_item_name": "plain bagel", "toasted": False},
                {"item_type": "drink", "menu_item_name": "coffee", "size": "medium"},
            ]
        }
        order = dict_to_order_task(order_dict)

        assert order.items.get_item_count() == 2
        assert isinstance(order.items.items[0], BagelItemTask)
        assert isinstance(order.items.items[1], CoffeeItemTask)

    def test_confirmed_order(self):
        """Test converting confirmed order."""
        order_dict = {"status": "confirmed"}
        order = dict_to_order_task(order_dict)

        assert order.checkout.confirmed is True


# =============================================================================
# OrderTask to Dict Conversion Tests
# =============================================================================

class TestOrderTaskToDict:
    """Tests for order_task_to_dict conversion."""

    def test_empty_order(self):
        """Test converting empty order."""
        order = OrderTask()
        result = order_task_to_dict(order)

        assert result["status"] == "pending"
        assert result["items"] == []
        assert result["total_price"] == 0

    def test_customer_info(self):
        """Test converting customer info."""
        order = OrderTask()
        order.customer_info.name = "Jane Doe"
        order.customer_info.phone = "555-5678"
        order.customer_info.email = "jane@example.com"

        result = order_task_to_dict(order)

        assert result["customer"]["name"] == "Jane Doe"
        assert result["customer"]["phone"] == "555-5678"
        assert result["customer"]["email"] == "jane@example.com"

    def test_order_type(self):
        """Test converting order type."""
        order = OrderTask()
        order.delivery_method.order_type = "pickup"

        result = order_task_to_dict(order)

        assert result["order_type"] == "pickup"

    def test_delivery_address(self):
        """Test converting delivery address."""
        order = OrderTask()
        order.delivery_method.order_type = "delivery"
        order.delivery_method.address.street = "456 Oak Ave"

        result = order_task_to_dict(order)

        assert result["order_type"] == "delivery"
        assert result["delivery_address"] == "456 Oak Ave"

    def test_bagel_item_conversion(self):
        """Test converting bagel item to dict."""
        order = OrderTask()
        bagel = BagelItemTask(
            bagel_type="sesame",
            toasted=True,
            spread="butter",
            extras=["tomato"],
            quantity=1,
            unit_price=4.99,
        )
        order.items.add_item(bagel)

        result = order_task_to_dict(order)

        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["item_type"] == "bagel"  # Bagels now keep their type
        assert item["bagel_type"] == "sesame"
        assert item["toasted"] is True
        assert item["spread"] == "butter"
        assert item["extras"] == ["tomato"]  # Bagels use "extras" not "toppings"
        assert item["quantity"] == 1
        assert item["unit_price"] == 4.99

    def test_coffee_item_conversion(self):
        """Test converting coffee item to dict."""
        order = OrderTask()
        coffee = CoffeeItemTask(
            drink_type="latte",
            size="large",
            iced=True,
            milk="almond",
            sweetener="honey",
            unit_price=5.50,
        )
        order.items.add_item(coffee)

        result = order_task_to_dict(order)

        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["item_type"] == "drink"
        assert item["menu_item_name"] == "latte"
        assert item["size"] == "large"
        assert item["item_config"]["style"] == "iced"
        assert item["item_config"]["milk"] == "almond"
        assert item["item_config"]["sweetener"] == "honey"

    def test_confirmed_status(self):
        """Test confirmed order status."""
        order = OrderTask()
        order.checkout.confirmed = True

        result = order_task_to_dict(order)

        assert result["status"] == "confirmed"

    def test_collecting_items_status(self):
        """Test status when items exist."""
        order = OrderTask()
        order.items.add_item(BagelItemTask(bagel_type="plain"))

        result = order_task_to_dict(order)

        assert result["status"] == "collecting_items"

    def test_total_price_calculation(self):
        """Test total price is calculated correctly."""
        order = OrderTask()
        order.items.add_item(BagelItemTask(bagel_type="plain", unit_price=3.99, quantity=2))
        order.items.add_item(CoffeeItemTask(drink_type="coffee", unit_price=2.50))

        result = order_task_to_dict(order)

        expected_total = (3.99 * 2) + 2.50  # 10.48
        assert result["total_price"] == expected_total

    def test_skipped_items_excluded(self):
        """Test that skipped items are excluded."""
        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain")
        coffee = CoffeeItemTask(drink_type="latte")
        order.items.add_item(bagel)
        order.items.add_item(coffee)
        order.items.skip_item(0)  # Skip the bagel

        result = order_task_to_dict(order)

        # Only the coffee should be in the output
        assert len(result["items"]) == 1
        assert result["items"][0]["menu_item_name"] == "latte"


# =============================================================================
# Round-Trip Conversion Tests
# =============================================================================

class TestRoundTripConversion:
    """Tests for converting dict -> OrderTask -> dict."""

    def test_basic_roundtrip(self):
        """Test that basic data survives round-trip."""
        original = {
            "status": "collecting_items",
            "order_type": "pickup",
            "customer": {
                "name": "Test User",
                "phone": "555-0000",
            },
            "items": [
                {
                    "item_type": "bagel",
                    "bagel_type": "everything",
                    "toasted": True,
                    "spread": "cream cheese",
                    "toppings": [],
                    "quantity": 1,
                    "unit_price": 5.00,
                }
            ],
        }

        # Convert to OrderTask and back
        order = dict_to_order_task(original)
        result = order_task_to_dict(order)

        # Check key fields survived
        assert result["order_type"] == "pickup"
        assert result["customer"]["name"] == "Test User"
        assert len(result["items"]) == 1
        assert result["items"][0]["item_type"] == "bagel"
        assert result["items"][0]["bagel_type"] == "everything"
        assert result["items"][0]["toasted"] is True
        assert result["items"][0]["spread"] == "cream cheese"

    def test_conversation_history_preserved(self):
        """Test that conversation history is preserved."""
        original = {
            "task_orchestrator_state": {
                "conversation_history": [
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi there!"},
                ]
            }
        }

        order = dict_to_order_task(original)
        result = order_task_to_dict(order)

        assert result["task_orchestrator_state"]["conversation_history"] == [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
