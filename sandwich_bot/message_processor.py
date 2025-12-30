"""
Unified message processing for all chat endpoints.

This module provides a single MessageProcessor class that handles the complete
lifecycle of processing a user message:
- Session management (load/save)
- Customer lookup
- State machine processing
- Order persistence
- Analytics logging
- Payment emails

All endpoints (web chat, streaming, VAPI voice) use this class, with only
request/response format handling done in the endpoint itself.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .models import ChatSession, SessionAnalytics, Order, Store, Company, ItemType
from .menu_index_builder import build_menu_index, get_menu_version
from .email_service import send_payment_link_email
from .chains.integration import process_voice_message

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Data Classes
# -----------------------------------------------------------------------------

@dataclass
class ProcessingContext:
    """Input context for message processing."""
    user_message: str
    session_id: str

    # Optional context
    caller_id: Optional[str] = None
    store_id: Optional[str] = None

    # Pre-loaded session (optional - if not provided, will be loaded)
    session: Optional[Dict[str, Any]] = None


@dataclass
class ProcessingResult:
    """Output from message processing."""
    reply: str
    order_state: Dict[str, Any]
    actions: List[Dict[str, Any]]

    # Session data for response
    history: List[Dict[str, str]] = field(default_factory=list)

    # Status flags
    order_persisted: bool = False
    analytics_logged: bool = False
    payment_email_sent: bool = False

    # For backward compatibility with existing endpoints
    primary_intent: str = "unknown"
    primary_slots: Dict[str, Any] = field(default_factory=dict)

    # The full session (for endpoints that need it)
    session: Dict[str, Any] = field(default_factory=dict)


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
        self._company: Optional[Company] = None

    def process(self, ctx: ProcessingContext) -> ProcessingResult:
        """
        Process a user message and return the result.

        This is the main entry point that orchestrates all processing steps.
        """
        # 1. Load or create session
        session = ctx.session or self._get_or_create_session(ctx.session_id)
        if session is None:
            raise ValueError(f"Session not found: {ctx.session_id}")

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

        # 3. Build menu and store context
        menu_index = build_menu_index(self.db, store_id=session_store_id)
        store_info = self._build_store_info(session_store_id)

        # 4. Process through state machine
        reply, updated_order_state, actions = process_voice_message(
            user_message=ctx.user_message,
            order_state=order_state,
            history=history,
            session_id=ctx.session_id,
            menu_index=menu_index,
            store_info=store_info,
            returning_customer=returning_customer,
            llm_fallback_fn=None,  # State machine handles everything
        )

        # 5. Update history
        history.append({"role": "user", "content": ctx.user_message})
        history.append({"role": "assistant", "content": reply})

        # 6. Extract customer info for persistence
        customer_name = updated_order_state.get("customer", {}).get("name")
        customer_phone = updated_order_state.get("customer", {}).get("phone") or session_caller_id
        customer_email = updated_order_state.get("customer", {}).get("email")

        # Use caller_id as phone if not explicitly provided
        if session_caller_id and not updated_order_state.get("customer", {}).get("phone"):
            updated_order_state.setdefault("customer", {})
            updated_order_state["customer"]["phone"] = session_caller_id

        # 7. Handle confirmed order
        order_persisted = False
        analytics_logged = False
        payment_sent = False

        order_is_confirmed = updated_order_state.get("status") == "confirmed"
        has_customer_info = customer_name and (customer_phone or customer_email)
        order_not_yet_logged = updated_order_state.get("_confirmed_logged") is not True

        # Get store_id for persistence
        persist_store_id = session_store_id or self._get_random_store_id()

        # Persist order if confirmed with customer info
        if order_is_confirmed and has_customer_info:
            order_persisted = self._persist_order(
                updated_order_state,
                store_id=persist_store_id
            )

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

        # Send payment email if applicable
        if order_is_confirmed and customer_email and updated_order_state.get("db_order_id"):
            payment_sent = self._send_payment_email(
                updated_order_state,
                customer_email=customer_email,
                customer_name=customer_name,
                customer_phone=customer_phone,
            )

        # 8. Update and save session
        session["history"] = history
        session["order"] = updated_order_state
        self._save_session(ctx.session_id, session)

        # 9. Build result
        primary_intent = actions[0].get("intent", "unknown") if actions else "unknown"
        primary_slots = actions[0].get("slots", {}) if actions else {}

        return ProcessingResult(
            reply=reply,
            order_state=updated_order_state,
            actions=actions,
            history=history,
            order_persisted=order_persisted,
            analytics_logged=analytics_logged,
            payment_email_sent=payment_sent,
            primary_intent=primary_intent,
            primary_slots=primary_slots,
            session=session,
        )

    # -------------------------------------------------------------------------
    # Session Management
    # -------------------------------------------------------------------------

    def _get_or_create_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load session from database."""
        # Import here to avoid circular dependency
        from .main import get_or_create_session
        return get_or_create_session(self.db, session_id)

    def _save_session(self, session_id: str, session_data: Dict[str, Any]) -> None:
        """Save session to database."""
        # Import here to avoid circular dependency
        from .main import save_session
        save_session(self.db, session_id, session_data)

    # -------------------------------------------------------------------------
    # Customer Lookup
    # -------------------------------------------------------------------------

    def _lookup_customer_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """Look up returning customer by phone number."""
        if not phone:
            return None

        # Normalize phone number
        normalized_phone = phone.replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
        phone_suffix = normalized_phone[-10:] if len(normalized_phone) >= 10 else normalized_phone

        from sqlalchemy import func
        from sqlalchemy.orm import joinedload

        normalized_db_phone = func.replace(
            func.replace(
                func.replace(
                    func.replace(Order.phone, "-", ""),
                    " ", ""
                ),
                "(", ""
            ),
            ")", ""
        )

        # Find most recent order
        recent_order = (
            self.db.query(Order)
            .options(joinedload(Order.items))
            .filter(Order.phone.isnot(None))
            .filter(normalized_db_phone.like(f"%{phone_suffix}%"))
            .order_by(Order.created_at.desc())
            .first()
        )

        if not recent_order:
            return None

        # Get order count
        order_count = (
            self.db.query(Order)
            .filter(Order.phone.isnot(None))
            .filter(normalized_db_phone.like(f"%{phone_suffix}%"))
            .count()
        )

        # Get last order items
        last_order_items = []
        if recent_order.items:
            for item in recent_order.items:
                item_data = {
                    "menu_item_name": item.menu_item_name,
                    "quantity": item.quantity,
                    "price": item.unit_price,
                }
                # All item-specific fields (item_type, bread, toasted, etc.) are in item_config
                if item.item_config:
                    item_data.update(item.item_config)
                last_order_items.append(item_data)

        return {
            "name": recent_order.customer_name,
            "phone": recent_order.phone,
            "email": recent_order.customer_email,
            "order_count": order_count,
            "last_order_items": last_order_items,
            "last_order_date": recent_order.created_at.isoformat() if recent_order.created_at else None,
            "last_order_type": recent_order.order_type,
            "last_order_address": recent_order.delivery_address,  # For repeat delivery orders
        }

    # -------------------------------------------------------------------------
    # Store Info
    # -------------------------------------------------------------------------

    def _build_store_info(self, store_id: Optional[str]) -> Dict[str, Any]:
        """Build store info with tax rates, delivery zip codes, hours, address, etc."""
        company = self._get_company()
        company_name = company.name if company else "OrderBot"

        store_info = {
            "name": company_name,
            "store_id": store_id,
            "city_tax_rate": 0.0,
            "state_tax_rate": 0.0,
            "delivery_zip_codes": [],
            # Store location and contact info
            "address": None,
            "city": None,
            "state": None,
            "zip_code": None,
            "phone": None,
            "hours": None,
            # All stores info for cross-store delivery lookup
            "all_stores": [],
        }

        if store_id:
            store = self.db.query(Store).filter(Store.store_id == store_id).first()
            if store:
                store_info["name"] = store.name or company_name
                store_info["city_tax_rate"] = store.city_tax_rate or 0.0
                store_info["state_tax_rate"] = store.state_tax_rate or 0.0
                store_info["delivery_zip_codes"] = store.delivery_zip_codes or []
                # Add location and contact info
                store_info["address"] = store.address
                store_info["city"] = store.city
                store_info["state"] = store.state
                store_info["zip_code"] = store.zip_code
                store_info["phone"] = store.phone
                store_info["hours"] = store.hours

        # Get all stores for delivery zone lookup
        all_stores = self.db.query(Store).filter(Store.status == "open").all()
        store_info["all_stores"] = [
            {
                "store_id": s.store_id,
                "name": s.name,
                "delivery_zip_codes": s.delivery_zip_codes or [],
                "address": s.address,
                "city": s.city,
                "state": s.state,
                "phone": s.phone,
            }
            for s in all_stores
        ]

        return store_info

    def _get_company(self) -> Optional[Company]:
        """Get or cache company info."""
        if self._company is None:
            self._company = self.db.query(Company).first()
        return self._company

    def _get_random_store_id(self) -> str:
        """Get a random store ID."""
        from .main import get_random_store_id
        return get_random_store_id()

    # -------------------------------------------------------------------------
    # Order Persistence
    # -------------------------------------------------------------------------

    def _persist_order(
        self,
        order_state: Dict[str, Any],
        store_id: Optional[str] = None,
    ) -> bool:
        """Persist confirmed order to database."""
        try:
            from .main import persist_confirmed_order
            persist_confirmed_order(self.db, order_state, slots={}, store_id=store_id)
            logger.info(
                "Order persisted for customer: %s (store: %s)",
                order_state.get("customer", {}).get("name"),
                store_id
            )
            return True
        except Exception as e:
            logger.error("Failed to persist order: %s", e)
            return False

    # -------------------------------------------------------------------------
    # Analytics Logging
    # -------------------------------------------------------------------------

    def _log_analytics(
        self,
        ctx: ProcessingContext,
        order_state: Dict[str, Any],
        history: List[Dict[str, str]],
        reply: str,
        customer_name: Optional[str],
        customer_phone: Optional[str],
        store_id: Optional[str],
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
                order_status="confirmed",
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
        except Exception as e:
            logger.error("Failed to log session analytics: %s", e)
            return False

    # -------------------------------------------------------------------------
    # Payment Email
    # -------------------------------------------------------------------------

    def _send_payment_email(
        self,
        order_state: Dict[str, Any],
        customer_email: str,
        customer_name: Optional[str],
        customer_phone: Optional[str],
    ) -> bool:
        """Send payment link email."""
        try:
            db_order_id = order_state.get("db_order_id")
            if not db_order_id:
                return False

            company = self._get_company()
            store_name = company.name if company else "OrderBot"

            items = order_state.get("items", [])
            checkout_state = order_state.get("checkout_state", {})
            order_total = (
                checkout_state.get("total")
                or order_state.get("total_price")
                or sum(item.get("line_total", 0) for item in items)
            )
            order_type = order_state.get("order_type", "pickup")

            result = send_payment_link_email(
                to_email=customer_email,
                order_id=db_order_id,
                amount=order_total,
                store_name=store_name,
                customer_name=customer_name,
                customer_phone=customer_phone,
                order_type=order_type,
                items=items,
                subtotal=checkout_state.get("subtotal"),
                city_tax=checkout_state.get("city_tax", 0),
                state_tax=checkout_state.get("state_tax", 0),
                delivery_fee=checkout_state.get("delivery_fee", 0),
            )
            logger.info("Payment link email sent: %s", result)
            return True
        except Exception as e:
            logger.error("Failed to send payment email: %s", e)
            return False
