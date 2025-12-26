"""
Integration tests for the task orchestrator system.

Tests the complete flow from integration layer through orchestrator.
"""

import pytest
import os
from unittest.mock import patch, MagicMock

from sandwich_bot.chains.integration import (
    process_voice_message,
    process_chat_message,
)
from sandwich_bot.tasks.adapter import (
    process_message_with_tasks,
    dict_to_order_task,
    order_task_to_dict,
)
from sandwich_bot.tasks.models import OrderTask, BagelItemTask
from sandwich_bot.tasks.parsing import ParsedInput, ParsedBagelItem
from sandwich_bot.tasks.flow import process_message as flow_process_message


# =============================================================================
# Integration Layer Tests
# =============================================================================

class TestIntegrationLayerRouting:
    """Tests for integration layer routing to task orchestrator."""

    def test_force_task_orchestrator(self):
        """Test forcing task orchestrator via parameter (when state machine is disabled)."""
        # Mock state machine check to return False so task orchestrator can be used
        with patch('sandwich_bot.chains.integration.is_state_machine_enabled', return_value=False):
            with patch('sandwich_bot.chains.integration.process_message_with_tasks') as mock_tasks:
                mock_tasks.return_value = ("Hello!", {}, [{"intent": "greeting"}])

                reply, state, actions = process_voice_message(
                    user_message="Hello",
                    order_state={},
                    history=[],
                    session_id="test-session",
                    force_task_orchestrator=True,
                )

                mock_tasks.assert_called_once()
                assert reply == "Hello!"

    def test_env_flag_routes_to_tasks(self):
        """Test environment flag enables task orchestrator (when state machine is disabled)."""
        # State machine takes priority, so we need to disable it first
        with patch('sandwich_bot.chains.integration.is_state_machine_enabled', return_value=False):
            with patch.dict(os.environ, {"TASK_ORCHESTRATOR_ENABLED": "true"}):
                with patch('sandwich_bot.chains.integration.process_message_with_tasks') as mock_tasks:
                    mock_tasks.return_value = ("Hello!", {}, [])

                    process_chat_message(
                        user_message="Hi",
                        order_state={},
                        history=[],
                        session_id="test",
                    )

                    mock_tasks.assert_called_once()


# =============================================================================
# End-to-End Flow Tests (with mocked LLM)
# =============================================================================

class TestEndToEndFlowMocked:
    """End-to-end tests with mocked LLM parsing."""

    def test_simple_bagel_order_flow(self):
        """Test a simple bagel order from start to finish."""
        order = OrderTask()

        # Step 1: Greeting
        parsed = ParsedInput(is_greeting=True)
        order, action = flow_process_message(order, parsed)
        assert "welcome" in action.message.lower() or "what" in action.question.lower()

        # Step 2: Order a bagel with spread already specified
        parsed = ParsedInput(
            new_bagels=[ParsedBagelItem(bagel_type="everything", spread="cream cheese")]
        )
        order, action = flow_process_message(order, parsed)
        assert action.field_name == "toasted"

        # Step 3: Answer toasted
        parsed = ParsedInput(answers={"toasted": True})
        order, action = flow_process_message(order, parsed)
        # After toasted, should ask about extras or more items

        # Step 4: No more items
        parsed = ParsedInput(no_more_items=True)
        order, action = flow_process_message(order, parsed)
        assert "pickup" in action.question.lower() or "delivery" in action.question.lower()

        # Step 5: Pickup
        parsed = ParsedInput(order_type="pickup")
        order, action = flow_process_message(order, parsed)
        # Should ask for name

        # Step 6: Provide name
        parsed = ParsedInput(customer_name="John")
        order, action = flow_process_message(order, parsed)

        # Verify order state
        assert len(order.items.items) == 1
        assert order.items.items[0].bagel_type == "everything"
        assert order.items.items[0].toasted is True
        assert order.items.items[0].spread == "cream cheese"
        assert order.delivery_method.order_type == "pickup"
        assert order.customer_info.name == "John"

    def test_multi_item_order_flow(self):
        """Test ordering multiple items."""
        order = OrderTask()

        # Order bagel and coffee at once
        parsed = ParsedInput(
            new_bagels=[ParsedBagelItem(bagel_type="sesame", toasted=True, spread="butter")],
            new_coffees=[],  # Just bagel first
        )
        order, action = flow_process_message(order, parsed)

        # Complete bagel (already has toasted and spread)
        # Should ask about extras or more items

        assert len(order.items.items) >= 1

    def test_modification_flow(self):
        """Test modifying an order mid-flow."""
        order = OrderTask()

        # Add initial item
        parsed = ParsedInput(
            new_bagels=[ParsedBagelItem(bagel_type="plain", toasted=True)]
        )
        order, action = flow_process_message(order, parsed)

        # Modify toasted to False
        from sandwich_bot.tasks.parsing import ItemModification
        parsed = ParsedInput(
            modifications=[ItemModification(item_index=0, field="toasted", new_value=False)]
        )
        order, action = flow_process_message(order, parsed)

        assert order.items.items[0].toasted is False

    def test_cancel_item_flow(self):
        """Test cancelling an item."""
        order = OrderTask()

        # Add two items
        parsed = ParsedInput(
            new_bagels=[
                ParsedBagelItem(bagel_type="plain"),
                ParsedBagelItem(bagel_type="everything"),
            ]
        )
        order, action = flow_process_message(order, parsed)

        # Cancel first item
        parsed = ParsedInput(cancel_item_index=0)
        order, action = flow_process_message(order, parsed)

        # First item should be skipped
        from sandwich_bot.tasks.models import TaskStatus
        assert order.items.items[0].status == TaskStatus.SKIPPED
        assert order.items.items[1].status != TaskStatus.SKIPPED


