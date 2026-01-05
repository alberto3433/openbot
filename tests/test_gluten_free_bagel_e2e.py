"""
End-to-end tests for gluten free bagel ordering with upcharge.

Tests the complete flow from ordering to final price calculation,
verifying the gluten free upcharge is properly applied and displayed.
"""

from sandwich_bot.tasks.state_machine import OrderStateMachine
from sandwich_bot.tasks.models import OrderTask, BagelItemTask, SpeedMenuBagelItemTask
from sandwich_bot.tasks.adapter import order_task_to_dict
from sandwich_bot.tasks.pricing import PricingEngine


def create_test_menu_data():
    """Create minimal menu data for gluten free bagel tests."""
    return {
        "all_items": [
            {"id": 1, "name": "Bagel", "base_price": 2.20, "category": "custom_bagels"},
            {"id": 2, "name": "Gluten Free Bagel", "base_price": 3.00, "category": "custom_bagels"},
            {"id": 3, "name": "Plain Bagel", "base_price": 2.20, "category": "custom_bagels"},
            {"id": 4, "name": "Everything Bagel", "base_price": 2.20, "category": "custom_bagels"},
            {"id": 5, "name": "The Classic BEC", "base_price": 9.50, "category": "signature_sandwiches"},
        ],
        "custom_bagels": [
            {"id": 1, "name": "Bagel", "base_price": 2.20},
            {"id": 2, "name": "Gluten Free Bagel", "base_price": 3.00},
            {"id": 3, "name": "Plain Bagel", "base_price": 2.20},
            {"id": 4, "name": "Everything Bagel", "base_price": 2.20},
        ],
        "signature_sandwiches": [
            {"id": 5, "name": "The Classic BEC", "base_price": 9.50, "requires_bagel_choice": True},
        ],
        "bagels": {
            "plain": {"id": 3, "name": "Plain Bagel", "base_price": 2.20},
            "everything": {"id": 4, "name": "Everything Bagel", "base_price": 2.20},
            "gluten free": {"id": 2, "name": "Gluten Free Bagel", "base_price": 3.00},
        },
        # Item types with attribute options for pricing lookups
        "item_types": {
            "bagel": {
                "attributes": [
                    {
                        "slug": "bagel_type",
                        "options": [
                            {"slug": "plain", "display_name": "Plain", "price_modifier": 0.0},
                            {"slug": "everything", "display_name": "Everything", "price_modifier": 0.0},
                            {"slug": "sesame", "display_name": "Sesame", "price_modifier": 0.0},
                            {"slug": "gluten_free", "display_name": "Gluten Free", "price_modifier": 0.80},
                        ]
                    },
                    {
                        "slug": "spread",
                        "options": [
                            {"slug": "cream_cheese", "display_name": "Cream Cheese", "price_modifier": 1.50},
                            {"slug": "butter", "display_name": "Butter", "price_modifier": 0.50},
                        ]
                    },
                ]
            },
        },
    }


