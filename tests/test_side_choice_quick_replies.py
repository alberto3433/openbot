"""
Regression test: side_choice quick_replies should include BOTH Bagel and Fruit Salad.

Bug: Only "Fruit Salad" appeared as a clickable (underlined) option when the bot
asked "Would you like a bagel or fruit salad with it?" for omelette side_choice.
Root cause: "Bagel" option was missing from global_attribute_options table.
"""

from orderbot.tasks.state_machine import OrderStateMachine
from orderbot.tasks.models import OrderTask
from orderbot.tasks.schemas import OrderPhase


class TestSideChoiceQuickReplies:
    """Verify side_choice question includes both options as quick_replies."""

    def test_omelette_side_choice_has_both_quick_replies(self):
        """Both 'Bagel' and 'Fruit Salad' should appear as quick replies for side_choice."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        # Order an omelette — first question should be side_choice
        result = sm.process("cheese omelette", order)

        assert result.quick_replies is not None, (
            f"Should have quick_replies for side_choice question. Message: {result.message}"
        )
        labels = [qr["label"] for qr in result.quick_replies]
        assert "Bagel" in labels, f"'Bagel' should be in quick_replies. Got: {labels}"
        assert "Fruit Salad" in labels, f"'Fruit Salad' should be in quick_replies. Got: {labels}"
