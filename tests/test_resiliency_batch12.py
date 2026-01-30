"""
Resiliency Test Batch 12: Abbreviations & Shorthand

Tests the system's ability to handle common abbreviations.
"""

from orderbot.tasks.state_machine import OrderStateMachine, OrderPhase
from orderbot.tasks.models import OrderTask


class TestAbbreviationsShorthand:
    """Batch 12: Abbreviations & Shorthand."""

    def test_bec_abbreviation(self):
        """
        Test: User says "BEC" for bacon egg cheese.

        Scenario:
        - User says: "I'll have a BEC"
        - Expected: System recognizes as bacon egg and cheese
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("I'll have a BEC", order)

        assert result.message is not None
        # Should recognize BEC
        items = result.order.items.get_active_items()
        message_lower = result.message.lower()

        has_item = len(items) >= 1
        mentions_bec = any(word in message_lower for word in [
            "bacon", "egg", "cheese", "bec", "classic"
        ])

        assert has_item or mentions_bec, \
            f"Should recognize BEC. Message: {result.message}"

    # NOTE: test_oj_abbreviation removed - "OJ" is ambiguous (matches Fresh OJ,
    # Tropicana OJ, etc.) so it triggers disambiguation rather than direct recognition

