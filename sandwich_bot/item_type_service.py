"""
Service module for the generic item type system.

Provides helper functions to:
- Query item types and their attributes
- Calculate prices based on attribute options
- Build menu data structures from the generic system
"""

from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from .models import (
    ItemType,
    ItemTypeAttribute,
    AttributeOption,
)


def get_item_type_by_slug(db: Session, slug: str) -> Optional[ItemType]:
    """Get an item type by its slug."""
    return db.query(ItemType).filter(ItemType.slug == slug).first()


def get_type_attributes(
    db: Session,
    item_type_id: int,
    include_options: bool = True
) -> List[Dict[str, Any]]:
    """
    Get type attributes for an item type.

    Args:
        db: Database session
        item_type_id: The item type ID
        include_options: Whether to include options for each attribute

    Returns:
        List of attribute dicts with optional options
    """
    attrs = (
        db.query(ItemTypeAttribute)
        .filter(ItemTypeAttribute.item_type_id == item_type_id)
        .order_by(ItemTypeAttribute.display_order)
        .all()
    )

    result = []
    for attr in attrs:
        attr_dict = {
            "id": attr.id,
            "slug": attr.slug,
            "display_name": attr.display_name,
            "input_type": attr.input_type,
            "is_required": attr.is_required,
            "allow_none": attr.allow_none,
            "min_selections": attr.min_selections,
            "max_selections": attr.max_selections,
        }

        if include_options:
            options = (
                db.query(AttributeOption)
                .filter(AttributeOption.item_type_attribute_id == attr.id)
                .order_by(AttributeOption.display_order)
                .all()
            )
            attr_dict["options"] = [
                {
                    "slug": opt.slug,
                    "display_name": opt.display_name,
                    "price_modifier": opt.price_modifier,
                    "is_default": opt.is_default,
                    "is_available": opt.is_available,
                }
                for opt in options
            ]

        result.append(attr_dict)

    return result


# Backward compatibility alias
def get_attribute_definitions(
    db: Session,
    item_type_id: int,
    include_options: bool = True
) -> List[Dict[str, Any]]:
    """
    Get attribute definitions for an item type.

    Deprecated: Use get_type_attributes instead.
    """
    return get_type_attributes(db, item_type_id, include_options)


def get_attribute_option_price(
    db: Session,
    item_type_slug: str,
    attribute_slug: str,
    option_value: str
) -> float:
    """
    Get the price modifier for an attribute option.

    Args:
        db: Database session
        item_type_slug: The item type slug (e.g., "sandwich")
        attribute_slug: The attribute slug (e.g., "bread", "protein")
        option_value: The option display name or slug (e.g., "Wheat", "Turkey")

    Returns:
        Price modifier for this option, or 0.0 if not found
    """
    # Get the item type
    item_type = get_item_type_by_slug(db, item_type_slug)
    if not item_type:
        return 0.0

    # Get the type attribute
    attr = (
        db.query(ItemTypeAttribute)
        .filter(
            ItemTypeAttribute.item_type_id == item_type.id,
            ItemTypeAttribute.slug == attribute_slug
        )
        .first()
    )
    if not attr:
        return 0.0

    # Get the option by display_name or slug (case-insensitive)
    option_lower = option_value.lower() if option_value else ""
    options = (
        db.query(AttributeOption)
        .filter(AttributeOption.item_type_attribute_id == attr.id)
        .all()
    )

    for opt in options:
        if opt.display_name.lower() == option_lower or opt.slug.lower() == option_lower:
            return opt.price_modifier

    return 0.0


