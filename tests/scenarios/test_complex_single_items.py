"""
Complex Single-Item Order Tests.

These tests focus on single items with complex modifier combinations,
special instructions, and edge cases that are harder to parse.

Run with: pytest tests/scenarios/ -v
"""

import pytest
from orderbot.tasks.state_machine import OrderStateMachine
from orderbot.tasks.models import OrderTask
from orderbot.tasks.schemas import OrderPhase


class TestComplexBagelOrders:
    """Complex bagel orders with multiple modifiers and special requests."""

    def test_bagel_with_five_modifiers(self):
        """Everything bagel with lox, capers, red onion, tomato, and cream cheese."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Everything bagel with lox, capers, red onion, tomato, and cream cheese please",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_bagel_with_extra_and_light_modifiers(self):
        """Bagel with extra cream cheese and light onion."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Sesame bagel toasted with extra cream cheese and light red onion",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_bagel_with_on_the_side_request(self):
        """Bagel with cream cheese on the side."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Plain bagel toasted with cream cheese on the side",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_bagel_scooped_with_spread(self):
        """Scooped bagel with veggie cream cheese."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Everything bagel scooped and toasted with veggie cream cheese",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_bagel_with_double_spread(self):
        """Bagel with two types of cream cheese."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Everything bagel with scallion and plain cream cheese",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_bagel_not_toasted_explicit(self):
        """Explicit not toasted request."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Plain bagel, do NOT toast it, with butter",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_bagel_with_bacon_egg_cheese_added(self):
        """Plain bagel turned into BEC."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Everything bagel with bacon, egg, and cheese please",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_bagel_with_mixed_toppings_and_spread(self):
        """Bagel with both savory toppings and sweet spread."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Cinnamon raisin bagel toasted with butter and bacon",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_half_bagel_request(self):
        """Request for half a bagel."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Can I get half an everything bagel with cream cheese?",
            order
        )

        # Should either create item or explain they don't do halves
        assert result.message is not None, "Should have a response"

class TestComplexCoffeeOrders:
    """Complex coffee orders with multiple customizations."""

    def test_latte_with_multiple_syrups(self):
        """Latte with vanilla and caramel syrup."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Large iced latte with vanilla and caramel syrup",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_coffee_with_specific_milk_and_sweetener(self):
        """Coffee with oat milk and 2 Splenda."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Medium hot coffee with oat milk and 2 Splenda",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_decaf_iced_latte_extra_shot(self):
        """Decaf iced latte with an extra shot (paradox)."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Large decaf iced latte with an extra shot",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_cappuccino_extra_dry(self):
        """Extra dry cappuccino."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Small cappuccino, extra dry please",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_coffee_half_caf(self):
        """Half-caf coffee order."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Large half-caf latte with almond milk",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_iced_coffee_no_ice(self):
        """Iced coffee with no ice (paradox request)."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Large iced coffee, no ice",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_espresso_with_cream(self):
        """Espresso with a splash of cream."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Double espresso with a splash of cream",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_mocha_with_extra_chocolate(self):
        """Mocha is not on the menu - should suggest alternatives."""
        from orderbot.db import SessionLocal

        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        with SessionLocal() as db:
            result = sm.process(
                "Large iced mocha with extra chocolate",
                order,
                db_session=db,
            )

        # Mocha is not on the menu, so no item should be added
        items = result.order.items.get_active_items()
        assert len(items) == 0, "Mocha not on menu - should suggest alternatives, not add item"
        # Should suggest espresso-based alternatives
        assert "don't have" in result.message.lower() or "we have" in result.message.lower(), \
            f"Expected suggestion message, got: {result.message}"

    def test_coffee_specific_temperature(self):
        """Coffee at specific temperature."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Medium latte, not too hot please",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_americano_with_room(self):
        """Americano with room for cream."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Large hot americano with room",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestComplexSandwichOrders:
    """Complex sandwich and breakfast item orders."""

    def test_bec_with_multiple_modifications(self):
        """BEC with multiple add/remove modifications."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Classic BEC on everything, add avocado, no cheese",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_sandwich_with_substitution(self):
        """Sandwich with ingredient substitution."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Turkey sandwich, swap the mayo for mustard",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_egg_sandwich_specific_cook(self):
        """Egg sandwich with specific egg preparation."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Egg and cheese on plain, eggs scrambled well done",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_omelette_with_extra_fillings(self):
        """Omelette with multiple extra fillings."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Western omelette with extra peppers and onions, add mushrooms",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_sandwich_double_meat(self):
        """Sandwich with double meat."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "BLT with double bacon please",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_wrap_instead_of_bread(self):
        """Request for wrap instead of bread."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Can I get the turkey club as a wrap?",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_gluten_free_bread_request(self):
        """Request for gluten-free bread."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "BEC on gluten free bread if you have it",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_sandwich_cut_in_half(self):
        """Sandwich cut in half request."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Turkey sandwich on whole wheat, cut in half please",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestComplexBeverageOrders:
    """Complex non-coffee beverage orders."""

    def test_smoothie_with_additions(self):
        """Smoothie with protein and additions."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Berry smoothie with protein powder and extra banana",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_juice_fresh_squeezed(self):
        """Fresh squeezed juice request."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Fresh squeezed orange juice, large",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_tea_with_specific_temperature(self):
        """Tea with specific temperature."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Green tea, not too hot, with honey",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_hot_chocolate_extra_whip(self):
        """Hot chocolate with extra whipped cream."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Large hot chocolate with extra whipped cream and chocolate drizzle",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_chai_latte_dirty(self):
        """Dirty chai latte (with espresso shot)."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Large dirty chai latte with oat milk",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestSpecialInstructions:
    """Orders with special instructions and preferences."""

    def test_allergy_mention(self):
        """Order mentioning allergy."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Plain bagel with butter, I have a sesame allergy",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_dietary_restriction(self):
        """Order with dietary restriction mentioned."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "What do you have that's vegan?",
            order
        )

        # Should either list items or acknowledge query
        assert result.message is not None, "Should have a response"

    def test_order_for_later(self):
        """Order for specific time."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Everything bagel toasted with cream cheese, this is for pickup at 10am",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_rush_order(self):
        """Rush order request."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "I need a BEC on everything fast, I'm running late",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_separate_bag_request(self):
        """Request for items in separate bags."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Two everything bagels with cream cheese, can you put them in separate bags?",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"
