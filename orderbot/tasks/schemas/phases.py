"""
Order Phase Definitions.

This module defines the OrderPhase enum representing the high-level phases
of the order flow in the state machine.
"""

from enum import Enum


class OrderPhase(str, Enum):
    """High-level phases of the order flow."""
    GREETING = "greeting"
    TAKING_ITEMS = "taking_items"
    CONFIGURING_ITEM = "configuring_item"  # Waiting for specific item input
    CHECKOUT_DELIVERY = "checkout_delivery"
    CHECKOUT_NAME = "checkout_name"
    CHECKOUT_CONFIRM = "checkout_confirm"
    CHECKOUT_PAYMENT_METHOD = "checkout_payment_method"  # Ask text or email
    CHECKOUT_PHONE = "checkout_phone"  # Collect phone if they want text confirmation
    CHECKOUT_EMAIL = "checkout_email"  # Collect email if they want email receipt
    COMPLETE = "complete"
    CANCELLED = "cancelled"
