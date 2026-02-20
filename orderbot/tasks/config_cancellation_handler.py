"""
Configuration Cancellation Handler for Order State Machine.

Handles cancellation/removal requests during item configuration phase.
Extracted from config_helper_handler.py for better separation of concerns.
"""

import logging
from typing import Callable, TYPE_CHECKING

from .models import OrderTask, MenuItemTask
from .schemas import StateMachineResult
from .parsers import strip_conversational_fillers
from .pending_fields import PendingField
from .config_cancellation_matchers import (
    START_OVER_PATTERN,
    STANDALONE_CANCEL_PATTERN,
    CANCEL_ORDER_PATTERN,
    _extract_modifier_and_item_reference,
    _get_removable_modifiers,
    _item_matches,
    _extract_cancel_description,
    _should_defer_to_attribute_handler,
    _cancel_matches_item_or_type,
)
from .config_cancellation_operations import ConfigCancellationOperations

if TYPE_CHECKING:
    from .config_helper_handler import ConfigHelperHandler
    from .pricing import PricingEngine

logger = logging.getLogger(__name__)


class ConfigCancellationHandler:
    """
    Handles cancellation/removal requests during item configuration.

    When a user says "remove the coffee" or "cancel this" while being asked
    about coffee size, this handler processes the cancellation request instead
    of forcing the user to answer the configuration question.
    """

    def __init__(
        self,
        config_helper_handler: "ConfigHelperHandler | None" = None,
        configure_next_incomplete_item: Callable[[OrderTask], StateMachineResult] | None = None,
        pricing: "PricingEngine | None" = None,
    ) -> None:
        """
        Initialize the config cancellation handler.

        Args:
            config_helper_handler: Parent handler for getting current config question.
            configure_next_incomplete_item: Callback to get config question for incomplete items.
            pricing: PricingEngine for recalculating prices after modifier removal.
        """
        self.config_helper_handler = config_helper_handler
        self._configure_next_incomplete_item = configure_next_incomplete_item
        self.pricing = pricing
        self._operations = ConfigCancellationOperations(self)

    def check_cancellation_during_config(
        self,
        user_input: str,
        current_item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Check if user wants to cancel/remove items while in configuration phase.

        Returns StateMachineResult if cancellation handled, None otherwise.
        """
        user_input_stripped = strip_conversational_fillers(user_input.strip())

        # Check for "start over" - clears entire order
        if START_OVER_PATTERN.match(user_input_stripped):
            logger.info("Start over during config: '%s'", user_input_stripped)
            return self._handle_start_over(order)

        # Extract cancel target description
        cancel_desc = self._extract_cancel_description(user_input_stripped)
        if not cancel_desc:
            return None
        logger.info("Cancel request during config: '%s'", cancel_desc)

        # Defer to attribute handler if cancel matches pending attribute
        if self._should_defer_to_attribute_handler(cancel_desc, order):
            return None

        # Try removing an already-set attribute by name
        if isinstance(current_item, MenuItemTask):
            result = self._try_remove_attribute_by_name(cancel_desc, current_item, order)
            if result:
                return result

        # At customization checkpoint, defer unset attribute declines
        if order.pending_field in (
            PendingField.CUSTOMIZATION_CHECKPOINT,
            PendingField.CUSTOMIZATION_SELECTION,
        ) and isinstance(current_item, MenuItemTask):
            result = self._try_remove_attribute_by_name(
                cancel_desc, current_item, order, defer_if_unset=True
            )
            if result:
                return result

        # Cancel current item ("this", "it") or all items ("everything", "all")
        result = self._try_cancel_current_item(cancel_desc, current_item, order)
        if result:
            return result
        result = self._try_cancel_all_items(cancel_desc, order)
        if result:
            return result

        # Determine if cancel_desc refers to an item type or cart item name
        matches_item_type, matches_item_in_order = self._cancel_matches_item_or_type(
            cancel_desc, order
        )

        # Try modifier removal (skipped when cancel_desc matches an item)
        result = self._try_remove_modifier_by_reference(cancel_desc, current_item, order)
        if result:
            return result
        result = self._try_remove_modifier_on_current_item(
            cancel_desc, current_item, order, matches_item_type, matches_item_in_order,
        )
        if result:
            return result

        # Fall through: find and remove matching items
        return self._find_and_remove_matching_items(cancel_desc, current_item, order)

    # ---- Thin delegation wrappers for backward compatibility ----

    def _handle_start_over(self, order: OrderTask) -> StateMachineResult:
        return self._operations._handle_start_over(order)

    @staticmethod
    def _extract_cancel_description(user_input_stripped: str) -> str | None:
        return _extract_cancel_description(user_input_stripped)

    @staticmethod
    def _should_defer_to_attribute_handler(cancel_desc: str, order: OrderTask) -> bool:
        return _should_defer_to_attribute_handler(cancel_desc, order)

    @staticmethod
    def _cancel_matches_item_or_type(
        cancel_desc: str, order: OrderTask,
    ) -> tuple[bool, bool]:
        return _cancel_matches_item_or_type(cancel_desc, order)

    def _try_remove_attribute_by_name(
        self,
        cancel_desc: str,
        current_item: MenuItemTask,
        order: OrderTask,
        *,
        defer_if_unset: bool = False,
    ) -> StateMachineResult | None:
        return self._operations._try_remove_attribute_by_name(
            cancel_desc, current_item, order, defer_if_unset=defer_if_unset
        )

    def _try_cancel_current_item(
        self,
        cancel_desc: str,
        current_item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        return self._operations._try_cancel_current_item(cancel_desc, current_item, order)

    def _try_cancel_all_items(
        self,
        cancel_desc: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        return self._operations._try_cancel_all_items(cancel_desc, order)

    def _try_remove_modifier_by_reference(
        self,
        cancel_desc: str,
        current_item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        return self._operations._try_remove_modifier_by_reference(
            cancel_desc, current_item, order
        )

    def _try_remove_modifier_on_current_item(
        self,
        cancel_desc: str,
        current_item: MenuItemTask,
        order: OrderTask,
        matches_item_type: bool,
        matches_item_in_order: bool,
    ) -> StateMachineResult | None:
        return self._operations._try_remove_modifier_on_current_item(
            cancel_desc, current_item, order, matches_item_type, matches_item_in_order,
        )

    def _find_and_remove_matching_items(
        self,
        cancel_desc: str,
        current_item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        return self._operations._find_and_remove_matching_items(
            cancel_desc, current_item, order
        )

    def _get_current_config_question(
        self,
        order: OrderTask,
        item: MenuItemTask,
    ) -> str | None:
        return self._operations._get_current_config_question(order, item)

    def _config_removal_response(
        self,
        removal_msg: str,
        order: OrderTask,
        config_item: MenuItemTask,
        fallback_msg: str,
    ) -> StateMachineResult:
        return self._operations._config_removal_response(
            removal_msg, order, config_item, fallback_msg
        )
