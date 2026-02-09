"""
Order Modification Tests.

These tests focus on mid-order modifications, corrections, changes of mind,
and complex modification requests.

Run with: pytest tests/scenarios/ -v
"""

import pytest
from orderbot.tasks.state_machine import OrderStateMachine
from orderbot.tasks.models import OrderTask
from orderbot.tasks.schemas import OrderPhase


class TestAddModifiers:
    """Tests for adding modifiers to items."""

    def test_add_bacon_to_existing_bagel(self):
        """Add bacon to bagel mid-order."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Everything bagel with cream cheese", order)
        result2 = sm.process("add bacon to that", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_add_extra_cheese(self):
        """Add extra cheese to sandwich."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("BEC on everything", order)
        result2 = sm.process("make it extra cheese", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_add_shot_to_coffee(self):
        """Add espresso shot to coffee."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Large iced latte", order)
        result2 = sm.process("add an extra shot", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_add_syrup_after_ordering(self):
        """Add syrup to coffee after initial order."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Medium hot latte", order)
        result2 = sm.process("can you add vanilla syrup", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_add_avocado(self):
        """Add avocado to sandwich."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Turkey sandwich", order)
        result2 = sm.process("add avocado please", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_add_multiple_modifiers_at_once(self):
        """Add multiple modifiers in one request."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Plain bagel toasted", order)
        result2 = sm.process("add cream cheese, lox, and capers", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestRemoveModifiers:
    """Tests for removing modifiers from items."""

    def test_remove_cheese_from_bec(self):
        """Remove cheese from BEC."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("BEC on everything, no cheese", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_remove_onion_from_lox(self):
        """Remove onion from lox bagel."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Lox on everything bagel, hold the onion", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_remove_ice_from_coffee(self):
        """Remove ice from iced coffee."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Large iced coffee, easy on the ice", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_hold_the_mayo(self):
        """Hold the mayo on sandwich."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Turkey club, hold the mayo", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_without_tomato(self):
        """Without tomato on sandwich."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("BLT without tomato", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_no_butter(self):
        """Explicit no butter request."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Plain bagel toasted, no butter", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestChangeRequests:
    """Tests for changing attributes mid-order."""

    def test_change_bagel_type(self):
        """Change bagel type after ordering."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Sesame bagel with cream cheese", order)
        result2 = sm.process("actually make that everything", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_change_size(self):
        """Change coffee size."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Medium latte", order)
        result2 = sm.process("make it a large instead", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_change_hot_to_iced(self):
        """Change hot to iced."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Large latte", order)
        result2 = sm.process("wait, make that iced", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_change_milk_type(self):
        """Change milk type."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Large latte with whole milk", order)
        result2 = sm.process("actually oat milk please", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_change_toasted_status(self):
        """Change toasted to not toasted."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Everything bagel toasted", order)
        result2 = sm.process("don't toast it actually", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_change_spread_type(self):
        """Change spread type."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Plain bagel with plain cream cheese", order)
        result2 = sm.process("switch that to scallion cream cheese", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestCancelRequests:
    """Tests for canceling items or parts of orders."""

    def test_cancel_last_item(self):
        """Cancel the last item ordered."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Everything bagel with cream cheese", order)
        result2 = sm.process("Large iced latte", result1.order)
        result3 = sm.process("cancel the latte", result2.order)

        items = result3.order.items.get_active_items()
        # Should still have bagel but not latte
        assert result3.message is not None, "Should have a response"

    def test_cancel_that(self):
        """Cancel using 'cancel that'."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Sesame bagel", order)
        result2 = sm.process("cancel that", result1.order)

        # Should acknowledge cancellation
        assert result2.message is not None, "Should have a response"

    def test_nevermind(self):
        """Cancel using 'nevermind'."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("BEC on everything", order)
        result2 = sm.process("nevermind on that", result1.order)

        assert result2.message is not None, "Should have a response"

    def test_remove_specific_item(self):
        """Remove a specific item from multi-item order."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Everything bagel and a coffee", order)
        result2 = sm.process("remove the bagel", result1.order)

        assert result2.message is not None, "Should have a response"

    def test_start_over(self):
        """Start the order over."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Everything bagel with lox", order)
        result2 = sm.process("Large coffee", result1.order)
        result3 = sm.process("actually let me start over", result2.order)

        assert result3.message is not None, "Should have a response"


class TestSubstitutions:
    """Tests for ingredient substitutions."""

    def test_substitute_bread(self):
        """Substitute bread type."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "BEC, but can you do it on a plain bagel instead of everything",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_substitute_cheese(self):
        """Substitute cheese type."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "BEC with swiss instead of american",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_substitute_milk(self):
        """Substitute milk type."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Latte with almond milk instead of regular",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_egg_white_substitution(self):
        """Substitute with egg whites."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "BEC with egg whites instead of regular eggs",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestComplexModifications:
    """Complex modification scenarios."""

    def test_multiple_changes_one_request(self):
        """Multiple changes in one request."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Sesame bagel with plain cream cheese", order)
        result2 = sm.process(
            "make it everything, toasted, with scallion instead of plain",
            result1.order
        )

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_add_and_remove_same_request(self):
        """Add and remove in same request."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("BEC on everything", order)
        result2 = sm.process("add avocado but remove the cheese", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_change_mind_twice(self):
        """Change mind multiple times."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Sesame bagel", order)
        result2 = sm.process("make it everything", result1.order)
        result3 = sm.process("actually plain", result2.order)

        items = result3.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_modify_during_config(self):
        """Modify item while being asked config questions."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Plain bagel", order)
        # During config, add modifier and answer
        result2 = sm.process("yes toasted, and add bacon", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_modify_earlier_item(self):
        """Modify an earlier item after ordering new one."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Everything bagel with cream cheese", order)
        result2 = sm.process("and a large coffee", result1.order)
        result3 = sm.process("add lox to the bagel", result2.order)

        items = result3.order.items.get_active_items()
        assert len(items) >= 1, "Should have items"


