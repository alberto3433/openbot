"""
Shared Serializers for Admin Routes.

This module provides reusable serialization functions for converting
SQLAlchemy models to Pydantic response schemas. These serializers are
used across multiple admin route modules.

Usage:
    from orderbot.schemas.serializers import (
        serialize_global_attribute_option,
        serialize_global_attribute,
        serialize_menu_item,
        serialize_item_type,
    )
"""

from .global_attributes import (
    serialize_global_attribute_option,
    serialize_global_attribute,
    serialize_global_attribute_list,
    serialize_item_type_link,
)
from .menu_items import serialize_menu_item
from .item_types import serialize_item_type

__all__ = [
    # Global attribute serializers
    "serialize_global_attribute_option",
    "serialize_global_attribute",
    "serialize_global_attribute_list",
    "serialize_item_type_link",
    # Menu item serializers
    "serialize_menu_item",
    # Item type serializers
    "serialize_item_type",
]
