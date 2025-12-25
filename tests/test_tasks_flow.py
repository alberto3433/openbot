"""
Tests for the flow control module.

Tests state updates, next action selection, and the complete flow.
"""

import pytest

from sandwich_bot.tasks.models import (
    TaskStatus,
    OrderTask,
    BagelItemTask,
    CoffeeItemTask,
)
from sandwich_bot.tasks.parsing import (
    ParsedInput,
    ParsedBagelItem,
    ParsedCoffeeItem,
    ItemModification,
)
from sandwich_bot.tasks.flow import (
    ActionType,
    NextAction,
    update_order_state,
    get_next_action,
    process_message,
)
from sandwich_bot.tasks.field_config import MenuFieldConfig


# =============================================================================
# State Update Tests
# =============================================================================

class TestUpdateOrderState:
    """Tests for update_order_state function."""

    def test_add_single_bagel(self):
        """Test adding a single bagel to order."""
        order = OrderTask()
        parsed = ParsedInput(
            new_bagels=[ParsedBagelItem(bagel_type="everything")]
        )

        order = update_order_state(order, parsed)

        assert len(order.items.items) == 1
        assert isinstance(order.items.items[0], BagelItemTask)
        assert order.items.items[0].bagel_type == "everything"

    def test_add_multiple_items(self):
        """Test adding multiple items at once."""
        order = OrderTask()
        parsed = ParsedInput(
            new_bagels=[
                ParsedBagelItem(bagel_type="plain", toasted=True),
            ],
            new_coffees=[
                ParsedCoffeeItem(drink_type="latte", size="large", iced=True),
            ],
        )

        order = update_order_state(order, parsed)

        assert len(order.items.items) == 2
        assert order.items.items[0].bagel_type == "plain"
        assert order.items.items[0].toasted is True
        assert order.items.items[1].drink_type == "latte"
        assert order.items.items[1].iced is True

    def test_apply_answers(self):
        """Test applying answers to current item."""
        order = OrderTask()
        # Add a bagel first
        order = update_order_state(order, ParsedInput(
            new_bagels=[ParsedBagelItem(bagel_type="sesame")]
        ))

        # Now apply answer
        parsed = ParsedInput(answers={"toasted": True})
        order = update_order_state(order, parsed)

        assert order.items.items[0].toasted is True

    def test_cancel_item_by_index(self):
        """Test cancelling item by index."""
        order = OrderTask()
        order = update_order_state(order, ParsedInput(
            new_bagels=[
                ParsedBagelItem(bagel_type="plain"),
                ParsedBagelItem(bagel_type="everything"),
            ]
        ))

        # Cancel first item
        parsed = ParsedInput(cancel_item_index=0)
        order = update_order_state(order, parsed)

        assert order.items.items[0].status == TaskStatus.SKIPPED
        assert order.items.items[1].status != TaskStatus.SKIPPED

    def test_cancel_item_by_description(self):
        """Test cancelling item by description."""
        order = OrderTask()
        order = update_order_state(order, ParsedInput(
            new_bagels=[ParsedBagelItem(bagel_type="plain")],
            new_coffees=[ParsedCoffeeItem(drink_type="latte")],
        ))

        # Cancel the bagel
        parsed = ParsedInput(cancel_item_description="plain bagel")
        order = update_order_state(order, parsed)

        assert order.items.items[0].status == TaskStatus.SKIPPED
        assert order.items.items[1].status != TaskStatus.SKIPPED

    def test_apply_modification(self):
        """Test applying modification to item."""
        order = OrderTask()
        order = update_order_state(order, ParsedInput(
            new_bagels=[ParsedBagelItem(bagel_type="sesame", toasted=True)]
        ))

        # Modify toasted to False
        parsed = ParsedInput(
            modifications=[
                ItemModification(item_index=0, field="toasted", new_value=False)
            ]
        )
        order = update_order_state(order, parsed)

        assert order.items.items[0].toasted is False

    def test_set_order_type_pickup(self):
        """Test setting order type to pickup."""
        order = OrderTask()
        parsed = ParsedInput(order_type="pickup")
        order = update_order_state(order, parsed)

        assert order.delivery_method.order_type == "pickup"
        assert order.delivery_method.status == TaskStatus.COMPLETE

    def test_set_order_type_delivery(self):
        """Test setting order type to delivery."""
        order = OrderTask()
        parsed = ParsedInput(
            order_type="delivery",
            delivery_address="123 Main St, New York"
        )
        order = update_order_state(order, parsed)

        assert order.delivery_method.order_type == "delivery"
        assert order.delivery_method.address.street == "123 Main St, New York"

    def test_set_customer_info(self):
        """Test setting customer information."""
        order = OrderTask()
        parsed = ParsedInput(
            customer_name="John Doe",
            customer_phone="555-1234",
            customer_email="john@example.com"
        )
        order = update_order_state(order, parsed)

        assert order.customer_info.name == "John Doe"
        assert order.customer_info.phone == "555-1234"
        assert order.customer_info.email == "john@example.com"

    def test_set_payment_method(self):
        """Test setting payment method."""
        order = OrderTask()
        parsed = ParsedInput(payment_method="card_link")
        order = update_order_state(order, parsed)

        assert order.payment.method == "card_link"


