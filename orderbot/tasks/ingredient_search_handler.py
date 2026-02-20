"""
Ingredient Search Handler Module.

Handles ingredient search, category/desire extraction, category inquiry responses,
and unrecognized order attempt detection.

Extracted from taking_items_handler.py for better separation of concerns.
"""

import logging
import re
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache

from .models import OrderTask
from .models.pending_states import PendingIngredientSearch
from .pending_fields import PendingField
from .schemas import StateMachineResult
from .response_utils import is_affirmative
from .utils.text import format_english_list
from .order_detection import (
    looks_like_order_attempt,
    extract_order_item_name,
    looks_like_availability_question,
    extract_availability_item_name,
)

if TYPE_CHECKING:
    from .taking_items_handler import TakingItemsHandler

logger = logging.getLogger(__name__)


class IngredientSearchHandler:
    """Handles ingredient search, category extraction, and unrecognized item detection.

    Delegates back to the parent TakingItemsHandler for adding items and menu inquiry
    routing when needed.
    """

    # Pattern to strip desire/mood phrases that wrap a category reference
    # e.g., "I am in the mood for a sandwich" -> "sandwich"
    _DESIRE_MOOD_PATTERN = re.compile(
        r"^(?:i(?:'?m| am)\s+(?:in the mood for|craving|feeling like)|"
        r"how about|what about)\s+",
        re.IGNORECASE,
    )

    def __init__(self, parent: "TakingItemsHandler") -> None:
        """Initialize with reference to parent handler.

        Args:
            parent: The TakingItemsHandler that owns this sub-handler.
        """
        self._parent = parent

    def handle_ingredient_search(
        self,
        parsed: "OpenInputResponse",
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle ingredient-based menu search.

        When user says "chicken" or "something with bacon", show matching items.

        Returns:
            StateMachineResult if handled, None otherwise.
        """
        if not parsed.ingredient_search_matches:
            return None

        ingredient = parsed.ingredient_search_query or "that ingredient"
        matches = parsed.ingredient_search_matches
        logger.info(
            "INGREDIENT SEARCH: showing %d items with '%s'",
            len(matches), ingredient
        )

        # Build a nice response showing the matching items
        if len(matches) == 1:
            item = matches[0]
            item_name = item.get("name", "that item")
            desc = item.get("description", "")
            msg = f"For {ingredient}, we have the {item_name}"
            if desc:
                msg += f" ({desc})"
            msg += ". Would you like one?"

            # Store context so "yes" / "give me one" adds this item
            order.pending_suggested_item = item_name
            order.pending_field = PendingField.CONFIRM_SUGGESTED_ITEM
        else:
            # Multiple items - list them (cap at 6 for initial display)
            display_count = min(6, len(matches))
            item_names = [m.get("name", "item") for m in matches[:display_count]]
            has_more = len(matches) > display_count

            # Format the list properly
            if len(item_names) == 1:
                items_list = item_names[0]
            elif len(item_names) == 2:
                items_list = f"{item_names[0]} or {item_names[1]}"
            elif has_more:
                # "Item1, Item2, ..., Item6, and X more" (no "or" before "and")
                items_list = ", ".join(item_names)
                items_list += f", and {len(matches) - display_count} more"
            else:
                # "Item1, Item2, Item3, Item4, Item5, or Item6"
                items_list = format_english_list(item_names, conjunction="or")

            msg = f"For items with {ingredient}, we have: {items_list}. Which would you like?"

            # Store pagination state for "what else" follow-up
            if has_more:
                order.pending_ingredient_search = PendingIngredientSearch(
                    ingredient=ingredient,
                    matches=matches,
                    offset=display_count,
                )

        # Build quick replies for inline clickable text
        if len(matches) == 1:
            qr = [{"label": item_name, "value": item_name}]
        else:
            qr = [{"label": name, "value": name} for name in item_names]
            if has_more:
                qr.append({"label": f"{len(matches) - display_count} more", "value": "what else?"})
        return StateMachineResult(
            message=msg,
            order=order,
            quick_replies=qr,
        )

    def try_extract_category_from_input(
        self,
        raw_input: str | None,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Try to extract a category reference from desire/mood phrases.

        Handles inputs like "I am in the mood for a sandwich" by stripping
        desire/mood prefixes, ordering prefixes, and articles, then checking
        if the remainder is a category reference.

        Args:
            raw_input: The raw user input string.
            order: The current order task.

        Returns:
            StateMachineResult if a category was found and routed, None otherwise.
        """
        if not raw_input or not self._parent.menu_inquiry_handler:
            return None

        from .normalization import strip_ordering_prefix

        text = raw_input.strip()

        # Strip desire/mood phrases first
        text = self._DESIRE_MOOD_PATTERN.sub("", text).strip()

        # Also apply existing ordering prefix stripping ("I want", "can I get", etc.)
        text = strip_ordering_prefix(text)

        # Strip articles and trailing punctuation/please
        text = re.sub(r"^(?:a|an|some|the)\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*(?:please|thanks?)[.!?]*\s*$", "", text, flags=re.IGNORECASE)
        text = text.strip().rstrip("?.!")

        if not text:
            return None

        category_slug = menu_cache.is_category_reference(text)
        if not category_slug:
            return None

        logger.info(
            "Extracted category '%s' from desire/mood phrase: '%s'",
            category_slug, raw_input,
        )
        result = self._parent.menu_inquiry_handler.handle_category_clarification(category_slug, order)
        # handle_category_clarification returns str when a single item matched
        if isinstance(result, str):
            return self._parent.item_adder_handler.add_menu_item(result, 1, order)
        return result

    def handle_category_inquiry_response(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle affirmative response to category inquiry (e.g., 'Would you like to hear more?').

        When pending_field is CATEGORY_INQUIRY and user says 'yes', show more items
        from the display group pagination or list items from the pending category.

        Returns:
            StateMachineResult if handled, None otherwise.
        """
        logger.info(
            "CATEGORY_INQUIRY_RESPONSE: pending_field=%s, user_input='%s'",
            order.pending_field, user_input
        )

        if order.pending_field != PendingField.CATEGORY_INQUIRY:
            return None

        logger.info("CATEGORY_INQUIRY_RESPONSE: Matched CATEGORY_INQUIRY pending field")

        if not is_affirmative(user_input):
            # Not an affirmative response - clear pending state and continue ordering
            logger.info("CATEGORY_INQUIRY_RESPONSE: Not affirmative, clearing state")
            order.pending_field = None
            order.pending_config_queue = []
            order.menu_query_pagination = None
            return StateMachineResult(
                message="Sure! What can I get for you?",
                order=order,
            )

        logger.info("CATEGORY_INQUIRY_RESPONSE: Affirmative response detected")

        # Clear the pending field since we're handling this now
        order.pending_field = None

        # Check if there's display group pagination to continue
        pagination = order.get_menu_pagination()
        logger.info("CATEGORY_INQUIRY_RESPONSE: pagination=%s", pagination)

        if pagination and pagination.get("type") == "display_group_items":
            # Use menu_inquiry_handler to show more items
            logger.info("CATEGORY_INQUIRY_RESPONSE: Calling handle_more_menu_items")
            if self._parent.menu_inquiry_handler:
                try:
                    return self._parent.menu_inquiry_handler.handle_more_menu_items(order)
                except (ValueError, KeyError, TypeError, AttributeError) as e:
                    logger.error("CATEGORY_INQUIRY_RESPONSE: handle_more_menu_items failed: %s", e, exc_info=True)

        # Check if there's a pending category to list items from
        pending_category = None
        if order.pending_config_queue:
            pending_category = order.pending_config_queue[0]
            order.pending_config_queue = []
            logger.info("CATEGORY_INQUIRY_RESPONSE: pending_category=%s", pending_category)

        if pending_category and isinstance(pending_category, str):
            # List items from this category
            logger.info("CATEGORY_INQUIRY_RESPONSE: Calling handle_menu_query for %s", pending_category)
            if self._parent.menu_inquiry_handler:
                try:
                    return self._parent.menu_inquiry_handler.handle_menu_query(pending_category, order)
                except (ValueError, KeyError, TypeError, AttributeError) as e:
                    logger.error("CATEGORY_INQUIRY_RESPONSE: handle_menu_query failed: %s", e, exc_info=True)

        # Fallback: no pagination or category found
        logger.info("CATEGORY_INQUIRY_RESPONSE: Fallback - no pagination or category")
        return StateMachineResult(
            message="What would you like to order?",
            order=order,
        )

    def handle_unrecognized_order_attempt(
        self,
        parsed: "OpenInputResponse",
        order: OrderTask,
        raw_user_input: str | None,
    ) -> StateMachineResult | None:
        """Check if user is trying to order something we don't recognize.

        Handles inputs like "I want home fries", "can I have a croissant",
        or bare item names like "pepsi".

        Returns:
            StateMachineResult if an unrecognized item was detected, None otherwise.
        """
        if not parsed.unclear or not raw_user_input or not self._parent._unrecognized_handler:
            return None

        text_stripped = raw_user_input.strip()
        is_order_attempt = looks_like_order_attempt(raw_user_input)
        is_known_unrecognized = self._is_known_unrecognized_item(text_stripped)
        is_availability = looks_like_availability_question(raw_user_input)

        if not (is_order_attempt or is_known_unrecognized or is_availability):
            return None

        # Extract item name based on detected pattern type
        if is_order_attempt:
            item_name = extract_order_item_name(raw_user_input)
        elif is_availability:
            item_name = extract_availability_item_name(raw_user_input)
        else:
            item_name = text_stripped
        if not item_name:
            return None

        logger.info("Detected order attempt for unrecognized item: '%s'", item_name)
        message, category_for_followup, qr = self._parent._unrecognized_handler.get_not_found_response(
            item_name, order=order
        )
        if category_for_followup:
            # Track state so "yes" response can list items in this category
            order.pending_field = PendingField.CATEGORY_INQUIRY
            order.pending_config_queue = [category_for_followup]
        return StateMachineResult(
            message=message,
            order=order,
            quick_replies=qr or None,
        )

    def _is_known_unrecognized_item(self, text: str) -> bool:
        """Check if text matches a known unrecognized item pattern.

        This allows bare item names like "pepsi" to trigger the unrecognized
        item handler even without ordering language like "I want".

        Args:
            text: User input text (should be stripped)

        Returns:
            True if the text matches a curated unrecognized item suggestion.
        """
        unrecognized_handler = self._parent._unrecognized_handler
        if not unrecognized_handler or not unrecognized_handler._db_session:
            return False
        curated = unrecognized_handler._check_curated_suggestions(text.lower().strip())
        return curated is not None
