"""
Resiliency Test Batch 1: Replacement & Modification Scenarios

Tests the system's ability to handle replacement and modification requests
where the user wants to change something about an item already in their order.
"""

import pytest
from sandwich_bot.tasks.state_machine import OrderStateMachine, OrderPhase
from sandwich_bot.tasks.models import OrderTask, BagelItemTask, CoffeeItemTask, TaskStatus


class TestReplacementModificationScenarios:
    """Batch 1: Replacement & Modification Scenarios."""

    def test_change_spread_on_bagel_with_existing_spread(self):
        """
        Test: User has bagel with cream cheese, wants to change to veggie cream cheese.

        Scenario:
        - User has: plain bagel with cream cheese
        - User says: "actually make it veggie cream cheese"
        - Expected: spread changes to veggie cream cheese, bagel type preserved
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(
            bagel_type="plain",
            toasted=True,
            spread="cream cheese",
        )
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("actually make it veggie cream cheese", order)

        # Get the bagel from the result
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]
        assert len(bagels) == 1, "Should still have 1 bagel"

        updated_bagel = bagels[0]
        assert updated_bagel.bagel_type == "plain", "Bagel type should be preserved"
        assert updated_bagel.toasted is True, "Toasted should be preserved"
        # Spread is stored as spread="cream cheese" + spread_type="veggie" = "veggie cream cheese"
        assert updated_bagel.spread_type == "veggie", f"Spread type should be veggie, got: {updated_bagel.spread_type}"

    def test_change_coffee_size_small_to_large(self):
        """
        Test: User has small latte, wants to change to large.

        Scenario:
        - User has: small hot latte
        - User says: "make it a large"
        - Expected: size changes to large, other attributes preserved
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        coffee = CoffeeItemTask(
            drink_type="latte",
            size="small",
            iced=False,  # False = hot
        )
        coffee.mark_complete()
        order.items.add_item(coffee)

        sm = OrderStateMachine()
        result = sm.process("make it a large", order)

        coffees = [i for i in result.order.items.items if isinstance(i, CoffeeItemTask)]
        assert len(coffees) == 1, "Should still have 1 coffee"

        updated_coffee = coffees[0]
        assert updated_coffee.size == "large", f"Size should be large, got: {updated_coffee.size}"
        assert updated_coffee.drink_type == "latte", "Drink type should be preserved"
        assert updated_coffee.iced is False, "Iced should be preserved (False = hot)"

    def test_change_milk_type_on_coffee(self):
        """
        Test: User has latte with whole milk, wants oat milk.

        Scenario:
        - User has: medium latte with whole milk
        - User says: "can you make it with oat milk instead"
        - Expected: milk type changes to oat, other attributes preserved
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        coffee = CoffeeItemTask(
            drink_type="latte",
            size="medium",
            iced=False,  # False = hot
            milk="whole",
        )
        coffee.mark_complete()
        order.items.add_item(coffee)

        sm = OrderStateMachine()
        result = sm.process("can you make it with oat milk instead", order)

        coffees = [i for i in result.order.items.items if isinstance(i, CoffeeItemTask)]
        assert len(coffees) == 1, "Should still have 1 coffee"

        updated_coffee = coffees[0]
        assert updated_coffee.milk == "oat", f"Milk should be oat, got: {updated_coffee.milk}"
        assert updated_coffee.size == "medium", "Size should be preserved"
        assert updated_coffee.drink_type == "latte", "Drink type should be preserved"

    def test_change_quantity_make_it_two(self):
        """
        Test: User has 1 bagel, says "actually, make that two".

        Scenario:
        - User has: 1 everything bagel toasted with cream cheese
        - User says: "actually, make that two"
        - Expected: quantity increases to 2 (either by adding another or updating quantity)
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(
            bagel_type="everything",
            toasted=True,
            spread="cream cheese",
        )
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("actually, make that two", order)

        # Should either have 2 bagels OR 1 bagel with quantity 2
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]
        total_quantity = sum(b.quantity for b in bagels)

        assert total_quantity == 2, f"Should have 2 bagels total, got {total_quantity}"

        # All bagels should have the same type
        for b in bagels:
            assert b.bagel_type == "everything", "Bagel type should be preserved"

    def test_remove_modifier_remove_the_bacon(self):
        """
        Test: User has bagel with bacon, says "remove the bacon".

        Scenario:
        - User has: everything bagel with egg and bacon
        - User says: "remove the bacon"
        - Expected: bacon is removed, egg remains
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(
            bagel_type="everything",
            toasted=True,
            sandwich_protein="bacon",
        )
        bagel.extras = ["egg"]
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("remove the bacon", order)

        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]
        assert len(bagels) == 1, "Should still have 1 bagel"

        updated_bagel = bagels[0]
        # Bacon should be removed from sandwich_protein or extras
        has_bacon = (
            (updated_bagel.sandwich_protein and "bacon" in updated_bagel.sandwich_protein.lower()) or
            any("bacon" in e.lower() for e in (updated_bagel.extras or []))
        )
        assert not has_bacon, f"Bacon should be removed. protein={updated_bagel.sandwich_protein}, extras={updated_bagel.extras}"

        # Egg should still be there
        has_egg = (
            (updated_bagel.sandwich_protein and "egg" in updated_bagel.sandwich_protein.lower()) or
            any("egg" in e.lower() for e in (updated_bagel.extras or []))
        )
        assert has_egg, f"Egg should be preserved. protein={updated_bagel.sandwich_protein}, extras={updated_bagel.extras}"
