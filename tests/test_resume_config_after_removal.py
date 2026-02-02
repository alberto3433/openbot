"""
Test: Resume item configuration after removing another item.

Scenario: User orders 2 plain bagels, then removes the second one.
Expected: Bot should continue asking configuration questions for the remaining bagel.
"""
import pytest
from orderbot.tasks.state_machine import OrderStateMachine
from orderbot.tasks.models import OrderTask, TaskStatus


class TestResumeConfigAfterRemoval:
    """Tests for resuming configuration after item removal."""

    def test_remove_second_bagel_continues_first_bagel_config(self):
        """
        Regression test for: removing an item during config should continue with remaining item.

        Flow:
        1. User: "2 plain bagels"
        2. Bot: "For the first plain bagel, would you like it toasted?"
        3. User: "remove bagel 2"
        4. Bot should ask about toasting (not "Anything else?")
        """
        sm = OrderStateMachine()

        # Order 2 plain bagels
        result = sm.process("2 plain bagels")
        order = result.order

        # Should have 2 bagels in the cart
        active_items = order.items.get_active_items()
        assert len(active_items) == 2, f"Expected 2 items, got {len(active_items)}"

        # At least one should be in_progress (waiting for config)
        in_progress_items = [i for i in active_items if i.status == TaskStatus.IN_PROGRESS]
        assert len(in_progress_items) > 0, "Expected at least one item to be in_progress"

        # Remove the second bagel
        result = sm.process("remove the second bagel", order=order)

        # Should have 1 bagel remaining
        remaining_items = result.order.items.get_active_items()
        assert len(remaining_items) == 1, f"Expected 1 item after removal, got {len(remaining_items)}"

        # The response should ask about toasting, NOT say "Anything else?"
        msg_lower = result.message.lower()
        print(f"Bot response: {result.message}")

        # Should mention toasted/toasting
        assert "toasted" in msg_lower or "toast" in msg_lower, \
            f"Expected toasting question, got: {result.message}"

        # Should NOT just say "anything else"
        # (It's OK to say "Anything else?" AFTER asking the config question)
        assert not msg_lower.endswith("anything else?"), \
            f"Should not end with just 'Anything else?': {result.message}"

    def test_cancel_that_continues_remaining_config(self):
        """Test 'cancel that' continues configuration of remaining item."""
        sm = OrderStateMachine()

        # Order 2 plain bagels
        result = sm.process("2 plain bagels")
        order = result.order

        # Cancel the last item
        result = sm.process("cancel that", order=order)

        # Should have 1 bagel remaining
        remaining_items = result.order.items.get_active_items()
        assert len(remaining_items) == 1, f"Expected 1 item after removal, got {len(remaining_items)}"

        # The response should continue configuration
        msg_lower = result.message.lower()
        print(f"Bot response: {result.message}")

        # Should be asking about the remaining bagel's config
        assert "toasted" in msg_lower or "toast" in msg_lower, \
            f"Expected toasting question, got: {result.message}"

    def test_remove_all_asks_what_to_order(self):
        """Test removing all items asks what to order (not configuration).

        Note: This test uses "cancel that" twice because "remove everything" is not
        recognized during config phase. This is a separate issue from the main fix.
        """
        sm = OrderStateMachine()

        # Order 2 plain bagels
        result = sm.process("2 plain bagels")
        order = result.order

        # Remove first item - should continue with second item config
        result = sm.process("cancel that", order=order)

        # Should have 1 item remaining
        remaining = result.order.items.get_active_items()
        assert len(remaining) == 1, f"Expected 1 item after first removal, got {len(remaining)}"

        # Remove second item
        result = sm.process("cancel that", order=result.order)

        # Should have 0 items remaining
        remaining_items = result.order.items.get_active_items()
        assert len(remaining_items) == 0, f"Expected 0 items after removal, got {len(remaining_items)}"

        # Should ask what to order, not a config question
        msg_lower = result.message.lower()
        print(f"Bot response: {result.message}")

        assert "what would you like" in msg_lower or "what can i get" in msg_lower, \
            f"Expected 'what would you like to order' type message, got: {result.message}"
