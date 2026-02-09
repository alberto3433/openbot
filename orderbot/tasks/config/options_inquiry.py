"""
Options Inquiry Handler for Menu Item Configuration.

Handles "what are my options?" type inquiries during item configuration,
including pagination for large option lists.

Extracted from menu_item_config_handler.py for better separation of concerns.
"""

import re
from typing import Callable, TYPE_CHECKING

from ..schemas import StateMachineResult
from ..parsers.constants import DEFAULT_PAGINATION_SIZE
from ..utils.text import format_english_list

if TYPE_CHECKING:
    from ..models import OrderTask, MenuItemTask
    from .context import ConfigHandlerContext

__all__ = ["OptionsInquiryHandler"]


class OptionsInquiryHandler:
    """
    Handles options inquiry during menu item configuration.

    Provides methods for:
    - Detecting "what options do you have?" type questions
    - Detecting inquiries about different attributes
    - Pagination for large option lists
    - Formatting option lists for display
    """

    def __init__(
        self,
        ctx: "ConfigHandlerContext | None" = None,
        # Legacy parameter for backward compatibility (deprecated)
        get_optional_attributes: Callable[[str], list[dict]] | None = None,
    ) -> None:
        """Initialize the options inquiry handler.

        Args:
            ctx: ConfigHandlerContext with shared dependencies. If provided,
                 individual callback parameters are ignored.

        Deprecated args (use ctx instead):
            get_optional_attributes: Callback to get optional attributes for an item type.
        """
        if ctx is not None:
            self._get_optional_attributes = ctx.get_optional_attributes
        else:
            # Legacy: individual parameter
            self._get_optional_attributes = get_optional_attributes

    def is_options_inquiry(self, user_input: str, topic: str | None = None) -> bool:
        """Check if user is asking about available options.

        Args:
            user_input: The user's input text
            topic: Optional topic word (e.g., "bread", "cheese") to check for
                   context-specific patterns like "what bread do you have"

        Returns:
            True if user is asking about options.
        """
        input_lower = user_input.lower().strip()

        # Generic option inquiry phrases (always match)
        inquiry_phrases = [
            "what do you have",
            "what kind do you have",
            "what kinds do you have",
            "what type do you have",
            "what types do you have",
            "what are my options",
            "what are the options",
            "what options",
            "options",
            "list them",
            "what choices",
            "what are my choices",
            "what are the choices",
            "what can i choose",
            "what can i get",
            "show me",
        ]
        if any(phrase in input_lower for phrase in inquiry_phrases):
            return True

        # Also catch "what kind of X do you have?" pattern
        # e.g., "what kind of bread do you have?", "what kinds of toppings do you have?"
        flexible_pattern = r"what\s+kind(s)?\s+of\s+\w+\s+do\s+you\s+have"
        if re.search(flexible_pattern, input_lower):
            return True

        # Context-aware patterns: check if user is asking about the specific topic
        # e.g., "what bread do you have" when we're asking about bread
        if topic:
            topic_lower = topic.lower().strip()
            # Handle plural forms (bread -> breads)
            topic_plural = topic_lower + "s" if not topic_lower.endswith("s") else topic_lower

            # Build patterns for this specific topic
            # "what bread do you have", "what breads do you have"
            # "what bread options", "what breads are there"
            # "what types of bread", "what kinds of bread"
            # "which bread", "which breads"
            topic_patterns = [
                # "what bread do you have" / "what breads do you have"
                rf"what\s+{re.escape(topic_lower)}s?\s+do\s+you\s+have",
                rf"what\s+{re.escape(topic_lower)}s?\s+(?:are\s+there|have\s+you\s+got|you\s+got)",
                # "what types/kinds of bread"
                rf"what\s+(?:types?|kinds?)\s+of\s+{re.escape(topic_lower)}",
                # "what bread options" / "bread options"
                rf"(?:what\s+)?{re.escape(topic_lower)}s?\s+(?:options?|choices?)",
                # "which bread" / "which breads"
                rf"which\s+{re.escape(topic_lower)}s?",
                # "any bread options" / "any breads"
                rf"(?:any|some)\s+{re.escape(topic_lower)}s?(?:\s+options?)?",
            ]

            for pattern in topic_patterns:
                if re.search(pattern, input_lower):
                    return True

            # Also check for partial topic matches for compound topics like "Tea Flavor"
            # "what flavors do you have?" should match when topic is "Tea Flavor"
            topic_words = topic_lower.replace("_", " ").split()
            for word in topic_words:
                if len(word) >= 4:  # Skip short words like "of", "the"
                    word_patterns = [
                        rf"what\s+{re.escape(word)}s?\s+do\s+you\s+have",
                        rf"what\s+{re.escape(word)}s?\s+(?:are\s+there|have\s+you\s+got)",
                        rf"which\s+{re.escape(word)}s?",
                    ]
                    for pattern in word_patterns:
                        if re.search(pattern, input_lower):
                            return True

        return False

    def detect_different_attribute_inquiry(
        self, user_input: str, item_type: str, current_attr_slug: str
    ) -> dict | None:
        """Detect if user is asking about a DIFFERENT attribute's options.

        When we're asking about one attribute (e.g., condiments) but the user asks
        "what toppings do you have?", we should switch to showing toppings options.

        Args:
            user_input: The user's input
            item_type: The item type slug (e.g., "bagel")
            current_attr_slug: The attribute we're currently asking about

        Returns:
            The different attribute config dict if found, None otherwise.
        """
        if not self._get_optional_attributes:
            return None

        input_lower = user_input.lower().strip()

        # Pattern to extract attribute name from "what X do you have?" type questions
        patterns = [
            r"what\s+(\w+)\s+do\s+you\s+have",
            r"what\s+(\w+)\s+options",
            r"what\s+kinds?\s+of\s+(\w+)",
            r"list\s+(?:the\s+)?(\w+)",
        ]

        # Get all optional attributes for this item type
        all_attrs = self._get_optional_attributes(item_type)

        for pattern in patterns:
            match = re.search(pattern, input_lower)
            if match:
                asked_attr = match.group(1).rstrip("s")  # Remove trailing 's' for matching

                # Check if this matches a different attribute
                for attr in all_attrs:
                    attr_slug = attr.get("slug", "")
                    attr_name = attr.get("display_name", "").lower()

                    # Skip the current attribute
                    if attr_slug == current_attr_slug:
                        continue

                    # Check if the asked attribute matches this one
                    if (asked_attr == attr_slug or
                        asked_attr == attr_slug.rstrip("s") or
                        asked_attr in attr_name or
                        attr_name.startswith(asked_attr)):
                        return attr

        return None

    def detect_options_inquiry_for_attribute(
        self, user_input: str, attributes: list[dict]
    ) -> dict | None:
        """Detect if user is asking 'what X do you have?' and return matching attribute.

        Used at customization checkpoint to detect options inquiries about ANY
        attribute, including ones that have already been partially answered.
        E.g., user adds "salt" then asks "what condiments do you have?" -
        condiments is no longer in unanswered list but we should still show options.

        Args:
            user_input: The user's input text
            attributes: List of attribute config dicts to check against

        Returns:
            The matching attribute config dict if found, None otherwise.
        """
        input_lower = user_input.lower().strip()

        # Patterns to extract attribute name from inquiry questions
        inquiry_patterns = [
            r"what\s+(?:kind\s+of\s+)?(\w+)\s+(?:do\s+you\s+have|options|are\s+there|are\s+available|available)",
            r"(?:show|list)\s+(?:me\s+)?(?:the\s+)?(\w+)(?:\s+options)?",
            r"what\s+(\w+)\s+can\s+i\s+(?:add|get|have)",
            r"what\s+(?:types?|kinds?)\s+of\s+(\w+)",
            # "what X choices do you have"
            r"what\s+(\w+)\s+choices?\s+(?:do\s+you\s+have|are\s+there|are\s+available)",
            # "what are the/my X options/choices"
            r"what\s+are\s+(?:the|my)\s+(\w+)\s+(?:options?|choices?)",
        ]

        for pattern in inquiry_patterns:
            match = re.search(pattern, input_lower)
            if match:
                topic = match.group(1).strip().rstrip("s")  # Remove trailing 's'

                for attr in attributes:
                    attr_slug = attr.get("slug", "")
                    attr_name = attr.get("display_name", "").lower()
                    attr_slug_normalized = attr_slug.rstrip("s")
                    # Handle _type suffix: "spread" should match "spread_type"
                    attr_slug_base = attr_slug.replace("_type", "")

                    # Match against slug, normalized slug, base (without _type), or display name
                    if (topic == attr_slug or
                        topic == attr_slug_normalized or
                        topic == attr_slug_base or
                        topic in attr_name or
                        attr_name.startswith(topic)):
                        return attr

        return None

    def is_show_more_request(self, user_input: str) -> bool:
        """Check if user is asking to see more options.

        Args:
            user_input: The user's input text

        Returns:
            True if user wants to see more options.
        """
        input_lower = user_input.lower().strip()
        show_more_phrases = [
            "what else",
            "any other",
            "more options",
            "other options",
            "what other",
            "anything else",
            "show more",
            "more",
            "next",
            "keep going",
            "continue",
            "different",
        ]
        return any(phrase in input_lower for phrase in show_more_phrases)

    def get_options_page(
        self, options: list[dict], page: int, page_size: int = DEFAULT_PAGINATION_SIZE
    ) -> tuple[list[dict], bool]:
        """Get a page of options.

        Args:
            options: Full list of options
            page: 0-indexed page number
            page_size: Number of options per page

        Returns:
            Tuple of (page_options, has_more).
        """
        start_idx = page * page_size
        end_idx = start_idx + page_size
        page_options = options[start_idx:end_idx]
        has_more = end_idx < len(options)
        return page_options, has_more

    def format_options_page(
        self, options: list[dict], is_first_page: bool, has_more: bool
    ) -> str:
        """Format a page of options for display.

        Args:
            options: List of option dicts with "display_name" key
            is_first_page: Whether this is the first page
            has_more: Whether there are more options after this page

        Returns:
            Formatted string for display.
        """
        names = [opt["display_name"] for opt in options]
        if len(names) == 0:
            return "That's all the options."
        options_str = format_english_list(names, conjunction="or")

        if is_first_page:
            if has_more:
                return f"We have {options_str}, and more. Would you like to hear the rest?"
            else:
                return f"We have {options_str}."
        else:
            if has_more:
                return f"We also have {options_str}, and more. Want to hear more?"
            else:
                return f"And finally, {options_str}. That's all of them."

    def handle_options_inquiry(
        self,
        item: "MenuItemTask",
        order: "OrderTask",
        attr: dict,
        options: list[dict],
        is_show_more: bool = False,
    ) -> StateMachineResult:
        """Handle user asking about available options with pagination.

        Args:
            item: The menu item being configured
            order: The order task
            attr: The attribute config dict
            options: List of available options
            is_show_more: Whether this is a "show more" request

        Returns:
            StateMachineResult with formatted options message.
        """
        if is_show_more:
            # Increment page
            order.config_options_page += 1
        else:
            # Start from first page
            order.config_options_page = 1

        page = order.config_options_page - 1  # 0-indexed for slicing
        page_options, has_more = self.get_options_page(
            options, page, DEFAULT_PAGINATION_SIZE
        )

        if not page_options:
            # No more options
            order.config_options_page = 0  # Reset
            return StateMachineResult(
                message="That's all the options. Which would you like?",
                order=order,
            )

        is_first_page = (page == 0)
        message = self.format_options_page(page_options, is_first_page, has_more)

        return StateMachineResult(message=message, order=order)
