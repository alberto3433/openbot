"""
Unit tests for individual chains.

Tests each chain's specific behavior and flow handling.
"""

import pytest

from sandwich_bot.chains import (
    OrderState,
    ChainName,
    GreetingChain,
    AddressChain,
    BagelChain,
    CoffeeChain,
    CheckoutChain,
    BagelItem,
    CoffeeItem,
)


@pytest.fixture
def order_state():
    """Create a fresh order state for testing."""
    return OrderState()


class TestGreetingChain:
    """Tests for GreetingChain."""

    @pytest.fixture
    def chain(self):
        return GreetingChain(store_info={
            "name": "Test Bagel Shop",
            "hours": "7am - 3pm daily",
            "address": "123 Test St",
        })

    def test_handles_greeting(self, chain, order_state):
        """Test basic greeting handling."""
        result = chain.invoke(order_state, "hello")

        assert result.message
        assert "Test Bagel Shop" in result.message or "pickup" in result.message.lower()

    def test_handles_hours_inquiry(self, chain, order_state):
        """Test hours inquiry handling."""
        result = chain.invoke(order_state, "what are your hours")

        assert "7am" in result.message or "open" in result.message.lower()
        assert result.chain_complete is False  # Stays to see if they want to order

    def test_handles_location_inquiry(self, chain, order_state):
        """Test location inquiry handling."""
        result = chain.invoke(order_state, "where are you located")

        assert "123 Test St" in result.message

    def test_detects_delivery_preference(self, chain, order_state):
        """Test detection of delivery preference in greeting."""
        result = chain.invoke(order_state, "hi, I need delivery")

        assert result.state.address.order_type == "delivery"
        assert result.chain_complete is True
        assert result.next_chain == ChainName.ADDRESS

    def test_detects_pickup_preference(self, chain, order_state):
        """Test detection of pickup preference in greeting."""
        result = chain.invoke(order_state, "hi, pickup please")

        assert result.state.address.order_type == "pickup"
        assert result.chain_complete is True


class TestAddressChain:
    """Tests for AddressChain."""

    @pytest.fixture
    def chain(self):
        return AddressChain(store_info={"address": "456 Store Ave"})

    def test_asks_for_order_type(self, chain, order_state):
        """Test asking for pickup/delivery when not specified."""
        result = chain.invoke(order_state, "hey")

        assert "pickup" in result.message.lower() or "delivery" in result.message.lower()

    def test_handles_pickup_selection(self, chain, order_state):
        """Test handling pickup selection."""
        result = chain.invoke(order_state, "pickup")

        assert result.state.address.order_type == "pickup"
        assert result.state.address.store_location_confirmed is True
        assert result.chain_complete is True
        assert result.next_chain == ChainName.BAGEL

    def test_handles_delivery_selection(self, chain, order_state):
        """Test handling delivery selection."""
        result = chain.invoke(order_state, "delivery")

        assert result.state.address.order_type == "delivery"
        assert "address" in result.message.lower()
        assert result.chain_complete is False

    def test_parses_address(self, chain, order_state):
        """Test address parsing."""
        order_state.address.order_type = "delivery"

        result = chain.invoke(order_state, "123 Main Street Brooklyn NY 11201")

        assert result.state.address.street is not None
        assert "123" in result.state.address.street

    def test_asks_for_missing_info(self, chain, order_state):
        """Test asking for missing address info."""
        order_state.address.order_type = "delivery"
        order_state.address.street = "123 Main St"

        result = chain.invoke(order_state, "Brooklyn")

        # Should ask for more info or confirm
        assert result.message

    def test_pickup_with_items_goes_to_checkout(self, chain, order_state):
        """Test that selecting pickup when user has items goes to checkout."""
        # User already has items in their order
        order_state.bagels.items.append(BagelItem(bagel_type="plain", unit_price=2.50))

        result = chain.invoke(order_state, "pickup")

        assert result.state.address.order_type == "pickup"
        assert result.chain_complete is True
        # Should go to checkout, NOT bagel ordering
        assert result.next_chain == ChainName.CHECKOUT
        # Should NOT ask "What can I get for you?"
        assert "what can i get" not in result.message.lower()

    def test_pickup_without_items_goes_to_ordering(self, chain, order_state):
        """Test that selecting pickup when user has no items goes to ordering."""
        # User has no items yet
        result = chain.invoke(order_state, "pickup")

        assert result.state.address.order_type == "pickup"
        assert result.chain_complete is True
        # Should go to bagel ordering
        assert result.next_chain == ChainName.BAGEL


