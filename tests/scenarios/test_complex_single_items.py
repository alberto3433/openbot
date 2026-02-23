"""
Complex Single-Item Order Tests.

These tests focus on single items with complex modifier combinations,
special instructions, and edge cases that are harder to parse.

Run with: pytest tests/scenarios/ -v
"""

import pytest


class TestComplexBagelOrders:
    """Complex bagel orders with multiple modifiers and special requests."""

    def test_bagel_with_five_modifiers(self, order_and_sm):
        """Everything bagel with lox, capers, red onion, tomato, and cream cheese."""
        order, sm = order_and_sm

        result = sm.process(
            "Everything bagel with lox, capers, red onion, tomato, and cream cheese please",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_bagel_with_extra_and_light_modifiers(self, order_and_sm):
        """Bagel with extra cream cheese and light onion."""
        order, sm = order_and_sm

        result = sm.process(
            "Sesame bagel toasted with extra cream cheese and light red onion",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_bagel_with_on_the_side_request(self, order_and_sm):
        """Bagel with cream cheese on the side."""
        order, sm = order_and_sm

        result = sm.process(
            "Plain bagel toasted with cream cheese on the side",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_bagel_scooped_with_spread(self, order_and_sm):
        """Scooped bagel with veggie cream cheese."""
        order, sm = order_and_sm

        result = sm.process(
            "Everything bagel scooped and toasted with veggie cream cheese",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_bagel_not_toasted_explicit(self, order_and_sm):
        """Explicit not toasted request."""
        order, sm = order_and_sm

        result = sm.process(
            "Plain bagel, do NOT toast it, with butter",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_bagel_with_bacon_egg_cheese_added(self, order_and_sm):
        """Plain bagel turned into BEC."""
        order, sm = order_and_sm

        result = sm.process(
            "Everything bagel with bacon, egg, and cheese please",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_bagel_with_mixed_toppings_and_spread(self, order_and_sm):
        """Bagel with both savory toppings and sweet spread."""
        order, sm = order_and_sm

        result = sm.process(
            "Cinnamon raisin bagel toasted with butter and bacon",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_half_bagel_request(self, order_and_sm):
        """Request for half a bagel."""
        order, sm = order_and_sm

        result = sm.process(
            "Can I get half an everything bagel with cream cheese?",
            order
        )

        # Should either create item or explain they don't do halves
        assert result.message is not None, "Should have a response"

class TestComplexCoffeeOrders:
    """Complex coffee orders with multiple customizations."""

    def test_latte_with_multiple_syrups(self, order_and_sm):
        """Latte with vanilla and caramel syrup."""
        order, sm = order_and_sm

        result = sm.process(
            "Large iced latte with vanilla and caramel syrup",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_coffee_with_specific_milk_and_sweetener(self, order_and_sm):
        """Coffee with oat milk and 2 Splenda."""
        order, sm = order_and_sm

        result = sm.process(
            "Medium hot coffee with oat milk and 2 Splenda",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_decaf_iced_latte_extra_shot(self, order_and_sm):
        """Decaf iced latte with an extra shot (paradox)."""
        order, sm = order_and_sm

        result = sm.process(
            "Large decaf iced latte with an extra shot",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_cappuccino_extra_dry(self, order_and_sm):
        """Extra dry cappuccino."""
        order, sm = order_and_sm

        result = sm.process(
            "Small cappuccino, extra dry please",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_coffee_half_caf(self, order_and_sm):
        """Half-caf coffee order."""
        order, sm = order_and_sm

        result = sm.process(
            "Large half-caf latte with almond milk",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_iced_coffee_no_ice(self, order_and_sm):
        """Iced coffee with no ice (paradox request)."""
        order, sm = order_and_sm

        result = sm.process(
            "Large iced coffee, no ice",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_espresso_with_cream(self, order_and_sm):
        """Espresso with a splash of cream."""
        order, sm = order_and_sm

        result = sm.process(
            "Double espresso with a splash of cream",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_mocha_with_extra_chocolate(self, order_and_sm):
        """Mocha is not on the menu - should suggest alternatives."""
        from orderbot.db import SessionLocal

        order, sm = order_and_sm

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

    def test_coffee_specific_temperature(self, order_and_sm):
        """Coffee at specific temperature."""
        order, sm = order_and_sm

        result = sm.process(
            "Medium latte, not too hot please",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_americano_with_room(self, order_and_sm):
        """Americano with room for cream."""
        order, sm = order_and_sm

        result = sm.process(
            "Large hot americano with room",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestComplexSandwichOrders:
    """Complex sandwich and breakfast item orders."""

    def test_bec_with_multiple_modifications(self, order_and_sm):
        """BEC with multiple add/remove modifications."""
        order, sm = order_and_sm

        result = sm.process(
            "Classic BEC on everything, add avocado, no cheese",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_sandwich_with_substitution(self, order_and_sm):
        """Sandwich with ingredient substitution."""
        order, sm = order_and_sm

        result = sm.process(
            "Turkey sandwich, swap the mayo for mustard",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_egg_sandwich_specific_cook(self, order_and_sm):
        """Egg sandwich with specific egg preparation."""
        order, sm = order_and_sm

        result = sm.process(
            "Egg and cheese on plain, eggs scrambled well done",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_omelette_with_extra_fillings(self, order_and_sm):
        """Omelette with multiple extra fillings."""
        order, sm = order_and_sm

        result = sm.process(
            "Western omelette with extra peppers and onions, add mushrooms",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_sandwich_double_meat(self, order_and_sm):
        """Sandwich with double meat."""
        order, sm = order_and_sm

        result = sm.process(
            "BLT with double bacon please",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_wrap_instead_of_bread(self, order_and_sm):
        """Request for wrap instead of bread."""
        order, sm = order_and_sm

        result = sm.process(
            "Can I get the turkey club as a wrap?",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_gluten_free_bread_request(self, order_and_sm):
        """Request for gluten-free bread."""
        order, sm = order_and_sm

        result = sm.process(
            "BEC on gluten free bread if you have it",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_egg_sandwich_with_plain_bagel_skips_bread_question(self, order_and_sm):
        """
        When user specifies bread type that matches the default, should NOT re-ask for bread.

        Bug fix test: "ham egg and cheese on a plain bagel" was asking "What kind of bread?"
        even though plain bagel was already specified and is the default bread option.
        """
        order, sm = order_and_sm

        result = sm.process(
            "ham egg and cheese on a plain bagel",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

        # The item should have bread set
        item = items[0]
        bread_selections = [s for s in item.selections if s.get("category") == "bread"]
        assert len(bread_selections) == 1, "Should have exactly one bread selection"

        # Should be marked as confirmed since user explicitly chose it
        bread_sel = bread_selections[0]
        assert bread_sel.get("_confirmed") is True, (
            "Bread should be marked as confirmed (_confirmed=True) since user explicitly chose it"
        )

        # Response should NOT ask about bread
        message_lower = result.message.lower() if result.message else ""
        assert "what kind of bread" not in message_lower, (
            f"Should not ask about bread type when already specified. Got: {result.message}"
        )
        assert "what type of bread" not in message_lower, (
            f"Should not ask about bread type when already specified. Got: {result.message}"
        )

    def test_sandwich_cut_in_half(self, order_and_sm):
        """Sandwich cut in half request."""
        order, sm = order_and_sm

        result = sm.process(
            "Turkey sandwich on whole wheat, cut in half please",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestComplexBeverageOrders:
    """Complex non-coffee beverage orders."""

    def test_smoothie_with_additions(self, order_and_sm):
        """Smoothie with protein and additions."""
        order, sm = order_and_sm

        result = sm.process(
            "Berry smoothie with protein powder and extra banana",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_juice_fresh_squeezed(self, order_and_sm):
        """Fresh squeezed juice request."""
        order, sm = order_and_sm

        result = sm.process(
            "Fresh squeezed orange juice, large",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_tea_with_specific_temperature(self, order_and_sm):
        """Tea with specific temperature."""
        order, sm = order_and_sm

        result = sm.process(
            "Green tea, not too hot, with honey",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_hot_chocolate_extra_whip(self, order_and_sm):
        """Hot chocolate with extra whipped cream."""
        order, sm = order_and_sm

        result = sm.process(
            "Large hot chocolate with extra whipped cream and chocolate drizzle",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_chai_latte_dirty(self, order_and_sm):
        """Dirty chai latte (with espresso shot)."""
        order, sm = order_and_sm

        result = sm.process(
            "Large dirty chai latte with oat milk",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestSpecialInstructions:
    """Orders with special instructions and preferences."""

    def test_allergy_mention(self, order_and_sm):
        """Order mentioning allergy."""
        order, sm = order_and_sm

        result = sm.process(
            "Plain bagel with butter, I have a sesame allergy",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_dietary_restriction(self, order_and_sm):
        """Order with dietary restriction mentioned."""
        order, sm = order_and_sm

        result = sm.process(
            "What do you have that's vegan?",
            order
        )

        # Should either list items or acknowledge query
        assert result.message is not None, "Should have a response"

    def test_order_for_later(self, order_and_sm):
        """Order for specific time."""
        order, sm = order_and_sm

        result = sm.process(
            "Everything bagel toasted with cream cheese, this is for pickup at 10am",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_rush_order(self, order_and_sm):
        """Rush order request."""
        order, sm = order_and_sm

        result = sm.process(
            "I need a BEC on everything fast, I'm running late",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_separate_bag_request(self, order_and_sm):
        """Request for items in separate bags."""
        order, sm = order_and_sm

        result = sm.process(
            "Two everything bagels with cream cheese, can you put them in separate bags?",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"