class TestGlutenFreeBagelE2E:
    """End-to-end tests for gluten free bagel ordering."""

    def test_order_gluten_free_bagel_direct(self):
        """
        Test: User orders a gluten free bagel directly.

        Scenario:
        - User says: "I'd like a gluten free bagel"
        - System asks: "Would you like that toasted?"
        - User says: "yes please"
        - Expected: Bagel has gluten free type with $0.80 upcharge
        """
        menu_data = create_test_menu_data()
        order = OrderTask()
        sm = OrderStateMachine(menu_data=menu_data)

        # User orders gluten free bagel
        result = sm.process("I'd like a gluten free bagel", order)

        # Should ask about toasted
        assert "toast" in result.message.lower(), f"Should ask about toasting. Message: {result.message}"

        # User says yes to toasted
        result = sm.process("yes please", result.order)

        # Verify bagel was added with correct attributes
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]
        assert len(bagels) == 1, "Should have 1 bagel"

        bagel = bagels[0]
        assert bagel.bagel_type == "gluten free", f"Should be gluten free, got: {bagel.bagel_type}"
        assert bagel.toasted is True, "Should be toasted"
        assert bagel.bagel_type_upcharge == 0.80, f"Should have $0.80 upcharge, got: {bagel.bagel_type_upcharge}"

        # Verify price includes upcharge ($2.20 base + $0.80 upcharge = $3.00)
        assert bagel.unit_price == 3.00, f"Unit price should be $3.00, got: {bagel.unit_price}"

    def test_order_gluten_free_bagel_with_spread(self):
        """
        Test: User orders gluten free bagel with cream cheese.

        Scenario:
        - User says: "one gluten free bagel with cream cheese toasted"
        - Expected: $2.20 base + $0.80 gluten free + $1.50 cream cheese = $4.50
        """
        menu_data = create_test_menu_data()
        order = OrderTask()
        sm = OrderStateMachine(menu_data=menu_data)

        # User orders gluten free bagel with spread and toasted (explicit "one" to avoid quantity parsing)
        result = sm.process("one gluten free bagel with cream cheese toasted", order)

        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]
        assert len(bagels) == 1, f"Should have 1 bagel, got {len(bagels)}"

        bagel = bagels[0]
        assert bagel.bagel_type == "gluten free", f"Should be gluten free, got: {bagel.bagel_type}"
        assert bagel.toasted is True, "Should be toasted"
        assert bagel.spread == "cream cheese", f"Should have cream cheese, got: {bagel.spread}"
        assert bagel.bagel_type_upcharge == 0.80, f"Should have $0.80 upcharge, got: {bagel.bagel_type_upcharge}"

        # $2.20 base + $0.80 gluten free + $1.50 cream cheese = $4.50
        expected_price = 4.50
        assert abs(bagel.unit_price - expected_price) < 0.01, f"Unit price should be ${expected_price}, got: {bagel.unit_price}"

    def test_gluten_free_bagel_adapter_output(self):
        """
        Test: Verify adapter output shows gluten free as modifier with upcharge.

        The adapter should output:
        - display_name: "Bagel"
        - modifiers: [{"name": "Gluten Free", "price": 0.80}, ...]
        """
        menu_data = create_test_menu_data()

        def menu_lookup(name: str):
            for item in menu_data["all_items"]:
                if item["name"].lower() == name.lower():
                    return item
            return None

        pricing = PricingEngine(menu_data=menu_data, menu_lookup_func=menu_lookup)

        order = OrderTask()
        bagel = BagelItemTask(
            bagel_type="gluten free",
            bagel_type_upcharge=0.80,
            toasted=True,
            spread="cream cheese",
            unit_price=4.50,
        )
        bagel.mark_complete()
        order.items.add_item(bagel)

        result = order_task_to_dict(order, pricing=pricing)
        item = result["items"][0]

        # Display name should be "Bagel" (not "gluten free bagel")
        assert item["display_name"] == "Bagel", f"Display name should be 'Bagel', got: {item['display_name']}"

        # Gluten free should be in modifiers with $0.80 price
        modifiers = item["item_config"]["modifiers"]
        gluten_free_mod = next((m for m in modifiers if "gluten" in m["name"].lower()), None)
        assert gluten_free_mod is not None, "Gluten free should be in modifiers"
        assert gluten_free_mod["price"] == 0.80, f"Gluten free upcharge should be $0.80, got: {gluten_free_mod['price']}"

        # Verify base_price + modifiers = line_total
        base_price = item["item_config"]["base_price"]
        modifiers_total = sum(m["price"] for m in modifiers)
        calculated_total = base_price + modifiers_total
        assert abs(calculated_total - item["line_total"]) < 0.01, \
            f"base_price ({base_price}) + modifiers ({modifiers_total}) should equal line_total ({item['line_total']})"

    def test_regular_bagel_no_upcharge(self):
        """
        Test: Regular bagel (plain) should not have upcharge.

        Scenario:
        - User orders: "plain bagel toasted"
        - Expected: No upcharge, base price only
        """
        menu_data = create_test_menu_data()
        order = OrderTask()
        sm = OrderStateMachine(menu_data=menu_data)

        result = sm.process("plain bagel toasted", order)

        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]
        assert len(bagels) == 1, "Should have 1 bagel"

        bagel = bagels[0]
        assert bagel.bagel_type == "plain", f"Should be plain, got: {bagel.bagel_type}"
        assert bagel.bagel_type_upcharge == 0.0, f"Should have no upcharge, got: {bagel.bagel_type_upcharge}"

        # $2.20 base, no upcharge
        assert bagel.unit_price == 2.20, f"Unit price should be $2.20, got: {bagel.unit_price}"

    def test_regular_bagel_adapter_shows_type_as_modifier(self):
        """
        Test: Regular bagel type should still show as modifier (with $0 price).
        """
        menu_data = create_test_menu_data()

        def menu_lookup(name: str):
            for item in menu_data["all_items"]:
                if item["name"].lower() == name.lower():
                    return item
            return None

        pricing = PricingEngine(menu_data=menu_data, menu_lookup_func=menu_lookup)

        order = OrderTask()
        bagel = BagelItemTask(
            bagel_type="everything",
            bagel_type_upcharge=0.0,
            toasted=True,
            unit_price=2.20,
        )
        bagel.mark_complete()
        order.items.add_item(bagel)

        result = order_task_to_dict(order, pricing=pricing)
        item = result["items"][0]

        # Display name should be "Bagel"
        assert item["display_name"] == "Bagel"

        # Everything should be in modifiers with $0 price
        modifiers = item["item_config"]["modifiers"]
        type_mod = next((m for m in modifiers if m["name"].lower() == "everything"), None)
        assert type_mod is not None, "Everything should be in modifiers"
        assert type_mod["price"] == 0.0, f"Everything should have $0 upcharge, got: {type_mod['price']}"


