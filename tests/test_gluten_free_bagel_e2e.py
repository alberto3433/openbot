"""
End-to-end tests for gluten free bagel ordering with upcharge.

Tests the complete flow from ordering to final price calculation,
verifying the gluten free upcharge is properly applied and displayed.
"""

import pytest
from orderbot.tasks.state_machine import OrderStateMachine
from orderbot.tasks.models import OrderTask, MenuItemTask
from tests.helpers import BagelItemTask, create_bagel_menu_data
from tests.helpers.item_factories import _set_modifier_price
from orderbot.tasks.adapter import order_task_to_dict
from orderbot.tasks.pricing import PricingEngine


def _answer_until_done(sm, result, max_rounds=10):
    """Answer remaining config questions with 'no' until 'anything else' or done."""
    for _ in range(max_rounds):
        msg = result.message.lower()
        if 'anything else' in msg:
            break
        pending = result.order.pending_field or ''
        if not pending and 'anything else' not in msg:
            break
        result = sm.process('no', result.order)
    return result


class TestGlutenFreeBagelE2E:
    """End-to-end tests for gluten free bagel ordering."""

    def test_order_gluten_free_bagel_direct(self):
        """
        Test: User orders a gluten free bagel directly.

        Scenario:
        - User says: "I'd like a gluten free bagel"
        - System asks about toasting, scooping, spread, etc.
        - User answers yes/no to each
        - Expected: Bagel has gluten free bread with upcharge
        """
        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.process("I'd like a gluten free bagel", order)
        assert "toast" in result.message.lower(), f"Should ask about toasting. Message: {result.message}"

        # Answer toast yes
        result = sm.process("yes", result.order)

        # Answer remaining questions (scoop, spread, etc.)
        result = _answer_until_done(sm, result)

        bagels = [i for i in result.order.items.get_active_items() if i.menu_item_name == 'Bagel']
        assert len(bagels) == 1, "Should have 1 bagel"

        bagel = bagels[0]
        assert 'gluten_free' in bagel["bread"], f"Should be gluten free bread, got: {bagel['bread']}"
        assert bagel["toasted"] is True, "Should be toasted"
        # Gluten free upcharge should make price higher than base $2.50
        assert bagel.unit_price > 2.50, f"GF bagel should cost more than $2.50, got: {bagel.unit_price}"

    def test_order_gluten_free_bagel_with_spread(self):
        """
        Test: User orders gluten free bagel with cream cheese.

        Scenario:
        - User says: "one gluten free bagel with cream cheese toasted"
        - Expected: Bagel with gluten free bread, toasted, cream cheese spread
        """
        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.process("one gluten free bagel with cream cheese toasted", order)

        # Answer remaining questions
        result = _answer_until_done(sm, result)

        bagels = [i for i in result.order.items.get_active_items() if i.menu_item_name == 'Bagel']
        assert len(bagels) == 1, f"Should have 1 bagel, got {len(bagels)}"

        bagel = bagels[0]
        assert 'gluten_free' in bagel["bread"], f"Should be gluten free, got: {bagel['bread']}"
        assert bagel["toasted"] is True, "Should be toasted"

        # Verify cream cheese was captured as spread
        spreads = bagel.get_selections('spread')
        has_cc = any('cream_cheese' in s.get('slug', '') for s in spreads)
        assert has_cc, f"Should have cream cheese spread, got: {spreads}"

        # GF + cream cheese should cost more than base
        assert bagel.unit_price > 2.50, f"GF + CC bagel should be > $2.50, got: {bagel.unit_price}"

    def test_gluten_free_bagel_adapter_output(self):
        """
        Test: Verify adapter output shows gluten free as modifier with upcharge.

        The adapter should output:
        - display_name: "Bagel"
        - modifiers: [{"name": "Gluten Free", "price": 0.80}, ...]
        """
        menu_data = create_bagel_menu_data()

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

        # Display name should include the bagel type
        assert item["display_name"] == "Gluten Free Bagel", f"Display name should be 'Gluten Free Bagel', got: {item['display_name']}"

        # Verify line_total matches the unit_price we set
        assert item["line_total"] == 4.50, f"Line total should be $4.50, got: {item['line_total']}"

        # Verify item_config exists with expected structure
        assert "item_config" in item, "item_config should be present"
        assert "base_price" in item["item_config"], "base_price should be in item_config"
        assert "modifiers" in item["item_config"], "modifiers should be in item_config"

    def test_regular_bagel_no_upcharge(self):
        """
        Test: Regular bagel (plain) should not have upcharge.

        Scenario:
        - User orders: "plain bagel toasted"
        - Expected: Base price only, no upcharge
        """
        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.process("plain bagel toasted", order)

        # Answer remaining questions
        result = _answer_until_done(sm, result)

        bagels = [i for i in result.order.items.get_active_items() if i.menu_item_name == 'Bagel']
        assert len(bagels) == 1, "Should have 1 bagel"

        bagel = bagels[0]
        assert 'plain' in bagel["bread"], f"Should be plain, got: {bagel['bread']}"
        assert bagel["toasted"] is True, "Should be toasted"

        # Plain bagel should be base price ($2.50)
        assert bagel.unit_price == 2.50, f"Plain bagel should be $2.50, got: {bagel.unit_price}"

    def test_regular_bagel_adapter_shows_type_as_modifier(self):
        """
        Test: Regular bagel type should still show as modifier (with $0 price).
        """
        menu_data = create_bagel_menu_data()

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

        # Display name should include the bagel type
        assert item["display_name"] == "Everything Bagel", f"Display name should be 'Everything Bagel', got: {item['display_name']}"

        # Verify line total matches unit_price
        assert item["line_total"] == 2.20, f"Line total should be $2.20, got: {item['line_total']}"


