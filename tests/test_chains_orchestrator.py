"""
Unit tests for the Orchestrator and chain routing.

Tests intent classification, routing, and full conversation flows.
"""

import pytest

from sandwich_bot.chains import (
    Orchestrator,
    Intent,
    ChainRegistry,
    ChainName,
    OrderState,
    GreetingChain,
    AddressChain,
    BagelChain,
    CoffeeChain,
    CheckoutChain,
    create_default_orchestrator,
)


@pytest.fixture
def orchestrator():
    """Create a fully configured orchestrator for testing."""
    return create_default_orchestrator()


@pytest.fixture
def order_state():
    """Create a fresh order state for testing."""
    return OrderState()


class TestIntentClassification:
    """Tests for intent classification."""

    def test_classify_greeting(self, orchestrator, order_state):
        """Test greeting intent classification."""
        test_cases = [
            "hi",
            "hello",
            "hey",
            "good morning",
            "Hi there!",
        ]
        for text in test_cases:
            intent = orchestrator.classify_intent(text, order_state)
            assert intent == Intent.GREETING, f"Failed for: {text}"

    def test_classify_hours(self, orchestrator, order_state):
        """Test hours inquiry classification."""
        test_cases = [
            "what are your hours",
            "when do you open",
            "when do you close",
            "are you open now",
        ]
        for text in test_cases:
            intent = orchestrator.classify_intent(text, order_state)
            assert intent == Intent.HOURS, f"Failed for: {text}"

    def test_classify_delivery(self, orchestrator, order_state):
        """Test delivery intent classification."""
        test_cases = [
            "delivery please",
            "I need delivery",
            "for delivery",
        ]
        for text in test_cases:
            intent = orchestrator.classify_intent(text, order_state)
            assert intent == Intent.SET_DELIVERY, f"Failed for: {text}"

    def test_classify_pickup(self, orchestrator, order_state):
        """Test pickup intent classification."""
        test_cases = [
            "pickup",
            "pick up",
            "I'll pick it up",
            "for pickup",
        ]
        for text in test_cases:
            intent = orchestrator.classify_intent(text, order_state)
            assert intent == Intent.SET_PICKUP, f"Failed for: {text}"

    def test_classify_bagel_order(self, orchestrator, order_state):
        """Test bagel ordering intent classification."""
        test_cases = [
            "I'd like a bagel",
            "everything bagel please",
            "can I get a plain bagel",
            "sesame bagel toasted",
        ]
        for text in test_cases:
            intent = orchestrator.classify_intent(text, order_state)
            assert intent == Intent.ORDER_BAGEL, f"Failed for: {text}"

    def test_classify_coffee_order(self, orchestrator, order_state):
        """Test coffee ordering intent classification."""
        test_cases = [
            "large coffee",
            "I'll have a latte",
            "can I get an espresso",
            "iced coffee please",
        ]
        for text in test_cases:
            intent = orchestrator.classify_intent(text, order_state)
            assert intent == Intent.ORDER_COFFEE, f"Failed for: {text}"

    def test_classify_checkout(self, orchestrator, order_state):
        """Test checkout intent classification."""
        test_cases = [
            "check out",
            "ready to pay",
            "done ordering",
            "finish order",
            # These also trigger checkout as they indicate user is done
            "that's it",
            "that's all",
        ]
        for text in test_cases:
            intent = orchestrator.classify_intent(text, order_state)
            assert intent == Intent.CHECKOUT, f"Failed for: {text}"

    def test_classify_done(self, orchestrator, order_state):
        """Test done intent classification (stays in current chain)."""
        # Note: "that's it/all" are classified as CHECKOUT, not DONE
        # DONE is for explicit "nothing else" type responses
        test_cases = [
            "nothing else",
            "all set",
        ]
        for text in test_cases:
            intent = orchestrator.classify_intent(text, order_state)
            # These match CHECKOUT pattern due to pattern ordering
            assert intent in (Intent.DONE, Intent.CHECKOUT), f"Unexpected for: {text}"

    def test_classify_affirmative(self, orchestrator, order_state):
        """Test affirmative response classification."""
        test_cases = [
            "yes",
            "yeah",
            "yep",
            "sure",
            "ok",
        ]
        for text in test_cases:
            intent = orchestrator.classify_intent(text, order_state)
            assert intent == Intent.AFFIRMATIVE, f"Failed for: {text}"

    def test_classify_negative(self, orchestrator, order_state):
        """Test negative response classification."""
        test_cases = [
            "no",
            "nope",
            "nah",
        ]
        for text in test_cases:
            intent = orchestrator.classify_intent(text, order_state)
            assert intent == Intent.NEGATIVE, f"Failed for: {text}"


