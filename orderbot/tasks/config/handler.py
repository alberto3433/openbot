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
import re
from typing import Callable

from orderbot.cache import menu_cache
from orderbot.constants import QUALIFIER_PROXIMITY_THRESHOLD
from ..models import OrderTask, MenuItemTask
from ..pending_fields import PendingField
from ..normalization import strip_ordering_prefix
from ..schemas import StateMachineResult, OrderPhase
from ..parsers.constants import DEFAULT_PAGINATION_SIZE
from ..handler_config import BaseHandler
from ..checkout_messages import got_it_anything_else
from ..utils import OptionMatcher, InputNormalizer
from ..utils.text import format_display_list
from .context import ConfigHandlerContext
from .select_input import SelectInputHandler
from .options_inquiry import OptionsInquiryHandler
from .disambiguation import ConfigDisambiguationHandler
from .question_builder import QuestionBuilder
from .selection_extractor import SelectionExtractor
from .direct_option_matcher import DirectOptionMatcher
from ..response_utils import is_negative, is_affirmative
from .quantity_input import QuantityInputHandler
from .package_input import PackageInputHandler
from .attribute_capture import capture_attributes_from_input
from .parsers import BooleanParser
from .customization_checkpoint import CustomizationCheckpointHandler
from .attribute_resolver import (
    get_item_type_attributes,
    get_mandatory_attributes,
    get_optional_attributes,
    get_skipped_attributes,
    get_unanswered_mandatory,
    get_unanswered_optional,
)

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

        # Create shared context for sub-handlers
        # This replaces the callback jungle pattern where each sub-handler received 10+ callbacks
        self._ctx = ConfigHandlerContext(
            pricing=config.pricing,
            option_matcher=self._option_matcher,
            input_normalizer=self._input_normalizer,
            # Attribute resolution
            get_item_type_attributes=self._get_item_type_attributes,
            get_optional_attributes=self._get_optional_attributes,
            get_unanswered_optional=self._get_unanswered_optional,
            # Display/formatting
            format_display_list=self._format_display_list,
            # Navigation
            advance_to_next_question=self._advance_to_next_question,
            get_next_question=self._get_next_question,
            # Matching
            match_attribute_from_input=self._match_attribute_from_input,
            extract_quantity_from_input=self._extract_quantity_from_input,
            extract_qualifier_for_option=self._extract_qualifier_for_option,
            # Price
            recalculate_item_price=self._recalculate_item_price,
            # Question/action callbacks
            ask_disambiguation_for_options=self._ask_disambiguation_for_options,
            ask_customization_checkpoint=self._ask_customization_checkpoint,
            ask_optional_attribute=self._ask_optional_attribute,
            ask_more_customizations=self._ask_more_customizations,
            try_direct_option_match=self._try_direct_option_match,
            # Optional callback (set via property setter)
            process_pending_parsed_items=None,
        )

        # Initialize sub-handlers using shared context
        self._select_input_handler = SelectInputHandler(
            pricing=config.pricing,
            option_matcher=self._option_matcher,
            input_normalizer=self._input_normalizer,
        )
        self._options_inquiry_handler = OptionsInquiryHandler(ctx=self._ctx)
        self._disambiguation_handler = ConfigDisambiguationHandler(ctx=self._ctx)
        self._question_builder = QuestionBuilder()
        self._selection_extractor = SelectionExtractor(pricing=config.pricing)
        self._direct_option_matcher = DirectOptionMatcher(
            option_matcher=self._option_matcher,
            ctx=self._ctx,
        )
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

    def _get_item_type_attributes(self, item_type_slug: str) -> dict:
        """Get item type attributes. Delegates to attribute_resolver."""
        return get_item_type_attributes(item_type_slug)

    def _get_mandatory_attributes(self, item_type_slug: str) -> list[dict]:
        """Get mandatory attributes. Delegates to attribute_resolver."""
        return get_mandatory_attributes(item_type_slug)

    def _get_optional_attributes(self, item_type_slug: str) -> list[dict]:
        """Get optional attributes. Delegates to attribute_resolver."""
        return get_optional_attributes(item_type_slug)

    def _get_unanswered_mandatory(
        self, item: MenuItemTask, item_type_slug: str
    ) -> list[dict]:
        """Get unanswered mandatory attributes. Delegates to attribute_resolver."""
        return get_unanswered_mandatory(item, item_type_slug)

    def _get_skipped_attributes(self, item: MenuItemTask) -> set[str]:
        """Get skipped attributes. Delegates to attribute_resolver."""
        return get_skipped_attributes(item)

    def _get_unanswered_optional(
        self, item: MenuItemTask, item_type_slug: str
    ) -> list[dict]:
        """Get unanswered optional attributes. Delegates to attribute_resolver."""
        return get_unanswered_optional(item, item_type_slug)

    def _extract_quantity_from_input(self, user_input: str) -> tuple[int, str]:
        """
        Extract quantity from user input.

        Returns (quantity, remaining_text) tuple.
        Delegates to InputNormalizer.
        """
        return self._input_normalizer.extract_leading_quantity(user_input)


    def _extract_qualifier_for_option(self, user_input: str, option_name: str) -> str | None:
        """
        Extract qualifier (extra, light, lots of, on the side, etc.) for a specific option.

        Scans user input for qualifier patterns adjacent to the option name.

        Args:
            user_input: The full user input text (e.g., "lots of lettuce and extra mayo")
            option_name: The option to find qualifier for (e.g., "Lettuce")

        Returns:
            Normalized qualifier like "extra" or "on the side", or None if no qualifier found.
        """
        qualifier_patterns = menu_cache.get_qualifier_patterns()
        if not qualifier_patterns:
            return None

        user_lower = user_input.lower()
        option_lower = option_name.lower()

        # Find position of the option in user input
        # Try multiple variations: full name, individual words, slug-based patterns
        opt_match = None
        search_terms = [option_lower]

        # Also try individual words from the display name (e.g., "milk" from "Whole Milk")
        for word in option_lower.split():
            if len(word) >= 3:  # Skip short words like "a", "of", etc.
                search_terms.append(word)

        for term in search_terms:
            opt_match = re.search(rf'\b{re.escape(term)}\b', user_lower)
            if opt_match:
                break

        if not opt_match:
            return None

        opt_start, opt_end = opt_match.start(), opt_match.end()

        # Check for qualifiers adjacent to this option
        for pattern in qualifier_patterns:
            pattern_re = re.compile(rf'\b{re.escape(pattern)}\b', re.IGNORECASE)
            for match in pattern_re.finditer(user_lower):
                qual_start, qual_end = match.start(), match.end()

                # Qualifier before option: "extra lettuce", "lots of lettuce"
                is_before = qual_end <= opt_start and opt_start - qual_end <= QUALIFIER_PROXIMITY_THRESHOLD
                # Qualifier after option: "lettuce on the side"
                is_after = qual_start >= opt_end and qual_start - opt_end <= QUALIFIER_PROXIMITY_THRESHOLD

                if is_before or is_after:
                    info = menu_cache.get_qualifier_info(pattern)
                    if info:
                        return info["normalized_form"]

        return None

    def _match_attribute_from_input(
        self, user_input: str, attributes: list[dict]
    ) -> list[dict]:
        """
        Try to match user input to one or more attributes.

        Used when user says "add egg and spread" to match multiple.
        Supports partial matching: "cheese" matches "Extra Cheese", "egg" matches "Add Egg".
        """
        user_lower = user_input.lower().strip()
        matched = []

        for attr in attributes:
            display_lower = attr["display_name"].lower()
            slug_readable = attr["slug"].replace("_", " ")

            # Exact match: attribute name in user input
            if display_lower in user_lower:
                matched.append(attr)
                continue
            if slug_readable in user_lower:
                matched.append(attr)
                continue

            # Partial match: user input is a word in the attribute name
            # e.g., "cheese" matches "Extra Cheese", "egg" matches "Add Egg"
            if self._option_matcher._is_whole_word_match(user_lower, display_lower):
                matched.append(attr)
                continue
            if self._option_matcher._is_whole_word_match(user_lower, slug_readable):
                matched.append(attr)
                continue

        return matched

    def _format_display_list(
        self,
        items: list[dict],
        key: str = "display_name",
        conjunction: str = "or",
    ) -> str:
        """Format a list of items for display.

        Delegates to utils.text.format_display_list.
        """
        return format_display_list(items, key=key, conjunction=conjunction)

    def _format_checkpoint_questions(self, attrs: list[dict]) -> str:
        """Format unanswered optional attributes as individual questions."""
        questions = []
        for attr in attrs:
            q = attr.get("question_text")
            if q:
                questions.append(q)
            else:
                display = attr.get("display_name") or attr["slug"]
                questions.append(f"Add {display}?")
        return " ".join(questions)

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

        # Find first unanswered mandatory attribute
        unanswered = self._get_unanswered_mandatory(item, item_type)
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
        """
        Handle ambiguous selections that need user disambiguation.

        When user says something like "syrup" without specifying which one,
        we need to ask "Which syrup? Vanilla, Hazelnut, Caramel, or Peppermint?"

        Returns StateMachineResult if disambiguation is needed, None otherwise.
        """
        if not item.ambiguous_selections:
            return None

        # Get the first ambiguous selection to resolve
        ambig = item.ambiguous_selections[0]
        attr_slug = ambig.get("attr_slug", "")
        token = ambig.get("token", "")
        matching_options = ambig.get("matching_options", [])

        if not matching_options:
            # No options to disambiguate - shouldn't happen, but clear and continue
            item.ambiguous_selections.pop(0)
            return None

        # Build list of option display names
        from ..utils.text import format_english_list
        option_names = [opt.get("display_name", opt.get("slug", "")) for opt in matching_options]

        # Format options as "Vanilla Syrup, Hazelnut Syrup, Caramel Syrup, or Peppermint Syrup"
        options_str = format_english_list(option_names, conjunction="or")

        # Build the disambiguation question
        # Use the token (e.g., "syrup") in the question
        item_name = item.get_display_name()
        question = f"Got it, for the {item_name}. Which {token}? {options_str}?"

        # Store state for handling the user's response
        # pending_field format: "item_type:attr_slug" so the router knows what attribute this is for
        order.set_phase(OrderPhase.CONFIGURING_ITEM)
        order.pending_item_id = item.id
        order.pending_field = PendingField.AMBIGUOUS_SELECTION
        # Store the ambiguous selection info so we can process the response
        order.pending_config_queue = [ambig]  # Store as list for compatibility

        return StateMachineResult(message=question, order=order)

    def _ask_attribute_question(
        self, item: MenuItemTask, order: OrderTask, attr: dict,
        is_first_question: bool = False
    ) -> StateMachineResult:
        """
        Ask the question for a specific attribute.

        Does NOT list options by default - user must ask "what options?" to see them.
        For boolean attributes (like toasted), uses simple yes/no question.
        Uses DB's question_text if configured, otherwise generates a natural question.

        For multi-item configurations, uses ordinal references like "the first one", "the second one".
        """
        # Handle unavailable selection first (early return if applicable)
        unavail_result = self._question_builder.handle_unavailable_selection(item, order, attr)
        if unavail_result:
            return unavail_result

        # Handle unmatched selection (tokens that don't match any option)
        unmatched_result = self._question_builder.handle_unmatched_selection(item, order, attr)
        if unmatched_result:
            return unmatched_result

        # Calculate ordinal position and context for multi-item orders
        ordinal, item_num, has_duplicates = self._question_builder.calculate_item_ordinal(item, order)
        multi_count = len(order.multi_item_config_names) if order.multi_item_config_names else 1
        item_ref = item.get_display_name()

        # Build base question text
        question = self._question_builder.build_base_question(
            attr, item_ref, ordinal, has_duplicates, multi_count
        )

        # Add acknowledgment prefix for first question of each item
        if is_first_question:
            prefix = self._question_builder.build_first_question_prefix(
                item, order, attr, ordinal, item_num, has_duplicates
            )
            if prefix:
                # For subsequent items in multi-item, prefix IS the full question
                if multi_count > 1 and item_num > 1:
                    question = prefix
                else:
                    question = prefix + question

        # Set up order state for receiving the answer
        order.set_phase(OrderPhase.CONFIGURING_ITEM)
        order.pending_item_id = item.id
        order.pending_field = f"{item.menu_item_type}:{attr['slug']}"
        order.config_options_page = 0

        return StateMachineResult(message=question, order=order)

    def _ask_customization_checkpoint(
        self, item: MenuItemTask, order: OrderTask, acknowledgment: str | None = None
    ) -> StateMachineResult:
        """Ask if user wants to customize with optional attributes.

        Args:
            item: The menu item being configured
            order: The current order
            acknowledgment: Optional acknowledgment message to prepend (e.g., "Butter added")
        """
        item_type = item.menu_item_type
        unanswered_optional = self._get_unanswered_optional(item, item_type)

        # Always recalculate price after adding a modifier
        # This ensures upcharges are applied immediately, not just when config is complete
        self._recalculate_item_price(item)

        # Build acknowledgment prefix if provided
        ack_prefix = f"Got it, {acknowledgment}. " if acknowledgment else ""

        if not unanswered_optional:
            # No optional attributes available - price already recalculated above, complete
            item.customization_offered = True
            item.mark_complete()
            order.clear_pending()

            # Check if there are pending parsed items that haven't been added yet
            # This handles the case where disambiguation was triggered and remaining items
            # in the order were stored (e.g., "latte and bagel" - bagel is stored while
            # we disambiguate and configure latte)
            if self._process_pending_parsed_items_callback:
                pending_result = self._process_pending_parsed_items_callback(order)
                if pending_result:
                    return pending_result

            # Check if there are other items queued for configuration
            # This handles the case where disambiguation was triggered after other items
            # were already added (e.g., "an everything bagel and a latte")
            from ..handler_utils import process_next_queued_item
            queued_result = process_next_queued_item(
                order, self, f"after completing {item.get_display_name()}"
            )
            if queued_result:
                return queued_result

            # Check for other incomplete items that need configuration
            # This handles duplicated items (e.g., "make it two hot teas")
            next_result = self._get_next_question(order)
            if next_result and next_result.order.pending_field:
                # Prepend acknowledgment to the next question
                summary = item.get_summary()
                if ack_prefix:
                    return StateMachineResult(
                        message=f"{ack_prefix}Got it, {summary}. {next_result.message}",
                        order=next_result.order,
                    )
                return StateMachineResult(
                    message=f"Got it, {summary}. {next_result.message}",
                    order=next_result.order,
                )

            order.set_phase(OrderPhase.TAKING_ITEMS)
            return StateMachineResult(
                message=f"{ack_prefix}Got it, {item.get_summary()}. Anything else?" if ack_prefix else got_it_anything_else(item.get_summary()),
                order=order,
            )

        # Mark that we've reached the checkpoint
        item.customization_offered = True

        order.set_phase(OrderPhase.CONFIGURING_ITEM)
        order.pending_item_id = item.id
        order.pending_field = PendingField.CUSTOMIZATION_CHECKPOINT

        # List available customization options as individual questions
        options_questions = self._format_checkpoint_questions(unanswered_optional)

        return StateMachineResult(
            message=f"{ack_prefix}Any more changes? {options_questions}",
            order=order,
        )

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
        """
        Find and configure the next incomplete menu item of supported types.

        This method provides multi-item orchestration similar to bagel/coffee handlers.
        It iterates through items, asks required questions, and tracks progress.

        Args:
            order: The order task containing all items
            item_type: Optional specific item type to configure. If None,
                      configures all supported item types.

        Returns:
            StateMachineResult with next question or completion message
        """
        from ..models import TaskStatus
        from ..message_builder import MessageBuilder

        # Determine which item types to process
        # Get configurable item types from database (item types with linked attributes)
        configurable_types = menu_cache.get_configurable_item_types()
        if item_type:
            target_types = {item_type} & configurable_types
        else:
            target_types = configurable_types

        if not target_types:
            # No supported types to configure
            return self._get_next_question(order)

        # Collect all items of the target types
        target_items = [
            item for item in order.items.items
            if isinstance(item, MenuItemTask)
            and item.menu_item_type in target_types
        ]

        if not target_items:
            return self._get_next_question(order)

        # Group items by type for ordinal messaging
        items_by_type: dict[str, list[MenuItemTask]] = {}
        for item in target_items:
            t = item.menu_item_type
            if t not in items_by_type:
                items_by_type[t] = []
            items_by_type[t].append(item)

        # Process each incomplete item
        for item in target_items:
            if item.status != TaskStatus.IN_PROGRESS:
                continue

            item_type_slug = item.menu_item_type
            same_type_items = items_by_type.get(item_type_slug, [item])
            same_type_count = len(same_type_items)

            # Build ordinal descriptor if multiple items of same type
            if same_type_count > 1:
                item_num = next(
                    (i + 1 for i, it in enumerate(same_type_items) if it.id == item.id),
                    1
                )
                ordinal = MessageBuilder.get_ordinal(item_num)
                item_desc = f"the {ordinal} {item.menu_item_name}"
            else:
                item_desc = f"your {item.menu_item_name}"

            # Get unanswered mandatory attributes
            unanswered = self._get_unanswered_mandatory(item, item_type_slug)

            if unanswered:
                # Ask the first unanswered mandatory question
                first_attr = unanswered[0]
                order.set_phase(OrderPhase.CONFIGURING_ITEM)
                order.pending_item_id = item.id
                order.pending_field = f"{item_type_slug}:{first_attr['slug']}"
                order.config_options_page = 0

                # Get question text
                db_question = first_attr.get("question_text")
                attr_name = first_attr["display_name"].lower()
                if db_question:
                    question = db_question
                elif first_attr.get("input_type") == "boolean":
                    question = f"Would you like it {attr_name}?"
                else:
                    question = f"What kind of {attr_name} would you like?"

                # Add ordinal prefix for multi-item
                if same_type_count > 1:
                    message = f"For {item_desc}, {question.lower()}"
                else:
                    message = question

                return StateMachineResult(message=message, order=order)

            # No mandatory questions left - check if customization was offered
            if not item.customization_offered:
                return self._ask_customization_checkpoint(item, order)

            # Item is complete - recalculate price and mark complete
            self._recalculate_item_price(item)
            item.mark_complete()

        # All target items are complete - summarize and return
        completed_items = [
            item for item in target_items
            if item.status == TaskStatus.COMPLETE
        ]

        if completed_items:
            last_item = completed_items[-1]
            summary = last_item.get_summary()

            # Count identical items at the end for pluralization
            count = 0
            for item in reversed(completed_items):
                if item.get_summary() == summary:
                    count += 1
                else:
                    break

            if count > 1:
                summary = f"{count} {summary}s" if not summary.endswith("s") else f"{count} {summary}"

            order.clear_pending()
            order.set_phase(OrderPhase.TAKING_ITEMS)

            return StateMachineResult(
                message=got_it_anything_else(summary),
                order=order,
            )

        # Fallback to generic next question
        return self._get_next_question(order)

    # =========================================================================
    # Handle User Input for Different States
    # =========================================================================

    def handle_attribute_input(
        self, user_input: str, item: MenuItemTask, order: OrderTask, attr_slug: str
    ) -> StateMachineResult:
        """Handle user input for a specific attribute question."""
        # Check if we're in unmatched pagination flow
        pagination_result = self._handle_unmatched_pagination(user_input, item, order)
        if pagination_result:
            return pagination_result

        # Check if we're resolving a disambiguation first
        disambiguation_result = self._disambiguation_handler.handle_disambiguation_response(user_input, order)
        if disambiguation_result:
            return disambiguation_result

        # Strip common ordering prefixes from the input
        # e.g., "make it a double" -> "double", "give me triple" -> "triple"
        user_input = strip_ordering_prefix(user_input)

        # NOTE: milk_sweetener_syrup now uses the standard multi_select flow
        # which includes partial matching (e.g., "syrup" lists all syrup options)

        item_type = item.menu_item_type
        attrs = self._get_item_type_attributes(item_type)
        attr = attrs.get(attr_slug)

        if not attr:
            logger.warning("Attribute '%s' not found for %s", attr_slug, item_type)
            order.clear_pending()
            return self._get_next_question(order)

        options = attr.get("options", [])
        input_type = attr.get("input_type", "single_select")

        # Check for options inquiry / show-more BEFORE trying to match an answer
        # (Only for select types with options)
        if options and input_type in ("single_select", "multi_select"):
            # Check if user is asking for more options (pagination)
            # Accept both explicit "show more" phrases AND affirmative responses (e.g., "yes" after "do you want more?")
            if order.config_options_page > 0 and (
                self._options_inquiry_handler.is_show_more_request(user_input) or is_affirmative(user_input)
            ):
                return self._options_inquiry_handler.handle_options_inquiry(item, order, attr, options, is_show_more=True)

            # Check if user is asking about available options
            # Pass the attribute display name as topic for context-aware detection
            # e.g., "what bread do you have" when asking about bread
            topic = attr.get("display_name", "")
            if self._options_inquiry_handler.is_options_inquiry(user_input, topic=topic):
                return self._options_inquiry_handler.handle_options_inquiry(item, order, attr, options, is_show_more=False)

        # Check if user is asking about a DIFFERENT attribute's options
        # e.g., "what toppings do you have?" while being asked about condiments
        different_attr = self._options_inquiry_handler.detect_different_attribute_inquiry(user_input, item_type, attr_slug)
        if different_attr:
            diff_options = different_attr.get("options", [])
            if diff_options:
                # Switch to showing the different attribute's options
                order.pending_field = f"{item_type}:{different_attr['slug']}"
                return self._options_inquiry_handler.handle_options_inquiry(item, order, different_attr, diff_options, is_show_more=False)

        # Reset options page when user provides an actual answer
        order.config_options_page = 0

        # Handle boolean attributes
        if input_type == "boolean":
            return self._handle_boolean_input(user_input, item, order, attr)

        # Handle quantity attributes (e.g., shots)
        if input_type == "quantity":
            return self._handle_quantity_input(user_input, item, order, attr, options)

        # Handle package_multi_select (bagel packages - specify types like "3 plain, 2 everything")
        if input_type == "package_multi_select":
            return self._handle_package_input(user_input, item, order, attr)

        # Handle single/multi select
        if input_type in ("single_select", "multi_select"):
            # Check for forward delegation: if any option has forward_to_attribute set,
            # check if user input matches the target attribute's options
            forward_result = self._check_forward_delegation(
                user_input, item, order, attr, options, attrs
            )
            if forward_result:
                return forward_result

            return self._handle_select_input(user_input, item, order, attr, options)

        # Default: store raw input
        item[attr_slug] = user_input.strip()
        return self._advance_to_next_question(item, order, attr)

    def _check_forward_delegation(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        options: list[dict],
        attrs: dict,
    ) -> StateMachineResult | None:
        """Check if user input matches a forward-to attribute's options.

        This implements data-driven forward delegation: when an option has
        forward_to_attribute set, and user input matches the target attribute's
        options, we auto-select this option and forward to the target attribute.

        Example: package_variety has a "custom" option with forward_to_attribute="package_contents".
        If user says "2 plain 2 everything" instead of "custom", we:
        1. Auto-select "custom" for package_variety
        2. Forward input to package_contents handler

        Args:
            user_input: The user's input string
            item: The menu item being configured
            order: Current order state
            attr: Current attribute configuration
            options: Options for the current attribute
            attrs: All attributes for this item type

        Returns:
            StateMachineResult if forwarding occurred, None otherwise
        """
        attr_slug = attr["slug"]

        # Find options with forward delegation configured
        for opt in options:
            forward_to_attr_slug = opt.get("forward_to_attribute")
            if not forward_to_attr_slug:
                continue

            # Get the target attribute
            target_attr = attrs.get(forward_to_attr_slug)
            if not target_attr:
                logger.debug(
                    "FORWARD_DELEGATION: Target attribute '%s' not found for option '%s'",
                    forward_to_attr_slug,
                    opt.get("slug"),
                )
                continue

            # Check if user input matches target attribute's options
            # For package_multi_select, use looks_like_package_contents
            target_input_type = target_attr.get("input_type")
            if target_input_type == "package_multi_select":
                # Get the options_source_category from the target attribute (data-driven)
                target_attr_slug = target_attr.get("slug")
                options_source_category = menu_cache.get_options_source_category(target_attr_slug)

                if self._package_input_handler.looks_like_package_contents(
                    user_input, item, options_source_category
                ):
                    logger.info(
                        "FORWARD_DELEGATION: User provided '%s' matching %s options, "
                        "auto-selecting '%s' and forwarding",
                        user_input,
                        forward_to_attr_slug,
                        opt.get("slug"),
                    )
                    # Auto-select this option
                    item.add_selection(
                        slug=opt["slug"],
                        category=attr_slug,
                        quantity=1,
                        price=opt.get("price_modifier", 0),
                        display_name=opt.get("display_name"),
                    )
                    # Forward to target attribute handler
                    return self._handle_package_input(user_input, item, order, target_attr)

        return None

    def _handle_boolean_input(
        self, user_input: str, item: MenuItemTask, order: OrderTask, attr: dict
    ) -> StateMachineResult:
        """Handle yes/no input for boolean attributes.

        Uses BooleanParser to determine the boolean value from user input,
        then applies any additional selections and advances to the next question.
        """
        attr_slug = attr["slug"]

        # Use the boolean parser to parse the input
        result = self._boolean_parser.parse(user_input, attr)

        if result.value is None:
            # Couldn't parse, ask again
            question = attr.get("question_text") or f"{attr['display_name']}?"
            return StateMachineResult(
                message=f"Sorry, I didn't catch that. {question} (yes or no)",
                order=order,
            )

        # Store in selections
        item[attr_slug] = result.value

        # Extract and apply any additional selections from the input
        # (e.g., "yes with bacon" -> captures the boolean AND the bacon selection)
        self._selection_extractor.extract_and_apply_selections(user_input, item)

        # Capture any additional attributes mentioned in the input
        # e.g., "yes toasted scooped with cream cheese" captures toasted, scooped, and spread
        # Skip the current attribute to prevent double-interpretation
        self.capture_attributes_from_input(user_input, item, skip_attribute=attr_slug)

        return self._advance_to_next_question(item, order, attr)

    def _handle_quantity_input(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        options: list[dict],
    ) -> StateMachineResult:
        """Handle quantity-based input (e.g., shots).

        Delegates to QuantityInputHandler.
        """
        return self._quantity_input_handler.handle_quantity_input(
            user_input, item, order, attr, options
        )

    def _handle_package_input(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
    ) -> StateMachineResult:
        """Handle package_multi_select input (bagel packages).

        Parses input like "3 plain, 2 everything, 1 sesame" and validates
        against the pack size. Delegates to PackageInputHandler.
        """
        # Get options from the ingredient category specified in the attribute
        # This is data-driven: options_source_category tells us which ingredient category to use
        attr_slug = attr.get("slug")
        options_source_category = menu_cache.get_options_source_category(attr_slug)
        if not options_source_category:
            logger.warning(
                "No options_source_category configured for attribute '%s', defaulting to 'bread'",
                attr_slug,
            )
            options_source_category = "bread"

        raw_options = menu_cache.get_ingredient_details(options_source_category)
        if not raw_options:
            logger.warning(
                "No options found for category '%s' in package input",
                options_source_category,
            )
            package_options = []
        else:
            # Transform ingredient details to matcher-compatible format
            package_options = [
                {
                    "slug": opt["slug"],
                    "display_name": opt["name"],
                    "aliases": opt.get("patterns", []),
                }
                for opt in raw_options
            ]

        return self._package_input_handler.handle_package_input(
            user_input=user_input,
            item=item,
            order=order,
            attr=attr,
            options=package_options,
            advance_callback=self._advance_to_next_question,
        )

    def _handle_select_input(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        options: list[dict],
    ) -> StateMachineResult:
        """Handle single/multi select input - delegates to SelectInputHandler."""
        # Wrapper to capture additional attributes from user input before advancing
        # e.g., "plain bagel toasted scooped with cream cheese" when answering bread
        #
        # IMPORTANT: Only capture when user provides EXTRA info beyond just answering
        # the current question. For simple answers like "onion" for bread type, we
        # should NOT scan other attributes because:
        # - "onion" might match "onions" in toppings via alias
        # - The user is clearly just answering the bread question, not adding toppings
        #
        # We detect "simple answer" by checking if the user input is essentially just
        # the matched option name (e.g., "onion" -> matched "Onion Bagel")
        def advance_with_capture(item, order, attr, ack_text=None):
            should_capture = True
            if ack_text:
                # Check if user input is essentially just the matched option
                # e.g., "onion" matches "Onion Bagel" -> simple answer, skip capture
                # e.g., "plain toasted with cream cheese" does NOT match "Plain Bagel" -> capture
                user_lower = user_input.lower().strip()
                ack_lower = ack_text.lower().strip()
                # User input is a simple answer if it's contained in the matched option
                # or if it exactly matches (allowing for minor variations)
                if user_lower in ack_lower or ack_lower.startswith(user_lower):
                    should_capture = False

            if should_capture:
                self.capture_attributes_from_input(user_input, item, skip_attribute=attr['slug'])
            return self._advance_to_next_question(item, order, attr, ack_text)

        return self._select_input_handler.handle_select_input(
            user_input=user_input,
            item=item,
            order=order,
            attr=attr,
            options=options,
            advance_callback=advance_with_capture,
            format_display_list_callback=self._format_display_list,
            extract_selections_callback=self._selection_extractor.extract_selections_from_input,
            extract_qualifier_callback=self._extract_qualifier_for_option,
        )

    def _handle_unmatched_pagination(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle pagination responses for unmatched token messages.

        When user says "yes" or "more" after seeing "We don't have X. We have A, B, C... and more",
        this shows the next page of options.

        When user says "no" or selects an option, this resolves the pagination.

        Returns:
            StateMachineResult if pagination was handled, None otherwise.
        """
        pagination = order.pending_unmatched_pagination
        if not pagination:
            return None

        user_lower = user_input.lower().strip()

        # Check for "yes" / "more" to show next page
        if is_affirmative(user_input) or any(
            phrase in user_lower for phrase in ["more", "see more", "show more", "next"]
        ):
            return self._question_builder.advance_unmatched_pagination(order)

        # Check for "no" - decline options and advance to next question
        if is_negative(user_input):
            self._question_builder.clear_unmatched_pagination(order)
            # Get the current attribute and advance
            attr_slug = pagination.get("attr_slug")
            item_type = item.menu_item_type
            if item_type and attr_slug:
                attrs = self._get_item_type_attributes(item_type)
                attr = attrs.get(attr_slug)
                if attr:
                    return self._advance_to_next_question(item, order, attr)
            # Fallback - just get next question
            return self._get_next_question(order)

        # Check if user selected one of the available options
        available = pagination.get("available_options", [])
        matched, _ = self._option_matcher.match_single(user_input, available)
        if matched:
            # User selected an option - apply it and advance
            self._question_builder.clear_unmatched_pagination(order)
            attr_slug = pagination.get("attr_slug")

            opt_price = matched.get("price") or matched.get("price_modifier") or 0
            if opt_price == 0 and self.pricing:
                opt_price = self.pricing.lookup_generic_modifier_price(
                    matched["slug"], item.menu_item_type
                ) or 0.0

            item.add_selection(
                matched["slug"],
                attr_slug,
                quantity=1,
                price=opt_price,
                display_name=matched.get("display_name"),
                ingredient_category=matched.get("ingredient_category"),
            )
            logger.info(
                "UNMATCHED_PAGINATION: added selection '%s' for attr '%s'",
                matched["slug"], attr_slug
            )

            # Get the attribute and advance
            item_type = item.menu_item_type
            if item_type and attr_slug:
                attrs = self._get_item_type_attributes(item_type)
                attr = attrs.get(attr_slug)
                if attr:
                    return self._advance_to_next_question(
                        item, order, attr, matched.get("display_name")
                    )
            return self._get_next_question(order)

        # Input didn't match pagination flow - clear and let normal handling proceed
        # This handles cases where user ignores the pagination and orders something else
        self._question_builder.clear_unmatched_pagination(order)
        return None

    def _advance_to_next_question(
        self, item: MenuItemTask, order: OrderTask, current_attr: dict,
        matched_choice: str | None = None,
        use_multi_item_orchestration: bool = False
    ) -> StateMachineResult:
        """Advance to the next question after answering current attribute.

        Args:
            item: The menu item being configured
            order: The current order
            current_attr: The attribute that was just answered
            matched_choice: The display name of the choice the user made (for acknowledgment)
            use_multi_item_orchestration: If True, use configure_next_incomplete_item()
                to handle multiple items of the same type
        """
        item_type = item.menu_item_type
        logger.info(
            "ADVANCE_TO_NEXT: after attr=%s, item_type=%s, attribute_values=%s",
            current_attr.get("slug"), item_type, item.attribute_values
        )

        # Recalculate price after each attribute answer (data-driven pricing)
        # This handles variant pricing (size), upcharges, and any pricing model
        self._recalculate_item_price(item)

        # Check if we're in mandatory phase or optional phase
        if current_attr.get("ask_in_conversation", True):
            # Just answered a mandatory question, check for more
            unanswered_mandatory = self._get_unanswered_mandatory(item, item_type)
            if unanswered_mandatory:
                next_attr = unanswered_mandatory[0]
                result = self._ask_attribute_question(item, order, next_attr)
                # Prepend acknowledgment if provided
                if matched_choice and result.message:
                    result.message = f"Got it, {matched_choice}. {result.message}"
                return result
            else:
                # All mandatory done for this item
                if use_multi_item_orchestration:
                    # Use multi-item orchestration to check for more items
                    result = self.configure_next_incomplete_item(order, item_type)
                    if matched_choice and result.message:
                        result.message = f"Got it, {matched_choice}. {result.message}"
                    return result
                else:
                    # Single-item flow - go to checkpoint
                    result = self._ask_customization_checkpoint(item, order)
                    if matched_choice and result.message:
                        result.message = f"Got it, {matched_choice}. {result.message}"
                    return result
        else:
            # Just answered an optional question, ask for more customizations
            return self._ask_more_customizations(item, order, matched_choice)

    def _ask_more_customizations(
        self, item: MenuItemTask, order: OrderTask, matched_choice: str | None = None
    ) -> StateMachineResult:
        """Ask if user wants more customizations after completing one.

        Args:
            item: The menu item being configured
            order: The current order
            matched_choice: The display name of the choice just made (for acknowledgment)
        """
        item_type = item.menu_item_type
        unanswered = self._get_unanswered_optional(item, item_type)

        # Always recalculate price after adding a modifier
        # This ensures upcharges are applied immediately, not just when config is complete
        self._recalculate_item_price(item)

        # Build acknowledgment prefix if we have a choice to acknowledge
        ack_prefix = f"Okay, {matched_choice}. " if matched_choice else ""

        if not unanswered:
            # No more options - price already recalculated above, just complete
            item.mark_complete()
            order.clear_pending()

            # Check for other incomplete items that need configuration
            # This handles duplicated items (e.g., "make it two hot teas")
            next_result = self._get_next_question(order)
            if next_result and next_result.order.pending_field:
                # Prepend acknowledgment to the next question
                summary = item.get_summary()
                if ack_prefix:
                    return StateMachineResult(
                        message=f"{ack_prefix}Got it, {summary}. {next_result.message}",
                        order=next_result.order,
                    )
                return StateMachineResult(
                    message=f"Got it, {summary}. {next_result.message}",
                    order=next_result.order,
                )

            order.set_phase(OrderPhase.TAKING_ITEMS)
            return StateMachineResult(
                message=f"{ack_prefix}Got it, {item.get_summary()}. Anything else?",
                order=order,
            )

        # List remaining options as individual questions
        options_questions = self._format_checkpoint_questions(unanswered)

        order.set_phase(OrderPhase.CONFIGURING_ITEM)
        order.pending_item_id = item.id
        order.pending_field = PendingField.CUSTOMIZATION_CHECKPOINT

        return StateMachineResult(
            message=f"{ack_prefix}Any more changes? {options_questions}",
            order=order,
        )

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
        """Ask the question for a specific optional attribute."""
        options = attr.get("options", [])
        db_question = attr.get("question_text")

        if db_question:
            question = db_question
        elif attr.get("input_type") == "boolean":
            question = f"{attr['display_name']}?"
        elif options:
            # Only list options if there are few enough to be helpful
            if len(options) <= DEFAULT_PAGINATION_SIZE:
                options_text = self._format_display_list(options)
                question = f"What kind of {attr['display_name'].lower()}? ({options_text})"
            else:
                # Too many options - just ask, user can say "what do you have?" to see list
                question = f"What kind of {attr['display_name'].lower()}?"
        else:
            question = f"What {attr['display_name']}?"

        order.set_phase(OrderPhase.CONFIGURING_ITEM)
        order.pending_item_id = item.id
        order.pending_field = f"{item.menu_item_type}:{attr['slug']}"

        return StateMachineResult(message=question, order=order)

    def _ask_disambiguation_for_options(
        self,
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        candidates: list[dict],
        original_input: str,
    ) -> StateMachineResult:
        """Ask user to clarify which option they meant when input is ambiguous.

        Delegates to DirectOptionMatcher for the actual implementation.
        """
        return self._direct_option_matcher._ask_disambiguation_for_options(
            item, order, attr, candidates, original_input
        )

    def _try_direct_option_match(
        self,
        user_input: str,
        unanswered: list[dict],
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """
        Try to match user input directly to option values within attributes.

        Delegates to DirectOptionMatcher for the actual matching logic.
        """
        return self._direct_option_matcher.try_direct_option_match(
            user_input, unanswered, item, order
        )

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

        attrs = self._get_item_type_attributes(item_type)
        capture_attributes_from_input(
            user_input, item, attrs, self._option_matcher, skip_attribute=skip_attribute
        )
