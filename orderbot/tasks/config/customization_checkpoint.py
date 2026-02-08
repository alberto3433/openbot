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
from ..parsers.quantity_utils import (
    extract_leading_quantity,
    extract_additive_quantity,
    QUANTITY_MODIFIER_WORDS,
)
from .attribute_resolver import get_mandatory_attributes

if TYPE_CHECKING:
    from ..models import OrderTask, MenuItemTask
    from .options_inquiry import OptionsInquiryHandler
    from .context import ConfigHandlerContext
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
        ctx: "ConfigHandlerContext | None" = None,
        # Legacy parameters for backward compatibility (deprecated)
        option_matcher: "OptionMatcher | None" = None,
        recalculate_item_price: Callable[["MenuItemTask"], None] | None = None,
        get_unanswered_optional: Callable[["MenuItemTask", str], list[dict]] | None = None,
        get_optional_attributes: Callable[[str], list[dict]] | None = None,
        format_display_list: Callable[[list[dict]], str] | None = None,
        match_attribute_from_input: Callable[[str, list[dict]], list[dict]] | None = None,
        extract_quantity_from_input: Callable[[str], tuple[int, str]] | None = None,
        ask_disambiguation_for_options: Callable[
            ["MenuItemTask", "OrderTask", dict, dict, str], StateMachineResult
        ] | None = None,
        ask_customization_checkpoint: Callable[
            ["MenuItemTask", "OrderTask", str | None], StateMachineResult
        ] | None = None,
        ask_optional_attribute: Callable[
            ["MenuItemTask", "OrderTask", dict], StateMachineResult
        ] | None = None,
        try_direct_option_match: Callable[
            [str, list[dict], "MenuItemTask", "OrderTask"], StateMachineResult | None
        ] | None = None,
        get_next_question: Callable[["OrderTask"], StateMachineResult | None] | None = None,
        process_pending_parsed_items_callback: Callable[
            ["OrderTask"], StateMachineResult | None
        ] | None = None,
    ) -> None:
        """Initialize the customization checkpoint handler.

        Args:
            options_inquiry_handler: Handler for options inquiry questions.
            ctx: ConfigHandlerContext with shared dependencies. If provided,
                 individual callback parameters are ignored.

        Deprecated args (use ctx instead):
            option_matcher, recalculate_item_price, get_unanswered_optional,
            get_optional_attributes, format_display_list, match_attribute_from_input,
            extract_quantity_from_input, ask_disambiguation_for_options,
            ask_customization_checkpoint, ask_optional_attribute, try_direct_option_match,
            get_next_question, process_pending_parsed_items_callback
        """
        self._options_inquiry_handler = options_inquiry_handler

        # Use context if provided, otherwise fall back to individual parameters
        if ctx is not None:
            self._option_matcher = ctx.option_matcher
            self._recalculate_item_price = ctx.recalculate_item_price
            self._get_unanswered_optional = ctx.get_unanswered_optional
            self._get_optional_attributes = ctx.get_optional_attributes
            self._format_display_list = ctx.format_display_list
            self._match_attribute_from_input = ctx.match_attribute_from_input
            self._extract_quantity_from_input = ctx.extract_quantity_from_input
            self._ask_disambiguation_for_options = ctx.ask_disambiguation_for_options
            self._ask_customization_checkpoint = ctx.ask_customization_checkpoint
            self._ask_optional_attribute = ctx.ask_optional_attribute
            self._try_direct_option_match = ctx.try_direct_option_match
            self._get_next_question = ctx.get_next_question
            self._process_pending_parsed_items_callback = ctx.process_pending_parsed_items
        else:
            # Legacy: individual parameters
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
        # Strip "make it" prefix - users often say "make it 3 eggs" to customize
        user_lower = user_input.lower().strip()
        if user_lower.startswith("make it "):
            user_input = user_input[8:]  # len("make it ") == 8
            user_lower = user_lower[8:]
        # Also strip leading articles (a/an) - "make it an onion bagel" → "onion bagel"
        if user_lower.startswith("an "):
            user_input = user_input[3:]
            user_lower = user_lower[3:]
        elif user_lower.startswith("a "):
            user_input = user_input[2:]
            user_lower = user_lower[2:]
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

        # Try to match option values directly FIRST (e.g., "blueberry cream cheese" -> spread option)
        # This allows users to specify options without naming the attribute.
        # Use ALL optional attributes, not just unanswered - user may want to add to
        # an attribute they previously declined (e.g., said "no" to shots, now says "extra shot")
        #
        # IMPORTANT: Direct option matching MUST happen BEFORE attribute name matching!
        # Otherwise "blueberry cream cheese" matches "cheese" (attribute category) as a substring
        # and asks "What kind of cheese?" instead of setting the spread.
        result = self._try_direct_option_match(user_input, all_optional, item, order)
        if result:
            return result

        # If no optional match, try mandatory attributes for "make it X" style changes
        # e.g., "make it an onion bagel" to change bread type
        all_mandatory = get_mandatory_attributes(item_type)
        result = self._try_direct_option_match(user_input, all_mandatory, item, order)
        if result:
            return result

        # Try to match specific attribute(s) from input (e.g., "cheese" -> ask "What kind of cheese?")
        # This comes AFTER direct option matching to avoid substring matches on attribute names
        matched_attrs = self._match_attribute_from_input(user_input, unanswered)

        if matched_attrs:
            return self._handle_matched_attribute(
                user_input, user_lower, item, order, item_type, matched_attrs[0]
            )

        # Fallback: Try matching space-separated words against ingredients
        # This handles input like "salt pepper ketchup" by splitting on spaces
        result = self._try_ingredient_fallback(user_input, item, order)
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

    def _try_ingredient_fallback(
        self, user_input: str, item: "MenuItemTask", order: "OrderTask"
    ) -> StateMachineResult | None:
        """Try matching space-separated words against ingredients as fallback.

        This handles input like "salt pepper ketchup" by splitting on spaces
        and matching each word individually against the ingredients table.
        Also handles quantity modifier patterns like "more bacon", "extra cheese".
        Only called after attribute/option matching has failed.

        Args:
            user_input: User's input text
            item: Menu item being configured
            order: Current order

        Returns:
            StateMachineResult if any ingredients matched, None otherwise
        """
        from ..utils.text import format_english_list

        user_clean = user_input.lower().strip()

        # Only try splitting if there are multiple words
        words = user_clean.split()
        if len(words) <= 1:
            return None  # Single word already tried via other matching

        added_names: list[str] = []
        unmatched: list[str] = []
        matched_slugs: set[str] = set()  # Track already matched ingredients

        # Phase 1: Try to match full phrases with quantity modifiers
        # Handles "more bacon", "extra cheese", "double egg", etc.
        for match in menu_cache.find_matching_ingredients(user_clean):
            pattern = match["name"].lower()
            if pattern not in user_clean:
                continue

            quantity, is_additive = extract_additive_quantity(user_clean, pattern)
            slug = match["slug"]

            # Also check for "extra X" which should be additive
            # extract_additive_quantity treats "extra" as absolute (qty=2),
            # but we want it to be additive when ingredient already exists
            is_extra_prefix = user_clean.startswith(f"extra {pattern}")

            existing = item.find_modifier_by_slug(slug)

            if is_additive or (is_extra_prefix and existing):
                # Additive pattern: increment existing quantity or add new
                if existing:
                    existing["quantity"] = existing.get("quantity", 1) + quantity
                    display_qty = existing["quantity"]
                    display_name = f"{match['name']} x{display_qty}"
                    added_names.append(display_name)
                    logger.info(
                        "QUANTITY_MODIFIER: Incremented '%s' by %d to qty=%d",
                        slug, quantity, display_qty
                    )
                else:
                    # Additive but doesn't exist yet - add normally
                    item.add_selection(
                        slug=slug,
                        category=match["category"],
                        display_name=match["name"],
                        quantity=quantity,
                        price=match.get("base_price", 0.0),
                    )
                    added_names.append(match["name"])
                    logger.info(
                        "QUANTITY_MODIFIER: Added new '%s' with qty=%d (additive pattern)",
                        slug, quantity
                    )
            else:
                # Absolute pattern (e.g., "double bacon" = 2)
                if existing:
                    # Update existing quantity to absolute value
                    existing["quantity"] = quantity
                    display_name = f"{match['name']} x{quantity}" if quantity > 1 else match["name"]
                    added_names.append(display_name)
                else:
                    item.add_selection(
                        slug=slug,
                        category=match["category"],
                        display_name=match["name"],
                        quantity=quantity,
                        price=match.get("base_price", 0.0),
                    )
                    display_name = f"{quantity} {match['name']}" if quantity > 1 else match["name"]
                    added_names.append(display_name)
                logger.info(
                    "QUANTITY_MODIFIER: Set '%s' to qty=%d (absolute)",
                    slug, quantity
                )

            matched_slugs.add(slug)

        # If we matched via quantity modifier patterns, we're done
        if matched_slugs:
            self._recalculate_item_price(item)
            added_text = format_english_list(added_names)
            return self._ask_customization_checkpoint(item, order, f"{added_text} added")

        # Phase 1b: Check if term matches an attribute category
        # Handles "more cheese" when user has already selected provolone (cheese is attribute category)
        item_type_attrs = menu_cache.get_item_type_attributes(item.menu_item_type)

        for word in words:
            if word in QUANTITY_MODIFIER_WORDS:
                continue

            # Check if word matches an attribute category slug
            if word in item_type_attrs:
                existing = item.get_selection(word)  # e.g., get_selection("cheese")
                attr_config = item_type_attrs[word]

                if existing:
                    # Case A: Attribute already has a selection - modify quantity
                    quantity, is_additive = extract_additive_quantity(user_clean, word)
                    is_extra = user_clean.startswith(f"extra {word}")

                    if is_additive:
                        # "more cheese" - add the extracted quantity
                        existing["quantity"] = existing.get("quantity", 1) + quantity
                    elif is_extra:
                        # "extra cheese" - add 1 more
                        existing["quantity"] = existing.get("quantity", 1) + 1
                    else:
                        # "double cheese", "triple cheese" - set absolute quantity
                        existing["quantity"] = quantity

                    display_name = existing.get("display_name", word.title())
                    display_qty = existing["quantity"]
                    added_names.append(f"{display_name} x{display_qty}")
                    matched_slugs.add(word)
                    logger.info("ATTRIBUTE_QUANTITY: Set '%s' to qty=%d", word, display_qty)

                else:
                    # Case B: No existing selection - check options count
                    options = attr_config.get("options", [])
                    if len(options) == 1:
                        # Single option: add it directly
                        opt = options[0]
                        quantity, _ = extract_additive_quantity(user_clean, word)
                        opt_price = opt.get("price") or opt.get("price_modifier") or 0
                        item.add_selection(
                            slug=opt["slug"],
                            category=word,
                            quantity=quantity,
                            display_name=opt.get("display_name", opt["slug"]),
                            price=opt_price,
                        )
                        display_name = opt.get("display_name", opt["slug"])
                        added_names.append(display_name)
                        matched_slugs.add(word)
                        logger.info(
                            "ATTRIBUTE_SINGLE_OPTION: Added '%s' for category '%s'",
                            opt["slug"], word
                        )
                    elif len(options) > 1:
                        # Multiple options: ask which one
                        order.pending_field = f"{item.menu_item_type}:{word}"
                        question = attr_config.get("question_text", f"What kind of {word}?")
                        return StateMachineResult(message=question, order=order)

        # If we matched via attribute category patterns, we're done
        if matched_slugs:
            self._recalculate_item_price(item)
            added_text = format_english_list(added_names)
            return self._ask_customization_checkpoint(item, order, f"{added_text} added")

        # Phase 2: Word-by-word matching for multi-ingredient input
        # Handles "salt pepper ketchup"
        for word in words:
            # Skip quantity modifier words - don't report them as "not found"
            if word in QUANTITY_MODIFIER_WORDS:
                continue

            quantity, search_term = extract_leading_quantity(word)
            quantity = quantity or 1
            if not search_term:
                search_term = word

            matches = menu_cache.find_matching_ingredients(search_term)

            if len(matches) == 1:
                match = matches[0]
                item.add_selection(
                    slug=match["slug"],
                    category=match["category"],
                    display_name=match["name"],
                    quantity=quantity,
                    price=match.get("base_price", 0.0),
                )
                added_names.append(match["name"])
                logger.info(
                    "INGREDIENT_FALLBACK: Added '%s' (category=%s) from word '%s'",
                    match["name"], match["category"], word
                )
            elif len(matches) > 1:
                # Multiple matches - ambiguous, skip for now
                logger.debug(
                    "INGREDIENT_FALLBACK: Multiple matches for '%s', skipping", word
                )
                unmatched.append(word)
            else:
                # No match
                unmatched.append(word)

        if not added_names:
            return None  # No matches at all, let caller show "Sorry" message

        # Recalculate price
        self._recalculate_item_price(item)

        # Build message
        added_text = format_english_list(added_names)

        if unmatched:
            unmatched_text = format_english_list(unmatched)
            msg = f"{added_text} added. Couldn't find: {unmatched_text}."
        else:
            msg = f"{added_text} added."

        return self._ask_customization_checkpoint(item, order, msg)

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
