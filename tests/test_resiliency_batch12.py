"""
Resiliency Test Batch 12: Abbreviations & Shorthand

Tests the system's ability to handle common abbreviations.
"""

from sandwich_bot.tasks.state_machine import OrderStateMachine, OrderPhase
from sandwich_bot.tasks.models import OrderTask


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

    def test_oj_abbreviation(self):
        """
        Test: User says "OJ" for orange juice.

        Scenario:
        - User says: "and an OJ"
        - Expected: System recognizes as orange juice
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("and an OJ", order)

        assert result.message is not None
        # Should recognize OJ
        message_lower = result.message.lower()
        items = result.order.items.get_active_items()

        has_item = len(items) >= 1
        mentions_oj = any(word in message_lower for word in [
            "orange", "juice", "oj", "tropicana"
        ])

        assert has_item or mentions_oj, \
            f"Should recognize OJ. Message: {result.message}"

    def test_sec_abbreviation(self):
        """
        Test: User says "SEC" for sausage egg cheese.

        Scenario:
        - User says: "give me a SEC"
        - Expected: System recognizes as sausage egg and cheese
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("give me a SEC", order)

        assert result.message is not None
        # Should recognize or ask about SEC
        message_lower = result.message.lower()
        items = result.order.items.get_active_items()

        has_item = len(items) >= 1
        mentions_sec = any(word in message_lower for word in [
            "sausage", "egg", "cheese", "sec", "sandwich"
        ])

        assert has_item or mentions_sec, \
            f"Should recognize SEC. Message: {result.message}"
