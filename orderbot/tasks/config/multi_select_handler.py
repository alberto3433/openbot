"""
Multi-Select Input Handler.

Handles multi-select attribute input processing including:
- Matching multiple options from user input
- Disambiguation for ambiguous multi-select matches
- Applying matched selections to items

Extracted from select_input.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache

from ..models import OrderTask, MenuItemTask
from ..models.pending_states import PendingAttrDisambiguation
from ..schemas import StateMachineResult
from ..parsers.constants import extract_quantity_for_pattern
from ..parsers.quantity_utils import MAX_MODIFIER_QUANTITY
from ..utils.text import format_english_list

if TYPE_CHECKING:
    from ..utils import OptionMatcher, InputNormalizer

logger = logging.getLogger(__name__)


class MultiSelectHandler:
    """
    Handles multi-select input processing.

    Manages option matching, disambiguation, and selection application
    for attributes with multi_select input type.
    """

    def __init__(
        self,
        option_matcher: "OptionMatcher",
        input_normalizer: "InputNormalizer",
        format_display_list_callback=None,
        resolve_option_price_callback=None,
        find_option_position_callback=None,
        apply_multi_select_matches_callback=None,
        handle_unmatched_tokens_callback=None,
        extract_qualifier_callback=None,
    ):
        """
        Initialize the multi-select handler.

        Args:
            option_matcher: OptionMatcher for matching user input to options.
            input_normalizer: InputNormalizer for tokenizing and quantity extraction.
            format_display_list_callback: Callback to format options list for display.
            resolve_option_price_callback: Callback to resolve option price.
            find_option_position_callback: Callback to find option position in input.
            apply_multi_select_matches_callback: Callback to apply matched options.
            handle_unmatched_tokens_callback: Callback to handle unmatched tokens.
            extract_qualifier_callback: Callback to extract qualifiers.
        """
        self._option_matcher = option_matcher
        self._input_normalizer = input_normalizer
        self._format_display_list = format_display_list_callback
        self._resolve_option_price = resolve_option_price_callback
        self._find_option_position = find_option_position_callback
        self._apply_multi_select_matches = apply_multi_select_matches_callback
        self._handle_unmatched_tokens = handle_unmatched_tokens_callback
        self._extract_qualifier = extract_qualifier_callback

    def handle_multi_select(
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
        single_select_fallback_callback,
    ) -> StateMachineResult:
        """Handle multi_select input type.

        Args:
            user_input: Original user input string.
            user_lower: Lowercased/normalized user input.
            item: The MenuItemTask being configured.
            order: Current order state.
            attr: Attribute configuration dict.
            attr_slug: Attribute slug string.
            options: Available options for matching.
            quantity: Extracted quantity from input.
            advance_callback: Callback to advance to next question.
            single_select_fallback_callback: Callback to fall through to single-select.

        Returns:
            StateMachineResult with response or next question.
        """
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
        return single_select_fallback_callback(
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
            order.pending_attr_disambiguation = PendingAttrDisambiguation(
                options=token_matches,
                attr_slug=attr_slug,
                modifiers={"_quantity": token_qty},
                item_id=item.id,
            )
            options_text = self._format_display_list(token_matches)
            attr_display = attr.get("display_name", attr_slug).lower()
            # Build quick replies for inline clickable text
            qr = [{"label": o["display_name"], "value": o["display_name"]} for o in token_matches]
            return StateMachineResult(
                message=f"Which {attr_display}? {options_text}",
                order=order,
                quick_replies=qr,
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
        order.pending_attr_disambiguation = PendingAttrDisambiguation(
            options=ambiguous_options,
            attr_slug=attr_slug,
            modifiers={"_quantity": quantity},
            item_id=item.id,
        )
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
        # Build quick replies for inline clickable text
        qr = [{"label": o["display_name"], "value": o["display_name"]} for o in ambiguous_options]
        return StateMachineResult(
            message=f"Which {attr_display}? {options_text}",
            order=order,
            quick_replies=qr,
        )
