"""
Schemas Package for Orderbot
================================

This package contains all Pydantic models (schemas) used for API request
validation and response serialization. Organizing schemas separately from
routes provides several benefits:

1. **Reusability**: Schemas can be imported and reused across multiple routes
   and services without circular dependencies.

2. **Documentation**: FastAPI automatically generates OpenAPI documentation
   from these schemas, making the API self-documenting.

3. **Validation**: Pydantic provides automatic validation, type coercion,
   and detailed error messages for invalid input.

4. **Serialization**: Response models control exactly what data is returned
   to clients, preventing accidental exposure of internal fields.

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

Pydantic Configuration:
-----------------------
Response models should inherit from base.OrmModel or base.TimestampedModel
which configure from_attributes=True for SQLAlchemy compatibility:

    item = db.query(MenuItem).first()
    return MenuItemOut.model_validate(item)

Usage:
------
Import specific schemas:

    from orderbot.schemas.chat import ChatMessageRequest, ChatMessageResponse
    from orderbot.schemas.menu import MenuItemOut, MenuItemCreate

Or import from the package:

    from orderbot.schemas import ChatMessageRequest, MenuItemOut
"""

# Base classes for schema inheritance
from .base import (
    OrmModel,
    TimestampedModel,
    FullTimestampedModel,
    ListResponse,
    AvailabilityUpdate,
)

# Chat schemas
from .chat import (
    ReturningCustomerInfo,
    ChatStartResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    ActionOut,
    AbandonedSessionRequest,
)

# Menu schemas
from .menu import (
    MenuItemOut,
    MenuItemCreate,
    MenuItemUpdate,
)

# Order schemas
from .orders import (
    OrderSummaryOut,
    OrderItemOut,
    OrderDetailOut,
    OrderListResponse,
)

# Ingredient schemas
from .ingredients import (
    IngredientOut,
    IngredientCreate,
    IngredientUpdate,
    IngredientAvailabilityUpdate,
    IngredientStoreAvailabilityOut,
    MenuItemStoreAvailabilityOut,
    MenuItemAvailabilityUpdate,
)

# Analytics schemas
from .analytics import (
    SessionAnalyticsOut,
    SessionAnalyticsListResponse,
    AnalyticsSummary,
)

# Store schemas
from .stores import (
    StoreOut,
    StoreCreate,
    StoreUpdate,
)

# Company schemas
from .company import (
    CompanyOut,
    CompanyUpdate,
)

# Modifier schemas (item types, attributes, options)
from .modifiers import (
    AttributeOptionOut,
    AttributeOptionCreate,
    AttributeOptionUpdate,
    ItemTypeOut,
    ItemTypeCreate,
    ItemTypeUpdate,
)

__all__ = [
    # Base classes
    "OrmModel",
    "TimestampedModel",
    "FullTimestampedModel",
    "ListResponse",
    "AvailabilityUpdate",
    # Chat
    "ReturningCustomerInfo",
    "ChatStartResponse",
    "ChatMessageRequest",
    "ChatMessageResponse",
    "ActionOut",
    "AbandonedSessionRequest",
    # Menu
    "MenuItemOut",
    "MenuItemCreate",
    "MenuItemUpdate",
    # Orders
    "OrderSummaryOut",
    "OrderItemOut",
    "OrderDetailOut",
    "OrderListResponse",
    # Ingredients
    "IngredientOut",
    "IngredientCreate",
    "IngredientUpdate",
    "IngredientAvailabilityUpdate",
    "IngredientStoreAvailabilityOut",
    "MenuItemStoreAvailabilityOut",
    "MenuItemAvailabilityUpdate",
    # Analytics
    "SessionAnalyticsOut",
    "SessionAnalyticsListResponse",
    "AnalyticsSummary",
    # Stores
    "StoreOut",
    "StoreCreate",
    "StoreUpdate",
    # Company
    "CompanyOut",
    "CompanyUpdate",
    # Modifiers
    "AttributeOptionOut",
    "AttributeOptionCreate",
    "AttributeOptionUpdate",
    "ItemTypeOut",
    "ItemTypeCreate",
    "ItemTypeUpdate",
]
