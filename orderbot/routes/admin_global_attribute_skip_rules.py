"""
Admin Global Attribute Option Skip Rule Routes
===============================================

This module contains admin endpoints for managing skip rules on global
attribute options.  Split from admin_global_attribute_options.py for
maintainability.

Endpoints:
----------
- GET  /{attr_id}/options/{option_id}/skip-rules: List skip rules
- POST /{attr_id}/options/{option_id}/skip-rules: Add a skip rule
- DELETE /{attr_id}/options/{option_id}/skip-rules/{rule_id}: Delete a skip rule

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.
"""

import logging

from fastapi import Depends
from sqlalchemy.orm import Session, joinedload

from ..auth import verify_admin_credentials
from ..db import get_db
from ..exceptions import ResourceNotFoundError, ValidationError
from ..db.models import GlobalAttribute, GlobalAttributeOption, GlobalAttributeOptionSkip
from ..schemas.global_attributes import SkipRuleOut, SkipRuleCreate
from .admin_global_attributes import admin_global_attributes_router
from .crud_helpers import get_or_404

logger = logging.getLogger(__name__)


@admin_global_attributes_router.get(
    "/{attr_id}/options/{option_id}/skip-rules",
    response_model=list[SkipRuleOut],
    summary="List skip rules for an option"
)
def list_option_skip_rules(
    attr_id: int,
    option_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> list[SkipRuleOut]:
    """List all skip rules for a global attribute option."""
    # Verify attribute exists
    attr = get_or_404(db, GlobalAttribute, attr_id, detail="Global attribute not found")

    # Verify option exists and belongs to attribute
    option = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.id == option_id,
        GlobalAttributeOption.global_attribute_id == attr_id
    ).first()
    if not option:
        raise ResourceNotFoundError("Option not found")

    # Get skip rules with skipped_attribute relationship
    rules = (
        db.query(GlobalAttributeOptionSkip)
        .options(joinedload(GlobalAttributeOptionSkip.skipped_attribute))
        .filter(GlobalAttributeOptionSkip.triggering_option_id == option_id)
        .all()
    )

    return [
        SkipRuleOut(
            id=rule.id,
            skipped_attribute_id=rule.skipped_attribute_id,
            skipped_attribute_slug=rule.skipped_attribute.slug,
            skipped_attribute_name=rule.skipped_attribute.display_name,
        )
        for rule in rules
    ]


@admin_global_attributes_router.post(
    "/{attr_id}/options/{option_id}/skip-rules",
    response_model=SkipRuleOut,
    status_code=201,
    summary="Add a skip rule to an option"
)
def create_option_skip_rule(
    attr_id: int,
    option_id: int,
    payload: SkipRuleCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> SkipRuleOut:
    """Add a skip rule to a global attribute option."""
    # Verify attribute exists
    attr = get_or_404(db, GlobalAttribute, attr_id, detail="Global attribute not found")

    # Verify option exists and belongs to attribute
    option = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.id == option_id,
        GlobalAttributeOption.global_attribute_id == attr_id
    ).first()
    if not option:
        raise ResourceNotFoundError("Option not found")

    # Verify skipped attribute exists
    skipped_attr = get_or_404(db, GlobalAttribute, payload.skipped_attribute_id, detail="Skipped attribute not found")

    # Check if skip rule already exists
    existing = db.query(GlobalAttributeOptionSkip).filter(
        GlobalAttributeOptionSkip.triggering_option_id == option_id,
        GlobalAttributeOptionSkip.skipped_attribute_id == payload.skipped_attribute_id
    ).first()
    if existing:
        raise ValidationError(
            f"Skip rule for attribute '{skipped_attr.display_name}' already exists"
        )

    # Create the skip rule
    rule = GlobalAttributeOptionSkip(
        triggering_option_id=option_id,
        skipped_attribute_id=payload.skipped_attribute_id,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    logger.info(
        "Created skip rule: option %d (%s) skips attribute %d (%s)",
        option_id,
        option.slug or f"option_{option.id}",
        skipped_attr.id,
        skipped_attr.slug,
    )

    return SkipRuleOut(
        id=rule.id,
        skipped_attribute_id=rule.skipped_attribute_id,
        skipped_attribute_slug=skipped_attr.slug,
        skipped_attribute_name=skipped_attr.display_name,
    )


@admin_global_attributes_router.delete(
    "/{attr_id}/options/{option_id}/skip-rules/{rule_id}",
    status_code=204,
    summary="Delete a skip rule"
)
def delete_option_skip_rule(
    attr_id: int,
    option_id: int,
    rule_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete a skip rule from a global attribute option."""
    # Verify attribute exists
    attr = get_or_404(db, GlobalAttribute, attr_id, detail="Global attribute not found")

    # Verify option exists and belongs to attribute
    option = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.id == option_id,
        GlobalAttributeOption.global_attribute_id == attr_id
    ).first()
    if not option:
        raise ResourceNotFoundError("Option not found")

    # Find and delete the skip rule
    rule = db.query(GlobalAttributeOptionSkip).filter(
        GlobalAttributeOptionSkip.id == rule_id,
        GlobalAttributeOptionSkip.triggering_option_id == option_id
    ).first()
    if not rule:
        raise ResourceNotFoundError("Skip rule not found")

    logger.info(
        "Deleting skip rule %d from option %d",
        rule_id,
        option_id,
    )
    db.delete(rule)
    db.commit()
    return None
