"""
Handler Registry for State Machine.

Centralizes handler initialization and context distribution.
Provides a cleaner interface for managing the handler lifecycle.
"""

import logging
from typing import Any, Callable, TYPE_CHECKING

from .context import OrderContext
from .handler_config import HandlerConfig

if TYPE_CHECKING:
    from .checkout_handler import CheckoutHandler
    from .checkout_utils_handler import CheckoutUtilsHandler
    from .store_info_handler import StoreInfoHandler
    from .menu_inquiry_handler import MenuInquiryHandler
    from .order_utils_handler import OrderUtilsHandler
    from .item_adder_handler import ItemAdderHandler
    from .modifier_change_handler import ModifierChangeHandler
    from .config_helper_handler import ConfigHelperHandler
    from .menu_item_config_handler import MenuItemConfigHandler
    from .configuring_item_handler import ConfiguringItemHandler
    from .taking_items_handler import TakingItemsHandler
    from .slot_orchestration_handler import SlotOrchestrationHandler

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
        self._transition_callback = transition_callback
        self._handle_taking_items_with_parsed = handle_taking_items_with_parsed
        self._configure_next_incomplete_item = configure_next_incomplete_item

        # Handler storage
        self._handlers: dict[str, Any] = {}

        # Initialize all handlers
        self._initialize_handlers()

    def _initialize_handlers(self) -> None:
        """Initialize all handlers in dependency order."""
        from .checkout_handler import CheckoutHandler
        from .checkout_utils_handler import CheckoutUtilsHandler
        from .store_info_handler import StoreInfoHandler
        from .menu_inquiry_handler import MenuInquiryHandler
        from .order_utils_handler import OrderUtilsHandler
        from .item_adder_handler import ItemAdderHandler
        from .modifier_change_handler import ModifierChangeHandler
        from .config_helper_handler import ConfigHelperHandler
        from .menu_item_config_handler import MenuItemConfigHandler
        from .configuring_item_handler import ConfiguringItemHandler
        from .taking_items_handler import TakingItemsHandler
        from .slot_orchestration_handler import SlotOrchestrationHandler

        # Phase 1: Slot orchestration (no dependencies)
        self._handlers["slot_orchestration"] = SlotOrchestrationHandler()

        # Phase 2: Core utility handlers
        self._handlers["checkout"] = CheckoutHandler(
            config=self._config,
            transition_callback=self._transition_callback,
        )
        self._handlers["checkout_utils"] = CheckoutUtilsHandler(
            config=self._config,
            transition_to_next_slot=self._transition_callback,
        )

        # Wire get_next_question callback
        self._config.get_next_question = self._handlers["checkout_utils"].get_next_question

        # Phase 3: Independent handlers
        self._handlers["store_info"] = StoreInfoHandler(menu_data=self._config.menu_data)
        self._handlers["menu_inquiry"] = MenuInquiryHandler(config=self._config)
        self._handlers["order_utils"] = OrderUtilsHandler(
            config=self._config,
            build_order_summary=self._handlers["checkout_utils"].build_order_summary,
        )
        self._handlers["item_adder"] = ItemAdderHandler(config=self._config)
        self._handlers["modifier_change"] = ModifierChangeHandler(config=self._config)
        self._handlers["config_helper"] = ConfigHelperHandler(
            config=self._config,
            modifier_change_handler=self._handlers["modifier_change"],
            configure_next_incomplete_item=self._configure_next_incomplete_item,
        )

        # Phase 4: Wire cross-handler callbacks
        self._handlers["checkout"].order_utils_handler = self._handlers["order_utils"]
        self._handlers["checkout"]._handle_taking_items_with_parsed = self._handle_taking_items_with_parsed

        # Phase 5: Dependent handlers
        self._handlers["menu_item"] = MenuItemConfigHandler(config=self._config)
        self._handlers["item_adder"].menu_item_handler = self._handlers["menu_item"]
        self._handlers["checkout_utils"]._configure_next_incomplete_item = self._configure_next_incomplete_item

        self._handlers["configuring_item"] = ConfiguringItemHandler(
            config_helper_handler=self._handlers["config_helper"],
            checkout_utils_handler=self._handlers["checkout_utils"],
            modifier_change_handler=self._handlers["modifier_change"],
            item_adder_handler=self._handlers["item_adder"],
            menu_item_handler=self._handlers["menu_item"],
        )
        self._handlers["taking_items"] = TakingItemsHandler(
            config=self._config,
            item_adder_handler=self._handlers["item_adder"],
            menu_inquiry_handler=self._handlers["menu_inquiry"],
            store_info_handler=self._handlers["store_info"],
            checkout_utils_handler=self._handlers["checkout_utils"],
            checkout_handler=self._handlers["checkout"],
            configure_next_incomplete_item=self._configure_next_incomplete_item,
        )

        # Phase 6: Final cross-handler wiring
        self._handlers["configuring_item"].taking_items_handler = self._handlers["taking_items"]
        self._handlers["menu_item"].process_pending_parsed_items = (
            self._handlers["configuring_item"]._process_pending_parsed_items
        )

    def distribute_context(self, ctx: OrderContext) -> None:
        """Distribute context to all handlers that need it.

        Args:
            ctx: The order context to distribute
        """
        context_handlers = [
            "checkout",
            "store_info",
            "order_utils",
            "checkout_utils",
            "taking_items",
            "item_adder",
        ]

        for name in context_handlers:
            handler = self._handlers.get(name)
            if handler and hasattr(handler, "set_context"):
                handler.set_context(ctx)

    def get_menu_data_handlers(self) -> list:
        """Get handlers that need menu_data updates.

        Returns:
            List of handlers that have a menu_data property
        """
        menu_data_handlers = [
            "store_info",
            "menu_inquiry",
            "item_adder",
            "taking_items",
        ]
        return [self._handlers[name] for name in menu_data_handlers if name in self._handlers]

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
    def taking_items(self) -> "TakingItemsHandler":
        return self._handlers["taking_items"]
