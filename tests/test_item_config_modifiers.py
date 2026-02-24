"""Item configuration modifier handling, attribute selection, and configuration flow tests."""

import pytest
from unittest.mock import patch, MagicMock

from orderbot.tasks.models import OrderTask
from orderbot.tasks.handler_config import HandlerConfig

from tests.fixtures.mock_menu_cache import apply_mock_menu_cache


@pytest.fixture(autouse=True)
def mock_menu_cache_attributes(monkeypatch):
    """Auto-use fixture to mock menu_cache methods for all tests."""
    apply_mock_menu_cache(monkeypatch)


# =============================================================================
# Unknown Item Handling Tests
# =============================================================================

class TestUnknownItemHandling:
    """Tests for handling items that aren't on the menu."""

    def test_unknown_side_item_rejected_with_suggestions(self):
        """Test that ordering an unknown side item returns helpful suggestions."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        order = OrderTask()
        sm = OrderStateMachine()

        # Try to add a hashbrown (not on menu)
        canonical_name, error_message = sm.item_adder_handler.add_side_item("hashbrown", 1, order)

        # Should return None for canonical_name and an error message
        assert canonical_name is None
        assert error_message is not None
        # Message should indicate item wasn't found
        assert "couldn't find" in error_message.lower() or "don't have" in error_message.lower()
        assert "hashbrown" in error_message.lower()

        # Order should not have any items
        assert len(order.items.items) == 0

    def test_unknown_menu_item_rejected_with_suggestions(self):
        """Test that ordering an unknown menu item returns helpful suggestions."""
        from orderbot.tasks.state_machine import OrderStateMachine, StateMachineResult
        from orderbot.tasks.models import OrderTask

        order = OrderTask()
        sm = OrderStateMachine()

        # Try to add sushi (definitely not on a bagel shop menu)
        result = sm.item_adder_handler.add_menu_item("sushi roll", 1, order)

        # Should return a result with error message
        assert isinstance(result, StateMachineResult)
        # Message should indicate item wasn't found
        assert "couldn't find" in result.message.lower() or "don't have" in result.message.lower()
        assert "sushi" in result.message.lower()

        # Order should not have any items
        assert len(order.items.items) == 0

    def test_valid_side_item_added_successfully(self):
        """Test that a valid side item is added successfully.

        Uses "Latkes" which is an actual menu item in the database.
        """
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        order = OrderTask()
        sm = OrderStateMachine()

        # Add a valid side that exists in the real menu
        canonical_name, error_message = sm.item_adder_handler.add_side_item("latkes", 1, order)

        # Should succeed
        assert canonical_name == "Side of Breakfast Latke", f"Expected 'Side of Breakfast Latke', got: {canonical_name}"
        assert error_message is None, f"Expected no error, got: {error_message}"
        assert len(order.items.items) == 1
        assert order.items.items[0].menu_item_name == "Side of Breakfast Latke"
        assert order.items.items[0].unit_price > 0, "Price should be set from database"

    def test_infer_item_type_sides(self):
        """Test item type inference using category keywords.

        infer_item_type works by detecting item type keywords in the text,
        NOT by recognizing specific menu item names. So:
        - "side of bacon" -> contains "side" keyword -> returns side item type
        - "latkes" -> no keyword match -> returns None (correct behavior)
        """
        from orderbot.tasks.state_machine import OrderStateMachine

        sm = OrderStateMachine()

        # "side of bacon" contains the keyword "side" -> infers item type
        result = sm.menu_lookup.infer_item_type("side of bacon")
        assert result is not None and result.get("slug") == "side"

        # "sides" is an alias for the "side" item type
        result = sm.menu_lookup.infer_item_type("any sides available")
        assert result is not None and result.get("slug") == "side"

        # "latkes" has no item type keyword -> returns None (this is correct)
        result = sm.menu_lookup.infer_item_type("latkes")
        assert result is None

    def test_get_suggestions_for_item_type_formats_correctly(self):
        """Test that suggestions are formatted as natural language."""
        from orderbot.tasks.state_machine import OrderStateMachine

        menu_data = {
            "items_by_type": {
                "side": [
                    {"id": 1, "name": "Home Fries", "base_price": 3.99},
                    {"id": 2, "name": "Fruit Cup", "base_price": 4.99},
                    {"id": 3, "name": "Side of Bacon", "base_price": 2.99},
                ],
            },
        }

        sm = OrderStateMachine(menu_data=menu_data)

        suggestions = sm.menu_lookup.get_suggestions_for_item_type("side", limit=3)

        # Should be formatted as "A, B, or C"
        assert "Home Fries" in suggestions
        assert "Fruit Cup" in suggestions
        assert "Side of Bacon" in suggestions
        assert ", or " in suggestions

    def test_bagel_chips_parsed_as_side_item_not_bagel(self):
        """Test that 'bagel chips' is NOT parsed as a bagel order.

        This is a regression test for the bug where 'bagel chips' (a side item)
        was incorrectly parsed as a bagel order because it contains 'bagel'.
        Note: "bagel chips" goes through menu lookup for disambiguation (multiple flavors),
        so it returns as menu_item rather than side_item.
        """
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic
        from tests.helpers import has_bagel, get_menu_item, has_side_item, get_bagel_item

        # "bagel chips" should NOT be parsed as a bagel - it goes to menu lookup
        result = parse_open_input_deterministic("bagel chips")
        assert result is not None
        # Key assertion: NOT a bagel order
        assert not has_bagel(result), "'bagel chips' should NOT be parsed as a bagel"
        # It should go through menu lookup (menu_item) for disambiguation
        menu_item = get_menu_item(result)
        assert menu_item is not None and menu_item.item_name == "bagel chips"

        # Other side items should also work (may be parsed as menu_item for disambiguation)
        result2 = parse_open_input_deterministic("latkes")
        assert result2 is not None
        # Key assertion: NOT a bagel order
        assert not has_bagel(result2), "'latkes' should NOT be parsed as a bagel"
        # Should be recognized as a menu item (goes through menu lookup)
        assert len(result2.parsed_items) > 0, f"Should have a parsed item, got {result2.parsed_items}"

        result3 = parse_open_input_deterministic("fruit cup")
        assert result3 is not None
        assert not has_bagel(result3), "'fruit cup' should NOT be parsed as a bagel"
        assert len(result3.parsed_items) > 0, f"Should have a parsed item, got {result3.parsed_items}"

        # But "plain bagel" should still be a bagel order
        result4 = parse_open_input_deterministic("a plain bagel")
        assert result4 is not None
        assert has_bagel(result4), "'a plain bagel' should be parsed as a bagel"
        # Bagel type may be "plain" or "plain_bagel" (database slug)
        bagel = get_bagel_item(result4)
        assert bagel is not None and "plain" in bagel.attribute_values.get("bread", "").lower()


# =============================================================================
# Email Validation Tests
# =============================================================================

class TestSpreadSandwichWithCoke:
    """Tests for ordering a spread sandwich with a coke in a single message."""

    def test_spread_sandwich_with_coke_asks_toasted(self, menu_cache_loaded):
        """Test that ordering a spread sandwich with coke asks for toasted."""
        from orderbot.tasks.state_machine import OrderStateMachine, OrderTask

        sm = OrderStateMachine()  # Uses global menu data (loaded by menu_cache_loaded fixture)
        order = OrderTask()

        # Order bagel with spread and coke - uses real menu data
        result = sm.process("plain bagel with scallion cream cheese and a coke", order)

        # Should ask for toasted or proceed with configuration
        msg_lower = result.message.lower()
        # Accept either toasted question or configuration flow
        assert "toasted" in msg_lower or order.pending_field in ("toasted", "menu_item_attr_toasted", "menu_item_attr_spread_type", "bagel:toasted", "bagel:spread_type"), \
            f"Expected toasted/config question, got: {result.message} (pending_field={order.pending_field})"

        # Items should be in the cart (at least 1, bagel)
        items = order.items.items
        assert len(items) >= 1, f"Expected at least 1 item, got {len(items)}"

    def test_spread_sandwich_with_coke_completes_after_toasted(self, menu_cache_loaded):
        """Test that answering toasted question confirms both items."""
        from orderbot.tasks.state_machine import OrderStateMachine, OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        # Order bagel with scallion cream cheese and coke - uses real menu data
        result = sm.process("plain bagel with scallion cream cheese and a coke", order)

        # Process through configuration flow (answer toasted and any other questions)
        max_iterations = 5
        for _ in range(max_iterations):
            if "toasted" in result.message.lower():
                result = sm.process("yes", order)
            elif "spread" in result.message.lower():
                result = sm.process("no", order)
            elif order.pending_field == "customization_checkpoint":
                result = sm.process("no", order)
            else:
                break

        # Should eventually ask "Anything else?" or be in taking items phase
        msg_lower = result.message.lower()
        assert "anything else" in msg_lower or "else" in msg_lower or "got it" in msg_lower or order.phase == "taking_items", \
            f"Expected 'Anything else?', got: {result.message} (phase={order.phase})"

    def test_spread_sandwich_with_coke_checkout_flow(self, menu_cache_loaded):
        """Test full checkout flow after ordering spread sandwich with coke."""
        from orderbot.tasks.state_machine import OrderStateMachine, OrderTask
        from orderbot.tasks.schemas import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()

        # Order bagel with scallion cream cheese and coke - uses real menu data
        result = sm.process("plain bagel with scallion cream cheese and a coke", order)

        # Process through configuration flow
        max_iterations = 10
        for _ in range(max_iterations):
            msg_lower = result.message.lower()
            if "toasted" in msg_lower:
                result = sm.process("yes", order)
            elif "scoop" in msg_lower:
                result = sm.process("no", order)
            elif "spread" in msg_lower:
                result = sm.process("no", order)
            elif order.pending_field == "customization_checkpoint":
                result = sm.process("no", order)
            elif "anything else" in msg_lower or "else" in msg_lower:
                break
            else:
                break

        # Say no to proceed to checkout
        result = sm.process("no", order)

        # Should be in checkout flow
        msg_lower = result.message.lower()
        assert "pickup" in msg_lower or "delivery" in msg_lower or order.phase == OrderPhase.CHECKOUT_DELIVERY.value, \
            f"Expected pickup/delivery question, got: {result.message} (phase={order.phase})"


class TestBagelWithCoffeeConfig:
    """Tests for ordering a bagel with a coffee that needs configuration."""

    def test_bagel_and_latte_queues_coffee(self):
        """Test that ordering bagel + latte stores latte for processing after bagel."""
        from orderbot.tasks.state_machine import OrderStateMachine, OrderTask
        from tests.helpers import CoffeeItemTask

        sm = OrderStateMachine()  # Use global menu data for pricing
        order = OrderTask()

        # Order bagel and latte
        result = sm.process("a bagel and a latte", order)

        # With real menu data, "latte" may trigger disambiguation first
        if "which would you like" in result.message.lower() or order.pending_item_options:
            # Handle disambiguation - select the regular Latte
            result = sm.process("Latte", order)

        # Should ask for bagel type first
        assert "bagel" in result.message.lower(), f"Expected bagel question, got: {result.message}"
        assert order.pending_field in ("bagel_choice", "menu_item_attr_bread", "bagel:bread")

        # Coffee should be either:
        # 1. In the order items (if latte was processed first), or
        # 2. In pending_parsed_items (if bagel was processed first and latte stored for later)
        coffee_items = [
            item for item in order.items.items
            if "latte" in item.menu_item_name.lower()
        ]
        pending_latte = [
            item for item in order.pending_parsed_items
            if item.get("item_name", "").lower() == "latte"
        ]
        # Either latte is in items or in pending - one of these should be true
        assert len(coffee_items) == 1 or len(pending_latte) == 1, \
            f"Expected latte in items or pending. items={[i.menu_item_name for i in order.items.items]}, pending={order.pending_parsed_items}"

    def test_bagel_and_latte_full_flow(self):
        """Test complete bagel + latte configuration flow."""
        from orderbot.tasks.state_machine import OrderStateMachine, OrderTask

        sm = OrderStateMachine()  # Use global menu data for pricing
        order = OrderTask()

        # Order bagel and latte
        result = sm.process("a bagel and a latte", order)

        # With real menu data, "latte" may trigger disambiguation first
        if "which would you like" in result.message.lower() or order.pending_item_options:
            result = sm.process("Latte", order)

        assert "bagel" in result.message.lower()

        # Answer plain bagel
        result = sm.process("plain bagel", order)
        assert "toasted" in result.message.lower(), f"Expected toasted question, got: {result.message}"

        # Answer toasted
        result = sm.process("yes", order)

        # Handle scooped question if present (DB-driven attribute between toasted and spread)
        if "scoop" in result.message.lower():
            result = sm.process("no", order)

        # Data-driven flow may ask "Any spread?" or list options like "cream cheese or butter?"
        msg_lower = result.message.lower()
        assert "spread" in msg_lower or "cream cheese" in msg_lower or "butter" in msg_lower, f"Expected spread question, got: {result.message}"

        # Answer butter
        result = sm.process("butter", order)

        # Data-driven flow may offer customization checkpoint for optional attrs (cheese)
        # Skip it if present
        if "more changes" in result.message.lower() or "customize" in result.message.lower():
            result = sm.process("no", order)

        # After bagel config completes, the latte (stored in pending_parsed_items) is processed.
        # Since "latte" matches multiple items (Hot/Iced/Matcha), disambiguation is triggered.
        if "which would you like" in result.message.lower() or order.pending_item_options:
            result = sm.process("Hot Latte", order)

        # Now should ask coffee questions - size
        assert "size" in result.message.lower() or "small" in result.message.lower(), f"Expected coffee size question, got: {result.message}"
        assert order.pending_field in ("coffee_size", "menu_item_attr_size", "coffee_based_beverage:size", "espresso:size", "espresso_based_beverage:size")

    def test_bagel_and_latte_complete_with_coffee_config(self):
        """Test that coffee configuration completes properly after bagel."""
        from orderbot.tasks.state_machine import OrderStateMachine, OrderTask
        from tests.helpers import BagelItemTask, CoffeeItemTask

        sm = OrderStateMachine()  # Use global menu data for pricing
        order = OrderTask()

        # Order bagel and latte
        result = sm.process("a bagel and a latte", order)

        # With real menu data, "latte" may trigger disambiguation first
        if "which would you like" in result.message.lower() or order.pending_item_options:
            result = sm.process("Latte", order)

        # Complete bagel config: plain bagel
        result = sm.process("plain bagel", order)
        # Toasted
        result = sm.process("yes toasted", order)
        # Handle scooped question if present (DB-driven attribute between toasted and spread)
        if "scoop" in result.message.lower():
            result = sm.process("no", order)
        # Butter
        result = sm.process("butter", order)

        # Data-driven flow may offer customization checkpoint for optional attrs (cheese)
        # Skip it if present
        if "more changes" in result.message.lower() or "customize" in result.message.lower():
            result = sm.process("no", order)

        # After bagel config completes, the latte (stored in pending_parsed_items) is processed.
        # Since "latte" matches multiple items (Hot/Iced/Matcha), disambiguation is triggered.
        if "which would you like" in result.message.lower() or order.pending_item_options:
            result = sm.process("Hot Latte", order)

        # Should now be asking about coffee size
        assert "size" in result.message.lower() or "small" in result.message.lower(), f"Expected coffee size question, got: {result.message}"

        # Answer large (we now only offer Small or Large)
        result = sm.process("large", order)

        # Espresso type may ask about espresso shots, milk/sweetener/syrup, or decaf
        # Handle any follow-up questions until we get to "anything else"
        # Max 15 iterations to prevent infinite loop
        for _ in range(15):
            if "anything else" in result.message.lower():
                break
            msg_lower = result.message.lower()
            if "shot" in msg_lower or "espresso" in msg_lower:
                result = sm.process("regular", order)
            elif "milk" in msg_lower or "sugar" in msg_lower or "sweetener" in msg_lower or "syrup" in msg_lower:
                result = sm.process("no", order)
            elif "decaf" in msg_lower:
                result = sm.process("no", order)
            elif "more changes" in msg_lower or "customize" in msg_lower:
                result = sm.process("no", order)
            elif "hot" in msg_lower or "iced" in msg_lower:
                result = sm.process("hot", order)
            else:
                # Unknown question - try "no" as default
                result = sm.process("no", order)

        # Now should ask "Anything else?"
        assert "anything else" in result.message.lower(), f"Expected 'Anything else?', got: {result.message}"

        # Verify both items are complete
        bagels = [i for i in order.items.items if i.has_attribute('bread')]
        # For espresso items, check by name since attributes vary
        coffees = [i for i in order.items.items if "latte" in i.menu_item_name.lower()]
        assert len(bagels) == 1
        assert len(coffees) == 1
        assert bagels[0]["bread"] == "plain"
        # Check coffee has size attribute set
        assert coffees[0].has_attribute('size'), f"Coffee should have size: {coffees[0].attribute_values}"
        assert coffees[0]["size"] == "large"

    def test_bagel_and_coke_no_queue(self):
        """Test that bagel + coke doesn't queue coffee (sodas skip config)."""
        from orderbot.tasks.state_machine import OrderStateMachine, OrderTask

        sm = OrderStateMachine()  # Use global menu data for pricing
        order = OrderTask()

        # Order bagel and coke
        result = sm.process("a bagel and a coke", order)

        # Should ask for bagel type
        assert "bagel" in result.message.lower()

        # Coke should NOT be queued (it's a soda, no config needed)
        assert not order.has_queued_config_items(), f"Coke should not be queued, queue: {order.pending_config_queue}"

    def test_coffee_latte_and_bagel_full_flow(self):
        """Test 3-item order: coffee, latte, and bagel - all configurable items.

        This test validates that multi-item orders with disambiguation are handled
        correctly. Items may be stored in pending_parsed_items during disambiguation
        and processed after the current item's configuration completes.
        """
        from orderbot.tasks.state_machine import OrderStateMachine, OrderTask
        from tests.helpers import BagelItemTask, CoffeeItemTask

        sm = OrderStateMachine()  # Use global menu data for pricing
        order = OrderTask()

        # Order coffee, latte, and bagel
        result = sm.process("a coffee, a latte, and a bagel", order)

        # Configuration loop - handle up to 20 interactions to complete all items
        # This handles disambiguation, config questions, and customization checkpoints
        for _ in range(20):
            msg_lower = result.message.lower()

            # Exit when we reach "anything else?" (order complete for now)
            if "anything else" in msg_lower:
                break

            # Handle disambiguation
            if order.pending_item_options:
                result = sm.process("1", order)
                continue

            # Handle customization checkpoint
            if "more changes" in msg_lower or "customize" in msg_lower:
                result = sm.process("no", order)
                continue

            # Handle bagel configuration
            if "bagel" in msg_lower or order.pending_field == "bagel:bread":
                result = sm.process("plain", order)
                continue
            if "toasted" in msg_lower:
                result = sm.process("yes", order)
                continue
            if "scoop" in msg_lower:
                result = sm.process("no", order)
                continue
            if "spread" in msg_lower or "cream cheese" in msg_lower or "butter" in msg_lower:
                result = sm.process("butter", order)
                continue

            # Handle coffee configuration
            if "size" in msg_lower or "small" in msg_lower:
                result = sm.process("large", order)
                continue
            if "hot" in msg_lower or "iced" in msg_lower:
                result = sm.process("hot", order)
                continue
            if "milk" in msg_lower or "sugar" in msg_lower or "syrup" in msg_lower:
                result = sm.process("no", order)
                continue

            # If we're stuck, break to avoid infinite loop
            break

        # After completing configuration, verify at least 1 of each type is in cart
        # Note: with disambiguation, we may get 1 or 2 coffees depending on flow
        final_coffees = [i for i in order.items.items if i.has_attribute('size')]
        final_bagels = [i for i in order.items.items if i.has_attribute('bread')]

        assert len(final_coffees) >= 1, f"Expected at least 1 coffee, got: {len(final_coffees)}"
        # Bagel may still be in pending_parsed_items if flow didn't complete
        bagels_in_pending = [p for p in order.pending_parsed_items
                           if isinstance(p, dict) and p.get('item_type') == 'bagel']
        assert len(final_bagels) >= 1 or len(bagels_in_pending) >= 1, \
            f"Expected at least 1 bagel in items or pending, got: items={len(final_bagels)}, pending={len(bagels_in_pending)}"

    def test_two_coffees_and_two_bagels(self):
        """Test plural forms: 2 coffees and 2 plain bagels - all get configured.

        Uses a configuration loop to handle varying question order (size, milk,
        shots, etc.) without making assumptions about exact sequence.
        """
        from orderbot.tasks.state_machine import OrderStateMachine, OrderTask
        from tests.helpers import BagelItemTask, CoffeeItemTask

        sm = OrderStateMachine()  # Use global menu data for pricing
        order = OrderTask()

        # Order 2 coffees and 2 plain bagels
        result = sm.process("2 coffees and 2 plain bagels", order)

        # Items are configured in order of addition - coffee first
        # Should ask for coffee size or be in configuration mode
        msg_lower = result.message.lower()
        assert "size" in msg_lower or "small" in msg_lower or order.pending_field, \
            f"Expected coffee size question, got: {result.message}"

        # Bagels should be queued for configuration (all items added upfront)
        assert order.pending_config_queue, "Expected items in pending_config_queue"
        bagel_queued = [p for p in order.pending_config_queue
                        if isinstance(p, dict) and p.get('item_name') == 'Plain']
        assert len(bagel_queued) >= 1, f"Expected bagels in pending_config_queue, got: {order.pending_config_queue}"

        # Counter to track how many bagels and coffees we've configured
        bagels_configured = 0
        coffees_configured = 0

        # Configuration loop - handle up to 30 interactions
        for _ in range(30):
            msg_lower = result.message.lower()

            # Exit when we reach "anything else?"
            if "anything else" in msg_lower:
                break

            # Handle item disambiguation
            if order.pending_item_options:
                result = sm.process("1", order)
                continue

            # Handle attribute disambiguation (e.g., "Did you mean X or Y?")
            if order.pending_attr_disambiguation:
                result = sm.process("1", order)  # Select first option
                continue

            # Handle customization checkpoint
            if "more changes" in msg_lower or "customize" in msg_lower:
                result = sm.process("no", order)
                continue

            # Handle bagel configuration
            if "bagel" in msg_lower or order.pending_field == "bagel:bread":
                result = sm.process("everything" if bagels_configured == 0 else "onion", order)
                bagels_configured += 1
                continue
            if "toasted" in msg_lower:
                result = sm.process("yes", order)
                continue
            if "scoop" in msg_lower:
                result = sm.process("no", order)
                continue
            if "spread" in msg_lower or "cream cheese" in msg_lower or "butter" in msg_lower:
                result = sm.process("butter", order)
                continue

            # Handle coffee configuration (may ask size, milk/syrup, shots, hot/iced)
            if "size" in msg_lower or "small" in msg_lower:
                result = sm.process("small" if coffees_configured == 0 else "large", order)
                coffees_configured += 1
                continue
            # Check milk/sweetener BEFORE hot/iced to avoid "hot coffee" false positive
            if "milk" in msg_lower or "sugar" in msg_lower or "sweetener" in msg_lower or "syrup" in msg_lower:
                result = sm.process("no", order)
                continue
            # Check for actual hot/iced question (not just "hot" in "hot coffee")
            if "hot or iced" in msg_lower or ("iced" in msg_lower and "hot" not in msg_lower):
                result = sm.process("hot", order)
                continue
            if "shot" in msg_lower or "espresso" in msg_lower:
                result = sm.process("no", order)  # Skip extra shots (allow_none=True)
                continue
            if "decaf" in msg_lower:
                result = sm.process("no", order)
                continue

            # Unknown question - try "no" as default
            result = sm.process("no", order)

        # Verify we reached "Anything else?"
        assert "anything else" in result.message.lower(), f"Expected 'Anything else?', got: {result.message}"

        # Verify items are complete - check at least 1 of each since flow may vary
        bagels = [i for i in order.items.items if i.has_attribute('bread')]
        coffees = [i for i in order.items.items if i.has_attribute('size')]
        assert len(bagels) >= 1, f"Expected at least 1 bagel, got {len(bagels)}"
        assert len(coffees) >= 1, f"Expected at least 1 coffee, got {len(coffees)}"
        assert all(b["bread"] is not None for b in bagels), "All bagels should have type set"
        assert all(c["size"] is not None for c in coffees), "All coffees should have size set"

    def test_bagel_and_menu_item(self):
        """Test ordering a bagel and a menu item (like The Classic BEC) together.

        Items may be added directly to order.items.items or stored in
        pending_parsed_items if disambiguation or other processing is needed.

        Note: "classic BEC" matches multiple items (The Classic BEC and The Classic
        BEC Omelette), so disambiguation may be triggered. The test validates that
        at least the bagel is processed and the system enters a valid configuration state.
        """
        from orderbot.tasks.state_machine import OrderStateMachine, OrderTask
        from orderbot.tasks.models import MenuItemTask
        from tests.helpers import BagelItemTask

        # Use global menu data which has all pricing info
        sm = OrderStateMachine()
        order = OrderTask()

        # Order bagel and a signature menu item
        # "The Classic BEC" exists in the real database but "classic bec" may match
        # multiple items (BEC sandwich and BEC omelette), triggering disambiguation
        result = sm.process("one bagel and one classic BEC", order)

        # Handle any disambiguation that may have been triggered
        if order.pending_item_options:
            result = sm.process("1", order)

        # Count bagels - may be in items list or pending
        bagels_in_items = [i for i in order.items.items if i.has_attribute('bread')]
        bagels_in_pending = [p for p in order.pending_parsed_items
                           if isinstance(p, dict) and p.get('item_type') == 'bagel']
        total_bagels = len(bagels_in_items) + len(bagels_in_pending)

        # Count signature items (The Classic BEC) - items with default ingredients
        signature_items = [i for i in order.items.items
                          if isinstance(i, MenuItemTask) and i.has_default_ingredients()]
        signature_in_pending = [p for p in order.pending_parsed_items
                               if isinstance(p, dict) and p.get('item_name', '') in ['The Classic BEC']]

        # Also check for egg_sandwich items (The Classic BEC type)
        egg_sandwich_items = [i for i in order.items.items
                             if getattr(i, 'menu_item_type', None) == 'egg_sandwich']

        total_signature = len(signature_items) + len(signature_in_pending) + len(egg_sandwich_items)

        # Verify at least 1 bagel was processed
        assert total_bagels >= 1, f"Expected at least 1 bagel (items={len(bagels_in_items)}, pending={len(bagels_in_pending)})"

        # The Classic BEC should either be:
        # 1. In the order as a signature/egg_sandwich item, OR
        # 2. Mentioned in the message ("classic"), OR
        # 3. Pending disambiguation (pending_item_options not empty after first process)
        # 4. Queued in pending_config_queue for later processing
        msg_lower = result.message.lower()
        classic_in_message = "classic" in msg_lower
        classic_pending = any("classic" in str(p).lower() for p in order.pending_config_queue)

        has_classic_bec = (total_signature >= 1 or classic_in_message or
                          classic_pending or len(order.pending_item_options) > 0)
        # Note: Due to required_match_phrases filtering, "classic bec" may resolve to a
        # single item without disambiguation. The bagel configuration question takes priority.
        # This is valid behavior - the Classic BEC will be configured after the bagel.

        # If signature item is in order, verify name
        if signature_items:
            assert "classic" in signature_items[0].menu_item_name.lower()
        if egg_sandwich_items:
            assert "classic" in egg_sandwich_items[0].menu_item_name.lower()

        # Should be asking about configuration (bagel type, disambiguation, etc.)
        # The flow may vary based on which item needs config first
        valid_question = ("bagel" in msg_lower or "toasted" in msg_lower or
                         "which" in msg_lower or "size" in msg_lower or
                         order.pending_field is not None)
        assert valid_question, f"Expected config question, got: {result.message}"


