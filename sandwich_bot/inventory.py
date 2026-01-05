from typing import Dict, Any

from sqlalchemy.orm import Session

from .models import MenuItem


class OutOfStockError(Exception):
    """Raised when there is not enough inventory to fulfill an item."""

    def __init__(self, item_name: str, requested: int, available: int):
        self.item_name = item_name
        self.requested = requested
        self.available = available
        if available == 0:
            message = f"Sorry, {item_name} is currently out of stock."
        else:
            message = f"Sorry, we only have {available} {item_name}(s) available, but you requested {requested}."
        super().__init__(message)


def check_inventory_for_item(db: Session, item_name: str, quantity: int = 1) -> None:
    """Check if enough inventory exists for an item before adding to order.

    Raises OutOfStockError if not enough inventory.
    """
    if not item_name or quantity <= 0:
        return

    menu_item = db.query(MenuItem).filter_by(name=item_name).one_or_none()
    if menu_item is None:
        # Item not in database - allow it (might be a custom item or typo)
        return

    if menu_item.available_qty < quantity:
        raise OutOfStockError(item_name, quantity, menu_item.available_qty)


def apply_inventory_decrement_on_confirm(db: Session, order_state: Dict[str, Any]) -> None:
    """Decrement inventory based on the items in order_state.

    This function ONLY:
      1. Validates that enough inventory exists for each item.
      2. Decrements MenuItem.available_qty for each fulfilled line item.

    It does NOT create or update Order / OrderItem rows anymore.
    Persistence of the order is handled separately by persist_confirmed_order().
    """
    items = order_state.get("items", [])

    # 1) Validation pass: ensure enough inventory exists
    for item in items:
        name = item.get("menu_item_name")
        quantity = item.get("quantity") or 0

        if not name or quantity <= 0:
            continue

        menu_item = db.query(MenuItem).filter_by(name=name).one_or_none()
        if menu_item is None:
            # treat as non-inventory-tracked
            continue

        if menu_item.available_qty < quantity:
            raise OutOfStockError(name, quantity, menu_item.available_qty)

    # 2) Apply decrements
    for item in items:
        name = item.get("menu_item_name")
        quantity = item.get("quantity") or 0

        if not name or quantity <= 0:
            continue

        menu_item = db.query(MenuItem).filter_by(name=name).one_or_none()
        if menu_item is None:
            continue

        menu_item.available_qty -= quantity

    # 3) Commit only inventory changes
    db.commit()

