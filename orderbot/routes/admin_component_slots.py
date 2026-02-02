"""
Admin routes for Component Slot management.

Component slots allow item types to include configurable sub-items.
For example, an omelette can include a "side" slot that accepts bagels or fruit salad.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..db.models import (
    ItemType,
    ItemTypeComponentSlot,
    ComponentSlotOption,
    MenuItem,
)
from ..auth import verify_admin_credentials

admin_component_slots_router = APIRouter(
    prefix="/admin/component-slots",
    tags=["Admin - Component Slots"],
    dependencies=[Depends(verify_admin_credentials)],
)


# =============================================================================
# Item Types with Component Slots
# =============================================================================

@admin_component_slots_router.get("/item-types")
def list_item_types_with_slots(db: Session = Depends(get_db)):
    """List all item types with their component slot counts."""
    item_types = (
        db.query(ItemType)
        .options(joinedload(ItemType.component_slots))
        .order_by(ItemType.display_name)
        .all()
    )

    return [
        {
            "id": it.id,
            "slug": it.slug,
            "display_name": it.display_name,
            "slot_count": len(it.component_slots) if it.component_slots else 0,
        }
        for it in item_types
    ]


@admin_component_slots_router.get("/item-types/{item_type_id}/slots")
def get_item_type_slots(item_type_id: int, db: Session = Depends(get_db)):
    """Get all component slots for an item type."""
    item_type = db.query(ItemType).filter(ItemType.id == item_type_id).first()
    if not item_type:
        raise HTTPException(status_code=404, detail="Item type not found")

    slots = (
        db.query(ItemTypeComponentSlot)
        .filter(ItemTypeComponentSlot.parent_item_type_id == item_type_id)
        .options(joinedload(ItemTypeComponentSlot.slot_options))
        .order_by(ItemTypeComponentSlot.display_order)
        .all()
    )

    return {
        "item_type": {
            "id": item_type.id,
            "slug": item_type.slug,
            "display_name": item_type.display_name,
        },
        "slots": [
            {
                "id": slot.id,
                "slot_name": slot.slot_name,
                "display_name": slot.display_name,
                "prompt_text": slot.prompt_text,
                "is_required": slot.is_required,
                "min_quantity": slot.min_quantity,
                "max_quantity": slot.max_quantity,
                "display_order": slot.display_order,
                "option_count": len(slot.slot_options) if slot.slot_options else 0,
            }
            for slot in slots
        ],
    }


# =============================================================================
# Component Slot CRUD
# =============================================================================

@admin_component_slots_router.post("/item-types/{item_type_id}/slots")
def create_component_slot(
    item_type_id: int,
    slot_name: str,
    display_name: Optional[str] = None,
    prompt_text: Optional[str] = None,
    is_required: bool = True,
    min_quantity: int = 1,
    max_quantity: int = 1,
    display_order: int = 0,
    db: Session = Depends(get_db),
):
    """Create a new component slot for an item type."""
    # Verify item type exists
    item_type = db.query(ItemType).filter(ItemType.id == item_type_id).first()
    if not item_type:
        raise HTTPException(status_code=404, detail="Item type not found")

    # Check for duplicate slot name
    existing = (
        db.query(ItemTypeComponentSlot)
        .filter(
            ItemTypeComponentSlot.parent_item_type_id == item_type_id,
            ItemTypeComponentSlot.slot_name == slot_name,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail=f"Slot '{slot_name}' already exists for this item type")

    slot = ItemTypeComponentSlot(
        parent_item_type_id=item_type_id,
        slot_name=slot_name,
        display_name=display_name or slot_name.replace("_", " ").title(),
        prompt_text=prompt_text,
        is_required=is_required,
        min_quantity=min_quantity,
        max_quantity=max_quantity,
        display_order=display_order,
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)

    return {
        "id": slot.id,
        "slot_name": slot.slot_name,
        "display_name": slot.display_name,
        "prompt_text": slot.prompt_text,
        "is_required": slot.is_required,
        "min_quantity": slot.min_quantity,
        "max_quantity": slot.max_quantity,
        "display_order": slot.display_order,
    }


@admin_component_slots_router.put("/slots/{slot_id}")
def update_component_slot(
    slot_id: int,
    slot_name: Optional[str] = None,
    display_name: Optional[str] = None,
    prompt_text: Optional[str] = None,
    is_required: Optional[bool] = None,
    min_quantity: Optional[int] = None,
    max_quantity: Optional[int] = None,
    display_order: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Update a component slot."""
    slot = db.query(ItemTypeComponentSlot).filter(ItemTypeComponentSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")

    if slot_name is not None:
        slot.slot_name = slot_name
    if display_name is not None:
        slot.display_name = display_name
    if prompt_text is not None:
        slot.prompt_text = prompt_text
    if is_required is not None:
        slot.is_required = is_required
    if min_quantity is not None:
        slot.min_quantity = min_quantity
    if max_quantity is not None:
        slot.max_quantity = max_quantity
    if display_order is not None:
        slot.display_order = display_order

    db.commit()
    db.refresh(slot)

    return {
        "id": slot.id,
        "slot_name": slot.slot_name,
        "display_name": slot.display_name,
        "prompt_text": slot.prompt_text,
        "is_required": slot.is_required,
        "min_quantity": slot.min_quantity,
        "max_quantity": slot.max_quantity,
        "display_order": slot.display_order,
    }


@admin_component_slots_router.delete("/slots/{slot_id}")
def delete_component_slot(slot_id: int, db: Session = Depends(get_db)):
    """Delete a component slot and all its options."""
    slot = db.query(ItemTypeComponentSlot).filter(ItemTypeComponentSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")

    db.delete(slot)
    db.commit()

    return {"success": True, "message": f"Deleted slot '{slot.slot_name}'"}


# =============================================================================
# Slot Option CRUD
# =============================================================================

@admin_component_slots_router.get("/slots/{slot_id}/options")
def get_slot_options(slot_id: int, db: Session = Depends(get_db)):
    """Get all options for a component slot."""
    slot = (
        db.query(ItemTypeComponentSlot)
        .filter(ItemTypeComponentSlot.id == slot_id)
        .options(
            joinedload(ItemTypeComponentSlot.slot_options).joinedload(ComponentSlotOption.allowed_item_type),
            joinedload(ItemTypeComponentSlot.slot_options).joinedload(ComponentSlotOption.allowed_menu_item),
        )
        .first()
    )
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")

    options = []
    for opt in sorted(slot.slot_options, key=lambda o: o.display_order):
        option_data = {
            "id": opt.id,
            "price_rule": opt.price_rule,
            "fixed_price": opt.fixed_price,
            "display_name": opt.display_name,
            "display_order": opt.display_order,
        }

        if opt.allowed_item_type:
            option_data["allowed_item_type_id"] = opt.allowed_item_type_id
            option_data["allowed_item_type_slug"] = opt.allowed_item_type.slug
            option_data["allowed_item_type_name"] = opt.allowed_item_type.display_name

        if opt.allowed_menu_item:
            option_data["allowed_menu_item_id"] = opt.allowed_menu_item_id
            option_data["allowed_menu_item_name"] = opt.allowed_menu_item.name

        options.append(option_data)

    return {
        "slot": {
            "id": slot.id,
            "slot_name": slot.slot_name,
            "display_name": slot.display_name,
        },
        "options": options,
    }


@admin_component_slots_router.post("/slots/{slot_id}/options")
def add_slot_option(
    slot_id: int,
    allowed_item_type_id: Optional[int] = None,
    allowed_menu_item_id: Optional[int] = None,
    price_rule: str = "included",
    fixed_price: Optional[int] = None,
    display_name: Optional[str] = None,
    display_order: int = 0,
    db: Session = Depends(get_db),
):
    """Add an option to a component slot."""
    slot = db.query(ItemTypeComponentSlot).filter(ItemTypeComponentSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")

    # Must have either item_type or menu_item
    if not allowed_item_type_id and not allowed_menu_item_id:
        raise HTTPException(
            status_code=400,
            detail="Must specify either allowed_item_type_id or allowed_menu_item_id"
        )

    # Validate references
    if allowed_item_type_id:
        item_type = db.query(ItemType).filter(ItemType.id == allowed_item_type_id).first()
        if not item_type:
            raise HTTPException(status_code=404, detail="Item type not found")
        if not display_name:
            display_name = item_type.display_name

    if allowed_menu_item_id:
        menu_item = db.query(MenuItem).filter(MenuItem.id == allowed_menu_item_id).first()
        if not menu_item:
            raise HTTPException(status_code=404, detail="Menu item not found")
        if not display_name:
            display_name = menu_item.name

    option = ComponentSlotOption(
        slot_id=slot_id,
        allowed_item_type_id=allowed_item_type_id,
        allowed_menu_item_id=allowed_menu_item_id,
        price_rule=price_rule,
        fixed_price=fixed_price,
        display_name=display_name,
        display_order=display_order,
    )
    db.add(option)
    db.commit()
    db.refresh(option)

    return {
        "id": option.id,
        "allowed_item_type_id": option.allowed_item_type_id,
        "allowed_menu_item_id": option.allowed_menu_item_id,
        "price_rule": option.price_rule,
        "fixed_price": option.fixed_price,
        "display_name": option.display_name,
        "display_order": option.display_order,
    }


@admin_component_slots_router.put("/options/{option_id}")
def update_slot_option(
    option_id: int,
    price_rule: Optional[str] = None,
    fixed_price: Optional[int] = None,
    display_name: Optional[str] = None,
    display_order: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Update a slot option."""
    option = db.query(ComponentSlotOption).filter(ComponentSlotOption.id == option_id).first()
    if not option:
        raise HTTPException(status_code=404, detail="Option not found")

    if price_rule is not None:
        option.price_rule = price_rule
    if fixed_price is not None:
        option.fixed_price = fixed_price
    if display_name is not None:
        option.display_name = display_name
    if display_order is not None:
        option.display_order = display_order

    db.commit()
    db.refresh(option)

    return {
        "id": option.id,
        "allowed_item_type_id": option.allowed_item_type_id,
        "allowed_menu_item_id": option.allowed_menu_item_id,
        "price_rule": option.price_rule,
        "fixed_price": option.fixed_price,
        "display_name": option.display_name,
        "display_order": option.display_order,
    }


@admin_component_slots_router.delete("/options/{option_id}")
def delete_slot_option(option_id: int, db: Session = Depends(get_db)):
    """Delete a slot option."""
    option = db.query(ComponentSlotOption).filter(ComponentSlotOption.id == option_id).first()
    if not option:
        raise HTTPException(status_code=404, detail="Option not found")

    db.delete(option)
    db.commit()

    return {"success": True, "message": "Deleted option"}


# =============================================================================
# Helper endpoints
# =============================================================================

@admin_component_slots_router.get("/available-item-types")
def list_available_item_types(db: Session = Depends(get_db)):
    """List all item types available for slot options."""
    item_types = (
        db.query(ItemType)
        .order_by(ItemType.display_name)
        .all()
    )
    return [
        {"id": it.id, "slug": it.slug, "display_name": it.display_name}
        for it in item_types
    ]


@admin_component_slots_router.get("/available-menu-items")
def list_available_menu_items(
    search: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List menu items available for slot options."""
    query = db.query(MenuItem).order_by(MenuItem.name)

    if search:
        query = query.filter(MenuItem.name.ilike(f"%{search}%"))

    menu_items = query.limit(limit).all()
    return [
        {"id": mi.id, "name": mi.name}
        for mi in menu_items
    ]
