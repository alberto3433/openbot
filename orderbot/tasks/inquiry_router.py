"""
Inquiry Router Module.

Routes inquiry-type parsed responses to appropriate handlers.
Centralizes the routing logic for menu inquiries, store info, and other questions.

Extracted from taking_items_handler.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from .schemas import StateMachineResult
from .order_detection import get_dynamic_help_text

if TYPE_CHECKING:
    from .schemas import OpenInputResponse
    from .models import OrderTask
    from .menu_inquiry_handler import MenuInquiryHandler
    from .store_info_handler import StoreInfoHandler

logger = logging.getLogger(__name__)

__all__ = ["InquiryRouter"]


class InquiryRouter:
    """
    Router for inquiry-type parsed responses.

    Routes inquiries about prices, store info, menu, recommendations, etc.
    to their appropriate handlers.
    """

    def __init__(
        self,
        menu_inquiry_handler: "MenuInquiryHandler | None" = None,
        store_info_handler: "StoreInfoHandler | None" = None,
    ) -> None:
        """Initialize the inquiry router.

        Args:
            menu_inquiry_handler: Handler for menu-related inquiries.
            store_info_handler: Handler for store info inquiries.
        """
        self.menu_inquiry_handler = menu_inquiry_handler
        self.store_info_handler = store_info_handler

    def route_inquiry(
        self,
        parsed: "OpenInputResponse",
        order: "OrderTask",
        raw_user_input: str | None = None,
    ) -> StateMachineResult | None:
        """Route inquiry-type parsed responses to appropriate handlers.

        Checks all inquiry flags in the parsed response and routes to the
        appropriate handler. Returns None if no inquiry flag is set.

        Args:
            parsed: The parsed open input response.
            order: The current order task.
            raw_user_input: The raw user input string.

        Returns:
            StateMachineResult if an inquiry was handled, None otherwise.
        """
        # Handle price inquiries for specific items
        if parsed.asks_about_price and parsed.price_query_item:
            return self.menu_inquiry_handler.handle_price_inquiry(parsed.price_query_item, order)

        # Handle store info inquiries
        if parsed.asks_store_hours:
            return self.store_info_handler.handle_store_hours_inquiry(order)

        if parsed.asks_store_location:
            return self.store_info_handler.handle_store_location_inquiry(order)

        if parsed.asks_delivery_zone:
            return self.store_info_handler.handle_delivery_zone_inquiry(parsed.delivery_zone_query, order)

        if parsed.wants_customer_service:
            return self.store_info_handler.handle_customer_service_inquiry(order)

        if parsed.asks_recommendation:
            return self.store_info_handler.handle_recommendation_inquiry(
                match_type=parsed.recommendation_match_type,
                order=order,
                item_type_slug=parsed.recommendation_item_type_slug,
                menu_item_ids=parsed.recommendation_menu_item_ids,
                search_term=parsed.recommendation_search_term,
            )

        if parsed.asks_item_description:
            return self.menu_inquiry_handler.handle_item_description_inquiry(parsed.item_description_query, order)

        if parsed.asks_modifier_options:
            return self.store_info_handler.handle_modifier_inquiry(
                parsed.modifier_query_item, parsed.modifier_query_category, order
            )

        if parsed.menu_query:
            return self.menu_inquiry_handler.handle_menu_query(parsed.menu_query_type, order, show_prices=parsed.asks_about_price)

        if parsed.wants_more_menu_items:
            return self.menu_inquiry_handler.handle_more_menu_items(order, parsed.more_menu_category)

        if parsed.asking_signature_menu:
            return self.menu_inquiry_handler.handle_signature_menu_inquiry(parsed.signature_menu_type, order)

        if parsed.is_gratitude:
            return StateMachineResult(
                message="You're welcome! Anything else I can get for you?",
                order=order,
            )

        if parsed.is_help_request:
            # Generate help text dynamically from database item types
            help_text = get_dynamic_help_text()
            return StateMachineResult(
                message=help_text,
                order=order,
            )

        # No inquiry flag matched
        return None

    def route_category_clarification(
        self,
        parsed: "OpenInputResponse",
        order: "OrderTask",
    ) -> StateMachineResult | None:
        """Route category clarification requests.

        Args:
            parsed: The parsed open input response.
            order: The current order task.

        Returns:
            StateMachineResult if handled, None otherwise.
        """
        if parsed.needs_category_clarification:
            return self.menu_inquiry_handler.handle_category_clarification(
                parsed.needs_category_clarification, order
            )
        return None
