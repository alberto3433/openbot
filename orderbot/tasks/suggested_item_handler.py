"""
Suggested Item Handler Module.

Handles suggested item / ingredient suggestion / dietary followup confirmation flows.

Extracted from taking_items_handler.py for better separation of concerns.
"""

import logging
import re
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache

from .models import OrderTask
from .models.pending_states import PendingIngredientSuggestion
from .pending_fields import PendingField
from .schemas import StateMachineResult
from .response_utils import is_affirmative
from .utils.text import format_english_list, normalize_text

if TYPE_CHECKING:
    from .taking_items_handler import TakingItemsHandler

logger = logging.getLogger(__name__)

# Pattern for ordering-intent phrases that implicitly confirm a suggested item.
# Matches "I'll take one", "let me get that", "give me one", etc.
_IMPLICIT_ACCEPT_PATTERN = re.compile(
    r"(?:i'll|i\s+will)\s+(?:take|have|try|get|order)\s+(?:one|that|it|some)"
    r"|(?:let\s+me|can\s+i|could\s+i)\s+(?:get|have|try)\s+(?:one|that|it|some)"
    r"|(?:give|get)\s+me\s+(?:one|that|it|some)",
    re.IGNORECASE,
)


def _is_implicit_accept(text: str) -> bool:
    """Check if text contains ordering-intent phrases that implicitly accept a suggestion."""
    return bool(_IMPLICIT_ACCEPT_PATTERN.search(text))


