"""
Unit tests for the chains adapter layer.

Tests state conversion between dict and Pydantic formats,
and the integration with the orchestrator.
"""

import os
import pytest

from sandwich_bot.chains import (
    OrderState,
    ChainName,
    OrderStatus,
    BagelItem,
    CoffeeItem,
)
from sandwich_bot.chains.adapter import (
    is_chain_orchestrator_enabled,
    dict_to_order_state,
    order_state_to_dict,
    process_message_with_chains,
    _infer_current_chain,
    _infer_actions_from_result,
)


class TestFeatureFlag:
    """Tests for the feature flag functionality."""

    def test_flag_enabled_by_default(self, monkeypatch):
        """Test that the flag is enabled by default."""
        monkeypatch.delenv("CHAIN_ORCHESTRATOR_ENABLED", raising=False)
        assert is_chain_orchestrator_enabled() is True

    def test_flag_explicitly_false(self, monkeypatch):
        """Test explicit false setting."""
        monkeypatch.setenv("CHAIN_ORCHESTRATOR_ENABLED", "false")
        assert is_chain_orchestrator_enabled() is False

    def test_flag_explicitly_true(self, monkeypatch):
        """Test explicit true setting."""
        monkeypatch.setenv("CHAIN_ORCHESTRATOR_ENABLED", "true")
        assert is_chain_orchestrator_enabled() is True

    def test_flag_percentage_always(self, monkeypatch):
        """Test 100% rollout."""
        monkeypatch.setenv("CHAIN_ORCHESTRATOR_ENABLED", "100")
        # Should always be true with 100%
        assert is_chain_orchestrator_enabled() is True

    def test_flag_percentage_never(self, monkeypatch):
        """Test 0% rollout."""
        monkeypatch.setenv("CHAIN_ORCHESTRATOR_ENABLED", "0")
        assert is_chain_orchestrator_enabled() is False


class TestDictToOrderState:
    """Tests for converting dict state to Pydantic OrderState."""

    def test_empty_dict(self):
        """Test converting empty dict."""
        state = dict_to_order_state({})
        assert isinstance(state, OrderState)
        assert state.current_chain == ChainName.GREETING
        assert state.status == OrderStatus.IN_PROGRESS

    def test_with_session_id(self):
        """Test preserving session ID."""
        state = dict_to_order_state({}, session_id="test-123")
        assert state.session_id == "test-123"

    def test_customer_info(self):
        """Test converting customer info."""
        order_dict = {
            "customer": {
                "name": "John Doe",
                "phone": "555-1234",
                "email": "john@example.com",
            }
        }
        state = dict_to_order_state(order_dict)

        assert state.customer_name == "John Doe"
        assert state.customer_phone == "555-1234"
        assert state.customer_email == "john@example.com"

    def test_order_type_pickup(self):
        """Test pickup order type conversion."""
        order_dict = {"order_type": "pickup"}
        state = dict_to_order_state(order_dict)

        assert state.address.order_type == "pickup"
        assert state.address.store_location_confirmed is True

    def test_order_type_delivery(self):
        """Test delivery order type conversion."""
        order_dict = {
            "order_type": "delivery",
            "delivery_address": "123 Main St",
        }
        state = dict_to_order_state(order_dict)

        assert state.address.order_type == "delivery"
        assert state.address.street == "123 Main St"

    def test_sandwich_items(self):
        """Test converting sandwich items to bagel items."""
        order_dict = {
            "items": [
                {
                    "item_type": "sandwich",
                    "menu_item_name": "Everything Bagel",
                    "bread": "everything bagel",
                    "cheese": "cream cheese",
                    "toasted": True,
                    "quantity": 2,
                    "unit_price": 4.50,
                }
            ]
        }
        state = dict_to_order_state(order_dict)

        assert len(state.bagels.items) == 1
        bagel = state.bagels.items[0]
        assert bagel.bagel_type == "everything bagel"
        assert bagel.spread == "cream cheese"
        assert bagel.toasted is True
        assert bagel.quantity == 2
        assert bagel.unit_price == 4.50

    def test_drink_items(self):
        """Test converting drink items to coffee items."""
        order_dict = {
            "items": [
                {
                    "item_type": "drink",
                    "menu_item_name": "Iced Latte",
                    "size": "large",
                    "item_config": {
                        "milk": "oat",
                        "sweetener": "vanilla",
                    },
                    "unit_price": 5.75,
                }
            ]
        }
        state = dict_to_order_state(order_dict)

        assert len(state.coffee.items) == 1
        coffee = state.coffee.items[0]
        assert coffee.drink_type == "Iced Latte"
        assert coffee.size == "large"
        assert coffee.milk == "oat"
        assert coffee.sweetener == "vanilla"
        assert coffee.iced is True  # "Iced" in name

    def test_confirmed_status(self):
        """Test confirmed order status conversion."""
        order_dict = {"status": "confirmed"}
        state = dict_to_order_state(order_dict)

        assert state.status == OrderStatus.CONFIRMED