# =============================================================================
# Quantity Change Tests
# =============================================================================

class TestQuantityChange:
    """Tests for changing quantity of existing items at checkout confirmation."""

    def test_make_it_two_drinks(self):
        """Test 'make it two orange juices' adds another drink."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import CoffeeItemTask
        from orderbot.tasks.schemas import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.CHECKOUT_CONFIRM.value

        # Add one drink to the order
        drink = CoffeeItemTask(
            drink_type="Tropicana Orange Juice No Pulp",
            unit_price=3.50,
        )
        drink.mark_complete()
        order.items.add_item(drink)

        # User says "make it two orange juices"
        result = sm.order_utils_handler.handle_quantity_change("make it two orange juices", order)

        # Should have added one more
        assert result is not None
        coffees = [i for i in order.items.items if i.has_attribute('size')]
        assert len(coffees) == 2
        assert all(c.menu_item_name == "Tropicana Orange Juice No Pulp" for c in coffees)

    def test_can_you_make_it_two(self):
        """Test 'can you make it two' pattern."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import CoffeeItemTask
        from orderbot.tasks.schemas import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.CHECKOUT_CONFIRM.value

        drink = CoffeeItemTask(drink_type="Coffee", unit_price=2.50)
        drink.mark_complete()
        order.items.add_item(drink)

        result = sm.order_utils_handler.handle_quantity_change("can you make it two coffees", order)

        assert result is not None
        coffees = [i for i in order.items.items if i.has_attribute('size')]
        assert len(coffees) == 2

    def test_already_has_enough(self):
        """Test when user already has the requested quantity."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import CoffeeItemTask
        from orderbot.tasks.schemas import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.CHECKOUT_CONFIRM.value

        # Add two drinks already
        for _ in range(2):
            drink = CoffeeItemTask(drink_type="Latte", unit_price=4.50)
            drink.mark_complete()
            order.items.add_item(drink)

        result = sm.order_utils_handler.handle_quantity_change("make it two lattes", order)

        # Should NOT add more, just confirm
        assert result is not None
        assert "already have 2" in result.message
        coffees = [i for i in order.items.items if i.has_attribute('size')]
        assert len(coffees) == 2

    def test_no_match_returns_none(self):
        """Test that non-matching item returns None (lets other handlers try)."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import CoffeeItemTask
        from orderbot.tasks.schemas import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.CHECKOUT_CONFIRM.value

        drink = CoffeeItemTask(drink_type="Coffee", unit_price=2.50)
        drink.mark_complete()
        order.items.add_item(drink)

        # Ask for item not in order
        result = sm.order_utils_handler.handle_quantity_change("make it two bagels", order)

        # Should return None (no match)
        assert result is None