# =============================================================================
# Next Action Tests
# =============================================================================

class TestGetNextAction:
    """Tests for get_next_action function."""

    def test_empty_order_prompts_for_items(self):
        """Test that empty order asks what customer wants."""
        order = OrderTask()
        action = get_next_action(order)

        assert action.action_type == ActionType.ASK_QUESTION
        assert "what" in action.question.lower()

    def test_greeting_response(self):
        """Test response to greeting."""
        order = OrderTask()
        parsed = ParsedInput(is_greeting=True)
        action = get_next_action(order, parsed)

        assert action.action_type == ActionType.GREETING
        assert action.message is not None

    def test_asks_missing_bagel_fields(self):
        """Test asking for missing bagel fields."""
        order = OrderTask()
        order = update_order_state(order, ParsedInput(
            new_bagels=[ParsedBagelItem(bagel_type="plain")]
        ))

        action = get_next_action(order)

        # Should ask about spread first (optional but ask_if_empty=True)
        assert action.action_type == ActionType.ASK_QUESTION
        assert action.field_name == "spread"
        assert "cream cheese" in action.question.lower() or "butter" in action.question.lower()

    def test_asks_missing_coffee_fields(self):
        """Test asking for missing coffee fields."""
        order = OrderTask()
        order = update_order_state(order, ParsedInput(
            new_coffees=[ParsedCoffeeItem(drink_type="latte")]
        ))

        action = get_next_action(order)

        # Should ask about iced (required field without default)
        assert action.action_type == ActionType.ASK_QUESTION
        assert action.field_name == "iced"

    def test_coffee_with_all_fields_complete(self):
        """Test coffee with all required fields is complete."""
        order = OrderTask()
        order = update_order_state(order, ParsedInput(
            new_coffees=[ParsedCoffeeItem(
                drink_type="latte",
                size="large",
                iced=True,
            )]
        ))

        action = get_next_action(order)

        # Should ask if they want anything else
        assert action.action_type == ActionType.ASK_QUESTION
        assert "else" in action.question.lower() or "anything" in action.question.lower()

    def test_asks_for_pickup_or_delivery(self):
        """Test asking for pickup or delivery."""
        order = OrderTask()
        # Add complete item
        parsed = ParsedInput(
            new_coffees=[ParsedCoffeeItem(
                drink_type="drip coffee",
                size="medium",
                iced=False,
            )],
            no_more_items=True,
        )
        order = update_order_state(order, parsed)

        # Pass parsed to get_next_action so it knows user said no more items
        action = get_next_action(order, parsed)

        assert action.action_type == ActionType.ASK_QUESTION
        assert "pickup" in action.question.lower() or "delivery" in action.question.lower()

    def test_asks_for_customer_name(self):
        """Test asking for customer name."""
        order = OrderTask()
        # Add complete item
        parsed = ParsedInput(
            new_coffees=[ParsedCoffeeItem(
                drink_type="drip coffee",
                size="medium",
                iced=False,
            )],
            no_more_items=True,
            order_type="pickup",
        )
        order = update_order_state(order, parsed)

        # Pass parsed to get_next_action so it knows user said no more items
        action = get_next_action(order, parsed)

        assert action.action_type == ActionType.ASK_QUESTION
        assert "name" in action.question.lower()

    def test_shows_order_summary(self):
        """Test showing order summary before checkout."""
        order = OrderTask()
        parsed = ParsedInput(
            new_coffees=[ParsedCoffeeItem(
                drink_type="latte",
                size="large",
                iced=True,
            )],
            no_more_items=True,
            order_type="pickup",
            customer_name="John",
        )
        order = update_order_state(order, parsed)

        # Pass parsed to get_next_action so it knows user said no more items
        action = get_next_action(order, parsed)

        assert action.action_type == ActionType.SHOW_ORDER
        assert "latte" in action.message.lower()