class TestOrderStateToDict:
    """Tests for converting Pydantic OrderState to dict."""

    def test_empty_state(self):
        """Test converting empty state."""
        state = OrderState()
        order_dict = order_state_to_dict(state)

        assert order_dict["status"] == "pending"
        assert order_dict["items"] == []
        assert order_dict["customer"]["name"] is None

    def test_customer_info(self):
        """Test converting customer info."""
        state = OrderState(
            customer_name="Jane Doe",
            customer_phone="555-5678",
            customer_email="jane@example.com",
        )
        order_dict = order_state_to_dict(state)

        assert order_dict["customer"]["name"] == "Jane Doe"
        assert order_dict["customer"]["phone"] == "555-5678"
        assert order_dict["customer"]["email"] == "jane@example.com"

    def test_bagel_items(self):
        """Test converting bagel items."""
        state = OrderState()
        state.bagels.items.append(
            BagelItem(
                bagel_type="plain bagel",
                quantity=1,
                toasted=True,
                spread="butter",
                unit_price=3.50,
            )
        )
        order_dict = order_state_to_dict(state)

        assert len(order_dict["items"]) == 1
        item = order_dict["items"][0]
        assert item["item_type"] == "sandwich"
        assert item["menu_item_name"] == "plain bagel"
        assert item["toasted"] is True
        assert item["cheese"] == "butter"  # spread maps to cheese
        assert item["unit_price"] == 3.50

    def test_coffee_items(self):
        """Test converting coffee items."""
        state = OrderState()
        state.coffee.items.append(
            CoffeeItem(
                drink_type="latte",
                size="medium",
                milk="almond",
                iced=True,
                unit_price=4.50,
            )
        )
        order_dict = order_state_to_dict(state)

        assert len(order_dict["items"]) == 1
        item = order_dict["items"][0]
        assert item["item_type"] == "drink"
        assert item["menu_item_name"] == "latte"
        assert item["size"] == "medium"
        assert item["item_config"]["milk"] == "almond"
        assert item["item_config"]["style"] == "iced"

    def test_delivery_address(self):
        """Test delivery address conversion."""
        state = OrderState()
        state.address.order_type = "delivery"
        state.address.street = "456 Oak Ave"
        state.address.city = "Brooklyn"
        state.address.state = "NY"
        state.address.zip_code = "11201"

        order_dict = order_state_to_dict(state)

        assert order_dict["order_type"] == "delivery"
        assert "456 Oak Ave" in order_dict["delivery_address"]

    def test_confirmed_status(self):
        """Test confirmed status conversion."""
        state = OrderState()
        state.status = OrderStatus.CONFIRMED

        order_dict = order_state_to_dict(state)
        assert order_dict["status"] == "confirmed"


class TestInferCurrentChain:
    """Tests for chain inference from order state."""

    def test_pending_no_type(self):
        """Test that pending orders without type are in greeting."""
        order_dict = {"status": "pending"}
        chain = _infer_current_chain(order_dict)
        assert chain == ChainName.GREETING

    def test_with_order_type_no_items(self):
        """Test that orders with type but no items are in bagel chain."""
        order_dict = {"status": "pending", "order_type": "pickup"}
        chain = _infer_current_chain(order_dict)
        assert chain == ChainName.BAGEL

    def test_with_items(self):
        """Test that orders with items stay in bagel chain."""
        order_dict = {"status": "collecting_items", "items": [{"menu_item_name": "bagel"}]}
        chain = _infer_current_chain(order_dict)
        assert chain == ChainName.BAGEL

    def test_confirmed(self):
        """Test that confirmed orders are in checkout."""
        order_dict = {"status": "confirmed"}
        chain = _infer_current_chain(order_dict)
        assert chain == ChainName.CHECKOUT