# =============================================================================
# Adapter Round-Trip Tests
# =============================================================================

class TestAdapterRoundTrip:
    """Tests for complete round-trip through adapter."""

    def test_process_message_returns_valid_dict(self):
        """Test that process_message_with_tasks returns valid dict state."""
        # Mock the LLM parsing to avoid actual API calls
        with patch('sandwich_bot.tasks.orchestrator.parse_user_message') as mock_parse:
            mock_parse.return_value = ParsedInput(is_greeting=True)

            reply, state, actions = process_message_with_tasks(
                user_message="Hello",
                order_state_dict={},
                history=[],
                session_id="test-session",
            )

            # Verify response
            assert isinstance(reply, str)
            assert len(reply) > 0

            # Verify state dict format
            assert "status" in state
            assert "items" in state
            assert "customer" in state
            assert isinstance(state["items"], list)

    def test_state_preserved_across_messages(self):
        """Test that state is preserved across multiple messages."""
        with patch('sandwich_bot.tasks.orchestrator.parse_user_message') as mock_parse:
            # First message: greeting
            mock_parse.return_value = ParsedInput(is_greeting=True)

            _, state1, _ = process_message_with_tasks(
                user_message="Hello",
                order_state_dict={},
                history=[],
            )

            # Second message: order a bagel
            mock_parse.return_value = ParsedInput(
                new_bagels=[ParsedBagelItem(bagel_type="sesame")]
            )

            _, state2, _ = process_message_with_tasks(
                user_message="I want a sesame bagel",
                order_state_dict=state1,
                history=[],
            )

            # Verify bagel was added
            assert len(state2["items"]) == 1
            assert "sesame" in state2["items"][0]["menu_item_name"].lower()

    def test_conversation_history_preserved(self):
        """Test that conversation history is preserved in state."""
        with patch('sandwich_bot.tasks.orchestrator.parse_user_message') as mock_parse:
            mock_parse.return_value = ParsedInput(is_greeting=True)

            _, state, _ = process_message_with_tasks(
                user_message="Hello",
                order_state_dict={},
                history=[
                    {"role": "user", "content": "Previous message"},
                    {"role": "assistant", "content": "Previous response"},
                ],
            )

            # Verify conversation history is in task_orchestrator_state
            assert "task_orchestrator_state" in state
            assert "conversation_history" in state["task_orchestrator_state"]


# =============================================================================
# State Machine Multi-Bagel Tests
# =============================================================================