# =============================================================================
# Complete Flow Tests
# =============================================================================

class TestProcessMessage:
    """Tests for process_message function."""

    def test_full_single_item_flow(self):
        """Test complete flow for single item order."""
        order = OrderTask()

        # 1. Initial greeting
        order, action = process_message(order, ParsedInput(is_greeting=True))
        assert action.action_type == ActionType.GREETING

        # 2. Order a bagel
        order, action = process_message(order, ParsedInput(
            new_bagels=[ParsedBagelItem(bagel_type="everything")]
        ))
        # Should ask about spread first (ask_if_empty=True)
        assert action.action_type == ActionType.ASK_QUESTION
        assert action.field_name == "spread"

        # 3. Answer spread
        order, action = process_message(order, ParsedInput(
            answers={"spread": "cream cheese"}
        ))
        # Should ask about toasted next
        assert action.action_type == ActionType.ASK_QUESTION
        assert action.field_name == "toasted"

        # 4. Answer toasted
        order, action = process_message(order, ParsedInput(
            answers={"toasted": True}
        ))
        # Should ask if they want anything else (extras has ask_if_empty=False)
        assert action.action_type == ActionType.ASK_QUESTION

        # 5. No more items
        order, action = process_message(order, ParsedInput(
            no_more_items=True
        ))
        # Should ask pickup or delivery
        assert action.action_type == ActionType.ASK_QUESTION
        assert "pickup" in action.question.lower() or "delivery" in action.question.lower()

    def test_pickup_proceeds_to_customer_name(self):
        """Test that after saying pickup, flow proceeds to customer name, not back to items."""
        order = OrderTask()

        # Add complete bagel
        order, action = process_message(order, ParsedInput(
            new_bagels=[ParsedBagelItem(bagel_type="plain", toasted=True, spread="cream cheese")]
        ))

        # Say "that's it"
        order, action = process_message(order, ParsedInput(
            no_more_items=True
        ))
        # Should ask pickup or delivery
        assert "pickup" in action.question.lower() or "delivery" in action.question.lower()

        # Say "pickup"
        order, action = process_message(order, ParsedInput(
            order_type="pickup"
        ))

        # Should ask for customer name, NOT "Anything else?"
        assert action.action_type == ActionType.ASK_QUESTION
        assert action.field_name == "name"
        assert "name" in action.question.lower()
        assert "else" not in action.question.lower()

    def test_multi_item_flow(self):
        """Test flow with multiple items."""
        order = OrderTask()

        # Order bagel and coffee at once
        order, action = process_message(order, ParsedInput(
            new_bagels=[ParsedBagelItem(bagel_type="sesame", toasted=True)],
            new_coffees=[ParsedCoffeeItem(drink_type="latte", size="large", iced=True)],
        ))

        # Should ask about first incomplete item (bagel spread)
        assert action.action_type == ActionType.ASK_QUESTION

        # Answer bagel questions
        order, action = process_message(order, ParsedInput(
            answers={"spread": None}  # No spread
        ))

        # Continue through flow until items complete
        order, action = process_message(order, ParsedInput(
            no_more_items=True
        ))

        # Should eventually ask about pickup/delivery
        assert order.items.get_item_count() == 2

    def test_modification_mid_flow(self):
        """Test modifying an item mid-flow."""
        order = OrderTask()

        # Add bagel
        order, action = process_message(order, ParsedInput(
            new_bagels=[ParsedBagelItem(bagel_type="plain", toasted=True)]
        ))

        # Modify toasted
        order, action = process_message(order, ParsedInput(
            modifications=[
                ItemModification(item_index=0, field="toasted", new_value=False)
            ]
        ))

        assert order.items.items[0].toasted is False

    def test_cancel_and_continue(self):
        """Test cancelling an item and continuing."""
        order = OrderTask()

        # Add two items
        order, action = process_message(order, ParsedInput(
            new_bagels=[ParsedBagelItem(bagel_type="plain")],
            new_coffees=[ParsedCoffeeItem(drink_type="latte")],
        ))

        # Cancel the bagel
        order, action = process_message(order, ParsedInput(
            cancel_item_index=0
        ))

        # Bagel should be skipped
        assert order.items.items[0].status == TaskStatus.SKIPPED
        # Coffee should still be active
        assert order.items.items[1].status != TaskStatus.SKIPPED


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_parsed_input(self):
        """Test handling empty parsed input."""
        order = OrderTask()
        parsed = ParsedInput()
        order, action = process_message(order, parsed)

        # Should still work, asking for items
        assert action.action_type == ActionType.ASK_QUESTION

    def test_modification_invalid_index(self):
        """Test modification with invalid index is ignored."""
        order = OrderTask()
        order = update_order_state(order, ParsedInput(
            new_bagels=[ParsedBagelItem(bagel_type="plain")]
        ))

        # Try to modify non-existent item
        order = update_order_state(order, ParsedInput(
            modifications=[
                ItemModification(item_index=99, field="toasted", new_value=True)
            ]
        ))

        # Should not crash, bagel should be unchanged
        assert order.items.items[0].toasted is None

    def test_answer_without_current_item(self):
        """Test applying answer when no current item."""
        order = OrderTask()
        parsed = ParsedInput(answers={"toasted": True})

        # Should not crash
        order = update_order_state(order, parsed)
        assert len(order.items.items) == 0

    def test_defaults_applied_from_menu_config(self):
        """Test that menu config defaults are applied."""
        order = OrderTask()
        menu_config = MenuFieldConfig()

        # Coffee size should default to "medium" per menu config
        order = update_order_state(order, ParsedInput(
            new_coffees=[ParsedCoffeeItem(drink_type="latte", iced=True)]
        ), menu_config)

        # Size should have default applied
        assert order.items.items[0].size == "medium"

    def test_order_confirmed_flag_set_on_completion(self):
        """Test that checkout.confirmed is set when order is complete."""
        order = OrderTask()

        # Complete a full order flow
        # Add complete item with all required fields
        order, action = process_message(order, ParsedInput(
            new_coffees=[ParsedCoffeeItem(
                drink_type="latte",
                size="large",
                iced=True,
            )],
            no_more_items=True,
            order_type="pickup",
            customer_name="Test",
        ))

        # Should show order summary
        assert action.action_type == ActionType.SHOW_ORDER

        # Confirm the order
        order, action = process_message(order, ParsedInput(
            confirms_order=True,
        ))

        # Should ask about payment link
        assert action.action_type == ActionType.ASK_PAYMENT

        # Answer payment link question
        order, action = process_message(order, ParsedInput(
            wants_payment_link=False,
        ))

        # Should complete the order
        assert action.action_type == ActionType.COMPLETE_ORDER
        # Confirmed flag should be set
        assert order.checkout.confirmed is True
        assert order.checkout.status == TaskStatus.COMPLETE

    def test_clarification_message_validation(self):
        """Test that invalid clarification messages are replaced with default."""
        order = OrderTask()

        # Test 1: Invalid clarification (no question mark, too long, LLM reasoning)
        parsed = ParsedInput(
            needs_clarification=True,
            clarification_needed="plain bagel toasted with cream cheese. User may want to build that specific bagel rather than ordering from the speed menu."
        )
        order, action = process_message(order, parsed)

        assert action.action_type == ActionType.CLARIFY
        # Should use default message, not the LLM reasoning
        assert action.message == "I didn't quite catch that. Could you repeat?"

    def test_valid_clarification_question_passes_through(self):
        """Test that valid clarification questions are used as-is."""
        order = OrderTask()

        # Test 2: Valid clarification question (ends with ?, short)
        parsed = ParsedInput(
            needs_clarification=True,
            clarification_needed="Did you want a bagel or a coffee?"
        )
        order, action = process_message(order, parsed)

        assert action.action_type == ActionType.CLARIFY
        # Should use the valid question as-is
        assert action.message == "Did you want a bagel or a coffee?"


