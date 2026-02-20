"""
Global Attribute Serializers.

Provides serialization functions for GlobalAttribute and related models.
"""

from sqlalchemy.orm import Session

from orderbot.db.models import (
    GlobalAttribute,
    GlobalAttributeOption,
    Ingredient,
    ItemTypeGlobalAttribute,
)
from orderbot.schemas.global_attributes import (
    GlobalAttributeOut,
    GlobalAttributeListOut,
    GlobalAttributeOptionOut,
    ItemTypeGlobalAttributeOut,
    LinkedItemTypeInfo,
    SkipRuleOutBasic,
)


def _derive_option_identity(
    opt: GlobalAttributeOption,
    db: Session | None,
) -> tuple[str, str, str | None, str | None]:
    """Derive (slug, display_name, ingredient_name, modifier_category_name) for an option.

    3-tier fallback: eager-loaded ingredient -> DB lookup -> option's own columns.
    """
    ingredient = getattr(opt, 'ingredient', None)

    # Tier 2: DB fallback
    if not ingredient and opt.ingredient_id and db:
        ingredient = db.query(Ingredient).filter(Ingredient.id == opt.ingredient_id).first()

    if ingredient:
        slug = ingredient.slug
        display_name = ingredient.name
        ingredient_name = ingredient.name
        mod_cat = ingredient.modifier_category.display_name if ingredient.modifier_category else None
    else:
        slug = opt.slug or f"option_{opt.id}"
        display_name = opt.display_name or f"Option {opt.id}"
        ingredient_name = None
        mod_cat = None

    return slug, display_name, ingredient_name, mod_cat


def _resolve_forward_attribute_slug(
    opt: GlobalAttributeOption,
    db: Session | None,
) -> str | None:
    """Resolve forward_to_attribute slug with eager-load -> DB fallback."""
    if hasattr(opt, 'forward_to_attribute') and opt.forward_to_attribute:
        return opt.forward_to_attribute.slug
    if opt.forward_to_attribute_id and db:
        forward_attr = db.query(GlobalAttribute).filter(
            GlobalAttribute.id == opt.forward_to_attribute_id
        ).first()
        if forward_attr:
            return forward_attr.slug
    return None


def serialize_global_attribute_option(
    opt: GlobalAttributeOption,
    db: Session | None = None
) -> GlobalAttributeOptionOut:
    """Convert GlobalAttributeOption model to response schema.

    Args:
        opt: The GlobalAttributeOption to serialize
        db: Optional database session for fallback ingredient lookup

    Returns:
        GlobalAttributeOptionOut schema
    """
    # Get aliases from the option's alias_records
    aliases_str = ", ".join(opt.aliases) if opt.aliases else None

    # Derive identity fields from ingredient (3-tier fallback)
    slug, display_name, ingredient_name, modifier_category_name = _derive_option_identity(opt, db)

    # Serialize skip rules
    skip_rules_out = []
    if hasattr(opt, 'skip_rules') and opt.skip_rules:
        for rule in opt.skip_rules:
            skip_rules_out.append(SkipRuleOutBasic(
                id=rule.id,
                skipped_attribute_id=rule.skipped_attribute_id,
                skipped_attribute_slug=rule.skipped_attribute.slug if rule.skipped_attribute else "",
                skipped_attribute_name=rule.skipped_attribute.display_name if rule.skipped_attribute else "",
            ))

    # Resolve forward_to_attribute slug (eager-load -> DB fallback)
    forward_to_attr_slug = _resolve_forward_attribute_slug(opt, db)

    return GlobalAttributeOptionOut(
        id=opt.id,
        slug=slug,
        display_name=display_name,
        price_modifier=float(opt.price_modifier or 0),
        is_default=opt.is_default,
        is_available=opt.is_available,
        display_order=opt.display_order,
        ingredient_id=opt.ingredient_id,
        ingredient_name=ingredient_name,
        modifier_category_name=modifier_category_name,
        aliases=aliases_str,
        skip_rules=skip_rules_out,
        forward_to_attribute_id=opt.forward_to_attribute_id,
        forward_to_attribute_slug=forward_to_attr_slug,
        created_at=opt.created_at,
        updated_at=opt.updated_at,
    )


