"""
Fallback Interceptor for Configuring Item Handler.

Handles fallback-level intercepts during item configuration:
- New menu item parse (without "and a" / "also" prefix)
- Off-topic request redirection
- "Show more" pagination during config
- Modifier inquiry routing

These run last as they handle edge cases that didn't match earlier checks.
"""

import logging
import re
from typing import TYPE_CHECKING

from .models import OrderTask, MenuItemTask
from .models.utilities import parse_pending_field
from .normalization import singularize, strip_ordering_prefix
from .pending_fields import PendingField
from .schemas import StateMachineResult
from .parsers.inquiry_patterns import MORE_MENU_ITEMS_PATTERNS
from .parsers.quantity_utils import extract_leading_quantity
from .config_input_validation import detect_modifier_inquiry, is_off_topic_request
from orderbot.cache import menu_cache

if TYPE_CHECKING:
    from .modifier_addition_handler import ModifierAdditionHandler
    from .taking_items_handler import TakingItemsHandler
    from .config_helper_handler import ConfigHelperHandler

logger = logging.getLogger(__name__)


class ConfigFallbackInterceptor:
    """Handles fallback intercepts during item configuration.

    Fallback intercepts include new menu item parsing, off-topic redirection,
    pagination, and modifier inquiry routing. They run after priority and
    modification intercepts.
    """

    def __init__(
        self,
        modifier_addition_handler: "ModifierAdditionHandler",
        config_helper_handler: "ConfigHelperHandler",
    ) -> None:
        """Initialize the fallback interceptor.

        Args:
            modifier_addition_handler: Handler for adding items during config.
            config_helper_handler: Handler for config helpers (questions).
        """
        self.modifier_addition_handler = modifier_addition_handler
        self.config_helper_handler = config_helper_handler
        # Set via property after TakingItemsHandler is created (to avoid circular dependency)
        self._taking_items_handler: "TakingItemsHandler | None" = None

    @property
    def taking_items_handler(self) -> "TakingItemsHandler | None":
        """Get the taking items handler."""
        return self._taking_items_handler

    @taking_items_handler.setter
    def taking_items_handler(self, handler: "TakingItemsHandler | None") -> None:
        """Set the taking items handler (called after initialization to avoid circular deps)."""
        self._taking_items_handler = handler

    def check_fallback_intercepts(
        self, user_input: str, item, order: OrderTask, is_valid_answer: bool
    ) -> StateMachineResult | None:
        """Check for fallback intercepts: new menu item parse, off-topic, modifier inquiry.

        These run last as they handle edge cases that didn't match earlier checks.

        Args:
            user_input: Raw user input string.
            item: The current item being configured.
            order: Current order state.
            is_valid_answer: Whether input could be a valid answer for the pending field.
        """
        # Fallback: if input isn't a valid answer and wasn't caught as a modifier,
        # try parsing as a new menu item (without requiring "and a"/"also" prefix).
        # Guard: only try if input starts with an article, quantity word, or ordering phrase.
        if not is_valid_answer and isinstance(item, MenuItemTask):
            stripped = user_input.strip()
            if re.match(r'^(?:a(?:n)?\s+|(?:\d+|two|three|four|five|six)\s+|(?:can|could)\s+i\s+(?:get|have)\s+)', stripped, re.IGNORECASE):
                # Don't treat as a new menu item if the non-quantity part is a known
                # modifier — it's likely an answer to the pending question.
                # Strip ordering prefix first (e.g., "can I have butter?" -> "butter"),
                # then try quantity extraction (e.g., "2 sugars" -> "sugars").
                prefix_stripped = strip_ordering_prefix(stripped).lower().rstrip("?!.,")
                _, remainder = extract_leading_quantity(prefix_stripped or stripped.lower())
                remainder = remainder.strip()
                remainder_is_modifier = False
                if remainder:
                    for variant in (remainder, singularize(remainder)):
                        if menu_cache.is_known_modifier(variant):
                            remainder_is_modifier = True
                            break
                if not remainder_is_modifier:
                    add_item_fallback = self.modifier_addition_handler.handle_add_item_during_config(
                        stripped, item, order, require_prefix=False
                    )
                    if add_item_fallback:
                        return add_item_fallback

        # Check for off-topic requests during configuration
        # If detected, politely redirect back to the current configuration question
        if not is_valid_answer and is_off_topic_request(user_input, order.pending_field):
            logger.info("OFF-TOPIC REQUEST: Detected during config: '%s'", user_input[:50])
            item_name = item.get_summary() if hasattr(item, 'get_summary') else "your item"
            current_question = self.config_helper_handler.get_current_config_question(order, item)
            if current_question:
                msg = f"Let's finish with your {item_name} first. {current_question}"
            else:
                msg = f"Let's finish with your {item_name} first."
            return StateMachineResult(message=msg, order=order)

        # Check for "show more" pagination requests (e.g., "what else?" after modifier inquiry)
        # Route to the menu pagination handler if we have active pagination state
        if (order.get_menu_pagination()
            and self._taking_items_handler
            and self._taking_items_handler.menu_inquiry_handler
            and any(p.search(user_input) for p in MORE_MENU_ITEMS_PATTERNS)):
            logger.info("PAGINATION during config: routing 'show more' to menu inquiry handler")
            return self._taking_items_handler.menu_inquiry_handler.handle_more_menu_items(order)

        # Check for modifier inquiries like "what toppings do you have?" that passed the off-topic check
        # Route to store_info_handler for proper pagination support
        # EXCEPT at customization_checkpoint
        modifier_category = detect_modifier_inquiry(user_input)
        pending_is_attr_config = order.pending_field and ":" in order.pending_field

        # During attr config, only route to modifier inquiry if it's a known modifier
        # category AND it's NOT the currently pending attribute (so the config handler
        # can show its own attribute options with proper pagination)
        if pending_is_attr_config and modifier_category:
            _, pending_attr_slug = parse_pending_field(order.pending_field)
            if modifier_category == pending_attr_slug:
                # Matches current attribute - let config handler show attribute options
                modifier_category = None
            else:
                resolved = menu_cache.get_modifier_category_by_alias(modifier_category)
                if not resolved:
                    modifier_category = None

        if (modifier_category
            and self._taking_items_handler
            and self._taking_items_handler.store_info_handler
            and self._taking_items_handler.store_info_handler.menu_options_handler
            and order.pending_field != PendingField.CUSTOMIZATION_CHECKPOINT):
            logger.info("MODIFIER INQUIRY during config: category='%s'", modifier_category)
            return self._taking_items_handler.store_info_handler.menu_options_handler.handle_modifier_inquiry(
                item.menu_item_type if isinstance(item, MenuItemTask) else None,
                modifier_category,  # category extracted from query
                order,
            )

        return None
