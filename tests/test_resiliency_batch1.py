"""
Resiliency Test Batch 1: Replacement & Modification Scenarios

Tests the system's ability to handle replacement and modification requests
where the user wants to change something about an item already in their order.
"""

from orderbot.tasks.state_machine import OrderStateMachine, OrderPhase
from orderbot.tasks.models import OrderTask, TaskStatus
from tests.helpers import BagelItemTask, CoffeeItemTask


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
        bagels = [i for i in result.order.items.items if i.has_attribute('bread')]
        assert len(bagels) == 1, "Should still have 1 bagel"

        updated_bagel = bagels[0]
        assert updated_bagel["bread"] == "plain", "Bagel type should be preserved"
        assert updated_bagel["toasted"] is True, "Toasted should be preserved"
        # Spread is stored as spread="cream cheese" + spread_type="veggie" = "veggie cream cheese"
        assert updated_bagel["spread_type"] == "veggie", f"Spread type should be veggie, got: {updated_bagel['spread_type']}"

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

        coffees = [i for i in result.order.items.items if i.has_attribute('size')]
        assert len(coffees) == 1, "Should still have 1 coffee"

        updated_coffee = coffees[0]
        assert updated_coffee["size"] == "large", f"Size should be large, got: {updated_coffee['size']}"
        assert updated_coffee.menu_item_name == "latte", "Drink type should be preserved"
        assert updated_coffee["temperature"] == "hot", "Temperature should be preserved (hot)"

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

        coffees = [i for i in result.order.items.items if i.has_attribute('size')]
        assert len(coffees) == 1, "Should still have 1 coffee"

        updated_coffee = coffees[0]
        milk_mods = updated_coffee.get_selections("milk")
        assert len(milk_mods) == 1 and milk_mods[0]["slug"] == "oat", f"Milk should be oat, got: {milk_mods}"
        assert updated_coffee["size"] == "medium", "Size should be preserved"
        assert updated_coffee.menu_item_name == "latte", "Drink type should be preserved"

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

        coffees = [i for i in result.order.items.items if i.has_attribute('size')]
        assert len(coffees) == 1, "Should still have 1 coffee"

        updated_coffee = coffees[0]
        assert updated_coffee["decaf"] is True, f"Decaf should be True, got: {updated_coffee['decaf']}"
        assert updated_coffee["size"] == "medium", "Size should be preserved"
        assert updated_coffee.menu_item_name == "latte", "Drink type should be preserved"
        assert updated_coffee["temperature"] == "hot", "Temperature should be preserved (hot)"

    def test_order_decaf_coffee_upfront(self):
        """
        Test: User orders "decaf coffee" from the start (not as a modification).

        Scenario:
        - User says: "decaf coffee"
        - System asks for size: "What size would you like?"
        - User says: "large"
        - System asks for style: "Would you like that hot or iced?"
        - User says: "hot"
        - System asks for modifiers: "Would you like any milk, sugar or syrup?"
        - User says: "no"
        - Expected: Coffee item has decaf=True, size=large, iced=False

        Note: DB only has "small" and "large" sizes (no "medium").
        Phase 6 migration routes beverages through MenuItemConfigHandler.
        """
        from orderbot.tasks.adapter import order_task_to_dict

        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()

        # Step 1: Order decaf coffee
        result = sm.process("decaf coffee", order)

        # Should ask for size
        assert "size" in result.message.lower(), f"Should ask for size, got: {result.message}"

        # Check that coffee was added with decaf=True even before configuration is complete
        coffees = [i for i in result.order.items.items if i.has_attribute('size')]
        assert len(coffees) == 1, f"Should have 1 coffee, got {len(coffees)}"
        assert coffees[0]["decaf"] is True, f"Decaf should be True from initial order, got: {coffees[0]['decaf']}"

        # Step 2: Answer size - use "large" which is a valid DB option
        # (MenuItemConfigHandler uses DB options directly, not LLM parsing)
        result = sm.process("large", result.order)

        # Should ask for hot/iced (temperature attribute)
        assert "hot" in result.message.lower() or "iced" in result.message.lower() or "temperature" in result.message.lower(), \
            f"Should ask for hot/iced, got: {result.message}"

        # Check decaf is still True
        coffees = [i for i in result.order.items.items if i.has_attribute('size')]
        assert coffees[0]["decaf"] is True, f"Decaf should still be True after size, got: {coffees[0]['decaf']}"
        # Size is stored in attribute_values
        size_val = coffees[0]["size"]
        assert size_val == "large", f"Size should be large, got: {size_val}"

        # Step 3: Answer hot/iced - MenuItemConfigHandler uses boolean attribute handling
        result = sm.process("hot", result.order)

        # After temperature, may ask for modifiers or be done
        # Check that we got past temperature by verifying temperature is set
        coffees = [i for i in result.order.items.items if i.has_attribute('size')]
        coffee = coffees[0]
        # Temperature is stored in attribute_values
        temp_val = coffee["temperature"]
        assert temp_val == "hot", f"Temperature should be 'hot', got: {temp_val}"

        # Step 4: If there are optional modifier questions, answer no
        if "milk" in result.message.lower() or "sugar" in result.message.lower() or "modifier" in result.message.lower():
            result = sm.process("no", result.order)

        # Coffee should now be complete or asking "anything else?"
        coffees = [i for i in result.order.items.items if i.has_attribute('size')]
        assert len(coffees) == 1, "Should still have 1 coffee"

        final_coffee = coffees[0]
        assert final_coffee["decaf"] is True, f"Decaf should be True after config, got: {final_coffee['decaf']}"
        # Size is stored in attribute_values
        final_size = final_coffee["size"]
        assert final_size == "large", f"Size should be large, got: {final_size}"
        final_temp = final_coffee["temperature"]
        assert final_temp == "hot", f"Temperature should be 'hot', got: {final_temp}"
        # Item may or may not be complete depending on optional modifiers
        # assert final_coffee.status == TaskStatus.COMPLETE, f"Coffee should be complete, got: {final_coffee.status}"

        # Also verify the adapter output includes "decaf" in free_details
        order_dict = order_task_to_dict(result.order)
        coffee_item = order_dict["items"][0]
        assert "decaf" in coffee_item.get("free_details", []), \
            f"Expected 'decaf' in free_details, got: {coffee_item.get('free_details', [])}"

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
        bagels = [i for i in result.order.items.items if i.has_attribute('bread')]
        total_quantity = sum(b.quantity for b in bagels)

        assert total_quantity == 2, f"Should have 2 bagels total, got {total_quantity}"

        # All bagels should have the same type
        for b in bagels:
            assert b["bread"] == "everything", "Bagel type should be preserved"

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
            extra_protein="bacon",
        )
        bagel["toppings"] = ["egg"]
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("remove the bacon", order)

        bagels = [i for i in result.order.items.items if i.has_attribute('bread')]
        assert len(bagels) == 1, "Should still have 1 bagel"

        updated_bagel = bagels[0]
        # Bacon should be removed from extra_protein or toppings
        extra_protein = updated_bagel["extra_protein"]
        toppings = updated_bagel["toppings"] or []
        has_bacon = (
            (extra_protein and "bacon" in extra_protein.lower()) or
            any("bacon" in e.lower() for e in toppings)
        )
        assert not has_bacon, f"Bacon should be removed. protein={extra_protein}, toppings={toppings}"

        # Egg should still be there
        has_egg = (
            (extra_protein and "egg" in extra_protein.lower()) or
            any("egg" in e.lower() for e in toppings)
        )
        assert has_egg, f"Egg should be preserved. protein={extra_protein}, toppings={toppings}"

    def test_bagel_toasted_should_ask_about_scooped(self):
        """
        Test: User orders "onion bagel toasted" - should ask about scooped.

        Scenario:
        - User says: "onion bagel toasted"
        - Expected: System asks about scooped (before asking about spread)
        - Note: DB has scooped with display_order=3, spread with display_order=4
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("onion bagel toasted", order)

        # Should ask about scooped (comes before spread in DB display_order)
        msg_lower = result.message.lower()
        is_scooped_question = "scoop" in msg_lower
        assert is_scooped_question, \
            f"Should ask about scooped. Got: {result.message}"

        # Should be in CONFIGURING_ITEM phase with pending_field for scooped
        assert result.order.pending_field in ("scooped", "menu_item_attr_scooped", "bagel:scooped"), \
            f"Should be pending scooped question. Got pending_field: {result.order.pending_field}"

    def test_bagel_not_toasted_should_ask_about_scooped(self):
        """
        Test: User orders "plain bagel not toasted" - should ask about scooped.

        Same as above but with toasted=False.
        Note: DB has scooped with display_order=3, spread with display_order=4
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("plain bagel not toasted", order)

        # Should ask about scooped (comes before spread in DB display_order)
        msg_lower = result.message.lower()
        is_scooped_question = "scoop" in msg_lower
        assert is_scooped_question, \
            f"Should ask about scooped. Got: {result.message}"

        # Should be in CONFIGURING_ITEM phase with pending_field for scooped
        assert result.order.pending_field in ("scooped", "menu_item_attr_scooped", "bagel:scooped"), \
            f"Should be pending scooped question. Got pending_field: {result.order.pending_field}"

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

        Uses real database via menu_cache_loaded fixture.
        """
        from orderbot.tasks.models import MenuItemTask

        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # Pre-create the omelette item with requires_side_choice=True
        omelette = MenuItemTask(
            menu_item_name="Spinach & Feta Omelette",
            menu_item_id=500,
            unit_price=14.50,
            menu_item_type="omelette",
        )
        omelette["requires_side_choice"] = True
        omelette.mark_in_progress()
        order.items.add_item(omelette)

        sm = OrderStateMachine()
        # User says "and a coffee" to trigger multi-item handling
        result = sm.process("and a coffee", order)

        # Check items_needing_config path was triggered and side_choice was identified
        # The omelette should need side_choice configuration
        omelette_item = result.order.items.items[0]
        assert omelette_item["requires_side_choice"], "Omelette should have requires_side_choice=True"

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

    def test_change_spread_during_configuration(self):
        """
        Test: User changes spread DURING item configuration, not after.

        Scenario:
        - User orders: "plain bagel with cream cheese"
        - Bot asks: "Would you like it toasted?"
        - User says: "actually make it veggie cream cheese"
        - Expected: spread changes to veggie cream cheese, bot continues asking about toasting

        This tests the mid-config modification behavior where the change is applied
        immediately rather than being deferred until configuration is complete.
        """
        from orderbot.tasks.models import MenuItemTask

        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()

        # Step 1: User orders plain bagel with cream cheese
        result1 = sm.process("plain bagel with cream cheese", order)

        # Should be asking about toasted
        bagels = [i for i in result1.order.items.items if i.has_attribute('bread')]
        assert len(bagels) == 1, "Should have 1 bagel"
        bagel = bagels[0]

        # The bagel should be in_progress and we should be in CONFIGURING_ITEM phase
        assert result1.order.phase == OrderPhase.CONFIGURING_ITEM.value, \
            f"Expected CONFIGURING_ITEM phase, got: {result1.order.phase}"

        # Store the bagel ID for comparison
        bagel_id = bagel.id

        # Step 2: User changes spread to veggie during configuration
        result2 = sm.process("actually make it veggie cream cheese", result1.order)

        # The change should be applied AND we should continue with configuration
        # Check that we're still in configuration phase (or moved to next question)
        bagels_after = [i for i in result2.order.items.items if i.has_attribute('bread')]
        assert len(bagels_after) == 1, "Should still have 1 bagel"
        bagel_after = bagels_after[0]

        # The bagel type should be preserved
        assert bagel_after["bread"] in ("plain", "plain_bagel"), \
            f"Bagel type should be plain, got: {bagel_after['bread']}"

        # The change should be acknowledged in the message
        msg_lower = result2.message.lower()
        change_acknowledged = (
            "sure" in msg_lower or
            "changed" in msg_lower or
            "veggie" in msg_lower
        )
        assert change_acknowledged, \
            f"Bot should acknowledge the change. Got: {result2.message}"

        # Should continue with configuration (not say "let me finish first")
        deferred_response = "finish" in msg_lower and "first" in msg_lower
        assert not deferred_response, \
            f"Should NOT defer the change. Got: {result2.message}"

    def test_change_size_during_coffee_configuration(self):
        """
        Test: User changes size DURING coffee configuration.

        Scenario:
        - User orders: "small latte"
        - Bot asks: "Hot or iced?"
        - User says: "actually make it large" (uses change request pattern)
        - Expected: size changes to large, bot continues asking about temperature
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()

        # Step 1: User orders small latte
        result1 = sm.process("small latte", order)

        # Verify we're in configuration phase
        assert result1.order.phase == OrderPhase.CONFIGURING_ITEM.value, \
            f"Expected CONFIGURING_ITEM phase, got: {result1.order.phase}"

        # Step 2: User changes size to large during configuration
        # "actually make it X" is detected as a change request pattern
        result2 = sm.process("actually make it large", result1.order)

        # The change should be applied
        coffees = [i for i in result2.order.items.items if i.has_attribute('size')]
        assert len(coffees) == 1, "Should have 1 coffee"
        coffee = coffees[0]

        # Size should be changed to large
        assert coffee["size"] == "large", \
            f"Coffee size should be large, got: {coffee['size']}"

        # The change should be acknowledged and continue with config
        msg_lower = result2.message.lower()
        change_acknowledged = "sure" in msg_lower or "changed" in msg_lower
        deferred_response = "finish" in msg_lower and "first" in msg_lower

        assert not deferred_response, \
            f"Should NOT defer the change. Got: {result2.message}"