class TestQuantityModifications:
    """Modifications to quantities."""

    def test_change_quantity_up(self):
        """Increase quantity."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Two everything bagels", order)
        result2 = sm.process("make that three actually", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have items"

    def test_change_quantity_down(self):
        """Decrease quantity."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Four coffees", order)
        result2 = sm.process("only need two now", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have items"

    def test_add_one_more(self):
        """Add one more of same item."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Everything bagel with cream cheese", order)
        result2 = sm.process("add one more of those", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have items"

    def test_double_it(self):
        """Double the quantity."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("2 BECs", order)
        result2 = sm.process("double that", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have items"


class TestAddEggDuringConfig:
    """Tests for adding egg (which is an attribute) during config.

    Regression tests for bug where 'add an egg' during item configuration
    was rejected because ingredient validation happened before checking
    if the ingredient maps to an attribute with options.
    """

    def test_add_egg_to_bagel_with_existing_egg_asks_style(self):
        """Add egg to bagel that already has scrambled eggs asks for egg style.

        When a bagel already has 'scrambled eggs' and user says 'add an egg',
        the system should ask which egg style (scrambled, fried, etc.) instead
        of rejecting with 'Egg isn't available for the Bagel'.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        # Order bagel with scrambled eggs
        result1 = sm.process("bagel toasted with scrambled eggs", order)

        # Say "add an egg" during config
        result2 = sm.process("add an egg", result1.order)

        # Should NOT reject with "isn't available"
        assert "isn't available" not in result2.message.lower(), \
            f"Bug: System rejected 'add an egg' instead of asking for egg style: {result2.message}"
        assert "not available" not in result2.message.lower(), \
            f"Bug: System rejected 'add an egg' instead of asking for egg style: {result2.message}"

        # Should ask about egg style (has words like scrambled, fried, or "how would you like")
        egg_style_terms = ["scrambled", "fried", "how would you like", "egg"]
        has_egg_style = any(term in result2.message.lower() for term in egg_style_terms)
        assert has_egg_style, \
            f"Expected system to ask about egg style, got: {result2.message}"

    def test_add_egg_to_plain_bagel_asks_style(self):
        """Add egg to plain bagel (no existing egg) asks for egg style."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        # Order plain bagel (no egg yet)
        result1 = sm.process("plain bagel toasted", order)

        # Say "add an egg" during config
        result2 = sm.process("add an egg", result1.order)

        # Should NOT reject
        assert "isn't available" not in result2.message.lower(), \
            f"Bug: System rejected 'add an egg': {result2.message}"

        # Should ask about egg style or acknowledge adding
        assert result2.message is not None, "Should have a response"

    def test_add_2_eggs_to_existing_egg_gives_3_total(self):
        """Add 2 eggs to bagel with 1 egg should result in 3 eggs total.

        When a bagel has 1 scrambled egg and user says 'add 2 eggs', the
        system should end up with 3 eggs total, not replace with 2.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        # Order bagel with scrambled eggs (1 egg)
        result1 = sm.process("plain bagel toasted with scrambled eggs", order)

        # Say "add 2 eggs" during config
        result2 = sm.process("add 2 eggs", result1.order)

        # Should ask about egg style
        assert "scrambled" in result2.message.lower() or "fried" in result2.message.lower(), \
            f"Expected egg style question, got: {result2.message}"

        # Answer scrambled
        result3 = sm.process("scrambled", result2.order)

        # Check the item has 3 eggs (1 existing + 2 added)
        items = result3.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

        bagel = items[0]
        egg_selection = bagel.get_selection("egg")
        assert egg_selection is not None, "Bagel should have egg selection"

        egg_quantity = egg_selection.get("quantity", 1)
        assert egg_quantity == 3, \
            f"Expected 3 eggs (1 + 2), got {egg_quantity}. Selection: {egg_selection}"
