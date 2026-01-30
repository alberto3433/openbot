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
from typing import Callable, TYPE_CHECKING

from orderbot.menu_data_cache import menu_cache
from orderbot.cache.base import pluralize
from .models import OrderTask, MenuItemTask
from .pending_fields import PendingField
from .normalization import strip_ordering_prefix
from .schemas import StateMachineResult, OrderPhase
from .parsers.constants import extract_quantity, DEFAULT_PAGINATION_SIZE
from .parsers.quantity_utils import parse_numeric_input, extract_leading_quantity
from .handler_config import BaseHandler
from .checkout_messages import got_it_anything_else
from .utils import OptionMatcher, InputNormalizer
from .utils.text import format_english_list
from .select_input_handler import SelectInputHandler
from .config_options_inquiry import OptionsInquiryHandler
from .config_disambiguation import DisambiguationHandler
from .config_question_builder import QuestionBuilder
from .config_selection_extractor import SelectionExtractor
from .direct_option_matcher import DirectOptionMatcher
from .response_utils import is_negative, is_affirmative

logger = logging.getLogger(__name__)

# Maximum character distance between a qualifier (e.g., "extra", "on the side") and
# an option name for them to be considered associated. Used in _extract_qualifier_for_option.
QUALIFIER_PROXIMITY_THRESHOLD = 15


