"""
Resiliency Test Batch 9: Affirmative/Negative Responses

Tests the system's ability to handle yes/no and confirmation responses.
"""

import pytest
from sandwich_bot.tasks.state_machine import OrderStateMachine, OrderPhase
from sandwich_bot.tasks.models import OrderTask, BagelItemTask, CoffeeItemTask


class TestAffirmativeNegativeResponses:
    """Batch 9: Affirmative/Negative Responses."""

    def test_yes_response_to_toasted_question(self):
        """
        Test: User says "yes" when asked if they want it toasted.

        Scenario:
        - User has bagel being configured (toasted=None)
        - User says: "yes"
        - Expected: Bagel gets toasted=True
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="plain", toasted=None)
        bagel.mark_in_progress()  # Mark as current item
        order.items.add_item(bagel)
        # Set up pending state for toasted question
        order.pending_item_ids = [bagel.id]
        order.pending_field = "toasted"

        sm = OrderStateMachine()
        result = sm.process("yes", order)

        assert result.message is not None

        # Should set toasted to True
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]
        assert bagels[0].toasted is True, "Should be toasted"

    def test_yeah_sure_response(self):
        """
        Test: User says "yeah sure" as affirmative.

        Scenario:
        - User has bagel being configured
        - User says: "yeah sure"
        - Expected: Treated as affirmative
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="everything", toasted=None)
        bagel.mark_in_progress()  # Mark as current item
        order.items.add_item(bagel)
        # Set up pending state for toasted question
        order.pending_item_ids = [bagel.id]
        order.pending_field = "toasted"

        sm = OrderStateMachine()
        result = sm.process("yeah sure", order)

        assert result.message is not None
        # Should set toasted to True and continue
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]
        assert bagels[0].toasted is True, "Should be toasted"

    def test_no_response_to_anything_else(self):
        """
        Test: User says "no" when asked if they want anything else.

        Scenario:
        - User has completed items
        - User says: "no"
        - Expected: Proceeds to checkout, doesn't add items
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="sesame", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("no", order)

        assert result.message is not None

        # Should not add new items
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]
        assert len(bagels) == 1, f"Should still have 1 bagel, got {len(bagels)}"
