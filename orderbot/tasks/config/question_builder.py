"""
Question Builder for Menu Item Configuration.

Handles building questions and messages during item configuration,
including ordinal calculations, first question prefixes, and
unavailable selection handling.

Extracted from menu_item_config_handler.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache
from orderbot.cache.base import pluralize
from ..models.pending_states import PendingUnmatchedPagination
from ..models.utilities import is_name_forming_category
from ..schemas import StateMachineResult
from ..utils.text import format_english_list, number_to_word

if TYPE_CHECKING:
    from ..models import OrderTask, MenuItemTask

logger = logging.getLogger(__name__)

__all__ = ["QuestionBuilder"]


class QuestionBuilder:
    """
    Builds questions and messages for menu item configuration.

    Provides methods for:
    - Handling unavailable selection messages
    - Calculating item ordinal positions
    - Building base questions based on input type
    - Building first question prefixes/acknowledgments
    """

    def handle_unavailable_selection(
        self, item: "MenuItemTask", order: "OrderTask", attr: dict
    ) -> StateMachineResult | None:
        """
        Check if user tried to select an unavailable option for this attribute.
        If so, generate a helpful message showing what's available.

        Returns StateMachineResult if unavailable selection was handled, None otherwise.
        """
        attr_slug = attr.get("slug", "")
        unavail = item.unavailable_selections.get(attr_slug)
        if not unavail:
            return None

        attempted = unavail.get("attempted_display", unavail.get("attempted_slug", "that"))
        options = attr.get("options", [])

        # Get available options (filter out unavailable ones)
        available = [
            o.get("display_name", o.get("slug", ""))
            for o in options
            if o.get("is_available", True)
        ]

        # Build helpful message
        if len(available) <= 4:
            opts_str = format_english_list(available, conjunction="or")
        else:
            # Too many options - just name the attribute
            opts_str = None

        if opts_str:
            question = f"We don't have {attempted} - we have {opts_str}. Which would you like?"
        else:
            attr_name_lower = attr.get("display_name", attr_slug).lower()
            question = f"We don't have {attempted}. Which {attr_name_lower} would you like?"

        # Clear so we don't repeat this message
        del item.unavailable_selections[attr_slug]

        # Set up order state for receiving the answer
        order.setup_pending_config(item.id, f"{item.menu_item_type}:{attr_slug}")

        # Build quick replies for inline clickable text
        from ..handler_utils import build_quick_replies
        qr = build_quick_replies(available) if available else None
        return StateMachineResult(message=question, order=order, quick_replies=qr)

    def build_unrecognized_note(self, item: "MenuItemTask") -> str | None:
        """Build a non-interactive note about unrecognized ingredients.

        Pops ALL unrecognized ingredients from the item and builds a combined
        note string. This is prepended to the next config question rather than
        creating a separate interactive step.

        Args:
            item: The menu item to check for unrecognized ingredients.

        Returns:
            A note string like "Sorry, we don't carry Pepperoni." or None.
        """
        if not item.unrecognized_ingredients:
            return None

        parts = []
        while item.unrecognized_ingredients:
            entry = item.unrecognized_ingredients.pop(0)
            display_name = entry.get("display_name", entry.get("token", "that"))
            alternatives = entry.get("alternatives", [])
            alt_names = [a.get("name", "") for a in alternatives if a.get("name")]

            if alt_names:
                alt_str = format_english_list(alt_names, conjunction="or")
                parts.append(
                    f"we don't carry {display_name} (we have {alt_str})"
                )
            else:
                parts.append(f"we don't carry {display_name}")

        note = "Sorry, " + "; ".join(parts) + "."
        return note

    def handle_inapplicable_attributes(self, item: "MenuItemTask") -> str | None:
        """Check if item has inapplicable attribute words to notify the user about.

        Pops the first entry from the list and generates a note like
        "Heads up, the Tuna Salad Sandwich only comes in one size."

        Returns a note string to prepend to the question, or None if nothing to report.
        """
        if not item.inapplicable_attributes:
            return None

        entry = item.inapplicable_attributes.pop(0)
        attr_slug = entry.get("attribute_slug", "")
        item_name = item.get_display_name()

        # Get a human-readable attribute name
        attr_display = menu_cache.get_attribute_display_name(attr_slug)

        # Build the note
        if attr_slug == "size":
            return f"Heads up, the {item_name} only comes in one size."
        else:
            return f"Heads up, the {item_name} doesn't have {attr_display.lower()} options."

    def calculate_item_ordinal(
        self, item: "MenuItemTask", order: "OrderTask"
    ) -> tuple[str, int, bool]:
        """
        Calculate ordinal position of this item among same-type items.

        Returns:
            tuple of (ordinal_word, item_number, has_duplicates)
            - ordinal_word: "first", "second", etc.
            - item_number: 1-based position
            - has_duplicates: True if item name appears multiple times
        """
        from ..message_builder import MessageBuilder
        from ..models import MenuItemTask

        config_names = order.multi_item_config_names or []
        multi_count = len(config_names) if config_names else 1

        item_display = item.get_display_name()
        # Does this item's name appear more than once in the config list?
        item_name_count = sum(1 for n in config_names if n == item_display)
        has_duplicates = item_name_count > 1

        ordinal = "first"
        item_num = 1

        if multi_count > 1:
            # Find all items of the same type
            same_type_items = [
                it for it in order.items.items
                if isinstance(it, MenuItemTask) and it.menu_item_type == item.menu_item_type
            ]
            # Find position of current item
            item_num = next(
                (i + 1 for i, it in enumerate(same_type_items) if it.id == item.id),
                1
            )
            ordinal = MessageBuilder.get_ordinal(item_num)

        return ordinal, item_num, has_duplicates

    def build_base_question(
        self, attr: dict, item_ref: str, ordinal: str,
        has_duplicates: bool, multi_count: int,
    ) -> str:
        """
        Build the base question text based on input type and item context.

        Args:
            attr: Attribute configuration dict
            item_ref: Item display name (lowercase)
            ordinal: "first", "second", etc.
            has_duplicates: True if same item appears multiple times
            multi_count: Total number of items being configured
        """
        input_type = attr.get("input_type", "single_select")
        attr_name = attr["display_name"].lower()
        db_question = attr.get("question_text")

        # Use DB's question_text if available, with appropriate prefix for multi-item orders
        if db_question:
            if multi_count <= 1:
                return db_question
            elif has_duplicates:
                return f"For the {ordinal} {item_ref}, {db_question[0].lower()}{db_question[1:]}"
            else:
                return f"For the {item_ref}, {db_question[0].lower()}{db_question[1:]}"

        # Fallback to generic templates if no DB question
        if input_type == "boolean":
            if has_duplicates:
                return f"For the {ordinal} {item_ref}, would you like it {attr_name}?"
            elif multi_count > 1:
                return f"For the {item_ref}, would you like it {attr_name}?"
            else:
                return f"Would you like it {attr_name}?"
        elif input_type == "quantity":
            if has_duplicates:
                return f"For the {ordinal} {item_ref}, how many {attr_name} would you like?"
            elif multi_count > 1:
                return f"For the {item_ref}, how many {attr_name} would you like?"
            else:
                return f"How many {attr_name} would you like?"
        else:
            if has_duplicates:
                return f"For the {ordinal} {item_ref}, what kind of {attr_name} would you like?"
            elif multi_count > 1:
                return f"For the {item_ref}, what kind of {attr_name} would you like?"
            else:
                return f"What kind of {attr_name} would you like?"

    def build_first_question_prefix(
        self, item: "MenuItemTask", order: "OrderTask", attr: dict,
        ordinal: str, item_num: int, has_duplicates: bool,
    ) -> str | None:
        """
        Build acknowledgment prefix for the first question of each item.

        Returns the prefix string (e.g., "Got it, two Plain Bagels. ") or None
        if no prefix is needed (for subsequent questions, not first).
        """
        from collections import Counter

        config_names = order.multi_item_config_names or []
        multi_count = len(config_names) if config_names else 1
        item_display = item.get_display_name()
        input_type = attr.get("input_type", "single_select")
        attr_name = attr["display_name"].lower()

        if multi_count > 1:
            if item_num == 1 and has_duplicates:
                # First item with duplicates: ordinal format with "Got it" prefix
                # e.g. "Got it, for the first Bagel. What kind of bagel?"
                item_desc = f"the {ordinal} {item_display}"
                db_question = attr.get("question_text")
                if db_question:
                    return f"Got it, for {item_desc}. {db_question}"
                elif input_type == "boolean":
                    return f"Got it, for {item_desc}. Would you like it {attr_name}?"
                elif input_type == "quantity":
                    return f"Got it, for {item_desc}. How many {attr_name} would you like?"
                else:
                    return f"Got it, for {item_desc}. What kind of {attr_name} would you like?"
            elif item_num == 1:
                # First item without duplicates: summary acknowledgment
                all_same_name = len(set(config_names)) == 1

                if all_same_name:
                    # All identical: "Got it, two Plain Bagels."
                    quantity_word = number_to_word(multi_count)
                    item_name = pluralize(item_display)
                    item_desc = f"{quantity_word} {item_name}"
                else:
                    # Mixed items: collapse duplicates
                    name_counts = Counter(config_names)
                    desc_parts = []
                    for cname, ccount in name_counts.items():
                        if ccount > 1:
                            qty_word = number_to_word(ccount)
                            desc_parts.append(f"{qty_word} {pluralize(cname)}")
                        else:
                            # Include special instructions for this item
                            matching_item = next(
                                (it for it in order.items.items
                                 if it.get_display_name() == cname and it.special_instructions),
                                None
                            )
                            if matching_item and matching_item.special_instructions:
                                instructions_str = ", ".join(matching_item.special_instructions)
                                desc_parts.append(f"{instructions_str} {cname}")
                            else:
                                desc_parts.append(cname)
                    item_desc = format_english_list(desc_parts)
                return f"Got it, {item_desc}. "
            else:
                # Subsequent items - build a replacement question
                if has_duplicates:
                    item_desc = f"the {ordinal} {item_display}"
                else:
                    item_desc = f"the {item_display}"
                db_question = attr.get("question_text")
                if db_question:
                    return f"For {item_desc}, {db_question[0].lower()}{db_question[1:]}"
                elif input_type == "boolean":
                    return f"For {item_desc}, would you like that {attr_name}?"
                elif input_type == "quantity":
                    return f"For {item_desc}, how many {attr_name} would you like?"
                else:
                    return f"For {item_desc}, what kind of {attr_name} would you like?"
        else:
            # Single item - include selections and special instructions
            parts = []
            instructions = item.special_instructions or []
            instructions_text = " ".join(instructions).lower()
            instructions_words = set(instructions_text.split()) if instructions_text else set()

            # Add non-name-forming selections not already covered by special instructions
            for sel in item.selections:
                slug = sel.get("slug", "")
                if slug in ("no", "_declined"):
                    continue
                if sel.get("_skip_display"):
                    continue
                category = sel.get("category", "")
                if is_name_forming_category(category):
                    continue
                if sel.get("is_default"):
                    continue
                display = sel.get("display_name", "")
                if not display:
                    continue
                # Skip if any significant word overlaps with special instructions
                if instructions_words:
                    display_words = {w for w in display.lower().split() if len(w) > 2}
                    if display_words and any(w in instructions_words for w in display_words):
                        continue
                parts.append(display)

            # Add special instructions
            parts.extend(instructions)

            if parts:
                parts_str = format_english_list(parts)
                item_desc = f"{item_display} with {parts_str}"
            else:
                item_desc = item_display
            return f"Got it, for the {item_desc}. "

    def handle_unmatched_selection(
        self, item: "MenuItemTask", order: "OrderTask", attr: dict
    ) -> StateMachineResult | None:
        """
        Check if user mentioned tokens that don't match any option for this attribute.
        If so, show a helpful message with available options (paginated if needed).

        Returns StateMachineResult if unmatched selection was handled, None otherwise.
        """
        attr_slug = attr.get("slug", "")
        unmatched = item.unmatched_selections.get(attr_slug)
        if not unmatched:
            return None

        tokens = unmatched.get("tokens", [])
        if not tokens:
            return None

        unmatched_text = format_english_list(tokens, conjunction="or")
        options = attr.get("options", [])

        # Get available options (filter out unavailable ones)
        available = [
            opt for opt in options
            if opt.get("is_available", True)
        ]

        # Clear so we don't repeat this message
        del item.unmatched_selections[attr_slug]

        if not available:
            # No options available - just inform and continue
            return None

        # Store pagination state
        order.pending_unmatched_pagination = PendingUnmatchedPagination(
            unmatched_text=unmatched_text,
            attr_slug=attr_slug,
            available_options=available,
            page=0,
            item_id=item.id,
        )

        # Build first page message
        return self._build_unmatched_page_message(order, is_first=True)

    def _build_unmatched_page_message(
        self, order: "OrderTask", is_first: bool = True, ack_text: str | None = None
    ) -> StateMachineResult:
        """Build a paginated message showing available options for unmatched tokens.

        Args:
            order: The order containing pagination state
            is_first: Whether this is the first page (includes "We don't have X" prefix)
            ack_text: Optional acknowledgment text to prepend (e.g., "Got it, oat milk.")
        """
        from ..parsers.constants import DEFAULT_PAGINATION_SIZE

        pagination = order.pending_unmatched_pagination
        if not pagination:
            # Should not happen, but handle gracefully
            order.clear_pending()
            return StateMachineResult(
                message="Let me know if you'd like anything else.",
                order=order,
            )

        unmatched_text = pagination.unmatched_text
        available = pagination.available_options
        page = pagination.page

        page_size = DEFAULT_PAGINATION_SIZE
        start_idx = page * page_size
        end_idx = start_idx + page_size
        page_options = available[start_idx:end_idx]
        has_more = end_idx < len(available)

        names = [opt.get("display_name", opt.get("slug", "")) for opt in page_options]
        options_str = format_english_list(names, conjunction="and" if has_more else "or")

        # Build message based on page position
        prefix = f"Got it, {ack_text}. " if ack_text else ""

        if is_first:
            # First page: "We don't have honey. We have sugar, raw sugar, Splenda..."
            if has_more:
                message = (
                    f"{prefix}We don't have {unmatched_text}. "
                    f"We have {options_str}... and more — would you like to see more options?"
                )
            else:
                message = (
                    f"{prefix}We don't have {unmatched_text}. "
                    f"We have {options_str}. Would you like any of these?"
                )
        else:
            # Subsequent pages
            if has_more:
                message = f"We also have {options_str}... and more — would you like to see more?"
            else:
                message = f"And finally, {options_str}. Would you like any of these?"

        # Build quick replies for inline clickable text
        qr = [{"label": name, "value": name} for name in names]
        if has_more:
            qr.append({"label": "more", "value": "what else?"})

        return StateMachineResult(message=message, order=order, quick_replies=qr)

    def advance_unmatched_pagination(self, order: "OrderTask") -> StateMachineResult:
        """Advance to the next page of unmatched options.

        Returns the message for the next page.
        """
        pagination = order.pending_unmatched_pagination
        if not pagination:
            order.clear_pending()
            return StateMachineResult(
                message="Let me know what you'd like.",
                order=order,
            )

        # Increment page
        pagination.page += 1
        order.pending_unmatched_pagination = pagination

        return self._build_unmatched_page_message(order, is_first=False)

    def clear_unmatched_pagination(self, order: "OrderTask") -> None:
        """Clear the unmatched pagination state."""
        order.pending_unmatched_pagination = None
