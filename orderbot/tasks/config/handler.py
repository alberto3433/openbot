"""
Menu Item Configuration Handler for Order State Machine.

This module handles the configuration of menu items (like deli sandwiches)
with DB-driven attributes. It supports:
- Mandatory attributes (ask_in_conversation=True) asked in sequence
- Customization checkpoint after mandatory attributes
- Optional attributes (ask_in_conversation=False) offered in a loop
- Modifier extraction during configuration (proteins, cheeses, toppings, etc.)

Designed to be generic and work with any item type that has DB-defined attributes.
"""

import logging
from typing import Callable, TYPE_CHECKING

from orderbot.cache import menu_cache
from ..models import OrderTask, MenuItemTask
from ..normalization import strip_ordering_prefix
from ..parsers import strip_conversational_fillers
from ..schemas import StateMachineResult, OrderPhase
from ..handler_config import BaseHandler
from ..checkout_messages import got_it_anything_else
from ..utils import OptionMatcher, InputNormalizer
from ..utils.text import format_display_list, normalize_text, name_with_prefix
from .context import ConfigHandlerContext
from .select_input import SelectInputHandler
from .options_inquiry import OptionsInquiryHandler
from .disambiguation import ConfigDisambiguationHandler
from .question_builder import QuestionBuilder
from .selection_extractor import SelectionExtractor
from .direct_option_matcher import DirectOptionMatcher
from .quantity_input import QuantityInputHandler
from .package_input import PackageInputHandler
from .attribute_capture import capture_attributes_from_input
from .parsers import BooleanParser
from .customization_checkpoint import CustomizationCheckpointHandler
from .qualifier_extractor import QualifierExtractor
from .quick_reply_builder import QuickReplyBuilder
from .config_pagination import ConfigPaginationHandler
from .attribute_resolver import (
    get_optional_attributes,
    get_unanswered_mandatory,
    get_unanswered_optional,
)
from .config_question_flow import ConfigQuestionFlow
from .config_input_dispatch import ConfigInputDispatch

if TYPE_CHECKING:
    from ..models.pending_states import PendingUnmatchedPagination

logger = logging.getLogger(__name__)

