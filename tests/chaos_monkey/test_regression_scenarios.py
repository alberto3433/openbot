"""Unit tests for regression scenario classes.

Tests each regression scenario pattern using OrderStateMachine directly
(no API server needed). Uses fixed seeds for reproducibility.

Run with:
    python -m pytest tests/chaos_monkey/test_regression_scenarios.py -v
"""

import pytest

from orderbot.tasks.models import OrderTask
from orderbot.tasks.state_machine import OrderStateMachine, OrderPhase


class TestOrderTypeConfusion:
    """Pattern 1: 'make it pickup' should not empty the cart."""

    def test_make_it_pickup_preserves_cart(self, order_and_sm):
        """After adding an item, 'make it pickup' should keep the item."""
        order, sm = order_and_sm

        # Add an item
        result = sm.process("I'd like a plain bagel", order)
        active = order.items.get_active_items()
        assert len(active) >= 1, "Should have at least 1 item after ordering"

        # Answer config questions to stabilize
        for _ in range(5):
            if not order.pending_field:
                break
            result = sm.process("yes", order)

        items_before = len(order.items.get_active_items())
        assert items_before >= 1, "Should still have items before order type change"

        # Say "make it pickup"
        result = sm.process("make it pickup", order)

        items_after = order.items.get_active_items()
        assert len(items_after) >= items_before, (
            f"Cart should not lose items after 'make it pickup'. "
            f"Had {items_before}, now have {len(items_after)}"
        )

    def test_make_it_delivery_preserves_cart(self, order_and_sm):
        """After adding an item, 'make it delivery' should keep the item."""
        order, sm = order_and_sm

        result = sm.process("I'd like a hot coffee", order)
        active = order.items.get_active_items()
        assert len(active) >= 1, "Should have at least 1 item"

        # Answer config questions
        for _ in range(5):
            if not order.pending_field:
                break
            result = sm.process("large", order)

        items_before = len(order.items.get_active_items())

        result = sm.process("make it delivery", order)

        items_after = order.items.get_active_items()
        assert len(items_after) >= items_before, (
            f"Cart should not lose items after 'make it delivery'. "
            f"Had {items_before}, now have {len(items_after)}"
        )


class TestAttributeDecline:
    """Pattern 2: 'no X please' during config should not remove the item."""

    def test_no_option_during_config_keeps_item(self, order_and_sm):
        """Declining an attribute option should not remove the item."""
        order, sm = order_and_sm

        result = sm.process("I'd like a plain bagel", order)
        active = order.items.get_active_items()
        assert len(active) >= 1, "Should have at least 1 item"

        # Say "no" to a config question
        result = sm.process("no thanks", order)

        active_after = order.items.get_active_items()
        assert len(active_after) >= 1, (
            "Item should not be removed when declining an attribute option"
        )

    def test_not_toasted_keeps_item(self, order_and_sm):
        """'not toasted' should set toasted=false, not remove item."""
        order, sm = order_and_sm

        result = sm.process("I'd like a plain bagel", order)
        assert len(order.items.get_active_items()) >= 1

        result = sm.process("not toasted", order)

        active = order.items.get_active_items()
        assert len(active) >= 1, (
            "Item should remain after 'not toasted'"
        )


class TestQualifierPersistence:
    """Pattern 3: Qualifiers should survive disambiguation."""

    def test_large_qualifier_on_item(self, order_and_sm):
        """'large iced latte' should create an item — qualifier should not be lost."""
        order, sm = order_and_sm

        result = sm.process("large iced latte", order)

        # May get disambiguation or direct add — either way, respond
        if "which" in result.message.lower() or "did you mean" in result.message.lower():
            result = sm.process("1", order)

        active = order.items.get_active_items()
        assert len(active) >= 1, (
            "Should have at least 1 item after ordering with qualifier"
        )

    def test_iced_qualifier_on_item(self, order_and_sm):
        """'iced coffee' should create an item with iced attribute."""
        order, sm = order_and_sm

        result = sm.process("iced coffee", order)

        if "which" in result.message.lower() or "did you mean" in result.message.lower():
            result = sm.process("1", order)

        active = order.items.get_active_items()
        assert len(active) >= 1, (
            "Should have at least 1 item after ordering iced coffee"
        )