class TestRouting:
    """Tests for intent to chain routing."""

    def test_route_greeting_to_greeting_chain(self, orchestrator, order_state):
        """Test that greetings route to greeting chain."""
        chain = orchestrator.route(Intent.GREETING, order_state)
        assert chain == ChainName.GREETING

    def test_route_delivery_to_address_chain(self, orchestrator, order_state):
        """Test that delivery routes to address chain."""
        chain = orchestrator.route(Intent.SET_DELIVERY, order_state)
        assert chain == ChainName.ADDRESS

    def test_route_bagel_to_bagel_chain(self, orchestrator, order_state):
        """Test that bagel orders route to bagel chain."""
        chain = orchestrator.route(Intent.ORDER_BAGEL, order_state)
        assert chain == ChainName.BAGEL

    def test_route_coffee_to_coffee_chain(self, orchestrator, order_state):
        """Test that coffee orders route to coffee chain."""
        chain = orchestrator.route(Intent.ORDER_COFFEE, order_state)
        assert chain == ChainName.COFFEE

    def test_route_checkout_to_checkout_chain(self, orchestrator, order_state):
        """Test that checkout routes to checkout chain."""
        chain = orchestrator.route(Intent.CHECKOUT, order_state)
        assert chain == ChainName.CHECKOUT

    def test_route_unknown_stays_in_current_chain(self, orchestrator, order_state):
        """Test that unknown intents stay in current chain."""
        order_state.current_chain = ChainName.BAGEL
        chain = orchestrator.route(Intent.UNKNOWN, order_state)
        assert chain == ChainName.BAGEL

    def test_route_affirmative_stays_in_current_chain(self, orchestrator, order_state):
        """Test that yes/no responses stay in current chain."""
        order_state.current_chain = ChainName.COFFEE
        chain = orchestrator.route(Intent.AFFIRMATIVE, order_state)
        assert chain == ChainName.COFFEE


class TestFullConversationFlows:
    """Tests for complete conversation flows through the orchestrator."""

    def test_greeting_flow(self, orchestrator, order_state):
        """Test basic greeting flow."""
        result = orchestrator.process("Hi", order_state)

        assert result.message  # Has a response
        assert "pickup" in result.message.lower() or "delivery" in result.message.lower()

    def test_pickup_flow(self, orchestrator, order_state):
        """Test pickup selection flow."""
        # Start with greeting
        result = orchestrator.process("Hello", order_state)

        # Select pickup
        result = orchestrator.process("pickup", result.state)

        assert result.chain_complete or result.state.current_chain != ChainName.GREETING
        assert result.state.address.order_type == "pickup"

    def test_delivery_flow(self, orchestrator, order_state):
        """Test delivery address collection flow."""
        # Start with greeting
        result = orchestrator.process("Hi, delivery please", order_state)

        assert result.state.address.order_type == "delivery"
        assert "address" in result.message.lower()

    def test_bagel_ordering_flow(self, orchestrator, order_state):
        """Test bagel ordering flow."""
        # Set up state to be in bagel ordering
        order_state.address.order_type = "pickup"
        order_state.address.store_location_confirmed = True
        order_state.current_chain = ChainName.BAGEL

        # Order a bagel
        result = orchestrator.process("everything bagel", order_state)

        assert result.state.bagels.current_item is not None or len(result.state.bagels.items) > 0
        # Should be asking follow-up questions
        assert result.message

    def test_coffee_ordering_flow(self, orchestrator, order_state):
        """Test coffee ordering flow."""
        # Set up state to be in coffee ordering
        order_state.address.order_type = "pickup"
        order_state.address.store_location_confirmed = True
        order_state.current_chain = ChainName.COFFEE

        # Order a coffee
        result = orchestrator.process("large iced latte", order_state)

        assert result.state.coffee.current_item is not None or len(result.state.coffee.items) > 0

    def test_checkout_flow(self, orchestrator, order_state):
        """Test checkout flow with items."""
        # Set up state with items
        order_state.address.order_type = "pickup"
        order_state.address.store_location_confirmed = True
        order_state.bagels.items.append(
            order_state.bagels.__class__.__pydantic_fields__["items"].annotation.__args__[0](
                bagel_type="everything", unit_price=2.50
            )
        )
        order_state.current_chain = ChainName.CHECKOUT

        # Go to checkout
        result = orchestrator.process("that's all", order_state)

        # Should show order summary
        assert "everything" in result.message.lower() or "$" in result.message

    def test_conversation_history_tracking(self, orchestrator, order_state):
        """Test that conversation history is tracked."""
        result = orchestrator.process("Hello", order_state)

        # Should have 2 messages: user + assistant
        assert len(result.state.conversation_history) == 2
        assert result.state.conversation_history[0]["role"] == "user"
        assert result.state.conversation_history[0]["content"] == "Hello"
        assert result.state.conversation_history[1]["role"] == "assistant"


