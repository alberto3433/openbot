"""
Unit tests for the chains state models.

Tests the Pydantic models used for conversation state management.
"""

import pytest
from datetime import datetime

from sandwich_bot.chains.state import (
    AddressState,
    BagelItem,
    BagelOrderState,
    CoffeeItem,
    CoffeeOrderState,
    CheckoutState,
    OrderState,
    ChainResult,
    ChainName,
    OrderStatus,
)


class TestAddressState:
    """Tests for AddressState model."""

    def test_default_values(self):
        """Test that AddressState has correct defaults."""
        state = AddressState()
        assert state.order_type is None
        assert state.street is None
        assert state.city is None
        assert state.zip_code is None
        assert state.is_validated is False

    def test_pickup_is_complete(self):
        """Test is_complete for pickup orders."""
        state = AddressState(order_type="pickup", store_location_confirmed=True)
        assert state.is_complete() is True

        state = AddressState(order_type="pickup", store_location_confirmed=False)
        assert state.is_complete() is False

    def test_delivery_is_complete(self):
        """Test is_complete for delivery orders."""
        state = AddressState(
            order_type="delivery",
            street="123 Main St",
            city="Brooklyn",
            zip_code="11201",
            is_validated=True,
        )
        assert state.is_complete() is True

        # Missing validation
        state.is_validated = False
        assert state.is_complete() is False

        # Missing zip
        state.is_validated = True
        state.zip_code = None
        assert state.is_complete() is False

    def test_formatted_address(self):
        """Test get_formatted_address."""
        state = AddressState(
            order_type="delivery",
            street="123 Main St",
            city="Brooklyn",
            state="NY",
            zip_code="11201",
            apt_unit="4B",
        )
        addr = state.get_formatted_address()
        assert "123 Main St" in addr
        assert "Apt 4B" in addr
        assert "Brooklyn" in addr
        assert "NY" in addr
        assert "11201" in addr

    def test_formatted_address_pickup_returns_none(self):
        """Test that pickup orders return None for formatted address."""
        state = AddressState(order_type="pickup")
        assert state.get_formatted_address() is None


class TestBagelItem:
    """Tests for BagelItem model."""

    def test_default_values(self):
        """Test that BagelItem has correct defaults."""
        item = BagelItem(bagel_type="everything")
        assert item.bagel_type == "everything"
        assert item.quantity == 1
        assert item.toasted is None  # None = not asked yet
        assert item.spread is None
        assert item.extras == []

    def test_get_description_simple(self):
        """Test simple bagel description."""
        item = BagelItem(bagel_type="plain")
        desc = item.get_description()
        assert "plain" in desc.lower()

    def test_get_description_with_options(self):
        """Test bagel description with all options."""
        item = BagelItem(
            bagel_type="everything",
            quantity=2,
            toasted=True,
            spread="cream cheese",
            spread_type="scallion",
            extras=["lox", "capers"],
        )
        desc = item.get_description()
        assert "2x" in desc
        assert "everything" in desc.lower()
        assert "toasted" in desc.lower()
        assert "scallion" in desc.lower()
        assert "lox" in desc.lower()


class TestBagelOrderState:
    """Tests for BagelOrderState model."""

    def test_add_current_item(self):
        """Test adding current item to items list."""
        state = BagelOrderState()
        state.current_item = BagelItem(bagel_type="plain")
        assert len(state.items) == 0

        state.add_current_item()
        assert len(state.items) == 1
        assert state.current_item is None
        assert state.awaiting is None

    def test_get_total(self):
        """Test calculating total for bagel items."""
        state = BagelOrderState(
            items=[
                BagelItem(bagel_type="plain", quantity=2, unit_price=2.50),
                BagelItem(bagel_type="everything", quantity=1, unit_price=3.00),
            ]
        )
        total = state.get_total()
        assert total == 8.00  # (2 * 2.50) + (1 * 3.00)


class TestCoffeeItem:
    """Tests for CoffeeItem model."""

    def test_default_values(self):
        """Test that CoffeeItem has correct defaults."""
        item = CoffeeItem(drink_type="latte")
        assert item.drink_type == "latte"
        assert item.size is None
        assert item.iced is None  # None = not asked yet
        assert item.milk is None

    def test_get_description(self):
        """Test coffee item description."""
        item = CoffeeItem(
            drink_type="latte",
            size="large",
            iced=True,
            milk="oat",
        )
        desc = item.get_description()
        assert "large" in desc.lower()
        assert "iced" in desc.lower()
        assert "latte" in desc.lower()
        assert "oat" in desc.lower()


