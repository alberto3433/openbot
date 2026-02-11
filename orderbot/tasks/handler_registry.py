"""
Handler Registry for State Machine.

Centralizes handler initialization and context distribution.
Provides a cleaner interface for managing the handler lifecycle.
"""

import logging
from typing import Any, Callable, TYPE_CHECKING

from .context import OrderContext
from .handler_config import HandlerConfig
from .handlers import HandlerFactory, HandlerCallbacks

if TYPE_CHECKING:
    from .checkout_handler import CheckoutHandler
    from .checkout_utils_handler import CheckoutUtilsHandler
    from .store_info_handler import StoreInfoHandler
    from .recommendation_handler import RecommendationHandler
    from .menu_options_inquiry_handler import MenuOptionsInquiryHandler
    from .menu_inquiry_handler import MenuInquiryHandler
    from .menu_pagination_handler import MenuPaginationHandler
    from .order_utils_handler import OrderUtilsHandler
    from .item_adder_handler import ItemAdderHandler
    from .item_lookup_handler import ItemLookupHandler
    from .modifier_change_handler import ModifierChangeHandler
    from .config_helper_handler import ConfigHelperHandler
    from .config_cancellation_handler import ConfigCancellationHandler
    from .config import MenuItemConfigHandler
    from .configuring_item_handler import ConfiguringItemHandler
    from .config_selection_handler import ConfigSelectionHandler
    from .config_modification_handler import ConfigModificationHandler
    from .taking_items_handler import TakingItemsHandler
    from .slot_orchestration_handler import SlotOrchestrationHandler
    from .order_history_handler import OrderHistoryHandler

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

    # Handler accessors
    @property
    def slot_orchestration(self) -> "SlotOrchestrationHandler":
        return self._handlers["slot_orchestration"]

    @property
    def checkout(self) -> "CheckoutHandler":
        return self._handlers["checkout"]

    @property
    def checkout_utils(self) -> "CheckoutUtilsHandler":
        return self._handlers["checkout_utils"]

    @property
    def store_info(self) -> "StoreInfoHandler":
        return self._handlers["store_info"]

    @property
    def menu_inquiry(self) -> "MenuInquiryHandler":
        return self._handlers["menu_inquiry"]

    @property
    def order_utils(self) -> "OrderUtilsHandler":
        return self._handlers["order_utils"]

    @property
    def item_lookup(self) -> "ItemLookupHandler":
        return self._handlers["item_lookup"]

    @property
    def item_adder(self) -> "ItemAdderHandler":
        return self._handlers["item_adder"]

    @property
    def modifier_change(self) -> "ModifierChangeHandler":
        return self._handlers["modifier_change"]

    @property
    def config_helper(self) -> "ConfigHelperHandler":
        return self._handlers["config_helper"]

    @property
    def menu_item(self) -> "MenuItemConfigHandler":
        return self._handlers["menu_item"]

    @property
    def configuring_item(self) -> "ConfiguringItemHandler":
        return self._handlers["configuring_item"]

    @property
    def config_selection(self) -> "ConfigSelectionHandler":
        return self._handlers["config_selection"]

    @property
    def config_modification(self) -> "ConfigModificationHandler":
        return self._handlers["config_modification"]

    @property
    def taking_items(self) -> "TakingItemsHandler":
        return self._handlers["taking_items"]

    @property
    def order_history(self) -> "OrderHistoryHandler":
        return self._handlers["order_history"]
