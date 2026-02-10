"""
Natural Language Variation Tests.

These tests focus on different ways customers naturally express the same
order, including slang, abbreviations, and regional variations.

Run with: pytest tests/scenarios/ -v
"""

import pytest
from orderbot.tasks.state_machine import OrderStateMachine
from orderbot.tasks.models import OrderTask
from orderbot.tasks.schemas import OrderPhase


class TestPoliteVariations:
    """Different levels of politeness in ordering."""

    def test_very_polite_order(self):
        """Very polite ordering style."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Excuse me, could I please have an everything bagel toasted "
            "with cream cheese if it's not too much trouble?",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_casual_order(self):
        """Very casual ordering style."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("yo lemme get an everything bagel with cream cheese", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_terse_order(self):
        """Very brief terse order."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("everything bagel toasted cream cheese", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_demanding_order(self):
        """Demanding style order."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "I need an everything bagel toasted with scallion right now",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestSlangAndAbbreviations:
    """Tests for slang and common abbreviations."""

    def test_bec_abbreviation(self):
        """BEC abbreviation."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("BEC on everything", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_sec_abbreviation(self):
        """SEC (sausage egg cheese) abbreviation."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("SEC on plain", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_schmear_slang(self):
        """Schmear for cream cheese."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("everything bagel with a schmear", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_works_slang(self):
        """'The works' for all toppings."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("lox bagel with the works", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_cuppa_joe(self):
        """Cup of joe for coffee."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("large cuppa joe", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"


class TestIntentPhrasing:
    """Different ways to express ordering intent."""

    def test_can_i_get(self):
        """'Can I get' phrasing."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Can I get an everything bagel toasted?", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_could_i_have(self):
        """'Could I have' phrasing."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Could I have a large latte please?", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_id_like(self):
        """'I'd like' phrasing."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("I'd like a sesame bagel with butter", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_ill_have(self):
        """'I'll have' phrasing."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("I'll have the BEC on everything", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_give_me(self):
        """'Give me' phrasing."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Give me a plain bagel with cream cheese", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_let_me_get(self):
        """'Let me get' phrasing."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Let me get a medium hot coffee", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_hook_me_up(self):
        """'Hook me up' phrasing."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("hook me up with a large iced latte", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_i_need(self):
        """'I need' phrasing."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("I need a coffee and a bagel", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_i_want(self):
        """'I want' phrasing."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("I want an everything bagel", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_i_would_like_chai_tea(self):
        """'I would like' phrasing adds chai tea to cart."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("I would like a chai tea", order)

        # Chai tea is on the menu, should be added to cart
        items = result.order.items.get_active_items()
        assert len(items) >= 1, f"Should have added chai tea, got message: {result.message}"
        # Verify it's a chai item
        item_names = [item.menu_item_name.lower() for item in items if item.menu_item_name]
        assert any("chai" in name for name in item_names), \
            f"Expected chai tea in cart, got: {item_names}"


class TestAffirmativeResponses:
    """Different ways to say yes."""

    def test_yes_response(self):
        """Simple yes."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Plain bagel", order)
        result2 = sm.process("yes", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_yeah_response(self):
        """Yeah."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Everything bagel", order)
        result2 = sm.process("yeah", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_yep_response(self):
        """Yep."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Sesame bagel", order)
        result2 = sm.process("yep", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_sure_response(self):
        """Sure."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Plain bagel", order)
        result2 = sm.process("sure", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_please_response(self):
        """Please as affirmative."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Everything bagel", order)
        result2 = sm.process("please", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_absolutely_response(self):
        """Absolutely."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Plain bagel", order)
        result2 = sm.process("absolutely", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_for_sure_response(self):
        """For sure."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Sesame bagel", order)
        result2 = sm.process("for sure", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestNegativeResponses:
    """Different ways to say no."""

    def test_no_response(self):
        """Simple no."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Plain bagel", order)
        result2 = sm.process("no", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_nah_response(self):
        """Nah."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Everything bagel", order)
        result2 = sm.process("nah", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_nope_response(self):
        """Nope."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Sesame bagel", order)
        result2 = sm.process("nope", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_no_thanks_response(self):
        """No thanks."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Plain bagel", order)
        result2 = sm.process("no thanks", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_im_good_response(self):
        """I'm good."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Everything bagel", order)
        result2 = sm.process("I'm good", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_pass_response(self):
        """Pass."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Plain bagel", order)
        result2 = sm.process("pass", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestSizeVariations:
    """Different ways to express sizes."""

    def test_small_coffee(self):
        """Small coffee."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("small coffee", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_medium_coffee(self):
        """Medium coffee."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("medium latte", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_large_coffee(self):
        """Large coffee."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("large cappuccino", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_tall_coffee(self):
        """Tall (Starbucks size) coffee."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("tall latte", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_grande_coffee(self):
        """Grande (Starbucks size) coffee."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("grande americano", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_venti_coffee(self):
        """Venti (Starbucks size) coffee."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("venti coffee", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_regular_size(self):
        """Regular size."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("regular coffee", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"


class TestTemperatureVariations:
    """Different ways to express hot/iced."""

    def test_hot_explicit(self):
        """Explicitly hot."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("hot latte please", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_iced_explicit(self):
        """Explicitly iced."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("iced americano", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_cold_for_iced(self):
        """Cold instead of iced."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("cold coffee", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_warm_for_hot(self):
        """Warm instead of hot."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("warm latte", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_on_ice(self):
        """'On ice' for iced."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("latte on ice", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_over_ice(self):
        """'Over ice' for iced."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("coffee over ice", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"
