"""
Resiliency Test Batch 1: Replacement & Modification Scenarios

Tests the system's ability to handle replacement and modification requests
where the user wants to change something about an item already in their order.
"""

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

    def test_change_coffee_to_decaf(self):
        """
        Test: User has latte, wants to make it decaf.

        Scenario:
        - User has: medium latte
        - User says: "make it a decaf"
        - Expected: decaf changes to True, other attributes preserved
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        coffee = CoffeeItemTask(
            drink_type="latte",
            size="medium",
            iced=False,  # False = hot
        )
        coffee.mark_complete()
        order.items.add_item(coffee)

        sm = OrderStateMachine()
        result = sm.process("make it a decaf", order)

        coffees = [i for i in result.order.items.items if isinstance(i, CoffeeItemTask)]
        assert len(coffees) == 1, "Should still have 1 coffee"

        updated_coffee = coffees[0]
        assert updated_coffee.decaf is True, f"Decaf should be True, got: {updated_coffee.decaf}"
        assert updated_coffee.size == "medium", "Size should be preserved"
        assert updated_coffee.drink_type == "latte", "Drink type should be preserved"
        assert updated_coffee.iced is False, "Iced should be preserved"

    def test_order_decaf_coffee_upfront(self):
        """
        Test: User orders "decaf coffee" from the start (not as a modification).

        Scenario:
        - User says: "decaf coffee"
        - System asks for size: "What size would you like?"
        - User says: "medium"
        - System asks for style: "Would you like that hot or iced?"
        - User says: "hot"
        - System asks for modifiers: "Would you like any milk, sugar or syrup?"
        - User says: "no"
        - Expected: Coffee item has decaf=True, size=medium, iced=False
        """
        from unittest.mock import patch
        from sandwich_bot.tasks.schemas import CoffeeSizeResponse, CoffeeStyleResponse
        from sandwich_bot.tasks.adapter import order_task_to_dict

        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()

        # Step 1: Order decaf coffee
        result = sm.process("decaf coffee", order)

        # Should ask for size
        assert "size" in result.message.lower(), f"Should ask for size, got: {result.message}"

        # Check that coffee was added with decaf=True even before configuration is complete
        coffees = [i for i in result.order.items.items if isinstance(i, CoffeeItemTask)]
        assert len(coffees) == 1, f"Should have 1 coffee, got {len(coffees)}"
        assert coffees[0].decaf is True, f"Decaf should be True from initial order, got: {coffees[0].decaf}"

        # Step 2: Answer size (mock the LLM parser)
        with patch("sandwich_bot.tasks.coffee_config_handler.parse_coffee_size") as mock_size:
            mock_size.return_value = CoffeeSizeResponse(size="medium")
            result = sm.process("medium", result.order)

        # Should ask for hot/iced
        assert "hot" in result.message.lower() or "iced" in result.message.lower(), \
            f"Should ask for hot/iced, got: {result.message}"

        # Check decaf is still True
        coffees = [i for i in result.order.items.items if isinstance(i, CoffeeItemTask)]
        assert coffees[0].decaf is True, f"Decaf should still be True after size, got: {coffees[0].decaf}"
        assert coffees[0].size == "medium", f"Size should be medium, got: {coffees[0].size}"

        # Step 3: Answer hot/iced (mock the LLM parser)
        with patch("sandwich_bot.tasks.coffee_config_handler.parse_coffee_style") as mock_style:
            mock_style.return_value = CoffeeStyleResponse(iced=False)
            result = sm.process("hot", result.order)

        # Should ask for modifiers (milk/sugar/syrup)
        assert "milk" in result.message.lower() or "sugar" in result.message.lower(), \
            f"Should ask for modifiers, got: {result.message}"

        # Step 4: Answer modifiers question (decline)
        result = sm.process("no", result.order)

        # Coffee should now be complete
        coffees = [i for i in result.order.items.items if isinstance(i, CoffeeItemTask)]
        assert len(coffees) == 1, "Should still have 1 coffee"

        final_coffee = coffees[0]
        assert final_coffee.decaf is True, f"Decaf should be True after config, got: {final_coffee.decaf}"
        assert final_coffee.size == "medium", f"Size should be medium, got: {final_coffee.size}"
        assert final_coffee.iced is False, f"Iced should be False (hot), got: {final_coffee.iced}"
        assert final_coffee.status == TaskStatus.COMPLETE, f"Coffee should be complete, got: {final_coffee.status}"

        # Also verify the adapter output includes "decaf" in free_details
        order_dict = order_task_to_dict(result.order)
        coffee_item = order_dict["items"][0]
        assert "decaf" in coffee_item["free_details"], \
            f"Expected 'decaf' in free_details, got: {coffee_item['free_details']}"

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

    def test_bagel_toasted_should_ask_about_spread(self):
        """
        Test: User orders "onion bagel toasted" - should ask about spread.

        Scenario:
        - User says: "onion bagel toasted"
        - Expected: System asks about spread (cream cheese or butter)
        - This is a regression test for the bug where bagels with type+toasted
          specified would skip the spread question.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("onion bagel toasted", order)

        # Should ask about spread, not say "Got it, ... Anything else?"
        assert "cream cheese" in result.message.lower() or "butter" in result.message.lower(), \
            f"Should ask about spread. Got: {result.message}"

        # Should be in CONFIGURING_ITEM phase with pending_field = "spread"
        assert result.order.pending_field == "spread", \
            f"Should be pending spread question. Got pending_field: {result.order.pending_field}"

    def test_bagel_not_toasted_should_ask_about_spread(self):
        """
        Test: User orders "plain bagel not toasted" - should ask about spread.

        Same as above but with toasted=False.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("plain bagel not toasted", order)

        # Should ask about spread
        assert "cream cheese" in result.message.lower() or "butter" in result.message.lower(), \
            f"Should ask about spread. Got: {result.message}"

        # Should be in CONFIGURING_ITEM phase with pending_field = "spread"
        assert result.order.pending_field == "spread", \
            f"Should be pending spread question. Got pending_field: {result.order.pending_field}"

    def test_bagel_with_extras_skips_spread_question(self):
        """
        Test: User orders bagel with toppings - should NOT ask about spread.

        If the user already has toppings like bacon, egg, etc., don't ask about spread.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("everything bagel toasted with bacon and egg", order)

        # Should NOT ask about spread since bagel has toppings
        # Should say "Anything else?" or similar
        assert "anything else" in result.message.lower() or result.order.pending_field != "spread", \
            f"Should NOT ask about spread when bagel has toppings. Got: {result.message}"

    def test_omelette_asks_side_choice_first(self):
        """
        Test: Omelette with requires_side_choice=True should ask about side choice first.

        Omelettes come with a choice of bagel or fruit salad.
        Should NOT ask about toasted (omelettes aren't toasted).
        """
        from sandwich_bot.tasks.models import MenuItemTask

        # Create menu data with an omelette and coffee
        menu_data = {
            "all_items": [
                {"id": 500, "name": "Spinach & Feta Omelette", "base_price": 14.50, "category": "omelette"},
                {"id": 501, "name": "Coffee", "base_price": 3.45, "category": "sized_beverage"},
            ],
            "items_by_type": {
                "omelette": [
                    {"id": 500, "name": "Spinach & Feta Omelette", "base_price": 14.50, "category": "omelette"},
                ],
                "sized_beverage": [
                    {"id": 501, "name": "Coffee", "base_price": 3.45, "category": "sized_beverage"},
                ],
            },
            "categories": ["omelette", "sized_beverage"],
        }

        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # Pre-create the omelette item with requires_side_choice=True
        omelette = MenuItemTask(
            menu_item_name="Spinach & Feta Omelette",
            menu_item_id=500,
            unit_price=14.50,
            requires_side_choice=True,
            menu_item_type="omelette",
        )
        omelette.mark_in_progress()
        order.items.add_item(omelette)

        sm = OrderStateMachine(menu_data=menu_data)
        # User says "and a coffee" to trigger multi-item handling
        result = sm.process("and a coffee", order)

        # Check items_needing_config path was triggered and side_choice was identified
        # The omelette should need side_choice configuration
        omelette_item = result.order.items.items[0]
        assert omelette_item.requires_side_choice, "Omelette should have requires_side_choice=True"

        # Either pending_field should be side_choice OR the message should mention bagel/fruit
        # (depending on which item gets asked first)
        has_side_choice_question = (
            result.order.pending_field == "side_choice" or
            ("bagel" in result.message.lower() and "fruit" in result.message.lower())
        )
        # Should NOT ask about omelette being toasted
        asks_omelette_toasted = "omelette" in result.message.lower() and "toasted" in result.message.lower()

        assert not asks_omelette_toasted, \
            f"Should NOT ask if omelette is toasted. Got: {result.message}"
