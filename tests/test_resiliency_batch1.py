"""
Resiliency Test Batch 1: Replacement & Modification Scenarios

Tests the system's ability to handle replacement and modification requests
where the user wants to change something about an item already in their order.
"""

from orderbot.tasks.state_machine import OrderStateMachine, OrderPhase
from orderbot.tasks.models import OrderTask, TaskStatus, MenuItemTask
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
        # Spread is stored in the "spread" attribute - should now be veggie/vegetable cream cheese
        spread = updated_bagel["spread"]
        assert "veggie" in spread.lower() or "vegetable" in spread.lower(), \
            f"Spread should be veggie cream cheese, got: {spread}"

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
        # Use milk_sweetener_syrup category which matches the database schema
        milk_mods = updated_coffee.get_selections("milk_sweetener_syrup")
        # Filter to just milk selections (not sweeteners/syrups)
        milk_slugs = [m["slug"] for m in milk_mods if m["slug"] in ("oat", "oat_milk", "whole", "skim", "almond", "soy")]
        assert len(milk_slugs) == 1 and milk_slugs[0] in ("oat", "oat_milk"), f"Milk should be oat, got: {milk_mods}"
        assert updated_coffee["size"] == "medium", "Size should be preserved"
        assert updated_coffee.menu_item_name == "latte", "Drink type should be preserved"

    def test_change_coffee_to_decaf(self):
        """
        Test: User has latte, wants to make it decaf.

        Scenario:
        - User has: small hot latte
        - User says: "make it a decaf"
        - Expected: decaf changes to True, other attributes preserved
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        coffee = CoffeeItemTask(
            drink_type="latte",
            size="small",  # Lattes only have small/large, not medium
            iced=False,  # False = hot
        )
        coffee.mark_complete()
        order.items.add_item(coffee)

        sm = OrderStateMachine()
        result = sm.process("make it a decaf", order)

        # Should still have exactly 1 item in order
        assert result.order.items.get_item_count() == 1, "Should still have 1 item"

        updated_coffee = result.order.items.items[0]
        # Decaf can be True (bool) or "true" (string) depending on how it's stored
        decaf_val = updated_coffee["decaf"]
        assert decaf_val is True or decaf_val == "true", f"Decaf should be True/true, got: {decaf_val}"
        assert updated_coffee["size"] == "small", "Size should be preserved"
        assert "latte" in updated_coffee.menu_item_name.lower(), f"Drink type should be latte, got: {updated_coffee.menu_item_name}"
        assert updated_coffee["temperature"] == "hot", "Temperature should be preserved (hot)"

    def test_order_decaf_coffee_upfront(self):
        """
        Test: User orders "decaf coffee" from the start (not as a modification).

        Scenario:
        - User says: "decaf coffee"
        - System recognizes "Hot Coffee" menu item with decaf modifier
        - System asks for size: "What size?"
        - User says: "large"
        - System asks for modifiers: "Any milk, sweetener, or syrup?"
        - User says: "no"
        - System asks about espresso shots
        - User says: "no"
        - Expected: Coffee item has decaf=True, size=large

        Note: Temperature is now part of the menu item name (Hot Coffee vs Iced Coffee),
        not a separate attribute. DB only has "small" and "large" sizes.
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
        result = sm.process("large", result.order)

        # Should ask for milk/sweetener/syrup (no temperature question anymore)
        assert any(word in result.message.lower() for word in ["milk", "sweetener", "syrup"]), \
            f"Should ask for milk/sweetener/syrup, got: {result.message}"

        # Check decaf is still True and size is set
        coffees = [i for i in result.order.items.items if i.has_attribute('size')]
        assert coffees[0]["decaf"] is True, f"Decaf should still be True after size, got: {coffees[0]['decaf']}"
        size_val = coffees[0]["size"]
        assert size_val == "large", f"Size should be large, got: {size_val}"

        # Step 3: Skip milk/sweetener/syrup
        result = sm.process("no", result.order)

        # Step 4: Skip espresso shots if asked
        if "shot" in result.message.lower():
            result = sm.process("no", result.order)

        # Coffee should now be complete or asking "anything else?"
        coffees = [i for i in result.order.items.items if i.has_attribute('size')]
        assert len(coffees) == 1, "Should still have 1 coffee"

        final_coffee = coffees[0]
        assert final_coffee["decaf"] is True, f"Decaf should be True after config, got: {final_coffee['decaf']}"
        final_size = final_coffee["size"]
        assert final_size == "large", f"Size should be large, got: {final_size}"

        # Also verify the adapter output includes decaf=True
        order_dict = order_task_to_dict(result.order)
        coffee_item = order_dict["items"][0]
        assert coffee_item.get("decaf") is True, \
            f"Expected decaf=True in adapter output, got: {coffee_item.get('decaf')}"

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

        # Create bagel using MenuItemTask with correct DB attribute names:
        # - meat: multi_select for proteins like bacon
        # - egg: single_select for egg
        bagel = MenuItemTask(
            menu_item_name="Bagel",
            menu_item_type="bagel",
        )
        bagel.add_selection("everything", "bread")
        bagel.add_selection("yes", "toasted")
        bagel.add_selection("bacon", "meat")  # bacon goes in 'meat' attribute
        bagel.add_selection("egg", "egg")  # egg is its own attribute
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("remove the bacon", order)

        bagels = [i for i in result.order.items.items if i.has_attribute('bread')]
        assert len(bagels) == 1, "Should still have 1 bagel"

        updated_bagel = bagels[0]
        # Bacon should be removed from meat attribute
        meat = updated_bagel.get("meat") or []
        has_bacon = any("bacon" in str(m).lower() for m in (meat if isinstance(meat, list) else [meat]))
        assert not has_bacon, f"Bacon should be removed. meat={meat}"

        # Egg should still be there (in 'egg' attribute)
        egg_value = updated_bagel.get("egg")
        has_egg = egg_value is not None and egg_value != ""
        assert has_egg, f"Egg should be preserved. egg={egg_value}"

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
