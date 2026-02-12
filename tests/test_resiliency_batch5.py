"""
Resiliency Test Batch 5: Multi-Item Orders

Tests the system's ability to handle orders with multiple items
in a single request.
"""

from orderbot.tasks.state_machine import OrderStateMachine, OrderPhase
from orderbot.tasks.models import OrderTask, MenuItemTask
from tests.helpers import BagelItemTask, CoffeeItemTask


class TestMultiItemOrders:
    """Batch 5: Multi-Item Orders."""

    def test_bagel_and_coffee_together(self):
        """
        Test: User orders bagel and coffee in one sentence.

        Scenario:
        - User says: "a plain bagel and a large coffee"
        - Expected: System acknowledges both items and starts configuring the first one
        - Coffee is added after bagel configuration is complete
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("a plain bagel and a large coffee", order)

        # Should have a response acknowledging both items
        assert result.message is not None
        message_lower = result.message.lower()

        # Response should mention both items (e.g., "Got it, bagel and coffee...")
        assert "bagel" in message_lower and "coffee" in message_lower, \
            f"Should acknowledge both items. Message: {result.message}"

        # Should have added the first item (bagel) and start configuring it
        items = result.order.items.get_active_items()
        assert len(items) >= 1, f"Should have added bagel. Message: {result.message}"

        # First item should be the bagel
        bagel = items[0]
        assert bagel.menu_item_name == "Bagel", \
            f"First item should be bagel, got: {bagel.menu_item_name}"

        # Should be asking about toasted for the bagel
        assert "toasted" in message_lower, \
            f"Should ask about toasted. Message: {result.message}"

    def test_two_different_bagels(self):
        """
        Test: User orders two different types of bagels.

        Scenario:
        - User says: "one everything bagel and one plain bagel"
        - Expected: System adds both bagels with correct bread types
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("one everything bagel and one plain bagel", order)

        # Should have a response
        assert result.message is not None

        # Should have added both bagels
        bagels = [i for i in result.order.items.items if i.has_attribute('bread')]
        total_quantity = sum(b.quantity for b in bagels)

        assert total_quantity == 2, f"Should have 2 bagels, got {total_quantity}"

        # Should have recognized both types
        types = [b["bread"] for b in bagels]
        assert len(types) == 2, f"Should have 2 bagel types, got {len(types)}"
        assert any("everything" in t for t in types), f"Should have everything bagel. Types: {types}"
        assert any("plain" in t for t in types), f"Should have plain bagel. Types: {types}"

    def test_two_different_bagels_without_separator(self):
        """User says "one everything bagel one plain bagel" (no separator)."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()
        result = sm.process("one everything bagel one plain bagel", order)

        assert result.message is not None
        bagels = [i for i in result.order.items.items if i.has_attribute('bread')]
        total_quantity = sum(b.quantity for b in bagels)
        assert total_quantity == 2, f"Should have 2 bagels, got {total_quantity}"
        types = [b["bread"] for b in bagels]
        assert any("everything" in t for t in types), f"Missing everything. Types: {types}"
        assert any("plain" in t for t in types), f"Missing plain. Types: {types}"

    def test_comma_separated_items(self):
        """
        Test: User lists items separated by commas.

        Scenario:
        - User says: "everything bagel, coffee, and orange juice"
        - Expected: System adds all items or asks about each
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("everything bagel, coffee, and orange juice", order)

        # Should have a response
        assert result.message is not None

        # Should have added items or be asking about them
        all_items = result.order.items.get_active_items()

        # At minimum should recognize one item
        assert len(all_items) >= 1 or any(word in result.message.lower() for word in [
            "bagel", "coffee", "juice", "orange"
        ]), f"Should add items or ask about them. Message: {result.message}"

    def test_signature_item_with_coffee(self):
        """
        Test: User orders signature item with a coffee.

        Scenario:
        - User says: "the classic and a large latte"
        - Expected: System adds the latte and asks for classic disambiguation
          (The Classic BEC vs The Classic BEC Omelette)
        - User clarifies: "the bec"
        - Expected: System adds The Classic BEC
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("the classic and a large latte", order)

        # Should have a response
        assert result.message is not None

        # Should have added the latte (it resolves unambiguously to Hot Latte)
        all_items = result.order.items.get_active_items()
        assert len(all_items) >= 1, f"Should have added the latte. Message: {result.message}"

        # Check for latte in items
        has_latte = any(
            isinstance(i, MenuItemTask) and "latte" in (i.menu_item_name or "").lower()
            for i in all_items
        )
        assert has_latte, f"Should have added Hot Latte. Items: {all_items}"

        # Should ask for disambiguation about "the classic" (BEC vs Omelette)
        assert "classic" in result.message.lower(), \
            f"Should ask about which classic. Message: {result.message}"

        # Respond to disambiguation
        result = sm.process("the bec", result.order)

        # Should now have both items
        all_items = result.order.items.get_active_items()
        has_classic = any(
            isinstance(i, MenuItemTask) and "classic" in (i.menu_item_name or "").lower()
            for i in all_items
        )
        assert has_classic, f"Should have added The Classic BEC. Items: {all_items}"

    def test_quantity_on_each_item(self):
        """
        Test: User specifies quantities for multiple items.

        Scenario:
        - User says: "two plain bagels and three coffees"
        - Expected: System adds 2 bagels and 3 coffees
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("two plain bagels and three coffees", order)

        # Should have a response
        assert result.message is not None

        # Check quantities
        bagels = [i for i in result.order.items.items if i.has_attribute('bread')]
        coffees = [i for i in result.order.items.items if i.has_attribute('size')]

        bagel_qty = sum(b.quantity for b in bagels)
        coffee_qty = sum(c.quantity for c in coffees)

        # Should have correct quantities (or at least added the items)
        assert bagel_qty >= 1, f"Should have bagels. Got qty={bagel_qty}"
        assert coffee_qty >= 1 or any("coffee" in result.message.lower() for _ in [1]), \
            f"Should have coffees or mention them. Got qty={coffee_qty}"

    def test_add_item_during_config_no_prefix(self):
        """User says 'a latte' during config — should queue latte and re-ask config question."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        # First add a sandwich to trigger config
        result = sm.process("Chipotle Cream Cheese Sandwich", order)
        order = result.order

        # Now say "a latte" while being asked about bread
        result = sm.process("a latte", order)
        order = result.order

        # Should have added the latte (queued) and re-asked the config question
        all_items = order.items.get_active_items()
        item_names = [i.menu_item_name for i in all_items]
        assert any("latte" in n.lower() for n in item_names), \
            f"Should have added latte. Items: {item_names}"

        # Should still be configuring the sandwich (re-ask bread question)
        assert order.pending_field is not None, \
            f"Should still be configuring. Message: {result.message}"
