"""
LangChain-based conversation flow architecture.

This package implements a modular, chain-based approach to handling
conversation flows for ordering. Each domain (bagels, coffee, address, etc.)
has its own chain that manages state and conversation flow.
"""

from .state import (
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
from .base import BaseChain, ChainRegistry
from .orchestrator import Orchestrator, Intent
from .greeting_chain import GreetingChain
from .address_chain import AddressChain
from .bagel_chain import BagelChain
from .coffee_chain import CoffeeChain
from .checkout_chain import CheckoutChain

from .adapter import (
    is_chain_orchestrator_enabled,
    dict_to_order_state,
    order_state_to_dict,
    get_orchestrator,
    process_message_with_chains,
    process_message_hybrid,
)
from .integration import (
    process_voice_message,
    process_chat_message,
)

__all__ = [
    # State models
    "AddressState",
    "BagelItem",
    "BagelOrderState",
    "CoffeeItem",
    "CoffeeOrderState",
    "CheckoutState",
    "OrderState",
    "ChainResult",
    "ChainName",
    "OrderStatus",
    # Base classes
    "BaseChain",
    "ChainRegistry",
    # Orchestrator
    "Orchestrator",
    "Intent",
    # Chains
    "GreetingChain",
    "AddressChain",
    "BagelChain",
    "CoffeeChain",
    "CheckoutChain",
    # Adapter functions
    "is_chain_orchestrator_enabled",
    "dict_to_order_state",
    "order_state_to_dict",
    "get_orchestrator",
    "process_message_with_chains",
    "process_message_hybrid",
    # Integration functions
    "process_voice_message",
    "process_chat_message",
]


def create_default_orchestrator(
    menu_data: dict = None,
    store_info: dict = None,
    llm=None,
) -> Orchestrator:
    """
    Factory function to create a fully configured Orchestrator.

    Args:
        menu_data: Menu data for pricing and item info
        store_info: Store information (hours, address, etc.)
        llm: Optional LLM client for complex understanding

    Returns:
        Configured Orchestrator instance
    """
    registry = ChainRegistry()

    # Create and register all chains
    registry.register(GreetingChain(menu_data=menu_data, llm=llm, store_info=store_info))
    registry.register(AddressChain(menu_data=menu_data, llm=llm, store_info=store_info))
    registry.register(BagelChain(menu_data=menu_data, llm=llm))
    registry.register(CoffeeChain(menu_data=menu_data, llm=llm))
    registry.register(CheckoutChain(menu_data=menu_data, llm=llm))

    return Orchestrator(chain_registry=registry, llm=llm, menu_data=menu_data)
