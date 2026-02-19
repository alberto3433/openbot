"""
Resiliency Tests: Language variation (NL variation, affirmatives, abbreviations, corrections).

Consolidated from batches: 3, 9, 10, 12, 14, 15.
"""

import pytest

from orderbot.tasks.models import OrderTask
from orderbot.tasks.state_machine import OrderStateMachine, OrderPhase
from tests.helpers import BagelItemTask
from tests.helpers import BagelItemTask, CoffeeItemTask

# =============================================================================
# From test_resiliency_batch3.py
# =============================================================================

class TestNaturalLanguageVariation:
    """Batch 3: Natural Language Variation."""

    def test_throw_in_a_muffin(self):
        """
        Test: User uses informal "throw in" phrasing.

        Scenario:
        - User says: "throw in a blueberry muffin"
        - Expected: System adds a blueberry muffin
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("throw in a blueberry muffin", order)

        # Should have a response
        assert result.message is not None

        # Check the message mentions muffin or asks which one
        message_lower = result.message.lower()
        items = result.order.items.get_active_items()

        # Should either add the muffin or ask for clarification
        has_item = len(items) > 0
        mentions_muffin = "muffin" in message_lower or "blueberry" in message_lower

        assert has_item or mentions_muffin, \
            f"Should add muffin or reference it. Message: {result.message}"

    def test_typo_expresso(self):
        """
        Test: User makes common typo "expresso" instead of "espresso".

        Scenario:
        - User says: "expresso please"
        - Expected: System understands this as espresso
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("expresso please", order)

        # Should have a response
        assert result.message is not None

        # Should have added espresso (as coffee)
        coffees = [i for i in result.order.items.items if i.has_attribute('size')]

        if coffees:
            coffee = coffees[0]
            # Should be espresso
            assert coffee.menu_item_name.lower() == "espresso", \
                f"Should be espresso, got: {coffee.menu_item_name}"
        else:
            # Or should be asking about espresso
            assert "espresso" in result.message.lower() or "expresso" in result.message.lower(), \
                f"Should reference espresso. Message: {result.message}"

# =============================================================================
# From test_resiliency_batch9.py
# =============================================================================

class TestAffirmativeNegativeResponses:
    """Batch 9: Affirmative/Negative Responses."""

    def test_yes_response_to_toasted_question(self):
        """
        Test: User says "yes" when asked if they want it toasted.

        Scenario:
        - User has bagel being configured (toasted=None)
        - User says: "yes"
        - Expected: Bagel gets toasted=True
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="plain", toasted=None)
        bagel.mark_in_progress()  # Mark as current item
        order.items.add_item(bagel)
        # Set up pending state for toasted question
        order.pending_item_ids = [bagel.id]
        order.pending_field = "bagel:toasted"

        sm = OrderStateMachine()
        result = sm.process("yes", order)

        assert result.message is not None

        # Should set toasted to True
        bagels = [i for i in result.order.items.items if i.has_attribute('bread')]
        assert bagels[0]["toasted"] is True, "Should be toasted"

    def test_yeah_sure_response(self):
        """
        Test: User says "yeah sure" as affirmative.

        Scenario:
        - User has bagel being configured
        - User says: "yeah sure"
        - Expected: Treated as affirmative
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="everything", toasted=None)
        bagel.mark_in_progress()  # Mark as current item
        order.items.add_item(bagel)
        # Set up pending state for toasted question
        order.pending_item_ids = [bagel.id]
        order.pending_field = "bagel:toasted"

        sm = OrderStateMachine()
        result = sm.process("yeah sure", order)

        assert result.message is not None
        # Should set toasted to True and continue
        bagels = [i for i in result.order.items.items if i.has_attribute('bread')]
        assert bagels[0]["toasted"] is True, "Should be toasted"

    def test_no_response_to_anything_else(self):
        """
        Test: User says "no" when asked if they want anything else.

        Scenario:
        - User has completed items
        - User says: "no"
        - Expected: Proceeds to checkout, doesn't add items
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="sesame", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("no", order)

        assert result.message is not None

        # Should not add new items
        bagels = [i for i in result.order.items.items if i.has_attribute('bread')]
        assert len(bagels) == 1, f"Should still have 1 bagel, got {len(bagels)}"

# =============================================================================
# From test_resiliency_batch10.py
# =============================================================================

class TestGratitudeSocialResponses:
    """Batch 10: Gratitude & Social Responses."""

    def test_thank_you_response(self):
        """
        Test: User says "thank you" after ordering.

        Scenario:
        - User has items in order
        - User says: "thank you"
        - Expected: Polite acknowledgment, doesn't add items
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("thank you", order)

        assert result.message is not None
        # Should acknowledge politely
        message_lower = result.message.lower()
        is_polite = any(word in message_lower for word in [
            "welcome", "thank", "pleasure", "glad", "help", "else", "anything"
        ])
        assert is_polite, f"Should respond politely. Message: {result.message}"

    def test_thanks_response(self):
        """
        Test: User says "thanks" shorthand.

        Scenario:
        - User says: "thanks"
        - Expected: Polite response
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="everything", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("thanks", order)

        assert result.message is not None
        # Should not error or misinterpret
        bagels = [i for i in result.order.items.items if i.has_attribute('bread')]
        assert len(bagels) == 1, "Should not add extra items"

    def test_sorry_response(self):
        """
        Test: User says "sorry" (maybe after confusion).

        Scenario:
        - User says: "sorry, I meant plain bagel"
        - Expected: System handles gracefully, possibly interprets the order
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("sorry, I meant plain bagel", order)

        assert result.message is not None
        # Should either add the bagel or ask for clarification
        bagels = [i for i in result.order.items.items if i.has_attribute('bread')]
        has_bagel = len(bagels) >= 1
        mentions_bagel = "bagel" in result.message.lower()

        assert has_bagel or mentions_bagel, \
            f"Should handle the bagel order. Message: {result.message}"

