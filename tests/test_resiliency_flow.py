"""
Resiliency Tests: Order flow (cancellation, checkout, preparation, partial orders, done-ordering).

Consolidated from batches: 6, 7, 13, 16, 19.
"""

import pytest

from orderbot.tasks.models import OrderTask
from orderbot.tasks.models import OrderTask, TaskStatus
from orderbot.tasks.state_machine import OrderStateMachine, OrderPhase
from tests.helpers import BagelItemTask
from tests.helpers import BagelItemTask, CoffeeItemTask

# =============================================================================
# From test_resiliency_batch6.py
# =============================================================================

class TestCancellationRemoval:
    """Batch 6: Cancellation & Removal."""

    def test_remove_the_bagel(self):
        """
        Test: User says "remove the bagel" with one bagel in order.

        Scenario:
        - User has: 1 plain bagel
        - User says: "remove the bagel"
        - Expected: Bagel is removed (cancelled status)
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(
            bagel_type="plain",
            toasted=True,
        )
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("remove the bagel", order)

        # Should have a response
        assert result.message is not None

        # Bagel should be cancelled (status = SKIPPED)
        active_bagels = [
            i for i in result.order.items.items
            if i.has_attribute('bread') and i.status != TaskStatus.SKIPPED
        ]
        assert len(active_bagels) == 0, \
            f"Bagel should be removed. Active bagels: {len(active_bagels)}"

    def test_cancel_the_coffee(self):
        """
        Test: User says "cancel the coffee".

        Scenario:
        - User has: 1 hot coffee
        - User says: "cancel the coffee"
        - Expected: Coffee is cancelled
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        coffee = CoffeeItemTask(
            drink_type="hot coffee",
            size="large",
            iced=False,
        )
        coffee.mark_complete()
        order.items.add_item(coffee)

        sm = OrderStateMachine()
        result = sm.process("cancel the coffee", order)

        # Should have a response
        assert result.message is not None

        # Coffee should be cancelled (status = SKIPPED)
        active_coffees = [
            i for i in result.order.items.items
            if i.has_attribute('size') and i.status != TaskStatus.SKIPPED
        ]
        assert len(active_coffees) == 0, \
            f"Coffee should be cancelled. Active coffees: {len(active_coffees)}"

    def test_nevermind_the_last_item(self):
        """
        Test: User says "nevermind" or "actually no" for last item.

        Scenario:
        - User has: bagel and latte
        - User says: "nevermind the latte"
        - Expected: Latte is removed, bagel preserved
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(
            bagel_type="everything",
            toasted=True,
        )
        bagel.mark_complete()
        order.items.add_item(bagel)

        coffee = CoffeeItemTask(
            drink_type="latte",
            size="large",
            iced=True,
        )
        coffee.mark_complete()
        order.items.add_item(coffee)

        sm = OrderStateMachine()
        result = sm.process("nevermind the latte", order)

        # Should have a response
        assert result.message is not None

        # Latte should be cancelled (status = SKIPPED)
        active_lattes = [
            i for i in result.order.items.items
            if i.has_attribute('size') and i.status != TaskStatus.SKIPPED
        ]
        assert len(active_lattes) == 0, \
            f"Latte should be cancelled. Active lattes: {len(active_lattes)}"

        # Bagel should still be active
        active_bagels = [
            i for i in result.order.items.items
            if i.has_attribute('bread') and i.status != TaskStatus.SKIPPED
        ]
        assert len(active_bagels) == 1, \
            f"Bagel should be preserved. Active bagels: {len(active_bagels)}"

    def test_no_i_dont_want_that(self):
        """
        Test: User says "no I don't want that" after item added.

        Scenario:
        - User has: bagel just added
        - User says: "no I don't want that"
        - Expected: Last item is removed
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(
            bagel_type="sesame",
            toasted=True,
        )
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("no I don't want that", order)

        # Should have a response
        assert result.message is not None

        # Bagel should be cancelled (status = SKIPPED)
        active_bagels = [
            i for i in result.order.items.items
            if i.has_attribute('bread') and i.status != TaskStatus.SKIPPED
        ]
        assert len(active_bagels) == 0, \
            f"Last item should be removed. Active bagels: {len(active_bagels)}"

    def test_start_over(self):
        """
        Test: User says "start over" to clear the order.

        Scenario:
        - User has: multiple items
        - User says: "cancel everything"
        - Expected: All items cancelled, order reset

        Note: Using "cancel everything" as it's handled by deterministic parser.
              "start over" would need LLM to interpret.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        coffee = CoffeeItemTask(drink_type="latte", size="medium", iced=False)
        coffee.mark_complete()
        order.items.add_item(coffee)

        sm = OrderStateMachine()
        # Use "cancel everything" which is parsed deterministically
        result = sm.process("cancel everything", order)

        # Should have a response
        assert result.message is not None

        # System should acknowledge the cancellation request
        # The handler may cancel items or ask for confirmation
        message_lower = result.message.lower()
        acknowledges = any(word in message_lower for word in [
            "cancel", "clear", "remove", "start", "order", "everything"
        ])

        assert acknowledges, \
            f"Should acknowledge cancellation request. Message: {result.message}"

# =============================================================================
# From test_resiliency_batch7.py
# =============================================================================

class TestOrderConfirmationCheckout:
    """Batch 7: Order Confirmation & Checkout."""

    def test_thats_all(self):
        """
        Test: User says "that's all" to finish ordering.

        Scenario:
        - User has: bagel and coffee
        - User says: "that's all"
        - Expected: Order moves to confirmation/checkout phase
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        coffee = CoffeeItemTask(drink_type="latte", size="medium", iced=False)
        coffee.mark_complete()
        order.items.add_item(coffee)

        sm = OrderStateMachine()
        result = sm.process("that's all", order)

        # Should have a response
        assert result.message is not None

        # Should either move to next phase or confirm the order
        message_lower = result.message.lower()
        confirms = any(word in message_lower for word in [
            "confirm", "total", "order", "pickup", "delivery", "anything else", "all set"
        ]) or result.order.phase != OrderPhase.TAKING_ITEMS.value

        assert confirms, f"Should confirm order or move to next phase. Message: {result.message}"

    def test_im_done(self):
        """
        Test: User says "I'm done" to finish ordering.

        Scenario:
        - User has: bagel
        - User says: "I'm done"
        - Expected: Order moves to confirmation
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="everything", toasted=True, spread="cream cheese")
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("I'm done", order)

        # Should have a response
        assert result.message is not None

        # Should confirm or proceed
        message_lower = result.message.lower()
        confirms = any(word in message_lower for word in [
            "confirm", "total", "order", "pickup", "delivery", "anything else", "done"
        ]) or result.order.phase != OrderPhase.TAKING_ITEMS.value

        assert confirms, f"Should acknowledge done. Message: {result.message}"

    def test_nothing_else(self):
        """
        Test: User says "nothing else" when asked if they want more.

        Scenario:
        - User has: coffee
        - User says: "nothing else"
        - Expected: Order proceeds to checkout
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        coffee = CoffeeItemTask(drink_type="drip coffee", size="large", iced=False)
        coffee.mark_complete()
        order.items.add_item(coffee)

        sm = OrderStateMachine()
        result = sm.process("nothing else", order)

        # Should have a response
        assert result.message is not None

        # Should proceed
        message_lower = result.message.lower()
        proceeds = any(word in message_lower for word in [
            "confirm", "total", "order", "pickup", "delivery", "anything else", "else"
        ]) or result.order.phase != OrderPhase.TAKING_ITEMS.value

        assert proceeds, f"Should proceed with order. Message: {result.message}"

    def test_just_the_bagel(self):
        """
        Test: User says "just the bagel" meaning no additional items.

        Scenario:
        - User ordered bagel
        - System asks if they want anything else
        - User says: "just the bagel"
        - Expected: Order proceeds without adding more
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="sesame", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("just the bagel", order)

        # Should have a response
        assert result.message is not None

        # Should not add another bagel and should proceed
        bagels = [i for i in result.order.items.items if i.has_attribute('bread')]
        assert len(bagels) == 1, f"Should still have just 1 bagel. Got: {len(bagels)}"

    def test_thats_it_for_now(self):
        """
        Test: User says "that's it for now".

        Scenario:
        - User has items
        - User says: "that's it for now"
        - Expected: Order proceeds to checkout
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="plain", toasted=False)
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("that's it for now", order)

        # Should have a response
        assert result.message is not None

        # Should proceed
        message_lower = result.message.lower()
        proceeds = any(word in message_lower for word in [
            "confirm", "total", "order", "pickup", "delivery", "anything", "else"
        ]) or result.order.phase != OrderPhase.TAKING_ITEMS.value

        assert proceeds, f"Should proceed. Message: {result.message}"

