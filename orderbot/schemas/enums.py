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


class PaymentStatus(str, Enum):
    """Status values for payment tracking."""
    UNPAID = "unpaid"
    PENDING_PAYMENT = "pending_payment"
    PAID = "paid"
    EXPIRED = "expired"


class NotificationStatus(str, Enum):
    """Status values for notification log entries."""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class ToastOrderStatus(str, Enum):
    """Status values for Toast POS order sync."""
    PENDING_SYNC = "pending_sync"
    SUBMITTED = "submitted"
    SYNCED = "synced"
    FAILED = "failed"
