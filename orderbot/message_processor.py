"""
Unified message processing for all chat endpoints.

This module provides a single MessageProcessor class that handles the complete
lifecycle of processing a user message:
- Session management (load/save)
- Customer lookup
- State machine processing
- Order persistence
- Analytics logging
- Payment URL creation

All endpoints (web chat, streaming, VAPI voice) use this class, with only
request/response format handling done in the endpoint itself.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .db.models import SessionAnalytics, Company
from .cache import menu_cache
from .schemas.enums import OrderStatus
from .tasks.state_machine_adapter import process_message_with_state_machine
from .services.customer_service import find_or_create_customer, lookup_customer_by_phone
from .services.payment_service import create_payment_url, send_in_store_receipt
from .services.store_service import build_store_info, get_company

logger = logging.getLogger(__name__)

__all__ = ["MessageProcessor", "ProcessingContext", "ProcessingResult", "SessionNotFoundError"]


class SessionNotFoundError(ValueError):
    """Raised when a chat session cannot be found by ID."""
    pass


# -----------------------------------------------------------------------------
# Data Classes
# -----------------------------------------------------------------------------

@dataclass
class ProcessingContext:
    """Input context for message processing."""
    user_message: str
    session_id: str

    # Optional context
    caller_id: str | None = None
    store_id: str | None = None
    item_id: str | None = None
    add_item: bool = False

    # Pre-loaded session (optional - if not provided, will be loaded)
    session: dict[str, Any] | None = None


@dataclass
class ProcessingResult:
    """Output from message processing."""
    reply: str
    order_state: dict[str, Any]
    actions: list[dict[str, Any]]
    quick_replies: list[dict[str, str]] | None = None

    # Session data for response
    history: list[dict[str, str]] = field(default_factory=list)

    # Payment
    payment_url: str | None = None

    # Status flags
    order_persisted: bool = False
    analytics_logged: bool = False

    # The full session (for endpoints that need it)
    session: dict[str, Any] = field(default_factory=dict)


# -----------------------------------------------------------------------------
# MessageProcessor Class
# -----------------------------------------------------------------------------

class MessageProcessor:
    """
    Unified message processing for all endpoints.

    Handles the complete lifecycle:
    - Session management
    - Customer lookup
    - State machine processing
    - Order persistence
    - Analytics logging
    - Payment emails

    Usage:
        processor = MessageProcessor(db)
        result = processor.process(ProcessingContext(
            user_message="I'd like a bagel",
            session_id="abc123",
            caller_id="+15551234567",
        ))
    """

    def __init__(self, db: Session):
        self.db = db
        self._company: Company | None = None

    def process(self, ctx: ProcessingContext) -> ProcessingResult:
        """
        Process a user message and return the result.

        This is the main entry point that orchestrates all processing steps.
        """
        # 1. Load or create session
        session = ctx.session or self._get_or_create_session(ctx.session_id)
        if session is None:
            raise SessionNotFoundError(f"Session not found: {ctx.session_id}")

        # Extract session data
        history = session.get("history", [])
        order_state = session.get("order", {})
        returning_customer = session.get("returning_customer")
        session_store_id = ctx.store_id or session.get("store_id")
        session_caller_id = ctx.caller_id or session.get("caller_id")

        # 2. Re-lookup returning customer if needed
        if not returning_customer and session_caller_id:
            returning_customer = self._lookup_customer_by_phone(session_caller_id)
            if returning_customer:
                session["returning_customer"] = returning_customer
                logger.info("Re-looked up returning customer: %s", returning_customer.get("name"))

        # 3. Get cached menu index and store context
        menu_index = menu_cache.get_menu_index(session_store_id)

        # Use cached store_info from session if available, otherwise query
        store_info = session.get("store_info")
        if not store_info:
            store_info = self._build_store_info(session_store_id)

        # 4. Process through state machine
        reply, updated_order_state, actions, quick_replies = process_message_with_state_machine(
            user_message=ctx.user_message,
            order_state_dict=order_state,
            history=history,
            session_id=ctx.session_id,
            menu_data=menu_index,
            store_info=store_info,
            returning_customer=returning_customer,
            db_session=self.db,
            item_id=ctx.item_id,
            add_item=ctx.add_item,
        )

        # 4b. Handle store change signal from state machine
        new_store_id = updated_order_state.get("_new_store_id")
        if new_store_id:
            del updated_order_state["_new_store_id"]
            if new_store_id != session_store_id:
                session["store_id"] = new_store_id
                session_store_id = new_store_id
                new_store_info = self._build_store_info(new_store_id)
                session["store_info"] = new_store_info
                store_info = new_store_info
                # Recalculate taxes with new store's rates
                from .services.tax_utils import calculate_order_total
                subtotal = updated_order_state.get("checkout_state", {}).get("subtotal", 0)
                if subtotal > 0:
                    is_delivery = updated_order_state.get("order_type") == "delivery"
                    totals = calculate_order_total(subtotal, new_store_info, is_delivery)
                    cs = updated_order_state.get("checkout_state", {})
                    cs.update(totals)
                    updated_order_state["checkout_state"] = cs
                # Update store dict in order state for frontend
                raw_name = new_store_info.get("name", "")
                short = raw_name.split(" - ")[-1] if " - " in raw_name else raw_name
                updated_order_state["store"] = {
                    "store_id": new_store_id,
                    "name": raw_name,
                    "short_name": short,
                }
                # Persist preferred store on the customer record
                self._update_preferred_store(session, new_store_id)

        # 5. Update history (capped to last N messages to bound serialization cost)
        history.append({"role": "user", "content": ctx.user_message})
        history.append({"role": "assistant", "content": reply})
        _MAX_HISTORY_MESSAGES = 40  # 20 exchanges (user + assistant each)
        if len(history) > _MAX_HISTORY_MESSAGES:
            history[:] = history[-_MAX_HISTORY_MESSAGES:]

        # 6. Extract customer info for persistence
        customer_name = updated_order_state.get("customer", {}).get("name")
        customer_phone = updated_order_state.get("customer", {}).get("phone") or session_caller_id
        customer_email = updated_order_state.get("customer", {}).get("email")

        # Use caller_id as phone if not explicitly provided
        if session_caller_id and not updated_order_state.get("customer", {}).get("phone"):
            updated_order_state.setdefault("customer", {})
            updated_order_state["customer"]["phone"] = session_caller_id

        # 6b. Sync customer record to DB as soon as name + contact is available
        self._sync_customer_record(session, updated_order_state)

        # 7. Handle confirmed order
        order_persisted = False
        analytics_logged = False

        order_is_confirmed = updated_order_state.get("status") == OrderStatus.CONFIRMED
        has_customer_info = customer_name and (customer_phone or customer_email)
        order_not_yet_logged = updated_order_state.get("_confirmed_logged") is not True

        # Get store_id for persistence and POS submission
        persist_store_id = session_store_id or self._get_random_store_id()
        if persist_store_id and "store_id" not in updated_order_state:
            updated_order_state["store_id"] = persist_store_id

        # Persist order if confirmed with customer info
        if order_is_confirmed and has_customer_info:
            order_persisted = self._persist_order(
                updated_order_state,
                store_id=persist_store_id
            )

        # Submit to POS systems (best-effort, never blocks order flow)
        # When Square is the payment provider, skip _submit_to_square() here
        # because the Payment Links API creates the Square order at checkout.
        if order_persisted and updated_order_state.get("db_order_id"):
            self._submit_to_pos(updated_order_state, "toast")
            company = self._get_company()
            provider = getattr(company, "payment_provider", "stripe") if company else "stripe"
            if provider != "square":
                self._submit_to_pos(updated_order_state, "square")

        # Log analytics for ALL confirmed orders (regardless of customer info)
        if order_is_confirmed and order_not_yet_logged:
            updated_order_state["_confirmed_logged"] = True
            analytics_logged = self._log_analytics(
                ctx=ctx,
                order_state=updated_order_state,
                history=history,
                reply=reply,
                customer_name=customer_name,
                customer_phone=customer_phone,
                store_id=persist_store_id,
            )

        # Create payment URL (only on first confirmation)
        payment_url = None
        if order_is_confirmed and order_not_yet_logged and updated_order_state.get("db_order_id"):
            payment_url = create_payment_url(
                self.db,
                updated_order_state,
                customer_email=customer_email,
            )

        # Inject payment URL into quick_replies that use the __PAYMENT_URL__ sentinel
        needs_payment_url = quick_replies and any(
            qr.get("url") == "__PAYMENT_URL__" for qr in quick_replies
        )
        if needs_payment_url and updated_order_state.get("db_order_id"):
            if not payment_url:
                payment_url = create_payment_url(
                    self.db, updated_order_state, customer_email=customer_email,
                )
            if payment_url:
                for qr in quick_replies:
                    if qr.get("url") == "__PAYMENT_URL__":
                        qr["url"] = payment_url

        # Send receipt email for "pay in store" orders (no Stripe webhook to trigger it)
        payment_method = updated_order_state.get("payment_method")
        if (payment_method == "card_in_store"
                and order_is_confirmed
                and updated_order_state.get("db_order_id")
                and customer_email):
            send_in_store_receipt(self.db, updated_order_state, customer_email)

        # 8. Update and save session
        session["history"] = history
        session["order"] = updated_order_state
        self._save_session(ctx.session_id, session)

        # 9. Build result — payment_url is now embedded in quick_replies, not separate
        return ProcessingResult(
            reply=reply,
            order_state=updated_order_state,
            actions=actions,
            quick_replies=quick_replies,
            payment_url=None,
            history=history,
            order_persisted=order_persisted,
            analytics_logged=analytics_logged,
            session=session,
        )

    # -------------------------------------------------------------------------
    # Session Management
    # -------------------------------------------------------------------------

    def _get_or_create_session(self, session_id: str) -> dict[str, Any] | None:
        """Load session from database."""
        # Import here to avoid circular dependency
        from .services.session import get_or_create_session
        return get_or_create_session(self.db, session_id)

    def _save_session(self, session_id: str, session_data: dict[str, Any]) -> None:
        """Save session to database."""
        # Import here to avoid circular dependency
        from .services.session import save_session
        save_session(self.db, session_id, session_data)

    # -------------------------------------------------------------------------
    # Customer Lookup
    # -------------------------------------------------------------------------

    def _lookup_customer_by_phone(self, phone: str) -> dict[str, Any] | None:
        """Look up returning customer by phone number.

        Delegates to the shared lookup_customer_by_phone helper in services.helpers.
        """
        return lookup_customer_by_phone(self.db, phone)

    def _sync_customer_record(
        self,
        session: dict[str, Any],
        order_state: dict[str, Any],
    ) -> None:
        """Create or update a Customer record as soon as name + contact is available.

        Runs on every message so the record is persisted the moment checkout
        collects enough info, even if the user abandons the order. Uses
        find_or_create_customer() which is idempotent.
        """
        cust = order_state.get("customer", {})
        name = cust.get("name")
        phone = cust.get("phone")
        email = cust.get("email")
        delivery_address = order_state.get("delivery_address")

        if not name or not (phone or email):
            return

        try:
            customer = find_or_create_customer(
                self.db, name=name, phone=phone, email=email,
                delivery_address=delivery_address,
            )
            if customer:
                session["customer_id"] = customer.id
                order_state["customer_id"] = customer.id
                self.db.commit()
                logger.info("Synced customer #%d early (before confirmation)", customer.id)
        except SQLAlchemyError:
            logger.exception("Failed to sync customer record early")

    # -------------------------------------------------------------------------
    # Store Info
    # -------------------------------------------------------------------------

    def _build_store_info(self, store_id: str | None) -> dict[str, Any]:
        """Build store info with tax rates, delivery zip codes, hours, address, etc.

        Delegates to the shared build_store_info helper in services.helpers.
        """
        return build_store_info(self.db, store_id)

    def _get_company(self) -> Company | None:
        """Get or cache company info."""
        if self._company is None:
            self._company = get_company(self.db)
        return self._company

    def _get_random_store_id(self) -> str:
        """Get a random store ID."""
        from .config import get_random_store_id
        return get_random_store_id()

    # -------------------------------------------------------------------------
    # Store Preference
    # -------------------------------------------------------------------------

    def _update_preferred_store(
        self, session: dict[str, Any], store_id: str,
    ) -> None:
        """Persist the customer's preferred store so it survives sessions.

        Looks up the Customer record via customer_id stored in the session
        and sets preferred_store_id.
        """
        customer_id = session.get("customer_id")
        if not customer_id:
            return
        try:
            from .db.models import Customer
            customer = self.db.get(Customer, customer_id)
            if customer:
                customer.preferred_store_id = store_id
                self.db.flush()
                logger.info(
                    "Updated preferred_store_id=%s for customer #%d",
                    store_id, customer_id,
                )
        except SQLAlchemyError:
            logger.exception("Failed to update preferred_store_id for customer #%d", customer_id)

    # -------------------------------------------------------------------------
    # Order Persistence
    # -------------------------------------------------------------------------

    def _persist_order(
        self,
        order_state: dict[str, Any],
        store_id: str | None = None,
    ) -> bool:
        """Persist confirmed order to database."""
        try:
            from .services.order import persist_confirmed_order
            persist_confirmed_order(self.db, order_state, slots={}, store_id=store_id)
            logger.info(
                "Order persisted for customer: %s (store: %s)",
                order_state.get("customer", {}).get("name"),
                store_id
            )
            return True
        except SQLAlchemyError:
            logger.exception("Database error persisting order")
            return False
        except (ValueError, KeyError, TypeError):
            logger.exception("Failed to persist order")
            return False

    # -------------------------------------------------------------------------
    # POS Submission
    # -------------------------------------------------------------------------

    def _submit_to_pos(self, order_state: dict[str, Any], provider: str) -> bool:
        """Submit confirmed order to a POS provider. Best-effort: never raises."""
        try:
            if provider == "toast":
                from .toast.service import is_toast_configured as is_configured, submit_order
            else:
                from .square.service import is_square_configured as is_configured, submit_order
            if not is_configured():
                return False

            result = submit_order(self.db, order_state)
            if result:
                logger.info("Order #%s submitted to %s POS", order_state.get("db_order_id"), provider)
                return True
            return False
        except (ImportError, OSError, SQLAlchemyError, ValueError, KeyError, TypeError, ConnectionError):
            logger.exception("Failed to submit order #%s to %s", order_state.get("db_order_id"), provider)
            return False

    # -------------------------------------------------------------------------
    # Analytics Logging
    # -------------------------------------------------------------------------

    def _log_analytics(
        self,
        ctx: ProcessingContext,
        order_state: dict[str, Any],
        history: list[dict[str, str]],
        reply: str,
        customer_name: str | None,
        customer_phone: str | None,
        store_id: str | None,
    ) -> bool:
        """Log completed session to analytics."""
        try:
            items = order_state.get("items", [])
            session_record = SessionAnalytics(
                session_id=ctx.session_id,
                status="completed",
                message_count=len(history),
                had_items_in_cart=len(items) > 0,
                item_count=len(items),
                cart_total=order_state.get("total_price", 0.0),
                order_status=OrderStatus.CONFIRMED,
                conversation_history=history,
                last_bot_message=reply[:500] if reply else None,
                last_user_message=ctx.user_message[:500] if ctx.user_message else None,
                reason=None,
                customer_name=customer_name,
                customer_phone=customer_phone,
                store_id=store_id,
            )
            self.db.add(session_record)
            self.db.commit()
            logger.info("Session analytics logged: %s", ctx.session_id[:8])
            return True
        except SQLAlchemyError:
            logger.exception("Database error logging session analytics")
            return False
        except (ValueError, KeyError, TypeError):
            logger.exception("Failed to log session analytics")
            return False