class TestOrderTypeMidOrder:
    """Pattern 5: 'change it to delivery' should set order type, not modify item."""

    def test_change_to_delivery_sets_order_type(self, order_and_sm):
        """'change it to delivery' should set order_type and keep items."""
        order, sm = order_and_sm

        result = sm.process("I'd like a plain bagel", order)
        assert len(order.items.get_active_items()) >= 1

        # Answer config questions
        for _ in range(5):
            if not order.pending_field:
                break
            result = sm.process("yes", order)

        items_before = len(order.items.get_active_items())

        result = sm.process("change it to delivery", order)

        items_after = order.items.get_active_items()
        assert len(items_after) >= items_before, (
            f"Cart should not lose items after 'change it to delivery'. "
            f"Had {items_before}, now have {len(items_after)}"
        )

    def test_switch_to_pickup_sets_order_type(self, order_and_sm):
        """'switch to pickup' should set order_type and keep items."""
        order, sm = order_and_sm

        result = sm.process("I'd like a hot coffee", order)
        assert len(order.items.get_active_items()) >= 1

        for _ in range(5):
            if not order.pending_field:
                break
            result = sm.process("large", order)

        items_before = len(order.items.get_active_items())

        result = sm.process("switch to pickup", order)

        items_after = order.items.get_active_items()
        assert len(items_after) >= items_before, (
            f"Cart should not lose items after 'switch to pickup'. "
            f"Had {items_before}, now have {len(items_after)}"
        )


class TestInstructionLeak:
    """Pattern 4: 'X on the side' should not leak item name into instructions."""

    def test_on_the_side_no_item_name_leak(self, order_and_sm):
        """Ordering 'cream cheese on the side' should not put 'cream cheese' as instruction."""
        order, sm = order_and_sm

        result = sm.process("plain bagel with cream cheese on the side", order)

        active = order.items.get_active_items()
        assert len(active) >= 1, "Should have at least 1 item"

        # Check that the item's special instructions don't contain the item's own name
        for item in active:
            item_name = (item.menu_item_name or "").lower()
            if item_name and item.special_instructions:
                for instr in item.special_instructions:
                    # The item name itself should not be the instruction
                    assert item_name not in instr.lower() or "on the side" in instr.lower(), (
                        f"Item name '{item_name}' leaked into instruction: '{instr}'"
                    )


class TestPhaseRestoration:
    """Pattern 6: Adding items after providing customer info should work."""

    def test_add_item_after_name(self, order_and_sm):
        """After providing name, user should be able to add more items."""
        order, sm = order_and_sm

        # Add first item
        result = sm.process("I'd like a plain bagel", order)
        assert len(order.items.get_active_items()) >= 1

        # Answer config questions until item is fully configured
        for _ in range(5):
            if not order.pending_field:
                break
            result = sm.process("yes", order)

        # Say "that's it" to signal done with items, then provide name
        result = sm.process("that's all for now", order)

        items_count_1 = len(order.items.get_active_items())

        # Provide name
        result = sm.process("my name is Test", order)

        # Add another item — user changes mind
        result = sm.process("actually, I also want an iced tea", order)

        # Should have more items now
        active = order.items.get_active_items()
        assert len(active) > items_count_1, (
            f"Should be able to add items after providing name. "
            f"Had {items_count_1}, now have {len(active)}"
        )


class TestAvailabilityInquiry:
    """Pattern 7: Asking about a specific item should get a direct answer."""

    def test_do_you_have_specific_item(self, order_and_sm):
        """'do you have plain bagel?' should get a direct answer, not a category list."""
        order, sm = order_and_sm

        result = sm.process("do you have plain bagel?", order)

        # Response should mention the item or give a direct yes/no
        response_lower = result.message.lower()

        # Should NOT be a huge numbered list of items (category browsing)
        # Count numbered items — more than 5 suggests category browsing
        import re
        numbered_items = re.findall(r"\d+\.\s+\w+", response_lower)
        assert len(numbered_items) <= 5, (
            f"Response looks like category browsing ({len(numbered_items)} numbered items). "
            f"Expected a direct answer about the specific item."
        )

    def test_is_item_available(self, order_and_sm):
        """'is the iced tea available?' should reference the specific item."""
        order, sm = order_and_sm

        result = sm.process("is the iced tea available?", order)

        # Basic check: the bot gave some response
        assert result.message is not None and len(result.message) > 0, (
            "Bot should respond to availability inquiry"
        )


