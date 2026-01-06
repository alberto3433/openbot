"""
Handler Configuration for State Machine Handlers.

This module provides a centralized configuration dataclass that is shared
across all handler classes, reducing boilerplate in handler initialization.
"""

from dataclasses import dataclass, field
from typing import Callable, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .models import OrderTask, ItemTask
    from .schemas import StateMachineResult
    from .pricing import PricingEngine
    from .menu_lookup import MenuLookup
    from ..services.message_builder import MessageBuilder


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
        [str, "ItemTask", "OrderTask", str], "StateMachineResult | None"
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


@dataclass
class HandlerCallbacks:
    """
    Handler-specific callbacks that vary between handlers.

    These are callbacks that are specific to certain handlers and aren't
    shared across all handlers. Handlers that need these can accept them
    as a separate parameter or include them in a handler-specific config.
    """

    # Item configuration callbacks
    get_item_by_id: Callable[["OrderTask", str], "ItemTask | None"] | None = None
    configure_coffee: Callable[["OrderTask"], "StateMachineResult"] | None = None
    configure_next_incomplete_bagel: Callable[["OrderTask"], "StateMachineResult"] | None = None
    configure_next_incomplete_coffee: Callable[["OrderTask"], "StateMachineResult"] | None = None
    configure_next_incomplete_speed_menu_bagel: Callable[["OrderTask"], "StateMachineResult"] | None = None

    # Flow transition callbacks
    transition_to_next_slot: Callable[["OrderTask"], None] | None = None
    transition_callback: Callable[..., Any] | None = None

    # Input processing callbacks
    process_taking_items_input: Callable[[str, "OrderTask"], "StateMachineResult"] | None = None
    handle_taking_items_with_parsed: Callable[..., "StateMachineResult"] | None = None

    # Menu callbacks
    list_by_pound_category: Callable[[str, "OrderTask"], "StateMachineResult"] | None = None
    build_order_summary: Callable[["OrderTask"], str] | None = None
