"""
Configuration Helper Handler for Order State Machine.

This module provides configuration utilities and delegates to specialized handlers:
- ConfigSideChoiceHandler: Side choice / component slot handling
- ConfigChangeHandler: Modifier change requests and clarifications
- ConfigCancellationHandler: Cancellation during config

The main utility here is get_current_config_question() which looks up
the current question text from the database.
"""

import logging
from typing import Callable, TYPE_CHECKING

from .models import OrderTask, MenuItemTask, ItemTask
from .pending_fields import PendingField
from .schemas import StateMachineResult
from .handler_config import HandlerConfig
from orderbot.cache import menu_cache
from orderbot.exceptions import MenuDataNotLoadedError
from .handler_utils import is_configurable_menu_item
from .config_side_choice_handler import SIDE_SLOT_NAME

if TYPE_CHECKING:
    from .modifier_change_handler import ModifierChangeHandler
    from .config_cancellation_handler import ConfigCancellationHandler
    from .config_side_choice_handler import ConfigSideChoiceHandler
    from .config_change_handler import ConfigChangeHandler

logger = logging.getLogger(__name__)


class ConfigHelperHandler:
    """
    Configuration utilities and delegation hub.

    Provides:
    - get_current_config_question(): Database lookup for question text
    - Delegation to specialized handlers for side choice, changes, cancellation
    """

    def __init__(
        self,
        config: HandlerConfig,
        modifier_change_handler: "ModifierChangeHandler | None" = None,
        configure_next_incomplete_item: Callable[[OrderTask], StateMachineResult] | None = None,
        cancellation_handler: "ConfigCancellationHandler | None" = None,
    ):
        """
        Initialize the config helper handler.

        Args:
            config: HandlerConfig with shared dependencies.
            modifier_change_handler: Handler for modifier changes.
            configure_next_incomplete_item: Callback to get config question for incomplete items.
            cancellation_handler: Handler for cancellation during config.
        """
        self.config = config
        self.model = config.model
        self._get_next_question = config.get_next_question

        # Specialized handlers (lazily initialized)
        self._side_choice_handler: "ConfigSideChoiceHandler | None" = None
        self._change_handler: "ConfigChangeHandler | None" = None

        # Dependencies for specialized handlers
        self.modifier_change_handler = modifier_change_handler
        self._configure_next_incomplete_item = configure_next_incomplete_item
        self.cancellation_handler = cancellation_handler

    @property
    def side_choice_handler(self) -> "ConfigSideChoiceHandler":
        """Lazily initialize side choice handler."""
        if self._side_choice_handler is None:
            from .config_side_choice_handler import ConfigSideChoiceHandler
            self._side_choice_handler = ConfigSideChoiceHandler(self.config)
        return self._side_choice_handler

    @property
    def change_handler(self) -> "ConfigChangeHandler":
        """Lazily initialize change handler."""
        if self._change_handler is None:
            from .config_change_handler import ConfigChangeHandler
            self._change_handler = ConfigChangeHandler(
                modifier_change_handler=self.modifier_change_handler,
            )
        return self._change_handler

    def check_cancellation_during_config(
        self,
        user_input: str,
        current_item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Delegate to cancellation_handler for cancellation during config.

        This method is kept for backward compatibility.
        """
        if self.cancellation_handler:
            return self.cancellation_handler.check_cancellation_during_config(
                user_input, current_item, order
            )
        return None

    def get_current_config_question(
        self,
        order: OrderTask,
        item: ItemTask,
    ) -> str | None:
        """Get the current configuration question being asked.

        Uses database-driven question lookup for attribute-based fields.
        The pending_field format is "item_type:attr_slug" (e.g., "bagel:toasted").
        """
        field = order.pending_field
        if not field:
            return None

        # Handle customization_checkpoint - not attribute-based, uses a generic question
        if field == PendingField.CUSTOMIZATION_CHECKPOINT:
            return "any more changes?"

        # Handle side_choice - query component slots for the question text
        if field == PendingField.SIDE_CHOICE:
            if is_configurable_menu_item(item):
                side_slot = menu_cache.get_component_slot(item.menu_item_type, SIDE_SLOT_NAME)
                if side_slot and side_slot.get("prompt_text"):
                    return side_slot["prompt_text"]
            # Fallback to generic question if DB lookup fails
            return "Would you like a side with it?"

        # Parse pending_field to get item_type and attr_slug
        # Format: "item_type:attr_slug" (e.g., "bagel:toasted", "sized_beverage:size")
        if ":" in field:
            item_type, attr_slug = field.split(":", 1)
        else:
            # Legacy format without colon - try to infer from item
            if is_configurable_menu_item(item):
                item_type = item.menu_item_type
                attr_slug = field
            else:
                return None

        # Look up attribute from database
        try:
            attrs = menu_cache.get_item_type_attributes(item_type)
        except MenuDataNotLoadedError:
            logger.warning("Menu cache not loaded when getting question for %s:%s", item_type, attr_slug)
            return None

        attr = attrs.get(attr_slug)
        if not attr:
            return None

        # Use question_text from DB if available, otherwise generate
        db_question = attr.get("question_text")
        if db_question:
            return db_question

        # Generate question based on input_type and display_name
        input_type = attr.get("input_type", "single_select")
        attr_name = attr.get("display_name", attr_slug).lower()

        if input_type == "boolean":
            return f"Would you like it {attr_name}?"
        else:
            return f"What kind of {attr_name} would you like?"

    def handle_change_clarification_response(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Delegate to ConfigChangeHandler."""
        return self.change_handler.handle_change_clarification_response(user_input, order)

    def handle_modifier_change_request(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Delegate to ConfigChangeHandler."""
        return self.change_handler.handle_modifier_change_request(user_input, order)

    def handle_side_choice(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Delegate to ConfigSideChoiceHandler."""
        return self.side_choice_handler.handle_side_choice(user_input, item, order)
