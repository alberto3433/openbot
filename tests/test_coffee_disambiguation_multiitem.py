"""Test for multi-item orders with coffee disambiguation."""

import pytest
from unittest.mock import MagicMock, patch

from sandwich_bot.tasks.state_machine import OrderStateMachine
from sandwich_bot.tasks.models import OrderTask
from sandwich_bot.tasks.schemas import OrderPhase


def create_mock_menu_data():
    """Create mock menu data with multiple coffee options."""
    return {
        "all_items": [
            {"id": "1", "name": "Coffee", "base_price": 2.50, "category": "drinks"},
            {"id": "2", "name": "Latte", "base_price": 3.50, "category": "drinks"},
            {"id": "3", "name": "Plain Bagel", "base_price": 2.50, "category": "custom_bagels"},
            {"id": "4", "name": "Everything Bagel", "base_price": 2.75, "category": "custom_bagels"},
        ],
        "bagels": {
            "plain": {"id": "3", "name": "Plain Bagel", "base_price": 2.50},
            "everything": {"id": "4", "name": "Everything Bagel", "base_price": 2.75},
        },
        # MenuLookup searches "drinks" category, not "beverages"
        "drinks": [
            {"id": "1", "name": "Coffee", "base_price": 2.50},
            {"id": "2", "name": "Latte", "base_price": 3.50},
        ],
        "categories": ["custom_bagels", "drinks"],
        "store_id": "test_store",
    }


class TestCoffeeDisambiguationMultiItem:
    """Test that multi-item orders with ambiguous coffee are handled correctly."""

    def test_coffee_and_bagel_disambiguation(self):
        """Test 'coffee and a bagel' triggers disambiguation after bagel config."""
        menu_data = create_mock_menu_data()
        sm = OrderStateMachine(menu_data=menu_data)
        order = OrderTask(store_id="test_store")

        # Start with greeting
        result = sm.process("hi", order)
        assert "What can I get" in result.message or "help you" in result.message.lower()
        order = result.order

        # Send "coffee and a bagel"
        result = sm.process("coffee and a bagel", order)
        print(f"1. 'coffee and a bagel' -> {result.message}")
        order = result.order

        # Should ask about bagel type first
        assert "bagel" in result.message.lower() or "kind" in result.message.lower(), \
            f"Expected bagel type question, got: {result.message}"

        # Answer bagel type
        result = sm.process("plain", order)
        print(f"2. 'plain' -> {result.message}")
        order = result.order

        # Should ask about toasted
        assert "toast" in result.message.lower(), \
            f"Expected toasted question, got: {result.message}"

        # Answer toasted
        result = sm.process("yes", order)
        print(f"3. 'yes' (toasted) -> {result.message}")
        order = result.order

        # Should ask about spread
        assert "cream cheese" in result.message.lower() or "spread" in result.message.lower() or "butter" in result.message.lower(), \
            f"Expected spread question, got: {result.message}"

        # Mock the spread parser to avoid needing OpenAI
        with patch('sandwich_bot.tasks.bagel_config_handler.parse_spread_choice') as mock_spread:
            # Create a mock response object
            mock_response = MagicMock()
            mock_response.spread = None
            mock_response.no_spread = True
            mock_spread.return_value = mock_response

            result = sm.process("no thanks", order)
            print(f"4. 'no thanks' (spread) -> {result.message}")
            order = result.order

        # At this point, bagel is complete and we should see coffee disambiguation
        # The message should contain options like "Coffee", "Latte"
        msg_lower = result.message.lower()
        print(f"5. Checking for coffee disambiguation in: {result.message}")

        # Check that we're asking about coffee with options
        has_coffee_options = ("coffee" in msg_lower and
                             ("options" in msg_lower or
                              "which" in msg_lower or
                              "1." in result.message or
                              "latte" in msg_lower))

        assert has_coffee_options, \
            f"Expected coffee disambiguation question with options, got: {result.message}"

        # Verify pending_drink_options is set
        assert order.pending_drink_options, \
            "Expected pending_drink_options to be set for disambiguation"

        # Verify pending_field is drink_selection
        assert order.pending_field == "drink_selection", \
            f"Expected pending_field='drink_selection', got: {order.pending_field}"

        print("\n=== TEST PASSED ===")
        print("Coffee disambiguation is properly triggered after bagel configuration!")


    def test_bagel_and_coffee_order_reversed(self):
        """Test 'bagel and coffee' also triggers disambiguation after bagel config."""
        menu_data = create_mock_menu_data()
        sm = OrderStateMachine(menu_data=menu_data)
        order = OrderTask(store_id="test_store")

        # Start with greeting
        result = sm.process("hi", order)
        order = result.order

        # Send "bagel and coffee"
        result = sm.process("bagel and coffee", order)
        print(f"1. 'bagel and coffee' -> {result.message}")
        order = result.order

        # Should ask about bagel type first
        assert "bagel" in result.message.lower() or "kind" in result.message.lower()

        # Answer bagel type
        result = sm.process("everything", order)
        print(f"2. 'everything' -> {result.message}")
        order = result.order

        # Answer toasted
        result = sm.process("no", order)
        print(f"3. 'no' (toasted) -> {result.message}")
        order = result.order

        # Answer spread
        with patch('sandwich_bot.tasks.bagel_config_handler.parse_spread_choice') as mock_spread:
            mock_response = MagicMock()
            mock_response.spread = None
            mock_response.no_spread = True
            mock_spread.return_value = mock_response

            result = sm.process("nothing", order)
            print(f"4. 'nothing' (spread) -> {result.message}")
            order = result.order

        # Check for coffee disambiguation
        msg_lower = result.message.lower()
        has_coffee_options = ("coffee" in msg_lower and
                             ("options" in msg_lower or
                              "latte" in msg_lower or
                              "which" in msg_lower or
                              "1." in result.message))

        assert has_coffee_options, \
            f"Expected coffee disambiguation question, got: {result.message}"

        print("\n=== TEST PASSED ===")


if __name__ == "__main__":
    test = TestCoffeeDisambiguationMultiItem()
    print("=== Test 1: coffee and a bagel ===")
    test.test_coffee_and_bagel_disambiguation()
    print("\n=== Test 2: bagel and coffee ===")
    test.test_bagel_and_coffee_order_reversed()