class SuggestedItemHandler:
    """Handles suggested item confirmation, ingredient suggestion, and dietary followup flows.

    Delegates back to the parent TakingItemsHandler for normal order processing
    when the user declines a suggestion.
    """

    def __init__(self, parent: "TakingItemsHandler") -> None:
        """Initialize with reference to parent handler.

        Args:
            parent: The TakingItemsHandler that owns this sub-handler.
        """
        self._parent = parent

    def handle_confirm_suggested_item(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user's response to 'Would you like to order one?' after item description.

        Called when user asked about an item (e.g., 'what's in the Lexington?'),
        bot described it and asked 'Would you like to order one?'.
        """
        suggested_item = order.pending_suggested_item
        user_lower = normalize_text(user_input)

        # Clear context first (will be processed either way)
        order.pending_suggested_item = None
        order.pending_field = None

        if is_affirmative(user_input) and suggested_item:
            logger.info(
                "User confirmed suggested item '%s' with response: '%s'",
                suggested_item, user_input
            )
            # Use existing add_menu_item to add the suggested item
            return self._parent.item_adder_handler.add_menu_item(
                suggested_item,
                quantity=1,
                order=order,
            )

        # Check for ordering-intent phrases that implicitly accept the suggestion
        # e.g., "I'll take one", "I'll try that", "sounds good, I'll have one"
        if suggested_item and _is_implicit_accept(user_lower):
            logger.info(
                "User implicitly confirmed suggested item '%s' with ordering intent: '%s'",
                suggested_item, user_input
            )
            return self._parent.item_adder_handler.add_menu_item(
                suggested_item,
                quantity=1,
                order=order,
            )

        # Not affirmative - process as normal taking_items input
        # User might be ordering something else or saying no
        logger.info(
            "User did not confirm suggested item '%s', processing as normal input: '%s'",
            suggested_item, user_input
        )
        return self._parent.handle_taking_items(user_input, order)

    def handle_confirm_ingredient_suggestion(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user's response to ingredient suggestion.

        Called when user ordered just a modifier (e.g., 'I want caramel syrup'),
        bot suggested items that can have it, and now user responds.

        Handles three cases:
        1. User says "yes" -> ask which item they want
        2. User directly picks an item (e.g., "iced latte") -> add item with ingredient
        3. User says "no" or something unrelated -> process without ingredient
        """
        suggestion = order.pending_ingredient_suggestion
        ingredient = suggestion.ingredient if suggestion else ""
        suggested_items = suggestion.suggested_items if suggestion else []

        # Clear suggestion context
        order.pending_ingredient_suggestion = None
        order.pending_field = None

        # Check if user explicitly declined
        user_lower = normalize_text(user_input)
        is_negative = user_lower in ("no", "nope", "nah", "no thanks", "never mind", "nevermind")

        if is_negative:
            logger.info(
                "User declined ingredient suggestion for '%s', processing without ingredient: '%s'",
                ingredient, user_input
            )
            return self._parent.handle_taking_items(user_input, order)

        if is_affirmative(user_input) and suggested_items:
            logger.info(
                "User confirmed ingredient suggestion for '%s', asking which item",
                ingredient
            )
            # Store the ingredient to apply when user picks an item
            order.pending_ingredient_to_apply = ingredient
            # Ask which item they'd like
            items_list = format_english_list(suggested_items, conjunction="or")
            return StateMachineResult(
                message=f"Great! Which would you like - {items_list}?",
                order=order,
            )

        # User might be directly picking an item (e.g., "iced latte" instead of "yes")
        # Set the ingredient to apply and process the input as a normal order
        logger.info(
            "User responded to ingredient suggestion for '%s' with '%s', applying ingredient to next item",
            ingredient, user_input
        )
        order.pending_ingredient_to_apply = ingredient
        return self._parent.handle_taking_items(user_input, order)

    def handle_confirm_dietary_followup(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user's response to dietary follow-up offer.

        Called when user asked about a specific item's dietary property (e.g., 'is the classic vegan?'),
        got a negative answer, and was offered to see dietary options instead.

        Handles two cases:
        1. User says "yes" -> show the dietary options
        2. User says "no" or something else -> process as normal taking_items input
        """
        followup = order.pending_dietary_followup
        dietary_type = followup.dietary_type if followup else ""
        category = followup.category if followup else None

        # Clear follow-up context
        order.pending_dietary_followup = None
        order.pending_field = None

        if is_affirmative(user_input) and dietary_type:
            logger.info(
                "User confirmed dietary follow-up for '%s', showing options",
                dietary_type
            )
            # Call the dietary handler to show the options
            return self._parent._dietary_inquiry_handler.handle_dietary_options_inquiry(
                dietary_type, order, category=category
            )

        # Not affirmative - process as normal taking_items input
        logger.info(
            "User did not confirm dietary follow-up for '%s', processing as normal input: '%s'",
            dietary_type, user_input
        )
        return self._parent.handle_taking_items(user_input, order)

    def handle_standalone_ingredient(
        self,
        parsed: "OpenInputResponse",
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle standalone ingredient order (e.g., "I want caramel syrup").

        When user orders just an ingredient/modifier without specifying an item,
        suggest items that can have this modifier.

        Returns:
            StateMachineResult if handled, None otherwise.
        """
        if not parsed.found_ingredient_without_item or not parsed.found_ingredient_name:
            return None

        ingredient = parsed.found_ingredient_name
        logger.info(
            "STANDALONE INGREDIENT: suggesting items for '%s'",
            ingredient
        )

        # Get item types that can have this ingredient as a modifier
        item_types = menu_cache.get_item_types_for_ingredient(ingredient)
        if not item_types:
            return None

        # Get sample menu items for those item types
        sample_items = []
        seen_names = set()
        for item_type_info in item_types[:3]:  # Limit to 3 item types
            item_type_slug = item_type_info.get("slug")
            if not item_type_slug:
                continue

            items = menu_cache.get_items_by_item_type(item_type_slug)
            for item in items[:2]:  # Get up to 2 items per type
                item_name = item.get("name")
                if item_name and item_name not in seen_names:
                    seen_names.add(item_name)
                    sample_items.append(item_name)
                    if len(sample_items) >= 4:  # Cap at 4 total items
                        break
            if len(sample_items) >= 4:
                break

        if not sample_items:
            return None

        # Format the suggestion message
        items_list = format_english_list(sample_items, conjunction="or")
        msg = f"We could make you a {items_list} with {ingredient}. Would you like one of those?"

        # Store context for follow-up confirmation
        order.pending_ingredient_suggestion = PendingIngredientSuggestion(
            ingredient=ingredient,
            suggested_items=sample_items,
        )
        order.pending_field = PendingField.CONFIRM_INGREDIENT_SUGGESTION

        return StateMachineResult(
            message=msg,
            order=order,
        )