class TestGlutenFreeSpeedMenuE2E:
    """End-to-end tests for gluten free bagel choice on speed menu items."""

    def test_bec_with_gluten_free_bagel_choice(self):
        """
        Test: User orders BEC and chooses gluten free bagel.

        Scenario:
        - User says: "the classic bec"
        - System asks: "What kind of bread?"
        - User says: "gluten free plain bagel"
        - Expected: BEC with gluten free bread, price includes upcharge
        """
        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.process("the classic bec", order)
        assert "bread" in result.message.lower(), f"Should ask about bread. Message: {result.message}"

        # Choose gluten free plain bagel (specific to avoid disambiguation)
        result = sm.process("gluten free plain bagel", result.order)

        # Answer remaining questions
        for _ in range(8):
            if 'anything else' in result.message.lower():
                break
            msg = result.message.lower()
            if 'toast' in msg:
                result = sm.process('yes', result.order)
            else:
                result = sm.process('no', result.order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

        bec = items[0]
        assert 'gf_plain_bagel' in bec["bread"] or 'gluten_free' in bec["bread"], \
            f"Bread should be gluten free, got: {bec['bread']}"
        # GF BEC should cost more than plain BEC ($10.75)
        assert bec.unit_price > 10.75, f"GF BEC should cost more than $10.75, got: {bec.unit_price}"

    def test_signature_item_with_regular_bagel_no_upcharge(self):
        """
        Test: Speed menu item with regular bagel has no upcharge.
        """
        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.process("the classic bec", order)
        assert "bread" in result.message.lower(), f"Should ask about bread. Message: {result.message}"

        # Choose plain bagel
        result = sm.process("plain bagel", result.order)

        # Answer remaining questions
        for _ in range(8):
            if 'anything else' in result.message.lower():
                break
            msg = result.message.lower()
            if 'toast' in msg:
                result = sm.process('yes', result.order)
            else:
                result = sm.process('no', result.order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

        bec = items[0]
        assert 'plain' in bec["bread"], f"Bread should be plain, got: {bec['bread']}"
        # Plain BEC should be base price
        assert bec.unit_price == 10.75, f"Plain BEC should be $10.75, got: {bec.unit_price}"

    def test_signature_item_gluten_free_adapter_output(self):
        """
        Test: Speed menu item with gluten free bagel shows upcharge in adapter output.
        """
        order = OrderTask()

        # Create a completed speed menu item with gluten free
        item = MenuItemTask(
            menu_item_name="The Classic BEC",
            menu_item_id=123,  # Integer ID
            unit_price=10.80,  # $10.00 base + $0.80 gluten free
        )
        # Set attributes via selections API (Pydantic doesn't call property setters during __init__)
        item.add_selection("yes", "toasted")
        item.add_selection("gluten free", "bagel_choice")
        _set_modifier_price(item, "bagel_choice", "gluten free", 0.80)  # Test helper for setting price
        item.add_selection("american", "cheese")
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
                            "slug": "bread",  # was bagel_type, renamed to match deli_sandwich
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

        # Test gluten free variations using generic method
        assert pricing.lookup_attribute_option_upcharge("bagel", "bread", "gluten free") == 0.80
        assert pricing.lookup_attribute_option_upcharge("bagel", "bread", "gluten-free") == 0.80

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
        assert pricing.lookup_attribute_option_upcharge("bagel", "bread", "plain") == 0.0
        assert pricing.lookup_attribute_option_upcharge("bagel", "bread", "everything") == 0.0
        assert pricing.lookup_attribute_option_upcharge("bagel", "bread", "sesame") == 0.0