# =============================================================================
# Split Item Tests
# =============================================================================

class TestSplitItems:
    """Tests for splitting multi-quantity items with different attributes."""

    def test_split_bagels_with_different_spreads(self):
        """Test splitting 2 bagels with different spreads via modifications."""
        order = OrderTask()

        # Add 2 bagels
        order, action = process_message(order, ParsedInput(
            new_bagels=[ParsedBagelItem(bagel_type="plain", quantity=2, toasted=True)]
        ))

        # Should have 1 item with quantity 2
        assert len(order.items.items) == 1
        assert order.items.items[0].quantity == 2

        # Split with "butter on one, cream cheese on the other"
        # LLM may return this as modifications with different indices
        order, action = process_message(order, ParsedInput(
            modifications=[
                ItemModification(item_index=0, field="spread", new_value="butter"),
                ItemModification(item_index=1, field="spread", new_value="cream cheese"),
            ]
        ))

        # Should now have 2 separate items with quantity 1 each
        assert len(order.items.items) == 2
        assert order.items.items[0].quantity == 1
        assert order.items.items[1].quantity == 1
        # Each should have different spread
        spreads = {order.items.items[0].spread, order.items.items[1].spread}
        assert spreads == {"butter", "cream cheese"}

    def test_split_bagels_via_split_item_answers(self):
        """Test splitting 2 bagels with split_item_answers field."""
        order = OrderTask()

        # Add 2 bagels
        order, action = process_message(order, ParsedInput(
            new_bagels=[ParsedBagelItem(bagel_type="plain", quantity=2, toasted=True)]
        ))

        # Split using split_item_answers
        order, action = process_message(order, ParsedInput(
            split_item_answers=[
                {"spread": "butter"},
                {"spread": "cream cheese"}
            ]
        ))

        # Should now have 2 separate items
        assert len(order.items.items) == 2
        assert order.items.items[0].spread == "butter"
        assert order.items.items[1].spread == "cream cheese"

    def test_split_coffee_with_different_iced(self):
        """Test splitting 2 coffees - one hot, one iced."""
        order = OrderTask()

        # Add 2 coffees
        order, action = process_message(order, ParsedInput(
            new_coffees=[ParsedCoffeeItem(drink_type="latte", quantity=2, size="medium")]
        ))

        # Split with different iced values
        order, action = process_message(order, ParsedInput(
            modifications=[
                ItemModification(item_index=0, field="iced", new_value=True),
                ItemModification(item_index=1, field="iced", new_value=False),
            ]
        ))

        # Should have 2 separate items
        assert len(order.items.items) == 2
        iced_values = {order.items.items[0].iced, order.items.items[1].iced}
        assert iced_values == {True, False}

    def test_no_split_for_same_values(self):
        """Test that same values don't trigger a split."""
        order = OrderTask()

        # Add 2 bagels
        order, action = process_message(order, ParsedInput(
            new_bagels=[ParsedBagelItem(bagel_type="plain", quantity=2, toasted=True)]
        ))

        # "Both with cream cheese" - same value for both
        order, action = process_message(order, ParsedInput(
            modifications=[
                ItemModification(item_index=0, field="spread", new_value="cream cheese"),
                ItemModification(item_index=1, field="spread", new_value="cream cheese"),
            ]
        ))

        # Should NOT split - still 1 item with quantity 2
        assert len(order.items.items) == 1
        assert order.items.items[0].quantity == 2
        assert order.items.items[0].spread == "cream cheese"

    def test_split_preserves_toasted_attribute(self):
        """Test that split items preserve other attributes."""
        order = OrderTask()

        # Add 2 toasted plain bagels
        order, action = process_message(order, ParsedInput(
            new_bagels=[ParsedBagelItem(bagel_type="plain", quantity=2, toasted=True)]
        ))

        # Split by spread
        order, action = process_message(order, ParsedInput(
            modifications=[
                ItemModification(item_index=0, field="spread", new_value="butter"),
                ItemModification(item_index=1, field="spread", new_value="cream cheese"),
            ]
        ))

        # Both should still be toasted
        assert order.items.items[0].toasted is True
        assert order.items.items[1].toasted is True
        # Both should be plain
        assert order.items.items[0].bagel_type == "plain"
        assert order.items.items[1].bagel_type == "plain"

    def test_split_items_have_distinguishing_questions(self):
        """Test that split items get distinguishing context in questions."""
        order = OrderTask()

        # Add 2 bagels (no toasted value yet)
        order, action = process_message(order, ParsedInput(
            new_bagels=[ParsedBagelItem(bagel_type="plain", quantity=2)]
        ))

        # Split by spread - this sets spread but not toasted
        order, action = process_message(order, ParsedInput(
            split_item_answers=[
                {"spread": "butter"},
                {"spread": "cream cheese"}
            ]
        ))

        # Now we should have 2 separate items, each needing toasted
        assert len(order.items.items) == 2
        assert order.items.items[0].spread == "butter"
        assert order.items.items[1].spread == "cream cheese"

        # The first bagel should be asked about toasted - with context
        # since there's another similar item
        assert action.action_type == ActionType.ASK_QUESTION
        # The question should include "the one with butter" to distinguish
        assert "butter" in action.question.lower()

        # Answer for first bagel
        order, action = process_message(order, ParsedInput(
            answers={"toasted": True}
        ))

        # Now asking about second bagel - should mention cream cheese
        assert action.action_type == ActionType.ASK_QUESTION
        assert "cream cheese" in action.question.lower()