class TestGlutenFreeSpeedMenuE2E:
    """End-to-end tests for gluten free bagel choice on speed menu items."""

    def test_bec_with_gluten_free_bagel_choice(self):
        """
        Test: User orders BEC and chooses gluten free bagel.

        Scenario:
        - User says: "I want a BEC"
        - System asks about cheese, bagel type, toasted
        - User picks gluten free
        - Expected: BEC price + $0.80 upcharge
        """
        menu_data = create_test_menu_data()
        order = OrderTask()
        sm = OrderStateMachine(menu_data=menu_data)

        # User orders BEC
        result = sm.process("I want a classic BEC", order)

        # Find the speed menu item
        speed_items = [i for i in result.order.items.items if isinstance(i, SpeedMenuBagelItemTask)]
        assert len(speed_items) == 1, f"Should have 1 speed menu item, got {len(speed_items)}"

        # Answer cheese question if asked
        if "cheese" in result.message.lower():
            result = sm.process("american", result.order)

        # Answer bagel type question
        if "bagel" in result.message.lower() or "type" in result.message.lower():
            result = sm.process("gluten free", result.order)

        # Answer toasted question
        if "toast" in result.message.lower():
            result = sm.process("yes", result.order)

        # Verify gluten free upcharge applied
        speed_items = [i for i in result.order.items.items if isinstance(i, SpeedMenuBagelItemTask)]
        assert len(speed_items) == 1

        item = speed_items[0]
        assert item.bagel_choice == "gluten free", f"Bagel choice should be gluten free, got: {item.bagel_choice}"
        assert item.bagel_choice_upcharge == 0.80, f"Should have $0.80 upcharge, got: {item.bagel_choice_upcharge}"

    def test_speed_menu_with_regular_bagel_no_upcharge(self):
        """
        Test: Speed menu item with regular bagel has no upcharge.
        """
        menu_data = create_test_menu_data()
        order = OrderTask()
        sm = OrderStateMachine(menu_data=menu_data)

        # User orders BEC
        result = sm.process("I want a classic BEC", order)

        # Answer cheese question if asked
        if "cheese" in result.message.lower():
            result = sm.process("american", result.order)

        # Answer bagel type with regular bagel
        if "bagel" in result.message.lower() or "type" in result.message.lower():
            result = sm.process("plain", result.order)

        # Answer toasted question
        if "toast" in result.message.lower():
            result = sm.process("yes", result.order)

        # Verify no upcharge for plain bagel
        speed_items = [i for i in result.order.items.items if isinstance(i, SpeedMenuBagelItemTask)]
        assert len(speed_items) == 1

        item = speed_items[0]
        assert item.bagel_choice == "plain", f"Bagel choice should be plain, got: {item.bagel_choice}"
        assert item.bagel_choice_upcharge == 0.0, f"Should have no upcharge, got: {item.bagel_choice_upcharge}"

    def test_speed_menu_gluten_free_adapter_output(self):
        """
        Test: Speed menu item with gluten free bagel shows upcharge in adapter output.
        """
        order = OrderTask()

        # Create a completed speed menu item with gluten free
        item = SpeedMenuBagelItemTask(
            menu_item_name="The Classic BEC",
            menu_item_id=123,  # Integer ID
            toasted=True,
            bagel_choice="gluten free",
            bagel_choice_upcharge=0.80,
            cheese_choice="american",
            unit_price=10.80,  # $10.00 base + $0.80 gluten free
        )
        item.mark_complete()
        order.items.add_item(item)

        result = order_task_to_dict(order)
        order_item = result["items"][0]

        # Should have modifiers including bagel choice with upcharge
        modifiers = order_item["item_config"]["modifiers"]
        bagel_mod = next((m for m in modifiers if "gluten" in m["name"].lower()), None)
        assert bagel_mod is not None, "Gluten free bagel should be in modifiers"
        assert bagel_mod["price"] == 0.80, f"Gluten free upcharge should be $0.80, got: {bagel_mod['price']}"


