"""
Orchestrator - the brain of the conversation flow system.

The Orchestrator is responsible for:
1. Classifying user intent from their message
2. Routing to the appropriate chain based on intent
3. Managing state transitions between chains
4. Handling interruptions when user changes topics mid-flow
"""

import re
from enum import Enum
from typing import Any, Optional

from .base import BaseChain, ChainRegistry
from .state import OrderState, ChainResult, ChainName


class Intent(str, Enum):
    """User intents that the Orchestrator can classify."""

    # Greeting/General
    GREETING = "greeting"
    HOURS = "hours"
    LOCATION = "location"
    HELP = "help"

    # Address/Delivery
    SET_DELIVERY = "set_delivery"
    SET_PICKUP = "set_pickup"
    PROVIDE_ADDRESS = "provide_address"

    # Ordering - Bagels
    ORDER_BAGEL = "order_bagel"
    CUSTOMIZE_BAGEL = "customize_bagel"

    # Ordering - Coffee
    ORDER_COFFEE = "order_coffee"
    CUSTOMIZE_COFFEE = "customize_coffee"

    # Order management
    MODIFY_ORDER = "modify_order"
    REMOVE_ITEM = "remove_item"
    VIEW_ORDER = "view_order"

    # Checkout
    CHECKOUT = "checkout"
    CONFIRM = "confirm"
    CANCEL = "cancel"

    # Responses to questions
    AFFIRMATIVE = "affirmative"  # yes, yeah, sure, etc.
    NEGATIVE = "negative"  # no, nope, etc.
    DONE = "done"  # that's it, I'm done, etc.

    # Unknown
    UNKNOWN = "unknown"


# Intent classification rules - pattern matching for deterministic routing
INTENT_PATTERNS: dict[Intent, list[str]] = {
    # Greetings
    Intent.GREETING: [
        r"\b(hi|hello|hey|good\s*(morning|afternoon|evening)|howdy)\b",
        r"^(hi|hello|hey)[\s!.]*$",
    ],
    Intent.HOURS: [
        r"\b(hours?|open|close|when.*open|what time)\b",
    ],
    Intent.LOCATION: [
        r"\b(where|location|address|directions?|find you)\b",
    ],

    # Delivery/Pickup
    Intent.SET_DELIVERY: [
        r"\b(deliver(y)?|for delivery)\b",
    ],
    Intent.SET_PICKUP: [
        r"\b(pick\s*up|pickup|for pickup|come get|i.ll (pick|come))\b",
    ],
    Intent.PROVIDE_ADDRESS: [
        r"\d+\s+\w+\s+(st(reet)?|ave(nue)?|rd|road|blvd|dr(ive)?|ln|lane|way|ct|court)",
    ],

    # Bagel ordering
    Intent.ORDER_BAGEL: [
        r"\b(bagel|everything bagel|plain bagel|sesame|poppy|onion bagel|bialy)\b",
        r"\b(cream cheese|lox|schmear|toasted)\b",
    ],

    # Coffee ordering
    Intent.ORDER_COFFEE: [
        r"\b(coffee|latte|espresso|cappuccino|americano|cold brew|iced coffee|tea)\b",
        r"\b(drip|pour over|mocha|macchiato)\b",
    ],

    # Order management
    Intent.MODIFY_ORDER: [
        r"\b(change|modify|update|edit|switch)\b.*\b(order|item|bagel|coffee)\b",
    ],
    Intent.REMOVE_ITEM: [
        r"\b(remove|delete|cancel|take off|get rid of)\b.*\b(item|bagel|coffee|that)\b",
    ],
    Intent.VIEW_ORDER: [
        r"\b(what.*(order|have)|show.*order|my order|order so far|review)\b",
    ],

    # Checkout
    Intent.CHECKOUT: [
        r"\b(check\s*out|pay|done ordering|that.s (all|it|everything)|ready to pay)\b",
        r"\b(finish|complete|place.*order)\b",
    ],
    Intent.CONFIRM: [
        r"\b(confirm|looks good|correct|right|perfect|yes.*good|submit)\b",
    ],
    Intent.CANCEL: [
        r"\b(cancel|nevermind|forget it|start over|never mind)\b",
    ],

    # Simple responses
    Intent.AFFIRMATIVE: [
        r"^(yes|yeah|yep|yup|sure|ok|okay|definitely|absolutely|please|sounds good)[\s!.]*$",
    ],
    Intent.NEGATIVE: [
        r"^(no|nope|nah|not?\s*really|i.m good|nothing)[\s!.]*$",
    ],
    Intent.DONE: [
        r"\b(that.s (it|all|everything)|i.m (done|good|finished)|nothing else|all set)\b",
    ],
}


