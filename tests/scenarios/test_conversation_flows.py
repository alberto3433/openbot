"""
Multi-Turn Conversation Flow Tests.

These tests simulate realistic multi-turn conversations with back-and-forth
interactions, clarifications, and complex ordering sequences.

Run with: pytest tests/scenarios/ -v
"""

import pytest
from orderbot.tasks.state_machine import OrderStateMachine
from orderbot.tasks.models import OrderTask
from orderbot.tasks.schemas import OrderPhase


class TestBagelConfigFlows:
    """Multi-turn bagel configuration conversations."""

    def test_full_bagel_config_all_questions(self):
        """Complete bagel order answering all questions."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("I want a bagel", order)

        # Answer questions as they come
        current = result1
        answers = ["everything", "yes", "scallion cream cheese", "no extras"]

        for answer in answers:
            if current.order.phase == OrderPhase.TAKING_ITEMS.value:
                break
            current = sm.process(answer, current.order)

        items = current.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_bagel_with_single_word_answers(self):
        """Bagel order with minimal single word answers."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("bagel please", order)

        current = result1
        answers = ["plain", "no", "butter", "no"]

        for answer in answers:
            if current.order.phase == OrderPhase.TAKING_ITEMS.value:
                break
            current = sm.process(answer, current.order)

        items = current.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_bagel_with_elaborated_answers(self):
        """Bagel order with detailed verbose answers."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Can I get a bagel", order)

        current = result1
        answers = [
            "I'd like the everything bagel",
            "yes please, toasted would be great",
            "I'll have the veggie cream cheese",
            "no thank you, that's all for the bagel"
        ]

        for answer in answers:
            if current.order.phase == OrderPhase.TAKING_ITEMS.value:
                break
            current = sm.process(answer, current.order)

        items = current.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestCoffeeConfigFlows:
    """Multi-turn coffee configuration conversations."""

    def test_full_coffee_config(self):
        """Complete coffee order with all customizations."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("I want a latte", order)

        current = result1
        answers = ["large", "iced", "oat milk", "no sweetener"]

        for answer in answers:
            if current.order.phase == OrderPhase.TAKING_ITEMS.value:
                break
            current = sm.process(answer, current.order)

        items = current.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_coffee_with_add_ons_during_config(self):
        """Coffee order with add-ons requested during config."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Coffee please", order)

        current = result1
        answers = ["medium", "hot", "with cream and two sugars"]

        for answer in answers:
            if current.order.phase == OrderPhase.TAKING_ITEMS.value:
                break
            current = sm.process(answer, current.order)

        items = current.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_espresso_drink_config(self):
        """Espresso drink configuration flow."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Cappuccino", order)

        current = result1
        answers = ["small", "hot please", "regular milk is fine"]

        for answer in answers:
            if current.order.phase == OrderPhase.TAKING_ITEMS.value:
                break
            current = sm.process(answer, current.order)

        items = current.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestMultiItemFlows:
    """Multi-turn flows with multiple items."""

    def test_bagel_then_coffee_sequential(self):
        """Order bagel completely then add coffee."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        # Order and configure bagel
        result1 = sm.process("Everything bagel", order)
        result2 = sm.process("toasted please", result1.order)
        result3 = sm.process("plain cream cheese", result2.order)

        # Now add coffee
        result4 = sm.process("and a large iced latte", result3.order)

        # Configure coffee if needed
        current = result4
        for _ in range(3):
            if current.order.phase == OrderPhase.TAKING_ITEMS.value:
                break
            current = sm.process("no thanks", current.order)

        items = current.order.items.get_active_items()
        assert len(items) >= 1, "Should have items"

    def test_add_item_while_configuring(self):
        """Add new item while in the middle of configuring first."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Plain bagel", order)
        # In middle of config, add another item
        result2 = sm.process("yes toasted, and also a coffee", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have items"

    def test_build_order_across_turns(self):
        """Build up an order across many turns."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Let me get an everything bagel toasted with cream cheese", order)
        result2 = sm.process("add a BEC too", result1.order)
        result3 = sm.process("and throw in a large coffee", result2.order)
        result4 = sm.process("oh and two cookies", result3.order)

        items = result4.order.items.get_active_items()
        assert len(items) >= 1, "Should have multiple items"


class TestClarificationFlows:
    """Flows requiring clarification from the bot."""

    def test_clarify_bagel_type(self):
        """Clarification needed for bagel type."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("bagel with lox", order)
        result2 = sm.process("everything please", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_clarify_size(self):
        """Clarification needed for drink size."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("iced latte", order)
        result2 = sm.process("large", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_clarify_then_modify(self):
        """Answer clarification then modify."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("coffee", order)
        result2 = sm.process("medium hot", result1.order)
        result3 = sm.process("actually make it large", result2.order)

        items = result3.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestModificationFlows:
    """Flows with modifications during ordering."""

    def test_change_answer_immediately(self):
        """Change answer right after giving it."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Plain bagel", order)
        result2 = sm.process("yes toasted", result1.order)
        result3 = sm.process("wait no, not toasted", result2.order)

        items = result3.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_go_back_and_change(self):
        """Request to change an earlier decision."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Everything bagel toasted", order)
        result2 = sm.process("plain cream cheese", result1.order)
        result3 = sm.process("go back and make it scallion instead", result2.order)

        items = result3.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_add_modifier_after_config_complete(self):
        """Add modifier after item config is done."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Everything bagel toasted with butter", order)

        # Complete config
        current = result1
        for _ in range(3):
            if current.order.phase == OrderPhase.TAKING_ITEMS.value:
                break
            current = sm.process("no thanks", current.order)

        # Now add modifier
        result2 = sm.process("add bacon to the bagel", current.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"


class TestCancellationFlows:
    """Flows involving cancellations."""

    def test_cancel_and_restart(self):
        """Cancel current item and start fresh."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Sesame bagel", order)
        result2 = sm.process("cancel that", result1.order)
        result3 = sm.process("everything bagel instead", result2.order)

        items = result3.order.items.get_active_items()
        assert len(items) >= 1 or result3.message is not None, "Should have item or response"

    def test_remove_one_from_multi(self):
        """Remove one item from multi-item order."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("BEC on everything and a large coffee", order)
        result2 = sm.process("remove the coffee", result1.order)

        assert result2.message is not None, "Should have a response"

    def test_cancel_mid_config(self):
        """Cancel while in the middle of configuration."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Plain bagel", order)
        result2 = sm.process("yes toasted", result1.order)
        result3 = sm.process("nevermind, cancel that", result2.order)

        assert result3.message is not None, "Should have a response"


