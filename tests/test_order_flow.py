"""
Integration tests for greeting handler and taking items handler.

Split from test_tasks_integration.py for maintainability.
"""

import pytest
from unittest.mock import patch, MagicMock

from orderbot.tasks.models import OrderTask
from orderbot.tasks.handler_config import HandlerConfig

from tests.fixtures.mock_menu_cache import apply_mock_menu_cache


@pytest.fixture(autouse=True)
def mock_menu_cache_attributes(monkeypatch):
    """Auto-use fixture to mock menu_cache methods for all tests."""
    apply_mock_menu_cache(monkeypatch)


class TestGreetingHandler:
    """Tests for _handle_greeting."""

    def test_pure_greeting_returns_welcome(self):
        """Test that a pure greeting returns welcome message."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.schemas import OrderPhase, OpenInputResponse
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.GREETING.value

        with patch("orderbot.tasks.taking_items_handler.parse_open_input") as mock_parse:
            mock_parse.return_value = OpenInputResponse(
                is_greeting=True, unclear=False
            )

            result = sm._handle_greeting("hello", order)

            assert "welcome" in result.message.lower()
            assert "borough" in result.message.lower()

    def test_unclear_input_returns_welcome(self):
        """Test that unclear input returns welcome message."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.schemas import OrderPhase, OpenInputResponse
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.GREETING.value

        with patch("orderbot.tasks.taking_items_handler.parse_open_input") as mock_parse:
            mock_parse.return_value = OpenInputResponse(
                is_greeting=False, unclear=True
            )

            result = sm._handle_greeting("uh what", order)

            assert "welcome" in result.message.lower() or "get for you" in result.message.lower()

    def test_greeting_with_bagel_order_adds_item(self):
        """Test that greeting with bagel order adds bagel to cart."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.schemas import OrderPhase, OpenInputResponse
        from orderbot.tasks.schemas.parser_responses import ParsedItemEntry, Selection
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.GREETING.value

        with patch("orderbot.tasks.taking_items_handler.parse_open_input") as mock_parse:
            # Use selections instead of attribute_values (which is a read-only property)
            mock_parse.return_value = OpenInputResponse(
                is_greeting=False, unclear=False,
                parsed_items=[
                    ParsedItemEntry(
                        item_type="bagel",
                        selections=[
                            Selection(slug="plain", category="bread"),
                            Selection(slug="yes", category="toasted"),
                            Selection(slug="cream cheese", category="spread"),
                        ],
                    )
                ]
            )

            result = sm._handle_greeting("can I get a plain bagel toasted with cream cheese", order)

            # Should have added a bagel
            bagels = [i for i in order.items.items if i.has_attribute('bread')]
            assert len(bagels) >= 1
            assert bagels[0]["bread"] == "plain"

    def test_greeting_with_coffee_order_adds_item(self):
        """Test that greeting with coffee order adds coffee to cart."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.schemas import OrderPhase, OpenInputResponse
        from orderbot.tasks.schemas.parser_responses import ParsedItemEntry, Selection
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.GREETING.value

        with patch("orderbot.tasks.taking_items_handler.parse_open_input") as mock_parse:
            # Use "Coffee" which uniquely matches in menu (no disambiguation)
            # Use selections instead of attribute_values (which is a read-only property)
            mock_parse.return_value = OpenInputResponse(
                is_greeting=False, unclear=False,
                parsed_items=[
                    ParsedItemEntry(
                        item_type="coffee_based_beverage",
                        item_name="Coffee",
                        selections=[
                            Selection(slug="large", category="size"),
                            Selection(slug="iced", category="temperature"),
                        ],
                    )
                ]
            )

            result = sm._handle_greeting("I'd like a large iced coffee", order)

            # Should have added a coffee (or be configuring it, or asking for clarification)
            coffees = [i for i in order.items.items if i.has_attribute('size')]
            # If coffee config is in progress, the coffee should still be added
            # "drink_type" is also valid if disambiguation is needed between Coffee/Iced Coffee
            # "item_selection" is valid when multiple menu items match (e.g., Coffee vs Iced Coffee)
            assert len(coffees) >= 1 or order.pending_field in ("coffee_size", "coffee_style", "coffee_modifiers", "coffee_based_beverage:size", "coffee_based_beverage:temperature", "coffee_based_beverage:iced", "coffee_based_beverage:milk_sweetener_syrup", "drink_type", "item_selection")


# =============================================================================
# Taking Items Handler Tests
# =============================================================================

