from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache
from ..models import OrderTask, MenuItemTask
from ..normalization import strip_ordering_prefix
from ..parsers import strip_conversational_fillers
from ..schemas import StateMachineResult
from ..utils import OptionMatcher
from ..utils.text import normalize_text
from ..response_utils import is_affirmative

if TYPE_CHECKING:
    from .handler import MenuItemConfigHandler

logger = logging.getLogger(__name__)


class ConfigInputDispatch:

    def __init__(self, parent: MenuItemConfigHandler) -> None:
        self._parent = parent

    def handle_attribute_input(
        self, user_input: str, item: MenuItemTask, order: OrderTask, attr_slug: str
    ) -> StateMachineResult:
        """Handle user input for a specific attribute question."""
        # Check if we're in unmatched pagination flow
        pagination_result = self._parent._question_flow._handle_unmatched_pagination(user_input, item, order)
        if pagination_result:
            return pagination_result

        # Check if we're resolving a disambiguation first
        disambiguation_result = self._parent._disambiguation_handler.handle_disambiguation_response(user_input, order)
        if disambiguation_result:
            return disambiguation_result

        # Strip conversational fillers and ordering prefixes from the input
        # e.g., "wait, make that a large" -> "large", "can I have butter?" -> "butter"
        user_input = strip_conversational_fillers(user_input)
        user_input = strip_ordering_prefix(user_input).rstrip("?!.,")

        # NOTE: milk_sweetener_syrup now uses the standard multi_select flow
        # which includes partial matching (e.g., "syrup" lists all syrup options)

        item_type = item.menu_item_type
        attrs = menu_cache.get_item_type_attributes(item_type)
        attr = attrs.get(attr_slug)

        if not attr:
            logger.warning("Attribute '%s' not found for %s", attr_slug, item_type)
            order.clear_pending()
            return self._parent._get_next_question(order)

        options = attr.get("options", [])
        input_type = attr.get("input_type", "single_select")

        # Check for options inquiry / show-more BEFORE trying to match an answer
        # (Only for select types with options)
        if options and input_type in ("single_select", "multi_select"):
            # Check if user is asking for more options (pagination)
            # Accept both explicit "show more" phrases AND affirmative responses (e.g., "yes" after "do you want more?")
            if order.config_options_page > 0 and (
                self._parent._options_inquiry_handler.is_show_more_request(user_input) or is_affirmative(user_input)
            ):
                return self._parent._options_inquiry_handler.handle_options_inquiry(item, order, attr, options, is_show_more=True)

            # Check if user is asking about available options
            # Pass the attribute display name as topic for context-aware detection
            # e.g., "what bread do you have" when asking about bread
            topic = attr.get("display_name", "")
            if self._parent._options_inquiry_handler.is_options_inquiry(user_input, topic=topic):
                return self._parent._options_inquiry_handler.handle_options_inquiry(item, order, attr, options, is_show_more=False)

        # Check if user is asking about a DIFFERENT attribute's options
        # e.g., "what toppings do you have?" while being asked about condiments
        different_attr = self._parent._options_inquiry_handler.detect_different_attribute_inquiry(user_input, item_type, attr_slug)
        if different_attr:
            diff_options = different_attr.get("options", [])
            if diff_options:
                # Switch to showing the different attribute's options
                order.pending_field = f"{item_type}:{different_attr['slug']}"
                return self._parent._options_inquiry_handler.handle_options_inquiry(item, order, different_attr, diff_options, is_show_more=False)

        # Reset options page when user provides an actual answer
        order.config_options_page = 0

        # Dispatch by input_type for non-select types
        input_type_handlers = {
            "boolean": self._handle_boolean_input,
            "quantity": self._handle_quantity_input,
            "package_multi_select": self._handle_package_input,
        }

        handler = input_type_handlers.get(input_type)
        if handler:
            if input_type == "quantity":
                return handler(user_input, item, order, attr, options)
            return handler(user_input, item, order, attr)

        # single_select / multi_select need forward delegation check first
        if input_type in ("single_select", "multi_select"):
            forward_result = self._check_forward_delegation(
                user_input, item, order, attr, options, attrs
            )
            if forward_result:
                return forward_result
            return self._handle_select_input(user_input, item, order, attr, options)

        # Default: store raw input
        item[attr_slug] = user_input.strip()
        return self._parent._question_flow._advance_to_next_question(item, order, attr)

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

                if self._parent._package_input_handler.looks_like_package_contents(
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
        result = self._parent._boolean_parser.parse(user_input, attr)

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
        self._parent._selection_extractor.extract_and_apply_selections(user_input, item)

        # Capture any additional attributes mentioned in the input
        # e.g., "yes toasted scooped with cream cheese" captures toasted, scooped, and spread
        # Skip the current attribute to prevent double-interpretation
        self._parent.capture_attributes_from_input(user_input, item, skip_attribute=attr_slug)

        return self._parent._question_flow._advance_to_next_question(item, order, attr)

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
        return self._parent._quantity_input_handler.handle_quantity_input(
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

        return self._parent._package_input_handler.handle_package_input(
            user_input=user_input,
            item=item,
            order=order,
            attr=attr,
            options=package_options,
            advance_callback=self._parent._question_flow._advance_to_next_question,
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
            capture_input = user_input
            if ack_text:
                # Check if user input is essentially just the matched option
                # e.g., "onion" matches "Onion Bagel" -> simple answer, skip capture
                # e.g., "plain toasted with cream cheese" does NOT match "Plain Bagel" -> capture
                user_lower = normalize_text(user_input)
                ack_lower = normalize_text(ack_text)
                # User input is a simple answer if it's contained in the matched option
                # or if it exactly matches (allowing for minor variations)
                if user_lower in ack_lower or ack_lower.startswith(user_lower):
                    should_capture = False
                elif ack_lower in user_lower:
                    # User input contains the matched option plus extra words
                    # e.g., "do you have onion bagel?" contains "onion bagel"
                    # Strip the matched text so it won't double-match other attributes
                    # e.g., "onion" won't also match as a topping
                    capture_input = user_lower.replace(ack_lower, "", 1).strip()

            if should_capture:
                self._parent.capture_attributes_from_input(capture_input, item, skip_attribute=attr['slug'])
            return self._parent._question_flow._advance_to_next_question(item, order, attr, ack_text)

        return self._parent._select_input_handler.handle_select_input(
            user_input=user_input,
            item=item,
            order=order,
            attr=attr,
            options=options,
            advance_callback=advance_with_capture,
        )

    def _match_attribute_from_input(
        self, user_input: str, attributes: list[dict]
    ) -> list[dict]:
        """
        Try to match user input to one or more attributes.

        Used when user says "add egg and spread" to match multiple.
        Supports partial matching: "cheese" matches "Extra Cheese", "egg" matches "Add Egg".
        """
        user_lower = normalize_text(user_input)
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
            if self._parent._option_matcher._is_whole_word_match(user_lower, display_lower):
                matched.append(attr)
                continue
            if self._parent._option_matcher._is_whole_word_match(user_lower, slug_readable):
                matched.append(attr)
                continue

        return matched

    def _extract_qualifier_for_option(
        self, user_input: str, option_name: str,
        other_option_positions: list[tuple[int, int]] | None = None,
    ) -> str | None:
        """
        Extract qualifier (extra, light, lots of, on the side, etc.) for a specific option.

        Delegates to QualifierExtractor.
        """
        return self._parent._qualifier_extractor.extract_qualifier_for_option(
            user_input, option_name, other_option_positions
        )
