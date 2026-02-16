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
import re
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
from ..parsers.quantity_utils import parse_numeric_input, MAX_MODIFIER_QUANTITY
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
        user_lower = user_input.lower().strip()
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

        # Special handling for "half a pound" / "half pound" / "1/2 lb" weight inputs
        # These map to 2x quarter pound (1/4 lb) - same logic as by_pound_parsing.py
        # Must check BEFORE generic option matching to prevent "pound" matching "one_pound"
        if attr_slug == "weight":
            half_pound_pattern = re.compile(
                r"^(?:a\s+)?half\s+(?:a\s+)?(?:pound|lb)s?$|^1\s*/\s*2\s*(?:pound|lb)s?$",
                re.IGNORECASE
            )
            if half_pound_pattern.match(user_lower.strip()):
                # Look up the quarter pound option
                quarter_option = menu_cache.resolve_option_by_alias(attr_slug, "1/4 lb")
                if quarter_option:
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
                quantity, advance_callback,
            )

        # For single_select (or if multi_select found nothing), use single-match logic
        return self._handle_single_select(
            user_input, user_lower, item, order, attr, attr_slug, available_options,
            quantity, input_type, is_additive, advance_callback,
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

        # Check if any token matched multiple options - may need disambiguation
        result = self._check_multi_select_disambiguation(
            user_input, matched_options, options, item, order, attr, attr_slug,
            quantity,
        )
        if result:
            return result

        if matched_options:
            all_selections, added_selections = self._apply_multi_select_matches(
                matched_options, item, attr_slug, user_input, quantity,
            )

            # Build acknowledgment text with quantity
            display_names = []
            capped_note = None
            for sel in all_selections:
                name = sel["display_name"]
                qty = sel.get("quantity", 1)
                requested = sel.get("requested_quantity")
                if qty > 1:
                    name = f"{qty} {name}"
                if requested and requested > qty:
                    capped_note = (
                        f"I added {qty} instead of {requested}"
                        f" — {MAX_MODIFIER_QUANTITY} is the most we can do"
                    )
                display_names.append(name)
            ack_text = format_english_list(display_names)
            if capped_note:
                ack_text += f" ({capped_note})"

            # Check for unmatched tokens that need user response
            result = self._handle_unmatched_tokens(
                unmatched_tokens, all_selections, options, item, order, attr,
                attr_slug, ack_text, advance_callback,
            )
            if result:
                return result
            return advance_callback(item, order, attr, ack_text)

        # No matches - fall through to single select handling
        return self._handle_single_select_fallback(
            user_input, user_lower, item, order, attr, attr_slug, options,
            quantity, "multi_select", advance_callback,
        )

    def _check_multi_select_disambiguation(
        self,
        user_input: str,
        matched_options: list[dict],
        options: list[dict],
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        attr_slug: str,
        quantity: int,
    ) -> StateMachineResult | None:
        """Check if multi-select matches need disambiguation.

        Routes to specialized handlers for single-token and multi-token cases.

        Returns:
            StateMachineResult if disambiguation is needed, None otherwise.
        """
        if len(matched_options) <= 1:
            return None

        tokens = self._input_normalizer.tokenize_multi_input(user_input)

        # Case 1: Single token input matched multiple options (e.g. "syrups")
        if len(tokens) <= 1:
            result = self._disambiguate_single_token(
                user_input, matched_options, options, item, order, attr,
                attr_slug, quantity,
            )
            if result:
                return result

        # Case 2: Multi-token input where one token matched multiple options
        return self._disambiguate_multi_token(
            tokens, options, item, order, attr, attr_slug, quantity,
        )

    def _disambiguate_single_token(
        self,
        user_input: str,
        matched_options: list[dict],
        options: list[dict],
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        attr_slug: str,
        quantity: int,
    ) -> StateMachineResult | None:
        """Handle disambiguation when input is a single token matching multiple options.

        Checks if space-separated words each match a distinct option:
        - "salt pepper ketchup" = 3 words, 3 matches -> no disambiguation
        - "syrups" = 1 word, 3 matches -> needs disambiguation
        """
        space_words = [w for w in user_input.lower().split() if w.strip()]
        if len(space_words) >= len(matched_options):
            # Each word likely matched a distinct option - no disambiguation needed
            return None

        # Fewer words than matches - check each word individually
        unambiguous_matches = []
        first_ambiguous_options = None
        for word in space_words:
            word_matches = self._option_matcher.match_multiple(word, options)
            if len(word_matches) == 1:
                unambiguous_matches.append(word_matches[0])
            elif len(word_matches) > 1 and first_ambiguous_options is None:
                first_ambiguous_options = word_matches

        # Apply unambiguous matches immediately
        if unambiguous_matches:
            existing_slugs = {
                sel.get("slug") for sel in item.get_selections(attr_slug)
            }
            for match in unambiguous_matches:
                if match["slug"] not in existing_slugs:
                    opt_price = self._resolve_option_price(match, item.menu_item_type)
                    item.add_selection(
                        match["slug"],
                        attr_slug,
                        quantity=1,
                        price=opt_price,
                        display_name=match["display_name"],
                        ingredient_category=match.get("ingredient_category"),
                    )
                    existing_slugs.add(match["slug"])
                    logger.info(
                        "MULTI_SELECT: added unambiguous word match '%s'",
                        match["display_name"]
                    )

        if first_ambiguous_options is None:
            # All words unambiguous - no disambiguation needed
            return None

        # Disambiguate among the ambiguous word's matches
        return self._build_disambiguation_response(
            user_input, first_ambiguous_options, attr, attr_slug,
            quantity, item, order,
        )

    def _disambiguate_multi_token(
        self,
        tokens: list[str],
        options: list[dict],
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        attr_slug: str,
        quantity: int,
    ) -> StateMachineResult | None:
        """Handle disambiguation when one token in multi-token input matches multiple options.

        For each token, checks if it matched multiple options and whether
        individual words within the token resolve the ambiguity.
        """
        for token in tokens:
            token_matches = self._option_matcher.match_multiple(token, options)
            if len(token_matches) <= 1:
                continue

            # Check if each word in the token matches exactly one distinct option
            # e.g., "milk sugar" -> "milk" matches whole_milk, "sugar" matches domino_sugar
            if self._token_words_are_unambiguous(token, token_matches, options):
                continue

            # This single token matched multiple options - need disambiguation
            token_qty, _ = self._input_normalizer.extract_leading_quantity(token)
            if token_qty == 1:
                token_qty = quantity  # Fall back to overall quantity

            logger.info(
                "MULTI_SELECT DISAMBIGUATION: token '%s' matched %d options: %s",
                token, len(token_matches), [o["display_name"] for o in token_matches]
            )

            # Apply non-ambiguous matches from other tokens first
            self._apply_unambiguous_other_tokens(
                tokens, token, options, item, attr_slug,
            )

            # Store disambiguation state for the ambiguous token
            order.pending_attr_disambiguation = {
                "options": token_matches,
                "attr_slug": attr_slug,
                "modifiers": {"_quantity": token_qty},
                "item_id": item.id,
            }
            options_text = self._format_display_list(token_matches)
            attr_display = attr.get("display_name", attr_slug).lower()
            return StateMachineResult(
                message=f"Which {attr_display}? {options_text}",
                order=order,
            )

        return None

    def _token_words_are_unambiguous(
        self, token: str, token_matches: list[dict], options: list[dict]
    ) -> bool:
        """Check if individual words in a token each match exactly one distinct option."""
        token_words = [w for w in token.lower().split() if w.strip() and len(w) >= 2]
        if len(token_words) < 2:
            return False

        matched_by_word: set[str] = set()
        for word in token_words:
            word_matches = self._option_matcher.match_multiple(word, options)
            if len(word_matches) == 1:
                matched_by_word.add(word_matches[0]["slug"])
            elif len(word_matches) > 1:
                return False  # A word is ambiguous

        if len(matched_by_word) == len(token_matches):
            logger.debug(
                "MULTI_SELECT: token '%s' words each match distinct option, skipping disambiguation",
                token
            )
            return True
        return False

    def _apply_unambiguous_other_tokens(
        self,
        tokens: list[str],
        ambiguous_token: str,
        options: list[dict],
        item: MenuItemTask,
        attr_slug: str,
    ) -> None:
        """Apply non-ambiguous matches from other tokens before disambiguation."""
        for other_token in tokens:
            if other_token == ambiguous_token:
                continue
            other_matches = self._option_matcher.match_multiple(other_token, options)

            # Find the best match for this token
            best_match = None
            if len(other_matches) == 1:
                best_match = other_matches[0]
            elif len(other_matches) > 1:
                # Prefer option with must_match phrase matching the token
                other_token_lower = other_token.lower()
                for opt in other_matches:
                    must_match = opt.get("must_match", [])
                    if must_match and any(p.lower() in other_token_lower for p in must_match):
                        best_match = opt
                        break

            if best_match:
                existing_slugs = {sel.get("slug") for sel in item.get_selections(attr_slug)}
                if best_match["slug"] not in existing_slugs:
                    opt_price = self._resolve_option_price(best_match, item.menu_item_type)
                    item.add_selection(
                        best_match["slug"],
                        attr_slug,
                        quantity=1,
                        price=opt_price,
                        display_name=best_match["display_name"],
                        ingredient_category=best_match.get("ingredient_category"),
                    )
                    logger.info(
                        "MULTI_SELECT: added unambiguous match '%s' before disambiguation",
                        best_match["display_name"]
                    )

    def _build_disambiguation_response(
        self,
        user_input: str,
        ambiguous_options: list[dict],
        attr: dict,
        attr_slug: str,
        quantity: int,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Build a disambiguation response for ambiguous options."""
        logger.info(
            "MULTI_SELECT DISAMBIGUATION: input '%s' has ambiguous word "
            "matching %d options: %s",
            user_input, len(ambiguous_options),
            [o["display_name"] for o in ambiguous_options]
        )
        order.pending_attr_disambiguation = {
            "options": ambiguous_options,
            "attr_slug": attr_slug,
            "modifiers": {"_quantity": quantity},
            "item_id": item.id,
        }
        options_text = self._format_display_list(ambiguous_options)
        # Use the shared ingredient category as the label if all
        # ambiguous options belong to the same category (e.g. "syrup")
        categories = {
            o.get("ingredient_category")
            for o in ambiguous_options
            if o.get("ingredient_category")
        }
        if len(categories) == 1:
            cat_slug = next(iter(categories))
            attr_display = menu_cache.get_ingredient_category_display_name(
                cat_slug
            ).lower()
        else:
            attr_display = attr.get("display_name", attr_slug).lower()
        return StateMachineResult(
            message=f"Which {attr_display}? {options_text}",
            order=order,
        )

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
        added_selections = []
        for opt in matched_options:
            if opt["slug"] not in existing_slugs:
                # Extract qualifier (extra, light, on the side, etc.)
                qualifier = self._extract_qualifier(user_input, opt["display_name"])

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

        return None

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
        is_additive: bool,
        advance_callback,
    ) -> StateMachineResult:
        """Handle single_select input type."""
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

        options_text = self._format_display_list(partial_matches)
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
            if len(available_opts) == 1:
                single_opt = available_opts[0]
                opt_price = self._resolve_option_price(single_opt, item.menu_item_type)
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
            message = f"We have {options_text}. Which would you like?"
        else:
            first_page = matching_options[:DEFAULT_PAGINATION_SIZE]
            options_text = self._format_display_list(first_page)
            remaining = len(matching_options) - DEFAULT_PAGINATION_SIZE
            message = (
                f"We have {options_text}, and {remaining} more. "
                f"Would you like to hear more options or pick one of these?"
            )
            order.config_options_page = 1

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
            message=message,
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

