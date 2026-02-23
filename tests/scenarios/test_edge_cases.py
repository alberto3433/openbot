"""
Edge Case and Ambiguous Input Tests.

These tests focus on ambiguous language, edge cases, unusual phrasing,
and inputs that might be difficult to parse correctly.

Run with: pytest tests/scenarios/ -v
"""

import pytest
from orderbot.tasks.schemas import OrderPhase


class TestAmbiguousLanguage:
    """Tests for ambiguous or unclear customer language."""

    def test_regular_ambiguous(self, order_and_sm):
        """'Regular' can mean regular size or regular coffee type."""
        order, sm = order_and_sm

        result = sm.process("I'll have a regular", order)

        # Should ask for clarification or create item
        assert result.message is not None, "Should have a response"

    def test_the_usual(self, order_and_sm):
        """'The usual' with no history."""
        order, sm = order_and_sm

        result = sm.process("Give me the usual", order)

        # Should ask what the usual is
        assert result.message is not None, "Should have a response"

    def test_same_thing(self, order_and_sm):
        """'Same thing' as first request."""
        order, sm = order_and_sm

        result = sm.process("Same thing as always", order)

        assert result.message is not None, "Should have a response"

    def test_one_of_those(self, order_and_sm):
        """Vague 'one of those' reference."""
        order, sm = order_and_sm

        result = sm.process("Can I get one of those breakfast sandwiches", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_something_light(self, order_and_sm):
        """Vague 'something light' request."""
        order, sm = order_and_sm

        result = sm.process("I want something light", order)

        assert result.message is not None, "Should have a response"

    def test_whatever_is_good(self, order_and_sm):
        """'Whatever is good' request."""
        order, sm = order_and_sm

        result = sm.process("Whatever is good here", order)

        assert result.message is not None, "Should have a response"

    def test_surprise_me(self, order_and_sm):
        """'Surprise me' request."""
        order, sm = order_and_sm

        result = sm.process("Surprise me", order)

        assert result.message is not None, "Should have a response"


class TestPartialOrders:
    """Tests for incomplete or partial order specifications."""

    def test_just_bagel_type(self, order_and_sm):
        """Just bagel type, no toppings or spread."""
        order, sm = order_and_sm

        result = sm.process("Everything", order)

        # Should recognize as bagel type and ask follow-ups
        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_just_coffee(self, order_and_sm):
        """Just 'coffee' with no specifications."""
        order, sm = order_and_sm

        result = sm.process("Coffee", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.order.phase == OrderPhase.CONFIGURING_ITEM.value, \
            "Should have item or be configuring"

    def test_just_size(self, order_and_sm):
        """Just a size with no item."""
        order, sm = order_and_sm

        result = sm.process("Large", order)

        # Should ask what they want large
        assert result.message is not None, "Should have a response"

    def test_just_modifier(self, order_and_sm):
        """Just a modifier with no base item."""
        order, sm = order_and_sm

        result = sm.process("With cream cheese", order)

        # Should ask what they want cream cheese on
        assert result.message is not None, "Should have a response"


class TestSimilarItems:
    """Tests for items with similar names that could be confused."""

    def test_classic_bec_vs_classic_omelette(self, order_and_sm):
        """Distinguish between Classic BEC and Classic Omelette."""
        order, sm = order_and_sm

        result = sm.process("The classic", order)

        # Should either pick one or ask for clarification
        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_hot_coffee_vs_hot_chocolate(self, order_and_sm):
        """Distinguish between hot coffee and hot chocolate."""
        order, sm = order_and_sm

        result = sm.process("Something hot", order)

        assert result.message is not None, "Should have a response"

    def test_plain_bagel_vs_plain_cream_cheese(self, order_and_sm):
        """Distinguish plain bagel from plain cream cheese."""
        order, sm = order_and_sm

        result = sm.process("Plain please", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_iced_coffee_vs_iced_tea(self, order_and_sm):
        """Distinguish iced coffee from iced tea."""
        order, sm = order_and_sm

        result = sm.process("Something iced", order)

        assert result.message is not None, "Should have a response"


class TestUnusualPhrasing:
    """Tests for unusual or non-standard phrasing."""

    def test_backwards_order(self, order_and_sm):
        """Order with items mentioned in unusual order."""
        order, sm = order_and_sm

        result = sm.process("Toasted, with cream cheese, an everything bagel", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_repeated_words(self, order_and_sm):
        """Order with repeated or stuttered words."""
        order, sm = order_and_sm

        result = sm.process("I want I want an everything bagel", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_filler_words(self, order_and_sm):
        """Order with lots of filler words."""
        order, sm = order_and_sm

        result = sm.process(
            "Um so like I'll have like an everything bagel like toasted I guess",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_run_on_sentence(self, order_and_sm):
        """Long run-on sentence order."""
        order, sm = order_and_sm

        result = sm.process(
            "yeah so I need a bagel the everything one and I want it toasted and "
            "cream cheese the scallion one and a coffee large please",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_formal_language(self, order_and_sm):
        """Very formal order language."""
        order, sm = order_and_sm

        result = sm.process(
            "Good morning, I would like to request one everything bagel, toasted, "
            "accompanied by scallion cream cheese, if you please",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_very_brief(self, order_and_sm):
        """Very brief terse order."""
        order, sm = order_and_sm

        result = sm.process("BEC. Everything. Toasted.", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestNegativeLanguage:
    """Tests for negative phrasing and requests."""

    def test_dont_want(self, order_and_sm):
        """'I don't want' phrasing."""
        order, sm = order_and_sm

        result = sm.process(
            "Everything bagel, I don't want it toasted",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_nothing_on_it(self, order_and_sm):
        """'Nothing on it' request."""
        order, sm = order_and_sm

        result = sm.process("Plain bagel toasted, nothing on it", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_hold_everything(self, order_and_sm):
        """'Hold everything' on a signature item."""
        order, sm = order_and_sm

        result = sm.process("BLT hold everything except the bread", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_skip_the(self, order_and_sm):
        """'Skip the' phrasing."""
        order, sm = order_and_sm

        result = sm.process("Lox bagel, skip the capers", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_leave_off(self, order_and_sm):
        """'Leave off' phrasing."""
        order, sm = order_and_sm

        result = sm.process("BEC, leave off the egg", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestTyposAndMisspellings:
    """Tests for common typos and misspellings."""

    def test_bagel_misspelled(self, order_and_sm):
        """Misspelled bagel."""
        order, sm = order_and_sm

        result = sm.process("Evrything bagle with cream cheese", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should handle misspelling"

    def test_latte_misspelled(self, order_and_sm):
        """Misspelled latte."""
        order, sm = order_and_sm

        result = sm.process("Large lattee please", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should handle misspelling"

    def test_cappuccino_misspelled(self, order_and_sm):
        """Misspelled cappuccino."""
        order, sm = order_and_sm

        result = sm.process("Capuccino medium", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should handle misspelling"

    def test_scallion_misspelled(self, order_and_sm):
        """Misspelled scallion."""
        order, sm = order_and_sm

        result = sm.process("Everything bagel with scalion cream cheese", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should handle misspelling"


class TestNumbers:
    """Tests for various number formats."""

    def test_spelled_out_numbers(self, order_and_sm):
        """Numbers spelled out."""
        order, sm = order_and_sm

        result = sm.process("Three everything bagels please", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_numeric_digits(self, order_and_sm):
        """Numeric digits."""
        order, sm = order_and_sm

        result = sm.process("4 plain bagels", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_mixed_numbers(self, order_and_sm):
        """Mixed number formats."""
        order, sm = order_and_sm

        result = sm.process("Two bagels and 3 coffees", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestQuestions:
    """Tests for questions mixed with orders."""

    def test_question_then_order(self, order_and_sm):
        """Question followed by order."""
        order, sm = order_and_sm

        result = sm.process(
            "Do you have sesame bagels? I'll take one if you do.",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_conditional_order(self, order_and_sm):
        """Conditional order."""
        order, sm = order_and_sm

        result = sm.process(
            "Everything bagel if you have it, otherwise plain",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_price_inquiry_with_order(self, order_and_sm):
        """Price inquiry with order intent."""
        order, sm = order_and_sm

        result = sm.process(
            "How much is an everything bagel with lox? I'll have one.",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"


class TestContextSwitches:
    """Tests for sudden context switches."""

    def test_mid_order_question(self, order_and_sm):
        """Question in the middle of ordering."""
        order, sm = order_and_sm

        result1 = sm.process("Everything bagel", order)
        result2 = sm.process("wait, do you have gluten free bagels?", result1.order)

        assert result2.message is not None, "Should have a response"

    def test_change_topic_completely(self, order_and_sm):
        """Sudden topic change."""
        order, sm = order_and_sm

        result1 = sm.process("Plain bagel toasted", order)
        result2 = sm.process("What time do you close?", result1.order)

        assert result2.message is not None, "Should have a response"

    def test_return_to_order_after_question(self, order_and_sm):
        """Return to ordering after asking question."""
        order, sm = order_and_sm

        result1 = sm.process("What bagels do you have?", order)
        result2 = sm.process("I'll have an everything bagel toasted with cream cheese", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"
