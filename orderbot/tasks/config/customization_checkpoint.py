"""
Customization Checkpoint Handler for Menu Item Configuration.

Handles user responses to customization checkpoint during item configuration,
such as adding optional modifiers or completing the item.

Extracted from menu_item_config_handler.py for better separation of concerns.
"""

import logging
import re
from typing import Callable, TYPE_CHECKING

from orderbot.cache import menu_cache

from ..schemas import StateMachineResult, OrderPhase
from ..pending_fields import PendingField
from ..checkout_messages import got_it_anything_else
from ..parsers.constants import extract_quantity_for_pattern

if TYPE_CHECKING:
    from ..models import OrderTask, MenuItemTask
    from .options_inquiry import OptionsInquiryHandler
    from ..utils import OptionMatcher

logger = logging.getLogger(__name__)

__all__ = ["CustomizationCheckpointHandler"]


class CustomizationCheckpointHandler:
    """
    Handles customization checkpoint responses during menu item configuration.

    Provides methods for:
    - Processing "no"/"done" responses to complete customization
    - Handling options inquiries for attributes
    - Matching specific attributes from user input
    - Boolean attribute handling
    - Direct option value matching
    """

    def __init__(
        self,
        options_inquiry_handler: "OptionsInquiryHandler",
        option_matcher: "OptionMatcher",
        recalculate_item_price: Callable[["MenuItemTask"], None],
        get_unanswered_optional: Callable[["MenuItemTask", str], list[dict]],
        get_optional_attributes: Callable[[str], list[dict]],
        format_display_list: Callable[[list[dict]], str],
        match_attribute_from_input: Callable[[str, list[dict]], list[dict]],
        extract_quantity_from_input: Callable[[str], tuple[int, str]],
        ask_disambiguation_for_options: Callable[
            ["MenuItemTask", "OrderTask", dict, dict, str], StateMachineResult
        ],
        ask_customization_checkpoint: Callable[
            ["MenuItemTask", "OrderTask", str | None], StateMachineResult
        ],
        ask_optional_attribute: Callable[
            ["MenuItemTask", "OrderTask", dict], StateMachineResult
        ],
        try_direct_option_match: Callable[
            [str, list[dict], "MenuItemTask", "OrderTask"], StateMachineResult | None
        ],
        get_next_question: Callable[["OrderTask"], StateMachineResult | None] | None = None,
        process_pending_parsed_items_callback: Callable[
            ["OrderTask"], StateMachineResult | None
        ] | None = None,
    ) -> None:
        """Initialize the customization checkpoint handler.

        Args:
            options_inquiry_handler: Handler for options inquiry questions.
            option_matcher: Matcher for option values.
            recalculate_item_price: Callback to recalculate item price.
            get_unanswered_optional: Callback to get unanswered optional attributes.
            get_optional_attributes: Callback to get all optional attributes for item type.
            format_display_list: Callback to format a list of options for display.
            match_attribute_from_input: Callback to match attributes from user input.
            extract_quantity_from_input: Callback to extract quantity from user input.
            ask_disambiguation_for_options: Callback to ask disambiguation for options.
            ask_customization_checkpoint: Callback to ask customization checkpoint.
            ask_optional_attribute: Callback to ask for a specific optional attribute.
            try_direct_option_match: Callback to try matching option values directly.
            get_next_question: Callback to get next question when item is complete.
            process_pending_parsed_items_callback: Callback to process pending parsed items.
        """
        self._options_inquiry_handler = options_inquiry_handler
        self._option_matcher = option_matcher
        self._recalculate_item_price = recalculate_item_price
        self._get_unanswered_optional = get_unanswered_optional
        self._get_optional_attributes = get_optional_attributes
        self._format_display_list = format_display_list
        self._match_attribute_from_input = match_attribute_from_input
        self._extract_quantity_from_input = extract_quantity_from_input
        self._ask_disambiguation_for_options = ask_disambiguation_for_options
        self._ask_customization_checkpoint = ask_customization_checkpoint
        self._ask_optional_attribute = ask_optional_attribute
        self._try_direct_option_match = try_direct_option_match
        self._get_next_question = get_next_question
        self._process_pending_parsed_items_callback = process_pending_parsed_items_callback

    def handle_customization_checkpoint(
        self, user_input: str, item: "MenuItemTask", order: "OrderTask"
    ) -> StateMachineResult:
        """Handle user response to customization checkpoint.

        Args:
            user_input: User's input text
            item: Menu item being configured
            order: Current order

        Returns:
            StateMachineResult with next question or completion message
        """
        user_lower = user_input.lower().strip()
        item_type = item.menu_item_type

        # Check for "no" or "done" - user doesn't want to customize further
        no_patterns = menu_cache.get_response_patterns("negative")
        is_declining = (
            any(user_lower == p or user_lower.startswith(p) for p in no_patterns)
            or menu_cache.is_done(user_lower)
        )
        if is_declining:
            return self._handle_declining(item, order)

        unanswered = self._get_unanswered_optional(item, item_type)

        # Get all optional attributes for direct option matching
        all_optional = self._get_optional_attributes(item_type)

        # Check for options inquiry about ANY attribute (mandatory or optional)
        # e.g., "what spreads do you have?" even if user already answered "no" to spreads
        all_attrs = menu_cache.get_item_type_attributes(item_type)
        all_attrs_list = list(all_attrs.values())
        inquiry_attr = self._options_inquiry_handler.detect_options_inquiry_for_attribute(
            user_input, all_attrs_list
        )
        if inquiry_attr:
            options = inquiry_attr.get("options", [])
            if options:
                # Set pending_field to the attribute so pagination ("show more") works
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
            return self._handle_matched_attribute(
                user_input, user_lower, item, order, item_type, matched_attrs[0]
            )

        # Try to match option values directly (e.g., "add a little mayo" -> mayo in condiments)
        # This allows users to specify options without naming the attribute
        # Use ALL optional attributes, not just unanswered - user may want to add to
        # an attribute they previously declined (e.g., said "no" to shots, now says "extra shot")
        result = self._try_direct_option_match(user_input, all_optional, item, order)
        if result:
            return result

        # Couldn't match - inform user we don't have what they asked for
        options_list = self._format_display_list(unanswered)
        return StateMachineResult(
            message=f"Sorry, we don't have {user_input}. You can add: {options_list}. What would you like?",
            order=order,
        )

    def _handle_declining(
        self, item: "MenuItemTask", order: "OrderTask"
    ) -> StateMachineResult:
        """Handle user declining further customization.

        Args:
            item: Menu item being configured
            order: Current order

        Returns:
            StateMachineResult with completion or next item message
        """
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

    def _handle_matched_attribute(
        self,
        user_input: str,
        user_lower: str,
        item: "MenuItemTask",
        order: "OrderTask",
        item_type: str,
        attr: dict,
    ) -> StateMachineResult:
        """Handle when user input matches a specific attribute.

        Args:
            user_input: Original user input
            user_lower: Lowercased user input
            item: Menu item being configured
            order: Current order
            item_type: Item type slug
            attr: Matched attribute dict

        Returns:
            StateMachineResult with next action
        """
        # Check if user is asking about options ("what condiments do you have?")
        # rather than selecting an attribute to configure
        if self._options_inquiry_handler.is_options_inquiry(
            user_input, topic=attr.get("display_name", "")
        ):
            options = attr.get("options", [])
            if options:
                # Set pending_field to this attribute so "what else?" goes through
                # _handle_attribute_answer() which has show-more pagination logic
                order.pending_field = f"{item.menu_item_type}:{attr['slug']}"
                return self._options_inquiry_handler.handle_options_inquiry(
                    item, order, attr, options, is_show_more=False
                )

        # For boolean attributes, set value directly without asking
        if attr.get("input_type") == "boolean":
            return self._handle_boolean_attribute(
                user_lower, item, order, item_type, attr
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
            result = self._try_match_option_value(
                remaining_text, item, order, attr, attr_slug, options, input_type, quantity
            )
            if result:
                return result

        # No option matched - ask for the option
        # Store quantity so it can be applied when user answers
        if quantity > 1:
            order.pending_modifier_quantity = quantity
        return self._ask_optional_attribute(item, order, attr)

    def _handle_boolean_attribute(
        self,
        user_lower: str,
        item: "MenuItemTask",
        order: "OrderTask",
        item_type: str,
        attr: dict,
    ) -> StateMachineResult:
        """Handle boolean attribute selection.

        Args:
            user_lower: Lowercased user input
            item: Menu item being configured
            order: Current order
            item_type: Item type slug
            attr: Attribute dict

        Returns:
            StateMachineResult with next action
        """
        attr_slug = attr.get("slug")
        # Check for negation patterns ("no decaf", "not sliced", "without decaf")
        negation_pattern = rf"\b(no|not|without|skip)\s+{re.escape(attr_slug)}\b"
        is_negated = bool(re.search(negation_pattern, user_lower, re.IGNORECASE))
        item[attr_slug] = not is_negated

        # Recalculate price and check if more to configure
        self._recalculate_item_price(item)
        remaining = self._get_unanswered_optional(item, item_type)
        if remaining:
            return self._ask_customization_checkpoint(item, order, None)

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

    def _try_match_option_value(
        self,
        remaining_text: str,
        item: "MenuItemTask",
        order: "OrderTask",
        attr: dict,
        attr_slug: str,
        options: list[dict],
        input_type: str,
        quantity: int,
    ) -> StateMachineResult | None:
        """Try to match option value from user input.

        Args:
            remaining_text: Text after quantity extraction
            item: Menu item being configured
            order: Current order
            attr: Attribute dict
            attr_slug: Attribute slug
            options: Available options
            input_type: Attribute input type
            quantity: Extracted quantity

        Returns:
            StateMachineResult if option matched, None otherwise
        """
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
                    item, order, attr, disambiguation, remaining_text
                )

            if matched_opts:
                # Apply matched options directly
                display_parts = []
                for opt in matched_opts:
                    opt_name = opt["display_name"]
                    opt_quantity = extract_quantity_for_pattern(user_clean, opt_name.lower())
                    if opt_quantity == 1:
                        opt_quantity = extract_quantity_for_pattern(user_clean, opt["slug"].replace("_", " "))
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
                return self._ask_customization_checkpoint(item, order, f"{display_text} added")
        else:
            # single_select
            matched_opt, _ = self._option_matcher.match_single(user_clean, options)
            if matched_opt:
                opt_name = matched_opt["display_name"]
                opt_price = matched_opt.get("price") or matched_opt.get("price_modifier") or 0
                item.add_selection(
                    matched_opt["slug"], attr_slug,
                    quantity=quantity, price=opt_price,
                    display_name=opt_name,
                )
                display = f"{quantity} {opt_name}" if quantity > 1 else opt_name
                return self._ask_customization_checkpoint(item, order, f"{display} added")

        return None

    def handle_customization_selection(
        self, user_input: str, item: "MenuItemTask", order: "OrderTask"
    ) -> StateMachineResult:
        """Handle user selecting which attribute to customize from the list.

        This is essentially the same as checkpoint handling.

        Args:
            user_input: User's input text
            item: Menu item being configured
            order: Current order

        Returns:
            StateMachineResult with next action
        """
        return self.handle_customization_checkpoint(user_input, item, order)
