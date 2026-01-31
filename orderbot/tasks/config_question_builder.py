"""
Question Builder for Menu Item Configuration.

Handles building questions and messages during item configuration,
including ordinal calculations, first question prefixes, and
unavailable selection handling.

Extracted from menu_item_config_handler.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from orderbot.cache.base import pluralize
from .schemas import StateMachineResult, OrderPhase
from .utils.text import format_english_list, number_to_word

if TYPE_CHECKING:
    from .models import OrderTask, MenuItemTask

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
        order.set_phase(OrderPhase.CONFIGURING_ITEM)
        order.pending_item_id = item.id
        order.pending_field = f"{item.menu_item_type}:{attr_slug}"
        order.config_options_page = 0

        return StateMachineResult(message=question, order=order)

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
        from .message_builder import MessageBuilder
        from .models import MenuItemTask

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
        has_duplicates: bool, multi_count: int
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

        # Use DB's question_text if available for single-item orders
        if db_question and multi_count <= 1:
            return db_question

        if input_type == "boolean":
            if has_duplicates:
                return f"For the {ordinal} {item_ref}, would you like it {attr_name}?"
            elif multi_count > 1:
                return f"For the {item_ref}, would you like it {attr_name}?"
            else:
                return f"Would you like it {attr_name}?"
        else:
            if has_duplicates:
                return f"For the {ordinal} {item_ref}, what kind of {attr_name} would you like?"
            elif multi_count > 1:
                return f"For the {item_ref}, what kind of {attr_name} would you like?"
            else:
                return f"What kind of {attr_name} would you like?"

    def build_first_question_prefix(
        self, item: "MenuItemTask", order: "OrderTask", attr: dict,
        ordinal: str, item_num: int, has_duplicates: bool
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
            if item_num == 1:
                # First item acknowledgment
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
                    item_desc = f"the {item_display.lower()}"
                if input_type == "boolean":
                    return f"For {item_desc}, would you like that {attr_name}?"
                else:
                    return f"For {item_desc}, what kind of {attr_name} would you like?"
        else:
            # Single item - include special instructions if present
            if item.special_instructions:
                instructions_str = ", ".join(item.special_instructions)
                # Format: "Got it, for the Hot Coffee with room for cream."
                item_desc = f"{item_display} with {instructions_str}"
            else:
                item_desc = item_display
            return f"Got it, for the {item_desc}. "