class TestCheckoutState:
    """Tests for CheckoutState model."""

    def test_calculate_total_pickup(self):
        """Test total calculation for pickup orders."""
        state = CheckoutState()
        state.calculate_total(subtotal=10.00, is_delivery=False, tax_rate=0.08)

        assert state.subtotal == 10.00
        assert state.tax == 0.80
        assert state.delivery_fee == 0.0
        assert state.total == 10.80

    def test_calculate_total_delivery(self):
        """Test total calculation for delivery orders."""
        state = CheckoutState()
        state.calculate_total(subtotal=10.00, is_delivery=True, tax_rate=0.08)

        assert state.subtotal == 10.00
        assert state.tax == 0.80
        assert state.delivery_fee == 2.99
        assert state.total == 13.79

    def test_generate_order_number(self):
        """Test order number generation."""
        state = CheckoutState()
        order_num = state.generate_order_number()

        assert order_num.startswith("ORD-")
        # Format: ORD-{6 hex chars}-{2 digits} = 4 + 6 + 1 + 2 = 13 chars
        assert len(order_num) == 13
        assert state.order_number == order_num


class TestOrderState:
    """Tests for OrderState model."""

    def test_default_values(self):
        """Test that OrderState has correct defaults."""
        state = OrderState()

        assert state.session_id is not None
        assert state.started_at is not None
        assert state.current_chain == ChainName.GREETING
        assert state.status == OrderStatus.IN_PROGRESS
        assert state.customer_name is None

    def test_has_items(self):
        """Test has_items method."""
        state = OrderState()
        assert state.has_items() is False

        state.bagels.items.append(BagelItem(bagel_type="plain"))
        assert state.has_items() is True

    def test_get_item_count(self):
        """Test get_item_count method."""
        state = OrderState()
        assert state.get_item_count() == 0

        state.bagels.items.append(BagelItem(bagel_type="plain", quantity=2))
        state.coffee.items.append(CoffeeItem(drink_type="latte"))
        assert state.get_item_count() == 3  # 2 bagels + 1 coffee

    def test_get_subtotal(self):
        """Test get_subtotal method."""
        state = OrderState()
        state.bagels.items.append(BagelItem(bagel_type="plain", quantity=2, unit_price=2.50))
        state.coffee.items.append(CoffeeItem(drink_type="latte", unit_price=4.75))

        assert state.get_subtotal() == 9.75  # (2 * 2.50) + 4.75

    def test_add_message(self):
        """Test adding messages to conversation history."""
        state = OrderState()
        state.add_message("user", "Hello")
        state.add_message("assistant", "Hi there!")

        assert len(state.conversation_history) == 2
        assert state.conversation_history[0]["role"] == "user"
        assert state.conversation_history[0]["content"] == "Hello"
        assert state.conversation_history[1]["role"] == "assistant"

    def test_transition_to(self):
        """Test chain transition."""
        state = OrderState()
        assert state.current_chain == ChainName.GREETING
        assert state.previous_chain is None

        state.transition_to(ChainName.ADDRESS)
        assert state.current_chain == ChainName.ADDRESS
        assert state.previous_chain == ChainName.GREETING

        state.transition_to(ChainName.BAGEL)
        assert state.current_chain == ChainName.BAGEL
        assert state.previous_chain == ChainName.ADDRESS

    def test_get_order_summary_empty(self):
        """Test order summary with no items."""
        state = OrderState()
        summary = state.get_order_summary()
        assert "No items" in summary

    def test_get_order_summary_with_items(self):
        """Test order summary with items."""
        state = OrderState()
        state.bagels.items.append(
            BagelItem(bagel_type="everything", toasted=True, unit_price=2.50)
        )
        state.coffee.items.append(
            CoffeeItem(drink_type="latte", size="large", unit_price=4.75)
        )

        summary = state.get_order_summary()
        assert "everything" in summary.lower()
        assert "latte" in summary.lower()
        assert "$" in summary


class TestChainResult:
    """Tests for ChainResult model."""

    def test_default_values(self):
        """Test that ChainResult has correct defaults."""
        state = OrderState()
        result = ChainResult(message="Hello", state=state)

        assert result.message == "Hello"
        assert result.chain_complete is False
        assert result.next_chain is None
        assert result.needs_user_input is True

    def test_with_all_options(self):
        """Test ChainResult with all options specified."""
        state = OrderState()
        result = ChainResult(
            message="Moving to address",
            state=state,
            chain_complete=True,
            next_chain=ChainName.ADDRESS,
            needs_user_input=False,
        )

        assert result.chain_complete is True
        assert result.next_chain == ChainName.ADDRESS
        assert result.needs_user_input is False
