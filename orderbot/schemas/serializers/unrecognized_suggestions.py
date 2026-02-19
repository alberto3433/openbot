"""
Unrecognized Suggestions Serializers.

Provides serialization functions for UnrecognizedMenuItemSuggestion and
UnrecognizedIngredientSuggestion models that need relationship traversal.
"""

from orderbot.db.models import UnrecognizedMenuItemSuggestion, UnrecognizedIngredientSuggestion
from orderbot.schemas.unrecognized_suggestions import (
    UnrecognizedMenuItemSuggestionOut,
    UnrecognizedIngredientSuggestionOut,
)


def serialize_menu_item_suggestion(
    db_obj: UnrecognizedMenuItemSuggestion,
) -> UnrecognizedMenuItemSuggestionOut:
    """Serialize a menu item suggestion with relationships.

    Traverses suggested_item_type and suggested_menu_items relationships
    to populate slug/name fields that aren't direct columns.
    """
    item_type_slug = None
    if db_obj.suggested_item_type:
        item_type_slug = db_obj.suggested_item_type.slug

    menu_item_names = None
    if db_obj.suggested_menu_items:
        menu_item_names = [item.name for item in db_obj.suggested_menu_items]

    return UnrecognizedMenuItemSuggestionOut(
        id=db_obj.id,
        input_pattern=db_obj.input_pattern,
        match_type=db_obj.match_type,
        suggested_item_type_id=db_obj.suggested_item_type_id,
        suggested_item_type_slug=item_type_slug,
        suggested_menu_item_names=menu_item_names,
        hit_count=db_obj.hit_count,
        is_active=db_obj.is_active,
        created_at=db_obj.created_at,
    )


def serialize_ingredient_suggestion(
    db_obj: UnrecognizedIngredientSuggestion,
) -> UnrecognizedIngredientSuggestionOut:
    """Serialize an ingredient suggestion with relationships.

    Traverses alternative_ingredients relationship to populate
    alternative_ingredient_names.
    """
    alt_names = None
    if db_obj.alternative_ingredients:
        alt_names = [ing.name for ing in db_obj.alternative_ingredients]

    return UnrecognizedIngredientSuggestionOut(
        id=db_obj.id,
        input_pattern=db_obj.input_pattern,
        match_type=db_obj.match_type,
        suggested_display_name=db_obj.suggested_display_name,
        modifier_category=db_obj.modifier_category,
        alternative_ingredient_names=alt_names,
        hit_count=db_obj.hit_count,
        is_active=db_obj.is_active,
        created_at=db_obj.created_at,
    )
