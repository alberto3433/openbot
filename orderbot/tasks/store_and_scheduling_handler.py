"""
Store and Scheduling Handler for Order State Machine.

Handles store selection/change and scheduling (pickup time) logic.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .models import OrderTask
from .schemas import StateMachineResult
from .mixins import ContextMixin
from .parsers.time_parser import parse_time_expression

if TYPE_CHECKING:
    from .context import OrderContext

logger = logging.getLogger(__name__)


class StoreAndSchedulingHandler(ContextMixin):
    """Handles store selection/change and pickup time scheduling.

    Uses ContextMixin to receive ``_store_info`` from the per-request context.
    """

    def __init__(self) -> None:
        self._store_info: dict | None = None
        self._returning_customer: dict | None = None
        self._is_repeat_order: bool = False
        self._last_order_type: str | None = None

    def handle_store_change_request(
        self,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle a request to change the ordering store.

        Shows "from" as a linkified word. Clicking it triggers the paginated
        store list via handle_store_selection.
        """
        store_info = self._store_info or {}
        all_stores = store_info.get("all_stores", [])
        if not all_stores or len(all_stores) <= 1:
            msg = "There's only one store available right now."
            order.add_message("assistant", msg)
            return StateMachineResult(message=msg, order=order)

        order.pending_store_change = True
        order.pending_store_page = 0
        msg = "Which store would you like to order from?"
        order.add_message("assistant", msg)
        return StateMachineResult(
            message=msg,
            order=order,
            quick_replies=[{"label": "from", "value": "show stores"}],
        )

    def handle_store_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle the user's store selection after a pending_store_change prompt.

        Handles three input types:
        1. "show stores" (from clicking the "from" link) -- show first page
        2. "what else?" / "show more" -- show next page
        3. Store name or ID -- change the store

        Sets a transient ``_new_store_id`` key on the order so the message
        processor can update the session.
        """
        from .parsers.constants import DEFAULT_PAGINATION_SIZE

        store_info = self._store_info or {}
        all_stores = store_info.get("all_stores", [])
        text_lower = user_input.strip().lower()

        # --- Show stores / show more ---
        is_show = text_lower == "show stores"
        is_more = text_lower in ("what else?", "what else", "show more", "more")

        if is_show or is_more:
            if is_show:
                order.pending_store_page = 0
            page = order.pending_store_page
            page_size = DEFAULT_PAGINATION_SIZE
            start = page * page_size
            end = start + page_size
            page_stores = all_stores[start:end]
            has_more = end < len(all_stores)

            if not page_stores:
                order.pending_store_page = 0
                msg = "That's all the stores."
                order.pending_store_change = True
                return StateMachineResult(message=msg, order=order)

            # Build short names
            names = []
            for s in page_stores:
                raw = s.get("name", "")
                short = raw.split(" - ")[-1] if " - " in raw else raw
                names.append(short)

            # Format message
            if page == 0:
                if has_more:
                    names_str = ", ".join(names) + ", and more"
                    msg = f"We have {names_str} — want to see more?"
                else:
                    if len(names) > 1:
                        msg = "We have " + ", ".join(names[:-1]) + " or " + names[-1] + "."
                    else:
                        msg = f"We have {names[0]}."
            else:
                if has_more:
                    msg = "We also have " + ", ".join(names) + ", and more."
                else:
                    msg = "And finally, " + ", ".join(names) + ". That's all of them."

            # Build quick replies — each store name linkified + "more" if paginated
            # Use short name as value so it displays nicely as the user message
            qr = []
            for s, short in zip(page_stores, names):
                qr.append({"label": short, "value": short})
            if has_more:
                qr.append({"label": "more", "value": "what else?"})

            order.pending_store_page = page + 1
            order.pending_store_change = True
            return StateMachineResult(message=msg, order=order, quick_replies=qr)

        # --- Store selection by ID or name ---
        matched_store = None
        for s in all_stores:
            if s["store_id"] == user_input.strip():
                matched_store = s
                break
        if not matched_store:
            for s in all_stores:
                name_lower = s.get("name", "").lower()
                short_lower = (
                    name_lower.split(" - ")[-1] if " - " in name_lower else name_lower
                )
                if text_lower in name_lower or text_lower == short_lower:
                    matched_store = s
                    break

        if matched_store:
            order.pending_store_change = False
            order._new_store_id = matched_store["store_id"]
            was_confirmed = order.store_confirmed
            order.store_confirmed = True
            raw = matched_store.get("name", "")
            short = raw.split(" - ")[-1] if " - " in raw else raw
            if was_confirmed:
                msg = f"Switched to {short}. What can I get you?"
            else:
                msg = f"Great, ordering from {short}! What can I get you?"
            return StateMachineResult(message=msg, order=order)

        # No match — re-prompt with "from" link
        order.pending_store_change = True
        msg = "I didn't catch that store. Which store would you like to order from?"
        return StateMachineResult(
            message=msg,
            order=order,
            quick_replies=[{"label": "from", "value": "show stores"}],
        )

    def handle_scheduling_expression(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle time/scheduling expressions like 'pickup at 3pm'.

        Parses time expressions from user input and validates against
        store hours. Sets pickup_time on the delivery method task.

        Returns:
            StateMachineResult if a time expression was handled, None otherwise.
        """
        store_info = self._store_info or {}
        timezone_str = store_info.get("timezone", "America/New_York")

        parsed_time = parse_time_expression(user_input, timezone_str)
        if parsed_time is None:
            return None

        if parsed_time.is_asap:
            order.delivery_method.pickup_time = None
            return StateMachineResult(
                message="Got it, your order will be ready as soon as possible!",
                order=order,
            )

        # Validate against store hours
        from ..services.store_hours import validate_scheduled_time
        hours_config = store_info.get("hours_config")
        is_valid, error_msg = validate_scheduled_time(
            parsed_time.time_value, hours_config, timezone_str,
        )

        if not is_valid:
            return StateMachineResult(
                message=error_msg,
                order=order,
            )

        # Set the pickup time
        order.delivery_method.pickup_time = parsed_time.time_value.isoformat()

        # Format a friendly confirmation
        try:
            display_time = parsed_time.time_value.strftime("%I:%M %p").lstrip("0")
        except ValueError:
            display_time = parsed_time.time_value.strftime("%I:%M %p").lstrip("0")

        now = datetime.now(ZoneInfo(timezone_str))
        days_ahead = (parsed_time.time_value.date() - now.date()).days
        if days_ahead == 0:
            day_part = "today"
        elif days_ahead == 1:
            day_part = "tomorrow"
        else:
            day_part = parsed_time.time_value.strftime("%A")

        return StateMachineResult(
            message=f"Got it, your order will be scheduled for {day_part} at {display_time}. What can I get you?",
            order=order,
        )

    def handle_scheduling_change_request(
        self,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle a request to change pickup/delivery time.

        Returns a question with quick reply options for scheduling.
        """
        msg = "When would you like your order ready?"
        order.pending_scheduling = True
        order.add_message("assistant", msg)
        return StateMachineResult(
            message=msg,
            order=order,
            quick_replies=[
                {"label": "As soon as possible", "value": "as soon as possible"},
                {"label": "In 30 minutes", "value": "in 30 minutes"},
                {"label": "In 1 hour", "value": "in 1 hour"},
                {"label": "Choose a time", "value": "I'd like to choose a specific time"},
            ],
        )
