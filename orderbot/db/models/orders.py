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


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(String, nullable=False, default="confirmed", index=True)  # e.g., pending/confirmed/preparing/ready/completed/cancelled
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
    payment_status = Column(String, nullable=False, default="unpaid")  # "unpaid", "pending_payment", "paid"
    payment_method = Column(String, nullable=True)  # "cash", "card_in_store", "card_phone", "card_link"

    # Order-level special instructions (e.g., "light on the cream cheese", "extra crispy")
    special_instructions = Column(Text, nullable=True)

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

    # Composite index for common query pattern: filtering by status and sorting by date
    __table_args__ = (
        Index("ix_orders_status_created_at", "status", "created_at"),
    )


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
