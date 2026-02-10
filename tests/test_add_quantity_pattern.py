"""
Tests for the "add N" / "add N more" quantity pattern.

When user says "add 3" with items in cart:
- 1 unique item type -> add 3 more of that item
- 2+ unique item types -> ask disambiguation question
- 0 items -> fall through to normal parsing
"""

import pytest

from orderbot.tasks.state_machine import OrderStateMachine
from orderbot.tasks.models import OrderTask, MenuItemTask
from orderbot.tasks.schemas import OrderPhase
from orderbot.tasks.pending_fields import PendingField
from orderbot.tasks.early_pattern_handler import (
    ADD_QUANTITY_PATTERN,
    _parse_quantity,
)


class TestAddQuantityPattern:
    """Tests for the ADD_QUANTITY_PATTERN regex."""

    @pytest.mark.parametrize("input_text,expected_qty", [
        ("add 3", 3),
        ("add 1", 1),
        ("add 5 more", 5),
        ("add 2 of those", 2),
        ("add 3 of them", 3),
        ("add 4 please", 4),
        ("add 3 more please", 3),
        ("add two", 2),
        ("add three more", 3),
        ("add one", 1),
        ("add 10 of these", 10),
    ])
    def test_pattern_matches(self, input_text, expected_qty):
        """Test that pattern correctly matches various inputs."""
        match = ADD_QUANTITY_PATTERN.match(input_text)
        assert match is not None, f"Pattern should match '{input_text}'"
        qty = _parse_quantity(match.group(1))
        assert qty == expected_qty, f"Expected quantity {expected_qty}, got {qty}"

    @pytest.mark.parametrize("input_text", [
        "add a bagel",
        "add bacon",
        "add cream cheese",
        "add vanilla syrup",
        "add the classic",
        "add more bacon",  # No number
        "another one",
        "one more",
        # "get N" and "give me N" are handled by MAKE_IT_N_PATTERN, not this one
        "get 2",
        "give me 3",
    ])
    def test_pattern_does_not_match_items(self, input_text):
        """Test that pattern does NOT match item orders or modifier additions."""
        match = ADD_QUANTITY_PATTERN.match(input_text)
        assert match is None, f"Pattern should NOT match '{input_text}'"


class TestAddQuantityWithOneItemType:
    """Tests for 'add N' when there's exactly one item type in cart."""

    def test_add_3_with_single_item_creates_copies(self):
        """When cart has 1 item type and user says 'add 3', add 3 copies."""
        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # Create a menu item with menu_item_id set (simulating item from DB)
        item = MenuItemTask(
            menu_item_name="Dr. Brown's Cel-Ray",
            menu_item_type="soda",
            menu_item_id=123,
            unit_price=3.00,
        )
        item.mark_complete()
        order.items.add_item(item)

        initial_count = len(order.items.items)
        assert initial_count == 1

        result = sm.process("add 3", order)

        # Should have added 3 more (total 4)
        assert len(result.order.items.items) == 4
        assert "added" in result.message.lower()
        assert "3" in result.message

    def test_add_1_with_single_item_creates_one_copy(self):
        """'add 1' should add one more of the existing item."""
        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        item = MenuItemTask(
            menu_item_name="Plain Bagel",
            menu_item_type="bagel",
            menu_item_id=456,
            unit_price=2.50,
        )
        item.mark_complete()
        order.items.add_item(item)

        result = sm.process("add 1", order)

        assert len(result.order.items.items) == 2
        assert "added" in result.message.lower()

    def test_add_copies_preserves_attributes(self):
        """Copies should preserve all attributes from the original."""
        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # Create a configured bagel
        item = MenuItemTask(
            menu_item_name="Bagel",
            menu_item_type="bagel",
            menu_item_id=789,
            unit_price=4.50,
        )
        item.add_selection("everything", "bread", display_name="Everything")
        item.add_selection("yes", "toasted", display_name="Toasted")
        item.add_selection("cream_cheese", "spread", display_name="Cream Cheese")
        item.mark_complete()
        order.items.add_item(item)

        result = sm.process("add 2", order)

        assert len(result.order.items.items) == 3

        # All copies should have the same attributes
        for copied_item in result.order.items.items:
            assert copied_item.get_selection_value("bread") == "everything"
            assert copied_item.get_selection_value("toasted") == "yes"
            assert copied_item.get_selection_value("spread") == "cream_cheese"

    def test_add_2_of_those_works(self):
        """'add 2 of those' should add 2 more of the existing item."""
        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        item = MenuItemTask(
            menu_item_name="Coffee",
            menu_item_type="coffee_based_beverage",
            menu_item_id=101,
            unit_price=2.00,
        )
        item.mark_complete()
        order.items.add_item(item)

        result = sm.process("add 2 of those", order)

        assert len(result.order.items.items) == 3

    def test_add_3_more_please_works(self):
        """'add 3 more please' should add 3 more of the existing item."""
        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        item = MenuItemTask(
            menu_item_name="Cookie",
            menu_item_type="cookie",
            menu_item_id=202,
            unit_price=1.50,
        )
        item.mark_complete()
        order.items.add_item(item)

        result = sm.process("add 3 more please", order)

        assert len(result.order.items.items) == 4


