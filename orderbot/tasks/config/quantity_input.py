"""
Quantity Input Handler for Menu Item Configuration.

Handles quantity-based input for attributes like shots, syrups, etc.
Extracted from menu_item_config_handler.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING, Callable

from orderbot.cache import menu_cache
from orderbot.cache.base import pluralize

from ..models import OrderTask, MenuItemTask
from ..schemas import StateMachineResult
from ..response_utils import is_negative, is_affirmative
from ..parsers.quantity_utils import parse_numeric_input, MAX_MODIFIER_QUANTITY

if TYPE_CHECKING:
    from .context import ConfigHandlerContext

logger = logging.getLogger(__name__)


class QuantityInputHandler:
    """
    Handles quantity-based input for menu item configuration.

    Interprets user input as quantities for attributes like extra shots,
    syrups, etc. Supports:
    - Negative responses ("no", "none") as skip
    - Affirmative responses ("yes", "sure") as quantity=1
    - Numeric words ("double", "triple", "two") as that quantity
    - Digits ("2", "3") as that quantity
    """

    def __init__(
        self,
        ctx: "ConfigHandlerContext | None" = None,
        # Legacy parameter for backward compatibility (deprecated)
        advance_callback: Callable[
            [MenuItemTask, OrderTask, dict, str | None], StateMachineResult
        ] | None = None,
    ):
        """
        Initialize the quantity input handler.

        Args:
            ctx: ConfigHandlerContext with shared dependencies. If provided,
                 individual callback parameters are ignored.

        Deprecated args (use ctx instead):
            advance_callback: Callback to advance to next question after handling input.
        """
        if ctx is not None:
            self._advance_to_next_question = ctx.advance_to_next_question
        else:
            # Legacy: individual parameter
            self._advance_to_next_question = advance_callback

    def handle_quantity_input(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        options: list[dict],
    ) -> StateMachineResult:
        """Handle quantity-based input (e.g., shots).

        This input type interprets:
        - Negative responses ("no", "none") as skip
        - Affirmative responses ("yes", "sure") as quantity=1
        - Numeric words ("double", "triple", "two") as that quantity
        - Digits ("2", "3") as that quantity

        Uses the first available option for unit price and display name.
        Validates against max_selections from the attribute config.

        Args:
            user_input: User's input text
            item: Menu item being configured
            order: Current order
            attr: Attribute definition dict
            options: Available options for this attribute

        Returns:
            StateMachineResult with next question or error message
        """
        attr_slug = attr["slug"]
        user_lower = user_input.lower().strip()

        # Get unit option (first available option defines unit price and name)
        available_options = [opt for opt in options if opt.get("is_available", True)]
        if not available_options:
            logger.warning("No available options for quantity attribute %s", attr_slug)
            return self._advance_to_next_question(item, order, attr, None)

        unit_option = available_options[0]
        unit_price = unit_option.get("price") or unit_option.get("price_modifier") or 0.0
        unit_name = unit_option.get("display_name", attr["display_name"])
        unit_slug = unit_option.get("slug", attr_slug)

        # Get max quantity from attribute config
        max_qty = attr.get("max_selections") or MAX_MODIFIER_QUANTITY

        # Check for negative responses (skip)
        is_neg = is_negative(user_input)

        # Also check if input starts with a negative pattern followed by the attribute/unit name
        # e.g., "no shots" when asking about extra shots, "no syrup" when asking about syrup
        if not is_neg:
            unit_name_lower = unit_name.lower()
            attr_name_lower = attr["display_name"].lower()
            no_patterns = menu_cache.get_response_patterns("negative")
            for neg_pattern in no_patterns:
                # Check patterns like "no shots", "no extra shots", "none of that"
                if user_lower.startswith(neg_pattern + " "):
                    remainder = user_lower[len(neg_pattern) + 1:].strip()
                    # Check if remainder contains the unit name or attribute name
                    if (unit_name_lower in remainder or
                        attr_name_lower in remainder or
                        unit_slug in remainder or
                        attr_slug in remainder):
                        is_neg = True
                        break

        if is_neg:
            # For quantity attributes, "none" means 0 (not None/declined)
            # This distinguishes "no extra shots" (0) from unanswered
            item[attr_slug] = 0
            return self._advance_to_next_question(item, order, attr, None)

        # Check for affirmative responses (quantity=1)
        # Also treat "extra" or "extra <anything>" as affirmative (e.g., "extra shot" = 1 shot)
        is_extra_response = user_lower == "extra" or user_lower.startswith("extra ")
        if is_affirmative(user_input) or is_extra_response:
            quantity = 1
        else:
            # Try to parse numeric quantity
            parsed_qty = parse_numeric_input(user_input)
            if parsed_qty is None:
                # Couldn't parse - ask for clarification
                question = attr.get("question_text") or f"How many {attr['display_name'].lower()}?"
                return StateMachineResult(
                    message=f"Sorry, I didn't catch that. {question}",
                    order=order,
                )
            quantity = parsed_qty

        # Validate quantity
        if quantity < 1:
            return self._advance_to_next_question(item, order, attr, None)
        if quantity > max_qty:
            return StateMachineResult(
                message=f"Sorry, the maximum is {max_qty}. How many would you like?",
                order=order,
            )

        # Add selection with per-unit price
        # Pluralize the name when quantity > 1
        if quantity > 1:
            display_name = pluralize(unit_name)
        else:
            display_name = unit_name

        item.add_selection(
            unit_slug,
            attr_slug,
            quantity=quantity,
            price=unit_price,  # Per-unit price, not total
            display_name=display_name,
        )

        logger.info(
            "QUANTITY_INPUT: %s=%d (unit_price=$%.2f, total=$%.2f) from input '%s'",
            attr_slug, quantity, unit_price, quantity * unit_price, user_input
        )

        # Build acknowledgment with quantity prefix and pluralization
        if quantity > 1:
            plural_name = pluralize(unit_name)
            ack_text = f"{quantity} {plural_name}"
        else:
            ack_text = unit_name

        return self._advance_to_next_question(item, order, attr, ack_text)
