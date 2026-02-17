"""
Alias Service
=============

Functions for alias validation, uniqueness checking, and syncing across
all entity types (Ingredient, MenuItem, ItemType, ModifierCategory, GlobalAttributeOption).

Functions:
- check_alias_uniqueness: Check if an alias is globally unique
- validate_aliases: Validate and return list of unique aliases
- sync_entity_aliases: Sync aliases for any entity type from comma-separated string
"""

import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db.models import (
    GlobalAttributeOptionAlias,
    IngredientAlias,
    ItemTypeAlias,
    MenuItemAlias,
    ModifierCategoryAlias,
)


logger = logging.getLogger(__name__)


# =============================================================================
# Entity Type Configuration for Alias Syncing
# =============================================================================

# Maps entity type to (AliasModel, FK column name, validate_aliases exclude param name)
_ALIAS_CONFIG = {
    "ingredient": (IngredientAlias, "ingredient_id", "exclude_ingredient_id"),
    "menu_item": (MenuItemAlias, "menu_item_id", "exclude_menu_item_id"),
    "modifier_category": (ModifierCategoryAlias, "modifier_category_id", "exclude_modifier_category_id"),
    "item_type": (ItemTypeAlias, "item_type_id", "exclude_item_type_id"),
    "global_attribute_option": (GlobalAttributeOptionAlias, "global_attribute_option_id", "exclude_global_attr_option_id"),
}


def _check_alias_in_table(
    db: Session,
    alias_model: type,
    alias_lower: str,
    exclude_id: int | None,
    fk_column_name: str,
    entity_type_name: str,
    entity_name_accessor: str,
) -> tuple[bool, str | None]:
    """Check for alias collision in a single alias table.

    Generic helper that checks if an alias already exists in an alias table,
    optionally excluding a specific entity ID (for update operations).

    Args:
        db: Database session
        alias_model: The alias model class (e.g., ItemTypeAlias)
        alias_lower: Lowercase alias to search for
        exclude_id: Entity ID to exclude from search (for updates)
        fk_column_name: Name of the FK column (e.g., "item_type_id")
        entity_type_name: Human-readable entity type (e.g., "ItemType")
        entity_name_accessor: Attribute path to get entity name (e.g., "item_type.slug")

    Returns:
        Tuple of (is_unique, conflict_message)
        - (True, None) if no collision
        - (False, message) if collision found
    """
    query = db.query(alias_model).filter(
        func.lower(alias_model.alias) == alias_lower
    )
    if exclude_id:
        query = query.filter(getattr(alias_model, fk_column_name) != exclude_id)
    existing = query.first()
    if existing:
        # Navigate the attribute path (e.g., "item_type.slug" or "option.display_name")
        entity_name = existing
        for attr in entity_name_accessor.split("."):
            entity_name = getattr(entity_name, attr, None)
        return False, f"Alias already exists on {entity_type_name} '{entity_name}'"
    return True, None


def check_alias_uniqueness(
    db: Session,
    alias: str,
    exclude_item_type_id: int | None = None,
    exclude_menu_item_id: int | None = None,
    exclude_modifier_category_id: int | None = None,
    exclude_ingredient_id: int | None = None,
    exclude_global_attr_option_id: int | None = None,
) -> tuple[bool, str | None]:
    """
    Check if an alias is globally unique across all alias tables.

    Aliases must be unique across all entity types (ItemType, MenuItem,
    ModifierCategory, Ingredient, GlobalAttributeOption) to prevent ambiguous lookups.

    Args:
        db: Database session
        alias: The alias to check (case-insensitive)
        exclude_item_type_id: ItemType ID to exclude (for updates)
        exclude_menu_item_id: MenuItem ID to exclude (for updates)
        exclude_modifier_category_id: ModifierCategory ID to exclude (for updates)
        exclude_ingredient_id: Ingredient ID to exclude (for updates)
        exclude_global_attr_option_id: GlobalAttributeOption ID to exclude (for updates)

    Returns:
        Tuple of (is_unique, conflict_message)
        - (True, None) if alias is unique
        - (False, "Alias 'x' already exists on ItemType 'y'") if duplicate found
    """
    alias_lower = alias.strip().lower()
    if not alias_lower:
        return True, None

    # Configuration for each alias table to check
    alias_tables = [
        (ItemTypeAlias, exclude_item_type_id, "item_type_id", "ItemType", "item_type.slug"),
        (MenuItemAlias, exclude_menu_item_id, "menu_item_id", "MenuItem", "menu_item.name"),
        (ModifierCategoryAlias, exclude_modifier_category_id, "modifier_category_id", "ModifierCategory", "modifier_category.slug"),
        (IngredientAlias, exclude_ingredient_id, "ingredient_id", "Ingredient", "ingredient.name"),
        (GlobalAttributeOptionAlias, exclude_global_attr_option_id, "global_attribute_option_id", "GlobalAttributeOption", "option.display_name"),
    ]

    for alias_model, exclude_id, fk_column, entity_type, name_accessor in alias_tables:
        is_unique, message = _check_alias_in_table(
            db, alias_model, alias_lower, exclude_id, fk_column, entity_type, name_accessor
        )
        if not is_unique:
            return False, message

    return True, None