# Mapping from intents to chains
INTENT_TO_CHAIN: dict[Intent, ChainName] = {
    Intent.GREETING: ChainName.GREETING,
    Intent.HOURS: ChainName.GREETING,
    Intent.LOCATION: ChainName.GREETING,
    Intent.HELP: ChainName.GREETING,

    Intent.SET_DELIVERY: ChainName.ADDRESS,
    Intent.SET_PICKUP: ChainName.ADDRESS,
    Intent.PROVIDE_ADDRESS: ChainName.ADDRESS,

    Intent.ORDER_BAGEL: ChainName.BAGEL,
    Intent.CUSTOMIZE_BAGEL: ChainName.BAGEL,

    Intent.ORDER_COFFEE: ChainName.COFFEE,
    Intent.CUSTOMIZE_COFFEE: ChainName.COFFEE,

    Intent.MODIFY_ORDER: ChainName.MODIFY,
    Intent.REMOVE_ITEM: ChainName.MODIFY,
    Intent.VIEW_ORDER: ChainName.CHECKOUT,

    Intent.CHECKOUT: ChainName.CHECKOUT,
    Intent.CONFIRM: ChainName.CHECKOUT,
    Intent.CANCEL: ChainName.CANCEL,
}


class Orchestrator:
    """
    The brain that determines user intent and delegates to appropriate chains.

    The Orchestrator uses a combination of:
    1. Pattern matching for deterministic routing (fast, reliable)
    2. Current conversation state (what chain are we in, what are we waiting for)
    3. Optional LLM for complex/ambiguous cases
    """

    def __init__(
        self,
        chain_registry: ChainRegistry,
        llm: Optional[Any] = None,
        menu_data: Optional[dict] = None,
    ):
        """
        Initialize the Orchestrator.

        Args:
            chain_registry: Registry containing all chain instances
            llm: Optional LLM for complex intent classification
            menu_data: Menu data for context
        """
        self.chains = chain_registry
        self.llm = llm
        self.menu_data = menu_data or {}

    def classify_intent(self, user_input: str, state: OrderState) -> Intent:
        """
        Classify user intent from their message.

        Uses pattern matching first, then falls back to context-based
        classification, and finally LLM if available.

        Args:
            user_input: User's message text
            state: Current order state for context

        Returns:
            Classified intent
        """
        input_lower = user_input.lower().strip()

        # 1. Try pattern matching first (deterministic, fast)
        for intent, patterns in INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, input_lower, re.IGNORECASE):
                    return intent

        # 2. Context-based classification based on current chain
        # If we're in the middle of a flow and waiting for input,
        # assume the input is for the current chain
        current_chain = self.chains.get(state.current_chain)
        if current_chain:
            awaiting = current_chain.get_awaiting_field(state)
            if awaiting:
                # We're waiting for specific input - assume it's for current chain
                return self._infer_intent_for_chain(state.current_chain)

        # 3. LLM fallback for ambiguous cases (if available)
        if self.llm:
            return self._classify_with_llm(user_input, state)

        return Intent.UNKNOWN

    def _infer_intent_for_chain(self, chain: ChainName) -> Intent:
        """Infer the most likely intent for a chain's expected input."""
        chain_to_intent = {
            ChainName.GREETING: Intent.GREETING,
            ChainName.ADDRESS: Intent.PROVIDE_ADDRESS,
            ChainName.BAGEL: Intent.ORDER_BAGEL,
            ChainName.COFFEE: Intent.ORDER_COFFEE,
            ChainName.CHECKOUT: Intent.CHECKOUT,
        }
        return chain_to_intent.get(chain, Intent.UNKNOWN)

    def _classify_with_llm(self, user_input: str, state: OrderState) -> Intent:
        """Use LLM for complex intent classification."""
        # This would call the LLM to classify intent
        # For now, return UNKNOWN to fall through to current chain
        return Intent.UNKNOWN

    def route(self, intent: Intent, state: OrderState) -> ChainName:
        """
        Determine which chain should handle the request.

        Considers:
        1. Explicit intent-to-chain mapping
        2. Current conversation state (avoid unnecessary chain switching)
        3. Chain completion status

        Args:
            intent: Classified intent
            state: Current order state

        Returns:
            Chain name to route to
        """
        # Get the natural chain for this intent
        target_chain = INTENT_TO_CHAIN.get(intent)

        # If no explicit mapping, stay in current chain
        if target_chain is None:
            return state.current_chain

        # Handle simple responses in context of current chain
        if intent in (Intent.AFFIRMATIVE, Intent.NEGATIVE, Intent.DONE):
            return state.current_chain

        # If unknown intent, stay in current chain
        if intent == Intent.UNKNOWN:
            return state.current_chain

        return target_chain

    def process(self, user_input: str, state: OrderState) -> ChainResult:
        """
        Main entry point - process user input and return response.

        This is the primary method called by the application. It:
        1. Classifies the user's intent
        2. Routes to the appropriate chain
        3. Invokes the chain to process the input
        4. Returns the result with updated state

        Args:
            user_input: User's message text
            state: Current order state

        Returns:
            ChainResult with response and updated state
        """
        # Add user message to history
        state.add_message("user", user_input)

        # If order is already confirmed, handle post-confirmation flow
        if state.checkout.confirmed:
            return self._handle_post_confirmation(state, user_input)

        # Classify intent
        intent = self.classify_intent(user_input, state)

        # Determine target chain
        target_chain_name = self.route(intent, state)

        # Get chain instance
        chain = self.chains.get(target_chain_name)

        if chain is None:
            # Fallback: stay in current chain or default to greeting
            chain = self.chains.get(state.current_chain)
            if chain is None:
                chain = self.chains.get(ChainName.GREETING)

            if chain is None:
                # No chains available - return error
                return ChainResult(
                    message="I'm sorry, I'm having trouble processing that. Can you try again?",
                    state=state,
                    chain_complete=False,
                )

        # Update state to reflect current chain
        if target_chain_name != state.current_chain:
            state.transition_to(target_chain_name)

        # Invoke the chain
        result = chain.invoke(state, user_input)

        # Add assistant response to history (if there's a message)
        if result.message:
            result.state.add_message("assistant", result.message)

        # Handle chain completion and auto-transition
        if result.chain_complete and result.next_chain:
            result.state.transition_to(result.next_chain)

            # If the chain says it doesn't need user input, auto-invoke the next chain
            if not result.needs_user_input:
                next_chain = self.chains.get(result.next_chain)
                if next_chain:
                    # Invoke the next chain with empty input to trigger its initial message
                    next_result = next_chain.invoke(result.state, "")
                    if next_result.message:
                        next_result.state.add_message("assistant", next_result.message)
                    return next_result

        return result

    def _handle_post_confirmation(self, state: OrderState, user_input: str) -> ChainResult:
        """
        Handle messages that come in after an order is already confirmed.

        This prevents the bot from restarting the order flow or greeting
        after a completed order.
        """
        input_lower = user_input.lower().strip()
        order_number = state.checkout.order_number or "your order"
        short_number = order_number[-2:] if len(order_number) >= 2 else order_number

        # Check if user wants to start a new order
        if re.search(r"\b(new order|another order|start over|order again)\b", input_lower):
            # Reset state for new order but keep customer info
            customer_name = state.customer_name
            customer_phone = state.customer_phone
            customer_email = state.customer_email

            from .state import OrderState as NewOrderState
            new_state = NewOrderState(
                customer_name=customer_name,
                customer_phone=customer_phone,
                customer_email=customer_email,
            )
            return ChainResult(
                message="Sure! Let's start a new order. Will this be for pickup or delivery?",
                state=new_state,
                chain_complete=True,
                next_chain=ChainName.ADDRESS,
            )

        # Check for common post-order questions
        if re.search(r"\b(when|how long|ready|status|eta)\b", input_lower):
            if state.address.order_type == "delivery":
                return ChainResult(
                    message=f"Your order {short_number} should arrive in about 30-45 minutes. Thanks for your patience!",
                    state=state,
                    chain_complete=True,
                )
            else:
                return ChainResult(
                    message=f"Your order {short_number} should be ready for pickup in about 10-15 minutes.",
                    state=state,
                    chain_complete=True,
                )

        if re.search(r"\b(thank|thanks|bye|goodbye)\b", input_lower):
            return ChainResult(
                message="You're welcome! Enjoy your order, and we hope to see you again soon!",
                state=state,
                chain_complete=True,
            )

        # Default: remind them their order is confirmed
        return ChainResult(
            message=f"Your order {short_number} is already confirmed and being prepared. Is there anything else I can help you with?",
            state=state,
            chain_complete=True,
        )

    def get_suggested_responses(self, state: OrderState) -> list[str]:
        """
        Get suggested quick responses for the current state.

        Useful for showing buttons/chips to the user.

        Args:
            state: Current order state

        Returns:
            List of suggested response strings
        """
        current_chain = self.chains.get(state.current_chain)
        if not current_chain:
            return []

        # Get awaiting field to provide context-specific suggestions
        awaiting = current_chain.get_awaiting_field(state)

        # Default suggestions based on chain
        suggestions: dict[ChainName, list[str]] = {
            ChainName.GREETING: ["I'd like to order", "What's on the menu?", "Delivery please"],
            ChainName.ADDRESS: ["Pickup", "Delivery"],
            ChainName.BAGEL: ["Everything bagel", "Plain bagel", "That's all"],
            ChainName.COFFEE: ["Large coffee", "Iced latte", "No coffee, thanks"],
            ChainName.CHECKOUT: ["Looks good", "Add something else", "Cancel order"],
        }

        return suggestions.get(state.current_chain, [])
