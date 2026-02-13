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

    @pytest.mark.parametrize("cancel_phrase", [
        "cancel",
        "nevermind",
        "never mind",
        "forget it",
        "skip",
        "skip this",
        "I changed my mind",
        "I changed my mind, cancel",
        "i don't want it",
        "i don't want this anymore",
    ])
    def test_standalone_cancel_during_config(self, cancel_phrase):
        """Test standalone cancel phrases cancel the current item during config.

        When being asked a config question like "What kind of bread?", standalone
        phrases like "cancel", "nevermind", or "I changed my mind" should cancel
        the current item being configured.
        """
        sm = OrderStateMachine()

        # Order a plain bagel (will trigger config question about toasting)
        result = sm.process("plain bagel")
        order = result.order

        # Should have 1 bagel in the cart, in_progress
        active_items = order.items.get_active_items()
        assert len(active_items) == 1, f"Expected 1 item, got {len(active_items)}"
        assert active_items[0].status == TaskStatus.IN_PROGRESS

        # Use standalone cancel phrase
        result = sm.process(cancel_phrase, order=order)

        # Should have 0 items remaining (item was cancelled)
        remaining_items = result.order.items.get_active_items()
        assert len(remaining_items) == 0, \
            f"Cancel phrase '{cancel_phrase}' should have cancelled the item, " \
            f"but {len(remaining_items)} items remain"

        # Response should confirm removal
        msg_lower = result.message.lower()
        print(f"Input: '{cancel_phrase}' -> Response: {result.message}")
        assert "removed" in msg_lower or "cancelled" in msg_lower, \
            f"Expected removal confirmation for '{cancel_phrase}', got: {result.message}"

    def test_standalone_cancel_with_multiple_items(self):
        """Test standalone cancel cancels only the current item, continues with next."""
        sm = OrderStateMachine()

        # Order 2 plain bagels
        result = sm.process("2 plain bagels")
        order = result.order

        # Should have 2 bagels
        assert len(order.items.get_active_items()) == 2

        # Use standalone "cancel" - should cancel current item, continue with next
        result = sm.process("cancel", order=order)

        # Should have 1 item remaining
        remaining = result.order.items.get_active_items()
        assert len(remaining) == 1, f"Expected 1 item after cancel, got {len(remaining)}"

        # Response should confirm removal AND ask about the remaining item
        msg_lower = result.message.lower()
        print(f"Bot response: {result.message}")
        assert "removed" in msg_lower, f"Expected removal confirmation, got: {result.message}"
        # Should continue with the remaining item's configuration
        assert "toast" in msg_lower, \
            f"Expected to continue with toasting question, got: {result.message}"

    @pytest.mark.parametrize("remove_phrase", [
        "actually, remove the plain bagel",
        "Actually, Remove The Plain Bagel",  # capitalized
        "um, remove the plain bagel",
        "wait, cancel the plain bagel",
        "oh, nevermind the plain bagel",
    ])
    def test_removal_with_conversational_fillers(self, remove_phrase):
        """Test removal phrases prefixed with conversational fillers.

        Phrases like "actually, remove the X" should work during configuration.
        The filler words (actually, um, wait, oh) should be stripped before
        pattern matching.
        """
        sm = OrderStateMachine()

        # Order a plain bagel (will trigger config question about toasting)
        result = sm.process("plain bagel")
        order = result.order

        # Should have 1 bagel in the cart, in_progress
        active_items = order.items.get_active_items()
        assert len(active_items) == 1, f"Expected 1 item, got {len(active_items)}"
        assert active_items[0].status == TaskStatus.IN_PROGRESS

        # Use removal phrase with filler
        result = sm.process(remove_phrase, order=order)

        # Should have 0 items remaining (item was removed)
        remaining_items = result.order.items.get_active_items()
        assert len(remaining_items) == 0, \
            f"Phrase '{remove_phrase}' should have removed the item, " \
            f"but {len(remaining_items)} items remain"

        # Response should confirm removal
        msg_lower = result.message.lower()
        print(f"Input: '{remove_phrase}' -> Response: {result.message}")
        assert "removed" in msg_lower, \
            f"Expected removal confirmation for '{remove_phrase}', got: {result.message}"

    @pytest.mark.parametrize("clear_phrase", [
        "never mind, cancel everything",
        "actually, cancel all",
        "wait, remove all",
        "um, cancel the whole order",
        "start over",
        "Start over",
        "let's start over",
        "can I start over",
    ])
    def test_clear_order_with_conversational_fillers(self, clear_phrase):
        """Test clearing entire order with filler words during configuration.

        Phrases like "never mind, cancel everything" should clear all items
        from the order during configuration phase.
        """
        sm = OrderStateMachine()

        # Order 2 items
        result = sm.process("2 plain bagels")
        order = result.order

        # Should have 2 items
        active_items = order.items.get_active_items()
        assert len(active_items) == 2, f"Expected 2 items, got {len(active_items)}"

        # Use clear phrase with filler
        result = sm.process(clear_phrase, order=order)

        # Should have 0 items remaining (all cleared)
        remaining_items = result.order.items.get_active_items()
        assert len(remaining_items) == 0, \
            f"Phrase '{clear_phrase}' should have cleared all items, " \
            f"but {len(remaining_items)} items remain"

        # Response should confirm clearing
        msg_lower = result.message.lower()
        print(f"Input: '{clear_phrase}' -> Response: {result.message}")
        assert "cleared" in msg_lower or "removed" in msg_lower or "start over" in msg_lower, \
            f"Expected clearing confirmation for '{clear_phrase}', got: {result.message}"