class TestBagelChain:
    """Tests for BagelChain."""

    @pytest.fixture
    def chain(self):
        return BagelChain(menu_data={
            "bagel_types": ["plain", "everything", "sesame"],
            "prices": {"bagel_base": 2.50, "spread": 1.50},
        })

    def test_asks_for_bagel_type(self, chain, order_state):
        """Test asking for bagel type when not specified."""
        result = chain.invoke(order_state, "I want a bagel")

        assert "what kind" in result.message.lower() or "bagel" in result.message.lower()

    def test_parses_bagel_type(self, chain, order_state):
        """Test parsing bagel type from input."""
        result = chain.invoke(order_state, "everything bagel")

        assert result.state.bagels.current_item is not None
        assert result.state.bagels.current_item.bagel_type == "everything"

    def test_parses_quantity(self, chain, order_state):
        """Test parsing quantity from input."""
        result = chain.invoke(order_state, "two everything bagels")

        assert result.state.bagels.current_item is not None
        assert result.state.bagels.current_item.quantity == 2

    def test_asks_about_toasted(self, chain, order_state):
        """Test asking about toasting."""
        # Start an order
        result = chain.invoke(order_state, "plain bagel")

        # Should ask about toasting at some point
        assert "toast" in result.message.lower() or result.state.bagels.awaiting

    def test_handles_spread_selection(self, chain, order_state):
        """Test handling spread selection."""
        order_state.bagels.current_item = BagelItem(bagel_type="everything")
        order_state.bagels.awaiting = "spread"

        result = chain.invoke(order_state, "scallion cream cheese")

        assert result.state.bagels.current_item.spread == "cream cheese"
        assert result.state.bagels.current_item.spread_type == "scallion"

    def test_handles_no_spread(self, chain, order_state):
        """Test handling no spread."""
        order_state.bagels.current_item = BagelItem(bagel_type="everything")
        order_state.bagels.awaiting = "spread"

        result = chain.invoke(order_state, "no thanks")

        assert result.state.bagels.current_item.spread is None

    def test_finishes_item_on_confirm(self, chain, order_state):
        """Test confirming and adding item to order."""
        order_state.bagels.current_item = BagelItem(
            bagel_type="everything",
            toasted=True,
            spread="cream cheese",
            unit_price=4.00,
        )
        order_state.bagels.awaiting = "confirm"

        result = chain.invoke(order_state, "yes")

        # Item should be added to items list
        assert len(result.state.bagels.items) == 1
        assert result.state.bagels.current_item is None

    def test_handles_done_ordering(self, chain, order_state):
        """Test handling done ordering."""
        order_state.bagels.items.append(BagelItem(bagel_type="plain", unit_price=2.50))

        result = chain.invoke(order_state, "that's all")

        assert result.chain_complete is True

    def test_routes_to_coffee(self, chain, order_state):
        """Test routing to coffee when mentioned."""
        order_state.bagels.items.append(BagelItem(bagel_type="plain", unit_price=2.50))

        result = chain.invoke(order_state, "I'll also have a coffee")

        assert result.next_chain == ChainName.COFFEE

    def test_handles_no_another_bagel(self, chain, order_state):
        """Test that 'no' to 'another bagel?' moves to next chain."""
        # Set up state as if we just confirmed a bagel and were asked "another?"
        order_state.bagels.items.append(BagelItem(bagel_type="plain", unit_price=2.50))
        order_state.bagels.awaiting = "another"
        order_state.bagels.current_item = None  # Item was added, so current is None

        result = chain.invoke(order_state, "no")

        # Should finish ordering and move to coffee or checkout
        assert result.chain_complete is True
        assert result.next_chain in (ChainName.COFFEE, ChainName.CHECKOUT)

    def test_preserves_spread_when_bagel_type_not_specified(self, chain, order_state):
        """Test that spread is preserved when user says 'bagel with cream cheese' then specifies type."""
        # Step 1: User says "bagel with cream cheese" - no specific type
        result = chain.invoke(order_state, "bagel with cream cheese")

        # Should ask for bagel type
        assert "what kind" in result.message.lower() or "bagel" in result.message.lower()
        assert result.state.bagels.awaiting == "bagel_type"
        # Spread should be preserved in current_item
        assert result.state.bagels.current_item is not None
        assert result.state.bagels.current_item.spread == "cream cheese"

        # Step 2: User specifies bagel type
        result2 = chain.invoke(result.state, "plain")

        # Should have the bagel type set and spread preserved
        assert result2.state.bagels.current_item.bagel_type == "plain"
        assert result2.state.bagels.current_item.spread == "cream cheese"

    def test_toasted_response_preserves_bagel_type(self, chain, order_state):
        """Test that bagel type is preserved when answering toasted question."""
        # Set up state with a bagel that has a type and is awaiting toasted
        order_state.bagels.current_item = BagelItem(
            bagel_type="plain",
            spread="cream cheese",
        )
        order_state.bagels.awaiting = "toasted"

        result = chain.invoke(order_state, "yes")

        # Bagel type should still be "plain"
        assert result.state.bagels.current_item.bagel_type == "plain"
        assert result.state.bagels.current_item.toasted is True
        assert result.state.bagels.current_item.spread == "cream cheese"


