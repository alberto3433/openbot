"""
Admin Testing Routes for Sandwich Bot
======================================

This module contains admin endpoints for testing and debugging purposes.
These utilities help with development, QA testing, and troubleshooting.

Endpoints:
----------
- GET /admin/testing/reset-customer: Clear returning customer data

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.

Purpose:
--------
These endpoints exist to support:
1. Testing the returning customer flow
2. Resetting state for QA testing
3. Debugging order issues

Returning Customer Reset:
-------------------------
The reset-customer endpoint clears orders for a phone number, allowing
the number to be used as a "new customer" for testing the first-time
customer experience.

Production Notes:
-----------------
These endpoints modify data and should be used carefully in production.
Consider restricting to non-production environments if needed.

Usage:
------
    # Reset customer history for a phone number
    GET /admin/testing/reset-customer?phone=2125550100
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..models import Order


logger = logging.getLogger(__name__)

# Router definition
admin_testing_router = APIRouter(
    prefix="/admin/testing",
    tags=["Admin - Testing"]
)


# =============================================================================
# Testing Endpoints
# =============================================================================

@admin_testing_router.get("/reset-customer")
def reset_customer(
    phone: str = Query(..., description="Phone number to reset"),
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
):
    """
    Reset a customer's order history for testing.

    Deletes all orders associated with the given phone number so the
    number can be used as a new customer in testing.

    Args:
        phone: Phone number to reset (orders with this phone will be deleted)

    Returns:
        Dict with count of deleted orders
    """
    from sqlalchemy import func

    # Normalize phone number for matching
    normalized_phone = phone.replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
    phone_suffix = normalized_phone[-10:] if len(normalized_phone) >= 10 else normalized_phone

    # Build normalized phone column for comparison
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

    # Find and delete orders
    orders_to_delete = db.query(Order).filter(
        Order.phone.isnot(None),
        normalized_db_phone.like(f"%{phone_suffix}%")
    ).all()

    count = len(orders_to_delete)

    for order in orders_to_delete:
        db.delete(order)

    db.commit()

    logger.info("Reset customer: deleted %d orders for phone %s", count, phone)

    return {
        "success": True,
        "phone": phone,
        "orders_deleted": count,
        "message": f"Deleted {count} orders for phone number {phone}"
    }