# =============================================================================
# From test_resiliency_batch12.py
# =============================================================================

class TestAbbreviationsShorthand:
    """Batch 12: Abbreviations & Shorthand."""

    def test_bec_abbreviation(self):
        """
        Test: User says "BEC" for bacon egg cheese.

        Scenario:
        - User says: "I'll have a BEC"
        - Expected: System recognizes as bacon egg and cheese
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("I'll have a BEC", order)

        assert result.message is not None
        # Should recognize BEC
        items = result.order.items.get_active_items()
        message_lower = result.message.lower()

        has_item = len(items) >= 1
        mentions_bec = any(word in message_lower for word in [
            "bacon", "egg", "cheese", "bec", "classic"
        ])

        assert has_item or mentions_bec, \
            f"Should recognize BEC. Message: {result.message}"

    # NOTE: test_oj_abbreviation removed - "OJ" is ambiguous (matches Fresh OJ,
    # Tropicana OJ, etc.) so it triggers disambiguation rather than direct recognition

# =============================================================================
# From test_resiliency_batch14.py
# =============================================================================

class TestPronounContextReferences:
    """Batch 14: Pronoun/Context References."""

    def test_same_thing(self):
        """
        Test: User says "same thing" to duplicate last item.

        Scenario:
        - User has: 1 plain bagel
        - User says: "same thing"
        - Expected: Another plain bagel added
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("same thing", order)

        assert result.message is not None
        bagels = [i for i in result.order.items.items if i.has_attribute('bread')]
        total_qty = sum(b.quantity for b in bagels)

        # Should have 2 bagels or acknowledge the request
        assert total_qty >= 2 or "same" in result.message.lower(), \
            f"Should duplicate. Qty={total_qty}, Message: {result.message}"

    def test_another_one_of_those(self):
        """
        Test: User says "another one of those".

        Scenario:
        - User has: coffee
        - User says: "another one of those"
        - Expected: Another coffee added
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        coffee = CoffeeItemTask(drink_type="latte", size="large", iced=True)
        coffee.mark_complete()
        order.items.add_item(coffee)

        sm = OrderStateMachine()
        result = sm.process("another one of those", order)

        assert result.message is not None
        coffees = [i for i in result.order.items.items if i.has_attribute('size')]
        total_qty = sum(c.quantity for c in coffees)

        # Should have 2 coffees
        assert total_qty >= 2, f"Should have 2 coffees. Qty={total_qty}"

# =============================================================================
# From test_resiliency_batch15.py
# =============================================================================

class TestCorrectionsAfterMisunderstanding:
    """Batch 15: Corrections After Misunderstanding."""

    def test_no_i_said_plain(self):
        """
        Test: User corrects "no, I said plain".

        Scenario:
        - User has: poppy bagel (wrong)
        - User says: "no, I said plain"
        - Expected: Changes to plain bagel
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="poppy", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("no, I said plain", order)

        assert result.message is not None
        bagels = [i for i in result.order.items.items if i.has_attribute('bread')]

        # Should have plain bagel or acknowledge correction
        if bagels:
            has_plain = any(b["bread"] == "plain" for b in bagels)
            assert has_plain or "plain" in result.message.lower(), \
                f"Should correct to plain. Types: {[b['bread'] for b in bagels]}"

    def test_i_meant_the_small_one(self):
        """
        Test: User says "I meant the small one".

        Scenario:
        - User has: large coffee
        - User says: "I meant the small one"
        - Expected: Changes to small
        """
        # CoffeeItemTask imported from test_helpers at top of file

        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        coffee = CoffeeItemTask(drink_type="latte", size="large", iced=False)
        coffee.mark_complete()
        order.items.add_item(coffee)

        sm = OrderStateMachine()
        result = sm.process("I meant the small one", order)

        assert result.message is not None
        coffees = [i for i in result.order.items.items if i.has_attribute('size')]

        # Should change to small or acknowledge
        if coffees:
            has_small = any(c["size"] == "small" for c in coffees)
            assert has_small or "small" in result.message.lower(), \
                f"Should change to small. Sizes: {[c['size'] for c in coffees]}"

    def test_thats_not_what_i_ordered(self):
        """
        Test: User says "that's not what I ordered".

        Scenario:
        - User has items
        - User says: "that's not what I ordered"
        - Expected: System asks for clarification or offers to fix
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        bagel = BagelItemTask(bagel_type="sesame", toasted=True)
        bagel.mark_complete()
        order.items.add_item(bagel)

        sm = OrderStateMachine()
        result = sm.process("that's not what I ordered", order)

        assert result.message is not None
        # Should acknowledge the concern
        message_lower = result.message.lower()
        responds = any(word in message_lower for word in [
            "sorry", "what", "correct", "change", "help", "order", "wrong"
        ])
        assert responds, f"Should respond to concern. Message: {result.message}"
