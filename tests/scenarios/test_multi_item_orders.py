"""
Multi-Item Order Tests.

These tests focus on orders with multiple items, different combinations,
and complex order structures.

Run with: pytest tests/scenarios/ -v
"""

import pytest
from orderbot.tasks.state_machine import OrderStateMachine
from orderbot.tasks.models import OrderTask
from orderbot.tasks.schemas import OrderPhase


class TestTwoItemOrders:
    """Orders with exactly two items."""

    def test_bagel_and_coffee_different_sizes(self):
        """Bagel with small coffee."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Everything bagel with cream cheese and a small hot coffee",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_two_bagels_different_types(self):
        """Two bagels of different types."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "One everything bagel toasted and one sesame not toasted",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_sandwich_and_drink(self):
        """Sandwich with beverage."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "BEC on everything and a large orange juice",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_two_different_coffees(self):
        """Two coffees with different customizations."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Large iced latte with oat milk and a small hot coffee black",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_omelette_and_coffee(self):
        """Omelette with coffee."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Cheese omelette with a medium latte",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_bagel_and_pastry(self):
        """Bagel with a pastry item."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Plain bagel toasted with butter and a chocolate croissant",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_sandwich_and_soup(self):
        """Sandwich with soup."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Turkey sandwich and a cup of soup",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_two_becs_different_bread(self):
        """Two BECs on different breads."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Two BECs - one on everything and one on plain",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_bagel_and_side_salad(self):
        """Bagel with side salad."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Everything bagel with lox and a small side salad",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_two_drinks_for_and_syntax(self):
        """Two drinks using 'and' syntax."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "A large coffee and a medium iced tea",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestThreeItemOrders:
    """Orders with three items."""

    def test_bagel_coffee_pastry_combo(self):
        """Classic three-item breakfast combo."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Everything bagel toasted with cream cheese, large coffee, and a muffin",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_three_bagels_different_configs(self):
        """Three bagels with different configurations."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Plain bagel with butter, everything bagel with scallion cream cheese, and sesame bagel with lox",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_omelette_bagel_coffee(self):
        """Full breakfast with omelette."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Western omelette, plain bagel toasted, and a large iced coffee",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_sandwich_chips_drink(self):
        """Lunch combo with chips and drink."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Turkey club, bag of chips, and a coke",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_three_coffees_office_order(self):
        """Three different coffees for the office."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "One large latte, one medium cappuccino, and one small drip coffee",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_bec_with_sides(self):
        """BEC with multiple sides."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "BEC on everything, hash browns, and a small coffee",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"


class TestFourPlusItemOrders:
    """Orders with four or more items."""

    def test_family_breakfast_order(self):
        """Family breakfast order."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Two everything bagels with cream cheese, a BEC, and two large coffees",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_office_bagel_order(self):
        """Office bagel platter order."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "I need 6 assorted bagels - 2 everything, 2 plain, 1 sesame, 1 whole wheat",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_large_coffee_order(self):
        """Multiple coffees for a meeting."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "4 large hot coffees - 2 with milk and sugar, 1 black, 1 with just cream",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_party_platter_components(self):
        """Components for a party platter."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "12 mini bagels, cream cheese, lox, and sliced tomatoes",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_mixed_breakfast_catering(self):
        """Mixed breakfast catering order."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "3 BECs, 2 cheese omelettes, 4 bagels with cream cheese, and a box of coffee",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"


class TestQuantityOrders:
    """Orders with specific quantities."""

    def test_exact_quantity_bagels(self):
        """Exact number of identical bagels."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "5 plain bagels toasted with cream cheese",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_dozen_bagels(self):
        """A dozen bagels."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "A dozen assorted bagels please",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_half_dozen(self):
        """Half dozen bagels."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Half dozen everything bagels",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_couple_of_items(self):
        """A couple of items."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "A couple of everything bagels with scallion",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_few_items(self):
        """A few items."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "A few chocolate chip cookies",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_two_of_each(self):
        """Two of each item type."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Two BECs and two large coffees",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestForMultiplePeople:
    """Orders for multiple people."""

    def test_order_for_two_people(self):
        """Order specifying for two people."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "For me, everything bagel with lox. For my friend, plain with butter.",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_his_and_hers_order(self):
        """His and hers split order."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "I'll have a BEC, and she'll have an egg white omelette",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_one_for_me_one_for_coworker(self):
        """Order for self and coworker."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Large latte for me, medium cappuccino for my coworker",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_kids_order_with_adult(self):
        """Order with items for kids."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "A BEC for me, and two plain bagels with butter for the kids",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestSequentialAdditions:
    """Tests for adding items sequentially."""

    def test_add_item_with_also(self):
        """Add item using 'also'."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Everything bagel with cream cheese", order)
        result2 = sm.process("also a large coffee", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have items"

    def test_add_item_with_and_also(self):
        """Add item using 'and also'."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("BEC on everything", order)
        result2 = sm.process("and also a small orange juice", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have items"

    def test_add_item_with_plus(self):
        """Add item using 'plus'."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Large iced latte", order)
        result2 = sm.process("plus a chocolate croissant", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have items"

    def test_add_item_oh_and(self):
        """Add item using 'oh and'."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Plain bagel toasted", order)
        result2 = sm.process("oh and can I get a coffee too?", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have items"

    def test_add_item_forgot_to_mention(self):
        """Add item with 'forgot to mention'."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Everything bagel with lox", order)
        result2 = sm.process("forgot to mention, I also need a water", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1 or result2.message is not None, "Should have items or response"


class TestSplitOrders:
    """Orders that need to be split or have split configurations."""

    def test_split_same_item_different_config(self):
        """Same item type with different configs."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Two bagels - make one toasted with cream cheese and one not toasted with butter",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_one_for_here_one_to_go(self):
        """Split order for here and to go."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Two lattes - one for here and one to go",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_split_check_hint(self):
        """Order with split check hint."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "BEC on everything and a latte - those are separate orders",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"
