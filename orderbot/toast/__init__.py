"""
Toast POS Integration Package
=================================

Integrates with the Toast POS system to push confirmed orders to the kitchen
display. Toast is best-effort: if unconfigured or unavailable, orders are still
saved locally and the chatbot flow is unaffected.

Key modules:
- service.py: Toast API client (auth, submit, query)
- order_builder.py: Translates internal order dict → Toast API JSON payload
- guid_resolver.py: Maps local IDs to Toast GUIDs via toast_guid_map table
- webhook.py: Receives Toast status updates (fulfillment callbacks)
- admin_routes.py: Admin CRUD for GUID mappings
- menu_sync.py: Auto-match Toast menu items to local items
"""

from .service import is_toast_configured, submit_order

__all__ = [
    "is_toast_configured",
    "submit_order",
]
