"""
Handler Registry for State Machine.

Centralizes handler initialization and context distribution.
Provides a cleaner interface for managing the handler lifecycle.
"""

import logging
from typing import Any, Callable

from .context import OrderContext
from .handler_config import HandlerConfig
from .handlers import HandlerFactory, HandlerCallbacks

logger = logging.getLogger(__name__)


class HandlerRegistry:
    """
    Registry for all handlers in the state machine.

    Provides:
    - Centralized initialization of all handlers
    - Context distribution to handlers that need it
    - Easy access to handlers by name
    """

    def __init__(
        self,
        config: HandlerConfig,
        transition_callback: Callable,
        handle_taking_items_with_parsed: Callable,
        configure_next_incomplete_item: Callable,
    ):
        """Initialize the handler registry.

        Args:
            config: Shared handler configuration
            transition_callback: Callback for transitioning to next slot
            handle_taking_items_with_parsed: Callback for handling parsed items
            configure_next_incomplete_item: Callback for configuring next item
        """
        self._config = config

        # Create callbacks dataclass
        self._callbacks = HandlerCallbacks(
            transition_to_next_slot=transition_callback,
            configure_next_incomplete_item=configure_next_incomplete_item,
            handle_taking_items_with_parsed=handle_taking_items_with_parsed,
        )

        # Build all handlers using factory
        factory = HandlerFactory(config, self._callbacks)
        self._handlers = factory.build_all()
        self._context_handlers = factory.get_context_handlers()
        self._menu_data_handler_names = factory.get_menu_data_handlers()

    def distribute_context(self, ctx: OrderContext) -> None:
        """Distribute context to all handlers that need it.

        Args:
            ctx: The order context to distribute
        """
        for name in self._context_handlers:
            handler = self._handlers.get(name)
            if handler and hasattr(handler, "set_context"):
                handler.set_context(ctx)

    def get_menu_data_handlers(self) -> list:
        """Get handlers that need menu_data updates.

        Returns:
            List of handlers that have a menu_data property
        """
        return [
            self._handlers[name]
            for name in self._menu_data_handler_names
            if name in self._handlers
        ]

    def __getattr__(self, name: str) -> Any:
        """Provide handler access by name (e.g., registry.checkout, registry.taking_items)."""
        handlers = self.__dict__.get("_handlers", {})
        if name in handlers:
            return handlers[name]
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")