class TestCoffeeChain:
    """Tests for CoffeeChain."""

    @pytest.fixture
    def chain(self):
        return CoffeeChain()

    def test_asks_for_drink_type(self, chain, order_state):
        """Test asking for drink type when not specified."""
        result = chain.invoke(order_state, "I want a drink")

        # Message should prompt for more info - could be "Anything else?" or asking about drink type
        assert result.message is not None
        assert result.state.coffee.awaiting == "drink_type"

    def test_parses_drink_type(self, chain, order_state):
        """Test parsing drink type from input."""
        result = chain.invoke(order_state, "latte please")

        assert result.state.coffee.current_item is not None
        assert result.state.coffee.current_item.drink_type == "latte"

    def test_parses_size(self, chain, order_state):
        """Test parsing size from input."""
        result = chain.invoke(order_state, "large coffee")

        assert result.state.coffee.current_item is not None
        assert result.state.coffee.current_item.size == "large"

    def test_parses_iced(self, chain, order_state):
        """Test parsing iced preference."""
        result = chain.invoke(order_state, "iced latte")

        assert result.state.coffee.current_item is not None
        assert result.state.coffee.current_item.iced is True

    def test_handles_milk_selection(self, chain, order_state):
        """Test handling milk selection."""
        order_state.coffee.current_item = CoffeeItem(drink_type="latte")
        order_state.coffee.awaiting = "milk"

        result = chain.invoke(order_state, "oat milk")

        assert result.state.coffee.current_item.milk == "oat"

    def test_handles_no_coffee(self, chain, order_state):
        """Test handling when user doesn't want coffee."""
        result = chain.invoke(order_state, "no thanks")

        assert result.chain_complete is True

    def test_calculates_price(self, chain, order_state):
        """Test price calculation."""
        result = chain.invoke(order_state, "large iced latte with oat milk")

        item = result.state.coffee.current_item
        assert item is not None
        assert item.unit_price > 0


class TestCheckoutChain:
    """Tests for CheckoutChain."""

    @pytest.fixture
    def chain(self):
        return CheckoutChain(tax_rate=0.08)

    def test_shows_order_summary(self, chain, order_state):
        """Test showing order summary."""
        order_state.bagels.items.append(
            BagelItem(bagel_type="everything", unit_price=2.50)
        )
        order_state.address.order_type = "pickup"

        result = chain.invoke(order_state, "checkout")

        assert "$" in result.message
        assert "everything" in result.message.lower()
        assert result.state.checkout.order_reviewed is True

    def test_calculates_totals(self, chain, order_state):
        """Test total calculation."""
        order_state.bagels.items.append(
            BagelItem(bagel_type="everything", unit_price=10.00)
        )
        order_state.address.order_type = "pickup"

        result = chain.invoke(order_state, "checkout")

        assert result.state.checkout.subtotal == 10.00
        assert result.state.checkout.tax == 0.80  # 10 * 0.08
        assert result.state.checkout.total == 10.80

    def test_adds_delivery_fee(self, chain, order_state):
        """Test delivery fee addition."""
        order_state.bagels.items.append(
            BagelItem(bagel_type="everything", unit_price=10.00)
        )
        order_state.address.order_type = "delivery"
        order_state.address.street = "123 Main St"
        order_state.address.city = "Brooklyn"
        order_state.address.zip_code = "11201"

        result = chain.invoke(order_state, "checkout")

        assert result.state.checkout.delivery_fee == 2.99
        assert result.state.checkout.total == 13.79  # 10 + 0.80 + 2.99

    def test_handles_confirmation(self, chain, order_state):
        """Test order confirmation with name already provided."""
        order_state.bagels.items.append(
            BagelItem(bagel_type="everything", unit_price=2.50)
        )
        order_state.address.order_type = "pickup"
        order_state.checkout.order_reviewed = True
        order_state.customer_name = "John"  # Pre-populate name
        order_state.checkout.contact_collected = True  # Skip contact collection

        result = chain.invoke(order_state, "yes, looks good")

        assert result.state.checkout.confirmed is True
        assert result.state.checkout.order_number is not None

    def test_asks_for_name_on_confirmation(self, chain, order_state):
        """Test that checkout asks for customer name if not provided."""
        order_state.bagels.items.append(
            BagelItem(bagel_type="everything", unit_price=2.50)
        )
        order_state.address.order_type = "pickup"
        order_state.checkout.order_reviewed = True

        result = chain.invoke(order_state, "yes, looks good")

        # Should ask for name instead of confirming
        assert result.state.checkout.confirmed is False
        assert result.state.checkout.awaiting == "name"
        assert "name" in result.message.lower()

    def test_handles_modification_request(self, chain, order_state):
        """Test modification request handling."""
        order_state.bagels.items.append(
            BagelItem(bagel_type="everything", unit_price=2.50)
        )
        order_state.address.order_type = "pickup"
        order_state.checkout.order_reviewed = True

        result = chain.invoke(order_state, "no, I want to change something")

        assert "change" in result.message.lower() or "what" in result.message.lower()

    def test_handles_cancellation(self, chain, order_state):
        """Test order cancellation."""
        order_state.bagels.items.append(
            BagelItem(bagel_type="everything", unit_price=2.50)
        )

        result = chain.invoke(order_state, "cancel my order")

        assert "cancel" in result.message.lower()
        assert result.chain_complete is True

    def test_empty_cart_redirect(self, chain, order_state):
        """Test redirect when cart is empty."""
        result = chain.invoke(order_state, "checkout")

        assert result.chain_complete is True
        assert result.next_chain == ChainName.BAGEL
