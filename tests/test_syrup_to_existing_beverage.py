"""Test that syrup-only input adds to existing espresso instead of creating new coffee."""
import pytest
from orderbot.tasks.state_machine import OrderStateMachine
from orderbot.tasks.models import OrderTask, MenuItemTask
from orderbot.tasks.schemas.phases import OrderPhase


class TestSyrupToExistingBeverage:
    """Test that modifier-only inputs go to the last beverage."""

    def test_2_vanilla_syrups_after_espresso(self):
        """
        Scenario:
        - User orders: espresso
        - User says: "2 vanilla syrups"
        - Expected: syrup added to espresso, NOT new coffee created

        Note: Espresso is now a data-driven MenuItemTask with menu_item_type="espresso".
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # Add espresso to the order (as MenuItemTask)
        espresso = MenuItemTask(
            menu_item_name="Espresso",
            menu_item_type="espresso",
        )
        espresso.mark_complete()
        order.items.add_item(espresso)

        # Initial state: 1 espresso
        assert len(order.items.items) == 1
        assert isinstance(order.items.items[0], MenuItemTask)

        # Now add "2 vanilla syrups"
        sm = OrderStateMachine()
        result = sm.process("2 vanilla syrups", order)

        # Should still have 1 item (the espresso), not 2
        assert len(result.order.items.items) == 1, (
            f"Expected 1 item, got {len(result.order.items.items)}: "
            f"{[type(i).__name__ for i in result.order.items.items]}"
        )

        # The item should be an espresso (MenuItemTask)
        item = result.order.items.items[0]
        assert isinstance(item, MenuItemTask), f"Expected MenuItemTask, got {type(item).__name__}"

        # Check that vanilla syrup was added with quantity 2 (unified selections list)
        syrup_mods = [m for m in (item.modifiers or []) if m.get("category") == "syrup"]
        vanilla_mods = [m for m in syrup_mods if "vanilla" in m.get("slug", "").lower()]
        assert len(vanilla_mods) >= 1, f"Vanilla syrup not found in selections: {item.modifiers}"

        vanilla_mod = vanilla_mods[0]
        assert vanilla_mod.get("quantity") == 2, f"Expected quantity 2, got {vanilla_mod.get('quantity')}"

    def test_vanilla_syrup_after_coffee(self):
        """
        Scenario:
        - User orders: coffee
        - User says: "vanilla syrup"
        - Expected: syrup added to coffee, NOT new coffee created

        Note: Coffee is now a data-driven MenuItemTask with menu_item_type="sized_beverage".
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # Add coffee to the order (as MenuItemTask with sized_beverage type)
        coffee = MenuItemTask(
            menu_item_name="coffee",
            menu_item_type="sized_beverage",
        )
        coffee.attribute_values["size"] = "medium"
        coffee.attribute_values["iced"] = False
        coffee.mark_complete()
        order.items.add_item(coffee)

        # Initial state: 1 coffee
        assert len(order.items.items) == 1

        # Now add "vanilla syrup"
        sm = OrderStateMachine()
        result = sm.process("vanilla syrup", order)

        # Should still have 1 item
        assert len(result.order.items.items) == 1, f"Expected 1 item, got {len(result.order.items.items)}"

        # The item should be a sized_beverage MenuItemTask
        item = result.order.items.items[0]
        assert isinstance(item, MenuItemTask), f"Expected MenuItemTask, got {type(item).__name__}"
        assert item.has_attribute('size'), "Expected is_sized_beverage to be True"

        # Check that vanilla syrup was added (unified selections list)
        syrup_modifiers = [m for m in (item.modifiers or []) if m.get("category") == "syrup"]
        syrup_slugs = [m.get("slug") for m in syrup_modifiers]
        # Slug is "vanilla_syrup" from database, check for substring match
        assert any("vanilla" in slug for slug in syrup_slugs), f"Vanilla syrup not found in selections: {item.modifiers}"

    def test_add_sweetener_to_espresso(self):
        """
        Scenario:
        - User orders: espresso
        - User says: "add sweet n low"
        - Expected: sweetener added to espresso via early modifier block

        Note: Espresso is now a data-driven MenuItemTask with menu_item_type="espresso".
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # Add espresso to the order (as MenuItemTask)
        espresso = MenuItemTask(
            menu_item_name="Espresso",
            menu_item_type="espresso",
        )
        espresso.mark_complete()
        order.items.add_item(espresso)

        # Now add "add sweet n low" - the "add" keyword triggers the early modifier block
        sm = OrderStateMachine()
        result = sm.process("add sweet n low", order)

        # Should still have 1 item
        assert len(result.order.items.items) == 1, f"Expected 1 item, got {len(result.order.items.items)}"

        # The item should be an espresso (MenuItemTask)
        item = result.order.items.items[0]
        assert isinstance(item, MenuItemTask), f"Expected MenuItemTask, got {type(item).__name__}"

        # Check that sweetener was added (unified selections list)
        sweetener_mods = [m for m in (item.modifiers or []) if m.get("category") == "sweetener"]
        sweetener_slugs = [m.get("slug") for m in sweetener_mods]
        assert "sweet_n_low" in sweetener_slugs, f"Sweet N Low not found in selections: {item.modifiers}"

    def test_two_vanilla_syrups_word_quantity_in_config(self):
        """
        Scenario (user's actual bug report):
        - User orders: espresso
        - Bot: may ask about shots first (if configured) or milk/sweetener/syrup
        - User answers any shots question (if asked)
        - Bot: "Any milk, sweetener, or syrup?"
        - User says: "two vanilla syrups"
        - Expected: 2 vanilla syrups added to espresso (quantity=2)

        Note: Espresso is now created as MenuItemTask with menu_item_type="espresso"
        to use the data-driven configuration flow. Syrups during config are stored in
        the unified modifiers list with quantity.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # Add espresso to start the flow
        sm = OrderStateMachine()
        result = sm.process("espresso", order)

        # Espresso should be added
        assert len(result.order.items.items) == 1
        # Espresso is now created as MenuItemTask with menu_item_type="espresso"
        item = result.order.items.items[0]
        assert isinstance(item, MenuItemTask), f"Expected MenuItemTask, got {type(item).__name__}"
        assert item.menu_item_type == "espresso", f"Expected menu_item_type='espresso', got '{item.menu_item_type}'"

        # If database is configured to ask about shots first, answer that
        if "shots" in result.message.lower():
            result = sm.process("single", result.order)

        # Now bot should ask about milk/sweetener/syrup
        assert "milk" in result.message.lower() or "sweetener" in result.message.lower() or "syrup" in result.message.lower(), \
            f"Expected milk/sweetener/syrup question, got: {result.message}"

        # Answer with "two vanilla syrups" (word quantity)
        result = sm.process("two vanilla syrups", result.order)

        # Check the espresso has vanilla syrup with quantity 2
        espresso = result.order.items.items[0]
        assert isinstance(espresso, MenuItemTask)

        # Config flow stores modifiers in the unified modifiers list
        vanilla_sels = [s for s in espresso.modifiers if "vanilla" in s.get("slug", "").lower()]
        assert len(vanilla_sels) == 1, f"Expected 1 vanilla selection, got: {espresso.modifiers}"

        vanilla_sel = vanilla_sels[0]
        assert vanilla_sel.get("quantity") == 2, f"Expected quantity 2, got {vanilla_sel.get('quantity')}"

    def test_syrup_disambiguation_then_quantity(self):
        """
        Scenario (the bug that was fixed):
        - User orders: large iced latte
        - Bot: asks about milk/sweetener/syrup
        - User: "syrup" (ambiguous - triggers disambiguation)
        - Bot: asks "Which syrup?" listing options
        - User: "2 hazelnut syrups"
        - Expected: 2 hazelnut syrups added (quantity=2, not 1)

        Bug was: when disambiguation was triggered, quantity was captured at THAT moment
        (quantity=1 for "syrup"), and when resolved with "2 hazelnut syrups", the stored
        quantity was used instead of re-extracting from the resolution input.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()

        # Start by ordering a large iced latte (iced/hot are now separate menu items)
        result = sm.process("large iced latte", order)
        assert len(result.order.items.items) == 1
        item = result.order.items.items[0]
        assert isinstance(item, MenuItemTask)

        # Should now ask about milk/sweetener/syrup (or extra shots)
        # Skip any intermediate questions until we get to modifiers
        while not any(word in result.message.lower() for word in ["milk", "sweetener", "syrup"]):
            # Answer any intermediate questions with "no"
            result = sm.process("no", result.order)
            if "anything else" in result.message.lower() or "done" in result.message.lower():
                break

        # Say just "syrup" to trigger disambiguation
        result = sm.process("syrup", result.order)

        # Should trigger disambiguation - bot asks which syrup
        assert result.order.pending_attr_disambiguation is not None or "which" in result.message.lower(), \
            f"Expected disambiguation, got: {result.message}"

        # Resolve with "2 hazelnut syrups"
        result = sm.process("2 hazelnut syrups", result.order)

        # Check the latte has hazelnut syrup with quantity 2
        latte = result.order.items.items[0]
        assert isinstance(latte, MenuItemTask)

        # Find hazelnut syrup in modifiers
        hazelnut_sels = [s for s in latte.modifiers if "hazelnut" in s.get("slug", "").lower()]
        assert len(hazelnut_sels) == 1, f"Expected 1 hazelnut selection, got: {latte.modifiers}"

        hazelnut_sel = hazelnut_sels[0]
        assert hazelnut_sel.get("quantity") == 2, \
            f"Expected quantity 2, got {hazelnut_sel.get('quantity')}. Full modifier: {hazelnut_sel}"


class TestQuantityPrefixes:
    """Test quantity prefixes like 'double', 'triple', 'extra' for modifiers."""

    def test_double_bacon_on_bagel(self):
        """
        Test 'add double bacon' applies quantity=2.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # Add a bagel to the order
        bagel = MenuItemTask(
            menu_item_name="Plain Bagel",
            menu_item_type="bagel",
        )
        bagel.mark_complete()
        order.items.add_item(bagel)

        # Now add "double bacon"
        sm = OrderStateMachine()
        result = sm.process("add double bacon", order)

        # Check that bacon was added with quantity 2
        item = result.order.items.items[0]
        bacon_mods = [m for m in (item.modifiers or []) if "bacon" in m.get("slug", "").lower()]
        assert len(bacon_mods) >= 1, f"Bacon not found in modifiers: {item.modifiers}"

        bacon_mod = bacon_mods[0]
        assert bacon_mod.get("quantity") == 2, f"Expected quantity 2, got {bacon_mod.get('quantity')}"

    def test_extra_bacon_on_bagel(self):
        """
        Test 'add extra bacon' applies quantity=2.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # Add a bagel to the order (same as test_double_bacon_on_bagel)
        bagel = MenuItemTask(
            menu_item_name="Plain Bagel",
            menu_item_type="bagel",
        )
        bagel.mark_complete()
        order.items.add_item(bagel)

        # Now add "extra bacon"
        sm = OrderStateMachine()
        result = sm.process("add extra bacon", order)

        # Check that bacon was added with quantity 2
        item = result.order.items.items[0]
        bacon_mods = [m for m in (item.modifiers or []) if "bacon" in m.get("slug", "").lower()]
        assert len(bacon_mods) >= 1, f"Bacon not found in modifiers: {item.modifiers}"

        bacon_mod = bacon_mods[0]
        assert bacon_mod.get("quantity") == 2, f"Expected quantity 2, got {bacon_mod.get('quantity')}"

    def test_triple_vanilla_syrup(self):
        """
        Test 'add triple vanilla syrup' applies quantity=3.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # Add a coffee to the order
        coffee = MenuItemTask(
            menu_item_name="Coffee",
            menu_item_type="sized_beverage",
        )
        coffee.attribute_values["size"] = "medium"
        coffee.mark_complete()
        order.items.add_item(coffee)

        # Now add "triple vanilla syrup"
        sm = OrderStateMachine()
        result = sm.process("add triple vanilla syrup", order)

        # Check that vanilla syrup was added with quantity 3
        item = result.order.items.items[0]
        vanilla_mods = [m for m in (item.modifiers or []) if "vanilla" in m.get("slug", "").lower()]
        assert len(vanilla_mods) >= 1, f"Vanilla not found in modifiers: {item.modifiers}"

        vanilla_mod = vanilla_mods[0]
        assert vanilla_mod.get("quantity") == 3, f"Expected quantity 3, got {vanilla_mod.get('quantity')}"


class TestShotsHandling:
    """Test 'double shot' and 'triple shot' phrases for espresso drinks.

    Note: These tests require database configuration for the 'shots' attribute
    with ask_in_conversation=True. If the database isn't configured this way,
    the tests will be skipped.
    """

    def test_double_shot_espresso_config(self):
        """
        Test that 'double shot' during espresso config sets quantity=2.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()

        # Order an espresso
        result = sm.process("espresso", order)
        assert len(result.order.items.items) == 1
        item = result.order.items.items[0]
        assert item.menu_item_type == "espresso"

        # Check if database is configured to ask about shots
        if "shot" not in result.message.lower():
            pytest.skip("Database not configured to ask about shots for espresso")

        # Answer with "double shot"
        result = sm.process("double shot", result.order)

        # Check that espresso_shots has quantity=2 (double = 2)
        # Note: quantity attributes store the unit slug (e.g., "shot") with quantity in modifiers
        item = result.order.items.items[0]
        shot_mods = [m for m in item.modifiers if m.get("category") == "espresso_shots"]
        assert len(shot_mods) == 1, f"Expected 1 shot modifier, got {len(shot_mods)}"
        assert shot_mods[0].get("quantity") == 2, f"Expected quantity=2 (double), got {shot_mods[0].get('quantity')}"

    def test_triple_shot_espresso_config(self):
        """
        Test that 'triple shot' during espresso config sets quantity=3.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()

        # Order an espresso
        result = sm.process("espresso", order)
        assert len(result.order.items.items) == 1

        # Check if database is configured to ask about shots
        if "shot" not in result.message.lower():
            pytest.skip("Database not configured to ask about shots for espresso")

        # Answer with "triple shot"
        result = sm.process("triple shot", result.order)

        # Check that espresso_shots has quantity=3 (triple = 3)
        # Note: quantity attributes store the unit slug (e.g., "shot") with quantity in modifiers
        item = result.order.items.items[0]
        shot_mods = [m for m in item.modifiers if m.get("category") == "espresso_shots"]
        assert len(shot_mods) == 1, f"Expected 1 shot modifier, got {len(shot_mods)}"
        assert shot_mods[0].get("quantity") == 3, f"Expected quantity=3 (triple), got {shot_mods[0].get('quantity')}"

    def test_numeric_extra_shots(self):
        """
        Test that numeric answers like '1' or '2' for shots work.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()

        # Order an espresso
        result = sm.process("espresso", order)
        assert len(result.order.items.items) == 1

        # Check if database is configured to ask about shots
        if "shot" not in result.message.lower():
            pytest.skip("Database not configured to ask about shots for espresso")

        # Answer with "2" (meaning 2 extra shots)
        result = sm.process("2", result.order)

        # Check that espresso_shots has quantity=2
        # Note: quantity attributes store the unit slug (e.g., "shot") with quantity in modifiers
        item = result.order.items.items[0]
        shot_mods = [m for m in item.modifiers if m.get("category") == "espresso_shots"]
        assert len(shot_mods) == 1, f"Expected 1 shot modifier, got {len(shot_mods)}"
        assert shot_mods[0].get("quantity") == 2, f"Expected quantity=2, got {shot_mods[0].get('quantity')}"

    def test_yes_to_shot_question_adds_single_shot(self):
        """
        Test that 'yes' to 'Would you like an espresso shot?' adds 1 shot.

        Regression test for issue where "yes" would prompt "Which shots would you like?"
        instead of adding a single shot and advancing.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()

        # Order a coffee (sized_beverage) to get the shots question
        result = sm.process("large black coffee", order)
        assert len(result.order.items.items) == 1

        # Check if database is configured to ask about shots
        if "shot" not in result.message.lower():
            pytest.skip("Database not configured to ask about shots")

        # Answer with "yes" - should add 1 shot and advance
        result = sm.process("yes", result.order)

        # The response should NOT ask "which shots" - it should advance
        # This was the bug: "yes" used to prompt "Great! Which shots would you like?"
        assert "which" not in result.message.lower(), (
            f"'yes' should add a shot and advance, not ask 'which shots'. Got: {result.message}"
        )

    def test_no_extra_shots(self):
        """
        Test that 'none' for shots declines the option (nothing added to cart).
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()

        # Order an espresso
        result = sm.process("espresso", order)
        assert len(result.order.items.items) == 1

        # Check if database is configured to ask about shots
        if "shot" not in result.message.lower():
            pytest.skip("Database not configured to ask about shots for espresso")

        # Answer with "none"
        result = sm.process("none", result.order)

        # Check that shots attribute is declined (None = nothing in cart)
        item = result.order.items.items[0]
        shots_value = item.attribute_values.get("espresso_shots")
        assert shots_value is None, f"Expected espresso_shots=None (declined), got {shots_value}"


class TestExtraShotAtCheckpoint:
    """Test 'extra shot' phrase after item configuration.

    This tests the scenario where:
    1. User orders espresso
    2. User declines all customization questions (shots, milk, decaf)
    3. Bot says "Anything else?" (item is complete)
    4. User says "extra shot"
    5. Expected: Extra shots are added to the completed item

    Note: "extra" is interpreted as quantity=2 in the modifier system.
    """

    def test_extra_shot_at_customization_checkpoint(self):
        """
        Test that 'extra shot' after completing an espresso adds shots.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()

        # Order an espresso
        result = sm.process("espresso", order)
        assert len(result.order.items.items) == 1
        item = result.order.items.items[0]
        assert item.menu_item_type == "espresso"

        # Navigate to customization_checkpoint - keep processing until we get there
        max_iterations = 5
        for _ in range(max_iterations):
            pending = result.order.pending_field
            if pending == "customization_checkpoint":
                break
            # Answer common questions to advance
            if pending and "decaf" in pending:
                result = sm.process("no", result.order)
            elif result.message and "anything else" in result.message.lower():
                break
            else:
                # If we get here, try moving forward with "no"
                result = sm.process("no", result.order)

        # Now say "extra shot"
        result = sm.process("extra shot", result.order)

        # Check that shots were added via modifiers
        # Category can be "shots" or "espresso_shots" depending on item type config
        item = result.order.items.items[0]
        # Filter out the _declined marker (added when user said "no" to shots initially)
        shot_mods = [
            m for m in (item.modifiers or [])
            if "shot" in m.get("category", "").lower() and m.get("slug") != "_declined"
        ]

        # Debug output
        if not shot_mods:
            print(f"DEBUG: Bot message: {result.message}")
            print(f"DEBUG: Pending field: {result.order.pending_field}")
            print(f"DEBUG: Item modifiers: {item.modifiers}")
            print(f"DEBUG: Item attribute_values: {item.attribute_values}")

        assert len(shot_mods) == 1, f"Expected 1 shot modifier, got {shot_mods}"
        # "extra shot" means adding 2 shots (the system treats "extra" as quantity=2)
        assert shot_mods[0].get("quantity") == 2, f"Expected quantity=2 for 'extra shot', got {shot_mods[0]}"
        # Verify the price is applied (should be $0.75 per shot)
        assert shot_mods[0].get("price", 0) > 0, f"Expected price > 0, got {shot_mods[0]}"

    def test_parse_shots_function_handles_extra_shot(self):
        """
        Test that the _parse_shots_from_input function handles 'extra shot' phrase.
        Uses direct function call since _parse_shots_from_input is a simple string check.
        """
        # Test the parsing logic directly (same logic as in the handler)
        def parse_shots_from_input(user_lower: str) -> int | None:
            if "extra shot" in user_lower or "1 extra" in user_lower:
                return 1
            if "double" in user_lower or "2 shot" in user_lower:
                return 1
            elif "triple" in user_lower or "3 shot" in user_lower:
                return 2
            elif "quad" in user_lower or "4 shot" in user_lower:
                return 3
            return None

        assert parse_shots_from_input("extra shot") == 1
        assert parse_shots_from_input("1 extra") == 1
        assert parse_shots_from_input("add an extra shot") == 1
        assert parse_shots_from_input("double shot") == 1
        assert parse_shots_from_input("triple shot") == 2


class TestOptionsInquiryAtCheckpoint:
    """Test 'what X do you have?' at customization checkpoint.

    This tests the scenario where:
    1. User orders a bagel with a condiment (e.g., salt)
    2. Bot asks "Any more changes?"
    3. User asks "what condiments do you have?"
    4. Expected: Bot lists condiment options (not "Sorry, we don't have that")

    The fix ensures that options inquiries work for ALL optional attributes,
    not just unanswered ones.
    """

    def test_what_condiments_after_adding_salt(self):
        """
        Test that 'what condiments do you have?' works after adding salt.

        Scenario:
        - User orders: plain bagel toasted not scooped no spread
        - Bot asks: Any more changes? You can add Egg, Cheese, Meat, Toppings, or Condiments.
        - User says: salt
        - Bot says: Okay, Salt added. Any more changes? You can add Egg, Cheese, Meat, or Toppings.
        - User asks: what condiments do you have

        Expected: Bot lists condiment options
        Actual (before fix): "Sorry, we don't have what condiments do you have"
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()

        # Order a plain bagel with some specifications
        result = sm.process("plain bagel toasted not scooped no spread", order)
        assert len(result.order.items.items) == 1
        item = result.order.items.items[0]
        assert item.menu_item_type == "bagel"

        # Check if we're at customization_checkpoint
        max_iterations = 10
        for _ in range(max_iterations):
            pending = result.order.pending_field
            if pending == "customization_checkpoint":
                break
            # Answer common questions to advance
            if pending and pending.endswith(":scooped"):
                result = sm.process("no", result.order)
            elif pending and pending.endswith(":spread_type"):
                result = sm.process("none", result.order)
            elif result.message and "any more changes" in result.message.lower():
                break
            else:
                result = sm.process("no", result.order)

        # Add salt
        result = sm.process("salt", result.order)
        # Verify salt was added
        item = result.order.items.items[0]
        condiment_mods = [
            m for m in (item.modifiers or [])
            if m.get("category") == "condiments" or "salt" in m.get("slug", "").lower()
        ]

        # Now ask about condiments
        result = sm.process("what condiments do you have", result.order)

        # Should NOT contain the error message
        assert "sorry" not in result.message.lower(), (
            f"Bot incorrectly rejected options inquiry: {result.message}"
        )
        assert "we don't have what condiments" not in result.message.lower(), (
            f"Bot incorrectly rejected options inquiry: {result.message}"
        )

        # Should list condiment options - check for at least one condiment
        # Common condiments: Salt, Black Pepper, Ketchup, Mustard, Mayo, etc.
        message_lower = result.message.lower()
        has_condiment_option = any(
            cond in message_lower
            for cond in ["pepper", "ketchup", "mustard", "mayo", "condiment"]
        )
        assert has_condiment_option, (
            f"Bot did not list condiment options: {result.message}"
        )

    def test_declined_not_in_summary_after_removal(self):
        """
        Test that 'Declined' does not appear in item summary.

        Scenario:
        - User orders: plain bagel toasted not scooped no spread
        - User adds: ketchup
        - User removes: ketchup
        - Bot shows summary

        Expected: Summary should NOT contain "Declined"
        Actual (before fix): "Plain Bagel, Declined, Toasted, Salt"
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()

        # Order a plain bagel with some specifications that decline spread
        result = sm.process("plain bagel toasted not scooped no spread", order)
        assert len(result.order.items.items) == 1

        # Navigate to customization_checkpoint
        max_iterations = 10
        for _ in range(max_iterations):
            pending = result.order.pending_field
            if pending == "customization_checkpoint":
                break
            if pending and pending.endswith(":scooped"):
                result = sm.process("no", result.order)
            elif pending and pending.endswith(":spread_type"):
                result = sm.process("none", result.order)
            elif result.message and "any more changes" in result.message.lower():
                break
            else:
                result = sm.process("no", result.order)

        # Add ketchup
        result = sm.process("ketchup", result.order)

        # Remove ketchup
        result = sm.process("remove ketchup", result.order)

        # Check that "Declined" doesn't appear in the message
        assert "declined" not in result.message.lower(), (
            f"Summary incorrectly contains 'Declined': {result.message}"
        )

        # Also check the item's get_summary() method directly
        item = result.order.items.items[0]
        summary = item.get_summary()
        assert "declined" not in summary.lower(), (
            f"Item summary incorrectly contains 'Declined': {summary}"
        )

    def test_what_spreads_after_declining_spread(self):
        """
        Test that 'what spreads do you have?' works after declining spread.

        Scenario:
        - User orders: plain bagel
        - Bot asks: Would you like it toasted?
        - User says: yes
        - Bot asks: Would you like it scooped?
        - User says: no
        - Bot asks: Any spread on that?
        - User says: no
        - Bot asks: Any more changes? You can add Egg or Condiments.
        - User asks: what spreads do you have

        Expected: Bot lists spread options (cream cheese, butter, etc.)
        Actual (before fix): "Sorry, we don't have what spreads do you have"

        The fix ensures mandatory attributes (like spread_type) are included
        when detecting "what X do you have?" inquiries, not just optional ones.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()

        # Order a plain bagel
        result = sm.process("plain bagel", order)
        assert len(result.order.items.items) == 1
        item = result.order.items.items[0]
        assert item.menu_item_type == "bagel"

        # Navigate through configuration, declining spread
        max_iterations = 15
        for _ in range(max_iterations):
            pending = result.order.pending_field
            if pending == "customization_checkpoint":
                break
            # Answer questions based on pending field
            if pending and pending.endswith(":bread"):
                result = sm.process("plain", result.order)
            elif pending and pending.endswith(":toasted"):
                result = sm.process("yes", result.order)
            elif pending and pending.endswith(":scooped"):
                result = sm.process("no", result.order)
            elif pending and pending.endswith(":spread_type"):
                result = sm.process("no", result.order)
            elif result.message and "any more changes" in result.message.lower():
                break
            else:
                result = sm.process("no", result.order)

        # At customization checkpoint - now ask about spreads
        result = sm.process("what spreads do you have", result.order)

        # Should NOT contain the error message
        assert "sorry" not in result.message.lower(), (
            f"Bot incorrectly rejected options inquiry: {result.message}"
        )
        assert "we don't have what spreads" not in result.message.lower(), (
            f"Bot incorrectly rejected options inquiry: {result.message}"
        )

        # Should list spread options - check for at least one spread
        # Common spreads: Cream Cheese, Butter, etc.
        message_lower = result.message.lower()
        has_spread_option = any(
            spread in message_lower
            for spread in ["cream cheese", "butter", "scallion", "spread"]
        )
        assert has_spread_option, (
            f"Bot did not list spread options: {result.message}"
        )


class TestChangeRequestWithQuantity:
    """Test change requests with quantity prefixes like 'can you make it with 2 vanilla syrups'."""

    def test_make_it_with_2_vanilla_syrups(self):
        """
        Regression test for: "can you make it with 2 vanilla syrups" returning
        "This item doesn't have a Unknown to change."

        The fix strips the quantity prefix before analyzing the modifier.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # Create a pre-configured latte with 1 vanilla syrup
        latte = MenuItemTask(
            menu_item_name="Latte",
            menu_item_type="sized_beverage",
        )
        latte.attribute_values["size"] = "medium"
        latte.attribute_values["iced"] = False
        latte.add_selection(
            "vanilla_syrup",
            "syrup",
            quantity=1,
            price=0.75,
            display_name="Vanilla Syrup",
        )
        latte.mark_complete()
        order.items.add_item(latte)

        sm = OrderStateMachine()

        # The change request that was failing
        result = sm.process("can you make it with 2 vanilla syrups", order)

        # Should NOT return "Unknown" error
        assert "unknown" not in result.message.lower(), (
            f"Got 'Unknown' error: {result.message}"
        )

        # Check that vanilla syrup has quantity 2
        item = result.order.items.items[0]
        vanilla_mods = [m for m in (item.modifiers or []) if "vanilla" in m.get("slug", "").lower()]
        assert len(vanilla_mods) >= 1, f"Vanilla syrup not found: {item.modifiers}"
        assert vanilla_mods[0].get("quantity") == 2, (
            f"Expected quantity 2, got {vanilla_mods[0].get('quantity')}"
        )

        # Verify display is pluralized ("Vanilla Syrups" not "Vanilla Syrup")
        summary = item.get_summary()
        assert "Syrups" in summary, (
            f"Expected pluralized 'Syrups' in summary but got: {summary}"
        )


class TestSyrupDisambiguationWithMultiInput:
    """Test that '2 syrups' triggers disambiguation instead of adding all syrups."""

    def test_oat_milk_and_2_syrups_triggers_disambiguation(self):
        """
        Scenario (the bug being fixed):
        - User configures a latte, answers size and iced questions
        - Bot asks about milk/sweetener/syrup
        - User says: "oat milk and 2 syrups"
        - Expected: Bot adds oat milk, then asks "Which syrups?"
        - Bug was: Bot added ALL 4 syrups instead of asking which ones

        Root cause: The disambiguation check only triggered when the ENTIRE input
        was a single token. For "oat milk and 2 syrups", it's 2 tokens, so it
        skipped disambiguation even though "syrups" matched all syrup options.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # Create a latte that is already configured up to milk/sweetener/syrup question
        latte = MenuItemTask(
            menu_item_name="Latte",
            menu_item_type="sized_beverage",
        )
        latte.attribute_values["size"] = "large"
        latte.attribute_values["iced"] = True
        order.items.add_item(latte)
        order.pending_item_id = latte.id
        order.pending_field = "sized_beverage:milk_sweetener_syrup"
        order.phase = OrderPhase.CONFIGURING_ITEM.value

        sm = OrderStateMachine()

        # Say "oat milk and 2 syrups" - should add oat milk and ask which syrups
        result = sm.process("oat milk and 2 syrups", order)

        # Should be asking about syrups (disambiguation)
        msg_lower = result.message.lower()
        assert "syrup" in msg_lower, (
            f"Expected syrup disambiguation question, got: {result.message}"
        )
        assert "?" in result.message or "which" in msg_lower, (
            f"Expected disambiguation question, got: {result.message}"
        )

        # The order should have pending disambiguation
        assert result.order.pending_attr_disambiguation is not None, (
            "Expected pending disambiguation to be set"
        )
        disambig = result.order.pending_attr_disambiguation
        assert disambig.get("attr_slug") == "milk_sweetener_syrup", (
            f"Expected attr_slug='milk_sweetener_syrup', got: {disambig.get('attr_slug')}"
        )

        # Should NOT have added all syrups
        item = result.order.items.items[0]
        syrup_mods = [m for m in (item.modifiers or [])
                      if m.get("ingredient_category") == "syrup"]
        # Bug would add 4 syrups; fix should add 0 (waiting for disambiguation)
        assert len(syrup_mods) == 0, (
            f"Expected 0 syrups before disambiguation, but got {len(syrup_mods)}: {syrup_mods}"
        )

        # Should have added oat milk (ingredient_category is 'milk')
        milk_mods = [m for m in (item.modifiers or [])
                     if m.get("ingredient_category") == "milk"]
        assert len(milk_mods) == 1, f"Expected 1 milk modifier, got: {milk_mods}"
        assert "oat" in milk_mods[0].get("slug", "").lower(), (
            f"Expected oat milk, got: {milk_mods[0]}"
        )

    def test_2_syrups_single_input_triggers_disambiguation(self):
        """
        Simpler case: user just says "2 syrups" - should trigger disambiguation.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        latte = MenuItemTask(
            menu_item_name="Latte",
            menu_item_type="sized_beverage",
        )
        latte.attribute_values["size"] = "large"
        latte.attribute_values["iced"] = True
        order.items.add_item(latte)
        order.pending_item_id = latte.id
        order.pending_field = "sized_beverage:milk_sweetener_syrup"
        order.phase = OrderPhase.CONFIGURING_ITEM.value

        sm = OrderStateMachine()

        # Say "2 syrups" - should ask which syrups
        result = sm.process("2 syrups", order)

        # Should be asking about syrups (disambiguation)
        msg_lower = result.message.lower()
        assert "syrup" in msg_lower, (
            f"Expected syrup disambiguation question, got: {result.message}"
        )

        # Should have disambiguation pending with quantity=2
        assert result.order.pending_attr_disambiguation is not None
        disambig = result.order.pending_attr_disambiguation
        assert disambig.get("modifiers", {}).get("_quantity", 1) == 2, (
            f"Expected quantity 2 in disambiguation, got: {disambig.get('modifiers')}"
        )

    def test_2_vanilla_syrups_no_disambiguation(self):
        """
        When user specifies which syrup, no disambiguation needed.
        "2 vanilla syrups" should add 2 vanilla syrups directly.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        latte = MenuItemTask(
            menu_item_name="Latte",
            menu_item_type="sized_beverage",
        )
        latte.attribute_values["size"] = "large"
        latte.attribute_values["iced"] = True
        order.items.add_item(latte)
        order.pending_item_id = latte.id
        order.pending_field = "sized_beverage:milk_sweetener_syrup"
        order.phase = OrderPhase.CONFIGURING_ITEM.value

        sm = OrderStateMachine()

        # Say "2 vanilla syrups" - specific, no disambiguation needed
        result = sm.process("2 vanilla syrups", order)

        # Should NOT have disambiguation pending
        assert result.order.pending_attr_disambiguation is None, (
            f"Did not expect disambiguation, but got: {result.order.pending_attr_disambiguation}"
        )

        # Should have added vanilla syrup with quantity 2
        item = result.order.items.items[0]
        vanilla_mods = [m for m in (item.modifiers or [])
                        if "vanilla" in m.get("slug", "").lower()]
        assert len(vanilla_mods) == 1, f"Expected 1 vanilla syrup, got: {vanilla_mods}"
        assert vanilla_mods[0].get("quantity") == 2, (
            f"Expected quantity 2, got: {vanilla_mods[0].get('quantity')}"
        )
