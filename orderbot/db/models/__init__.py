"""SQLAlchemy database models.

This package contains all SQLAlchemy ORM models for the application.
All models are re-exported here for backward compatibility with imports
from orderbot.models.
"""

from .base import Base

# Config models
from .config import (
    AttributeInquiryKeyword,
    ComponentSlotOption,
    ItemType,
    ItemTypeAlias,
    ItemTypeComponentSlot,
    MenuDisplayGroup,
    MenuDisplayGroupAlias,
    ModifierCategory,
    ModifierCategoryAlias,
    ModifierQualifier,
    OverallCategory,
    ResponsePattern,
)

# Attribute models
from .attributes import (
    GlobalAttribute,
    GlobalAttributeAlias,
    GlobalAttributeOption,
    GlobalAttributeOptionAlias,
    GlobalAttributeOptionSkip,
    ItemTypeGlobalAttribute,
)

# Menu models
from .menu import (
    MenuItem,
    MenuItemAlias,
    MenuItemIngredient,
    MenuItemStoreAvailability,
)

# Ingredient models
from .ingredients import (
    Ingredient,
    IngredientAlias,
    IngredientCategory,
    IngredientMustMatch,
    IngredientStoreAvailability,
    IngredientSubcategory,
    IngredientUnit,
)

# Order models
from .orders import NotificationLog, Order, OrderItem, OrderStatusHistory

# Toast POS integration models
from .toast import ToastGuidMap

# Session models
from .sessions import ChatSession, SessionAnalytics

# Company models
from .company import (
    Company,
    MenuItemSize,
    MenuItemSizeCategory,
    MenuItemSizePrice,
    NeighborhoodZipCode,
    Store,
)

# Analytics models
from .analytics import (
    UnrecognizedMenuItemLog,
    UnrecognizedMenuItemSuggestion,
    UnrecognizedOptionSuggestion,
    UnrecognizedIngredientSuggestion,
)

__all__ = [
    # Base
    "Base",
    # Config
    "AttributeInquiryKeyword",
    "ComponentSlotOption",
    "ItemTypeComponentSlot",
    "MenuDisplayGroup",
    "MenuDisplayGroupAlias",
    "OverallCategory",
    "ItemType",
    "ItemTypeAlias",
    "ResponsePattern",
    "ModifierCategory",
    "ModifierCategoryAlias",
    "ModifierQualifier",
    # Attributes
    "GlobalAttribute",
    "GlobalAttributeAlias",
    "GlobalAttributeOption",
    "GlobalAttributeOptionAlias",
    "GlobalAttributeOptionSkip",
    "ItemTypeGlobalAttribute",
    # Menu
    "MenuItem",
    "MenuItemAlias",
    "MenuItemIngredient",
    "MenuItemStoreAvailability",
    # Ingredients
    "IngredientUnit",
    "Ingredient",
    "IngredientAlias",
    "IngredientMustMatch",
    "IngredientCategory",
    "IngredientSubcategory",
    "IngredientStoreAvailability",
    # Orders
    "NotificationLog",
    "Order",
    "OrderItem",
    "OrderStatusHistory",
    # Sessions
    "ChatSession",
    "SessionAnalytics",
    # Company
    "Store",
    "NeighborhoodZipCode",
    "Company",
    "MenuItemSizeCategory",
    "MenuItemSize",
    "MenuItemSizePrice",
    # Analytics
    "UnrecognizedMenuItemSuggestion",
    "UnrecognizedMenuItemLog",
    "UnrecognizedOptionSuggestion",
    "UnrecognizedIngredientSuggestion",
    # Toast POS
    "ToastGuidMap",
]
