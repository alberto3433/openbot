"""Customer models.

Contains: Customer.
"""

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import relationship

from .base import Base


class Customer(Base):
    """Represents a customer for loyalty/account tracking.

    Customers are looked up by phone (primary) or email. The same customer
    record is reused across multiple orders.
    """
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=True)
    phone = Column(String, nullable=True, index=True)
    email = Column(String, nullable=True, index=True)
    stripe_customer_id = Column(String, nullable=True, index=True)
    delivery_address = Column(String, nullable=True)

    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    preferred_store_id = Column(String, nullable=True)
    preferred_voice = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    orders = relationship("Order", back_populates="customer")
