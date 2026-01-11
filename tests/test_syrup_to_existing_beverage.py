"""Test that syrup-only input adds to existing espresso instead of creating new coffee."""
import pytest
from sandwich_bot.tasks.state_machine import OrderStateMachine
from sandwich_bot.tasks.models import OrderTask, MenuItemTask
from sandwich_bot.tasks.schemas.phases import OrderPhase


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

        # Check that vanilla syrup was added with quantity 2
        # Data-driven espresso stores syrups in attribute_values["milk_sweetener_syrup_selections"]
        modifier_selections = item.attribute_values.get("milk_sweetener_syrup_selections", [])
        vanilla_mods = [m for m in modifier_selections if "vanilla" in m.get("slug", "").lower()]
        assert len(vanilla_mods) >= 1, f"Vanilla syrup not found in modifiers: {modifier_selections}"

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
        coffee.size = "medium"
        coffee.iced = False
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
        assert item.is_sized_beverage, "Expected is_sized_beverage to be True"

        # Check that vanilla syrup was added
        syrup_flavors = [s.get("flavor") for s in item.flavor_syrups]
        assert "vanilla" in syrup_flavors, f"Vanilla syrup not found in syrups: {item.flavor_syrups}"

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

        # Check that sweetener was added
        # Data-driven espresso stores sweeteners in attribute_values["milk_sweetener_syrup_selections"]
        modifier_selections = item.attribute_values.get("milk_sweetener_syrup_selections", [])
        sweetener_slugs = [m.get("slug") for m in modifier_selections]
        assert "sweet_n_low" in sweetener_slugs, f"Sweet N Low not found in modifiers: {modifier_selections}"

    def test_two_vanilla_syrups_word_quantity_in_config(self):
        """
        Scenario (user's actual bug report):
        - User orders: espresso
        - Bot: "Got it, espresso. How many shots?" (shots has display_order=1)
        - User says: "single"
        - Bot: "Any milk, sweetener, or syrup?" (milk_sweetener_syrup has display_order=2)
        - User says: "two vanilla syrups"
        - Expected: 2 vanilla syrups added to espresso (quantity=2)

        Note: Espresso is now created as MenuItemTask with menu_item_type="espresso"
        to use the data-driven configuration flow. Syrups are stored in
        attribute_values["milk_sweetener_syrup_selections"] with quantity.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # Add espresso to start the flow
        sm = OrderStateMachine()
        result = sm.process("espresso", order)

        # Espresso should be added and bot should ask about shots first
        assert len(result.order.items.items) == 1
        # Espresso is now created as MenuItemTask with menu_item_type="espresso"
        item = result.order.items.items[0]
        assert isinstance(item, MenuItemTask), f"Expected MenuItemTask, got {type(item).__name__}"
        assert item.menu_item_type == "espresso", f"Expected menu_item_type='espresso', got '{item.menu_item_type}'"
        assert "shots" in result.message.lower(), f"Expected shots question, got: {result.message}"

        # Answer the shots question
        result = sm.process("single", result.order)

        # Now bot should ask about milk/sweetener/syrup
        assert "milk" in result.message.lower() or "sweetener" in result.message.lower() or "syrup" in result.message.lower(), \
            f"Expected milk/sweetener/syrup question, got: {result.message}"

        # Answer with "two vanilla syrups" (word quantity)
        result = sm.process("two vanilla syrups", result.order)

        # Check the espresso has vanilla syrup with quantity 2
        espresso = result.order.items.items[0]
        assert isinstance(espresso, MenuItemTask)

        # For data-driven espresso, syrups are stored in attribute_values["milk_sweetener_syrup_selections"]
        modifier_selections = espresso.attribute_values.get("milk_sweetener_syrup_selections", [])
        vanilla_mods = [m for m in modifier_selections if "vanilla" in m.get("slug", "").lower()]
        assert len(vanilla_mods) == 1, f"Expected 1 vanilla modifier, got: {modifier_selections}"

        vanilla_mod = vanilla_mods[0]
        assert vanilla_mod.get("quantity") == 2, f"Expected quantity 2, got {vanilla_mod.get('quantity')}"
