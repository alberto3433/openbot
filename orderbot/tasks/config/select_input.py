"""
Select Input Handler.

This module handles single/multi select input processing including:
- Single-select attribute matching
- Multi-select attribute matching with quantity extraction
- Disambiguation for ambiguous matches
- Partial match handling
- Numeric option matching

Extracted from menu_item_config_handler.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache

from ..models import OrderTask, MenuItemTask
from ..selection_utils import (
    extract_meaningful_words,
    find_partial_matches,
    find_numeric_options,
)
from ..schemas import StateMachineResult, OrderPhase
from ..parsers.constants import extract_quantity_for_pattern, DEFAULT_PAGINATION_SIZE
from ..parsers.quantity_utils import parse_numeric_input
from ..utils.text import format_english_list
from ..utils import OptionMatcher
from ..response_utils import is_affirmative

if TYPE_CHECKING:
    from ..pricing import PricingEngine
    from ..utils import InputNormalizer

logger = logging.getLogger(__name__)


class SelectInputHandler:
    """
    Handles single/multi select input processing.

    Manages option matching, disambiguation, and selection application
    for attribute questions with select-type inputs.
    """

    def __init__(
        self,
        pricing: "PricingEngine | None",
        option_matcher: "OptionMatcher",
        input_normalizer: "InputNormalizer",
    ):
        """
        Initialize the select input handler.

        Args:
            pricing: PricingEngine for price lookups.
            option_matcher: OptionMatcher for matching user input to options.
            input_normalizer: InputNormalizer for extracting quantities.
        """
        self.pricing = pricing
        self._option_matcher = option_matcher
        self._input_normalizer = input_normalizer

    def handle_select_input(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        options: list[dict],
        advance_callback,
        format_display_list_callback,
        extract_selections_callback,
        extract_qualifier_callback,
    ) -> StateMachineResult:
        """Handle single/multi select input.

        Args:
            user_input: User's input string
            item: The MenuItemTask being configured
            order: Current order state
            attr: Attribute configuration dict
            options: List of available options
            advance_callback: Callback to advance to next question
            format_display_list_callback: Callback to format options list
            extract_selections_callback: Callback to extract selections from input
            extract_qualifier_callback: Callback to extract qualifiers

        Returns:
            StateMachineResult with response or next question
        """
        attr_slug = attr["slug"]
        user_lower = user_input.lower().strip()
        input_type = attr.get("input_type", "single_select")

        # Extract quantity from input (e.g., "2 scrambled eggs" -> quantity=2)
        # Also check pending_modifier_quantity which was stored when asking the question
        quantity, _ = self._input_normalizer.extract_leading_quantity(user_input)
        if quantity == 1 and order.pending_modifier_quantity:
            quantity = order.pending_modifier_quantity
        # Clear pending quantity after extracting it
        order.pending_modifier_quantity = None

        # Filter to only available options for matching
        # Keep unavailable options separate for "we don't have X" messaging
        available_options = [opt for opt in options if opt.get("is_available", True)]
        unavailable_options = [opt for opt in options if not opt.get("is_available", True)]

        # Check for "none" / "no" / "skip"
        # Accept negative responses for non-required attributes or when allow_none=True
        can_skip = not attr.get("is_required", True) or attr.get("allow_none", False)
        if can_skip:
            skip_patterns = menu_cache.get_response_patterns("negative")
            if any(user_lower == p or user_lower.startswith(p + " ") for p in skip_patterns):
                item[attr_slug] = None
                return advance_callback(item, order, attr)

        # Check if user input matches an unavailable option FIRST
        # e.g., "medium" when only small/large are available
        # Use exact_only=True to avoid partial matches (e.g., "large" matching "Extra Large")
        if unavailable_options:
            unavail_match, _ = self._option_matcher.match_single(
                user_input, unavailable_options, exact_only=True
            )
            if unavail_match:
                # User asked for something we don't have
                unavail_name = unavail_match.get("display_name", user_input)
                if available_options:
                    names = [opt["display_name"] for opt in available_options]
                    from ..utils.text import format_english_list
                    options_str = format_english_list(names, conjunction="or")
                    return StateMachineResult(
                        message=f"Sorry, we don't have {unavail_name}. We have {options_str}.",
                        order=order,
                    )
                else:
                    return StateMachineResult(
                        message=f"Sorry, we don't have {unavail_name}.",
                        order=order,
                    )

        # For multi_select, try to match ALL options in the input
        if input_type == "multi_select":
            return self._handle_multi_select(
                user_input, user_lower, item, order, attr, attr_slug, available_options,
                quantity, advance_callback, format_display_list_callback,
                extract_qualifier_callback,
            )

        # For single_select (or if multi_select found nothing), use single-match logic
        return self._handle_single_select(
            user_input, user_lower, item, order, attr, attr_slug, available_options,
            quantity, input_type, advance_callback, format_display_list_callback,
            extract_selections_callback, extract_qualifier_callback,
        )

    def _handle_multi_select(
        self,
        user_input: str,
        user_lower: str,
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        attr_slug: str,
        options: list[dict],
        quantity: int,
        advance_callback,
        format_display_list_callback,
        extract_qualifier_callback,
    ) -> StateMachineResult:
        """Handle multi_select input type."""
        match_result = self._option_matcher.match_multiple_with_unmatched(user_input, options)
        matched_options = match_result.matched
        unmatched_tokens = match_result.unmatched
        logger.info(
            "MULTI_SELECT MATCH for %s: input='%s', found %d matches: %s, unmatched: %s",
            attr_slug, user_input, len(matched_options),
            [o["slug"] for o in matched_options], unmatched_tokens
        )

        # DISAMBIGUATION: Check if any single token matched multiple options
        # This handles cases like "oat milk and 2 syrups" where "syrups" matches all syrup options
        tokens = self._input_normalizer.tokenize_multi_input(user_input)

        if len(matched_options) > 1:
            # Case 1: Single token input matched multiple options
            is_single_token = len(tokens) <= 1
            if is_single_token:
                logger.info(
                    "MULTI_SELECT DISAMBIGUATION: single token '%s' matched %d options: %s",
                    user_input, len(matched_options), [o["display_name"] for o in matched_options]
                )
                # Store disambiguation state and ask user to clarify
                order.pending_attr_disambiguation = {
                    "options": matched_options,
                    "attr_slug": attr_slug,
                    "modifiers": {"_quantity": quantity},
                    "item_id": item.id,
                }
                options_text = format_display_list_callback(matched_options)
                return StateMachineResult(
                    message=f"Did you mean {options_text}?",
                    order=order,
                )

            # Case 2: Multi-token input but ONE token matched multiple options
            # Check each token individually to see if any single token caused multiple matches
            for token in tokens:
                token_matches = self._option_matcher.match_multiple(token, options)
                if len(token_matches) > 1:
                    # This single token matched multiple options - need disambiguation
                    # Extract quantity from token (e.g., "2 syrups" -> 2)
                    token_qty, _ = self._input_normalizer.extract_leading_quantity(token)
                    if token_qty == 1:
                        token_qty = quantity  # Fall back to overall quantity

                    logger.info(
                        "MULTI_SELECT DISAMBIGUATION: token '%s' matched %d options: %s",
                        token, len(token_matches), [o["display_name"] for o in token_matches]
                    )

                    # Apply non-ambiguous matches first (other tokens that matched exactly one option)
                    for other_token in tokens:
                        if other_token == token:
                            continue
                        other_matches = self._option_matcher.match_multiple(other_token, options)
                        if len(other_matches) == 1:
                            opt = other_matches[0]
                            existing_slugs = {sel.get("slug") for sel in item.get_selections(attr_slug)}
                            if opt["slug"] not in existing_slugs:
                                opt_price = OptionMatcher.get_option_price(opt)
                                if opt_price == 0 and self.pricing:
                                    opt_price = self.pricing.lookup_generic_modifier_price(
                                        opt["slug"], item.menu_item_type
                                    ) or 0.0
                                item.add_selection(
                                    opt["slug"],
                                    attr_slug,
                                    quantity=1,
                                    price=opt_price,
                                    display_name=opt["display_name"],
                                    ingredient_category=opt.get("ingredient_category"),
                                )
                                logger.info(
                                    "MULTI_SELECT: added unambiguous match '%s' before disambiguation",
                                    opt["display_name"]
                                )

                    # Store disambiguation state for the ambiguous token
                    order.pending_attr_disambiguation = {
                        "options": token_matches,
                        "attr_slug": attr_slug,
                        "modifiers": {"_quantity": token_qty},
                        "item_id": item.id,
                    }
                    options_text = format_display_list_callback(token_matches)
                    attr_display = attr.get("display_name", attr_slug).lower()
                    return StateMachineResult(
                        message=f"Which {attr_display}? {options_text}",
                        order=order,
                    )

        if matched_options:
            # Get existing selections for this category
            existing_selections = item.get_selections(attr_slug)
            existing_slugs = {sel.get("slug") for sel in existing_selections}

            user_lower = user_input.lower()
            added_selections = []
            for opt in matched_options:
                if opt["slug"] not in existing_slugs:
                    # Extract qualifier (extra, light, on the side, etc.)
                    qualifier = extract_qualifier_callback(user_input, opt["display_name"])

                    # Only extract numeric quantity if category supports it (has quantity_unit)
                    mod_category = opt.get("ingredient_category") or attr_slug
                    quantity_unit = menu_cache.get_ingredient_category_quantity_unit(mod_category)

                    opt_quantity = 1
                    if quantity_unit:
                        # Extract quantity specific to this option
                        opt_quantity = extract_quantity_for_pattern(user_lower, opt["display_name"].lower())
                        if opt_quantity == 1:
                            opt_quantity = extract_quantity_for_pattern(user_lower, opt["slug"].replace("_", " "))
                        if opt_quantity == 1 and opt.get("aliases"):
                            for alias in opt["aliases"]:
                                alias_qty = extract_quantity_for_pattern(user_lower, alias.lower())
                                if alias_qty > 1:
                                    opt_quantity = alias_qty
                                    break

                    opt_price = OptionMatcher.get_option_price(opt)

                    # Look up price from pricing engine if not in option
                    if opt_price == 0 and self.pricing:
                        opt_price = self.pricing.lookup_generic_modifier_price(
                            opt["slug"], item.menu_item_type
                        ) or 0.0

                    # Add selection using unified API
                    item.add_selection(
                        opt["slug"],
                        attr_slug,
                        quantity=opt_quantity,
                        price=opt_price,
                        display_name=opt["display_name"],
                        ingredient_category=opt.get("ingredient_category"),
                    )
                    added_selections.append({
                        "slug": opt["slug"],
                        "display_name": opt["display_name"],
                        "price": opt_price,
                        "quantity": opt_quantity,
                        "qualifier": qualifier,
                    })

                    if opt_price > 0:
                        logger.info(
                            "Updated unit_price for %s: added %s price %.2f (qty=%d), new total %.2f",
                            item.id, opt["slug"], opt_price, opt_quantity, item.unit_price
                        )

            all_selections = existing_selections + added_selections
            all_slugs = [sel.get("slug") for sel in all_selections]
            logger.info(
                "STORED multi_select: %s = %s, selections count: %d",
                attr_slug, all_slugs, len(item.selections)
            )

            # Build acknowledgment text with quantity and qualifier
            display_names = []
            for sel in all_selections:
                name = sel["display_name"]
                qual = sel.get("qualifier")
                qty = sel.get("quantity", 1)
                if qual:
                    name = f"{name} ({qual})"
                if qty > 1:
                    name = f"{qty} {name}"
                display_names.append(name)

            ack_text = format_english_list(display_names)

            # If there are unmatched tokens, stay on current question and show options
            if unmatched_tokens:
                unmatched_text = format_english_list(unmatched_tokens, conjunction="or")

                # Get available options (excluding already selected ones)
                selected_slugs = {sel.get("slug") for sel in all_selections}
                available = [
                    opt for opt in options
                    if opt.get("is_available", True) and opt["slug"] not in selected_slugs
                ]

                if not available:
                    # All options selected, can advance
                    ack_text = f"{ack_text}. Sorry, we don't have {unmatched_text}"
                    return advance_callback(item, order, attr, ack_text)

                # Store pagination state for "yes"/"more" handling
                order.pending_unmatched_pagination = {
                    "unmatched_text": unmatched_text,
                    "attr_slug": attr_slug,
                    "available_options": available,
                    "page": 0,
                    "item_id": item.id,
                }

                # Build options list with pagination
                if len(available) <= DEFAULT_PAGINATION_SIZE:
                    names = [opt["display_name"] for opt in available]
                    options_str = format_english_list(names, conjunction="or")
                    message = (
                        f"Got it, {ack_text}. We don't have {unmatched_text}. "
                        f"We have {options_str}. Would you like any of these?"
                    )
                else:
                    first_page = available[:DEFAULT_PAGINATION_SIZE]
                    names = [opt["display_name"] for opt in first_page]
                    options_str = format_english_list(names, conjunction="and")
                    message = (
                        f"Got it, {ack_text}. We don't have {unmatched_text}. "
                        f"We have {options_str}... and more. Would you like to see more options?"
                    )
                    order.pending_unmatched_pagination["page"] = 1

                return StateMachineResult(message=message, order=order)

            return advance_callback(item, order, attr, ack_text)

        # No matches - fall through to single select handling
        return self._handle_single_select_fallback(
            user_input, user_lower, item, order, attr, attr_slug, options,
            quantity, "multi_select", advance_callback, format_display_list_callback,
            None, extract_qualifier_callback,
        )

    def _handle_single_select(
        self,
        user_input: str,
        user_lower: str,
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        attr_slug: str,
        options: list[dict],
        quantity: int,
        input_type: str,
        advance_callback,
        format_display_list_callback,
        extract_selections_callback,
        extract_qualifier_callback,
    ) -> StateMachineResult:
        """Handle single_select input type."""
        matched, partial_matches = self._option_matcher.match_single(user_input, options)

        if matched:
            return self._apply_single_match(
                user_input, item, order, attr, attr_slug, matched, quantity,
                input_type, advance_callback, extract_qualifier_callback,
            )

        # Multiple partial matches - store disambiguation state and ask
        if partial_matches:
            return self._handle_partial_matches(
                user_input, item, order, attr_slug, partial_matches, quantity,
                extract_selections_callback, format_display_list_callback,
            )

        return self._handle_single_select_fallback(
            user_input, user_lower, item, order, attr, attr_slug, options,
            quantity, input_type, advance_callback, format_display_list_callback,
            extract_selections_callback, extract_qualifier_callback,
        )

    def _apply_single_match(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        attr_slug: str,
        matched: dict,
        quantity: int,
        input_type: str,
        advance_callback,
        extract_qualifier_callback,
    ) -> StateMachineResult:
        """Apply a single matched option to the item."""
        # Extract qualifier for single match
        qualifier = extract_qualifier_callback(user_input, matched["display_name"])
        sel_price = matched.get("price") or matched.get("price_modifier") or 0

        # Determine the price for this option
        option_price = sel_price or 0.0
        variant_price_applied = False

        if input_type != "multi_select" and self.pricing:
            # Look up price from pricing engine
            variant_price, _ = self.pricing.lookup_size_price(
                item.menu_item_name, matched["slug"]
            )
            if variant_price is not None:
                # Check if this is a bundle-included item (price should stay $0)
                bundle_price_rule = getattr(item, 'bundle_price_rule', None)
                bundle_included_price = getattr(item, 'bundle_included_price', None)
                if bundle_price_rule == 'included' and bundle_included_price is None:
                    # Full inclusion: keep price at $0, don't apply variant pricing
                    item.unit_price = 0.0
                    variant_price_applied = False
                    logger.info(
                        "Bundle-included item %s: skipping variant pricing, keeping price=$0.00",
                        item.id
                    )
                else:
                    # Variant pricing found - set unit_price to the looked-up price
                    item.unit_price = variant_price
                    variant_price_applied = True
                    logger.info(
                        "Set unit_price for %s from variant pricing: %s=%s, price=%.2f",
                        item.id, attr_slug, matched["slug"], variant_price
                    )
            else:
                # No variant pricing - use upcharge lookup
                option_price = self.pricing.lookup_attribute_option_upcharge_for_item(
                    item.menu_item_name, item.menu_item_type, attr_slug, matched["slug"]
                ) or 0.0
                logger.info(
                    "Upcharge lookup: menu_item=%s, item_type=%s, attr=%s, option=%s -> price=%.2f",
                    item.menu_item_name, item.menu_item_type, attr_slug, matched["slug"], option_price
                )

        # Add selection using unified API
        if variant_price_applied:
            # Variant pricing already set unit_price to the full variant price.
            # Store selection with price=0 to avoid duplicate display in cart.
            item.add_selection(
                matched["slug"],
                attr_slug,
                quantity=quantity,
                price=0,  # No price since variant pricing handles it
                display_name=matched["display_name"],
            )
        else:
            item.add_selection(
                matched["slug"],
                attr_slug,
                quantity=quantity,
                price=option_price,
                display_name=matched["display_name"],
            )
            if option_price > 0:
                logger.info(
                    "Updated unit_price for %s: added %s price %.2f (qty=%d), new total %.2f",
                    item.id, attr_slug, option_price, quantity, item.unit_price
                )

        # Acknowledgment with quantity and qualifier
        ack_name = matched["display_name"]
        if qualifier:
            ack_name = f"{ack_name} ({qualifier})"
        ack_text = f"{quantity} {ack_name}" if quantity > 1 else ack_name
        return advance_callback(item, order, attr, ack_text)

    def _handle_partial_matches(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
        attr_slug: str,
        partial_matches: list[dict],
        quantity: int,
        extract_selections_callback,
        format_display_list_callback,
    ) -> StateMachineResult:
        """Handle multiple partial matches - disambiguation."""
        # Extract any selections that should be remembered during disambiguation
        stored_modifiers = {"_quantity": quantity}
        if extract_selections_callback:
            extracted_selections = extract_selections_callback(user_input, item.menu_item_type)
            if extracted_selections:
                for sel in extracted_selections:
                    stored_modifiers[sel.category] = sel.slug
                    if sel.quantity > 1:
                        stored_modifiers[f"{sel.category}_quantity"] = sel.quantity

        # Store disambiguation state
        order.pending_attr_disambiguation = {
            "options": partial_matches,
            "attr_slug": attr_slug,
            "modifiers": stored_modifiers,
            "item_id": item.id,
        }

        logger.info(
            "DISAMBIGUATION STARTED: attr=%s, options=%s, stored_mods=%s",
            attr_slug, [o["display_name"] for o in partial_matches], stored_modifiers
        )

        options_text = format_display_list_callback(partial_matches)
        return StateMachineResult(
            message=f"I found a few options matching that. Did you mean {options_text}?",
            order=order,
        )

    def _handle_single_select_fallback(
        self,
        user_input: str,
        user_lower: str,
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        attr_slug: str,
        options: list[dict],
        quantity: int,
        input_type: str,
        advance_callback,
        format_display_list_callback,
        extract_selections_callback,
        extract_qualifier_callback,
    ) -> StateMachineResult:
        """Handle fallback cases when no match found."""
        # Check for partial matches on option display names
        partial_result = self._check_partial_match(
            user_lower, options, item, order, attr_slug, format_display_list_callback,
            quantity=quantity
        )
        if partial_result:
            return partial_result

        # Try generic numeric matching for attributes with numeric option slugs
        numeric_match = self._try_numeric_option_match(
            user_input, options, item, order, attr, attr_slug, advance_callback
        )
        if numeric_match:
            return numeric_match

        # Check if input is an affirmative response ("yes", "sure", etc.)
        if is_affirmative(user_input):
            available_opts = [opt for opt in options if opt.get("is_available", True)]

            # If there's exactly ONE option, auto-select it
            # This handles "Would you like an espresso shot?" -> "yes" -> add 1 shot
            if len(available_opts) == 1:
                single_opt = available_opts[0]
                opt_price = single_opt.get("price") or single_opt.get("price_modifier") or 0.0
                display_name = single_opt.get("display_name", single_opt["slug"])

                item.add_selection(
                    single_opt["slug"],
                    attr_slug,
                    quantity=1,
                    price=opt_price,
                    display_name=display_name,
                )

                logger.info(
                    "AFFIRMATIVE_SINGLE_OPTION: auto-selected %s=%s for 'yes' response",
                    attr_slug, single_opt["slug"]
                )

                return advance_callback(item, order, attr, display_name)

            # Multiple options - ask which one
            attr_name = attr["display_name"].lower()
            available = [opt["display_name"] for opt in available_opts]
            if available and len(available) <= 6:
                options_str = format_english_list(available, conjunction="or")
                return StateMachineResult(
                    message=f"Great! Which {attr_name} would you like? {options_str}",
                    order=order,
                )

        # No match at all - show first page of options directly
        attr_name = attr["display_name"].lower()
        available = [opt for opt in options if opt.get("is_available", True)]

        if not available:
            message = f"Sorry, we don't have {user_input} and there are no {attr_name} options available."
        elif len(available) <= DEFAULT_PAGINATION_SIZE:
            # Show all options
            names = [opt["display_name"] for opt in available]
            options_str = format_english_list(names, conjunction="or")
            message = f"Sorry, we don't have {user_input}. We have {options_str}."
        else:
            # Show first page with pagination
            first_page = available[:DEFAULT_PAGINATION_SIZE]
            names = [opt["display_name"] for opt in first_page]
            options_str = format_english_list(names, conjunction="and")
            message = f"Sorry, we don't have {user_input}. We have {options_str}, and more. Do you want one of these or do you want to hear more options?"
            # Set pagination state so "yes" / "more options" works on next turn
            order.config_options_page = 1

        return StateMachineResult(message=message, order=order)

    def _check_partial_match(
        self,
        user_input: str,
        options: list[dict],
        item: MenuItemTask,
        order: OrderTask,
        attr_slug: str,
        format_display_list_callback,
        quantity: int = 1,
    ) -> StateMachineResult | None:
        """
        Check if user input partially matches option display names.

        For example:
        - "syrup" -> matches "vanilla syrup", "caramel syrup", "hazelnut syrup"
        """
        # Extract meaningful words using utility function
        words = extract_meaningful_words(user_input)
        if not words:
            return None

        # Find partial matches using utility function
        matching_options, matched_term = find_partial_matches(words, options)

        if not matching_options:
            return None

        if len(matching_options) == 1:
            logger.info(
                "Partial match '%s' matched single option: %s",
                user_input, matching_options[0]["display_name"]
            )
            return None

        # Multiple options match - list them for user
        options_text = format_display_list_callback(matching_options)

        # Store disambiguation state (including quantity from original input)
        order.pending_attr_disambiguation = {
            "options": matching_options,
            "attr_slug": attr_slug,
            "modifiers": {"_quantity": quantity},
            "item_id": item.id,
        }
        order.set_phase(OrderPhase.CONFIGURING_ITEM)
        order.pending_item_id = item.id
        order.pending_field = f"{item.menu_item_type}:{attr_slug}"

        logger.info(
            "Partial match: user said '%s', term '%s' matched %d options",
            user_input, matched_term, len(matching_options)
        )

        return StateMachineResult(
            message=f"We have {options_text}. Which would you like?",
            order=order,
        )

    def _try_numeric_option_match(
        self,
        user_input: str,
        options: list[dict],
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        attr_slug: str,
        advance_callback,
    ) -> StateMachineResult | None:
        """
        Try to match user input to options with numeric slugs.

        This enables data-driven handling of numeric attributes like "shots"
        where options have slugs like "1", "2", "3", "4".

        Also handles affirmative responses ("yes", "sure") by defaulting to "1"
        when the options are numeric. This supports flows like:
        - Bot: "Would you like an espresso shot?"
        - User: "yes" -> adds 1 shot
        """
        # Check if any options have numeric slugs (using utility function)
        numeric_slugs = find_numeric_options(options)
        if not numeric_slugs:
            return None

        # Parse numeric value from user input
        parsed_num = parse_numeric_input(user_input)

        # If no numeric value found but user said "yes", default to 1
        # This handles "Would you like a shot?" -> "yes" -> 1 shot
        if parsed_num is None:
            if is_affirmative(user_input) and "1" in numeric_slugs:
                parsed_num = 1
            else:
                return None

        # Find option with matching numeric slug
        target_slug = str(parsed_num)
        matched_option = None
        for opt in options:
            if opt["slug"] == target_slug:
                matched_option = opt
                break

        if not matched_option:
            return None

        # Found a match - add the selection
        opt_price = matched_option.get("price") or matched_option.get("price_modifier") or 0.0
        display_name = matched_option.get("display_name", f"{parsed_num}")

        item.add_selection(
            matched_option["slug"],
            attr_slug,
            quantity=1,
            price=opt_price,
            display_name=display_name,
        )

        logger.info(
            "NUMERIC_MATCH: %s=%s (price=$%.2f) from input '%s'",
            attr_slug, matched_option["slug"], opt_price, user_input
        )

        return advance_callback(item, order, attr, display_name)

