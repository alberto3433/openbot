"""
Item Type Helper Functions
==========================

This module provides helper functions that derive configurability status
from linked global attributes.

Usage:
------
    from orderbot.services.item_type_helpers import has_linked_attributes

    # Check if item type is configurable (has any linked global attributes)
    if has_linked_attributes(item_type_id, db):
        # Item type has attributes to configure
        ...
"""

from sqlalchemy.orm import Session

from ..models import ItemTypeGlobalAttribute


def has_linked_attributes(item_type_id: int, db: Session) -> bool:
    """
    Check if an item type has any linked global attributes.

    This indicates whether an item type is configurable:
    - True = item type has attributes that can be configured
    - False = item type is simple with no configuration options

    Args:
        item_type_id: The ID of the item type to check
        db: SQLAlchemy database session

    Returns:
        True if the item type has at least one linked global attribute
    """
    count = db.query(ItemTypeGlobalAttribute).filter(
        ItemTypeGlobalAttribute.item_type_id == item_type_id
    ).count()

    return count > 0
