"""Test for options inquiry pattern fix - 'what toppings are available?'"""

import pytest
from orderbot.tasks.state_machine import OrderStateMachine
from orderbot.tasks.models import OrderTask
from orderbot.tasks.schemas import OrderPhase


class TestOptionsInquiryPatterns:
    """Test that options inquiry patterns are detected correctly."""

    def test_what_toppings_are_available(self):
        """Test 'what toppings are available?' lists options, not asks another question."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        # Order a bagel
        result = sm.process("I want a bagel", order)

        # Answer bagel type
        result = sm.process("everything", result.order)

        # Answer toasted
        result = sm.process("yes", result.order)

        # Now at customization checkpoint, ask about toppings
        result = sm.process("what toppings are available?", result.order)

        # Should get a list of toppings, not "What kind of toppings?"
        message = result.message.lower()
        assert "we have" in message or ", or" in message or ", and more" in message, \
            f"Expected options list, got: {result.message}"

        # Should NOT be asking a question back
        assert "what kind" not in message, \
            f"Should not ask 'what kind', got: {result.message}"

    def test_what_toppings_do_you_have(self):
        """Test 'what toppings do you have?' pattern still works."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        # Quick setup to customization checkpoint
        result = sm.process("I want an everything bagel toasted", order)

        # Ask about toppings
        result = sm.process("what toppings do you have?", result.order)

        # Should list options
        message = result.message.lower()
        assert "we have" in message or ", or" in message, \
            f"Expected options list, got: {result.message}"

    def test_options_pagination(self):
        """Test that options inquiry supports pagination with 'more'."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        # Setup to customization checkpoint
        result = sm.process("I want an everything bagel toasted", order)

        # Ask about toppings
        result = sm.process("what toppings are available?", result.order)

        first_message = result.message

        # If there are more options, test pagination
        if "more" in first_message.lower():
            result2 = sm.process("more", result.order)
            # Second page should be different from first
            assert result2.message != first_message, \
                "Second page should show different content"
            # Should mention "also have" or similar
            assert "also" in result2.message.lower() or "finally" in result2.message.lower(), \
                f"Expected continuation phrase, got: {result2.message}"