def serialize_global_attribute(
    attr: GlobalAttribute,
    db: Session
) -> GlobalAttributeOut:
    """Convert GlobalAttribute model to response schema with options.

    Note: Requires attr.options and attr.item_type_links (with item_type)
    to be eager-loaded to avoid N+1 queries.

    Args:
        attr: The GlobalAttribute to serialize
        db: Database session for fallback lookups

    Returns:
        GlobalAttributeOut schema
    """
    options_out = [serialize_global_attribute_option(opt, db) for opt in attr.options]

    # Use eager-loaded relationship instead of separate queries
    linked_item_types = []
    for link in attr.item_type_links:
        item_type = link.item_type
        if item_type:
            linked_item_types.append(LinkedItemTypeInfo(
                id=item_type.id,
                slug=item_type.slug,
                display_name=item_type.display_name or item_type.slug.replace('_', ' ').title(),
            ))

    return GlobalAttributeOut(
        id=attr.id,
        slug=attr.slug,
        display_name=attr.display_name,
        input_type=attr.input_type,
        description=attr.description,
        question_text=attr.question_text,
        offer_question_text=attr.offer_question_text,
        options_source_category=attr.options_source_category,
        options=options_out,
        item_type_count=len(linked_item_types),
        linked_item_types=linked_item_types,
        created_at=attr.created_at,
        updated_at=attr.updated_at,
    )


def serialize_global_attribute_list(
    attr: GlobalAttribute,
    db: Session
) -> GlobalAttributeListOut:
    """Convert GlobalAttribute model to list response schema (no options).

    Note: Requires attr.options and attr.item_type_links to be eager-loaded
    to avoid N+1 queries.

    Args:
        attr: The GlobalAttribute to serialize
        db: Database session (unused but kept for API consistency)

    Returns:
        GlobalAttributeListOut schema
    """
    return GlobalAttributeListOut(
        id=attr.id,
        slug=attr.slug,
        display_name=attr.display_name,
        input_type=attr.input_type,
        description=attr.description,
        question_text=attr.question_text,
        offer_question_text=attr.offer_question_text,
        options_source_category=attr.options_source_category,
        option_count=len(attr.options),
        item_type_count=len(attr.item_type_links),
        created_at=attr.created_at,
        updated_at=attr.updated_at,
    )


def serialize_item_type_link(
    link: ItemTypeGlobalAttribute,
    db: Session
) -> ItemTypeGlobalAttributeOut:
    """Convert ItemTypeGlobalAttribute link to response schema.

    Args:
        link: The ItemTypeGlobalAttribute link to serialize
        db: Database session for fallback lookups

    Returns:
        ItemTypeGlobalAttributeOut schema
    """
    global_attr = link.global_attribute
    options_out = [serialize_global_attribute_option(opt, db) for opt in global_attr.options]

    return ItemTypeGlobalAttributeOut(
        id=link.id,
        item_type_id=link.item_type_id,
        item_type_slug=link.item_type.slug if link.item_type else None,
        global_attribute_id=link.global_attribute_id,
        global_attribute_slug=global_attr.slug,
        global_attribute_display_name=global_attr.display_name,
        input_type=global_attr.input_type,
        display_order=link.display_order,
        is_required=link.is_required,
        allow_none=link.allow_none,
        ask_in_conversation=link.ask_in_conversation,
        listen_only=link.listen_only,
        question_text=global_attr.question_text,
        offer_question_text=global_attr.offer_question_text,
        min_selections=link.min_selections,
        max_selections=link.max_selections,
        option_subcategory_filter=link.option_subcategory_filter,
        options=options_out,
        created_at=link.created_at,
        updated_at=link.updated_at,
    )