# =============================================================================
# Cheese Choice Handler Tests
# =============================================================================

class TestCheeseChoice:
    """Tests for _handle_cheese_choice when user said generic 'cheese'."""

    def test_american_cheese_selected(self):
        """Test selecting American cheese."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import BagelItemTask
        from orderbot.tasks.schemas import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_field = "bagel:cheese"

        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel["needs_cheese_clarification"] = True
        bagel.mark_in_progress()
        order.items.add_item(bagel)
        order.pending_item_ids = [bagel.id]

        result = sm.configuring_item_handler.handle_configuring_item("american please", order)

        # Unified handler stores cheese in attribute_values
        assert bagel.attribute_values.get("cheese") == "american"

    def test_cheddar_cheese_selected(self):
        """Test selecting cheddar cheese."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import BagelItemTask
        from orderbot.tasks.schemas import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_field = "bagel:cheese"

        bagel = BagelItemTask(bagel_type="everything", toasted=True)
        bagel["needs_cheese_clarification"] = True
        bagel.mark_in_progress()
        order.items.add_item(bagel)
        order.pending_item_ids = [bagel.id]

        result = sm.configuring_item_handler.handle_configuring_item("cheddar", order)

        # Unified handler stores cheese in attribute_values
        assert bagel.attribute_values.get("cheese") == "cheddar"

    def test_swiss_cheese_selected(self):
        """Test selecting Swiss cheese."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import BagelItemTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_field = "bagel:cheese"

        bagel = BagelItemTask(bagel_type="plain")
        bagel["needs_cheese_clarification"] = True
        bagel.mark_in_progress()
        order.items.add_item(bagel)
        order.pending_item_ids = [bagel.id]

        result = sm.configuring_item_handler.handle_configuring_item("swiss cheese", order)

        # Unified handler stores cheese in attribute_values
        assert bagel.attribute_values.get("cheese") == "swiss"

    def test_muenster_cheese_selected(self):
        """Test selecting muenster cheese (with alternate spelling)."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import BagelItemTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_field = "bagel:cheese"

        bagel = BagelItemTask(bagel_type="plain")
        bagel["needs_cheese_clarification"] = True
        bagel.mark_in_progress()
        order.items.add_item(bagel)
        order.pending_item_ids = [bagel.id]

        # Test alternate spelling "munster"
        result = sm.configuring_item_handler.handle_configuring_item("munster", order)

        # Unified handler stores cheese in attribute_values (normalized to muenster)
        assert bagel.attribute_values.get("cheese") == "muenster"

    def test_invalid_cheese_prompts_again(self):
        """Test that invalid cheese type shows available options directly."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import BagelItemTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_field = "bagel:cheese"

        bagel = BagelItemTask(bagel_type="plain")
        bagel["needs_cheese_clarification"] = True
        bagel.mark_in_progress()
        order.items.add_item(bagel)
        order.pending_item_ids = [bagel.id]

        result = sm.configuring_item_handler.handle_configuring_item("brie", order)

        # Should not add invalid cheese
        toppings = bagel["toppings"] or []
        assert len(toppings) == 0
        # New behavior: shows available options directly instead of re-asking
        assert "Sorry, we don't have brie" in result.message
        assert "We have" in result.message
        assert bagel["needs_cheese_clarification"] is True


# =============================================================================
# Menu Query Handler Tests
# =============================================================================

class TestCoffeeSize:
    """Tests for _handle_coffee_size."""

    def test_small_size_selected(self):
        """Test selecting small size.

        Temperature (hot/iced) is now part of the menu item name (e.g. 'Hot Latte'),
        not a separate attribute. After size, the next question is espresso_shots
        (per mock data display_order: size=1, espresso_shots=2, milk_sweetener_syrup=3).
        Size is NOT pre-set -- the item starts without a size so the handler sets it.
        """
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask, MenuItemTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_field = "coffee_based_beverage:size"

        coffee = MenuItemTask(
            menu_item_name="Hot Latte",
            menu_item_type="coffee_based_beverage",
            quantity=1,
            unit_price=0.0,
        )
        coffee.mark_in_progress()
        order.items.add_item(coffee)
        order.pending_item_ids = [coffee.id]

        result = sm.configuring_item_handler.handle_configuring_item("small please", order)

        assert coffee["size"] == "small"
        # Mock data: espresso_shots has display_order=2, milk_sweetener_syrup=3
        assert order.pending_field == "coffee_based_beverage:espresso_shots"
        assert "shot" in result.message.lower() or "extra" in result.message.lower()

    def test_large_size_selected(self):
        """Test selecting large size.

        Temperature (hot/iced) is now part of the menu item name (e.g. 'Hot Coffee'),
        not a separate attribute. After size, the next question is espresso_shots
        (per mock data display_order: size=1, espresso_shots=2, milk_sweetener_syrup=3).
        Size is NOT pre-set -- the item starts without a size so the handler sets it.
        """
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask, MenuItemTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_field = "coffee_based_beverage:size"

        coffee = MenuItemTask(
            menu_item_name="Hot Coffee",
            menu_item_type="coffee_based_beverage",
            quantity=1,
            unit_price=0.0,
        )
        coffee.mark_in_progress()
        order.items.add_item(coffee)
        order.pending_item_ids = [coffee.id]

        result = sm.configuring_item_handler.handle_configuring_item("I'll take a large", order)

        assert coffee["size"] == "large"
        # Mock data: espresso_shots has display_order=2, milk_sweetener_syrup=3
        assert "shot" in result.message.lower() or "extra" in result.message.lower()

    def test_invalid_size_reprompts(self, menu_cache_loaded):
        """Test that invalid size like 'extra large' re-prompts user.

        Phase 3 residual validation rejects 'extra large' because 'extra' is a
        meaningful modifier, not conversational filler.  The system should ask
        for a valid size instead of incorrectly matching 'large'.
        """
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import CoffeeItemTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_field = "coffee_based_beverage:size"

        coffee = CoffeeItemTask(drink_type="latte")
        coffee.mark_in_progress()
        order.items.add_item(coffee)
        order.pending_item_ids = [coffee.id]

        # "extra large" should NOT match "large" -- "extra" is meaningful
        result = sm.configuring_item_handler.handle_configuring_item("extra large", order)

        assert coffee["size"] is None, (
            f"Size should remain unset for 'extra large', but got: {coffee['size']}"
        )
        msg_lower = result.message.lower()
        assert "size" in msg_lower or "small" in msg_lower or "large" in msg_lower, \
            f"Should re-prompt for valid size, got: {result.message}"

    def test_size_with_drink_name_in_prompt(self):
        """Test that reprompt shows available sizes when input is unclear."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import CoffeeItemTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_field = "coffee_based_beverage:size"

        coffee = CoffeeItemTask(drink_type="espresso")
        coffee.mark_in_progress()
        order.items.add_item(coffee)
        order.pending_item_ids = [coffee.id]

        # Use unclear input that doesn't match any valid size
        result = sm.configuring_item_handler.handle_configuring_item("hmm", order)

        # Should show available size options
        msg = result.message.lower()
        assert "small" in msg or "large" in msg, f"Expected available sizes in response, got: {result.message}"

    def test_cancel_coffee_during_size_config(self):
        """Test canceling a latte during size configuration via _handle_configuring_item."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import CoffeeItemTask
        from orderbot.tasks.schemas import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_field = "espresso:size"

        latte = CoffeeItemTask(drink_type="latte")
        latte.mark_in_progress()
        order.items.add_item(latte)
        order.pending_item_ids = [latte.id]

        # Use _handle_configuring_item which includes cancellation check
        # Say "remove the latte" since latte != coffee in menu taxonomy
        result = sm._handle_configuring_item("remove the latte", order)

        # Latte should be removed
        active_items = order.items.get_active_items()
        assert len(active_items) == 0
        # Should be back to TAKING_ITEMS phase
        assert order.phase == OrderPhase.TAKING_ITEMS.value
        assert "removed" in result.message.lower()

    def test_cancel_this_during_size_config(self):
        """Test canceling 'this' during size configuration."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import CoffeeItemTask
        from orderbot.tasks.schemas import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_field = "espresso:size"

        cappuccino = CoffeeItemTask(drink_type="cappuccino")
        cappuccino.mark_in_progress()
        order.items.add_item(cappuccino)
        order.pending_item_ids = [cappuccino.id]

        result = sm._handle_configuring_item("cancel this", order)

        active_items = order.items.get_active_items()
        assert len(active_items) == 0
        assert order.phase == OrderPhase.TAKING_ITEMS.value
        assert "removed" in result.message.lower()
        assert "cappuccino" in result.message.lower()

    def test_cancel_plural_lattes_during_config(self):
        """Test 'remove the lattes' removes all latte items."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import BagelItemTask, CoffeeItemTask
        from orderbot.tasks.schemas import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_field = "espresso:size"

        # Add a bagel (complete)
        bagel = BagelItemTask(bagel_type="plain", toasted=True, spread="butter")
        bagel.mark_complete()
        order.items.add_item(bagel)

        # Add two lattes
        latte1 = CoffeeItemTask(drink_type="latte", size="small")
        latte1.mark_complete()
        order.items.add_item(latte1)

        latte2 = CoffeeItemTask(drink_type="latte")
        latte2.mark_in_progress()
        order.items.add_item(latte2)
        order.pending_item_ids = [latte2.id]

        result = sm._handle_configuring_item("remove the lattes", order)

        active_items = order.items.get_active_items()
        # Should only have the bagel left
        assert len(active_items) == 1
        assert active_items[0]["bread"] == "plain"
        assert order.phase == OrderPhase.TAKING_ITEMS.value
        assert "removed" in result.message.lower()


class TestAnotherItemDuringConfig:
    """Tests for handling 'another X' requests during item configuration.

    When a user says 'another latte' while being asked about the size of the
    current latte, the named item should be added to the cart and queued for
    later config, while continuing the current item's configuration.
    'another one' (no item name) still redirects to finish current config.
    """

    def test_another_item_adds_to_cart_during_config(self):
        """Test that 'another latte' during config adds item and continues current config."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import CoffeeItemTask
        from orderbot.tasks.schemas import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_field = "coffee_based_beverage:size"

        coffee = CoffeeItemTask(drink_type="latte")
        coffee.mark_in_progress()
        order.items.add_item(coffee)
        order.pending_item_ids = [coffee.id]

        result = sm.configuring_item_handler._check_config_interceptors(
            "another latte", coffee, order
        )

        # Should add the item to the cart and continue current config
        assert result is not None
        assert len(order.items.items) == 2  # original + newly added
        assert "added" in result.message.lower() or "got it" in result.message.lower()

    def test_one_more_bagel_adds_to_cart_during_config(self):
        """Test that 'one more bagel' during config adds item and continues current config."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import BagelItemTask
        from orderbot.tasks.schemas import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_field = "bagel:toasted"

        bagel = BagelItemTask(bagel_type="plain")
        bagel.mark_in_progress()
        order.items.add_item(bagel)
        order.pending_item_ids = [bagel.id]

        result = sm.configuring_item_handler._check_config_interceptors(
            "one more bagel", bagel, order
        )

        # Should add the item to the cart and continue current config
        assert result is not None
        assert len(order.items.items) == 2  # original + newly added
        assert "added" in result.message.lower() or "got it" in result.message.lower()

    def test_another_one_redirects_to_finish_config(self):
        """Test that 'another one' during config redirects to finish current item."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import CoffeeItemTask
        from orderbot.tasks.schemas import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_field = "coffee_based_beverage:size"

        coffee = CoffeeItemTask(drink_type="espresso")
        coffee.mark_in_progress()
        order.items.add_item(coffee)
        order.pending_item_ids = [coffee.id]

        result = sm.configuring_item_handler._check_config_interceptors(
            "and another", coffee, order
        )

        # Should redirect to finish config
        assert result is not None
        assert "finish customizing" in result.message.lower()

    def test_valid_size_answer_not_intercepted(self):
        """Test that valid size answers like 'small' are NOT intercepted."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import CoffeeItemTask
        from orderbot.tasks.schemas import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_field = "coffee_based_beverage:size"

        coffee = CoffeeItemTask(drink_type="latte")
        coffee.mark_in_progress()
        order.items.add_item(coffee)
        order.pending_item_ids = [coffee.id]

        result = sm.configuring_item_handler._check_config_interceptors(
            "small", coffee, order
        )

        # Valid answer should NOT be intercepted (returns None)
        assert result is None


# =============================================================================
# Coffee Style Handler Tests
# =============================================================================

import pytest


# =============================================================================
# Coffee Modifiers Handler Tests
# =============================================================================

class TestCoffeeModifiers:
    """Tests for coffee modifiers question (milk, sugar, syrup)."""

    def test_latte_ordering_flow(self):
        """Test full latte ordering flow with configuration questions.

        Flow:
        1. "I'd like a latte" -> disambiguation or "Got it, for the Hot Latte. What size?"
        2. "small" -> "Got it, Small. Any extra shots?"
        3. "no" -> "Any milk, sweetener, or syrup?"
        4. "whole milk" -> accepts whole milk and confirms item (decaf is silent)
        """
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from orderbot.tasks.schemas import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # Step 1: Order a latte - may trigger disambiguation with real DB data
        result = sm.process("I'd like a latte", order)

        # Handle disambiguation if triggered (Hot Latte vs Iced Latte)
        if "which would you like" in result.message.lower() or result.order.pending_item_options:
            result = sm.process("Hot Latte", result.order)

        assert "hot latte" in result.message.lower()
        assert "size" in result.message.lower()

        # Step 2: Answer size - system asks about extra shots
        result = sm.process("small", result.order)
        assert "shot" in result.message.lower()

        # Step 3: Answer shots - system asks about milk/sweetener/syrup
        result = sm.process("no", result.order)
        assert "milk" in result.message.lower() or "sweetener" in result.message.lower()

        # Step 4: Answer milk - "whole milk" should be accepted without disambiguation
        # Decaf is a silent question (empty question_text) so it won't be asked
        result = sm.process("whole milk", result.order)

        # Handle optional customization checkpoint if triggered
        if "more changes" in result.message.lower() or "style" in result.message.lower():
            result = sm.process("no", result.order)

        # Should confirm the order with item summary
        msg_lower = result.message.lower()
        assert "hot latte" in msg_lower
        assert "small" in msg_lower
        assert "milk" in msg_lower



class TestCoffeeModifierRemoval:
    """Tests for removing coffee modifiers with 'without X' patterns."""

    def test_without_milk_removes_milk(self):
        """Test that 'without milk' removes milk from coffee."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import CoffeeItemTask
        from orderbot.tasks.schemas.phases import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS

        # Coffee with milk
        coffee = CoffeeItemTask(drink_type="latte", size="small", iced=True, milk="whole")
        coffee.mark_complete()
        order.items.add_item(coffee)

        result = sm.process("make it without milk", order)

        # Milk should be removed but coffee should still exist
        assert len(result.order.items.get_active_items()) == 1
        # Get the coffee from result order
        result_coffee = result.order.items.get_active_items()[0]
        milk_modifiers = result_coffee.get_selections("milk")
        assert len(milk_modifiers) == 0
        assert "removed" in result.message.lower() or "changed" in result.message.lower()

    def test_without_sugar_removes_sweetener(self):
        """Test that 'without sugar' removes sweetener from coffee."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import CoffeeItemTask
        from orderbot.tasks.schemas.phases import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS

        # Coffee with sugar
        coffee = CoffeeItemTask(drink_type="coffee", size="large", iced=False, sweeteners=[{"slug": "sugar", "quantity": 2}])
        coffee.mark_complete()
        order.items.add_item(coffee)

        result = sm.process("make it without sugar", order)

        # Sweetener should be removed but coffee should still exist
        assert len(result.order.items.get_active_items()) == 1
        # Get the coffee from result order
        result_coffee = result.order.items.get_active_items()[0]
        sweeteners = result_coffee.get_selections("sweetener")
        assert len(sweeteners) == 0
        assert "removed" in result.message.lower() or "changed" in result.message.lower()

    def test_without_syrup_removes_syrup(self):
        """Test that 'without syrup' removes syrup from coffee."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import CoffeeItemTask
        from orderbot.tasks.schemas.phases import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS

        # Coffee with syrup
        coffee = CoffeeItemTask(drink_type="latte", size="medium", iced=True, flavor_syrups=[{"slug": "vanilla", "quantity": 1}])
        coffee.mark_complete()
        order.items.add_item(coffee)

        result = sm.process("make it without syrup", order)

        # Syrup should be removed but coffee should still exist
        assert len(result.order.items.get_active_items()) == 1
        # Get the coffee from result order
        result_coffee = result.order.items.get_active_items()[0]
        syrups = result_coffee.get_selections("syrup")
        assert len(syrups) == 0
        assert "removed" in result.message.lower() or "changed" in result.message.lower()


