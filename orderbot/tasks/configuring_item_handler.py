"""
Configuring Item Handler for Order State Machine.

This module handles the configuration of items (answering questions about
items being configured like size, style, toasted, spread, etc.).

Extracted from state_machine.py for better separation of concerns.
This handler acts as an orchestrator, delegating to specialized handlers:
- ConfigSelectionHandler: item/modifier selection and disambiguation
- ConfigModificationHandler: mid-config modifications ("can you make it X?", "add bacon")
- ConfigPriorityInterceptor: done ordering, cancellation, quantity changes
- ConfigModificationInterceptor: modifier changes, boolean matching, cross-attr matching
- ConfigFallbackInterceptor: new item parsing, off-topic, modifier inquiry
"""

import logging
from typing import Callable, TYPE_CHECKING

from .models import OrderTask, MenuItemTask, parse_pending_field
from .pending_fields import PendingField
from .schemas import StateMachineResult, Selection
from .checkout_messages import ErrorMessages
from .config_input_validation import is_valid_answer_for_pending_field
from orderbot.cache import menu_cache
from .config_side_choice_handler import SIDE_CHOICE_ATTR_SLUG
from .config_priority_interceptor import ConfigPriorityInterceptor
from .config_modification_interceptor import ConfigModificationInterceptor
from .config_fallback_interceptor import ConfigFallbackInterceptor
from .utils.text import format_english_list, normalize_text

if TYPE_CHECKING:
    from .config_helper_handler import ConfigHelperHandler
    from .checkout_utils_handler import CheckoutUtilsHandler
    from .modifier_change_handler import ModifierChangeHandler
    from .item_adder_handler import ItemAdderHandler
    from .config import MenuItemConfigHandler
    from .taking_items_handler import TakingItemsHandler
    from .config_selection_handler import ConfigSelectionHandler
    from .config_modification_handler import ConfigModificationHandler
    from .bundle_modification_handler import BundleModificationHandler
    from .modifier_addition_handler import ModifierAdditionHandler

logger = logging.getLogger(__name__)


