"""
Select Input Handler.

This module handles single/multi select input processing including:
- Single-select attribute matching
- Multi-select attribute matching with quantity extraction
- Disambiguation for ambiguous matches
- Partial match handling
- Numeric option matching

Dispatches to MultiSelectHandler and SingleSelectHandler for
type-specific logic. Keeps shared utilities (price resolution,
half-pound pattern, option position finding, multi-select match
application, unmatched token handling) in this class.

Extracted from menu_item_config_handler.py for better separation of concerns.
"""

import logging
import re
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache

from ..utils.pricing_utils import safe_recalculate_price
from ..parsers.constants import HALF_POUND_PATTERN
from ..models import OrderTask, MenuItemTask
from ..models.pending_states import PendingUnmatchedPagination
from ..schemas import StateMachineResult
from ..parsers.constants import extract_quantity_for_pattern, DEFAULT_PAGINATION_SIZE
from ..parsers.quantity_utils import MAX_MODIFIER_QUANTITY
from ..utils.text import format_english_list, normalize_text
from ..utils import OptionMatcher

from .multi_select_handler import MultiSelectHandler
from .single_select_handler import SingleSelectHandler

if TYPE_CHECKING:
    from ..pricing import PricingEngine
    from ..utils import InputNormalizer

logger = logging.getLogger(__name__)


