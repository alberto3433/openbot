"""
Handler Configuration for State Machine Handlers.

This module provides a centralized configuration dataclass that is shared
across all handler classes, reducing boilerplate in handler initialization.
"""

from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

from .mixins import MenuDataMixin, ContextMixin, CallbackMixin

if TYPE_CHECKING:
    from .models import OrderTask, ItemTask
    from .schemas import StateMachineResult
    from .context import OrderContext

@dataclass
class HandlerConfig:
    """
    Shared configuration for state machine handlers.

    This dataclass consolidates common dependencies that are passed to most
    handlers, reducing the boilerplate of having to pass 5-10 parameters
    to each handler's __init__.

    Attributes:
        model: LLM model name for AI-powered parsing (default: gpt-4o-mini)
        pricing: PricingEngine instance for price lookups
        menu_lookup: MenuLookup instance for menu item lookups
        menu_data: Raw menu data dictionary (alternative to menu_lookup)
        store_info: Store information dictionary
        message_builder: MessageBuilder for constructing bot messages
        get_next_question: Callback to determine the next question to ask
        check_redirect: Callback to check if user input should redirect flow
    """

    # Core dependencies
    model: str = "gpt-4o-mini"
    pricing: "PricingEngine | None" = None
    menu_lookup: "MenuLookup | None" = None
    menu_data: dict | None = None
    store_info: dict | None = None
    message_builder: "MessageBuilder | None" = None

    # Common callbacks
    get_next_question: Callable[["OrderTask"], "StateMachineResult"] | None = None
    check_redirect: Callable[
        [str, "ItemTask", "OrderTask", str, "set[str] | None"], "StateMachineResult | None"
    ] | None = None

    def with_overrides(self, **kwargs) -> "HandlerConfig":
        """
        Create a new HandlerConfig with some values overridden.

        This is useful when you need a slightly modified config for a
        specific handler without mutating the original.

        Example:
            base_config = HandlerConfig(model="gpt-4o-mini", pricing=engine)
            coffee_config = base_config.with_overrides(model="gpt-4o")
        """
        from dataclasses import asdict
        current = asdict(self)
        current.update(kwargs)
        return HandlerConfig(**current)


class BaseHandler(MenuDataMixin):
    """
    Base class for state machine handlers.

    Provides common initialization logic to reduce boilerplate across handlers.
    Handlers inherit from this and call super().__init__(config).

    Attributes extracted from config:
        model: LLM model name (default: "gpt-4o-mini")
        pricing: PricingEngine instance
        menu_lookup: MenuLookup instance
        menu_data: Raw menu data dictionary
        store_info: Store information dictionary
        message_builder: MessageBuilder instance
        _get_next_question: Callback for next question
        _check_redirect: Callback for redirect checks
    """

    def __init__(self, config: "HandlerConfig"):
        """
        Initialize base handler with config.

        Args:
            config: HandlerConfig with shared dependencies.
        """
        self.model = config.model
        self.pricing = config.pricing
        self.menu_lookup = config.menu_lookup
        self._menu_data = config.menu_data or {}
        self._store_info = config.store_info
        self.message_builder = config.message_builder
        self._get_next_question = config.get_next_question
        self._check_redirect = config.check_redirect

    @property
    def store_info(self) -> dict | None:
        """Get store info dictionary."""
        return self._store_info

    @store_info.setter
    def store_info(self, value: dict | None) -> None:
        """Set store info dictionary."""
        self._store_info = value


class BaseStateHandler(BaseHandler, ContextMixin, CallbackMixin):
    """
    Extended base class for state machine handlers with context and callbacks.

    Combines BaseHandler with ContextMixin and CallbackMixin to provide:
    - All BaseHandler functionality (model, pricing, menu_lookup, etc.)
    - Per-request context management (returning_customer, is_repeat_order, etc.)
    - Transition and configuration callbacks

    Use this when a handler needs context propagation and/or transition callbacks.
    For simpler handlers that only need base dependencies, use BaseHandler directly.

    Attributes inherited from BaseHandler:
        model: LLM model name
        pricing: PricingEngine instance
        menu_lookup: MenuLookup instance
        menu_data: Raw menu data dictionary
        store_info: Store information dictionary
        message_builder: MessageBuilder instance

    Attributes from ContextMixin:
        _returning_customer: Returning customer data
        _is_repeat_order: Whether this is a repeat order
        _last_order_type: Last order type (pickup/delivery)

    Attributes from CallbackMixin:
        _transition_to_next_slot: Callback to transition order state
        _configure_next_incomplete_item: Callback to get next config question
    """

    def __init__(
        self,
        config: "HandlerConfig",
        transition_callback: Callable[["OrderTask"], None] | None = None,
        configure_callback: Callable[["OrderTask"], "StateMachineResult"] | None = None,
    ):
        """
        Initialize state handler with config and callbacks.

        Args:
            config: HandlerConfig with shared dependencies.
            transition_callback: Callback to transition order to next slot.
            configure_callback: Callback to get config question for incomplete items.
        """
        super().__init__(config)

        # Initialize ContextMixin attributes
        self._returning_customer: dict | None = None
        self._is_repeat_order: bool = False
        self._last_order_type: str | None = None

        # Initialize CallbackMixin attributes
        self._transition_to_next_slot = transition_callback
        self._configure_next_incomplete_item = configure_callback

    def set_context(self, ctx: "OrderContext") -> None:
        """Set per-request context from unified OrderContext.

        Extends ContextMixin.set_context to also update menu_data from context.

        Args:
            ctx: OrderContext with store info, returning customer data, etc.
        """
        # Call parent to set common context attributes
        super().set_context(ctx)
        # Also update menu_data from context if provided
        if ctx.menu_data:
            self._menu_data = ctx.menu_data