class TestInferActions:
    """Tests for action inference from state changes."""

    def test_no_changes(self):
        """Test when no changes occurred."""
        old_state = {"items": []}
        new_state = {"items": []}
        result = type("ChainResult", (), {"state": OrderState()})()

        actions = _infer_actions_from_result(old_state, new_state, result)

        # Should have conversation action
        assert len(actions) == 1
        assert actions[0]["intent"] == "conversation"

    def test_item_added(self):
        """Test detecting added items."""
        old_state = {"items": []}
        new_state = {
            "items": [{"item_type": "sandwich", "menu_item_name": "Everything Bagel"}]
        }
        result = type("ChainResult", (), {"state": OrderState()})()

        actions = _infer_actions_from_result(old_state, new_state, result)

        assert any(a["intent"] == "add_sandwich" for a in actions)

    def test_drink_added(self):
        """Test detecting added drinks."""
        old_state = {"items": []}
        new_state = {
            "items": [{"item_type": "drink", "menu_item_name": "Latte"}]
        }
        result = type("ChainResult", (), {"state": OrderState()})()

        actions = _infer_actions_from_result(old_state, new_state, result)

        assert any(a["intent"] == "add_drink" for a in actions)

    def test_order_type_changed(self):
        """Test detecting order type change."""
        old_state = {"items": []}
        new_state = {"items": [], "order_type": "delivery"}
        result = type("ChainResult", (), {"state": OrderState()})()

        actions = _infer_actions_from_result(old_state, new_state, result)

        assert any(a["intent"] == "set_order_type" for a in actions)

    def test_order_confirmed(self):
        """Test detecting order confirmation."""
        old_state = {"items": [], "status": "pending"}
        new_state = {"items": [], "status": "confirmed"}
        result = type("ChainResult", (), {"state": OrderState()})()

        actions = _infer_actions_from_result(old_state, new_state, result)

        assert any(a["intent"] == "confirm_order" for a in actions)


class TestBagelChainStateRoundtrip:
    """Tests for bagel chain state serialization roundtrip."""

    def test_bagel_current_item_preserved(self):
        """Test that current bagel item is preserved through roundtrip."""
        state = OrderState()
        state.bagels.current_item = BagelItem(
            bagel_type="everything",
            toasted=True,
            unit_price=2.50,
        )
        state.bagels.awaiting = "spread"

        order_dict = order_state_to_dict(state)
        restored = dict_to_order_state(order_dict)

        assert restored.bagels.current_item is not None
        assert restored.bagels.current_item.bagel_type == "everything"
        assert restored.bagels.current_item.toasted is True
        assert restored.bagels.awaiting == "spread"

    def test_bagel_awaiting_preserved(self):
        """Test that bagel awaiting field is preserved."""
        state = OrderState()
        state.bagels.awaiting = "toasted"

        order_dict = order_state_to_dict(state)
        restored = dict_to_order_state(order_dict)

        assert restored.bagels.awaiting == "toasted"


class TestCoffeeChainStateRoundtrip:
    """Tests for coffee chain state serialization roundtrip."""

    def test_coffee_current_item_preserved(self):
        """Test that current coffee item is preserved through roundtrip."""
        state = OrderState()
        state.coffee.current_item = CoffeeItem(
            drink_type="latte",
            size="large",
            iced=True,
            unit_price=5.50,
        )
        state.coffee.awaiting = "milk"

        order_dict = order_state_to_dict(state)
        restored = dict_to_order_state(order_dict)

        assert restored.coffee.current_item is not None
        assert restored.coffee.current_item.drink_type == "latte"
        assert restored.coffee.current_item.size == "large"
        assert restored.coffee.current_item.iced is True
        assert restored.coffee.awaiting == "milk"


