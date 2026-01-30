"""
Option Matching Orchestrator.

Consolidates option matching and disambiguation logic that was duplicated across:
- menu_item_config_handler.py (_try_direct_option_match, _ask_disambiguation_for_options)
- select_input_handler.py (_handle_multi_select, _handle_single_select)
- modifier_change_handler.py (_analyze_modifier)

This orchestrator provides a single entry point for:
1. Matching user input to options (delegates to OptionMatcher)
2. Detecting disambiguation scenarios
3. Setting order disambiguation state
4. Building clarification messages
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .option_matcher import OptionMatcher
from .input_normalizer import InputNormalizer
from ..parsers.quantity_utils import extract_leading_quantity
from .text import format_english_list

if TYPE_CHECKING:
    from ..models import OrderTask, MenuItemTask

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """Result of an option matching operation."""

    matched_options: list[dict]
    """List of matched option dicts (may be empty if no matches)."""

    needs_disambiguation: bool
    """True if user input was ambiguous and needs clarification."""

    disambiguation_candidates: list[dict]
    """List of candidate options when disambiguation is needed."""

    clarification_message: str | None
    """Pre-built clarification message if disambiguation is needed."""

    quantity: int
    """Extracted quantity from user input (defaults to 1)."""

    @property
    def has_matches(self) -> bool:
        """True if at least one option was matched."""
        return len(self.matched_options) > 0

    @property
    def single_match(self) -> dict | None:
        """Return the single match if exactly one was found, else None."""
        return self.matched_options[0] if len(self.matched_options) == 1 else None


class OptionMatchingOrchestrator:
    """
    Orchestrates option matching with disambiguation handling.

    Provides a unified interface for matching user input to attribute options,
    handling both single-select and multi-select scenarios with disambiguation
    detection and state management.

    Usage:
        orchestrator = OptionMatchingOrchestrator()
        result = orchestrator.match_options(
            user_input="bacon",
            options=options_list,
            input_type="multi_select",
        )

        if result.needs_disambiguation:
            # Set disambiguation state on order
            orchestrator.set_disambiguation_state(
                order, item, attr_slug, result
            )
            return StateMachineResult(message=result.clarification_message, order=order)

        if result.has_matches:
            # Apply the matched options
            for opt in result.matched_options:
                item.add_selection(opt["slug"], ...)
    """

    def __init__(
        self,
        option_matcher: OptionMatcher | None = None,
        input_normalizer: InputNormalizer | None = None,
    ):
        """
        Initialize the orchestrator.

        Args:
            option_matcher: OptionMatcher instance. Uses default if not provided.
            input_normalizer: InputNormalizer for quantity extraction.
        """
        self._normalizer = input_normalizer or InputNormalizer()
        self._matcher = option_matcher or OptionMatcher(self._normalizer)

    def match_options(
        self,
        user_input: str,
        options: list[dict],
        input_type: str = "single_select",
        attr_display_name: str | None = None,
    ) -> MatchResult:
        """
        Match user input to options with disambiguation detection.

        Args:
            user_input: The user's input string
            options: List of option dicts with 'slug', 'display_name', etc.
            input_type: 'single_select' or 'multi_select'
            attr_display_name: Display name for the attribute (for clarification messages)

        Returns:
            MatchResult with matched options and disambiguation info
        """
        # Extract quantity from input
        quantity, remaining = extract_leading_quantity(user_input)
        quantity = quantity or 1

        if input_type == "multi_select":
            return self._match_multi_select(
                user_input, options, quantity, attr_display_name
            )
        else:
            return self._match_single_select(
                user_input, options, quantity, attr_display_name
            )

    def _match_multi_select(
        self,
        user_input: str,
        options: list[dict],
        quantity: int,
        attr_display_name: str | None,
    ) -> MatchResult:
        """Handle multi-select matching with disambiguation detection."""
        matched, disambiguation = self._matcher.match_multiple_with_disambiguation(
            user_input, options
        )

        if disambiguation:
            # Single ambiguous term matches multiple options
            message = self._build_disambiguation_message(
                disambiguation, attr_display_name
            )
            return MatchResult(
                matched_options=[],
                needs_disambiguation=True,
                disambiguation_candidates=disambiguation,
                clarification_message=message,
                quantity=quantity,
            )

        return MatchResult(
            matched_options=matched,
            needs_disambiguation=False,
            disambiguation_candidates=[],
            clarification_message=None,
            quantity=quantity,
        )

    def _match_single_select(
        self,
        user_input: str,
        options: list[dict],
        quantity: int,
        attr_display_name: str | None,
    ) -> MatchResult:
        """Handle single-select matching with partial match disambiguation."""
        matched_opt, partial_matches = self._matcher.match_single(user_input, options)

        if matched_opt:
            return MatchResult(
                matched_options=[matched_opt],
                needs_disambiguation=False,
                disambiguation_candidates=[],
                clarification_message=None,
                quantity=quantity,
            )

        if partial_matches:
            # Multiple partial matches - need disambiguation
            message = self._build_disambiguation_message(
                partial_matches, attr_display_name
            )
            return MatchResult(
                matched_options=[],
                needs_disambiguation=True,
                disambiguation_candidates=partial_matches,
                clarification_message=message,
                quantity=quantity,
            )

        # No matches
        return MatchResult(
            matched_options=[],
            needs_disambiguation=False,
            disambiguation_candidates=[],
            clarification_message=None,
            quantity=quantity,
        )

    def _build_disambiguation_message(
        self,
        candidates: list[dict],
        attr_display_name: str | None,
    ) -> str:
        """Build a clarification message for disambiguation."""
        display_names = [opt.get("display_name", opt["slug"]) for opt in candidates]
        options_text = format_english_list(display_names)

        if attr_display_name:
            return f"Which {attr_display_name} would you like? {options_text}?"
        else:
            return f"Did you mean {options_text}?"

    def set_disambiguation_state(
        self,
        order: "OrderTask",
        item: "MenuItemTask",
        attr_slug: str,
        result: MatchResult,
    ) -> None:
        """
        Set disambiguation state on the order.

        Call this when result.needs_disambiguation is True to store
        the disambiguation context for handling user's clarifying response.

        Args:
            order: The order to update
            item: The item being configured
            attr_slug: The attribute slug being configured
            result: The MatchResult with disambiguation candidates
        """
        order.pending_attr_disambiguation = {
            "options": result.disambiguation_candidates,
            "attr_slug": attr_slug,
            "modifiers": {"_quantity": result.quantity},
            "item_id": item.id,
        }

    def clear_disambiguation_state(self, order: "OrderTask") -> None:
        """Clear any pending disambiguation state on the order."""
        order.pending_attr_disambiguation = None
