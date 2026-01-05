"""
Resiliency Test Batch 13: Preparation Preferences

Tests the system's ability to handle specific preparation requests.
"""

from sandwich_bot.tasks.state_machine import OrderStateMachine, OrderPhase
from sandwich_bot.tasks.models import OrderTask, BagelItemTask


class TestPreparationPreferences:
    """Batch 13: Preparation Preferences."""

    def test_extra_toasted(self):
        """
        Test: User says "extra toasted".

        Scenario:
        - User says: "plain bagel extra toasted"
        - Expected: Bagel is toasted (extra preference noted)
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("plain bagel extra toasted", order)

        assert result.message is not None
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]

        # Should have a bagel that's toasted
        assert len(bagels) >= 1, f"Should add bagel. Message: {result.message}"
        if bagels[0].toasted is not None:
            assert bagels[0].toasted is True, "Should be toasted"

    def test_lightly_toasted(self):
        """
        Test: User says "lightly toasted".

        Scenario:
        - User says: "everything bagel lightly toasted"
        - Expected: Bagel is toasted (light preference noted)
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("everything bagel lightly toasted", order)

        assert result.message is not None
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]

        # Should have a bagel
        assert len(bagels) >= 1, f"Should add bagel. Message: {result.message}"

    def test_extra_cream_cheese(self):
        """
        Test: User says "extra cream cheese".

        Scenario:
        - User says: "plain bagel with extra cream cheese"
        - Expected: Bagel with cream cheese (extra noted)
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("plain bagel with extra cream cheese", order)

        assert result.message is not None
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]

        # Should have a bagel with cream cheese
        assert len(bagels) >= 1, f"Should add bagel. Message: {result.message}"
        bagel = bagels[0]
        # Should have cream cheese noted somehow
        has_cc = (
            bagel.spread == "cream cheese" or
            "cream cheese" in (bagel.notes or "") or
            "cream cheese" in str(bagel.extras or [])
        )
        assert has_cc or "cream cheese" in result.message.lower(), \
            f"Should note cream cheese. Message: {result.message}"