class SelectInputHandler:
    """
    Handles single/multi select input processing.

    Manages option matching, disambiguation, and selection application
    for attribute questions with select-type inputs.

    Delegates to MultiSelectHandler and SingleSelectHandler for
    type-specific logic while keeping shared utilities here.
    """

    def __init__(
        self,
        pricing: "PricingEngine | None",
        option_matcher: "OptionMatcher",
        input_normalizer: "InputNormalizer",
        format_display_list_callback=None,
        extract_selections_callback=None,
        extract_qualifier_callback=None,
    ):
        """
        Initialize the select input handler.

        Args:
            pricing: PricingEngine for price lookups.
            option_matcher: OptionMatcher for matching user input to options.
            input_normalizer: InputNormalizer for extracting quantities.
            format_display_list_callback: Callback to format options list for display.
            extract_selections_callback: Callback to extract selections from input.
            extract_qualifier_callback: Callback to extract qualifiers (extra, light, etc.).
        """
        self.pricing = pricing
        self._option_matcher = option_matcher
        self._input_normalizer = input_normalizer
        self._format_display_list = format_display_list_callback
        self._extract_selections = extract_selections_callback
        self._extract_qualifier = extract_qualifier_callback

        # Initialize sub-handlers
        self._multi_select_handler = MultiSelectHandler(
            option_matcher=option_matcher,
            input_normalizer=input_normalizer,
            format_display_list_callback=format_display_list_callback,
            resolve_option_price_callback=self._resolve_option_price,
            find_option_position_callback=self._find_option_position_in_input,
            apply_multi_select_matches_callback=self._apply_multi_select_matches,
            handle_unmatched_tokens_callback=self._handle_unmatched_tokens,
            extract_qualifier_callback=extract_qualifier_callback,
        )

        self._single_select_handler = SingleSelectHandler(
            pricing=pricing,
            option_matcher=option_matcher,
            input_normalizer=input_normalizer,
            format_display_list_callback=format_display_list_callback,
            extract_selections_callback=extract_selections_callback,
            extract_qualifier_callback=extract_qualifier_callback,
            resolve_option_price_callback=self._resolve_option_price,
        )

    def _resolve_option_price(self, option: dict, item_type: str) -> float:
        """Look up option price with pricing engine fallback.

        Consolidates the repeated pattern of checking option price fields
        then falling back to the pricing engine for modifier prices.

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

    def _handle_half_pound_pattern(
        self,
        user_lower: str,
        attr: dict,
        item: MenuItemTask,
        order: OrderTask,
        advance_callback,
    ) -> StateMachineResult | None:
        """Handle 'half a pound' / '1/2 lb' pattern for weight-based attributes.

        These map to 2x quarter pound (1/4 lb). Must check BEFORE generic option
        matching to prevent "pound" from matching "one_pound".

        Returns:
            StateMachineResult if matched, None to continue normal flow.
        """
        attr_slug = attr["slug"]
        if attr_slug != "weight":
            return None

        if not HALF_POUND_PATTERN.match(user_lower.strip()):
            return None

        # Look up the quarter pound option
        quarter_option = menu_cache.resolve_option_by_alias(attr_slug, "1/4 lb")
        if not quarter_option:
            return None

        opt_slug = quarter_option.get("slug")
        logger.info(
            "HALF_POUND_HANDLER: Resolved 'half a pound' to %s=%s with qty=2",
            attr_slug, opt_slug
        )
        item[attr_slug] = opt_slug
        item.quantity = 2  # Two quarter-pound portions = half pound
        # Apply variant pricing for the quarter pound option
        if self.pricing:
            variant_price, _ = self.pricing.lookup_size_price(
                item.menu_item_name, opt_slug
            )
            if variant_price is not None:
                item.unit_price = variant_price
                logger.info(
                    "Set unit_price for %s from variant pricing: %s=%s, price=%.2f",
                    item.id, attr_slug, opt_slug, variant_price
                )
        return advance_callback(item, order, attr, "1/2 lb")

    def handle_select_input(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        options: list[dict],
        advance_callback,
    ) -> StateMachineResult:
        """Handle single/multi select input.

        Args:
            user_input: User's input string
            item: The MenuItemTask being configured
            order: Current order state
            attr: Attribute configuration dict
            options: List of available options
            advance_callback: Callback to advance to next question

        Returns:
            StateMachineResult with response or next question
        """
        attr_slug = attr["slug"]
        user_lower = normalize_text(user_input)
        input_type = attr.get("input_type", "single_select")

        # Extract quantity from input (e.g., "2 scrambled eggs" -> quantity=2)
        # Also check pending_modifier_quantity which was stored when asking the question
        quantity, _ = self._input_normalizer.extract_leading_quantity(user_input)
        if quantity == 1 and order.pending_modifier_quantity:
            quantity = order.pending_modifier_quantity
        # Check if this is an additive request (e.g., "add 2 eggs" to item with 1 egg)
        is_additive = order.pending_modifier_is_additive
        # Clear pending quantity/additive flags after extracting them
        order.pending_modifier_quantity = None
        order.pending_modifier_is_additive = False

        # Check for half-pound / 1/2 lb pattern before generic option matching
        half_result = self._handle_half_pound_pattern(
            user_lower, attr, item, order, advance_callback,
        )
        if half_result:
            return half_result

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

            # Check negation patterns targeting the attribute name
            # e.g., "I don't want a spread", "don't need any spread"
            attr_display = attr.get("display_name", "").lower()
            if attr_display:
                negation_skip = re.search(
                    rf"don'?t\s+(?:want|need|like)\s+(?:a\s+|an\s+|any\s+|the\s+)?{re.escape(attr_display)}",
                    user_lower,
                )
                if negation_skip:
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
                    qr = [{"label": name, "value": name} for name in names]
                    return StateMachineResult(
                        message=f"Sorry, we don't have {unavail_name}. We have {options_str}.",
                        order=order,
                        quick_replies=qr,
                    )
                else:
                    return StateMachineResult(
                        message=f"Sorry, we don't have {unavail_name}.",
                        order=order,
                    )

        # For multi_select, try to match ALL options in the input
        if input_type == "multi_select":
            return self._multi_select_handler.handle_multi_select(
                user_input, user_lower, item, order, attr, attr_slug, available_options,
                quantity, advance_callback,
                single_select_fallback_callback=self._single_select_handler._handle_single_select_fallback,
            )

        # For single_select (or if multi_select found nothing), use single-match logic
        return self._single_select_handler.handle_single_select(
            user_input, user_lower, item, order, attr, attr_slug, available_options,
            quantity, input_type, is_additive, advance_callback,
        )

    @staticmethod
    def _find_option_position_in_input(
        user_lower: str, option_name: str,
    ) -> tuple[int, int] | None:
        """Find the position of an option name in the user input.

        Uses the same word-boundary matching logic as _extract_qualifier_for_option:
        tries the full display name first, then individual words (>= 3 chars).

        Args:
            user_lower: Lowercased user input text.
            option_name: The option display name to locate.

        Returns:
            (start, end) position tuple, or None if not found.
        """
        option_lower = option_name.lower()
        search_terms = [option_lower]
        for word in option_lower.split():
            if len(word) >= 3:
                search_terms.append(word)
        for term in search_terms:
            match = re.search(rf'\b{re.escape(term)}\b', user_lower)
            if match:
                return (match.start(), match.end())
        return None

    def _apply_multi_select_matches(
        self,
        matched_options: list[dict],
        item: MenuItemTask,
        attr_slug: str,
        user_input: str,
        quantity: int,
    ) -> tuple[list[dict], list[dict]]:
        """Apply matched options to the item as selections.

        Processes each matched option, extracts qualifiers and quantities,
        looks up prices, and adds selections to the item.

        Args:
            matched_options: Options that were matched from user input.
            item: The MenuItemTask being configured.
            attr_slug: Attribute slug string.
            user_input: Original user input string.
            quantity: Default quantity extracted from user input.

        Returns:
            Tuple of (all_selections, added_selections) where all_selections
            includes existing + newly added, and added_selections is only new.
        """
        # Get existing selections for this category
        existing_selections = item.get_selections(attr_slug)
        existing_slugs = {sel.get("slug") for sel in existing_selections}

        user_lower = user_input.lower()

        # Pre-compute option positions for qualifier proximity checks.
        # When multiple options are matched, a qualifier should only attach to
        # the closest option (e.g., "milk and a little sugar" -> only sugar
        # gets the "light" qualifier).
        option_positions: dict[str, tuple[int, int]] = {}
        if len(matched_options) > 1:
            for opt in matched_options:
                pos = self._find_option_position_in_input(user_lower, opt["display_name"])
                if pos:
                    option_positions[opt["slug"]] = pos

        added_selections = []
        for opt in matched_options:
            if opt["slug"] not in existing_slugs:
                # Build other_option_positions for this option (positions of all OTHER options)
                other_positions = None
                if option_positions:
                    other_positions = [
                        pos for slug, pos in option_positions.items()
                        if slug != opt["slug"]
                    ]
                    if not other_positions:
                        other_positions = None

                # Extract qualifier (extra, light, on the side, etc.)
                qualifier = self._extract_qualifier(
                    user_input, opt["display_name"],
                    other_option_positions=other_positions,
                )

                # Extract quantity specific to this option (e.g., "2 shots", "two splendas")
                opt_quantity = extract_quantity_for_pattern(user_lower, opt["display_name"].lower())
                if opt_quantity == 1:
                    opt_quantity = extract_quantity_for_pattern(user_lower, opt["slug"].replace("_", " "))
                if opt_quantity == 1 and opt.get("aliases"):
                    for alias in opt["aliases"]:
                        alias_qty = extract_quantity_for_pattern(user_lower, alias.lower())
                        if alias_qty > 1:
                            opt_quantity = alias_qty
                            break

                # Cap per-modifier quantity
                requested_quantity = opt_quantity
                if opt_quantity > MAX_MODIFIER_QUANTITY:
                    opt_quantity = MAX_MODIFIER_QUANTITY

                opt_price = self._resolve_option_price(opt, item.menu_item_type)

                # Build display name with qualifier if present
                display_name = opt["display_name"]
                if qualifier:
                    display_name = f"{display_name} ({qualifier})"

                # Add selection using unified API
                item.add_selection(
                    opt["slug"],
                    attr_slug,
                    quantity=opt_quantity,
                    price=opt_price,
                    display_name=display_name,
                    ingredient_category=opt.get("ingredient_category"),
                )
                added_selections.append({
                    "slug": opt["slug"],
                    "display_name": display_name,
                    "price": opt_price,
                    "quantity": opt_quantity,
                    "qualifier": qualifier,
                    "requested_quantity": requested_quantity,
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

        return (all_selections, added_selections)

    def _handle_unmatched_tokens(
        self,
        unmatched_tokens: list[str],
        all_selections: list[dict],
        options: list[dict],
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        attr_slug: str,
        ack_text: str,
        advance_callback,
    ) -> StateMachineResult | None:
        """Handle unmatched tokens from multi-select input.

        Filters out qualifier words, then builds a response telling the user
        which tokens were not recognized and showing available options.

        Args:
            unmatched_tokens: Tokens that did not match any option.
            all_selections: All current selections (existing + newly added).
            options: All available options for this attribute.
            item: The MenuItemTask being configured.
            order: Current order state.
            attr: Attribute configuration dict.
            attr_slug: Attribute slug string.
            ack_text: Acknowledgment text for matched selections.
            advance_callback: Callback to advance to next question.

        Returns:
            StateMachineResult if unmatched tokens need response, None otherwise.
        """
        # Filter out qualifier pattern words from unmatched tokens
        # e.g., "a little bit of milk" -> "little", "bit", "of" shouldn't be "not found"
        if unmatched_tokens:
            qualifier_patterns = menu_cache.get_qualifier_patterns()
            # Build set of all words that appear in qualifier patterns
            qualifier_words = set()
            for pattern in qualifier_patterns:
                for word in pattern.lower().split():
                    if len(word) >= 2:  # Skip single-char words
                        qualifier_words.add(word)
            # Also filter common prepositions/articles that appear in qualifiers
            qualifier_words.update({'a', 'of', 'the', 'on', 'with'})
            # Filter out qualifier words from unmatched tokens
            unmatched_tokens = [t for t in unmatched_tokens if t.lower() not in qualifier_words]

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
            order.pending_unmatched_pagination = PendingUnmatchedPagination(
                unmatched_text=unmatched_text,
                attr_slug=attr_slug,
                available_options=available,
                page=0,
                item_id=item.id,
            )

            # Build options list with pagination
            if len(available) <= DEFAULT_PAGINATION_SIZE:
                names = [opt["display_name"] for opt in available]
                options_str = format_english_list(names, conjunction="or")
                has_more = False
                message = (
                    f"Got it, {ack_text}. We don't have {unmatched_text}. "
                    f"We have {options_str}. Would you like any of these?"
                )
            else:
                first_page = available[:DEFAULT_PAGINATION_SIZE]
                names = [opt["display_name"] for opt in first_page]
                options_str = format_english_list(names, conjunction="and")
                has_more = True
                message = (
                    f"Got it, {ack_text}. We don't have {unmatched_text}. "
                    f"We have {options_str}... and more — would you like to see more options?"
                )
                order.pending_unmatched_pagination.page = 1

            # Build quick replies for inline clickable text
            from ..handler_utils import build_quick_replies
            qr = build_quick_replies(names)
            if has_more:
                qr.append({"label": "more", "value": "what else?"})

            # Recalculate price for selections already applied above.
            # Normally advance_callback handles this, but it's skipped when
            # unmatched tokens keep us on the current question.
            safe_recalculate_price(self.pricing, item, "after multi-select with unmatched tokens")

            return StateMachineResult(message=message, order=order, quick_replies=qr)

        return None
