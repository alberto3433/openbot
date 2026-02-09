"""
Item Type Serializers.

Provides serialization functions for ItemType and related models.
"""

from sqlalchemy.orm import Session

from orderbot.db.models import (
    GlobalAttribute,
    ItemType,
    ItemTypeGlobalAttribute,
    MenuItem,
)
from orderbot.schemas.modifiers import ItemTypeOut, GlobalAttributeRef


def serialize_item_type(
    item_type: ItemType,
    db: Session
) -> ItemTypeOut:
    """Build full ItemTypeOut response.

    Args:
        item_type: The ItemType to serialize
        db: Database session for relationship queries

    Returns:
        ItemTypeOut schema
    """
    menu_item_count = db.query(MenuItem).filter(
        MenuItem.item_type_id == item_type.id
    ).count()

    # Query linked global attributes with their link details in a single query
    linked_data = (
        db.query(GlobalAttribute, ItemTypeGlobalAttribute)
        .join(ItemTypeGlobalAttribute, ItemTypeGlobalAttribute.global_attribute_id == GlobalAttribute.id)
        .filter(ItemTypeGlobalAttribute.item_type_id == item_type.id)
        .order_by(ItemTypeGlobalAttribute.display_order)
        .all()
    )

    global_attribute_count = len(linked_data)
    global_attributes = [
        GlobalAttributeRef(
            id=attr.id,
            slug=attr.slug,
            display_name=attr.display_name,
        )
        for attr, link in linked_data
    ]

    # Derive configurability from query results (no extra queries needed)
    is_configurable = global_attribute_count > 0
    has_askable = any(link.ask_in_conversation for attr, link in linked_data)
    skip_config = not has_askable if is_configurable else True

    # Get display group info (required)
    display_group = item_type.menu_display_group
    display_group_name = display_group.display_name if display_group else "Unknown"

    # Get category name from display group
    category_name = None
    if display_group and display_group.overall_category:
        category_name = display_group.overall_category.display_name

    return ItemTypeOut(
        id=item_type.id,
        slug=item_type.slug,
        display_name=item_type.display_name,
        is_configurable=is_configurable,
        skip_config=skip_config,
        menu_display_group_id=item_type.menu_display_group_id,
        menu_display_group_name=display_group_name,
        overall_category_name=category_name,
        menu_item_count=menu_item_count,
        global_attribute_count=global_attribute_count,
        global_attributes=global_attributes,
        aliases=item_type.aliases,
    )