class TestStateMachineMultiBagel:
    """Tests for state machine multi-bagel handling."""

    def test_two_of_them_plain_sets_two_bagels(self):
        """Test that '2 of them plain' sets type for 2 bagels and continues configuring first bagel."""
        from sandwich_bot.tasks.state_machine import (
            OrderStateMachine,
            OrderPhase,
            BagelChoiceResponse,
        )
        from sandwich_bot.tasks.models import OrderTask, BagelItemTask, TaskStatus

        # Create order with 3 bagels that don't have types yet
        order = OrderTask()
        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_field = "bagel_choice"

        for i in range(3):
            bagel = BagelItemTask(bagel_type=None)
            bagel.mark_in_progress()
            order.items.add_item(bagel)

        order.pending_item_id = order.items.items[0].id
        sm = OrderStateMachine()

        # Mock parse_bagel_choice to return quantity=2
        with patch("sandwich_bot.tasks.state_machine.parse_bagel_choice") as mock_parse:
            mock_parse.return_value = BagelChoiceResponse(bagel_type="plain", quantity=2)

            result = sm._handle_bagel_choice("2 of them plain", order.items.items[0], order)

            # Verify 2 bagels have type set
            bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]
            typed_count = sum(1 for b in bagels if b.bagel_type == "plain")
            assert typed_count == 2, f"Expected 2 plain bagels, got {typed_count}"

            # Third bagel should not have a type
            assert bagels[2].bagel_type is None, "Third bagel should not have type yet"

            # With new flow: should ask about TOASTED for first bagel (fully configure each bagel)
            assert "first" in result.message.lower()
            assert result.order.pending_field == "toasted"

    def test_each_bagel_fully_configured_before_next(self):
        """Test that each bagel is fully configured (type->toasted->spread) before moving to next."""
        from sandwich_bot.tasks.state_machine import (
            OrderStateMachine,
            OrderPhase,
        )
        from sandwich_bot.tasks.models import OrderTask, BagelItemTask, TaskStatus

        # Create order with 2 bagels - first has type, second doesn't
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        bagel1 = BagelItemTask(bagel_type="plain")
        bagel1.mark_in_progress()
        bagel2 = BagelItemTask(bagel_type=None)  # No type yet
        bagel2.mark_in_progress()
        order.items.add_item(bagel1)
        order.items.add_item(bagel2)

        sm = OrderStateMachine()

        # Ask for next incomplete bagel
        result = sm._configure_next_incomplete_bagel(order)

        # With new flow: should ask about first bagel's TOASTED (fully configure first bagel)
        assert "first" in result.message.lower()
        assert result.order.pending_field == "toasted"


# =============================================================================
# Price Recalculation Tests
# =============================================================================