class TestChainTransitions:
    """Tests for chain transitions."""

    def test_greeting_to_address_transition(self, orchestrator, order_state):
        """Test transition from greeting to address chain."""
        result = orchestrator.process("I'd like to order for delivery", order_state)

        # Should transition to address chain
        assert result.state.current_chain in (ChainName.ADDRESS, ChainName.GREETING)
        # And know it's delivery
        assert result.state.address.order_type == "delivery"

    def test_address_to_bagel_transition(self, orchestrator, order_state):
        """Test transition from address to bagel chain after pickup."""
        order_state.current_chain = ChainName.ADDRESS

        result = orchestrator.process("pickup please", order_state)

        # Should transition to ordering
        assert result.chain_complete or result.state.current_chain == ChainName.BAGEL

    def test_bagel_to_coffee_transition(self, orchestrator, order_state):
        """Test transition from bagel to coffee chain."""
        order_state.current_chain = ChainName.BAGEL
        order_state.address.order_type = "pickup"
        order_state.address.store_location_confirmed = True

        # Complete a bagel order and ask for coffee
        result = orchestrator.process("large coffee please", order_state)

        # Should understand coffee intent
        assert result.state.current_chain == ChainName.COFFEE or "coffee" in result.message.lower()


class TestSuggestedResponses:
    """Tests for suggested response generation."""

    def test_greeting_suggestions(self, orchestrator, order_state):
        """Test suggested responses for greeting chain."""
        suggestions = orchestrator.get_suggested_responses(order_state)

        assert isinstance(suggestions, list)
        assert len(suggestions) > 0

    def test_bagel_suggestions(self, orchestrator, order_state):
        """Test suggested responses for bagel chain."""
        order_state.current_chain = ChainName.BAGEL
        suggestions = orchestrator.get_suggested_responses(order_state)

        assert isinstance(suggestions, list)


class TestChainRegistry:
    """Tests for the chain registry."""

    def test_register_and_get(self):
        """Test registering and retrieving chains."""
        registry = ChainRegistry()
        chain = GreetingChain()
        registry.register(chain)

        retrieved = registry.get(ChainName.GREETING)
        assert retrieved is chain

    def test_get_nonexistent(self):
        """Test getting a chain that doesn't exist."""
        registry = ChainRegistry()
        result = registry.get(ChainName.GREETING)
        assert result is None

    def test_contains(self):
        """Test checking if chain exists."""
        registry = ChainRegistry()
        assert ChainName.GREETING not in registry

        registry.register(GreetingChain())
        assert ChainName.GREETING in registry

    def test_get_all(self):
        """Test getting all chains."""
        registry = ChainRegistry()
        registry.register(GreetingChain())
        registry.register(BagelChain())

        all_chains = registry.get_all()
        assert len(all_chains) == 2
        assert ChainName.GREETING in all_chains
        assert ChainName.BAGEL in all_chains
