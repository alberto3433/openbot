"""
Single-Select Input Handler.

Handles single-select attribute input processing including:
- Single option matching and application
- Partial match handling with disambiguation
- Fallback logic for unmatched inputs (numeric, affirmative, pagination)

Extracted from select_input.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from ..models import OrderTask, MenuItemTask
from ..models.pending_states import PendingAttrDisambiguation
from ..schemas import StateMachineResult
from ..selection_utils import (
    extract_meaningful_words,
    find_partial_matches,
    find_numeric_options,
)
from ..parsers.constants import extract_quantity_for_pattern, DEFAULT_PAGINATION_SIZE
from ..parsers.quantity_utils import parse_numeric_input
from ..utils.text import format_english_list
from ..response_utils import is_affirmative

if TYPE_CHECKING:
    from ..pricing import PricingEngine
    from ..utils import OptionMatcher, InputNormalizer

logger = logging.getLogger(__name__)


class SingleSelectHandler:
    """
    Handles single-select input processing.

    Manages option matching, disambiguation, and selection application
    for attributes with single_select input type.
    """

    def __init__(
        self,
        pricing: "PricingEngine | None",
        option_matcher: "OptionMatcher",
        input_normalizer: "InputNormalizer",
        format_display_list_callback=None,
        extract_selections_callback=None,
        extract_qualifier_callback=None,
        resolve_option_price_callback=None,
    ):
        """
        Initialize the single-select handler.

        Args:
            pricing: PricingEngine for price lookups.
            option_matcher: OptionMatcher for matching user input to options.
            input_normalizer: InputNormalizer for quantity extraction.
            format_display_list_callback: Callback to format options list for display.
            extract_selections_callback: Callback to extract selections from input.
            extract_qualifier_callback: Callback to extract qualifiers.
            resolve_option_price_callback: Callback to resolve option price.
        """
        self.pricing = pricing
        self._option_matcher = option_matcher
        self._input_normalizer = input_normalizer
        self._format_display_list = format_display_list_callback
        self._extract_selections = extract_selections_callback
        self._extract_qualifier = extract_qualifier_callback
        self._resolve_option_price = resolve_option_price_callback

    def handle_single_select(
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
        is_additive: bool,
        advance_callback,
    ) -> StateMachineResult:
        """Handle single_select input type.

        Args:
            user_input: Original user input string.
            user_lower: Lowercased/normalized user input.
            item: The MenuItemTask being configured.
            order: Current order state.
            attr: Attribute configuration dict.
            attr_slug: Attribute slug string.
            options: Available options for matching.
            quantity: Extracted quantity from input.
            input_type: The input type string (single_select or multi_select).
            is_additive: Whether this is an additive request.
            advance_callback: Callback to advance to next question.

        Returns:
            StateMachineResult with response or next question.
        """
        matched, partial_matches = self._option_matcher.match_single(user_input, options)

        if matched:
            return self._apply_single_match(
                user_input, item, order, attr, attr_slug, matched, quantity,
                input_type, is_additive, advance_callback,
            )

        # Multiple partial matches - store disambiguation state and ask
        if partial_matches:
            return self._handle_partial_matches(
                user_input, item, order, attr_slug, partial_matches, quantity,
            )

        return self._handle_single_select_fallback(
            user_input, user_lower, item, order, attr, attr_slug, options,
            quantity, input_type, advance_callback,
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
        is_additive: bool,
        advance_callback,
    ) -> StateMachineResult:
        """Apply a single matched option to the item."""
        # Extract qualifier for single match
        qualifier = self._extract_qualifier(user_input, matched["display_name"])

        # Extract quantity specific to matched option (e.g., "yes 2 shots" -> qty=2)
        # This catches cases where leading quantity extraction failed due to prefix words
        pattern_qty = extract_quantity_for_pattern(user_input, matched["slug"].replace("_", " "))
        if pattern_qty > quantity:
            quantity = pattern_qty
        sel_price = matched.get("price") or matched.get("price_modifier") or 0

        # Determine the price for this option
        option_price = sel_price or 0.0
        variant_price_applied = False

        if input_type != "multi_select" and self.pricing:
            # Only use variant pricing when this attribute is the item's
            # size/variant attribute (e.g., "size" for coffee, "weight" for
            # spreads).  Other single-select attributes like "bread" should
            # fall through to the upcharge lookup instead.
            size_cat = self.pricing.get_size_category_slug(item.menu_item_name)
            variant_price = None
            if size_cat and attr_slug == size_cat:
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

        # For additive requests (e.g., "add 2 eggs" to item with 1 egg), get existing quantity
        # BEFORE removing the selection so we can add to it
        if is_additive and input_type != "multi_select":
            existing_sel = item.get_selection(attr_slug)
            if existing_sel:
                existing_quantity = existing_sel.get("quantity", 1)
                original_quantity = quantity
                quantity = existing_quantity + quantity
                logger.info(
                    "ADDITIVE: Adding to existing quantity %d + %d = %d for attr=%s",
                    existing_quantity, original_quantity, quantity, attr_slug
                )

        # For single-select attributes, remove any existing selection before adding new one
        # This prevents the attribute_values from becoming a list with [old_value, new_value]
        if input_type != "multi_select":
            item.remove_selection(attr_slug)

        # Build display name with qualifier if present (e.g., "Scrambled (well done)")
        display_name = matched["display_name"]
        if qualifier:
            display_name = f"{display_name} ({qualifier})"

        # Add selection using unified API
        if variant_price_applied:
            # Variant pricing already set unit_price to the full variant price.
            # Store selection with price=0 to avoid duplicate display in cart.
            item.add_selection(
                matched["slug"],
                attr_slug,
                quantity=quantity,
                price=0,  # No price since variant pricing handles it
                display_name=display_name,
            )
        else:
            item.add_selection(
                matched["slug"],
                attr_slug,
                quantity=quantity,
                price=option_price,
                display_name=display_name,
            )
            if option_price > 0:
                logger.info(
                    "Updated unit_price for %s: added %s price %.2f (qty=%d), new total %.2f",
                    item.id, attr_slug, option_price, quantity, item.unit_price
                )

        # Acknowledgment with quantity and qualifier
        ack_name = display_name
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
    ) -> StateMachineResult:
        """Handle multiple partial matches - disambiguation."""
        # Extract any selections that should be remembered during disambiguation
        stored_modifiers = {"_quantity": quantity}
        if self._extract_selections:
            extracted_selections = self._extract_selections(user_input, item.menu_item_type)
            if extracted_selections:
                for sel in extracted_selections:
                    stored_modifiers[sel.category] = sel.slug
                    if sel.quantity > 1:
                        stored_modifiers[f"{sel.category}_quantity"] = sel.quantity

        # Store disambiguation state
        order.pending_attr_disambiguation = PendingAttrDisambiguation(
            options=partial_matches,
            attr_slug=attr_slug,
            modifiers=stored_modifiers,
            item_id=item.id,
        )

        logger.info(
            "DISAMBIGUATION STARTED: attr=%s, options=%s, stored_mods=%s",
            attr_slug, [o["display_name"] for o in partial_matches], stored_modifiers
        )

        options_text = self._format_display_list(partial_matches)
        # Build quick replies for inline clickable text
        qr = [{"label": o["display_name"], "value": o["display_name"]} for o in partial_matches]
        return StateMachineResult(
            message=f"I found a few options matching that. Did you mean {options_text}?",
            order=order,
            quick_replies=qr,
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
    ) -> StateMachineResult:
        """Handle fallback cases when no match found."""
        # Check for partial matches on option display names
        partial_result = self._check_partial_match(
            user_lower, options, item, order, attr_slug,
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

        # Try numeric quantity for single-option attributes
        # This handles "2" for attributes with a single option like "Shot"
        # where user is specifying quantity, not selecting an option
        available_opts = [opt for opt in options if opt.get("is_available", True)]
        if len(available_opts) == 1:
            parsed_qty = parse_numeric_input(user_input)
            if parsed_qty is not None and parsed_qty >= 1:
                single_opt = available_opts[0]
                opt_price = self._resolve_option_price(single_opt, item.menu_item_type)
                display_name = single_opt.get("display_name", single_opt["slug"])

                item.add_selection(
                    single_opt["slug"],
                    attr_slug,
                    quantity=parsed_qty,
                    price=opt_price,
                    display_name=display_name,
                )

                logger.info(
                    "NUMERIC_SINGLE_OPTION: auto-selected %s=%s qty=%d for numeric input '%s'",
                    attr_slug, single_opt["slug"], parsed_qty, user_input
                )

                return advance_callback(item, order, attr, display_name)

        # Check if input is an affirmative response ("yes", "sure", etc.)
        if is_affirmative(user_input):
            available_opts = [opt for opt in options if opt.get("is_available", True)]

            # If there's exactly ONE option, auto-select it
            # This handles "Would you like an espresso shot?" -> "yes" -> add 1 shot
            # Also handles "yes 2 shots" -> add 2 shots
            if len(available_opts) == 1:
                single_opt = available_opts[0]
                opt_price = self._resolve_option_price(single_opt, item.menu_item_type)
                display_name = single_opt.get("display_name", single_opt["slug"])

                # Extract quantity from input (e.g., "yes 2 shots" -> qty=2)
                qty = extract_quantity_for_pattern(user_input, single_opt["slug"])

                item.add_selection(
                    single_opt["slug"],
                    attr_slug,
                    quantity=qty,
                    price=opt_price,
                    display_name=display_name,
                )

                logger.info(
                    "AFFIRMATIVE_SINGLE_OPTION: auto-selected %s=%s qty=%d for 'yes' response",
                    attr_slug, single_opt["slug"], qty
                )

                return advance_callback(item, order, attr, display_name)

            # Multiple options - ask which one
            attr_name = attr["display_name"].lower()
            available = [opt["display_name"] for opt in available_opts]
            if available:
                page_names, qr, has_more = self._build_paginated_option_replies(available)
                options_str = format_english_list(page_names, conjunction="or" if not has_more else "and")
                if has_more:
                    message = f"Sure! We have {options_str}, and more — which {attr_name} would you like?"
                else:
                    message = f"Sure! Which {attr_name} would you like? {options_str}"
                return StateMachineResult(
                    message=message,
                    order=order,
                    quick_replies=qr,
                )

        # No match at all - show first page of options directly
        attr_name = attr["display_name"].lower()
        available = [opt for opt in options if opt.get("is_available", True)]

        qr = None
        if not available:
            message = f"Sorry, we don't have {user_input} and there are no {attr_name} options available."
        else:
            names = [opt["display_name"] for opt in available]
            page_names, qr, has_more = self._build_paginated_option_replies(names)
            options_str = format_english_list(page_names, conjunction="or" if not has_more else "and")
            if has_more:
                message = f"Sorry, we don't have {user_input}. We have {options_str}, and more — do you want one of these or do you want to hear more options?"
                # Set pagination state so "yes" / "more options" works on next turn
                order.config_options_page = 1
            else:
                message = f"Sorry, we don't have {user_input}. We have {options_str}."

        return StateMachineResult(message=message, order=order, quick_replies=qr)

    @staticmethod
    def _build_paginated_option_replies(
        names: list[str],
    ) -> tuple[list[str], list[dict], bool]:
        """Build a (possibly paginated) list of quick-reply options.

        If the number of names fits within DEFAULT_PAGINATION_SIZE, returns all
        names. Otherwise, returns the first page with a "more" button appended.

        Args:
            names: Display names of available options.

        Returns:
            Tuple of (page_names, quick_replies, has_more).
        """
        if len(names) <= DEFAULT_PAGINATION_SIZE:
            qr = [{"label": name, "value": name} for name in names]
            return names, qr, False

        first_page = names[:DEFAULT_PAGINATION_SIZE]
        qr = [{"label": name, "value": name} for name in first_page]
        qr.append({"label": "more", "value": "what else?"})
        return first_page, qr, True

    def _check_partial_match(
        self,
        user_input: str,
        options: list[dict],
        item: MenuItemTask,
        order: OrderTask,
        attr_slug: str,
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

        # Multiple options match - list them for user (with pagination)
        if len(matching_options) <= DEFAULT_PAGINATION_SIZE:
            options_text = self._format_display_list(matching_options)
            batch_names = [opt["display_name"] for opt in matching_options]
            has_more = False
            message = f"We have {options_text}. Which would you like?"
        else:
            first_page = matching_options[:DEFAULT_PAGINATION_SIZE]
            options_text = self._format_display_list(first_page)
            batch_names = [opt["display_name"] for opt in first_page]
            has_more = True
            remaining = len(matching_options) - DEFAULT_PAGINATION_SIZE
            message = (
                f"We have {options_text}, and {remaining} more. "
                f"Would you like to hear more options or pick one of these?"
            )

        # Store disambiguation state (including quantity from original input)
        order.pending_attr_disambiguation = PendingAttrDisambiguation(
            options=matching_options,
            attr_slug=attr_slug,
            modifiers={"_quantity": quantity},
            item_id=item.id,
        )
        order.setup_pending_config(item.id, f"{item.menu_item_type}:{attr_slug}")

        # Set pagination page AFTER setup_pending_config (which resets it to 0)
        if has_more:
            order.config_options_page = 1

        logger.info(
            "Partial match: user said '%s', term '%s' matched %d options",
            user_input, matched_term, len(matching_options)
        )

        # Build quick replies for inline clickable text
        qr = [{"label": name, "value": name} for name in batch_names]
        if has_more:
            qr.append({"label": f"{remaining} more", "value": "what else?"})

        return StateMachineResult(
            message=message,
            order=order,
            quick_replies=qr,
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
        opt_price = self._resolve_option_price(matched_option, item.menu_item_type)
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