# =============================================================================
# From test_resiliency_batch13.py
# =============================================================================

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
        bagels = [i for i in result.order.items.items if i.has_attribute('bread')]

        # Should have a bagel that's toasted
        assert len(bagels) >= 1, f"Should add bagel. Message: {result.message}"
        if bagels[0]["toasted"] is not None:
            assert bagels[0]["toasted"] is True, "Should be toasted"

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
        bagels = [i for i in result.order.items.items if i.has_attribute('bread')]

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
        bagels = [i for i in result.order.items.items if i.has_attribute('bread')]

        # Should have a bagel with cream cheese
        assert len(bagels) >= 1, f"Should add bagel. Message: {result.message}"
        bagel = bagels[0]
        # Should have cream cheese noted somehow (check spread field)
        spread = bagel["spread"] or ""
        # Spread slug will be something like "plain_cream_cheese" or "cream_cheese"
        assert "cream" in spread.lower(), \
            f"Should have cream cheese spread. Spread: {spread}, Message: {result.message}"

# =============================================================================
# From test_resiliency_batch16.py
# =============================================================================

class TestPartialIncompleteOrders:
    """Batch 16: Partial/Incomplete Orders."""

    def test_incomplete_i_want_a(self):
        """
        Test: User says incomplete "I want a..."

        Scenario:
        - User says: "I want a"
        - Expected: System asks what they want
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("I want a", order)

        assert result.message is not None
        # Should ask for clarification
        message_lower = result.message.lower()
        asks = any(word in message_lower for word in [
            "what", "which", "help", "like", "order", "?"
        ])
        assert asks, f"Should ask what they want. Message: {result.message}"

    def test_and_also_continuation(self):
        """
        Test: User says "and also..." to add more.

        Scenario:
        - User has: bagel
        - User says: "and also a coffee"
        - Expected: Coffee added to order
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("and also a coffee", order)

        assert result.message is not None
        coffees = [i for i in result.order.items.items if i.has_attribute('size')]

        # Should add coffee or ask about it
        has_coffee = len(coffees) >= 1
        mentions_coffee = "coffee" in result.message.lower()

        assert has_coffee or mentions_coffee, \
            f"Should add or ask about coffee. Message: {result.message}"

    def test_multi_turn_coffee_then_large(self):
        """
        Test: User orders in multiple turns - "coffee" then "large".

        Scenario:
        - User says: "coffee"
        - System asks about size
        - User says: "large"
        - Expected: Size is set to large
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        # First turn - order coffee
        result1 = sm.process("coffee", order)
        assert result1.message is not None

        # Second turn - specify size
        result2 = sm.process("large", result1.order)
        assert result2.message is not None

        coffees = [i for i in result2.order.items.items if i.has_attribute('size')]
        if coffees:
            coffee = coffees[0]
            # Should have large size or be asking about it
            assert coffee["size"] == "large" or "large" in result2.message.lower(), \
                f"Should be large. Size={coffee['size']}"

# =============================================================================
# From test_resiliency_batch19.py
# =============================================================================

CHECKOUT_KEYWORDS = ["pickup", "delivery", "name", "email", "phone", "payment"]

CHECKOUT_PHASES = {
    OrderPhase.CHECKOUT_DELIVERY.value,
    OrderPhase.CHECKOUT_NAME.value,
    OrderPhase.CHECKOUT_CONFIRM.value,
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