class MenuItemConfigHandler(BaseHandler):
    """
    Handles menu item configuration with DB-driven attributes.

    Reads item type attributes from the database to determine:
    - Which questions to ask (ask_in_conversation=True for mandatory)
    - What the question text should be (question_text field)
    - What options are valid (attribute_options or item_type_ingredients)
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
        # Extracted sub-handler for select input processing
        self._select_input_handler = SelectInputHandler(
            pricing=config.pricing,
            option_matcher=self._option_matcher,
            input_normalizer=self._input_normalizer,
        )
        # Callback for processing pending parsed items (set via setter to avoid circular deps)
        # Used when disambiguation was triggered during multi-item orders and there are
        # remaining items to process after configuration completes
        self._process_pending_parsed_items_callback: "Callable[[OrderTask], StateMachineResult | None] | None" = None
        # Sub-handler for options inquiry and pagination
        self._options_inquiry_handler = OptionsInquiryHandler(
            get_optional_attributes=self._get_optional_attributes,
        )
        # Sub-handler for disambiguation resolution
        self._disambiguation_handler = DisambiguationHandler(
            get_item_type_attributes=self._get_item_type_attributes,
            format_display_list=self._format_display_list,
            extract_qualifier_for_option=self._extract_qualifier_for_option,
            advance_to_next_question=self._advance_to_next_question,
            get_next_question=self._get_next_question,
        )
        # Sub-handler for question building
        self._question_builder = QuestionBuilder()
        # Sub-handler for selection extraction
        self._selection_extractor = SelectionExtractor(pricing=config.pricing)
        # Sub-handler for direct option matching (e.g., "add mayo" without saying "condiments")
        self._direct_option_matcher = DirectOptionMatcher(
            option_matcher=self._option_matcher,
            extract_qualifier_callback=self._extract_qualifier_for_option,
            match_option_callback=self._match_option_from_input,
            ask_more_customizations_callback=self._ask_more_customizations,
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

    def supports_item_type(self, item_type_slug: str | None) -> bool:
        """Check if this handler supports the given item type.

        An item type is supported if it has linked attributes in the database.
        """
        if not item_type_slug:
            return False
        return item_type_slug in menu_cache.get_configurable_item_types()

    def _get_item_type_attributes(self, item_type_slug: str) -> dict:
        """
        Get item type attributes from centralized cache.

        Uses menu_cache as the single source of truth for all item type
        attributes (both item-type-specific and global attributes).

        Returns dict with structure:
        {
            "bread": {
                "slug": "bread",
                "display_name": "Bread",
                "question_text": "What kind of bread?",
                "ask_in_conversation": True,
                "input_type": "single_select",
                "display_order": 1,
                "options": [{"slug": "plain", "display_name": "Plain", "price": 0}, ...]
            },
            ...
        }
        """
        return menu_cache.get_item_type_attributes(item_type_slug)

    def _get_mandatory_attributes(self, item_type_slug: str) -> list[dict]:
        """Get mandatory attributes (ask_in_conversation=True) in display order."""
        attrs = self._get_item_type_attributes(item_type_slug)
        mandatory = [
            attr for attr in attrs.values()
            if attr.get("ask_in_conversation", False)
        ]
        return sorted(mandatory, key=lambda x: x.get("display_order", 999))

    def _get_optional_attributes(self, item_type_slug: str) -> list[dict]:
        """Get optional attributes (ask_in_conversation=False) in display order."""
        attrs = self._get_item_type_attributes(item_type_slug)
        optional = [
            attr for attr in attrs.values()
            if not attr.get("ask_in_conversation", True)
        ]
        return sorted(optional, key=lambda x: x.get("display_order", 999))

    def _get_unanswered_mandatory(
        self, item: MenuItemTask, item_type_slug: str
    ) -> list[dict]:
        """Get mandatory attributes that haven't been answered yet.

        Checks both canonical attribute slugs and legacy aliases to handle
        backward compatibility with items created by legacy handlers.
        Also checks direct model fields for certain attributes.
        """
        mandatory = self._get_mandatory_attributes(item_type_slug)
        unanswered = []
        logger.info(
            "GET_UNANSWERED_MANDATORY: item_type=%s, attribute_values=%s",
            item_type_slug, item.attribute_values
        )
        for attr in mandatory:
            slug = attr["slug"]
            # Check canonical slug in attribute_values
            # All properties (bread, toasted, etc.) now use attribute_values as backing store
            if slug in item:
                logger.debug("  %s: FOUND in attribute_values", slug)
                continue
            logger.debug("  %s: NOT FOUND - adding to unanswered", slug)
            unanswered.append(attr)
        logger.info(
            "GET_UNANSWERED_MANDATORY result: %s",
            [a["slug"] for a in unanswered]
        )
        return unanswered

    def _get_unanswered_optional(
        self, item: MenuItemTask, item_type_slug: str
    ) -> list[dict]:
        """Get optional attributes that haven't been answered yet.

        Checks canonical attribute slugs in attribute_values.
        All properties (bread, toasted, etc.) now use attribute_values as backing store.
        """
        optional = self._get_optional_attributes(item_type_slug)
        unanswered = []
        for attr in optional:
            slug = attr["slug"]
            # Check canonical slug in attribute_values
            if slug in item:
                continue
            unanswered.append(attr)
        return unanswered

    def _extract_quantity_from_input(self, user_input: str) -> tuple[int, str]:
        """
        Extract quantity from user input.

        Returns (quantity, remaining_text) tuple.
        Delegates to InputNormalizer.
        """
        return self._input_normalizer.extract_leading_quantity(user_input)

    def _match_option_from_input(
        self, user_input: str, options: list[dict]
    ) -> tuple[dict | None, list[dict]]:
        """
        Try to match user input to an option with smart partial matching.

        Delegates to OptionMatcher.match_single().
        """
        return self._option_matcher.match_single(user_input, options)

    def _tokenize_multi_input(self, user_input: str) -> list[str]:
        """
        Tokenize compound input into individual items.

        Delegates to InputNormalizer.
        """
        return self._input_normalizer.tokenize_multi_input(user_input)

    def _match_multiple_options_from_input(
        self, user_input: str, options: list[dict]
    ) -> list[dict]:
        """
        Match ALL options mentioned in user input (for multi_select attributes).

        Delegates to OptionMatcher.match_multiple().
        """
        return self._option_matcher.match_multiple(user_input, options)

    def _is_whole_word_match(self, needle: str, haystack: str) -> bool:
        """Check if needle appears as a whole word/phrase in haystack."""
        return self._option_matcher._is_whole_word_match(needle, haystack)

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
        opt_match = re.search(rf'\b{re.escape(option_lower)}\b', user_lower)
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
            if self._is_whole_word_match(user_lower, display_lower):
                matched.append(attr)
                continue
            if self._is_whole_word_match(user_lower, slug_readable):
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

        Args:
            items: List of dicts containing the display values
            key: Key to extract from each dict (default: "display_name")
            conjunction: Word to join items (default: "or")

        Returns:
            Formatted string like "A, B, or C"
        """
        names = [item.get(key, "") for item in items if item.get(key)]
        return format_english_list(names, conjunction=conjunction)

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

        # Find first unanswered mandatory attribute
        unanswered = self._get_unanswered_mandatory(item, item_type)
        if not unanswered:
            # No mandatory questions, go to checkpoint
            return self._ask_customization_checkpoint(item, order)

        first_attr = unanswered[0]
        # Reset options page for first question
        order.config_options_page = 0
        return self._ask_attribute_question(item, order, first_attr, is_first_question=True)

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

        # Calculate ordinal position and context for multi-item orders
        ordinal, item_num, has_duplicates = self._question_builder.calculate_item_ordinal(item, order)
        multi_count = len(order.multi_item_config_names) if order.multi_item_config_names else 1
        item_ref = item.get_display_name().lower()

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
        self, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult:
        """Ask if user wants to customize with optional attributes."""
        item_type = item.menu_item_type
        unanswered_optional = self._get_unanswered_optional(item, item_type)

        if not unanswered_optional:
            # No optional attributes available, recalculate price and complete
            item.customization_offered = True
            self._recalculate_item_price(item)
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
            if order.has_queued_config_items():
                next_config = order.pop_next_config_item()
                next_item = order.items.get_item_by_id(next_config["item_id"])
                if next_item and isinstance(next_item, MenuItemTask):
                    logger.info(
                        "Processing queued item after completing %s: %s (%s)",
                        item.get_display_name(), next_config.get("item_name"), next_config["item_id"][:8]
                    )
                    return self.get_first_question(next_item, order)

            order.set_phase(OrderPhase.TAKING_ITEMS)
            return StateMachineResult(
                message=got_it_anything_else(item.get_summary()),
                order=order,
            )

        # Mark that we've reached the checkpoint
        item.customization_offered = True

        order.set_phase(OrderPhase.CONFIGURING_ITEM)
        order.pending_item_id = item.id
        order.pending_field = PendingField.CUSTOMIZATION_CHECKPOINT

        # List available customization options
        options_list = self._format_display_list(unanswered_optional)

        return StateMachineResult(
            message=f"Any more changes to that? You can add {options_list}.",
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
        from .models import TaskStatus
        from .message_builder import MessageBuilder

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
            if order.config_options_page > 0 and self._options_inquiry_handler.is_show_more_request(user_input):
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

        # Handle single/multi select
        if input_type in ("single_select", "multi_select"):
            return self._handle_select_input(user_input, item, order, attr, options)

        # Default: store raw input
        item[attr_slug] = user_input.strip()
        return self._advance_to_next_question(item, order, attr)

    def _handle_boolean_input(
        self, user_input: str, item: MenuItemTask, order: OrderTask, attr: dict
    ) -> StateMachineResult:
        """Handle yes/no input for boolean attributes."""
        user_lower = user_input.lower().strip()
        attr_slug = attr["slug"]

        # Check for explicit yes/no using patterns from database
        yes_patterns = menu_cache.get_response_patterns("affirmative")
        no_patterns = menu_cache.get_response_patterns("negative")

        # Also check for the attribute name with/without "not"
        attr_name = attr["display_name"].lower()
        bool_value: bool | None = None
        if f"not {attr_name}" in user_lower or f"un{attr_name}" in user_lower:
            bool_value = False
        elif any(p in user_lower for p in yes_patterns) or attr_name in user_lower:
            bool_value = True
        elif any(p in user_lower for p in no_patterns):
            bool_value = False
        else:
            # Couldn't parse, ask again
            question = attr.get("question_text") or f"{attr['display_name']}?"
            return StateMachineResult(
                message=f"Sorry, I didn't catch that. {question} (yes or no)",
                order=order,
            )

        # Store in selections
        item[attr_slug] = bool_value

        # Extract and apply any additional selections from the input
        # (e.g., "yes with bacon" -> captures the boolean AND the bacon selection)
        self._selection_extractor.extract_and_apply_selections(user_input, item)

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

        This input type interprets:
        - Negative responses ("no", "none") as skip
        - Affirmative responses ("yes", "sure") as quantity=1
        - Numeric words ("double", "triple", "two") as that quantity
        - Digits ("2", "3") as that quantity

        Uses the first available option for unit price and display name.
        Validates against max_selections from the attribute config.
        """
        attr_slug = attr["slug"]
        user_lower = user_input.lower().strip()

        # Get unit option (first available option defines unit price and name)
        available_options = [opt for opt in options if opt.get("is_available", True)]
        if not available_options:
            logger.warning("No available options for quantity attribute %s", attr_slug)
            return self._advance_to_next_question(item, order, attr)

        unit_option = available_options[0]
        unit_price = unit_option.get("price") or unit_option.get("price_modifier") or 0.0
        unit_name = unit_option.get("display_name", attr["display_name"])
        unit_slug = unit_option.get("slug", attr_slug)

        # Get max quantity from attribute config
        max_qty = attr.get("max_selections") or 10

        # Check for negative responses (skip)
        # Handles exact matches ("no", "none") and phrases like "no shots", "no extra shots"
        is_neg = is_negative(user_input)

        # Also check if input starts with a negative pattern followed by the attribute/unit name
        # e.g., "no shots" when asking about extra shots, "no syrup" when asking about syrup
        if not is_neg:
            unit_name_lower = unit_name.lower()
            attr_name_lower = attr["display_name"].lower()
            no_patterns = menu_cache.get_response_patterns("negative")
            for neg_pattern in no_patterns:
                # Check patterns like "no shots", "no extra shots", "none of that"
                if user_lower.startswith(neg_pattern + " "):
                    remainder = user_lower[len(neg_pattern) + 1:].strip()
                    # Check if remainder contains the unit name or attribute name
                    if (unit_name_lower in remainder or
                        attr_name_lower in remainder or
                        unit_slug in remainder or
                        attr_slug in remainder):
                        is_neg = True
                        break

        if is_neg:
            # Mark attribute as declined so _get_unanswered_mandatory knows it's answered
            # Using item[attr_slug] = None triggers __setitem__ which adds to modifiers
            item[attr_slug] = None
            return self._advance_to_next_question(item, order, attr)

        # Check for affirmative responses (quantity=1)
        # Also treat "extra" or "extra <anything>" as affirmative (e.g., "extra shot" = 1 shot)
        # This handles typos like "extra host" as "yes, one"
        is_extra_response = user_lower == "extra" or user_lower.startswith("extra ")
        if is_affirmative(user_input) or is_extra_response:
            quantity = 1
        else:
            # Try to parse numeric quantity
            parsed_qty = parse_numeric_input(user_input)
            if parsed_qty is None:
                # Couldn't parse - ask for clarification
                question = attr.get("question_text") or f"How many {attr['display_name'].lower()}?"
                return StateMachineResult(
                    message=f"Sorry, I didn't catch that. {question}",
                    order=order,
                )
            quantity = parsed_qty

        # Validate quantity
        if quantity < 1:
            return self._advance_to_next_question(item, order, attr)
        if quantity > max_qty:
            return StateMachineResult(
                message=f"Sorry, the maximum is {max_qty}. How many would you like?",
                order=order,
            )

        # Add selection with per-unit price
        # Note: Don't include quantity in display_name - the display layer handles that
        # But DO pluralize the name when quantity > 1
        # Store per-unit price; the pricing engine will multiply by quantity
        if quantity > 1:
            display_name = pluralize(unit_name)
        else:
            display_name = unit_name

        item.add_selection(
            unit_slug,
            attr_slug,
            quantity=quantity,
            price=unit_price,  # Per-unit price, not total
            display_name=display_name,
        )

        logger.info(
            "QUANTITY_INPUT: %s=%d (unit_price=$%.2f, total=$%.2f) from input '%s'",
            attr_slug, quantity, unit_price, quantity * unit_price, user_input
        )

        # Build acknowledgment with quantity prefix and pluralization
        if quantity > 1:
            plural_name = pluralize(unit_name)
            ack_text = f"{quantity} {plural_name}"
        else:
            ack_text = unit_name
        return self._advance_to_next_question(item, order, attr, ack_text)

    def _handle_select_input(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        options: list[dict],
    ) -> StateMachineResult:
        """Handle single/multi select input - delegates to SelectInputHandler."""
        return self._select_input_handler.handle_select_input(
            user_input=user_input,
            item=item,
            order=order,
            attr=attr,
            options=options,
            advance_callback=self._advance_to_next_question,
            format_display_list_callback=self._format_display_list,
            extract_selections_callback=self._selection_extractor.extract_selections_from_input,
            extract_qualifier_callback=self._extract_qualifier_for_option,
        )

    def _format_options_list_for_clarification(self, options: list[str]) -> str:
        """Format options list for clarification question.

        Args:
            options: List of option display names

        Returns:
            Formatted string like "A, B, C, or D"
        """
        return format_english_list(options, conjunction="or")

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
                return self._ask_attribute_question(item, order, next_attr)
            else:
                # All mandatory done for this item
                if use_multi_item_orchestration:
                    # Use multi-item orchestration to check for more items
                    return self.configure_next_incomplete_item(order, item_type)
                else:
                    # Single-item flow - go to checkpoint
                    return self._ask_customization_checkpoint(item, order)
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

        # Build acknowledgment prefix if we have a choice to acknowledge
        ack_prefix = f"Okay, {matched_choice}. " if matched_choice else ""

        if not unanswered:
            # No more options, recalculate price and complete
            self._recalculate_item_price(item)
            item.mark_complete()
            order.set_phase(OrderPhase.TAKING_ITEMS)
            order.clear_pending()
            return StateMachineResult(
                message=f"{ack_prefix}Got it, {item.get_summary()}. Anything else?",
                order=order,
            )

        # List remaining options
        options_list = self._format_display_list(unanswered)

        order.set_phase(OrderPhase.CONFIGURING_ITEM)
        order.pending_item_id = item.id
        order.pending_field = PendingField.CUSTOMIZATION_CHECKPOINT

        return StateMachineResult(
            message=f"{ack_prefix}Any more changes to that? You can add {options_list}.",
            order=order,
        )

    def handle_customization_checkpoint(
        self, user_input: str, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult:
        """Handle user response to customization checkpoint."""
        user_lower = user_input.lower().strip()
        item_type = item.menu_item_type

        # Check for "no" or "done" - user doesn't want to customize further
        no_patterns = menu_cache.get_response_patterns("negative")
        is_declining = (
            any(user_lower == p or user_lower.startswith(p) for p in no_patterns)
            or menu_cache.is_done(user_lower)
        )
        if is_declining:
            # Recalculate price and complete
            self._recalculate_item_price(item)
            item.mark_complete()
            order.clear_pending()

            # Check if there are pending parsed items that haven't been added yet
            # This handles the case where disambiguation was triggered and remaining items
            # in the order were stored (e.g., "bagel and latte" - latte is stored while
            # we disambiguate and configure bagel)
            if self._process_pending_parsed_items_callback:
                pending_result = self._process_pending_parsed_items_callback(order)
                if pending_result:
                    return pending_result

            # Check if there are more items to configure (e.g., coffee added with bagel)
            if self._get_next_question:
                next_result = self._get_next_question(order)
                # If there's another item to configure, return that
                if next_result and next_result.order.pending_field:
                    return next_result

            # No more items to configure - go back to taking items
            order.set_phase(OrderPhase.TAKING_ITEMS)
            return StateMachineResult(
                message=got_it_anything_else(item.get_summary()),
                order=order,
            )

        unanswered = self._get_unanswered_optional(item, item_type)

        # Check for options inquiry about ANY attribute (not just unanswered)
        # e.g., "what condiments do you have?" even after adding salt
        all_optional = self._get_optional_attributes(item_type)
        inquiry_attr = self._options_inquiry_handler.detect_options_inquiry_for_attribute(user_input, all_optional)
        if inquiry_attr:
            options = inquiry_attr.get("options", [])
            if options:
                order.pending_field = f"{item_type}:{inquiry_attr['slug']}"
                return self._options_inquiry_handler.handle_options_inquiry(
                    item, order, inquiry_attr, options, is_show_more=False
                )

        # Check for "yes" - user wants to see the list
        yes_patterns = menu_cache.get_response_patterns("affirmative")
        if any(user_lower == p or user_lower.startswith(p + " ") for p in yes_patterns):
            # If just "yes", list the options
            if user_lower in yes_patterns:
                options_list = self._format_display_list(unanswered)
                order.pending_field = PendingField.CUSTOMIZATION_SELECTION
                return StateMachineResult(
                    message=f"You can add: {options_list}. What would you like?",
                    order=order,
                )

        # Try to match specific attribute(s) from input
        matched_attrs = self._match_attribute_from_input(user_input, unanswered)

        if matched_attrs:
            attr = matched_attrs[0]

            # Check if user is asking about options ("what condiments do you have?")
            # rather than selecting an attribute to configure
            if self._options_inquiry_handler.is_options_inquiry(user_input, topic=attr.get("display_name", "")):
                options = attr.get("options", [])
                if options:
                    # Set pending_field to this attribute so "what else?" goes through
                    # _handle_attribute_answer() which has show-more pagination logic
                    order.pending_field = f"{item.menu_item_type}:{attr['slug']}"
                    return self._options_inquiry_handler.handle_options_inquiry(item, order, attr, options, is_show_more=False)

            # For boolean attributes, set value directly without asking
            if attr.get("input_type") == "boolean":
                attr_slug = attr.get("slug")
                # Check for negation patterns ("no decaf", "not sliced", "without decaf")
                negation_pattern = rf"\b(no|not|without|skip)\s+{re.escape(attr_slug)}\b"
                is_negated = bool(re.search(negation_pattern, user_lower, re.IGNORECASE))
                item[attr_slug] = not is_negated

                # Recalculate price and check if more to configure
                self._recalculate_item_price(item)
                remaining = self._get_unanswered_optional(item, item_type)
                if remaining:
                    return self._ask_customization_checkpoint(item, order)

                # No more optional attributes - complete the item
                item.mark_complete()
                order.clear_pending()
                if self._get_next_question:
                    next_result = self._get_next_question(order)
                    if next_result and next_result.order.pending_field:
                        return next_result
                order.set_phase(OrderPhase.TAKING_ITEMS)
                return StateMachineResult(
                    message=got_it_anything_else(item.get_summary()),
                    order=order,
                )

            # Non-boolean attribute - check if user also specified an option value
            # e.g., "american cheese" should apply "american" directly, not ask "What kind?"
            attr_slug = attr["slug"]
            options = attr.get("options", [])
            input_type = attr.get("input_type", "single_select")
            # Extract quantity and use remaining text for option matching
            # e.g., "2 egg whites" → quantity=2, remaining="egg whites"
            quantity, remaining_text = self._extract_quantity_from_input(user_input)

            if options:
                user_clean = remaining_text.lower().strip()
                if user_clean.startswith("add "):
                    user_clean = user_clean[4:].strip()

                if input_type == "multi_select":
                    # Use disambiguation-aware matching for multi-select
                    matched_opts, disambiguation = self._option_matcher.match_multiple_with_disambiguation(
                        user_clean, options
                    )

                    if disambiguation:
                        # Single ambiguous term matches multiple options - ask user to clarify
                        return self._ask_disambiguation_for_options(
                            item, order, attr, disambiguation, user_input
                        )

                    if matched_opts:
                        # Apply matched options directly
                        display_parts = []
                        for opt in matched_opts:
                            opt_name = opt["display_name"]
                            opt_quantity = extract_quantity(user_clean, opt_name.lower())
                            if opt_quantity == 1:
                                opt_quantity = extract_quantity(user_clean, opt["slug"].replace("_", " "))
                            if opt_quantity == 1 and quantity > 1:
                                opt_quantity = quantity
                            opt_price = opt.get("price") or opt.get("price_modifier") or 0
                            item.add_selection(
                                opt["slug"], attr_slug,
                                quantity=opt_quantity, price=opt_price,
                                display_name=opt_name,
                            )
                            display = f"{opt_quantity} {opt_name}" if opt_quantity > 1 else opt_name
                            display_parts.append(display)
                        display_text = ", ".join(display_parts)
                        return self._ask_more_customizations(item, order, f"{display_text} added")
                else:
                    # single_select
                    matched_opt, _ = self._match_option_from_input(user_clean, options)
                    if matched_opt:
                        opt_name = matched_opt["display_name"]
                        opt_price = matched_opt.get("price") or matched_opt.get("price_modifier") or 0
                        item.add_selection(
                            matched_opt["slug"], attr_slug,
                            quantity=quantity, price=opt_price,
                            display_name=opt_name,
                        )
                        display = f"{quantity} {opt_name}" if quantity > 1 else opt_name
                        return self._ask_more_customizations(item, order, f"{display} added")

            # No option matched - ask for the option
            # Store quantity so it can be applied when user answers
            if quantity > 1:
                order.pending_modifier_quantity = quantity
            return self._ask_optional_attribute(item, order, attr)

        # Try to match option values directly (e.g., "add a little mayo" -> mayo in condiments)
        # This allows users to specify options without naming the attribute
        result = self._try_direct_option_match(user_input, unanswered, item, order)
        if result:
            return result

        # Couldn't match - inform user we don't have what they asked for
        options_list = self._format_display_list(unanswered)
        return StateMachineResult(
            message=f"Sorry, we don't have {user_input}. You can add: {options_list}. What would you like?",
            order=order,
        )

    def handle_customization_selection(
        self, user_input: str, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult:
        """Handle user selecting which attribute to customize from the list."""
        # This is essentially the same as checkpoint handling
        return self.handle_customization_checkpoint(user_input, item, order)

    def _ask_optional_attribute(
        self, item: MenuItemTask, order: OrderTask, attr: dict
    ) -> StateMachineResult:
        """Ask the question for a specific optional attribute."""
        options = attr.get("options", [])

        if attr.get("input_type") == "boolean":
            # For boolean, just confirm
            question = attr.get("question_text") or f"{attr['display_name']}?"
        elif options:
            # Only list options if there are few enough to be helpful
            if len(options) <= DEFAULT_PAGINATION_SIZE:
                options_text = self._format_display_list(options)
                question = f"What kind of {attr['display_name'].lower()}? ({options_text})"
            else:
                # Too many options - just ask, user can say "what do you have?" to see list
                question = f"What kind of {attr['display_name'].lower()}?"
        else:
            question = attr.get("question_text") or f"What {attr['display_name']}?"

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
        self, user_input: str, item: MenuItemTask
    ) -> None:
        """
        Capture any attributes mentioned in the initial order input.

        Called when item is first created to pre-fill attributes.
        e.g., "deli sandwich with scrambled egg on a plain bagel toasted"
        """
        item_type = item.menu_item_type
        if not item_type or not self.supports_item_type(item_type):
            return

        attrs = self._get_item_type_attributes(item_type)
        user_lower = user_input.lower()

        for attr_slug, attr in attrs.items():
            # Skip if already answered
            if attr_slug in item:
                continue

            options = attr.get("options", [])
            input_type = attr.get("input_type", "single_select")

            if input_type == "boolean":
                # Check for explicit mentions
                attr_name = attr["display_name"].lower()
                if f"not {attr_name}" in user_lower:
                    item[attr_slug] = False
                    logger.info("Captured %s=False from input", attr_slug)
                elif attr_name in user_lower:
                    item[attr_slug] = True
                    logger.info("Captured %s=True from input", attr_slug)

            elif input_type in ("single_select", "multi_select") and options:
                # Only capture if we get a unique match (ignore disambiguation cases)
                matched, _ = self._match_option_from_input(user_input, options)
                if matched:
                    # Check if the matched option is available
                    if not matched.get("is_available", True):
                        # Store as unavailable selection for helpful messaging
                        item.unavailable_selections[attr_slug] = {
                            "attempted_slug": matched["slug"],
                            "attempted_display": matched.get("display_name", matched["slug"]),
                        }
                        logger.info(
                            "Captured unavailable %s=%s from input (will prompt for alternative)",
                            attr_slug, matched["slug"]
                        )
                        continue  # Don't add the selection
                    opt_price = matched.get("price") or matched.get("price_modifier") or 0
                    item.add_selection(
                        matched["slug"],
                        attr_slug,
                        price=opt_price,
                        display_name=matched.get("display_name"),
                    )
                    logger.info("Captured %s=%s from input", attr_slug, matched["slug"])
