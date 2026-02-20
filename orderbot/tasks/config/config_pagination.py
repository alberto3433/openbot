"""
Configuration Pagination Handler for Menu Item Configuration.

Handles pagination of unmatched token option lists during item configuration.
When a user input doesn't match any option and the system shows available options
with "... and more", this handler manages the show-more / selection / decline flow.

Extracted from MenuItemConfigHandler._advance_from_pagination and
MenuItemConfigHandler._handle_unmatched_pagination.
"""

import logging
from typing import Callable, TYPE_CHECKING

from orderbot.cache import menu_cache
from ..response_utils import is_negative, is_affirmative
from ..utils.text import normalize_text

if TYPE_CHECKING:
    from ..models import OrderTask, MenuItemTask
    from ..models.pending_states import PendingUnmatchedPagination
    from ..schemas import StateMachineResult
    from ..utils import OptionMatcher
    from .question_builder import QuestionBuilder

logger = logging.getLogger(__name__)

__all__ = ["ConfigPaginationHandler"]


class ConfigPaginationHandler:
    """Handles unmatched-token pagination during item configuration.

    Manages the flow when a user enters a token that doesn't match any option
    and the system presents available options in pages.

    Args:
        option_matcher: OptionMatcher for matching user input to available options.
        question_builder: QuestionBuilder for pagination page advances and clearing.
        resolve_option_price: Callback to resolve option price (with pricing engine fallback).
        advance_to_next_question: Callback to advance to the next configuration question.
        get_next_question: Callback to get the next question for the order.
    """

    def __init__(
        self,
        option_matcher: "OptionMatcher",
        question_builder: "QuestionBuilder",
        resolve_option_price: Callable[[dict, str], float],
        advance_to_next_question: Callable,
        get_next_question: Callable[["OrderTask"], "StateMachineResult | None"],
    ):
        self._option_matcher = option_matcher
        self._question_builder = question_builder
        self._resolve_option_price = resolve_option_price
        self._advance_to_next_question = advance_to_next_question
        self._get_next_question = get_next_question

    def advance_from_pagination(
        self, pagination: "PendingUnmatchedPagination", item: "MenuItemTask",
        order: "OrderTask", matched_choice: str | None = None,
    ) -> "StateMachineResult":
        """Look up the attribute from pagination context and advance to next question.

        Consolidates the repeated pattern of resolving attr_slug from pagination
        state and calling _advance_to_next_question.

        Args:
            pagination: The pagination state model (must have 'attr_slug').
            item: The menu item being configured.
            order: Current order state.
            matched_choice: Optional display name of the user's choice (for acknowledgment).

        Returns:
            StateMachineResult with the next question.
        """
        attr_slug = pagination.attr_slug
        item_type = item.menu_item_type
        if item_type and attr_slug:
            attrs = menu_cache.get_item_type_attributes(item_type)
            attr = attrs.get(attr_slug)
            if attr:
                return self._advance_to_next_question(item, order, attr, matched_choice)
        return self._get_next_question(order)

    def handle_unmatched_pagination(
        self,
        user_input: str,
        item: "MenuItemTask",
        order: "OrderTask",
    ) -> "StateMachineResult | None":
        """Handle pagination responses for unmatched token messages.

        When user says "yes" or "more" after seeing "We don't have X. We have A, B, C... and more",
        this shows the next page of options.

        When user says "no" or selects an option, this resolves the pagination.

        Returns:
            StateMachineResult if pagination was handled, None otherwise.
        """
        pagination = order.pending_unmatched_pagination
        if not pagination:
            return None

        user_lower = normalize_text(user_input)

        # Check for "yes" / "more" to show next page
        if is_affirmative(user_input) or any(
            phrase in user_lower for phrase in ["more", "see more", "show more", "next"]
        ):
            return self._question_builder.advance_unmatched_pagination(order)

        # Check for "no" - decline options and advance to next question
        if is_negative(user_input):
            self._question_builder.clear_unmatched_pagination(order)
            return self.advance_from_pagination(pagination, item, order)

        # Check if user selected one of the available options
        available = pagination.available_options
        matched, _ = self._option_matcher.match_single(user_input, available)
        if matched:
            self._question_builder.clear_unmatched_pagination(order)
            attr_slug = pagination.attr_slug

            opt_price = self._resolve_option_price(matched, item.menu_item_type)

            item.add_selection(
                matched["slug"],
                attr_slug,
                quantity=1,
                price=opt_price,
                display_name=matched.get("display_name"),
                ingredient_category=matched.get("ingredient_category"),
            )
            logger.info(
                "UNMATCHED_PAGINATION: added selection '%s' for attr '%s'",
                matched["slug"], attr_slug
            )

            return self.advance_from_pagination(
                pagination, item, order, matched.get("display_name")
            )

        # Input didn't match pagination flow - clear and let normal handling proceed
        # This handles cases where user ignores the pagination and orders something else
        self._question_builder.clear_unmatched_pagination(order)
        return None
