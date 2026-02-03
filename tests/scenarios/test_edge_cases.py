"""
Edge Case and Ambiguous Input Tests.

These tests focus on ambiguous language, edge cases, unusual phrasing,
and inputs that might be difficult to parse correctly.

Run with: pytest tests/scenarios/ -v
"""

import pytest
from orderbot.tasks.state_machine import OrderStateMachine
from orderbot.tasks.models import OrderTask
from orderbot.tasks.schemas import OrderPhase


class TestAmbiguousLanguage:
    """Tests for ambiguous or unclear customer language."""

    def test_regular_ambiguous(self):
        """'Regular' can mean regular size or regular coffee type."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("I'll have a regular", order)

        # Should ask for clarification or create item
        assert result.message is not None, "Should have a response"

    def test_the_usual(self):
        """'The usual' with no history."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Give me the usual", order)

        # Should ask what the usual is
        assert result.message is not None, "Should have a response"

    def test_same_thing(self):
        """'Same thing' as first request."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Same thing as always", order)

        assert result.message is not None, "Should have a response"

    def test_one_of_those(self):
        """Vague 'one of those' reference."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Can I get one of those breakfast sandwiches", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_something_light(self):
        """Vague 'something light' request."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("I want something light", order)

        assert result.message is not None, "Should have a response"

    def test_whatever_is_good(self):
        """'Whatever is good' request."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Whatever is good here", order)

        assert result.message is not None, "Should have a response"

    def test_surprise_me(self):
        """'Surprise me' request."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Surprise me", order)

        assert result.message is not None, "Should have a response"


class TestPartialOrders:
    """Tests for incomplete or partial order specifications."""

    def test_just_bagel_type(self):
        """Just bagel type, no toppings or spread."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Everything", order)

        # Should recognize as bagel type and ask follow-ups
        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_just_coffee(self):
        """Just 'coffee' with no specifications."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Coffee", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.order.phase == OrderPhase.CONFIGURING_ITEM.value, \
            "Should have item or be configuring"

    def test_just_size(self):
        """Just a size with no item."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Large", order)

        # Should ask what they want large
        assert result.message is not None, "Should have a response"

    def test_just_modifier(self):
        """Just a modifier with no base item."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("With cream cheese", order)

        # Should ask what they want cream cheese on
        assert result.message is not None, "Should have a response"


class TestSimilarItems:
    """Tests for items with similar names that could be confused."""

    def test_classic_bec_vs_classic_omelette(self):
        """Distinguish between Classic BEC and Classic Omelette."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("The classic", order)

        # Should either pick one or ask for clarification
        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_hot_coffee_vs_hot_chocolate(self):
        """Distinguish between hot coffee and hot chocolate."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Something hot", order)

        assert result.message is not None, "Should have a response"

    def test_plain_bagel_vs_plain_cream_cheese(self):
        """Distinguish plain bagel from plain cream cheese."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Plain please", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_iced_coffee_vs_iced_tea(self):
        """Distinguish iced coffee from iced tea."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Something iced", order)

        assert result.message is not None, "Should have a response"


class TestUnusualPhrasing:
    """Tests for unusual or non-standard phrasing."""

    def test_backwards_order(self):
        """Order with items mentioned in unusual order."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Toasted, with cream cheese, an everything bagel", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_repeated_words(self):
        """Order with repeated or stuttered words."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("I want I want an everything bagel", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_filler_words(self):
        """Order with lots of filler words."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Um so like I'll have like an everything bagel like toasted I guess",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_run_on_sentence(self):
        """Long run-on sentence order."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "yeah so I need a bagel the everything one and I want it toasted and "
            "cream cheese the scallion one and a coffee large please",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_formal_language(self):
        """Very formal order language."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Good morning, I would like to request one everything bagel, toasted, "
            "accompanied by scallion cream cheese, if you please",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_very_brief(self):
        """Very brief terse order."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("BEC. Everything. Toasted.", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestNegativeLanguage:
    """Tests for negative phrasing and requests."""

    def test_dont_want(self):
        """'I don't want' phrasing."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Everything bagel, I don't want it toasted",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_nothing_on_it(self):
        """'Nothing on it' request."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Plain bagel toasted, nothing on it", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_hold_everything(self):
        """'Hold everything' on a signature item."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("BLT hold everything except the bread", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_skip_the(self):
        """'Skip the' phrasing."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Lox bagel, skip the capers", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_leave_off(self):
        """'Leave off' phrasing."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("BEC, leave off the egg", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestTyposAndMisspellings:
    """Tests for common typos and misspellings."""

    def test_bagel_misspelled(self):
        """Misspelled bagel."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Evrything bagle with cream cheese", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should handle misspelling"

    def test_latte_misspelled(self):
        """Misspelled latte."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Large lattee please", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should handle misspelling"

    def test_cappuccino_misspelled(self):
        """Misspelled cappuccino."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Capuccino medium", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should handle misspelling"

    def test_scallion_misspelled(self):
        """Misspelled scallion."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Everything bagel with scalion cream cheese", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should handle misspelling"


class TestNumbers:
    """Tests for various number formats."""

    def test_spelled_out_numbers(self):
        """Numbers spelled out."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Three everything bagels please", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_numeric_digits(self):
        """Numeric digits."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("4 plain bagels", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_mixed_numbers(self):
        """Mixed number formats."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("Two bagels and 3 coffees", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestQuestions:
    """Tests for questions mixed with orders."""

    def test_question_then_order(self):
        """Question followed by order."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Do you have sesame bagels? I'll take one if you do.",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"

    def test_conditional_order(self):
        """Conditional order."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "Everything bagel if you have it, otherwise plain",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_price_inquiry_with_order(self):
        """Price inquiry with order intent."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process(
            "How much is an everything bagel with lox? I'll have one.",
            order
        )

        items = result.order.items.get_active_items()
        assert len(items) >= 1 or result.message is not None, "Should have item or response"


class TestContextSwitches:
    """Tests for sudden context switches."""

    def test_mid_order_question(self):
        """Question in the middle of ordering."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Everything bagel", order)
        result2 = sm.process("wait, do you have gluten free bagels?", result1.order)

        assert result2.message is not None, "Should have a response"

    def test_change_topic_completely(self):
        """Sudden topic change."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Plain bagel toasted", order)
        result2 = sm.process("What time do you close?", result1.order)

        assert result2.message is not None, "Should have a response"

    def test_return_to_order_after_question(self):
        """Return to ordering after asking question."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("What bagels do you have?", order)
        result2 = sm.process("I'll have an everything toasted with cream cheese", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"
