"""
Base chain class and interfaces for the conversation flow architecture.

All domain-specific chains inherit from BaseChain and implement
the invoke method to handle their specific conversation flow.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional

from .state import OrderState, ChainResult, ChainName


class BaseChain(ABC):
    """
    Abstract base class for all conversation chains.

    Each chain handles a specific domain (bagels, coffee, address, etc.)
    and is responsible for:
    1. Processing user input relevant to its domain
    2. Updating the appropriate sub-state
    3. Generating appropriate responses
    4. Signaling when its work is complete
    """

    chain_name: ChainName  # Must be set by subclass

    def __init__(self, menu_data: Optional[dict] = None, llm: Optional[Any] = None):
        """
        Initialize the chain.

        Args:
            menu_data: Menu data for item lookups and pricing
            llm: Optional LLM client for natural language understanding
        """
        self.menu_data = menu_data or {}
        self.llm = llm

    @abstractmethod
    def invoke(self, state: OrderState, user_input: str) -> ChainResult:
        """
        Process user input and return updated state with response.

        This is the main entry point for the chain. Implementations should:
        1. Parse/understand the user input
        2. Update the relevant sub-state
        3. Determine what to ask next or if complete
        4. Return a ChainResult with the response and updated state

        Args:
            state: Current order state
            user_input: User's message text

        Returns:
            ChainResult containing response message and updated state
        """
        pass

    def get_prompt_context(self, state: OrderState) -> dict:
        """
        Get context for LLM prompts.

        Override in subclasses to provide domain-specific context
        like current item state, available options, etc.

        Args:
            state: Current order state

        Returns:
            Dictionary of context variables for prompt templates
        """
        return {
            "current_chain": self.chain_name.value,
            "has_items": state.has_items(),
            "item_count": state.get_item_count(),
        }

    def can_handle(self, user_input: str, state: OrderState) -> bool:
        """
        Check if this chain can handle the given input.

        Used by Orchestrator to help with routing decisions.
        Default implementation returns True if this is the current chain.

        Args:
            user_input: User's message text
            state: Current order state

        Returns:
            True if this chain should handle the input
        """
        return state.current_chain == self.chain_name

    def get_awaiting_field(self, state: OrderState) -> Optional[str]:
        """
        Get the field this chain is currently waiting for.

        Returns None if not waiting for specific input.

        Args:
            state: Current order state

        Returns:
            Field name or None
        """
        return None


class ChainRegistry:
    """
    Registry for chain instances.

    The Orchestrator uses this to look up chains by name.
    """

    def __init__(self):
        self._chains: dict[ChainName, BaseChain] = {}

    def register(self, chain: BaseChain) -> None:
        """Register a chain instance."""
        self._chains[chain.chain_name] = chain

    def get(self, chain_name: ChainName) -> Optional[BaseChain]:
        """Get a chain by name."""
        return self._chains.get(chain_name)

    def get_all(self) -> dict[ChainName, BaseChain]:
        """Get all registered chains."""
        return self._chains.copy()

    def __contains__(self, chain_name: ChainName) -> bool:
        return chain_name in self._chains
