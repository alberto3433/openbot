"""
Handler Factory - Builds handlers in dependency order.

This factory encapsulates the complex handler initialization logic,
building handlers in the correct dependency order and wiring cross-handler
references. It replaces the manual wiring in HandlerRegistry._initialize_handlers.
"""

import logging
from typing import Any, TYPE_CHECKING

from ..handler_config import HandlerConfig
from .handler_callbacks import HandlerCallbacks

if TYPE_CHECKING:
    from ..context import OrderContext

logger = logging.getLogger(__name__)


class HandlerFactory:
    """
    Factory for building state machine handlers.

    Builds handlers in dependency order:
    1. Independent handlers (no dependencies)
    2. Utility handlers (depend on config only)
    3. Cross-dependent handlers (depend on each other)
    4. Top-level handlers (depend on multiple others)

    Usage:
        factory = HandlerFactory(config, callbacks)
        handlers = factory.build_all()
    """

    def __init__(self, config: HandlerConfig, callbacks: HandlerCallbacks):
        """Initialize the factory with config and callbacks.

        Args:
            config: Shared handler configuration.
            callbacks: Callbacks for state transitions and processing.
        """
        self._config = config
        self._callbacks = callbacks
        self._handlers: dict[str, Any] = {}

    def build_all(self) -> dict[str, Any]:
        """Build all handlers in dependency order.

        Returns:
            Dictionary of handler name -> handler instance.
        """
        self._build_phase_1_independent()
        self._build_phase_2_utilities()
        self._build_phase_3_core()
        self._build_phase_4_config()
        self._build_phase_5_top_level()
        self._wire_cross_references()

        return self._handlers

    def _build_phase_1_independent(self) -> None:
        """Phase 1: Build handlers with no dependencies."""
        from ..slot_orchestration_handler import SlotOrchestrationHandler
        from ..disambiguation_handler import DisambiguationHandler
        from ..store_and_scheduling_handler import StoreAndSchedulingHandler

        self._handlers["slot_orchestration"] = SlotOrchestrationHandler()
        self._handlers["disambiguation"] = DisambiguationHandler()
        self._handlers["store_and_scheduling"] = StoreAndSchedulingHandler()

    def _build_phase_2_utilities(self) -> None:
        """Phase 2: Build utility handlers that depend only on config."""
        from ..checkout_handler import CheckoutHandler
        from ..checkout_utils_handler import CheckoutUtilsHandler
        from ..recommendation_handler import RecommendationHandler
        from ..menu_options_inquiry_handler import MenuOptionsInquiryHandler
        from ..order_utils_handler import OrderUtilsHandler

        self._handlers["checkout"] = CheckoutHandler(
            config=self._config,
            transition_callback=self._callbacks.transition_to_next_slot,
        )
        self._handlers["checkout_utils"] = CheckoutUtilsHandler(
            config=self._config,
            transition_to_next_slot=self._callbacks.transition_to_next_slot,
        )

        # Wire get_next_question callback
        # NOTE: We still need to set this on config because BaseHandler extracts it
        # during __init__, so handlers built later will have the callback available.
        self._callbacks.get_next_question = self._handlers["checkout_utils"].get_next_question
        self._config.get_next_question = self._handlers["checkout_utils"].get_next_question

        self._handlers["recommendation"] = RecommendationHandler(
            menu_data=self._config.menu_data,
        )
        self._handlers["menu_options_inquiry"] = MenuOptionsInquiryHandler(
            menu_data=self._config.menu_data,
        )
        self._handlers["order_utils"] = OrderUtilsHandler(
            config=self._config,
            build_order_summary=self._handlers["checkout_utils"].build_order_summary,
        )

    def _build_phase_3_core(self) -> None:
        """Phase 3: Build core handlers that depend on utilities."""
        from ..store_info_handler import StoreInfoHandler
        from ..menu_pagination_handler import MenuPaginationHandler
        from ..menu_inquiry_handler import MenuInquiryHandler
        from ..item_lookup_handler import ItemLookupHandler
        from ..item_adder_handler import ItemAdderHandler
        from ..modifier_change_handler import ModifierChangeHandler
        from ..order_history_handler import OrderHistoryHandler

        self._handlers["store_info"] = StoreInfoHandler(
            menu_data=self._config.menu_data,
            recommendation_handler=self._handlers["recommendation"],
            menu_options_handler=self._handlers["menu_options_inquiry"],
        )
        self._handlers["menu_pagination"] = MenuPaginationHandler(
            menu_data=self._config.menu_data,
        )
        self._handlers["menu_inquiry"] = MenuInquiryHandler(
            config=self._config,
            pagination_handler=self._handlers["menu_pagination"],
        )

        # Item handlers
        self._handlers["item_lookup"] = ItemLookupHandler(
            menu_lookup=self._config.menu_lookup,
            disambiguation_handler=self._handlers["disambiguation"],
        )
        self._handlers["item_adder"] = ItemAdderHandler(
            config=self._config,
            item_lookup_handler=self._handlers["item_lookup"],
        )
        self._handlers["item_adder"].disambiguation_handler = self._handlers["disambiguation"]

        self._handlers["modifier_change"] = ModifierChangeHandler(config=self._config)
        self._handlers["order_history"] = OrderHistoryHandler(
            checkout_handler=self._handlers["checkout"],
        )

    def _build_phase_4_config(self) -> None:
        """Phase 4: Build configuration handlers."""
        from ..config_cancellation_handler import ConfigCancellationHandler
        from ..config_helper_handler import ConfigHelperHandler
        from ..config import MenuItemConfigHandler
        from ..config_selection_handler import ConfigSelectionHandler
        from ..config_modification_handler import ConfigModificationHandler
        from ..bundle_modification_handler import BundleModificationHandler
        from ..modifier_addition_handler import ModifierAdditionHandler
        from ..order_modification_handler import OrderModificationHandler

        self._handlers["config_cancellation"] = ConfigCancellationHandler(
            configure_next_incomplete_item=self._callbacks.configure_next_incomplete_item,
            pricing=self._config.pricing,
        )
        self._handlers["config_helper"] = ConfigHelperHandler(
            config=self._config,
            modifier_change_handler=self._handlers["modifier_change"],
            configure_next_incomplete_item=self._callbacks.configure_next_incomplete_item,
            cancellation_handler=self._handlers["config_cancellation"],
        )
        self._handlers["menu_item"] = MenuItemConfigHandler(config=self._config)

        self._handlers["config_selection"] = ConfigSelectionHandler(
            item_adder_handler=self._handlers["item_adder"],
            menu_item_handler=self._handlers["menu_item"],
        )
        self._handlers["config_modification"] = ConfigModificationHandler(
            config_helper_handler=self._handlers["config_helper"],
            checkout_utils_handler=self._handlers["checkout_utils"],
            modifier_change_handler=self._handlers["modifier_change"],
            item_adder_handler=self._handlers["item_adder"],
        )
        self._handlers["bundle_modification"] = BundleModificationHandler(
            config_helper_handler=self._handlers["config_helper"],
            checkout_utils_handler=self._handlers["checkout_utils"],
            modifier_change_handler=self._handlers["modifier_change"],
        )
        self._handlers["modifier_addition"] = ModifierAdditionHandler(
            config_helper_handler=self._handlers["config_helper"],
            checkout_utils_handler=self._handlers["checkout_utils"],
            modifier_change_handler=self._handlers["modifier_change"],
            item_adder_handler=self._handlers["item_adder"],
        )
        self._handlers["order_modification"] = OrderModificationHandler(
            message_builder=self._config.message_builder,
            config_helper_handler=self._handlers["config_helper"],
            configure_next_incomplete_item=self._callbacks.configure_next_incomplete_item,
        )

    def _build_phase_5_top_level(self) -> None:
        """Phase 5: Build top-level handlers that orchestrate others."""
        from ..configuring_item_handler import ConfiguringItemHandler
        from ..taking_items_handler import TakingItemsHandler

        self._handlers["configuring_item"] = ConfiguringItemHandler(
            config_helper_handler=self._handlers["config_helper"],
            checkout_utils_handler=self._handlers["checkout_utils"],
            modifier_change_handler=self._handlers["modifier_change"],
            item_adder_handler=self._handlers["item_adder"],
            menu_item_handler=self._handlers["menu_item"],
            config_selection_handler=self._handlers["config_selection"],
            config_modification_handler=self._handlers["config_modification"],
            bundle_modification_handler=self._handlers["bundle_modification"],
            modifier_addition_handler=self._handlers["modifier_addition"],
        )
        self._handlers["taking_items"] = TakingItemsHandler(
            config=self._config,
            item_adder_handler=self._handlers["item_adder"],
            menu_inquiry_handler=self._handlers["menu_inquiry"],
            store_info_handler=self._handlers["store_info"],
            checkout_utils_handler=self._handlers["checkout_utils"],
            checkout_handler=self._handlers["checkout"],
            configure_next_incomplete_item=self._callbacks.configure_next_incomplete_item,
        )

    def _wire_cross_references(self) -> None:
        """Wire cross-handler references that couldn't be done during construction.

        These are circular dependencies that require both handlers to exist
        before they can be wired together.
        """
        # Wire back-references
        self._handlers["menu_pagination"].menu_inquiry_handler = self._handlers["menu_inquiry"]
        self._handlers["config_cancellation"].config_helper_handler = self._handlers["config_helper"]
        self._handlers["checkout"].order_utils_handler = self._handlers["order_utils"]
        self._handlers["checkout"]._handle_taking_items_with_parsed = (
            self._callbacks.handle_taking_items_with_parsed
        )

        # Wire taking_items handler reference
        self._handlers["configuring_item"].taking_items_handler = self._handlers["taking_items"]
        self._handlers["config_selection"].taking_items_handler = self._handlers["taking_items"]
        self._handlers["config_modification"].taking_items_handler = self._handlers["taking_items"]
        self._handlers["bundle_modification"].taking_items_handler = self._handlers["taking_items"]
        self._handlers["modifier_addition"].taking_items_handler = self._handlers["taking_items"]

        # Wire menu_item handler references
        self._handlers["item_adder"].menu_item_handler = self._handlers["menu_item"]
        self._handlers["checkout_utils"]._configure_next_incomplete_item = (
            self._callbacks.configure_next_incomplete_item
        )
        self._handlers["menu_item"].process_pending_parsed_items = (
            self._handlers["configuring_item"]._process_pending_parsed_items
        )

        # Wire order_history_handler to taking_items' duplicate_handler
        self._handlers["taking_items"]._duplicate_handler.order_history_handler = (
            self._handlers["order_history"]
        )

    def get_context_handlers(self) -> list[str]:
        """Get names of handlers that need context distribution.

        Returns:
            List of handler names that have set_context method.
        """
        return [
            "checkout",
            "store_info",
            "store_and_scheduling",
            "order_utils",
            "checkout_utils",
            "taking_items",
            "item_adder",
            "order_history",
        ]

    def get_menu_data_handlers(self) -> list[str]:
        """Get names of handlers that need menu_data updates.

        Returns:
            List of handler names that have menu_data property.
        """
        return [
            "store_info",
            "recommendation",
            "menu_options_inquiry",
            "menu_inquiry",
            "menu_pagination",
            "item_lookup",
            "item_adder",
            "taking_items",
        ]
