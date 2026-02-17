"""Order models.

Contains: Order, OrderItem.
"""

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from .base import Base
from ...schemas.enums import OrderStatus, PaymentStatus, NotificationStatus, ToastOrderStatus


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(String, nullable=False, default=OrderStatus.CONFIRMED, index=True)
    customer_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    customer_email = Column(String, nullable=True)  # Email for payment links
    pickup_time = Column(String, nullable=True)

    # Price breakdown
    subtotal = Column(Float, nullable=True)  # Sum of line items before tax
    city_tax = Column(Float, nullable=True)  # City tax amount
    state_tax = Column(Float, nullable=True)  # State tax amount
    delivery_fee = Column(Float, nullable=True)  # Delivery fee (if delivery order)
    total_price = Column(Float, nullable=False, default=0.0)  # Final total including tax and fees

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    store_id = Column(String, nullable=True, index=True)  # Store identifier (e.g., "store_eb_001")

    # Order type: pickup or delivery
    order_type = Column(String, nullable=False, default="pickup")  # "pickup" or "delivery"
    delivery_address = Column(String, nullable=True)  # Address for delivery orders

    # Payment tracking
    payment_status = Column(String, nullable=False, default=PaymentStatus.UNPAID)  # "unpaid", "pending_payment", "paid"
    payment_method = Column(String, nullable=True)  # "cash", "card_in_store", "card_phone", "card_link"

    # Stripe payment integration
    stripe_checkout_session_id = Column(String, nullable=True, index=True)
    stripe_payment_intent_id = Column(String, nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)

    # Toast POS integration
    toast_order_guid = Column(String, nullable=True, index=True)
    toast_order_status = Column(String, nullable=True)  # pending_sync / submitted / failed / synced
    toast_submitted_at = Column(DateTime(timezone=True), nullable=True)

    # Order-level special instructions (e.g., "light on the cream cheese", "extra crispy")
    special_instructions = Column(Text, nullable=True)

    # Fulfillment tracking
    estimated_ready_at = Column(DateTime(timezone=True), nullable=True)
    ready_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    cancellation_reason = Column(String, nullable=True)
    staff_notes = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    status_history = relationship("OrderStatusHistory", back_populates="order", cascade="all, delete-orphan")

    # Composite index for common query pattern: filtering by status and sorting by date
    __table_args__ = (
        Index("ix_orders_status_created_at", "status", "created_at"),
    )


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    from_status = Column(String, nullable=True)
    to_status = Column(String, nullable=False)
    changed_by = Column(String, nullable=True)  # Username or "system"
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    order = relationship("Order", back_populates="status_history")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id"), nullable=True)

    menu_item_name = Column(String, nullable=False)

    # Generic item type system
    item_type_id = Column(Integer, ForeignKey("item_types.id"), nullable=True, index=True)

    # Item configuration (JSON) - stores all item-specific details
    item_config = Column(JSON, nullable=True)

    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    line_total = Column(Float, nullable=False)

    order = relationship("Order", back_populates="items")
    menu_item = relationship("MenuItem", back_populates="order_items")


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True, index=True)
    notification_type = Column(String, nullable=False)  # "sms" or "email"
    event = Column(String, nullable=False)  # "order_confirmed", "order_ready", "order_cancelled", "payment_received"
    recipient = Column(String, nullable=False)  # Phone number or email
    status = Column(String, nullable=False, default=NotificationStatus.SENT)  # "sent", "failed", "pending"
    provider_message_id = Column(String, nullable=True)  # AWS SNS/SES message ID
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