class TestPricingEngineGlutenFreeFromDatabase:
    """Test PricingEngine gluten free lookups from database (menu_data)."""

    def create_menu_data_with_bagel_types(self):
        """Create menu_data with bagel type attribute options."""
        return {
            "item_types": {
                "bagel": {
                    "attributes": [
                        {
                            "slug": "bagel_type",
                            "options": [
                                {"slug": "plain", "display_name": "Plain", "price_modifier": 0.0},
                                {"slug": "everything", "display_name": "Everything", "price_modifier": 0.0},
                                {"slug": "sesame", "display_name": "Sesame", "price_modifier": 0.0},
                                {"slug": "gluten_free", "display_name": "Gluten Free", "price_modifier": 0.80},
                            ]
                        }
                    ]
                }
            },
            "all_items": [{"name": "Bagel", "base_price": 2.20}],
        }

    def test_bagel_type_upcharges_gluten_free(self):
        """Test that gluten free upcharge is $0.80 from database."""
        menu_data = self.create_menu_data_with_bagel_types()

        def menu_lookup(name: str):
            for item in menu_data["all_items"]:
                if item["name"].lower() == name.lower():
                    return item
            return None

        pricing = PricingEngine(menu_data=menu_data, menu_lookup_func=menu_lookup)

        # Test gluten free variations
        assert pricing.get_bagel_type_upcharge("gluten free") == 0.80
        assert pricing.get_bagel_type_upcharge("gluten-free") == 0.80

    def test_bagel_type_upcharges_regular(self):
        """Test that regular bagels have no upcharge from database."""
        menu_data = self.create_menu_data_with_bagel_types()

        def menu_lookup(name: str):
            for item in menu_data["all_items"]:
                if item["name"].lower() == name.lower():
                    return item
            return None

        pricing = PricingEngine(menu_data=menu_data, menu_lookup_func=menu_lookup)

        # Regular bagels should have $0 upcharge
        assert pricing.get_bagel_type_upcharge("plain") == 0.0
        assert pricing.get_bagel_type_upcharge("everything") == 0.0
        assert pricing.get_bagel_type_upcharge("sesame") == 0.0
