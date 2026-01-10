"""
Routes Package for Sandwich Bot
================================

This package contains all API route definitions organized by domain. Each module
defines a FastAPI APIRouter with related endpoints grouped together.

Architecture Overview:
----------------------
Routes are organized into logical groups:

**Customer-Facing Routes:**
- chat.py: Chat session and messaging endpoints for ordering
- public.py: Public store/company info (no auth required)
- tts.py: Text-to-speech synthesis for voice interface

**Admin Routes (require authentication):**
- admin_menu.py: Menu item CRUD operations
- admin_orders.py: Order listing and management
- admin_ingredients.py: Ingredient management and 86 system
- admin_analytics.py: Session analytics and reporting
- admin_stores.py: Store/location management
- admin_company.py: Company-wide settings
- admin_modifiers.py: Item types, attributes, and options
- admin_testing.py: Debug and testing utilities

Router Registration:
--------------------
All routers are registered in main.py under two prefixes:
1. /api/v1/* - Versioned API (recommended)
2. /* - Root paths for backward compatibility

Each router is defined with a prefix and tags for OpenAPI documentation:

    chat_router = APIRouter(prefix="/chat", tags=["Chat"])

Route Dependencies:
-------------------
Common dependencies are injected via FastAPI's Depends():
- get_db: Database session for queries
- verify_admin_credentials: Admin authentication
- limiter.limit(): Rate limiting

Error Handling:
---------------
Routes raise HTTPException for error conditions:
- 400: Bad request (validation errors)
- 401: Unauthorized (invalid credentials)
- 404: Not found (invalid ID)
- 429: Too many requests (rate limited)
- 503: Service unavailable (missing configuration)

Usage:
------
Import routers in main.py:

    from sandwich_bot.routes import (
        chat_router,
        admin_menu_router,
        admin_orders_router,
        ...
    )

    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(chat_router)
    api_v1.include_router(admin_menu_router)
    ...
"""

from .chat import chat_router
from .admin_menu import admin_menu_router
from .admin_orders import admin_orders_router
from .admin_ingredients import admin_ingredients_router
from .admin_analytics import admin_analytics_router
from .admin_stores import admin_stores_router
from .admin_company import admin_company_router
from .admin_modifiers import admin_modifiers_router
from .admin_modifier_categories import admin_modifier_categories_router
from .admin_testing import admin_testing_router
from .admin_item_type_fields import admin_item_type_fields_router
from .admin_item_type_attributes import admin_item_type_attributes_router
from .admin_response_patterns import admin_response_patterns_router
from .admin_modifier_qualifiers import admin_modifier_qualifiers_router
from .admin_global_attributes import admin_global_attributes_router, admin_item_type_global_attrs_router
from .public import public_stores_router, public_company_router
from .tts import tts_router

__all__ = [
    "chat_router",
    "admin_menu_router",
    "admin_orders_router",
    "admin_ingredients_router",
    "admin_analytics_router",
    "admin_stores_router",
    "admin_company_router",
    "admin_modifiers_router",
    "admin_modifier_categories_router",
    "admin_testing_router",
    "admin_item_type_fields_router",
    "admin_item_type_attributes_router",
    "admin_response_patterns_router",
    "admin_modifier_qualifiers_router",
    "admin_global_attributes_router",
    "admin_item_type_global_attrs_router",
    "public_stores_router",
    "public_company_router",
    "tts_router",
]
