"""
Customization Checkpoint Handler for Menu Item Configuration.

Handles user responses to customization checkpoint during item configuration,
such as adding optional modifiers or completing the item.

Extracted from menu_item_config_handler.py for better separation of concerns.
"""

import logging
import re
from typing import TYPE_CHECKING

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
from .config_input_dispatch import _filter_options_by_category
from .flows import IngredientFallbackHandler
from ..shared_constants import ORDERING_PREFIX_RE, LEADING_ARTICLE_RE
from ..parsers.intent_patterns import ORDERING_LANGUAGE_PATTERN
from ..utils.text import normalize_text

if TYPE_CHECKING:
    from ..models import OrderTask, MenuItemTask
    from .options_inquiry import OptionsInquiryHandler
    from .context import ConfigHandlerContext

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
        ctx: "ConfigHandlerContext",
    ) -> None:
        """Initialize the customization checkpoint handler.

        Args:
            options_inquiry_handler: Handler for options inquiry questions.
            ctx: ConfigHandlerContext with shared dependencies.
        """
        self._options_inquiry_handler = options_inquiry_handler
        self._ctx = ctx

        # Initialize the ingredient fallback handler
        self._ingredient_fallback_handler = IngredientFallbackHandler(
            recalculate_item_price=ctx.recalculate_item_price,
            ask_customization_checkpoint=ctx.ask_customization_checkpoint,
        )

    def _handle_more_existing_selection(
        self, user_input: str, item: "MenuItemTask", order: "OrderTask"
    ) -> StateMachineResult | None:
        """Handle 'more X' / 'extra X' when X is already on the item.

        When user says 'more cheese' and provolone is already selected as the cheese
        attribute, increment the provolone quantity rather than matching against
        spread options (which would incorrectly match "cream cheese").

        Args:
            user_input: User's input text
            item: Menu item being configured
            order: Current order

        Returns:
            StateMachineResult if handled, None to continue normal flow
        """
        user_lower = normalize_text(user_input)

        # Check for "more X" or "extra X" patterns
        remainder = None
        for prefix in ("more ", "extra "):
            if user_lower.startswith(prefix):
                remainder = user_lower[len(prefix):].strip()
                break

        if not remainder:
            return None

        # Check if remainder matches an attribute category that has a selection
        item_type_attrs = menu_cache.get_item_type_attributes(item.menu_item_type)

        if remainder not in item_type_attrs:
            return None

        # Check if this attribute already has a selection
        existing_sel = item.get_selection(remainder)
        if not existing_sel:
            return None

        # Found! Increment the quantity
        existing_sel["quantity"] = existing_sel.get("quantity", 1) + 1
        new_qty = existing_sel["quantity"]

        display_name = existing_sel.get("display_name", remainder.replace("_", " ").title())

        # Recalculate price
        self._ctx.recalculate_item_price(item)

        display_text = f"{display_name} x{new_qty}"
        return self._ctx.ask_customization_checkpoint(item, order, display_text)

    def _check_new_item_at_checkpoint(
        self, user_lower: str, item: "MenuItemTask", order: "OrderTask"
    ) -> StateMachineResult | None:
        """Detect if user is ordering a new item at the customization checkpoint.

        Checks if the input contains an item type trigger word (e.g., "bagel",
        "latte", "coffee") that isn't also a known modifier/ingredient. At the
        checkpoint, modifier words take precedence over item type triggers.

        Args:
            user_lower: Lowercased user input
            item: Menu item being configured
            order: Current order

        Returns:
            StateMachineResult with redirect message if new item detected,
            None to continue normal checkpoint flow.
        """
        all_triggers = menu_cache.get_item_type_triggers()
        current_attrs = set(menu_cache.get_item_type_attributes(item.menu_item_type).keys())

        for triggers in all_triggers.values():
            for trigger in triggers:
                # Skip quantity/multiplier words that happen to be triggers
                # (e.g., "double" from "Double Chocolate Muffin")
                if trigger in QUANTITY_MODIFIER_WORDS:
                    continue
                if not re.search(rf'\b{re.escape(trigger)}\b', user_lower):
                    continue
                # Skip if trigger is also a known modifier/ingredient —
                # at checkpoint, "pepper" means the condiment, not "Pepper Jack Cheese Sandwich"
                if menu_cache.is_known_modifier(trigger):
                    continue
                # Skip if trigger matches an attribute slug of the current item
                # (e.g., "cheese" trigger at egg sandwich checkpoint = cheese attribute)
                if trigger in current_attrs:
                    continue
                item_name = item.get_display_name()
                return StateMachineResult(
                    message=f"Let's finish configuring the {item_name} first. Any more changes?",
                    order=order,
                )
        return None

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
        # Strip ordering prefixes ("add", "make it", "I'd like", "can I get", etc.)
        user_lower = normalize_text(user_input)
        prefix_match = ORDERING_PREFIX_RE.match(user_lower)
        if prefix_match:
            prefix_len = prefix_match.end()
            user_input = user_input[prefix_len:]
            user_lower = user_lower[prefix_len:]
        # Also strip leading articles (a/an/the)
        article_match = LEADING_ARTICLE_RE.match(user_lower)
        if article_match:
            art_len = article_match.end()
            user_input = user_input[art_len:]
            user_lower = user_lower[art_len:]
        item_type = item.menu_item_type

        # Check for "more X" / "extra X" patterns FIRST - before direct option matching
        # This handles "more cheese" when provolone is already selected as the cheese
        # attribute, preventing "cheese" from matching "cream cheese" in spread options
        more_result = self._handle_more_existing_selection(user_input, item, order)
        if more_result:
            return more_result

        # Check for "no" or "done" - user doesn't want to customize further
        no_patterns = menu_cache.get_response_patterns("negative")
        is_declining = (
            any(user_lower == p or user_lower.startswith(p) for p in no_patterns)
            or menu_cache.is_done(user_lower)
        )
        if is_declining:
            # Check for compound response like "no but can I get two large coffees"
            ordering_remainder = self._extract_ordering_remainder(user_input)
            if ordering_remainder:
                from ..parsers import parse_open_input_deterministic
                parsed = parse_open_input_deterministic(ordering_remainder)
                if parsed and parsed.parsed_items:
                    if not order.pending_parsed_items:
                        order.pending_parsed_items = []
                    for pi in parsed.parsed_items:
                        order.pending_parsed_items.append(
                            pi.model_dump() if hasattr(pi, 'model_dump') else pi.__dict__
                        )
                    logger.info(
                        "Extracted %d items from compound decline: '%s'",
                        len(parsed.parsed_items), ordering_remainder,
                    )
            return self._handle_declining(item, order)

        unanswered = self._ctx.get_unanswered_optional(item, item_type)

        # Get all optional attributes for direct option matching
        all_optional = self._ctx.get_optional_attributes(item_type)

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
                cat = self._options_inquiry_handler.extract_inquiry_category(user_input, options)
                order.config_options_category_filter = cat
                filtered = _filter_options_by_category(options, cat)
                return self._options_inquiry_handler.handle_options_inquiry(
                    item, order, inquiry_attr, filtered, is_show_more=False
                )

        # Check for "yes" - user wants to see the list
        yes_patterns = menu_cache.get_response_patterns("affirmative")
        if any(user_lower == p or user_lower.startswith(p + " ") for p in yes_patterns):
            # If just "yes", list the options
            if user_lower in yes_patterns:
                options_list = self._ctx.format_display_list(unanswered)
                order.pending_field = PendingField.CUSTOMIZATION_SELECTION
                # Build quick replies for inline clickable text
                qr = [{"label": a["display_name"], "value": a["display_name"]} for a in unanswered]
                return StateMachineResult(
                    message=f"You can add: {options_list}. What would you like?",
                    order=order,
                    quick_replies=qr,
                )

        # Check if user is ordering a NEW item (e.g., "onion bagel toasted and scooped")
        # This must happen BEFORE direct option matching, which would greedily match
        # words like "onion" as toppings on the current item.
        # We check item type triggers but skip triggers that are also known modifiers/
        # ingredients — at the checkpoint, modifier words take precedence over item
        # type triggers (e.g., "pepper" is a condiment, not a reference to
        # "Pepper Jack Cheese Sandwich").
        new_item_result = self._check_new_item_at_checkpoint(user_lower, item, order)
        if new_item_result:
            return new_item_result

        # Try to match option values directly FIRST (e.g., "blueberry cream cheese" -> spread option)
        # This allows users to specify options without naming the attribute.
        # Use ALL optional attributes, not just unanswered - user may want to add to
        # an attribute they previously declined (e.g., said "no" to shots, now says "extra shot")
        #
        # IMPORTANT: Direct option matching MUST happen BEFORE attribute name matching!
        # Otherwise "blueberry cream cheese" matches "cheese" (attribute category) as a substring
        # and asks "What kind of cheese?" instead of setting the spread.
        result = self._ctx.try_direct_option_match(user_input, all_optional, item, order)
        if result:
            return result

        # If no optional match, try mandatory attributes for "make it X" style changes
        # e.g., "make it an onion bagel" to change bread type
        all_mandatory = get_mandatory_attributes(item_type)
        result = self._ctx.try_direct_option_match(user_input, all_mandatory, item, order)
        if result:
            return result

        # Try to match specific attribute(s) from input (e.g., "cheese" -> ask "What kind of cheese?")
        # This comes AFTER direct option matching to avoid substring matches on attribute names
        matched_attrs = self._ctx.match_attribute_from_input(user_input, unanswered)

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
        options_list = self._ctx.format_display_list(unanswered)
        # Build quick replies for inline clickable text
        qr = [{"label": a["display_name"], "value": a["display_name"]} for a in unanswered]
        return StateMachineResult(
            message=f"Sorry, we don't have {user_input}. You can add: {options_list}. What would you like?",
            order=order,
            quick_replies=qr,
        )

    def _extract_ordering_remainder(self, user_input: str) -> str | None:
        """Extract ordering remainder from compound responses.

        Detects inputs like "no but can I get two large coffees" and returns
        the ordering portion ("can I get two large coffees") after stripping
        the negative prefix and connectors.

        Args:
            user_input: Raw user input text.

        Returns:
            The ordering portion if detected, None otherwise.
        """
        user_lower = normalize_text(user_input)

        # Must start with a negative pattern
        no_patterns = menu_cache.get_response_patterns("negative")
        matched_prefix = None
        for p in no_patterns:
            if user_lower == p:
                return None  # Pure negative, no remainder
            if user_lower.startswith(p + " ") or user_lower.startswith(p + ","):
                matched_prefix = p
                break

        if not matched_prefix:
            return None

        # Strip the negative prefix
        remainder = user_input[len(matched_prefix):].lstrip(" ,.")

        if not remainder:
            return None

        # Strip connectors: "but", "and", "also"
        remainder_lower = normalize_text(remainder)
        for connector in ("but ", "and ", "also "):
            if remainder_lower.startswith(connector):
                remainder = remainder[len(connector):].lstrip()
                break

        if not remainder:
            return None

        # Only return if remainder contains ordering language
        if ORDERING_LANGUAGE_PATTERN.search(remainder):
            return remainder

        return None

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
        self._ctx.recalculate_item_price(item)
        item.mark_complete()
        order.clear_pending()

        # Track item count before processing pending items so we can
        # acknowledge newly-added items (e.g., "no can I also have a coke?")
        items_before = len(order.items.items)

        # Check if there are pending parsed items that haven't been added yet
        # This handles the case where disambiguation was triggered and remaining items
        # in the order were stored (e.g., "bagel and latte" - latte is stored while
        # we disambiguate and configure bagel)
        if self._ctx.process_pending_parsed_items:
            pending_result = self._ctx.process_pending_parsed_items(order)
            if pending_result:
                return pending_result

        # Check if there are more items to configure (e.g., coffee added with bagel)
        if self._ctx.get_next_question:
            next_result = self._ctx.get_next_question(order)
            # If there's another item to configure, return that
            if next_result and next_result.order.pending_field:
                return next_result

        # No more items to configure - go back to taking items
        order.set_phase(OrderPhase.TAKING_ITEMS)

        # Build summary including any items added from compound input
        new_items = order.items.items[items_before:]
        added_names = [ni.get_display_name() for ni in new_items]
        summary = item.get_summary()
        if added_names:
            summary += ", and " + ", ".join(added_names)

        return StateMachineResult(
            message=got_it_anything_else(summary),
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
                cat = self._options_inquiry_handler.extract_inquiry_category(user_input, options)
                order.config_options_category_filter = cat
                filtered = _filter_options_by_category(options, cat)
                return self._options_inquiry_handler.handle_options_inquiry(
                    item, order, attr, filtered, is_show_more=False
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
        quantity, remaining_text = self._ctx.extract_quantity_from_input(user_input)

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
        return self._ctx.ask_optional_attribute(item, order, attr)

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
        self._ctx.recalculate_item_price(item)
        remaining = self._ctx.get_unanswered_optional(item, item_type)
        if remaining:
            return self._ctx.ask_customization_checkpoint(item, order, None)

        # No more optional attributes - complete the item
        item.mark_complete()
        order.clear_pending()
        if self._ctx.get_next_question:
            next_result = self._ctx.get_next_question(order)
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
        user_clean = normalize_text(remaining_text)
        if user_clean.startswith("add "):
            user_clean = user_clean[4:].strip()

        if input_type == "multi_select":
            # Use disambiguation-aware matching for multi-select
            matched_opts, disambiguation = self._ctx.option_matcher.match_multiple_with_disambiguation(
                user_clean, options
            )

            if disambiguation:
                # Single ambiguous term matches multiple options - ask user to clarify
                return self._ctx.ask_disambiguation_for_options(
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
                return self._ctx.ask_customization_checkpoint(item, order, f"{display_text} added")
        else:
            # single_select
            matched_opt, _ = self._ctx.option_matcher.match_single(user_clean, options)
            if matched_opt:
                opt_name = matched_opt["display_name"]
                opt_price = matched_opt.get("price") or matched_opt.get("price_modifier") or 0
                item.add_selection(
                    matched_opt["slug"], attr_slug,
                    quantity=quantity, price=opt_price,
                    display_name=opt_name,
                )
                display = f"{quantity} {opt_name}" if quantity > 1 else opt_name
                return self._ctx.ask_customization_checkpoint(item, order, f"{display} added")

        return None

    def _try_ingredient_fallback(
        self, user_input: str, item: "MenuItemTask", order: "OrderTask"
    ) -> StateMachineResult | None:
        """Try matching space-separated words against ingredients as fallback.

        Delegates to IngredientFallbackHandler for the actual matching logic.

        Args:
            user_input: User's input text
            item: Menu item being configured
            order: Current order

        Returns:
            StateMachineResult if any ingredients matched, None otherwise
        """
        return self._ingredient_fallback_handler.try_match(user_input, item, order)

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
