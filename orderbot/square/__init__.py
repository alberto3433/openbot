"""
Square POS Integration Package
==================================

Integrates with the Square Orders API to push confirmed orders to the kitchen
display (KDS). Square is best-effort: if unconfigured or unavailable, orders
are still saved locally and the chatbot flow is unaffected.

Key modules:
- service.py: Square API client (submit, query)
- order_builder.py: Translates internal order dict → Square CreateOrder JSON
- webhook.py: Receives Square fulfillment status updates
"""

from .service import create_payment_link, is_square_configured, submit_order

__all__ = [
    "create_payment_link",
    "is_square_configured",
    "submit_order",
]
