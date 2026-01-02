"""
Tests for the adapter module.

Tests state conversion between dict-based order state and OrderTask.
"""

import pytest

from sandwich_bot.tasks.adapter import (
    dict_to_order_task,
    order_task_to_dict,
)
from sandwich_bot.tasks.models import (
    TaskStatus,
    OrderTask,
    BagelItemTask,
    CoffeeItemTask,
)


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
                    "sweeteners": [{"type": "sugar", "quantity": 2}],
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
        assert item.sweeteners == [{"type": "sugar", "quantity": 2}]

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
            sweeteners=[{"type": "honey", "quantity": 1}],
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
        assert item["item_config"]["sweeteners"] == [{"type": "honey", "quantity": 1}]

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


# =============================================================================
# Modifiers Consistency Tests
# =============================================================================

class TestModifiersConsistency:
    """
    Tests for consistent modifier display across chat UI, admin page, and email.

    These tests ensure that modifiers (like lox, cream cheese, oat milk) are:
    1. Included in item_config when converting OrderTask to dict
    2. Properly preserved for database persistence
    3. Available for display in admin UI and confirmation emails
    """

    def test_bagel_with_lox_has_modifiers_in_item_config(self):
        """Test that bagel with lox includes modifiers in item_config."""
        order = OrderTask()
        bagel = BagelItemTask(
            bagel_type="plain",
            toasted=False,
            extras=["nova scotia salmon"],  # lox
            unit_price=8.75,  # $2.75 bagel + $6.00 lox
        )
        order.items.add_item(bagel)

        result = order_task_to_dict(order)

        item = result["items"][0]
        # Modifiers should be in both top-level AND item_config
        assert "modifiers" in item
        assert "modifiers" in item["item_config"]
        # Both should be the same
        assert item["modifiers"] == item["item_config"]["modifiers"]
        # Check lox modifier is present
        modifier_names = [m["name"] for m in item["modifiers"]]
        assert "nova scotia salmon" in modifier_names

    def test_bagel_modifiers_have_correct_prices(self):
        """Test that bagel modifiers have correct prices."""
        order = OrderTask()
        bagel = BagelItemTask(
            bagel_type="multigrain",
            toasted=True,
            spread="cream cheese",
            extras=["nova scotia salmon"],
            unit_price=11.75,  # bagel + lox + cream cheese
        )
        order.items.add_item(bagel)

        result = order_task_to_dict(order)

        item = result["items"][0]
        modifiers = item["item_config"]["modifiers"]

        # Find lox and cream cheese modifiers
        lox_mod = next((m for m in modifiers if "salmon" in m["name"].lower() or m["name"].lower() == "nova"), None)
        cream_cheese_mod = next((m for m in modifiers if "cream cheese" in m["name"].lower()), None)

        # Verify lox price
        assert lox_mod is not None, f"Lox modifier not found in {modifiers}"
        assert lox_mod["price"] == 6.00, f"Expected lox price 6.00, got {lox_mod['price']}"

        # Verify cream cheese price
        assert cream_cheese_mod is not None
        assert cream_cheese_mod["price"] == 1.50

    def test_bagel_base_price_in_item_config(self):
        """Test that base price is stored in item_config for bagels."""
        order = OrderTask()
        bagel = BagelItemTask(
            bagel_type="plain",
            toasted=True,
            extras=["bacon"],
            unit_price=4.75,  # $2.75 bagel + $2.00 bacon
        )
        order.items.add_item(bagel)

        result = order_task_to_dict(order)

        item = result["items"][0]
        # Base price should be in item_config
        assert "base_price" in item["item_config"]
        # Base price should be the bagel price without modifiers
        assert item["item_config"]["base_price"] >= 2.20  # At least default bagel price

    def test_coffee_modifiers_in_item_config(self):
        """Test that coffee modifiers with upcharges are in item_config."""
        order = OrderTask()
        coffee = CoffeeItemTask(
            drink_type="latte",
            size="large",
            iced=True,
            milk="oat",
            milk_upcharge=0.70,
            unit_price=5.70,  # $5.00 base + $0.70 oat milk
        )
        order.items.add_item(coffee)

        result = order_task_to_dict(order)

        item = result["items"][0]
        # Modifiers and free_details should be in item_config
        assert "modifiers" in item["item_config"]
        assert "free_details" in item["item_config"]

        # Oat milk upcharge should be in modifiers
        modifiers = item["item_config"]["modifiers"]
        milk_mod = next((m for m in modifiers if "oat" in m["name"].lower()), None)
        assert milk_mod is not None
        assert milk_mod["price"] == 0.70

    def test_coffee_free_details_in_item_config(self):
        """Test that free coffee details (iced/hot, sweetener) are in item_config."""
        order = OrderTask()
        coffee = CoffeeItemTask(
            drink_type="coffee",
            size="medium",
            iced=False,
            sweeteners=[{"type": "sugar", "quantity": 1}],
            unit_price=3.50,
        )
        order.items.add_item(coffee)

        result = order_task_to_dict(order)

        item = result["items"][0]
        free_details = item["item_config"]["free_details"]

        # Should contain "hot" and "sugar"
        assert any("hot" in d.lower() for d in free_details)
        assert any("sugar" in d.lower() for d in free_details)

    def test_coffee_decaf_in_free_details(self):
        """Test that decaf coffee has 'decaf' in free_details."""
        order = OrderTask()
        coffee = CoffeeItemTask(
            drink_type="coffee",
            size="medium",
            iced=True,
            decaf=True,  # Decaf coffee
            unit_price=3.50,
        )
        order.items.add_item(coffee)

        result = order_task_to_dict(order)

        item = result["items"][0]
        free_details = item["free_details"]
        item_config_free_details = item["item_config"]["free_details"]

        # Should contain "decaf" in both top-level free_details and item_config
        assert "decaf" in free_details, f"Expected 'decaf' in free_details, got: {free_details}"
        assert "decaf" in item_config_free_details, f"Expected 'decaf' in item_config.free_details, got: {item_config_free_details}"

        # Should also contain "iced" and "medium"
        assert "iced" in free_details
        assert "medium" in free_details

        # item_config should have decaf=True
        assert item["item_config"]["decaf"] is True

    def test_menu_item_modifiers_in_item_config(self):
        """Test that menu item (omelette) modifiers are in item_config."""
        from sandwich_bot.tasks.models import MenuItemTask

        order = OrderTask()
        item = MenuItemTask(
            menu_item_name="The Western Omelette",
            menu_item_type="omelette",
            side_choice="bagel",
            bagel_choice="everything",
            toasted=True,
            spread="cream cheese",
            spread_price=1.50,
            modifications=["extra cheese"],
            unit_price=14.99,
        )
        order.items.add_item(item)

        result = order_task_to_dict(order)

        item_dict = result["items"][0]
        # Modifiers should be in item_config
        assert "modifiers" in item_dict["item_config"]

    def test_modifiers_preserved_through_roundtrip(self):
        """Test that modifiers are preserved when saving to/loading from database format."""
        order = OrderTask()
        bagel = BagelItemTask(
            bagel_type="plain",
            toasted=False,
            extras=["nova scotia salmon", "capers"],
            unit_price=9.00,
        )
        order.items.add_item(bagel)

        # Convert to dict (this is what gets saved to database)
        order_dict = order_task_to_dict(order)
        item = order_dict["items"][0]

        # The item_config is what's stored in the database
        item_config = item["item_config"]

        # Verify modifiers are in item_config
        assert "modifiers" in item_config
        modifiers = item_config["modifiers"]

        # Should have both extras as modifiers
        modifier_names = [m["name"] for m in modifiers]
        assert "nova scotia salmon" in modifier_names
        assert "capers" in modifier_names

    def test_multiple_items_all_have_modifiers_in_item_config(self):
        """Test that all items in an order have modifiers in item_config."""
        order = OrderTask()

        # Add bagel with lox
        bagel = BagelItemTask(
            bagel_type="plain",
            extras=["nova scotia salmon"],
            unit_price=8.75,
        )
        order.items.add_item(bagel)

        # Add coffee with oat milk
        coffee = CoffeeItemTask(
            drink_type="latte",
            size="large",
            milk="oat",
            milk_upcharge=0.70,
            unit_price=5.70,
        )
        order.items.add_item(coffee)

        result = order_task_to_dict(order)

        # Both items should have modifiers in item_config
        for item in result["items"]:
            assert "item_config" in item
            assert "modifiers" in item["item_config"]

    def test_empty_modifiers_still_in_item_config(self):
        """Test that even items without modifiers have the modifiers field in item_config."""
        order = OrderTask()
        bagel = BagelItemTask(
            bagel_type="plain",
            toasted=True,
            unit_price=2.75,
        )
        order.items.add_item(bagel)

        result = order_task_to_dict(order)

        item = result["items"][0]
        # modifiers should be in item_config even if empty
        assert "modifiers" in item["item_config"]
        assert isinstance(item["item_config"]["modifiers"], list)

    def test_item_display_matches_cart_display(self):
        """Test that the data structure supports identical display in cart and admin."""
        order = OrderTask()
        # Price breakdown:
        # - base_price: $2.20
        # - multigrain bagel type: $0.00 (no upcharge)
        # - toasted: $0.00
        # - nova scotia salmon: $6.00
        # - cream cheese: $1.50
        # - Total: $9.70
        bagel = BagelItemTask(
            bagel_type="multigrain",
            toasted=True,
            extras=["nova scotia salmon"],
            spread="cream cheese",
            unit_price=9.70,
        )
        order.items.add_item(bagel)

        result = order_task_to_dict(order)
        item = result["items"][0]

        # The cart would display:
        # - Bagel: $2.20 (base_price)
        # - Multigrain: $0.00 (bagel type modifier)
        # - Toasted: $0.00
        # - nova scotia salmon: $6.00
        # - cream cheese: $1.50
        # Total: $9.70

        # Check all necessary data is present
        assert "display_name" in item  # For the main item line
        assert "base_price" in item["item_config"]  # Base price before modifiers
        assert "modifiers" in item["item_config"]  # List of modifiers with prices
        assert item["line_total"] == 9.70  # Total for the line

        # Verify we can calculate: base_price + sum(modifiers) = line_total
        base_price = item["item_config"]["base_price"]
        modifiers_total = sum(m["price"] for m in item["item_config"]["modifiers"])
        calculated_total = base_price + modifiers_total

        # Allow small floating point difference
        assert abs(calculated_total - item["line_total"]) < 0.01

    def test_gluten_free_bagel_upcharge_shown_as_modifier(self):
        """Test that gluten free bagel upcharge is shown as a separate modifier."""
        order = OrderTask()
        # Gluten free bagel: $2.20 base + $0.80 upcharge = $3.00
        bagel = BagelItemTask(
            bagel_type="gluten free",
            bagel_type_upcharge=0.80,  # Gluten free upcharge
            toasted=True,
            spread="cream cheese",
            unit_price=4.50,  # $2.20 base + $0.80 gluten free + $1.50 cream cheese
        )
        order.items.add_item(bagel)

        result = order_task_to_dict(order)
        item = result["items"][0]

        # Check that bagel type is shown as a modifier with upcharge
        modifiers = item["item_config"]["modifiers"]
        bagel_type_modifier = next(
            (m for m in modifiers if "gluten" in m["name"].lower()),
            None
        )
        assert bagel_type_modifier is not None, "Gluten free should be in modifiers"
        assert bagel_type_modifier["price"] == 0.80, "Gluten free upcharge should be $0.80"

        # Verify base_price + modifiers = line_total
        base_price = item["item_config"]["base_price"]
        modifiers_total = sum(m["price"] for m in modifiers)
        calculated_total = base_price + modifiers_total
        assert abs(calculated_total - item["line_total"]) < 0.01

    def test_regular_bagel_type_shown_as_modifier_without_upcharge(self):
        """Test that regular bagel types are shown as modifiers with $0 upcharge."""
        order = OrderTask()
        # Plain bagel: $2.20 base + $0.00 upcharge
        bagel = BagelItemTask(
            bagel_type="plain",
            bagel_type_upcharge=0.0,  # No upcharge for plain bagel
            toasted=False,
            unit_price=2.20,  # Just the base price
        )
        order.items.add_item(bagel)

        result = order_task_to_dict(order)
        item = result["items"][0]

        # Check that bagel type is shown as a modifier
        modifiers = item["item_config"]["modifiers"]
        bagel_type_modifier = next(
            (m for m in modifiers if m["name"].lower() == "plain"),
            None
        )
        assert bagel_type_modifier is not None, "Plain should be in modifiers"
        assert bagel_type_modifier["price"] == 0.0, "Plain bagel should have $0 upcharge"

        # Display name should be "Bagel" (not "plain bagel")
        assert item["display_name"] == "Bagel"
