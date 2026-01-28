"""
Schemas Package for Orderbot
================================

This package contains all Pydantic models (schemas) used for API request
validation and response serialization.

Schema Organization:
--------------------
- **base.py**: Base classes for schema inheritance (OrmModel, TimestampedModel, ListResponse)
- **chat.py**: Chat session and message schemas
- **menu.py**: Menu item CRUD schemas
- **orders.py**: Order and order item schemas
- **ingredients.py**: Ingredient management schemas
- **analytics.py**: Session analytics and reporting schemas
- **stores.py**: Store/location management schemas
- **company.py**: Company settings schemas
- **modifiers.py**: Item types, attributes, and options schemas

Naming Conventions:
-------------------
- *Out: Response models (e.g., MenuItemOut) - what API returns
- *Create: Request models for POST (e.g., MenuItemCreate) - what client sends to create
- *Update: Request models for PUT/PATCH (e.g., MenuItemUpdate) - what client sends to update
- *Request: Complex request bodies (e.g., ChatMessageRequest)
- *Response: Complex response structures (e.g., ChatMessageResponse)

Usage:
------
Import specific schemas from submodules:

    from orderbot.schemas.chat import ChatMessageRequest, ChatMessageResponse
    from orderbot.schemas.menu import MenuItemOut, MenuItemCreate
"""