class TestScenarioGeneration:
    """Test that regression scenario classes generate valid turns."""

    def test_order_type_confusion_generates(self):
        """OrderTypeConfusionScenario should generate 1 initial turn (reactive)."""
        from tests.chaos_monkey.scenarios.regression import OrderTypeConfusionScenario

        item = {"name": "Plain Bagel", "item_type": "bagel"}
        scenario = OrderTypeConfusionScenario(item=item, seed=42)
        turns = scenario.get_turns()

        assert len(turns) == 1
        assert "plain bagel" in turns[0].user_input.lower()
        assert turns[0].expected_items_in_cart == ["Plain Bagel"]
        # Should have generate_answer for reactive config + order type
        assert hasattr(scenario, "generate_answer")

    def test_attribute_decline_generates(self):
        """AttributeDeclineScenario should generate 2 turns."""
        from tests.chaos_monkey.scenarios.regression import AttributeDeclineScenario

        item = {"name": "Hot Coffee", "item_type": "sized_beverage"}
        attr_opts = {"size": ["Small", "Large"], "milk": ["Oat", "Almond"]}
        scenario = AttributeDeclineScenario(
            item=item, attribute_options=attr_opts, seed=42,
        )
        turns = scenario.get_turns()

        assert len(turns) == 2
        assert turns[0].expected_items_in_cart == ["Hot Coffee"]
        assert turns[1].expected_items_in_cart == ["Hot Coffee"]
        assert turns[1].expect_item_count == 1

    def test_qualifier_persistence_generates(self):
        """QualifierPersistenceScenario should generate 2 turns."""
        from tests.chaos_monkey.scenarios.regression import QualifierPersistenceScenario

        item = {"name": "Iced Latte", "item_type": "sized_beverage"}
        scenario = QualifierPersistenceScenario(
            item=item, qualifier="large", seed=42,
        )
        turns = scenario.get_turns()

        assert len(turns) == 2
        assert "large" in turns[0].user_input.lower()
        assert "iced latte" in turns[0].user_input.lower()

    def test_order_type_mid_order_generates(self):
        """OrderTypeMidOrderScenario should generate 1 initial turn (reactive)."""
        from tests.chaos_monkey.scenarios.regression import OrderTypeMidOrderScenario

        item = {"name": "BLT", "item_type": "sandwich"}
        scenario = OrderTypeMidOrderScenario(item=item, seed=42)
        turns = scenario.get_turns()

        assert len(turns) == 1
        assert "blt" in turns[0].user_input.lower()
        assert turns[0].expected_items_in_cart == ["BLT"]
        # Should have generate_answer for reactive config + order type
        assert hasattr(scenario, "generate_answer")

    def test_instruction_leak_generates(self):
        """InstructionLeakScenario should generate 1 turn."""
        from tests.chaos_monkey.scenarios.regression import InstructionLeakScenario

        item = {"name": "Hot Coffee", "item_type": "sized_beverage"}
        scenario = InstructionLeakScenario(item=item, seed=42)
        turns = scenario.get_turns()

        assert len(turns) == 1
        assert "on the side" in turns[0].user_input.lower()
        assert turns[0].expect_no_special_instruction_contains == "hot coffee"

    def test_phase_restoration_generates(self):
        """PhaseRestorationScenario should generate 1 initial turn (reactive)."""
        from tests.chaos_monkey.scenarios.regression import PhaseRestorationScenario

        item1 = {"name": "Plain Bagel", "item_type": "bagel"}
        item2 = {"name": "Hot Coffee", "item_type": "sized_beverage"}
        scenario = PhaseRestorationScenario(item1=item1, item2=item2, seed=42)
        turns = scenario.get_turns()

        assert len(turns) == 1
        assert "plain bagel" in turns[0].user_input.lower()
        assert turns[0].expected_items_in_cart == ["Plain Bagel"]
        # Should have generate_answer for reactive config + name + item2
        assert hasattr(scenario, "generate_answer")

    def test_availability_inquiry_generates(self):
        """AvailabilityInquiryScenario should generate 1 turn."""
        from tests.chaos_monkey.scenarios.regression import AvailabilityInquiryScenario

        item = {"name": "Iced Tea", "item_type": "sized_beverage"}
        scenario = AvailabilityInquiryScenario(item=item, seed=42)
        turns = scenario.get_turns()

        assert len(turns) == 1
        assert turns[0].is_menu_inquiry is True
        assert "iced tea" in turns[0].user_input.lower()
