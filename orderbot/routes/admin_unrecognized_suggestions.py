"""
Admin Unrecognized Suggestions - Re-export Hub
===============================================

This module re-exports all 4 unrecognized suggestion routers for backward compatibility.
The actual implementations live in their own modules.
"""

from .admin_unrecognized_menu_items import admin_unrecognized_menu_item_suggestions_router
from .admin_unrecognized_logs import admin_unrecognized_menu_item_logs_router
from .admin_unrecognized_options import admin_unrecognized_option_suggestions_router
from .admin_unrecognized_ingredients import admin_unrecognized_ingredient_suggestions_router

__all__ = [
    "admin_unrecognized_menu_item_suggestions_router",
    "admin_unrecognized_menu_item_logs_router",
    "admin_unrecognized_option_suggestions_router",
    "admin_unrecognized_ingredient_suggestions_router",
]