class ConfiguringItemHandler:
    """
    Handles configuring items (answering configuration questions).

    Routes user input to the appropriate field-specific handler based
    on the pending_field in the order. The pending_field format is
    "item_type:attr_slug" (e.g., "bagel:toasted", "sized_beverage:size").
    """

    def __init__(
        self,
        config_helper_handler: "ConfigHelperHandler | None" = None,
        checkout_utils_handler: "CheckoutUtilsHandler | None" = None,
        modifier_change_handler: "ModifierChangeHandler | None" = None,
        item_adder_handler: "ItemAdderHandler | None" = None,
        menu_item_handler: "MenuItemConfigHandler | None" = None,
        config_selection_handler: "ConfigSelectionHandler | None" = None,
        config_modification_handler: "ConfigModificationHandler | None" = None,
        bundle_modification_handler: "BundleModificationHandler | None" = None,
        modifier_addition_handler: "ModifierAdditionHandler | None" = None,
    ) -> None:
        """
        Initialize the configuring item handler.

        Args:
            config_helper_handler: Handler for config helpers (side choice, etc.).
            checkout_utils_handler: Handler for checkout utilities.
            modifier_change_handler: Handler for modifier changes.
            item_adder_handler: Handler for adding items.
            menu_item_handler: Handler for menu item configuration (deli sandwiches, espresso, etc.).
            config_selection_handler: Handler for item/modifier selection flows.
            config_modification_handler: Handler for "can you make it X?" and item switch.
            bundle_modification_handler: Handler for bundle child mods and cross-attribute matching.
            modifier_addition_handler: Handler for adding modifiers and items during config.
        """
        self.config_helper_handler = config_helper_handler
        self.checkout_utils_handler = checkout_utils_handler
        self.modifier_change_handler = modifier_change_handler
        self.item_adder_handler = item_adder_handler
        self.menu_item_handler = menu_item_handler
        self.config_selection_handler = config_selection_handler
        self.config_modification_handler = config_modification_handler
        self.bundle_modification_handler = bundle_modification_handler
        self.modifier_addition_handler = modifier_addition_handler
        # Set via setter after TakingItemsHandler is created (to avoid circular dependency)
        self._taking_items_handler: "TakingItemsHandler | None" = None

        # Create interceptors
        self._priority_interceptor = ConfigPriorityInterceptor(
            config_helper_handler=config_helper_handler,
            checkout_utils_handler=checkout_utils_handler,
            modifier_change_handler=modifier_change_handler,
            modifier_addition_handler=modifier_addition_handler,
            get_current_config_result_fn=self._get_current_config_result,
        )
        self._modification_interceptor = ConfigModificationInterceptor(
            modifier_change_handler=modifier_change_handler,
            bundle_modification_handler=bundle_modification_handler,
            config_modification_handler=config_modification_handler,
            modifier_addition_handler=modifier_addition_handler,
            config_helper_handler=config_helper_handler,
            checkout_utils_handler=checkout_utils_handler,
        )
        self._fallback_interceptor = ConfigFallbackInterceptor(
            modifier_addition_handler=modifier_addition_handler,
            config_helper_handler=config_helper_handler,
        )

    @property
    def taking_items_handler(self) -> "TakingItemsHandler | None":
        """Get the taking items handler."""
        return self._taking_items_handler

    @taking_items_handler.setter
    def taking_items_handler(self, handler: "TakingItemsHandler | None") -> None:
        """Set the taking items handler (called after initialization to avoid circular deps)."""
        self._taking_items_handler = handler
        # Propagate to the fallback interceptor
        self._fallback_interceptor.taking_items_handler = handler

    def _process_pending_parsed_items(self, order: OrderTask) -> StateMachineResult | None:
        """Delegate to config_selection_handler for processing pending parsed items.

        This method is kept for backward compatibility with menu_item_handler.
        """
        if self.config_selection_handler:
            return self.config_selection_handler.process_pending_parsed_items(order)
        return None

    def _handle_item_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Delegate to config_selection_handler for item selection.

        This method is kept for backward compatibility with tests.
        """
        return self.config_selection_handler.handle_item_selection(user_input, order)

    def handle_configuring_item(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """
        Handle input when configuring a specific item.

        THIS IS THE KEY: we use state-specific parsers that can ONLY
        interpret input as answers for the pending field. No new items.
        """
        # Pre-item-lookup dispatch: all handlers take (user_input, order)
        _dispatch = {
            PendingField.ITEM_SELECTION: self.config_selection_handler.handle_item_selection,
            PendingField.MODIFIER_SELECTION: self.config_selection_handler.handle_modifier_selection,
            PendingField.AMBIGUOUS_SELECTION: self._handle_ambiguous_selection_response,
            PendingField.CONFIRM_ITEM_SWITCH: self.config_modification_handler.handle_confirm_item_switch,
        }
        if self._taking_items_handler:
            _dispatch.update({
                PendingField.DUPLICATE_SELECTION: self._taking_items_handler.handle_duplicate_selection,
                PendingField.SAME_THING_CLARIFICATION: self._taking_items_handler.handle_same_thing_clarification,
                PendingField.CONFIRM_SUGGESTED_ITEM: self._taking_items_handler.handle_confirm_suggested_item,
                PendingField.CONFIRM_INGREDIENT_SUGGESTION: self._taking_items_handler.handle_confirm_ingredient_suggestion,
                PendingField.CONFIRM_DIETARY_FOLLOWUP: self._taking_items_handler.handle_confirm_dietary_followup,
                PendingField.QUANTITY_ADDITION_SELECTION: self._taking_items_handler.handle_quantity_addition_selection,
                PendingField.CATEGORY_INQUIRY: self._taking_items_handler._handle_category_inquiry_response,
            })
        handler = _dispatch.get(order.pending_field)
        if handler:
            return handler(user_input, order)

        item = order.items.get_item_by_id(order.pending_item_id)
        if item is None:
            order.clear_pending()
            return StateMachineResult(
                message=ErrorMessages.WHAT_TO_ORDER,
                order=order,
            )

        interceptor_result = self._check_config_interceptors(user_input, item, order)
        if interceptor_result:
            return interceptor_result

        # Post-item-lookup dispatch: handlers take (user_input, item, order)
        _item_dispatch: dict[str, Callable] = {
            PendingField.SIDE_CHOICE: self.config_helper_handler.handle_side_choice,
        }
        if isinstance(item, MenuItemTask) and self.menu_item_handler:
            _item_dispatch.update({
                PendingField.CUSTOMIZATION_CHECKPOINT: self.menu_item_handler.handle_customization_checkpoint,
                PendingField.CUSTOMIZATION_SELECTION: self.menu_item_handler.handle_customization_selection,
            })

        item_handler = _item_dispatch.get(order.pending_field)
        if item_handler:
            return item_handler(user_input, item, order)

        # Data-driven routing: pending_field format is "item_type:attr_slug"
        item_type_slug, attr_slug = parse_pending_field(order.pending_field)
        if item_type_slug and attr_slug and isinstance(item, MenuItemTask) and self.menu_item_handler:
            # side_choice attribute uses component slot handler (has full option list)
            if attr_slug == SIDE_CHOICE_ATTR_SLUG and menu_cache.item_type_has_component_slots(item_type_slug):
                logger.debug(
                    "Routing side_choice attr to component slot handler for %s",
                    item_type_slug
                )
                return self.config_helper_handler.handle_side_choice(user_input, item, order)
            logger.debug(
                "Routing '%s' through unified handler for %s attr=%s",
                order.pending_field, item_type_slug, attr_slug
            )
            return self.menu_item_handler.handle_attribute_input(user_input, item, order, attr_slug)

        # Queued menu item config (abbreviated flow from checkout_utils_handler)
        if order.pending_field == PendingField.MENU_ITEM_CONFIG:
            if isinstance(item, MenuItemTask) and self.menu_item_handler:
                self.menu_item_handler.capture_attributes_from_input(user_input, item)
                return self.menu_item_handler.get_first_question(item, order)

        # Default: unknown pending_field, advance to next question
        order.clear_pending()
        return self.checkout_utils_handler.get_next_question(order)

    def _handle_ambiguous_selection_response(
        self, user_input: str, order: OrderTask
    ) -> StateMachineResult:
        """Handle user's response to ambiguous selection disambiguation.

        When user said "syrup" and we asked "Which syrup?", this handles their response.
        """
        from .response_utils import is_move_on_response

        item = order.items.get_item_by_id(order.pending_item_id)
        if not item:
            order.clear_pending()
            return StateMachineResult(
                message="What can I get for you?",
                order=order,
            )

        # Get the pending ambiguous selection info
        if not order.pending_config_queue:
            # No pending info - shouldn't happen, continue with normal config
            order.clear_pending()
            if isinstance(item, MenuItemTask) and self.menu_item_handler:
                return self.menu_item_handler.get_first_question(item, order)
            return self.checkout_utils_handler.get_next_question(order)

        ambig_info = order.pending_config_queue[0]
        attr_slug = ambig_info.get("attr_slug", "")
        matching_options = ambig_info.get("matching_options", [])

        # Check for move-on responses ("skip", "none of these", "no", etc.)
        if is_move_on_response(user_input):
            logger.info(
                "User chose to move on from ambiguous selection for %s",
                attr_slug,
            )
            # Clear the ambiguous selection from the item
            if isinstance(item, MenuItemTask) and item.ambiguous_selections:
                item.ambiguous_selections.pop(0)
            order.pending_config_queue = []
            # Continue to the next question
            if isinstance(item, MenuItemTask) and self.menu_item_handler:
                return self.menu_item_handler.get_first_question(item, order)
            return self.checkout_utils_handler.get_next_question(order)

        # Try to match user input against the options
        user_lower = normalize_text(user_input)
        matched_option = None

        for opt in matching_options:
            opt_slug = opt.get("slug", "").lower()
            opt_display = opt.get("display_name", "").lower()

            # Check for exact match or partial match
            if (opt_slug == user_lower or
                opt_display == user_lower or
                opt_slug in user_lower or
                opt_display in user_lower or
                user_lower in opt_slug or
                user_lower in opt_display):
                matched_option = opt
                break

        if matched_option:
            # Apply the selected option to the item
            # Create a selection and apply it
            selection = Selection(
                slug=matched_option.get("slug", ""),
                category=attr_slug,
                display_name=matched_option.get("display_name", ""),
                price=matched_option.get("price", 0.0),
            )

            if isinstance(item, MenuItemTask) and self.menu_item_handler:
                self.menu_item_handler._apply_selections(item, [selection])
                # Recalculate price to include the upcharge for the selected option
                self.menu_item_handler._recalculate_item_price(item)

            # Clear the ambiguous selection from the item
            if item.ambiguous_selections:
                item.ambiguous_selections.pop(0)

            logger.info(
                "Resolved ambiguous selection: %s -> %s for %s",
                ambig_info.get("token"), matched_option.get("slug"), item.menu_item_name
            )

            # Clear pending state and continue with normal config
            order.pending_config_queue = []

            # Continue with get_first_question to check for more ambiguous selections
            # or proceed to normal config questions
            if isinstance(item, MenuItemTask) and self.menu_item_handler:
                return self.menu_item_handler.get_first_question(item, order)

        # No match found - try falling through to taking_items_handler for new item attempts
        if self._taking_items_handler:
            order.pending_config_queue = []
            if isinstance(item, MenuItemTask) and item.ambiguous_selections:
                item.ambiguous_selections.pop(0)
            order.clear_pending()
            return self._taking_items_handler.handle_taking_items(user_input, order)

        # Fallback: re-ask with move-on hint
        option_names = [opt.get("display_name", opt.get("slug", "")) for opt in matching_options]
        options_str = format_english_list(option_names, conjunction="or")
        qr = [{"label": opt.get("display_name", opt.get("slug", "")),
               "value": opt.get("display_name", opt.get("slug", ""))}
              for opt in matching_options]
        qr.append({"label": "Move on", "value": "move on"})

        return StateMachineResult(
            message=(
                f"I didn't catch that. Which would you like? {options_str}?"
                f' Or do you want to <u>move on</u>?'
            ),
            order=order,
            quick_replies=qr,
        )

    def _check_config_interceptors(
        self, user_input: str, item, order: OrderTask
    ) -> StateMachineResult | None:
        """Run pre-routing interceptors during item configuration.

        Checks for cancellation, change requests, off-topic input,
        and modifier inquiries before routing to field-specific handlers.

        Returns:
            StateMachineResult if an interceptor handled the input, None to continue.
        """
        # Group 1: Priority intercepts (done, cancel, quantity, another item)
        if result := self._check_priority_intercepts(user_input, item, order):
            return result

        # Group 2: Item addition during config ("and a X", "also X")
        # Must run BEFORE is_valid_answer check to prevent "blueberry" being
        # matched as a bread option when user says "and a Blueberry Cream Cheese Sandwich"
        if isinstance(item, MenuItemTask):
            if result := self.modifier_addition_handler.handle_add_item_during_config(
                user_input, item, order
            ):
                return result

        # Compute once: is this a valid answer for the pending field?
        is_valid = is_valid_answer_for_pending_field(user_input, order.pending_field)
        if is_valid:
            logger.debug("Input is valid answer for %s - skipping change/off-topic detection", order.pending_field)

        # Group 3: Modification checks (change request, bundle mod, can-you-make-it,
        # add modifiers, cross-attr, boolean)
        if isinstance(item, MenuItemTask):
            if result := self._check_modification_intercepts(user_input, item, order, is_valid):
                return result

        # Group 4: Fallback checks (new item parse, off-topic, modifier inquiry)
        if result := self._check_fallback_intercepts(user_input, item, order, is_valid):
            return result

        return None

    def _check_priority_intercepts(
        self, user_input: str, item, order: OrderTask
    ) -> StateMachineResult | None:
        """Delegate to priority interceptor."""
        return self._priority_interceptor.check_priority_intercepts(user_input, item, order)

    def _check_modification_intercepts(
        self, user_input: str, item: MenuItemTask, order: OrderTask, is_valid_answer: bool
    ) -> StateMachineResult | None:
        """Delegate to modification interceptor."""
        return self._modification_interceptor.check_modification_intercepts(
            user_input, item, order, is_valid_answer
        )

    def _check_fallback_intercepts(
        self, user_input: str, item, order: OrderTask, is_valid_answer: bool
    ) -> StateMachineResult | None:
        """Delegate to fallback interceptor."""
        return self._fallback_interceptor.check_fallback_intercepts(
            user_input, item, order, is_valid_answer
        )

    def _get_current_config_result(
        self, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult | None:
        """Get the current config question as a full StateMachineResult with quick_replies.

        Parses the pending_field, looks up the attribute, and delegates to the
        menu item config handler to build a complete result including quick_replies
        for frontend linkification.

        Returns:
            StateMachineResult with message and quick_replies, or None if lookup fails.
        """
        field = order.pending_field
        if not field or not self.menu_item_handler:
            return None

        item_type, attr_slug = parse_pending_field(field)
        if not item_type or not attr_slug:
            return None

        try:
            attrs = menu_cache.get_item_type_attributes(item_type)
        except (KeyError, ValueError) as e:
            logger.debug("Failed to get attributes for %s: %s", item_type, e)
            return None

        attr = attrs.get(attr_slug)
        if not attr:
            return None

        return self.menu_item_handler._ask_attribute_question(item, order, attr)
