"""
Store Info Handler for Order State Machine.

This module handles store information inquiries including:
- Store hours and location
- Customer service escalation
- Delivery zone checking

Recommendation and menu options inquiries are delegated to:
- RecommendationHandler
- MenuOptionsInquiryHandler

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import OrderContext
    from .recommendation_handler import RecommendationHandler
    from .menu_options_inquiry_handler import MenuOptionsInquiryHandler

from .models import OrderTask
from .schemas import StateMachineResult
from .mixins import MenuDataMixin
from .utils.text import format_english_list, normalize_text

logger = logging.getLogger(__name__)


class StoreInfoHandler(MenuDataMixin):
    """
    Handles store information inquiries.

    Manages store hours, location, customer service, and delivery zone checks.
    Delegates recommendations and menu options inquiries to specialized handlers.
    """

    def __init__(
        self,
        menu_data: dict | None = None,
        recommendation_handler: "RecommendationHandler | None" = None,
        menu_options_handler: "MenuOptionsInquiryHandler | None" = None,
    ):
        """
        Initialize the store info handler.

        Args:
            menu_data: Menu data dictionary.
            recommendation_handler: Handler for recommendation inquiries.
            menu_options_handler: Handler for modifier/attribute inquiries.
        """
        self._menu_data = menu_data or {}
        self._store_info: dict | None = None
        self.recommendation_handler = recommendation_handler
        self.menu_options_handler = menu_options_handler

    def set_context(self, ctx: "OrderContext") -> None:
        """Set context from unified OrderContext."""
        self._store_info = ctx.store_info

    def handle_store_hours_inquiry(self, order: OrderTask) -> StateMachineResult:
        """Handle inquiry about store hours using three-tier logic.

        Tier 1: All stores have identical hours → single-line answer.
        Tier 2: Preferred store selected → show that store's hours directly.
        Tier 3: Hours vary, no preferred store → paginated inline list.

        Store status awareness:
        - Tier 2: If the selected store is temporarily closed, say so.
        - Tier 3: Only shows open stores (all_stores is pre-filtered).
        """
        from .parsers.constants import DEFAULT_PAGINATION_SIZE

        store_info = self._store_info or {}
        hours_display = store_info.get("hours")
        store_name = store_info.get("name")
        store_status = store_info.get("status")
        all_stores = store_info.get("all_stores", [])

        # --- Tier 2: Preferred store selected with hours ---
        if hours_display and store_name:
            if store_status == "closed":
                message = (
                    f"Our {store_name} location is temporarily closed. "
                    f"Normal hours are {hours_display}. Can I help you with anything else?"
                )
            else:
                message = f"Our {store_name} location is open {hours_display}. Can I help you with an order?"
            return StateMachineResult(message=message, order=order)

        # --- Gather stores that have hours data ---
        stores_with_hours = [s for s in all_stores if s.get("hours_display")]

        if not stores_with_hours:
            # No hours data available for any store
            if store_name:
                return StateMachineResult(
                    message=f"I don't have the hours for {store_name} right now. Is there anything else I can help you with?",
                    order=order,
                )
            return StateMachineResult(
                message="I don't have store hours available right now. Is there anything else I can help you with?",
                order=order,
            )

        # --- Tier 1: All stores have identical hours ---
        if self._all_stores_same_hours(stores_with_hours):
            hours_text = stores_with_hours[0]["hours_display"]
            message = f"All our locations are open {hours_text}. Can I help you with an order?"
            return StateMachineResult(message=message, order=order)

        # --- Tier 3: Hours vary, no preferred store → paginated list ---
        return self._build_store_hours_page(stores_with_hours, 0, order)

    def handle_store_hours_followup(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle follow-up input during store hours pagination.

        Returns a result for "show more" / "more" inputs to advance pagination.
        Returns None for unrelated input (clears pending state, falls through).
        """
        text_lower = user_input.strip().lower()
        is_more = text_lower in ("show more", "more", "more locations", "what else", "what else?")

        if not is_more:
            # Not a pagination request — clear pending state and fall through
            order.pending_store_hours_inquiry = False
            order.pending_store_hours_page = 0
            return None

        store_info = self._store_info or {}
        all_stores = store_info.get("all_stores", [])
        stores_with_hours = [s for s in all_stores if s.get("hours_display")]

        page = order.pending_store_hours_page
        return self._build_store_hours_page(stores_with_hours, page, order)

    @staticmethod
    def _all_stores_same_hours(stores: list[dict]) -> bool:
        """Check if all stores have identical raw hours JSONB dicts."""
        if len(stores) <= 1:
            return True
        first_hours = stores[0].get("hours")
        return all(s.get("hours") == first_hours for s in stores[1:])

    def _build_store_hours_page(
        self, stores: list[dict], page: int, order: OrderTask,
    ) -> StateMachineResult:
        """Build a paginated bullet list of store hours.

        Each line shows: "- StoreName: Mon-Fri 7:00 AM - 9:00 PM"
        Sets pending state for "show more" follow-up.
        """
        from .parsers.constants import DEFAULT_PAGINATION_SIZE

        page_size = DEFAULT_PAGINATION_SIZE
        start = page * page_size
        end = start + page_size
        page_stores = stores[start:end]
        has_more = end < len(stores)

        lines = ["Our hours vary by location:"]
        for s in page_stores:
            raw_name = s.get("name", "")
            short_name = raw_name.split(" - ")[-1] if " - " in raw_name else raw_name
            hours_text = s.get("hours_display", "hours not available")
            lines.append(f"- {short_name}: {hours_text}")

        message = "\n".join(lines)
        if not has_more:
            message += "\nCan I help you with an order?"

        # Set pagination state
        order.pending_store_hours_inquiry = has_more
        order.pending_store_hours_page = page + 1

        qr = None
        if has_more:
            qr = [{"label": "More locations", "value": "more"}]

        return StateMachineResult(message=message, order=order, quick_replies=qr)

    def handle_store_location_inquiry(self, order: OrderTask) -> StateMachineResult:
        """Handle inquiry about store location/address.

        Uses store_info from the process() call to get address.
        If store_info is not available (no store context), asks the user which store.
        """
        store_info = self._store_info or {}
        address = store_info.get("address")
        city = store_info.get("city")
        state = store_info.get("state")
        zip_code = store_info.get("zip_code")
        store_name = store_info.get("name")

        # Build full address if we have the parts
        if address:
            address_parts = [address]
            if city:
                city_state_zip = city
                if state:
                    city_state_zip += f", {state}"
                if zip_code:
                    city_state_zip += f" {zip_code}"
                address_parts.append(city_state_zip)
            full_address = ", ".join(address_parts)

            if store_name:
                message = f"The address for our {store_name} location is {full_address}. Can I help you with an order?"
            else:
                message = f"Our address is {full_address}. Can I help you with an order?"
            return StateMachineResult(message=message, order=order)

        # No address info available
        if store_name:
            # We know the store but don't have address configured
            return StateMachineResult(
                message=f"I don't have the address for {store_name} right now. Is there anything else I can help you with?",
                order=order,
            )

        # No store context at all - we can't determine which store
        return StateMachineResult(
            message="Which location would you like the address for?",
            order=order,
        )

    def handle_customer_service_inquiry(self, order: OrderTask) -> StateMachineResult:
        """Handle customer service escalation requests.

        When a customer says things like "I want to speak to a manager", "my order was wrong",
        or "I need a refund", provide them with the corporate email and store phone number.

        Args:
            order: Current order state (unchanged)

        Returns:
            StateMachineResult with contact information for customer service
        """
        store_info = self._store_info or {}
        store_phone = store_info.get("phone")
        store_name = store_info.get("name")

        # Get company info from menu_data
        company_info = self._menu_data.get("company_info", {})
        corporate_email = company_info.get("corporate_email")
        instagram_handle = company_info.get("instagram_handle")
        feedback_form_url = company_info.get("feedback_form_url")

        # Build the response message
        contact_parts = []

        if store_phone:
            if store_name:
                contact_parts.append(f"call our {store_name} location at {store_phone}")
            else:
                contact_parts.append(f"call us at {store_phone}")

        if corporate_email:
            contact_parts.append(f"email us at {corporate_email}")

        if feedback_form_url:
            contact_parts.append(f"submit feedback at {feedback_form_url}")

        if contact_parts:
            contact_str = ", or ".join(contact_parts)
            message = (
                f"I'm sorry to hear that. For customer service assistance, you can {contact_str}. "
                "Our team will be happy to help resolve any issues. Is there anything else I can help with?"
            )
        else:
            # Fallback if no contact info is available
            message = (
                "I'm sorry to hear that. Please reach out to our team for assistance with your concern. "
                "Is there anything else I can help with?"
            )

        return StateMachineResult(message=message, order=order)

    def handle_delivery_zone_inquiry(self, query: str | None, order: OrderTask) -> StateMachineResult:
        """Handle inquiry about whether we deliver to a specific location.

        Process:
        1. If query is a zip code (5 digits), check directly
        2. If query is a neighborhood, look up zip codes in NYC_NEIGHBORHOOD_ZIPS
        3. If it looks like an address, geocode it to get the zip code
        4. Do reverse lookup across all stores to find which deliver to that zip

        Args:
            query: The location they're asking about (zip, neighborhood, or address)
            order: Current order state
        """
        store_info = self._store_info or {}
        all_stores = store_info.get("all_stores", [])

        if not query:
            return StateMachineResult(
                message="What area would you like to check for delivery? You can give me a zip code or neighborhood.",
                order=order,
            )

        query_clean = normalize_text(query)

        # Check if it's a zip code (5 digits)
        zip_match = re.match(r'^(\d{5})$', query_clean)
        if zip_match:
            zip_code = zip_match.group(1)
            return self._check_delivery_for_zip(zip_code, all_stores, order)

        # Check if it's a known neighborhood (from database)
        neighborhood_zip_codes = self._menu_data.get("neighborhood_zip_codes", {})
        neighborhood_key = query_clean.replace("'", "'").strip()
        if neighborhood_key in neighborhood_zip_codes:
            zip_codes = neighborhood_zip_codes[neighborhood_key]
            # Check if any of these zip codes are in delivery zones
            return self._check_delivery_for_neighborhood(query, zip_codes, all_stores, order)

        # Try fuzzy matching for neighborhoods (common variations)
        for key in neighborhood_zip_codes:
            if key in query_clean or query_clean in key:
                zip_codes = neighborhood_zip_codes[key]
                return self._check_delivery_for_neighborhood(query, zip_codes, all_stores, order)

        # Check if it looks like an address (has numbers suggesting a street address)
        if re.search(r'\d+\s+\w+', query):
            # Try to geocode the address to get a zip code
            from ..services.address_service import geocode_to_zip
            zip_code = geocode_to_zip(query)
            if zip_code:
                logger.info("Geocoded '%s' to zip code: %s", query, zip_code)
                return self._check_delivery_for_zip(zip_code, all_stores, order, original_query=query)

        # Unknown location - ask for more specific info
        return StateMachineResult(
            message=f"I'm not sure about {query}. Could you give me a zip code or street address so I can check our delivery area?",
            order=order,
        )

    def _format_delivery_response(
        self, delivering_stores: list, location_display: str, order: OrderTask
    ) -> StateMachineResult:
        """Format delivery availability response for a location.

        Args:
            delivering_stores: List of stores that deliver to the location
            location_display: Human-readable location name for messages
            order: Current order state

        Returns:
            StateMachineResult with appropriate delivery message
        """
        if delivering_stores:
            if len(delivering_stores) == 1:
                store_name = delivering_stores[0].get("name", "our store")
                message = f"Yes! {store_name} delivers to {location_display}. Would you like to place a delivery order?"
            else:
                store_names = [s.get("name", "Store") for s in delivering_stores]
                stores_str = format_english_list(store_names)
                message = f"Yes! We can deliver to {location_display} from {stores_str}. Would you like to place a delivery order?"
            qr = [{"label": name, "value": name} for name in store_names] if len(delivering_stores) > 1 else None
            return StateMachineResult(message=message, order=order, quick_replies=qr)

        # No stores deliver to this location
        return StateMachineResult(
            message=f"Unfortunately, we don't currently deliver to {location_display}. You're welcome to place a pickup order instead. Would you like to do that?",
            order=order,
        )

    def _check_delivery_for_zip(
        self, zip_code: str, all_stores: list, order: OrderTask, original_query: str | None = None
    ) -> StateMachineResult:
        """Check which stores deliver to a specific zip code."""
        delivering_stores = []
        location_display = original_query or zip_code

        for store in all_stores:
            delivery_zips = store.get("delivery_zip_codes", [])
            if zip_code in delivery_zips:
                delivering_stores.append(store)

        return self._format_delivery_response(delivering_stores, location_display, order)

    def _check_delivery_for_neighborhood(
        self, neighborhood: str, zip_codes: list, all_stores: list, order: OrderTask
    ) -> StateMachineResult:
        """Check which stores deliver to any of the neighborhood's zip codes."""
        delivering_stores = []

        for store in all_stores:
            delivery_zips = store.get("delivery_zip_codes", [])
            if any(z in delivery_zips for z in zip_codes):
                delivering_stores.append(store)

        return self._format_delivery_response(delivering_stores, neighborhood, order)

