"""
Stress Test Scenarios.

These tests focus on high-complexity orders, rapid changes, edge cases
under load, and scenarios that push the system's limits.

Run with: pytest tests/scenarios/ -v
"""

import pytest


class TestLargeOrders:
    """Tests for large quantity orders."""

    def test_dozen_bagels_assorted(self, order_and_sm):
        """Order a dozen assorted bagels."""
        order, sm = order_and_sm

        result = sm.process(
            "I need a dozen bagels - 4 everything, 4 plain, 2 sesame, 2 whole wheat",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should handle large order"

    def test_office_order_10_coffees(self, order_and_sm):
        """Order 10 coffees for the office."""
        order, sm = order_and_sm

        result = sm.process(
            "10 large hot coffees - 5 with milk and sugar, 3 black, 2 with just cream",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should handle large order"

    def test_catering_order(self, order_and_sm):
        """Large catering-style order."""
        order, sm = order_and_sm

        result = sm.process(
            "For a meeting: 10 assorted bagels, a tub of cream cheese, "
            "6 large coffees, and a dozen cookies",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should handle large order"

    def test_multiple_sandwiches(self, order_and_sm):
        """Order multiple sandwiches."""
        order, sm = order_and_sm

        result = sm.process(
            "5 BECs on everything, 3 turkey sandwiches, and 2 cheese omelettes",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should handle large order"

    def test_party_order(self, order_and_sm):
        """Party-sized order."""
        order, sm = order_and_sm

        result = sm.process(
            "I need 20 bagels assorted, 2 tubs of cream cheese, "
            "lox platter, and a box of coffee",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should handle large order"


class TestRapidModifications:
    """Tests for rapid successive modifications."""

    def test_three_changes_in_row(self, order_and_sm):
        """Three changes in rapid succession."""
        order, sm = order_and_sm

        result1 = sm.process("Sesame bagel", order)
        result2 = sm.process("plain", result1.order)
        result3 = sm.process("everything", result2.order)
        result4 = sm.process("sesame actually", result3.order)

        items = result4.order.items.get_active_items()
        assert len(items) >= 1, "Should handle rapid changes"

    def test_add_remove_add(self, order_and_sm):
        """Add, remove, then add again."""
        order, sm = order_and_sm

        result1 = sm.process("BEC on everything", order)
        result2 = sm.process("add avocado", result1.order)
        result3 = sm.process("remove avocado", result2.order)
        result4 = sm.process("add avocado back", result3.order)

        items = result4.order.items.get_active_items()
        assert len(items) >= 1, "Should handle rapid changes"

    def test_size_changes(self, order_and_sm):
        """Multiple size changes."""
        order, sm = order_and_sm

        result1 = sm.process("Small latte", order)
        result2 = sm.process("make it medium", result1.order)
        result3 = sm.process("large actually", result2.order)

        items = result3.order.items.get_active_items()
        assert len(items) >= 1, "Should handle size changes"

    def test_hot_iced_hot(self, order_and_sm):
        """Toggle between hot and iced."""
        order, sm = order_and_sm

        result1 = sm.process("Hot latte", order)
        result2 = sm.process("make it iced", result1.order)
        result3 = sm.process("no wait, hot", result2.order)

        items = result3.order.items.get_active_items()
        assert len(items) >= 1, "Should handle temperature changes"


class TestComplexModifierCombinations:
    """Tests for complex modifier combinations."""

    def test_many_modifiers_bagel(self, order_and_sm):
        """Bagel with many modifiers."""
        order, sm = order_and_sm

        result = sm.process(
            "Everything bagel toasted, scooped, with extra cream cheese, "
            "lox, capers, red onion, tomato, and a little bit of dill",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should handle many modifiers"

    def test_many_modifiers_coffee(self, order_and_sm):
        """Coffee with many customizations."""
        order, sm = order_and_sm

        result = sm.process(
            "Large iced latte with oat milk, extra shot, vanilla syrup, "
            "caramel drizzle, light ice, and whipped cream",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should handle many modifiers"

    def test_modifiers_with_quantities(self, order_and_sm):
        """Modifiers with specific quantities."""
        order, sm = order_and_sm

        result = sm.process(
            "Medium coffee with 2 creams, 3 sugars, and 1 shot of vanilla",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should handle modifier quantities"

    def test_contradicting_modifiers(self, order_and_sm):
        """Seemingly contradicting modifiers."""
        order, sm = order_and_sm

        result = sm.process(
            "Decaf coffee with an extra shot of espresso",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should handle or clarify"


class TestComplexMultiItemOrders:
    """Tests for complex orders with multiple items."""

    def test_five_items_different_types(self, order_and_sm):
        """Five items of different types."""
        order, sm = order_and_sm

        result = sm.process(
            "Everything bagel with lox, BEC on plain, large iced latte, "
            "cheese omelette, and a chocolate chip cookie",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should handle multiple items"

    def test_same_item_different_configs(self, order_and_sm):
        """Same item with different configurations."""
        order, sm = order_and_sm

        result = sm.process(
            "3 lattes - one large hot with oat milk, one medium iced with almond, "
            "one small hot regular milk",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should handle different configs"

    def test_mixed_quantities(self, order_and_sm):
        """Mixed quantities of items."""
        order, sm = order_and_sm

        result = sm.process(
            "2 everything bagels with cream cheese, 1 BEC, 3 large coffees, "
            "and 4 cookies",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should handle mixed quantities"


class TestLongConversations:
    """Tests for extended conversations."""

    def test_ten_turn_conversation(self, order_and_sm):
        """Ten-turn ordering conversation."""
        order, sm = order_and_sm

        # Turn 1-2
        result1 = sm.process("let me get an everything bagel", order)
        result2 = sm.process("toasted yes", result1.order)

        # Turn 3-4
        result3 = sm.process("scallion cream cheese", result2.order)
        result4 = sm.process("add lox", result3.order)

        # Turn 5-6
        result5 = sm.process("and a coffee", result4.order)
        result6 = sm.process("large", result5.order)

        # Turn 7-8
        result7 = sm.process("hot please", result6.order)
        result8 = sm.process("with oat milk", result7.order)

        # Turn 9-10
        result9 = sm.process("add another bagel plain with butter", result8.order)
        result10 = sm.process("yes toasted", result9.order)

        items = result10.order.items.get_active_items()
        assert len(items) >= 1, "Should complete long conversation"

    def test_conversation_with_many_corrections(self, order_and_sm):
        """Conversation with multiple corrections."""
        order, sm = order_and_sm

        result1 = sm.process("Plain bagel", order)
        result2 = sm.process("make it everything", result1.order)
        result3 = sm.process("toasted", result2.order)
        result4 = sm.process("with cream cheese", result3.order)
        result5 = sm.process("scallion cream cheese I mean", result4.order)
        result6 = sm.process("and add lox", result5.order)
        result7 = sm.process("no wait remove the lox", result6.order)
        result8 = sm.process("add bacon instead", result7.order)

        items = result8.order.items.get_active_items()
        assert len(items) >= 1, "Should handle many corrections"


class TestBoundaryConditions:
    """Tests for boundary conditions."""

    def test_very_long_input(self, order_and_sm):
        """Very long input string."""
        order, sm = order_and_sm

        long_input = (
            "I would like to order an everything bagel that is toasted with "
            "scallion cream cheese and also some lox and capers and red onion "
            "and tomato and I also want a large iced latte with oat milk and "
            "an extra shot of espresso and vanilla syrup " * 3
        )

        result = sm.process(long_input, order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should handle long input"

    def test_special_characters(self, order_and_sm):
        """Input with special characters."""
        order, sm = order_and_sm

        result = sm.process("Everything bagel - toasted! With cream cheese...", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should handle special characters"

    def test_numbers_and_text_mixed(self, order_and_sm):
        """Mixed numbers and text."""
        order, sm = order_and_sm

        result = sm.process("2 bagels, 3 coffees, and 1 BEC", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should handle mixed numbers"


class TestRecoveryScenarios:
    """Tests for error recovery scenarios."""

    def test_recover_from_unclear_input(self, order_and_sm):
        """Recover from unclear input."""
        order, sm = order_and_sm

        result1 = sm.process("give me a thing", order)
        result2 = sm.process("an everything bagel", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should recover from unclear input"

    def test_recover_after_cancel(self, order_and_sm):
        """Recover after canceling everything."""
        order, sm = order_and_sm

        result1 = sm.process("Everything bagel with lox", order)
        result2 = sm.process("cancel everything", result1.order)
        result3 = sm.process("start fresh - plain bagel with butter", result2.order)

        items = result3.order.items.get_active_items()
        assert len(items) >= 1 or result3.message is not None, "Should recover"


class TestConcurrentItems:
    """Tests for handling concurrent item configuration."""

    def test_configure_two_items_interleaved(self, order_and_sm):
        """Configure two items with interleaved answers."""
        order, sm = order_and_sm

        result1 = sm.process("bagel and coffee", order)
        result2 = sm.process("everything for the bagel, large for the coffee", result1.order)
        result3 = sm.process("toasted, hot", result2.order)

        items = result3.order.items.get_active_items()
        assert len(items) >= 1, "Should handle interleaved config"

    def test_specify_item_when_multiple_pending(self, order_and_sm):
        """Specify which item to configure when multiple pending."""
        order, sm = order_and_sm

        result1 = sm.process("2 bagels and 2 coffees", order)
        result2 = sm.process("the first bagel is everything", result1.order)
        result3 = sm.process("second bagel is plain", result2.order)

        items = result3.order.items.get_active_items()
        assert len(items) >= 1, "Should handle specific references"


class TestEdgeCaseOrders:
    """Additional edge case orders."""

    def test_order_just_water(self, order_and_sm):
        """Order just water."""
        order, sm = order_and_sm

        result = sm.process("just a water please", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should handle water"

    def test_order_side_only(self, order_and_sm):
        """Order only a side item."""
        order, sm = order_and_sm

        result = sm.process("just a side of cream cheese", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should handle side only"

    def test_asking_price_during_order(self, order_and_sm):
        """Ask price during complex order."""
        order, sm = order_and_sm

        result1 = sm.process("Everything bagel with lox", order)
        result2 = sm.process("how much is that?", result1.order)
        result3 = sm.process("ok add it", result2.order)

        items = result3.order.items.get_active_items()
        assert len(items) >= 1 or result3.message is not None, "Should handle price inquiry"

    def test_dietary_question_during_order(self, order_and_sm):
        """Dietary question during order."""
        order, sm = order_and_sm

        result1 = sm.process("Plain bagel", order)
        result2 = sm.process("is the cream cheese vegetarian?", result1.order)
        result3 = sm.process("yes please with cream cheese", result2.order)

        items = result3.order.items.get_active_items()
        assert len(items) >= 1 or result3.message is not None, "Should handle question"
