"""
ConversationDriver Examples.

Demonstrates how to use the ConversationDriver helper for multi-turn
conversation tests. These are rewrites of tests from test_resiliency_batch1.py
to show the pattern.
"""

from tests.helpers import BagelItemTask, CoffeeItemTask, ConversationDriver


class TestConversationDriverExamples:
    """Examples showing ConversationDriver usage patterns."""

    def test_change_spread_on_bagel(self):
        """User has bagel with cream cheese, changes to veggie cream cheese."""
        bagel = BagelItemTask(bagel_type="plain", toasted=True, spread="cream cheese")
        bagel.mark_complete()

        driver = ConversationDriver()
        driver.add_item(bagel)
        driver.say("actually make it veggie cream cheese")

        assert driver.item_count == 1
        updated = driver.items[0]
        assert updated["bread"] == "plain", "Bagel type should be preserved"
        assert updated["toasted"] is True, "Toasted should be preserved"
        spread = updated["spread"]
        assert "veggie" in spread.lower() or "vegetable" in spread.lower(), \
            f"Spread should be veggie cream cheese, got: {spread}"

    def test_change_coffee_size(self):
        """User has small latte, changes to large."""
        coffee = CoffeeItemTask(drink_type="latte", size="small", iced=False)
        coffee.mark_complete()

        driver = ConversationDriver()
        driver.add_item(coffee)
        driver.say("make it a large")

        assert driver.item_count == 1
        updated = driver.items[0]
        assert updated["size"] == "large", f"Size should be large, got: {updated['size']}"
        assert updated.menu_item_name == "latte", "Drink type should be preserved"
        assert updated["temperature"] == "hot", "Temperature should be preserved"

    def test_multi_turn_chaining(self):
        """Demonstrate chaining .say() calls for multi-turn flows."""
        driver = ConversationDriver()
        driver.say("I'd like a plain bagel")

        assert driver.item_count >= 1
        assert driver.message  # Bot should have responded