class TestAddQuantityWithMultipleItemTypes:
    """Tests for 'add N' when there are multiple item types in cart."""

    def test_add_2_with_multiple_items_asks_disambiguation(self):
        """When cart has 2+ item types and user says 'add 2', ask which item."""
        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # Add two different items
        item1 = MenuItemTask(
            menu_item_name="Dr. Brown's Cel-Ray",
            menu_item_type="soda",
            menu_item_id=123,
            unit_price=3.00,
        )
        item1.mark_complete()
        order.items.add_item(item1)

        item2 = MenuItemTask(
            menu_item_name="Plain Bagel",
            menu_item_type="bagel",
            menu_item_id=456,
            unit_price=2.50,
        )
        item2.mark_complete()
        order.items.add_item(item2)

        result = sm.process("add 2", order)

        # Should ask for disambiguation
        assert "which" in result.message.lower()
        assert result.order.pending_quantity_addition == 2
        assert result.order.pending_field == PendingField.QUANTITY_ADDITION_SELECTION
        assert len(result.order.pending_item_options) == 2

        # Verify both items are in the options
        option_names = [opt["name"] for opt in result.order.pending_item_options]
        assert any("cel-ray" in name.lower() for name in option_names)
        assert any("bagel" in name.lower() for name in option_names)

    def test_disambiguation_selection_by_number(self):
        """User can select item by number in disambiguation."""
        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        item1 = MenuItemTask(
            menu_item_name="Soda",
            menu_item_type="soda",
            menu_item_id=123,
            unit_price=3.00,
        )
        item1.mark_complete()
        order.items.add_item(item1)

        item2 = MenuItemTask(
            menu_item_name="Bagel",
            menu_item_type="bagel",
            menu_item_id=456,
            unit_price=2.50,
        )
        item2.mark_complete()
        order.items.add_item(item2)

        # First, trigger disambiguation
        result = sm.process("add 3", order)
        assert result.order.pending_quantity_addition == 3

        # Then select by number (1 = first option)
        result2 = sm.process("1", order)

        # Should have added 3 copies of the first item (Soda)
        # Disambiguation is cleared
        assert result2.order.pending_quantity_addition is None
        assert result2.order.pending_field is None
        # Total: original 2 + 3 copies of first = 5
        assert len(result2.order.items.items) == 5
        assert "added" in result2.message.lower()

    def test_disambiguation_selection_by_name(self):
        """User can select item by name in disambiguation."""
        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        item1 = MenuItemTask(
            menu_item_name="Soda",
            menu_item_type="soda",
            menu_item_id=123,
            unit_price=3.00,
        )
        item1.mark_complete()
        order.items.add_item(item1)

        item2 = MenuItemTask(
            menu_item_name="Bagel",
            menu_item_type="bagel",
            menu_item_id=456,
            unit_price=2.50,
        )
        item2.mark_complete()
        order.items.add_item(item2)

        # First, trigger disambiguation
        result = sm.process("add 2", order)
        assert result.order.pending_quantity_addition == 2

        # Then select by name
        result2 = sm.process("bagel", order)

        # Should have added 2 copies of the bagel
        assert result2.order.pending_quantity_addition is None
        assert len(result2.order.items.items) == 4  # original 2 + 2 bagels
        assert "added" in result2.message.lower()

    def test_multiple_same_item_type_counts_as_one(self):
        """Multiple items of same type should count as one unique type."""
        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # Add two sodas (same menu_item_id)
        for _ in range(2):
            item = MenuItemTask(
                menu_item_name="Soda",
                menu_item_type="soda",
                menu_item_id=123,  # Same ID
                unit_price=3.00,
            )
            item.mark_complete()
            order.items.add_item(item)

        # Should NOT trigger disambiguation (only 1 unique item type)
        result = sm.process("add 3", order)

        # Should add 3 more directly
        assert result.order.pending_quantity_addition is None
        assert len(result.order.items.items) == 5  # 2 original + 3 added


