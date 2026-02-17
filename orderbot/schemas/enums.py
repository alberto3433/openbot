from enum import Enum


class OrderStatus(str, Enum):
    """Status values for customer orders."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PENDING_PAYMENT = "pending_payment"
    PREPARING = "preparing"
    READY = "ready"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
