"""
Item Type Helper Functions
==========================

This module provides helper functions that derive configurability status
from linked global attributes, replacing the need for explicit `is_configurable`
and `skip_config` flags on the ItemType model.

Derived Logic:
--------------
- is_configurable: True if item type has ANY linked global attributes
- skip_config: True if item type has NO attributes with ask_in_conversation=True

These helpers are the single source of truth for configurability decisions.
All code that previously read is_configurable/skip_config should use these
functions instead.

Usage:
------
    from sandwich_bot.services.item_type_helpers import (
        has_linked_attributes,
        has_askable_attributes,
        get_item_type_config_status,
    )

    # Check if item type is configurable
    if has_linked_attributes(item_type_id, db):
        # Item type has attributes to configure
        ...

    # Check if we should ask about attributes in conversation
    if has_askable_attributes(item_type_id, db):
        # Item type has attributes the bot should ask about
        ...

    # Get full config status dict
    status = get_item_type_config_status(item_type_id, db)
    # status = {"is_configurable": True, "skip_config": False}
"""

from typing import Optional
from sqlalchemy.orm import Session

from ..models import ItemType, ItemTypeGlobalAttribute


def has_linked_attributes(item_type_id: int, db: Session) -> bool:
    """
    Check if an item type has any linked global attributes.

    This is equivalent to the old is_configurable flag:
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


def has_askable_attributes(item_type_id: int, db: Session) -> bool:
    """
    Check if an item type has any attributes with ask_in_conversation=True.

    This determines whether the bot should ask configuration questions:
    - True = at least one attribute should be asked about
    - False = no attributes need to be asked (all have ask_in_conversation=False)

    The inverse of this is equivalent to the old skip_config flag:
    - skip_config = not has_askable_attributes()

    Args:
        item_type_id: The ID of the item type to check
        db: SQLAlchemy database session

    Returns:
        True if the item type has at least one attribute with ask_in_conversation=True
    """
    count = db.query(ItemTypeGlobalAttribute).filter(
        ItemTypeGlobalAttribute.item_type_id == item_type_id,
        ItemTypeGlobalAttribute.ask_in_conversation == True  # noqa: E712
    ).count()
    return count > 0


def get_item_type_config_status(item_type_id: int, db: Session) -> dict:
    """
    Get the full configuration status for an item type.

    Returns a dict with derived is_configurable and skip_config values,
    providing backward compatibility with code that expects these flags.

    Args:
        item_type_id: The ID of the item type to check
        db: SQLAlchemy database session

    Returns:
        Dict with keys:
        - is_configurable: True if has any linked global attributes
        - skip_config: True if has no askable attributes
    """
    has_attrs = has_linked_attributes(item_type_id, db)
    has_askable = has_askable_attributes(item_type_id, db) if has_attrs else False

    return {
        "is_configurable": has_attrs,
        "skip_config": not has_askable,
    }


def get_item_type_config_status_by_slug(slug: str, db: Session) -> Optional[dict]:
    """
    Get configuration status for an item type by its slug.

    Convenience function for code that has the slug instead of ID.

    Args:
        slug: The item type slug (e.g., "bagel", "sized_beverage")
        db: SQLAlchemy database session

    Returns:
        Dict with is_configurable and skip_config, or None if item type not found
    """
    item_type = db.query(ItemType).filter(ItemType.slug == slug).first()
    if not item_type:
        return None
    return get_item_type_config_status(item_type.id, db)


def is_configurable(item_type: ItemType, db: Session) -> bool:
    """
    Check if an item type is configurable (has linked attributes).

    Convenience function that takes an ItemType object directly.

    Args:
        item_type: The ItemType model instance
        db: SQLAlchemy database session

    Returns:
        True if the item type has linked global attributes
    """
    return has_linked_attributes(item_type.id, db)


def should_skip_config(item_type: ItemType, db: Session) -> bool:
    """
    Check if configuration should be skipped for an item type.

    Configuration is skipped when:
    - Item type has no linked attributes (nothing to configure), OR
    - Item type has attributes but none have ask_in_conversation=True

    Convenience function that takes an ItemType object directly.

    Args:
        item_type: The ItemType model instance
        db: SQLAlchemy database session

    Returns:
        True if configuration questions should be skipped
    """
    if not has_linked_attributes(item_type.id, db):
        return True
    return not has_askable_attributes(item_type.id, db)