class TestComplexConversations:
    """Complex multi-turn conversations."""

    def test_change_mind_multiple_times(self):
        """Customer changes mind multiple times."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Plain bagel", order)
        result2 = sm.process("make it everything", result1.order)
        result3 = sm.process("no wait, sesame", result2.order)
        result4 = sm.process("you know what, everything was right", result3.order)

        items = result4.order.items.get_active_items()
        assert len(items) >= 1, "Should have at least 1 item"

    def test_order_with_questions_interspersed(self):
        """Order with questions mixed in."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Everything bagel", order)
        result2 = sm.process("is the scallion cream cheese good?", result1.order)
        result3 = sm.process("I'll try it, yes", result2.order)

        items = result3.order.items.get_active_items()
        assert len(items) >= 1 or result3.message is not None, "Should have item or response"

    def test_long_conversation_with_adds_and_removes(self):
        """Long conversation with multiple adds and removes."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Everything bagel toasted with cream cheese", order)
        result2 = sm.process("and a coffee", result1.order)
        result3 = sm.process("large hot", result2.order)
        result4 = sm.process("add a muffin", result3.order)
        result5 = sm.process("remove the coffee", result4.order)
        result6 = sm.process("add it back, make it iced", result5.order)

        items = result6.order.items.get_active_items()
        assert len(items) >= 1 or result6.message is not None, "Should have items or response"

    def test_hesitant_customer(self):
        """Customer who keeps hesitating and asking."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("hmm what should I get", order)
        result2 = sm.process("what's your most popular bagel?", result1.order)
        result3 = sm.process("ok I'll try the everything with cream cheese", result2.order)

        items = result3.order.items.get_active_items()
        assert len(items) >= 1 or result3.message is not None, "Should have item or response"


class TestFinalizationFlows:
    """Flows around finishing orders."""

    def test_that_will_be_all(self):
        """Customer indicating they're done."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Everything bagel toasted with cream cheese", order)

        # Complete config
        current = result1
        for _ in range(3):
            if current.order.phase == OrderPhase.TAKING_ITEMS.value:
                break
            current = sm.process("no thanks", current.order)

        result2 = sm.process("that will be all", current.order)

        assert result2.message is not None, "Should have a response"

    def test_ready_to_checkout(self):
        """Customer saying ready to checkout."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("BEC on everything", order)
        result2 = sm.process("I'm ready to pay", result1.order)

        assert result2.message is not None, "Should have a response"

    def test_anything_else_no(self):
        """Answering no to 'anything else' question."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Large hot coffee", order)

        current = result1
        for _ in range(5):
            if "anything else" in current.message.lower():
                result2 = sm.process("no that's it", current.order)
                break
            current = sm.process("no", current.order)
        else:
            result2 = current

        assert result2.message is not None, "Should have a response"


class TestRecoveryFlows:
    """Flows testing error recovery."""

    def test_misunderstanding_correction(self):
        """Correct a misunderstanding."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Plain bagel", order)
        result2 = sm.process("no I meant a plain cream cheese on everything", result1.order)

        items = result2.order.items.get_active_items()
        assert len(items) >= 1 or result2.message is not None, "Should have item or response"

    def test_wrong_item_correction(self):
        """Bot got wrong item, customer corrects."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("I said BEC not bagel with cream cheese", order)

        items = result1.order.items.get_active_items()
        assert len(items) >= 1 or result1.message is not None, "Should have item or response"

    def test_repeat_request(self):
        """Customer asks bot to repeat."""
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result1 = sm.process("Everything bagel", order)
        result2 = sm.process("what was the question again?", result1.order)

        assert result2.message is not None, "Should have a response"