def validate_aliases(
    db: Session,
    aliases_str: str | None,
    exclude_item_type_id: int | None = None,
    exclude_menu_item_id: int | None = None,
    exclude_modifier_category_id: int | None = None,
    exclude_ingredient_id: int | None = None,
    exclude_global_attr_option_id: int | None = None,
) -> list[str]:
    """
    Validate and return list of globally unique aliases.

    Parses comma-separated aliases string, validates each is globally unique,
    and returns the list of valid aliases. Raises ValueError if any alias
    is a duplicate.

    Args:
        db: Database session
        aliases_str: Comma-separated aliases string
        exclude_item_type_id: ItemType ID to exclude (for updates)
        exclude_menu_item_id: MenuItem ID to exclude (for updates)
        exclude_modifier_category_id: ModifierCategory ID to exclude (for updates)
        exclude_ingredient_id: Ingredient ID to exclude (for updates)
        exclude_global_attr_option_id: GlobalAttributeOption ID to exclude (for updates)

    Returns:
        List of validated aliases

    Raises:
        ValueError if any alias is not globally unique
    """
    if not aliases_str:
        return []

    aliases = []
    errors = []
    for alias in aliases_str.split(","):
        alias = alias.strip()
        if not alias:
            continue

        is_unique, error_msg = check_alias_uniqueness(
            db,
            alias,
            exclude_item_type_id=exclude_item_type_id,
            exclude_menu_item_id=exclude_menu_item_id,
            exclude_modifier_category_id=exclude_modifier_category_id,
            exclude_ingredient_id=exclude_ingredient_id,
            exclude_global_attr_option_id=exclude_global_attr_option_id,
        )
        if not is_unique:
            errors.append(error_msg)
        else:
            aliases.append(alias)

    if errors:
        raise ValueError("; ".join(errors))

    return aliases


def sync_entity_aliases(
    db: Session,
    entity: Any,
    aliases_str: str | None,
    entity_type: str,
) -> None:
    """
    Sync aliases for any entity type from a comma-separated string.

    This is a generic helper that consolidates the duplicate alias-handling
    logic across multiple admin routes. It:
    1. Clears existing aliases via the entity's `alias_records` relationship
    2. Flushes to avoid unique constraint violations
    3. Validates new aliases are globally unique
    4. Creates new alias records

    Args:
        db: Database session
        entity: The parent entity (Ingredient, MenuItem, ItemType, etc.)
        aliases_str: Comma-separated aliases string (or None to clear all)
        entity_type: One of "ingredient", "menu_item", "modifier_category",
                     "item_type", or "global_attribute_option"

    Raises:
        HTTPException: If any alias conflicts with an existing alias
        ValueError: If entity_type is not recognized

    Example:
        >>> sync_entity_aliases(db, ingredient, "swiss, swiss cheese", "ingredient")
    """
    if entity_type not in _ALIAS_CONFIG:
        raise ValueError(f"Unknown entity_type: {entity_type}. Must be one of {list(_ALIAS_CONFIG.keys())}")

    alias_model, fk_column, exclude_param = _ALIAS_CONFIG[entity_type]

    # Clear existing aliases via the entity's alias_records relationship
    for alias_record in list(entity.alias_records):
        db.delete(alias_record)

    # Flush deletes before inserting new records to avoid unique constraint violations
    db.flush()

    # Validate and add new aliases if provided
    if aliases_str:
        try:
            # Pass the entity's ID as the exclude parameter so re-saving same aliases works
            validated_aliases = validate_aliases(
                db,
                aliases_str,
                **{exclude_param: entity.id},
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        for alias in validated_aliases:
            # Create alias record using the FK column name
            alias_record = alias_model(**{fk_column: entity.id, "alias": alias})
            db.add(alias_record)