class MenuItemConfigHandler(BaseHandler):
    """
    Handles menu item configuration with DB-driven attributes.

    Reads item type attributes from the database to determine:
    - Which questions to ask (ask_in_conversation=True for mandatory)
    - What the question text should be (question_text field)
    - What options are valid (from global attribute options)
    """

    def __init__(self, config: "HandlerConfig"):
        """
        Initialize the menu item config handler.

        Args:
            config: HandlerConfig with shared dependencies.
        """
        super().__init__(config)
        # Note: Item type attributes are cached in menu_cache (single source of truth)
        self._input_normalizer = InputNormalizer()
        self._option_matcher = OptionMatcher(self._input_normalizer)

        # Callback for processing pending parsed items (set via setter to avoid circular deps)
        self._process_pending_parsed_items_callback: "Callable[[OrderTask], StateMachineResult | None] | None" = None

        # Initialize extracted sub-handler classes
        self._question_flow = ConfigQuestionFlow(self)
        self._input_dispatch = ConfigInputDispatch(self)

        # Create shared context for sub-handlers
        # This replaces the callback jungle pattern where each sub-handler received 10+ callbacks
        self._ctx = ConfigHandlerContext(
            pricing=config.pricing,
            option_matcher=self._option_matcher,
            input_normalizer=self._input_normalizer,
            # Attribute resolution (direct references to attribute_resolver functions / menu_cache)
            get_item_type_attributes=menu_cache.get_item_type_attributes,
            get_optional_attributes=get_optional_attributes,
            get_unanswered_optional=get_unanswered_optional,
            # Display/formatting (direct reference to utils.text function)
            format_display_list=format_display_list,
            # Navigation
            advance_to_next_question=self._advance_to_next_question,
            get_next_question=self._get_next_question,
            # Matching
            match_attribute_from_input=self._match_attribute_from_input,
            extract_quantity_from_input=self._input_normalizer.extract_leading_quantity,
            extract_qualifier_for_option=self._extract_qualifier_for_option,
            # Price
            recalculate_item_price=self._recalculate_item_price,
            # Question/action callbacks (disambiguation/direct match set after _direct_option_matcher init)
            ask_disambiguation_for_options=None,
            ask_customization_checkpoint=self._ask_customization_checkpoint,
            ask_optional_attribute=self._ask_optional_attribute,
            ask_more_customizations=self._ask_more_customizations,
            try_direct_option_match=None,
            # Optional callback (set via property setter)
            process_pending_parsed_items=None,
        )

        # Initialize sub-handlers using shared context
        self._selection_extractor = SelectionExtractor(pricing=config.pricing)
        self._select_input_handler = SelectInputHandler(
            pricing=config.pricing,
            option_matcher=self._option_matcher,
            input_normalizer=self._input_normalizer,
            format_display_list_callback=format_display_list,
            extract_selections_callback=self._selection_extractor.extract_selections_from_input,
            extract_qualifier_callback=self._extract_qualifier_for_option,
        )
        self._options_inquiry_handler = OptionsInquiryHandler(ctx=self._ctx)
        self._disambiguation_handler = ConfigDisambiguationHandler(ctx=self._ctx)
        self._question_builder = QuestionBuilder()
        self._direct_option_matcher = DirectOptionMatcher(
            ctx=self._ctx,
            option_matcher=self._option_matcher,
        )
        # Set disambiguation/direct match callbacks now that _direct_option_matcher exists
        self._ctx.ask_disambiguation_for_options = self._direct_option_matcher._ask_disambiguation_for_options
        self._ctx.try_direct_option_match = self._direct_option_matcher.try_direct_option_match
        self._quantity_input_handler = QuantityInputHandler(ctx=self._ctx)
        self._package_input_handler = PackageInputHandler(
            option_matcher=self._option_matcher,
            input_normalizer=self._input_normalizer,
        )
        self._customization_checkpoint_handler = CustomizationCheckpointHandler(
            options_inquiry_handler=self._options_inquiry_handler,
            ctx=self._ctx,
        )
        self._boolean_parser = BooleanParser()
        self._qualifier_extractor = QualifierExtractor()
        self._quick_reply_builder = QuickReplyBuilder()
        self._pagination_handler = ConfigPaginationHandler(
            option_matcher=self._option_matcher,
            question_builder=self._question_builder,
            resolve_option_price=self._resolve_option_price,
            advance_to_next_question=self._advance_to_next_question,
            get_next_question=self._get_next_question,
        )

    def _apply_selections(self, item: "MenuItemTask", selections: list) -> str | None:
        """
        Apply parsed selections to a menu item.

        This is a thin wrapper around the selection extractor's apply_selections method,
        exposed for use by other handlers (e.g., ItemAdderHandler).

        Args:
            item: The menu item to apply selections to
            selections: List of Selection objects from parsing

        Returns:
            Acknowledgment string if selections were applied, None otherwise
        """
        return self._selection_extractor.apply_selections(item, selections)

    @property
    def process_pending_parsed_items(self) -> "Callable[[OrderTask], StateMachineResult | None] | None":
        """Get callback for processing pending parsed items."""
        return self._process_pending_parsed_items_callback

    @process_pending_parsed_items.setter
    def process_pending_parsed_items(self, callback: "Callable[[OrderTask], StateMachineResult | None] | None") -> None:
        """Set callback for processing pending parsed items."""
        self._process_pending_parsed_items_callback = callback
        # Update the shared context and sub-handler
        self._ctx.process_pending_parsed_items = callback
        self._customization_checkpoint_handler._process_pending_parsed_items_callback = callback

    def supports_item_type(self, item_type_slug: str | None) -> bool:
        """Check if this handler supports the given item type.

        An item type is supported if it has linked attributes in the database.
        """
        if not item_type_slug:
            return False
        return item_type_slug in menu_cache.get_configurable_item_types()

    def _resolve_option_price(self, option: dict, item_type: str) -> float:
        """Look up option price with pricing engine fallback.

        Args:
            option: The option dict (must have 'slug' key).
            item_type: The item type slug for pricing engine lookup.

        Returns:
            The resolved price as a float.
        """
        price = OptionMatcher.get_option_price(option)
        if price == 0 and self.pricing:
            price = self.pricing.lookup_generic_modifier_price(
                option["slug"], item_type
            ) or 0.0
        return price

    # =========================================================================
    # Delegation wrappers — ConfigInputDispatch
    # =========================================================================

    def _extract_qualifier_for_option(
        self, user_input: str, option_name: str,
        other_option_positions: list[tuple[int, int]] | None = None,
    ) -> str | None:
        return self._input_dispatch._extract_qualifier_for_option(
            user_input, option_name, other_option_positions
        )

    def _match_attribute_from_input(
        self, user_input: str, attributes: list[dict]
    ) -> list[dict]:
        return self._input_dispatch._match_attribute_from_input(user_input, attributes)

    def handle_attribute_input(
        self, user_input: str, item: MenuItemTask, order: OrderTask, attr_slug: str
    ) -> StateMachineResult:
        return self._input_dispatch.handle_attribute_input(user_input, item, order, attr_slug)

    def _check_forward_delegation(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        options: list[dict],
        attrs: dict,
    ) -> StateMachineResult | None:
        return self._input_dispatch._check_forward_delegation(
            user_input, item, order, attr, options, attrs
        )

    def _handle_boolean_input(
        self, user_input: str, item: MenuItemTask, order: OrderTask, attr: dict
    ) -> StateMachineResult:
        return self._input_dispatch._handle_boolean_input(user_input, item, order, attr)

    def _handle_quantity_input(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        options: list[dict],
    ) -> StateMachineResult:
        return self._input_dispatch._handle_quantity_input(user_input, item, order, attr, options)

    def _handle_package_input(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
    ) -> StateMachineResult:
        return self._input_dispatch._handle_package_input(user_input, item, order, attr)

    def _handle_select_input(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        options: list[dict],
    ) -> StateMachineResult:
        return self._input_dispatch._handle_select_input(user_input, item, order, attr, options)

    # =========================================================================
    # Delegation wrappers — ConfigQuestionFlow
    # =========================================================================

    def _format_checkpoint_questions(self, attrs: list[dict]) -> tuple[str, list[dict[str, str]]]:
        return self._question_flow._format_checkpoint_questions(attrs)

    # =========================================================================
    # Main Entry Point
    # =========================================================================

    def get_first_question(
        self, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult:
        """
        Get the first configuration question for a menu item.

        Called when a new menu item is added and needs configuration.
        """
        item_type = item.menu_item_type
        if not item_type or not self.supports_item_type(item_type):
            # Not a supported item type, recalculate price and mark complete
            self._recalculate_item_price(item)
            item.mark_complete()
            return self._get_next_question(order)

        # Check for ambiguous selections first (e.g., "syrup" matching multiple options)
        # These need to be resolved before continuing with normal config
        ambig_result = self._handle_ambiguous_selection(item, order)
        if ambig_result:
            return ambig_result

        # Check for pending default extra clarifications
        # (e.g., "Chelsea Club with bacon" when bacon is already a default)
        clarification = order.pending_default_extra_clarification
        if clarification and clarification.item_id == item.id and clarification.candidates:
            candidate = clarification.candidates[0]
            msg = (
                f"{name_with_prefix('The', clarification.item_name)} already comes with "
                f"{candidate['display_name']}. Would you like extra?"
            )
            from ..pending_fields import PendingField
            order.pending_field = PendingField.CONFIRM_DEFAULT_EXTRA
            order.pending_item_ids = [item.id]
            return StateMachineResult(message=msg, order=order, quick_replies=[
                {"label": "Yes", "value": "yes"},
                {"label": "No", "value": "no"},
            ])

        # Find first unanswered mandatory attribute
        unanswered = get_unanswered_mandatory(item, item_type)
        if not unanswered:
            # No mandatory questions, go to checkpoint
            return self._ask_customization_checkpoint(item, order)

        first_attr = unanswered[0]
        # Reset options page for first question
        order.config_options_page = 0
        return self._ask_attribute_question(item, order, first_attr, is_first_question=True)

    def _handle_ambiguous_selection(
        self, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult | None:
        return self._question_flow._handle_ambiguous_selection(item, order)

    def _ask_attribute_question(
        self, item: MenuItemTask, order: OrderTask, attr: dict,
        is_first_question: bool = False
    ) -> StateMachineResult:
        return self._question_flow._ask_attribute_question(item, order, attr, is_first_question)

    def _ask_customization_checkpoint(
        self, item: MenuItemTask, order: OrderTask, acknowledgment: str | None = None
    ) -> StateMachineResult:
        return self._question_flow._ask_customization_checkpoint(item, order, acknowledgment)

    # =========================================================================
    # Pricing Abstraction
    # =========================================================================

    def _recalculate_item_price(self, item: MenuItemTask) -> float:
        """
        Recalculate and update an item's price based on its current state.

        Delegates to PricingEngine.recalculate_item_price which handles all
        item types generically using database-driven pricing.

        Args:
            item: The menu item to recalculate price for

        Returns:
            The new calculated price

        Raises:
            ValueError: If pricing engine is not available
        """
        if not self.pricing:
            raise ValueError(
                f"Cannot recalculate price for '{item.menu_item_name}': "
                "PricingEngine is required but not configured. "
                "Ensure handler is initialized with pricing in HandlerConfig."
            )
        return self.pricing.recalculate_item_price(item)

    # =========================================================================
    # Multi-Item Orchestration
    # =========================================================================

    def configure_next_incomplete_item(
        self, order: OrderTask, item_type: str | None = None
    ) -> StateMachineResult:
        return self._question_flow.configure_next_incomplete_item(order, item_type)

    # =========================================================================
    # Handle User Input for Different States
    # =========================================================================

    def _advance_from_pagination(
        self, pagination: "PendingUnmatchedPagination", item: MenuItemTask, order: OrderTask,
        matched_choice: str | None = None,
    ) -> StateMachineResult:
        return self._question_flow._advance_from_pagination(pagination, item, order, matched_choice)

    def _handle_unmatched_pagination(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        return self._question_flow._handle_unmatched_pagination(user_input, item, order)

    def _advance_to_next_question(
        self, item: MenuItemTask, order: OrderTask, current_attr: dict,
        matched_choice: str | None = None,
        use_multi_item_orchestration: bool = False
    ) -> StateMachineResult:
        return self._question_flow._advance_to_next_question(
            item, order, current_attr, matched_choice, use_multi_item_orchestration
        )

    def _ask_more_customizations(
        self, item: MenuItemTask, order: OrderTask, matched_choice: str | None = None
    ) -> StateMachineResult:
        return self._question_flow._ask_more_customizations(item, order, matched_choice)

    def handle_customization_checkpoint(
        self, user_input: str, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult:
        """Handle user response to customization checkpoint.

        Delegates to CustomizationCheckpointHandler for the actual logic.
        """
        return self._customization_checkpoint_handler.handle_customization_checkpoint(
            user_input, item, order
        )

    def handle_customization_selection(
        self, user_input: str, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult:
        """Handle user selecting which attribute to customize from the list.

        Delegates to CustomizationCheckpointHandler for the actual logic.
        """
        return self._customization_checkpoint_handler.handle_customization_selection(
            user_input, item, order
        )

    def _ask_optional_attribute(
        self, item: MenuItemTask, order: OrderTask, attr: dict
    ) -> StateMachineResult:
        return self._question_flow._ask_optional_attribute(item, order, attr)

    # =========================================================================
    # Proactive Attribute Capture
    # =========================================================================

    def capture_attributes_from_input(
        self, user_input: str, item: MenuItemTask, skip_attribute: str | None = None
    ) -> None:
        """
        Capture any attributes mentioned in the initial order input.

        Called when item is first created to pre-fill attributes.
        e.g., "deli sandwich with scrambled egg on a plain bagel toasted"

        Args:
            user_input: The user's raw input text
            item: The menu item to capture attributes for
            skip_attribute: Optional attribute slug to skip (used when answering
                a direct question to prevent double-interpretation, e.g., when
                answering "What kind of bagel?" with "onion", we skip bread
                so we don't also capture toppings=onions)

        Delegates to the extracted capture_attributes_from_input function.
        """
        item_type = item.menu_item_type
        if not item_type or not self.supports_item_type(item_type):
            return

        attrs = menu_cache.get_item_type_attributes(item_type)
        capture_attributes_from_input(
            user_input, item, attrs, self._option_matcher, skip_attribute=skip_attribute
        )