class TestCheckoutStateRoundtrip:
    """Tests for checkout state serialization roundtrip."""

    def test_checkout_awaiting_preserved(self):
        """Test that checkout awaiting field is preserved through roundtrip."""
        state = OrderState()
        state.checkout.awaiting = "name"
        state.checkout.order_reviewed = True

        # Convert to dict and back
        order_dict = order_state_to_dict(state)
        restored = dict_to_order_state(order_dict)

        assert restored.checkout.awaiting == "name"
        assert restored.checkout.order_reviewed is True

    def test_checkout_name_collected_preserved(self):
        """Test that name_collected field is preserved."""
        state = OrderState()
        state.checkout.name_collected = True
        state.checkout.contact_collected = True
        state.checkout.awaiting = "contact"

        order_dict = order_state_to_dict(state)
        restored = dict_to_order_state(order_dict)

        assert restored.checkout.name_collected is True
        assert restored.checkout.contact_collected is True
        assert restored.checkout.awaiting == "contact"

    def test_checkout_totals_preserved(self):
        """Test that checkout totals are preserved."""
        state = OrderState()
        state.checkout.subtotal = 15.50
        state.checkout.tax = 1.28
        state.checkout.delivery_fee = 2.99
        state.checkout.total = 19.77
        state.checkout.total_calculated = True

        order_dict = order_state_to_dict(state)
        restored = dict_to_order_state(order_dict)

        assert restored.checkout.subtotal == 15.50
        assert restored.checkout.tax == 1.28
        assert restored.checkout.delivery_fee == 2.99
        assert restored.checkout.total == 19.77
        assert restored.checkout.total_calculated is True

    def test_current_chain_preserved(self):
        """Test that current chain is preserved through roundtrip."""
        state = OrderState()
        state.current_chain = ChainName.CHECKOUT

        order_dict = order_state_to_dict(state)
        restored = dict_to_order_state(order_dict)

        assert restored.current_chain == ChainName.CHECKOUT

    def test_infer_chain_from_checkout_state(self):
        """Test that chain is inferred from checkout state when order_reviewed is True."""
        order_dict = {
            "status": "pending",
            "order_type": "pickup",
            "items": [{"item_type": "sandwich", "menu_item_name": "bagel"}],
            "checkout_state": {
                "order_reviewed": True,
                "awaiting": "name",
            },
        }

        chain = _infer_current_chain(order_dict)
        assert chain == ChainName.CHECKOUT


class TestProcessMessageWithChains:
    """Tests for the main processing function."""

    def test_greeting_flow(self):
        """Test processing a greeting message."""
        order_dict = {
            "status": "pending",
            "items": [],
            "customer": {},
        }

        reply, new_state, actions = process_message_with_chains(
            user_message="Hello",
            order_state_dict=order_dict,
            history=[],
            session_id="test-session",
        )

        assert reply  # Got a reply
        assert isinstance(new_state, dict)
        assert isinstance(actions, list)

    def test_pickup_selection(self):
        """Test processing pickup selection."""
        order_dict = {
            "status": "pending",
            "items": [],
            "customer": {},
        }

        reply, new_state, actions = process_message_with_chains(
            user_message="pickup please",
            order_state_dict=order_dict,
            history=[],
            session_id="test-session",
        )

        assert new_state.get("order_type") == "pickup"

    def test_bagel_order(self):
        """Test processing a bagel order."""
        order_dict = {
            "status": "pending",
            "order_type": "pickup",
            "items": [],
            "customer": {},
        }

        reply, new_state, actions = process_message_with_chains(
            user_message="everything bagel please",
            order_state_dict=order_dict,
            history=[],
            session_id="test-session",
        )

        # Should have started a bagel order
        assert reply  # Got a reply asking follow-up questions


class TestRoundTrip:
    """Tests for round-trip conversion (dict -> Pydantic -> dict)."""

    def test_empty_roundtrip(self):
        """Test round-trip with empty state."""
        original = {
            "status": "pending",
            "items": [],
            "customer": {"name": None, "phone": None, "email": None},
        }

        pydantic_state = dict_to_order_state(original)
        result = order_state_to_dict(pydantic_state)

        assert result["status"] == original["status"]
        assert result["items"] == original["items"]

    def test_full_order_roundtrip(self):
        """Test round-trip with a complete order."""
        original = {
            "status": "collecting_items",
            "order_type": "pickup",
            "items": [
                {
                    "item_type": "sandwich",
                    "menu_item_name": "Everything Bagel",
                    "bread": "everything bagel",
                    "toasted": True,
                    "quantity": 1,
                    "unit_price": 4.00,
                    "line_total": 4.00,
                },
            ],
            "customer": {
                "name": "Test User",
                "phone": "555-1234",
                "email": "test@example.com",
            },
            "total_price": 4.00,
        }

        pydantic_state = dict_to_order_state(original)
        result = order_state_to_dict(pydantic_state)

        # Check key fields are preserved
        assert result["order_type"] == original["order_type"]
        assert len(result["items"]) == len(original["items"])
        assert result["customer"]["name"] == original["customer"]["name"]
        assert result["customer"]["phone"] == original["customer"]["phone"]