class TestAddQuantityWithEmptyCart:
    """Tests for 'add N' when cart is empty."""

    def test_add_3_with_empty_cart_falls_through(self):
        """When cart is empty, 'add 3' should fall through to normal parsing."""
        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # No items in cart
        assert len(order.items.items) == 0

        result = sm.process("add 3", order)

        # Should fall through - the message won't contain "added N more"
        # It should instead parse "add 3" as a potential item order
        # or ask what they want to order
        assert result.order.pending_quantity_addition is None
        # Cart should still be empty or have whatever was parsed
        # The exact behavior depends on the fallback parsing


class TestAddQuantityEdgeCases:
    """Edge cases for the add quantity pattern."""

    def test_items_without_menu_item_id_are_skipped(self):
        """Items without menu_item_id shouldn't count in unique items."""
        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # Item without menu_item_id
        item1 = MenuItemTask(
            menu_item_name="Mystery Item",
            menu_item_type="other",
            menu_item_id=None,  # No ID
            unit_price=1.00,
        )
        item1.mark_complete()
        order.items.add_item(item1)

        # Item with menu_item_id
        item2 = MenuItemTask(
            menu_item_name="Soda",
            menu_item_type="soda",
            menu_item_id=123,
            unit_price=3.00,
        )
        item2.mark_complete()
        order.items.add_item(item2)

        result = sm.process("add 2", order)

        # Should only see one unique item type (the one with ID)
        # So no disambiguation needed
        assert result.order.pending_quantity_addition is None
        assert len(result.order.items.items) == 4  # 2 original + 2 copies of soda

    def test_copies_get_new_unique_ids(self):
        """Each copy should have a unique item ID."""
        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        item = MenuItemTask(
            menu_item_name="Soda",
            menu_item_type="soda",
            menu_item_id=123,
            unit_price=3.00,
        )
        item.mark_complete()
        order.items.add_item(item)

        original_id = item.id

        result = sm.process("add 2", order)

        # All item IDs should be unique
        all_ids = [i.id for i in result.order.items.items]
        assert len(all_ids) == len(set(all_ids)), "All item IDs should be unique"
        assert original_id in all_ids

    def test_add_more_with_word_quantity(self):
        """Test 'add three more' with word quantity."""
        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        item = MenuItemTask(
            menu_item_name="Cookie",
            menu_item_type="cookie",
            menu_item_id=303,
            unit_price=1.50,
        )
        item.mark_complete()
        order.items.add_item(item)

        result = sm.process("add three more", order)

        assert len(result.order.items.items) == 4  # 1 + 3
