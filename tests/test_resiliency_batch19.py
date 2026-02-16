"""
Resiliency Test Batch 19: Done Ordering During Item Configuration

Tests the system's ability to handle "finish my order" / "checkout" signals
during item configuration (CONFIGURING_ITEM phase). Explicit phrases containing
"order"/"checkout"/"pay" language should transition to checkout, while short
ambiguous phrases like "done" should NOT trigger checkout during config.
"""

from orderbot.tasks.state_machine import OrderStateMachine, OrderPhase
from orderbot.tasks.models import OrderTask, TaskStatus


# Checkout-phase indicators in bot responses
CHECKOUT_KEYWORDS = ["pickup", "delivery", "name", "email", "phone", "payment"]

CHECKOUT_PHASES = {
    OrderPhase.CHECKOUT_DELIVERY.value,
    OrderPhase.CHECKOUT_NAME.value,
    OrderPhase.CHECKOUT_CONFIRM.value,
    OrderPhase.CHECKOUT_PAYMENT_METHOD.value,
    OrderPhase.CHECKOUT_PHONE.value,
    OrderPhase.CHECKOUT_EMAIL.value,
}


def _is_checkout(result) -> bool:
    """Return True if the result indicates the order transitioned to checkout."""
    if result.order.phase in CHECKOUT_PHASES:
        return True
    msg = result.message.lower()
    return any(kw in msg for kw in CHECKOUT_KEYWORDS)


class TestDoneOrderingDuringConfig:
    """Batch 19: Done ordering during item configuration."""

    def test_finish_my_order_during_config(self):
        """
        Test: "finish my order" during config → transitions to checkout.

        Scenario:
        - User orders a plain bagel
        - Bot asks about toasting
        - User says "finish my order"
        - Expected: Item is completed, order transitions to checkout
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("plain bagel", order)
        assert result1.order.phase == OrderPhase.CONFIGURING_ITEM.value, (
            f"Expected CONFIGURING_ITEM, got: {result1.order.phase}"
        )

        result2 = sm.process("finish my order", result1.order)
        assert _is_checkout(result2), (
            f"Should transition to checkout. Phase: {result2.order.phase}, "
            f"Message: {result2.message}"
        )

    def test_thats_it_for_my_order_during_config(self):
        """
        Test: "that's it for my order" during config → transitions to checkout.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("plain bagel", order)
        assert result1.order.phase == OrderPhase.CONFIGURING_ITEM.value

        result2 = sm.process("that's it for my order", result1.order)
        assert _is_checkout(result2), (
            f"Should transition to checkout. Phase: {result2.order.phase}, "
            f"Message: {result2.message}"
        )

    def test_checkout_during_config(self):
        """
        Test: "checkout" during config → transitions to checkout.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("plain bagel", order)
        assert result1.order.phase == OrderPhase.CONFIGURING_ITEM.value

        result2 = sm.process("checkout", result1.order)
        assert _is_checkout(result2), (
            f"Should transition to checkout. Phase: {result2.order.phase}, "
            f"Message: {result2.message}"
        )

    def test_ready_to_pay_during_config(self):
        """
        Test: "I'm ready to pay" during config → transitions to checkout.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("plain bagel", order)
        assert result1.order.phase == OrderPhase.CONFIGURING_ITEM.value

        result2 = sm.process("I'm ready to pay", result1.order)
        assert _is_checkout(result2), (
            f"Should transition to checkout. Phase: {result2.order.phase}, "
            f"Message: {result2.message}"
        )

    def test_done_ordering_during_config(self):
        """
        Test: "done ordering" during config → transitions to checkout.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("plain bagel", order)
        assert result1.order.phase == OrderPhase.CONFIGURING_ITEM.value

        result2 = sm.process("done ordering", result1.order)
        assert _is_checkout(result2), (
            f"Should transition to checkout. Phase: {result2.order.phase}, "
            f"Message: {result2.message}"
        )

    def test_short_done_does_not_trigger_checkout_during_config(self):
        """
        Test: Short "done" does NOT trigger checkout during config.

        "done" is ambiguous during configuration — it could mean "done with
        this item's options". It should be treated as a config answer, not
        a checkout signal.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("plain bagel", order)
        assert result1.order.phase == OrderPhase.CONFIGURING_ITEM.value

        result2 = sm.process("done", result1.order)
        # Should NOT be in checkout — "done" is ambiguous during config
        assert result2.order.phase not in CHECKOUT_PHASES, (
            f"Short 'done' should NOT trigger checkout during config. "
            f"Phase: {result2.order.phase}, Message: {result2.message}"
        )

    def test_thats_it_does_not_trigger_checkout_during_config(self):
        """
        Test: Short "that's it" does NOT trigger checkout during config.

        "that's it" without "for my order" is ambiguous during configuration.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("plain bagel", order)
        assert result1.order.phase == OrderPhase.CONFIGURING_ITEM.value

        result2 = sm.process("that's it", result1.order)
        # Should NOT transition to checkout — ambiguous during config
        assert result2.order.phase not in CHECKOUT_PHASES, (
            f"Short 'that's it' should NOT trigger checkout during config. "
            f"Phase: {result2.order.phase}, Message: {result2.message}"
        )

    def test_item_marked_complete_on_done_ordering(self):
        """
        Test: Item being configured gets marked complete with whatever
        attributes were already set when user says "finish my order".
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("plain bagel", order)
        assert result1.order.phase == OrderPhase.CONFIGURING_ITEM.value

        # At this point the bagel has bread=plain but toasted is not yet set
        result2 = sm.process("finish my order", result1.order)

        # The bagel should be marked complete
        items = result2.order.items.items
        assert len(items) >= 1, "Should have at least 1 item"
        bagel = items[0]
        assert bagel.status == TaskStatus.COMPLETE, (
            f"Item should be marked complete. Status: {bagel.status}"
        )

    def test_lets_wrap_it_up_during_config(self):
        """
        Test: "let's wrap it up" during config → transitions to checkout.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("plain bagel", order)
        assert result1.order.phase == OrderPhase.CONFIGURING_ITEM.value

        result2 = sm.process("let's wrap it up", result1.order)
        assert _is_checkout(result2), (
            f"Should transition to checkout. Phase: {result2.order.phase}, "
            f"Message: {result2.message}"
        )

    def test_check_out_with_space_during_config(self):
        """
        Test: "check out" (with space) during config → transitions to checkout.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("plain bagel", order)
        assert result1.order.phase == OrderPhase.CONFIGURING_ITEM.value

        result2 = sm.process("check out", result1.order)
        assert _is_checkout(result2), (
            f"Should transition to checkout. Phase: {result2.order.phase}, "
            f"Message: {result2.message}"
        )

    def test_i_want_to_pay_during_config(self):
        """
        Test: "I want to pay" during config → transitions to checkout.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("plain bagel", order)
        assert result1.order.phase == OrderPhase.CONFIGURING_ITEM.value

        result2 = sm.process("I want to pay", result1.order)
        assert _is_checkout(result2), (
            f"Should transition to checkout. Phase: {result2.order.phase}, "
            f"Message: {result2.message}"
        )