class TestQuantityChangeDuringConfig:
    """Tests for changing item quantity during configuration."""

    @pytest.mark.parametrize("quantity_phrase,expected_total", [
        ("make it two", 2),
        ("make it 2", 2),
        ("make it three", 3),
        ("can you make it two", 2),
        ("can you make it 2", 2),
        ("could you make it three", 3),
        ("I want 2", 2),
        ("I'll have 3", 3),
        ("give me 2", 2),
        ("let's do 2", 2),
        ("2 of those", 2),
    ])
    def test_quantity_change_during_config(self, quantity_phrase, expected_total):
        """Test quantity change phrases work during item configuration.

        When being asked a config question like "What flavor tea?", phrases like
        "make it two" should duplicate the current item.
        """
        sm = OrderStateMachine()

        # Order a hot tea (will trigger config question about flavor)
        result = sm.process("hot tea")
        order = result.order

        # Should have 1 tea in the cart
        active_items = order.items.get_active_items()
        assert len(active_items) == 1, f"Expected 1 item, got {len(active_items)}"

        # Use quantity change phrase
        result = sm.process(quantity_phrase, order=order)

        # Should have expected_total items now
        active_items = result.order.items.get_active_items()
        assert len(active_items) == expected_total, \
            f"Quantity phrase '{quantity_phrase}' should result in {expected_total} items, " \
            f"but got {len(active_items)}"

        # Response should confirm the addition
        msg_lower = result.message.lower()
        print(f"Input: '{quantity_phrase}' -> Response: {result.message}")
        assert "total" in msg_lower, \
            f"Expected confirmation of quantity for '{quantity_phrase}', got: {result.message}"

    def test_quantity_change_with_item_name(self):
        """Test 'make it two hot teas' works during config.

        This is the specific case from the bug report where the user says
        "make it two hot teas" while being asked about tea flavor.
        """
        sm = OrderStateMachine()

        # Order a hot tea
        result = sm.process("hot tea")
        order = result.order
        assert len(order.items.get_active_items()) == 1

        # Say "make it two hot teas" while being asked about flavor
        result = sm.process("make it two hot teas", order=order)

        # Should have 2 teas now
        active_items = result.order.items.get_active_items()
        assert len(active_items) == 2, \
            f"Expected 2 items after 'make it two hot teas', got {len(active_items)}"

        # Response should confirm and continue with config
        msg_lower = result.message.lower()
        print(f"Bot response: {result.message}")
        assert "total" in msg_lower, f"Expected quantity confirmation, got: {result.message}"

    def test_can_you_make_it_quantity_change(self):
        """Test 'can you make it two hot teas' works during config.

        This covers the polite request form of quantity change.
        """
        sm = OrderStateMachine()

        # Order a hot tea
        result = sm.process("hot tea")
        order = result.order
        assert len(order.items.get_active_items()) == 1

        # Say "can you make it two hot teas" while being asked about flavor
        result = sm.process("can you make it two hot teas", order=order)

        # Should have 2 teas now
        active_items = result.order.items.get_active_items()
        assert len(active_items) == 2, \
            f"Expected 2 items after 'can you make it two hot teas', got {len(active_items)}"

        # Response should confirm and continue with config
        msg_lower = result.message.lower()
        print(f"Bot response: {result.message}")
        assert "total" in msg_lower, f"Expected quantity confirmation, got: {result.message}"

    def test_quantity_change_continues_config(self):
        """Test that after quantity change, config question is still asked."""
        sm = OrderStateMachine()

        # Order a plain bagel (will ask about toasting)
        result = sm.process("plain bagel")
        order = result.order

        # Change quantity
        result = sm.process("make it 2", order=order)

        # Should still be asking about the current item's config
        msg_lower = result.message.lower()
        print(f"Bot response: {result.message}")
        # Should continue with config question (toasted, spread, etc.)
        assert any(word in msg_lower for word in ["toast", "spread", "anything"]), \
            f"Expected config question to continue, got: {result.message}"

    def test_duplicate_items_both_get_configured(self):
        """Test that when quantity is increased, both items eventually get configured.

        This is a regression test for the case where user says "make it two hot teas"
        and both teas should be configured separately.
        """
        sm = OrderStateMachine()

        # Order a hot tea
        result = sm.process("hot tea")
        order = result.order

        # Say "make it two"
        result = sm.process("make it two", order=order)
        order = result.order

        # Should have 2 teas, both IN_PROGRESS
        active_items = order.items.get_active_items()
        assert len(active_items) == 2, f"Expected 2 items, got {len(active_items)}"

        # Debug: print each item's status
        for i, item in enumerate(active_items):
            print(f"Item {i}: status={item.status}, name={item.menu_item_name}")

        # At this point, both items should be non-complete (IN_PROGRESS or PENDING)
        # The duplicate preserves the original's status, so both should be IN_PROGRESS
        non_complete_count = sum(1 for i in active_items if i.status != TaskStatus.COMPLETE)
        assert non_complete_count == 2, \
            f"Expected 2 non-complete items after 'make it two', got {non_complete_count}"

        # Answer size question for first tea (hot tea asks size first)
        result = sm.process("large", order=order)
        order = result.order
        print(f"After 'large' (first tea size): {result.message}")

        # Configure the first tea with flavor
        result = sm.process("earl grey", order=order)
        order = result.order
        print(f"After 'earl grey' (first tea flavor): {result.message}")

        # Answer the milk/sweetener question for first tea
        result = sm.process("nothing", order=order)
        order = result.order
        print(f"After 'nothing' (first tea): {result.message}")

        # Check current state
        active_items = order.items.get_active_items()
        complete_count = sum(1 for i in active_items if i.status == TaskStatus.COMPLETE)
        incomplete_count = sum(1 for i in active_items if i.status == TaskStatus.IN_PROGRESS)
        print(f"After first tea: {complete_count} complete, {incomplete_count} in progress")

        # The first tea should be complete, and we should be asked about the second tea
        # (either flavor or milk/sweetener depending on what was copied)
        msg_lower = result.message.lower()

        # Continue configuring until we're done
        max_steps = 10  # Increased to handle size + flavor + milk for both teas
        for step in range(max_steps):
            if "anything else" in msg_lower and "flavor" not in msg_lower and "type of tea" not in msg_lower and "milk" not in msg_lower and "size" not in msg_lower:
                break

            # Check what the current question is asking for
            if "size" in msg_lower:
                result = sm.process("large", order=order)
                order = result.order
                print(f"Step {step + 1} - After 'large': {result.message}")
            elif "flavor" in msg_lower or "type of tea" in msg_lower:
                result = sm.process("green tea", order=order)
                order = result.order
                print(f"Step {step + 1} - After 'green tea': {result.message}")
            elif "milk" in msg_lower or "sweetener" in msg_lower or "syrup" in msg_lower:
                result = sm.process("nothing", order=order)
                order = result.order
                print(f"Step {step + 1} - After 'nothing': {result.message}")
            else:
                print(f"Step {step + 1} - Unknown question, breaking: {result.message}")
                break
            msg_lower = result.message.lower()

        # Now both items should be complete
        active_items = order.items.get_active_items()
        complete_count = sum(1 for i in active_items if i.status == TaskStatus.COMPLETE)
        print(f"Final: {complete_count} complete out of {len(active_items)}")

        assert complete_count == 2, \
            f"Expected 2 complete items at the end, got {complete_count}"

        # Final response should be "anything else"
        msg_lower = result.message.lower()
        assert "anything else" in msg_lower, \
            f"Expected 'anything else' after both teas configured, got: {result.message}"