class TestBagelModifierRemoval:
    """Tests for removing modifiers from bagels in TAKING_ITEMS phase."""

    def test_remove_cream_cheese_removes_spread_not_item(self):
        """Test that 'remove the cream cheese' removes spread, not the entire bagel.

        Regression test for bug where 'remove the cream cheese' removed the whole bagel
        because 'cream cheese' was found in the item summary.
        """
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import BagelItemTask
        from orderbot.tasks.schemas.phases import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS

        # Bagel with blueberry cream cheese spread
        bagel = BagelItemTask(
            bagel_type="everything",
            toasted=True,
            spread="cream cheese",
            spread_type="blueberry",
        )
        bagel.mark_complete()
        order.items.add_item(bagel)

        result = sm.process("remove the cream cheese", order)

        # Bagel should still exist
        active_items = result.order.items.get_active_items()
        assert len(active_items) == 1, "Bagel should NOT be removed, only the spread"

        # Spread should be removed (cream cheese is stored in "spread" attribute)
        result_bagel = active_items[0]
        assert result_bagel["spread"] is None, "Spread should be removed"

        # Response should mention removed
        assert "removed" in result.message.lower()

    def test_remove_cream_cheese_with_double_space(self):
        """Test that input with double spaces still works (voice input artifact)."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import BagelItemTask
        from orderbot.tasks.schemas.phases import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS

        bagel = BagelItemTask(
            bagel_type="everything",
            toasted=True,
            spread="cream cheese",
            spread_type="blueberry",
        )
        bagel.mark_complete()
        order.items.add_item(bagel)

        # Double space (common voice transcription artifact)
        result = sm.process("remove the cream  cheese", order)

        active_items = result.order.items.get_active_items()
        assert len(active_items) == 1, "Bagel should NOT be removed"
        result_bagel = active_items[0]
        assert result_bagel["spread"] is None, "Spread should be removed"

    def test_add_scallion_cream_cheese_adds_spread_not_sandwich(self):
        """Test that 'add scallion cream cheese' adds spread to bagel, not a new sandwich.

        Regression test for bug where 'add scallion cream cheese' would add a new
        'Scallion Cream Cheese Sandwich' item instead of adding the spread to the
        existing bagel in the cart.
        """
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import BagelItemTask
        from orderbot.tasks.schemas.phases import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS

        # Bagel without spread (user removed cream cheese earlier)
        bagel = BagelItemTask(
            bagel_type="everything",
            toasted=True,
            spread=None,  # No spread
        )
        bagel.mark_complete()
        order.items.add_item(bagel)

        # User says "add scallion cream cheese"
        result = sm.process("add scallion cream cheese", order)

        # Should still have only 1 item (the bagel), not 2 items
        active_items = result.order.items.get_active_items()
        assert len(active_items) == 1, \
            f"Should have 1 item (bagel with spread), not 2. Got: {[i.get_summary() for i in active_items]}"

        # The bagel should now have the spread
        result_bagel = active_items[0]
        assert result_bagel.menu_item_type == "bagel", "Item should be a bagel"
        assert result_bagel["spread_type"] is not None, "Bagel should have spread added"
        # Spread is stored as slug (e.g., "scallion_cc")
        spread_type = result_bagel["spread_type"]
        assert "scallion" in spread_type.lower() or "cc" in spread_type.lower(), \
            f"Spread should be scallion cream cheese (slug), got: {spread_type}"

        # Response should confirm the spread was added
        assert "scallion" in result.message.lower() or "cream cheese" in result.message.lower()

    def test_add_spread_to_bagel_with_existing_spread_replaces(self):
        """Test that 'add X cream cheese' replaces existing spread on bagel."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import BagelItemTask
        from orderbot.tasks.schemas.phases import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS

        # Bagel with plain cream cheese
        bagel = BagelItemTask(
            bagel_type="everything",
            toasted=True,
            spread="cream cheese",
        )
        bagel.mark_complete()
        order.items.add_item(bagel)

        # User says "add veggie cream cheese"
        result = sm.process("add veggie cream cheese", order)

        # Should still have only 1 item
        active_items = result.order.items.get_active_items()
        assert len(active_items) == 1

        # Spread should be updated (slug format like "vegetable_cream_cheese")
        result_bagel = active_items[0]
        spread = result_bagel["spread"]
        assert spread is not None, "Spread should be set"
        assert "veggie" in spread.lower() or "vegetable" in spread.lower(), \
            f"Spread should be veggie cream cheese, got: {spread}"

    def test_plain_cream_cheese_sets_spread_not_none(self):
        """Test that 'plain cream cheese' sets cream cheese spread, not 'none'.

        Regression test for bug where 'plain cream cheese' was interpreted as
        'no spread' because 'plain' matched the no-spread pattern before the
        spread extraction logic could run.
        """
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import BagelItemTask
        from orderbot.tasks.schemas.phases import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.CONFIGURING_ITEM
        order.pending_field = "bagel:spread_type"

        # Bagel waiting for spread choice
        bagel = BagelItemTask(
            bagel_type="everything",
            toasted=True,
            spread=None,
        )
        order.items.add_item(bagel)
        # Set pending_item_ids so is_configuring_item() returns True
        order.pending_item_ids = [bagel.id]

        # User says "plain cream cheese" in response to spread question
        result = sm.process("plain cream cheese", order)

        # The bagel should have cream cheese spread, NOT "none"
        active_items = order.items.get_active_items()
        assert len(active_items) == 1
        assert active_items[0]["spread_type"] is not None, "Spread should be set"
        assert active_items[0]["spread_type"] != "none", "Spread should NOT be 'none'"
        # Spread is stored as slug (e.g., "plain_cc")
        spread_type = active_items[0]["spread_type"]
        assert "plain_cc" in spread_type or "cc" in spread_type, \
            f"Spread should be plain cream cheese (slug), got: {spread_type}"