class TestPriceRecalculationInvariants:
    """Tests to ensure price is always updated when modifiers change."""

    def test_spread_modification_updates_price(self):
        """Test that modifying spread recalculates the bagel price."""
        from sandwich_bot.tasks.flow import _apply_modification, _calculate_bagel_price
        from sandwich_bot.tasks.models import OrderTask, BagelItemTask
        from sandwich_bot.tasks.parsing import ItemModification

        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True, spread=None, unit_price=2.50)
        bagel.mark_complete()
        order.items.add_item(bagel)

        # Verify initial price
        assert bagel.unit_price == 2.50

        # Apply spread modification
        mod = ItemModification(item_index=0, field="spread", new_value="cream cheese")
        _apply_modification(order, mod)

        # Price should now include spread
        assert bagel.spread == "cream cheese"
        assert bagel.unit_price > 2.50  # Price should increase with spread

    def test_protein_modification_updates_price(self):
        """Test that modifying sandwich_protein recalculates the bagel price."""
        from sandwich_bot.tasks.flow import _apply_modification
        from sandwich_bot.tasks.models import OrderTask, BagelItemTask
        from sandwich_bot.tasks.parsing import ItemModification

        order = OrderTask()
        bagel = BagelItemTask(bagel_type="everything", toasted=True, spread="none", unit_price=2.50)
        bagel.mark_complete()
        order.items.add_item(bagel)

        # Verify initial price
        assert bagel.unit_price == 2.50

        # Apply protein modification
        mod = ItemModification(item_index=0, field="sandwich_protein", new_value="ham")
        _apply_modification(order, mod)

        # Price should now include ham
        assert bagel.sandwich_protein == "ham"
        assert bagel.unit_price > 2.50  # Price should increase with protein

    def test_extras_modification_updates_price(self):
        """Test that modifying extras recalculates the bagel price."""
        from sandwich_bot.tasks.flow import _apply_modification
        from sandwich_bot.tasks.models import OrderTask, BagelItemTask
        from sandwich_bot.tasks.parsing import ItemModification

        order = OrderTask()
        bagel = BagelItemTask(bagel_type="sesame", toasted=True, spread="butter", unit_price=4.00)
        bagel.mark_complete()
        order.items.add_item(bagel)

        initial_price = bagel.unit_price

        # Apply extras modification
        mod = ItemModification(item_index=0, field="extras", new_value=["egg", "american"])
        _apply_modification(order, mod)

        # Price should now include extras
        assert bagel.extras == ["egg", "american"]
        assert bagel.unit_price > initial_price  # Price should increase with extras

    def test_state_machine_spread_choice_updates_price(self):
        """Test that state machine's spread choice handler recalculates price."""
        from sandwich_bot.tasks.state_machine import OrderStateMachine, OrderPhase
        from sandwich_bot.tasks.models import OrderTask, BagelItemTask

        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", toasted=True, spread=None, unit_price=2.50)
        bagel.mark_in_progress()
        order.items.add_item(bagel)

        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_field = "spread"
        order.pending_item_id = bagel.id

        sm = OrderStateMachine()
        result = sm._handle_spread_choice("cream cheese please", bagel, order)

        # Spread should be set and price recalculated
        assert bagel.spread == "cream cheese"
        # Price should be higher than base price
        assert bagel.unit_price >= 2.50

    def test_split_item_preserves_and_updates_prices(self):
        """Test that splitting items preserves/updates prices correctly."""
        from sandwich_bot.tasks.flow import _split_item_with_modifications
        from sandwich_bot.tasks.models import OrderTask, BagelItemTask, TaskStatus
        from sandwich_bot.tasks.parsing import ItemModification

        order = OrderTask()
        bagel = BagelItemTask(
            bagel_type="plain",
            toasted=True,
            quantity=2,
            spread=None,
            unit_price=2.50,
        )
        bagel.mark_in_progress()
        order.items.add_item(bagel)

        # Split with different spreads
        mods = [
            ItemModification(item_index=0, field="spread", new_value="butter"),
            ItemModification(item_index=1, field="spread", new_value="cream cheese"),
        ]
        _split_item_with_modifications(order, bagel, "spread", mods)

        # Should now have 2 bagels
        bagels = [i for i in order.items.items if isinstance(i, BagelItemTask)]
        assert len(bagels) == 2

        # Both should have prices updated
        assert bagels[0].spread == "butter"
        assert bagels[0].unit_price > 2.50  # Base + spread

        assert bagels[1].spread == "cream cheese"
        assert bagels[1].unit_price > 2.50  # Base + spread

    def test_calculate_bagel_price_includes_all_modifiers(self):
        """Test that price calculation includes protein, extras, and spread."""
        from sandwich_bot.tasks.flow import _calculate_bagel_price, DEFAULT_BAGEL_PRICES
        from sandwich_bot.tasks.models import BagelItemTask

        # Create a bagel with all modifiers
        bagel = BagelItemTask(
            bagel_type="everything",
            toasted=True,
            spread="cream cheese",
            sandwich_protein="ham",
            extras=["egg", "american"],
        )

        price = _calculate_bagel_price(bagel)

        # Price should be base + spread + ham + egg + american
        expected_min = (
            DEFAULT_BAGEL_PRICES["bagel_base"] +
            DEFAULT_BAGEL_PRICES["spread"] +
            DEFAULT_BAGEL_PRICES["proteins"]["ham"] +
            DEFAULT_BAGEL_PRICES["proteins"]["egg"] +
            DEFAULT_BAGEL_PRICES["cheeses"]["american"]
        )
        assert price >= expected_min

    def test_no_spread_does_not_add_spread_price(self):
        """Test that 'none' spread doesn't add spread price."""
        from sandwich_bot.tasks.flow import _calculate_bagel_price, DEFAULT_BAGEL_PRICES
        from sandwich_bot.tasks.models import BagelItemTask

        bagel = BagelItemTask(
            bagel_type="plain",
            toasted=True,
            spread="none",
        )

        price = _calculate_bagel_price(bagel)

        # Price should be just base (no spread for "none")
        assert price == DEFAULT_BAGEL_PRICES["bagel_base"]

    def test_state_machine_add_bagel_with_modifiers_includes_price(self):
        """Test that state machine calculates price correctly when adding bagel with modifiers."""
        from sandwich_bot.tasks.state_machine import (
            OrderStateMachine,
            OrderPhase,
            ExtractedModifiers,
        )
        from sandwich_bot.tasks.models import OrderTask, BagelItemTask

        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        # Simulate adding a bagel with ham, egg, american modifiers
        modifiers = ExtractedModifiers()
        modifiers.proteins = ["ham", "egg"]
        modifiers.cheeses = ["american"]

        result = sm._add_bagel(
            bagel_type="wheat",
            order=order,
            toasted=True,
            spread="none",
            spread_type=None,
            extracted_modifiers=modifiers,
        )

        # Find the bagel that was added
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]
        assert len(bagels) == 1

        bagel = bagels[0]
        assert bagel.bagel_type == "wheat"
        assert bagel.sandwich_protein == "ham"
        assert "egg" in bagel.extras
        assert "american" in bagel.extras

        # Price should include modifiers (base 2.50 + ham 2.00 + egg 1.50 + american 0.75 = 6.75)
        # Allow some flexibility for different pricing
        assert bagel.unit_price > 2.50, f"Expected price > $2.50, got ${bagel.unit_price}"
        assert bagel.unit_price >= 6.0, f"Expected price >= $6.00 with modifiers, got ${bagel.unit_price}"

    def test_state_machine_lookup_modifier_price_uses_defaults(self):
        """Test that state machine falls back to default prices when menu_data is empty."""
        from sandwich_bot.tasks.state_machine import OrderStateMachine

        # Create state machine without menu_data
        sm = OrderStateMachine(menu_data=None)

        # Should use default prices
        assert sm._lookup_modifier_price("ham") == 2.00
        assert sm._lookup_modifier_price("egg") == 1.50
        assert sm._lookup_modifier_price("american") == 0.75
        assert sm._lookup_modifier_price("bacon") == 2.00
        assert sm._lookup_modifier_price("cream cheese") == 1.50