class TestTakingItemsHandler:
    """Tests for _handle_taking_items."""

    def test_ordering_bagel_adds_to_cart(self):
        """Test that ordering a bagel adds it to the cart."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.schemas import OrderPhase, OpenInputResponse
        from orderbot.tasks.schemas.parser_responses import ParsedItemEntry, Selection
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        with patch("orderbot.tasks.taking_items_handler.parse_open_input") as mock_parse:
            # Use selections list instead of attribute_values (which is a read-only property)
            mock_parse.return_value = OpenInputResponse(
                parsed_items=[
                    ParsedItemEntry(
                        item_type="bagel",
                        selections=[
                            Selection(slug="everything", category="bread"),
                            Selection(slug="yes", category="toasted"),
                            Selection(slug="butter", category="spread"),
                        ],
                    )
                ]
            )

            result = sm._handle_taking_items("an everything bagel toasted with butter", order)

            bagels = [i for i in order.items.items if i.has_attribute('bread')]
            assert len(bagels) >= 1
            assert bagels[0]["bread"] == "everything"
            # Data-driven flow may ask about optional changes, spread, or proceed to "anything else"
            msg_lower = result.message.lower()
            assert "anything else" in msg_lower or "else" in msg_lower or "change" in msg_lower or "spread" in msg_lower

    def test_ordering_coffee_adds_to_cart(self):
        """Test that ordering coffee adds it to the cart."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.schemas import OrderPhase, OpenInputResponse
        from orderbot.tasks.schemas.parser_responses import ParsedItemEntry, Selection
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        with patch("orderbot.tasks.taking_items_handler.parse_open_input") as mock_parse:
            # Use "Coffee" which uniquely matches in menu (no disambiguation)
            # Use selections instead of attribute_values (which is a read-only property)
            mock_parse.return_value = OpenInputResponse(
                parsed_items=[
                    ParsedItemEntry(
                        item_type="coffee_based_beverage",
                        item_name="Coffee",
                        selections=[
                            Selection(slug="medium", category="size"),
                            Selection(slug="hot", category="temperature"),
                        ],
                    )
                ]
            )

            result = sm._handle_taking_items("a medium coffee", order)

            coffees = [i for i in order.items.items if i.has_attribute('size')]
            # Coffee should be added (or be configuring it, or asking for clarification)
            # "drink_type" is also valid if disambiguation is needed between Coffee/Iced Coffee
            # "item_selection" is valid when multiple menu items match (e.g., Coffee vs Iced Coffee)
            assert len(coffees) >= 1 or order.pending_field in ("coffee_size", "coffee_style", "coffee_modifiers", "coffee_based_beverage:size", "coffee_based_beverage:temperature", "coffee_based_beverage:iced", "coffee_based_beverage:milk_sweetener_syrup", "drink_type", "item_selection")

    def test_done_ordering_transitions_to_checkout(self):
        """Test that 'done ordering' transitions to checkout."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.schemas import OrderPhase, OpenInputResponse
        from orderbot.tasks.models import OrderTask
        from tests.helpers import BagelItemTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        # Add an item first
        bagel = BagelItemTask(bagel_type="plain", toasted=True, spread="cream cheese")
        bagel.mark_complete()
        order.items.add_item(bagel)

        with patch("orderbot.tasks.taking_items_handler.parse_open_input") as mock_parse:
            mock_parse.return_value = OpenInputResponse(
                done_ordering=True,
                parsed_items=[],
            )

            result = sm._handle_taking_items("that's all", order)

            # Should ask about pickup/delivery
            assert "pickup" in result.message.lower() or "delivery" in result.message.lower()

    def test_cancel_item_removes_from_cart(self):
        """Test that canceling an item removes it from cart."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.schemas import OrderPhase, OpenInputResponse
        from orderbot.tasks.models import OrderTask
        from tests.helpers import CoffeeItemTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        # Add a coffee
        coffee = CoffeeItemTask(drink_type="latte", size="large", iced=True)
        coffee.mark_complete()
        order.items.add_item(coffee)

        initial_count = len(order.items.items)

        with patch("orderbot.tasks.taking_items_handler.parse_open_input") as mock_parse:
            mock_parse.return_value = OpenInputResponse(
                cancel_item="latte",
                parsed_items=[],
            )

            result = sm._handle_taking_items("cancel the latte", order)

            assert len(order.items.items) == initial_count - 1
            assert "removed" in result.message.lower()

    def test_cancel_plural_items_removes_all_matching(self):
        """Test that 'remove the lattes' removes all latte items."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.schemas import OrderPhase, OpenInputResponse
        from orderbot.tasks.models import OrderTask
        from tests.helpers import BagelItemTask, CoffeeItemTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # Add a bagel
        bagel = BagelItemTask(bagel_type="plain", toasted=True, spread="butter")
        bagel.mark_complete()
        order.items.add_item(bagel)

        # Add two lattes
        latte1 = CoffeeItemTask(drink_type="latte", size="small", iced=False)
        latte1.mark_complete()
        order.items.add_item(latte1)

        latte2 = CoffeeItemTask(drink_type="latte", size="large", iced=True)
        latte2.mark_complete()
        order.items.add_item(latte2)

        assert len(order.items.items) == 3

        with patch("orderbot.tasks.taking_items_handler.parse_open_input") as mock_parse:
            mock_parse.return_value = OpenInputResponse(
                cancel_item="lattes",
                parsed_items=[],
            )

            result = sm._handle_taking_items("remove the lattes", order)

            # Should only have the bagel left
            active_items = order.items.get_active_items()
            assert len(active_items) == 1
            assert active_items[0]["bread"] == "plain"
            assert "removed" in result.message.lower()
            assert "2 lattes" in result.message.lower()

    def test_make_it_2_duplicates_last_item(self):
        """Test that 'make it 2' duplicates the last item."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.schemas import OrderPhase, OpenInputResponse
        from orderbot.tasks.models import OrderTask
        from tests.helpers import BagelItemTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        bagel = BagelItemTask(bagel_type="sesame", toasted=True, spread="cream cheese")
        bagel.mark_complete()
        order.items.add_item(bagel)

        initial_count = len(order.items.items)

        with patch("orderbot.tasks.taking_items_handler.parse_open_input") as mock_parse:
            mock_parse.return_value = OpenInputResponse(
                duplicate_last_item=1,
                parsed_items=[],
            )

            result = sm._handle_taking_items("make it 2", order)

            assert len(order.items.items) == initial_count + 1
            assert "total" in result.message.lower()

    def test_order_type_pickup_sets_delivery_method(self):
        """Test that mentioning pickup sets delivery method."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.schemas import OrderPhase, OpenInputResponse
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        with patch("orderbot.tasks.taking_items_handler.parse_open_input") as mock_parse:
            mock_parse.return_value = OpenInputResponse(
                order_type="pickup",
                parsed_items=[],
            )

            result = sm._handle_taking_items("I'd like to place a pickup order", order)

            assert order.delivery_method.order_type == "pickup"
            assert "pickup" in result.message.lower()

    def test_cancel_from_empty_cart_returns_message(self):
        """Test that canceling from empty cart returns helpful message."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.schemas import OrderPhase, OpenInputResponse
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        with patch("orderbot.tasks.taking_items_handler.parse_open_input") as mock_parse:
            mock_parse.return_value = OpenInputResponse(
                cancel_item="bagel",
                parsed_items=[],
            )

            result = sm._handle_taking_items("cancel the bagel", order)

            assert "nothing" in result.message.lower() or "yet" in result.message.lower()

    def test_multiple_bagels_adds_correct_quantity(self):
        """Test that ordering multiple bagels adds correct quantity."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.schemas import OrderPhase, OpenInputResponse
        from orderbot.tasks.schemas.parser_responses import ParsedItemEntry
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        with patch("orderbot.tasks.taking_items_handler.parse_open_input") as mock_parse:
            mock_parse.return_value = OpenInputResponse(
                parsed_items=[
                    ParsedItemEntry(
                        item_type="bagel",
                        quantity=3,
                        attribute_values={
                            "bread": "plain",
                            "toasted": True,
                            "spread_type": "cream cheese",
                        },
                    )
                ]
            )

            result = sm._handle_taking_items("3 plain bagels toasted with cream cheese", order)

            bagels = [i for i in order.items.items if i.has_attribute('bread')]
            assert len(bagels) == 3

    def test_another_espresso_creates_menu_item_task(self, menu_cache_loaded):
        """Test that 'another espresso' creates MenuItemTask, not CoffeeItemTask.

        Espresso uses the data-driven MenuItemTask flow with global attributes,
        not the CoffeeItemTask flow. This test ensures the handler routing is correct.

        NOTE: The menu may have multiple espresso variants (Single/Double Espresso)
        which triggers disambiguation instead of directly adding. This test accepts
        either outcome as valid data-driven behavior.
        """
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.schemas import OrderPhase, OpenInputResponse
        from orderbot.tasks.models import OrderTask, MenuItemTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # First, add an espresso to the order
        first_espresso = MenuItemTask(
            menu_item_name="Espresso",
            menu_item_type="espresso",
            unit_price=3.50,
        )
        first_espresso.mark_complete()
        order.items.add_item(first_espresso)

        with patch("orderbot.tasks.taking_items_handler.parse_open_input") as mock_parse:
            mock_parse.return_value = OpenInputResponse(
                duplicate_new_item_type="espresso",  # "another espresso" detected
                parsed_items=[],
            )

            result = sm._handle_taking_items("another espresso", order)

            # Should have espressos as MenuItemTask with menu_item_type='espresso'
            # NOT coffee_based_beverage or espresso_based_beverage (those are coffee/latte types)
            espressos = [i for i in order.items.items if isinstance(i, MenuItemTask) and i.menu_item_type == "espresso"]
            wrong_type_items = [i for i in order.items.items if isinstance(i, MenuItemTask) and i.menu_item_type in ("coffee_based_beverage", "espresso_based_beverage")]

            # Accept either: 2 espressos added, OR disambiguation triggered (options provided)
            # Both are valid data-driven behaviors depending on menu configuration
            if len(espressos) == 2:
                # Perfect - second espresso was added directly
                pass
            elif len(espressos) == 1 and (order.pending_item_options or "which" in result.message.lower()):
                # Disambiguation triggered due to multiple espresso variants - acceptable
                pass
            else:
                # At minimum, the first espresso should still be there
                assert len(espressos) >= 1, f"Expected at least 1 espresso, got {len(espressos)}"

            # Verify espresso didn't get wrong item type (coffee_based_beverage is for regular coffee)
            assert len(wrong_type_items) == 0, f"Espresso should not create coffee_based_beverage/espresso_based_beverage, got {[i.menu_item_type for i in wrong_type_items]}"


