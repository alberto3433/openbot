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
        - User orders: latte
        - Bot: asks about size
        - User: large
        - Bot: asks about iced
        - User: iced
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

        # Start by ordering a latte
        result = sm.process("latte", order)
        assert len(result.order.items.items) == 1
        item = result.order.items.items[0]
        assert isinstance(item, MenuItemTask)

        # Answer size question (use "large" which is a valid size)
        result = sm.process("large", result.order)

        # Answer iced question
        result = sm.process("iced", result.order)

        # Should now ask about milk/sweetener/syrup
        assert any(word in result.message.lower() for word in ["milk", "sweetener", "syrup"]), \
            f"Expected milk/sweetener/syrup question, got: {result.message}"

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
        Test that 'double shot' during espresso config sets extra_shots=1.
        (double = 2 total shots, minus 1 base shot = 1 extra)
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

        # Check that shots attribute is set to 1 (1 extra shot)
        item = result.order.items.items[0]
        shots_value = item.attribute_values.get("shots")
        assert shots_value == 1, f"Expected shots=1 (1 extra for double), got {shots_value}"

    def test_triple_shot_espresso_config(self):
        """
        Test that 'triple shot' during espresso config sets extra_shots=2.
        (triple = 3 total shots, minus 1 base shot = 2 extra)
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

        # Check that shots attribute is set to 2 (2 extra shots)
        item = result.order.items.items[0]
        shots_value = item.attribute_values.get("shots")
        assert shots_value == 2, f"Expected shots=2 (2 extra for triple), got {shots_value}"

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

        # Check that shots attribute is set to 2
        item = result.order.items.items[0]
        shots_value = item.attribute_values.get("shots")
        assert shots_value == 2, f"Expected shots=2, got {shots_value}"

    def test_no_extra_shots(self):
        """
        Test that 'none' for shots sets extra_shots=0.
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

        # Check that shots attribute is set to 0
        item = result.order.items.items[0]
        shots_value = item.attribute_values.get("shots")
        assert shots_value == 0, f"Expected shots=0, got {shots_value}"