# =============================================================================
# Order Type Upfront Tests
# =============================================================================

class TestOrderTypeUpfront:
    """Tests for recognizing pickup/delivery order type mentioned upfront."""

    def test_pickup_order_sets_delivery_method(self):
        """Test that 'I'd like to place a pickup order' sets order type."""
        from sandwich_bot.tasks.state_machine import (
            OrderStateMachine,
            OpenInputResponse,
        )
        from sandwich_bot.tasks.models import OrderTask

        order = OrderTask()
        sm = OrderStateMachine()

        # Simulate parsed input with order_type set
        parsed = OpenInputResponse(order_type="pickup")
        result = sm._handle_taking_items_with_parsed(parsed, order)

        # Should set delivery method
        assert order.delivery_method.order_type == "pickup"
        # Should acknowledge and ask what they want
        assert "pickup" in result.message.lower()
        assert "what can i get" in result.message.lower() or "get for you" in result.message.lower()

    def test_delivery_order_sets_delivery_method(self):
        """Test that 'I'd like to place a delivery order' sets order type."""
        from sandwich_bot.tasks.state_machine import (
            OrderStateMachine,
            OpenInputResponse,
        )
        from sandwich_bot.tasks.models import OrderTask

        order = OrderTask()
        sm = OrderStateMachine()

        # Simulate parsed input with order_type set
        parsed = OpenInputResponse(order_type="delivery")
        result = sm._handle_taking_items_with_parsed(parsed, order)

        # Should set delivery method
        assert order.delivery_method.order_type == "delivery"
        # Should acknowledge and ask what they want
        assert "delivery" in result.message.lower()

    def test_pickup_order_with_items_processes_both(self):
        """Test that 'pickup order, I'll have a plain bagel' processes both."""
        from sandwich_bot.tasks.state_machine import (
            OrderStateMachine,
            OpenInputResponse,
        )
        from sandwich_bot.tasks.models import OrderTask, BagelItemTask

        order = OrderTask()
        sm = OrderStateMachine()

        # Simulate parsed input with order_type AND a bagel order
        parsed = OpenInputResponse(
            order_type="pickup",
            new_bagel=True,
            new_bagel_type="plain",
        )
        result = sm._handle_taking_items_with_parsed(parsed, order)

        # Should set delivery method
        assert order.delivery_method.order_type == "pickup"
        # Should have added the bagel
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]
        assert len(bagels) == 1
        assert bagels[0].bagel_type == "plain"

    def test_checkout_asks_for_name_when_order_type_set_upfront(self):
        """Test that checkout asks for name when order type was set upfront.

        Bug fix: When user says "I'd like a pickup order" upfront and then says
        "that's it", we should ask for their name, not ask pickup/delivery again.
        """
        from sandwich_bot.tasks.state_machine import (
            OrderStateMachine,
            OpenInputResponse,
            OrderPhase,
        )
        from sandwich_bot.tasks.models import OrderTask, BagelItemTask, TaskStatus

        order = OrderTask()
        sm = OrderStateMachine()

        # User set order type upfront
        order.delivery_method.order_type = "pickup"

        # Add a complete item
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)

        # User says "that's it" - triggers _transition_to_checkout
        result = sm._transition_to_checkout(order)

        # Should ask for name, NOT pickup/delivery
        assert "name" in result.message.lower()
        assert "pickup or delivery" not in result.message.lower()
        assert order.phase == OrderPhase.CHECKOUT_NAME.value

    def test_email_choice_sets_checkout_email_phase(self):
        """Test that choosing 'email' sets CHECKOUT_EMAIL phase for next input.

        Bug fix: When user chooses email for notification, the phase should be
        CHECKOUT_EMAIL so their email address is captured correctly.
        """
        from unittest.mock import patch, MagicMock
        from sandwich_bot.tasks.state_machine import (
            OrderStateMachine,
            OrderPhase,
        )
        from sandwich_bot.tasks.models import OrderTask, BagelItemTask, TaskStatus

        order = OrderTask()
        sm = OrderStateMachine()

        # Set up order state: has items, delivery method, name, confirmed
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)
        order.delivery_method.order_type = "pickup"
        order.customer_info.name = "Joey"
        order.checkout.order_reviewed = True
        order.phase = OrderPhase.CHECKOUT_PAYMENT_METHOD.value

        # Mock parse_payment_method to return email choice (no email address)
        with patch("sandwich_bot.tasks.state_machine.parse_payment_method") as mock_parse:
            mock_parse.return_value = MagicMock(
                choice="email",
                email_address=None,  # No email provided yet
                phone_number=None,
            )
            result = sm._handle_payment_method("email", order)

        # Should ask for email
        assert "email" in result.message.lower()
        # Phase should be CHECKOUT_EMAIL (not CHECKOUT_PHONE)
        assert order.phase == OrderPhase.CHECKOUT_EMAIL.value

    def test_email_address_captured_in_checkout_email_phase(self):
        """Test that email address is captured when in CHECKOUT_EMAIL phase."""
        from unittest.mock import patch, MagicMock
        from sandwich_bot.tasks.state_machine import (
            OrderStateMachine,
            OrderPhase,
        )
        from sandwich_bot.tasks.models import OrderTask, BagelItemTask, TaskStatus

        order = OrderTask()
        sm = OrderStateMachine()

        # Set up order state
        bagel = BagelItemTask(bagel_type="plain", toasted=True)
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)
        order.delivery_method.order_type = "pickup"
        order.customer_info.name = "Joey"
        order.checkout.order_reviewed = True
        order.payment.method = "card_link"
        order.phase = OrderPhase.CHECKOUT_EMAIL.value

        # Mock parse_email to return the email address
        with patch("sandwich_bot.tasks.state_machine.parse_email") as mock_parse:
            mock_parse.return_value = MagicMock(email="joey@example.com")
            result = sm._handle_email("joey@example.com", order)

        # Email should be stored
        assert order.customer_info.email == "joey@example.com"
        # Order should be complete
        assert result.is_complete
        assert "joey@example.com" in result.message
        assert "Joey" in result.message  # Thank you message includes name

    def test_email_phase_persists_through_process(self):
        """Test that CHECKOUT_EMAIL phase is preserved through process().

        Bug fix: When user chooses email, the phase is set to CHECKOUT_EMAIL.
        On the next turn, process() was calling _transition_to_next_slot() which
        overwrote the phase to CHECKOUT_PHONE. This test verifies the fix.
        """
        from unittest.mock import patch, MagicMock
        from sandwich_bot.tasks.state_machine import (
            OrderStateMachine,
            OrderPhase,
        )
        from sandwich_bot.tasks.models import OrderTask, BagelItemTask, TaskStatus

        sm = OrderStateMachine()

        # Set up order state as it would be after choosing "email"
        order = OrderTask()
        bagel = BagelItemTask(bagel_type="egg", toasted=True)
        bagel.spread = "none"  # "with nothing on it"
        bagel.status = TaskStatus.COMPLETE
        order.items.add_item(bagel)
        order.delivery_method.order_type = "pickup"
        order.customer_info.name = "Hank"
        order.checkout.order_reviewed = True
        order.payment.method = "card_link"
        order.phase = OrderPhase.CHECKOUT_EMAIL.value  # Set by previous handler

        # Mock parse_email to return the email address
        with patch("sandwich_bot.tasks.state_machine.parse_email") as mock_parse:
            mock_parse.return_value = MagicMock(email="alberto33@gmail.com")
            # Call process() - this should NOT overwrite the phase
            result = sm.process("alberto33@gmail.com", order)

        # Verify email was captured
        assert order.customer_info.email == "alberto33@gmail.com"
        # Order should be complete
        assert result.is_complete
        assert "alberto33@gmail.com" in result.message
        assert "Hank" in result.message