def calculate_item_price_from_config(
    db: Session,
    item_type_slug: str,
    base_price: float,
    item_config: Dict[str, Any]
) -> float:
    """
    Calculate the total price for an item based on its configuration.

    Args:
        db: Database session
        item_type_slug: The item type slug (e.g., "sandwich")
        base_price: The base price of the menu item
        item_config: The item configuration dict (e.g., {"bread": "wheat", "protein": "turkey"})

    Returns:
        Total price including all modifiers
    """
    if not item_config:
        return base_price

    total = base_price

    # Get item type
    item_type = get_item_type_by_slug(db, item_type_slug)
    if not item_type:
        return base_price

    # Get all type attributes for this item type
    attrs = (
        db.query(ItemTypeAttribute)
        .filter(ItemTypeAttribute.item_type_id == item_type.id)
        .all()
    )

    attr_map = {a.slug: a for a in attrs}

    # Calculate modifiers for each attribute in the config
    for attr_slug, value in item_config.items():
        if attr_slug not in attr_map:
            continue

        attr = attr_map[attr_slug]

        # Handle different input types
        if attr.input_type == "single_select":
            # Single value
            if value and value != "none":
                total += get_attribute_option_price(db, item_type_slug, attr_slug, value)

        elif attr.input_type == "multi_select":
            # List of values
            if isinstance(value, list):
                for v in value:
                    total += get_attribute_option_price(db, item_type_slug, attr_slug, v)

        elif attr.input_type == "boolean":
            # Boolean doesn't typically have price modifiers
            pass

    return total


def build_item_type_menu_data(db: Session, item_type_slug: str) -> Dict[str, Any]:
    """
    Build menu data for an item type including all attributes and options.

    This is useful for building dynamic LLM prompts that describe what
    options are available for a given item type.

    Args:
        db: Database session
        item_type_slug: The item type slug

    Returns:
        Dict with item type info, attributes, and all options
    """
    item_type = get_item_type_by_slug(db, item_type_slug)
    if not item_type:
        return {}

    return {
        "slug": item_type.slug,
        "display_name": item_type.display_name,
        "is_configurable": item_type.is_configurable,
        "attributes": get_type_attributes(db, item_type.id, include_options=True),
    }


def get_available_options_for_attribute(
    db: Session,
    item_type_slug: str,
    attribute_slug: str,
    store_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get available options for an attribute, optionally filtered by store availability.

    Args:
        db: Database session
        item_type_slug: The item type slug
        attribute_slug: The attribute slug
        store_id: Optional store ID for availability filtering

    Returns:
        List of available option dicts
    """
    item_type = get_item_type_by_slug(db, item_type_slug)
    if not item_type:
        return []

    attr = (
        db.query(ItemTypeAttribute)
        .filter(
            ItemTypeAttribute.item_type_id == item_type.id,
            ItemTypeAttribute.slug == attribute_slug
        )
        .first()
    )
    if not attr:
        return []

    options = (
        db.query(AttributeOption)
        .filter(
            AttributeOption.item_type_attribute_id == attr.id,
            AttributeOption.is_available == True
        )
        .order_by(AttributeOption.display_order)
        .all()
    )

    return [
        {
            "slug": opt.slug,
            "display_name": opt.display_name,
            "price_modifier": opt.price_modifier,
            "is_default": opt.is_default,
        }
        for opt in options
    ]


def config_to_legacy_fields(item_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert generic item_config to legacy order item fields.

    This helps maintain backward compatibility during the migration period.

    Args:
        item_config: Generic configuration dict

    Returns:
        Dict with legacy field names
    """
    if not item_config:
        return {}

    return {
        "size": item_config.get("size"),
        "bread": item_config.get("bread"),
        "protein": item_config.get("protein"),
        "cheese": item_config.get("cheese"),
        "toppings": item_config.get("toppings", []),
        "sauces": item_config.get("sauces", []),
        "toasted": item_config.get("toasted"),
    }


def legacy_fields_to_config(
    size: str = None,
    bread: str = None,
    protein: str = None,
    cheese: str = None,
    toppings: List[str] = None,
    sauces: List[str] = None,
    toasted: bool = None
) -> Dict[str, Any]:
    """
    Convert legacy order item fields to generic item_config.

    Args:
        size, bread, protein, cheese, toppings, sauces, toasted: Legacy fields

    Returns:
        Generic configuration dict
    """
    config = {}

    if size is not None:
        config["size"] = size
    if bread is not None:
        config["bread"] = bread
    if protein is not None:
        config["protein"] = protein
    if cheese is not None:
        config["cheese"] = cheese
    if toppings is not None:
        config["toppings"] = toppings
    if sauces is not None:
        config["sauces"] = sauces
    if toasted is not None:
        config["toasted"] = toasted

    return config
