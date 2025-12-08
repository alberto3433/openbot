from typing import Dict, Any

from sqlalchemy.orm import Session

from .models import MenuItem, Order, OrderItem


class OutOfStockError(Exception):
    """Raised when there is not enough inventory to fulfill an item."""

    def __init__(self, item_name: str, requested: int, available: int):
        self.item_name = item_name
        self.requested = requested
        self.available = available
        super().__init__(
            f"Not enough inventory for {item_name}: requested {requested}, available {available}"
        )


def apply_inventory_decrement_on_confirm(db: Session, order_state: Dict[str, Any]) -> None:
    """Decrement inventory based on the items in order_state.

    Additionally, if the order_state is marked as confirmed (status == 'confirmed'),
    persist an Order + OrderItem rows in the database.

    This function will:

    1. Verify that inventory is sufficient for each line item.
       - If not, raise OutOfStockError and leave DB unchanged.
    2. Decrement MenuItem.available_qty for each fulfilled line item.
    3. If order_state['status'] == 'confirmed', create an Order row and
       associated OrderItem rows, and attach the created order_id back onto
       the order_state (order_state['order_id']).

    The caller is responsible for catching OutOfStockError and handling it
    (e.g., adjusting reply to user). On success, this function commits the
    transaction.
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
            # If the menu item does not exist in DB, treat as non-inventory-tracked
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

    # 3) Persist Order / OrderItems if this is a confirmed order
    if order_state.get("status") == "confirmed":
        order = Order(
            status="confirmed",
            customer_name=order_state.get("customer_name"),
            phone=order_state.get("phone"),
            pickup_time=order_state.get("pickup_time"),
            total_price=order_state.get("total_price", 0.0),
        )
        db.add(order)
        db.flush()  # populate order.id

        for item in items:
            name = item.get("menu_item_name")
            quantity = item.get("quantity") or 0

            if not name or quantity <= 0:
                continue

            menu_item = db.query(MenuItem).filter_by(name=name).one_or_none()

            order_item = OrderItem(
                order_id=order.id,
                menu_item_id=menu_item.id if menu_item is not None else None,
                menu_item_name=name,
                quantity=quantity,
                unit_price=item.get("unit_price", 0.0),
                line_total=item.get("line_total", 0.0),
                extra={
                    "size": item.get("size"),
                    "bread": item.get("bread"),
                    "protein": item.get("protein"),
                    "cheese": item.get("cheese"),
                    "toppings": item.get("toppings", []),
                    "sauces": item.get("sauces", []),
                    "toasted": item.get("toasted"),
                },
            )
            db.add(order_item)

        # Expose the persisted order ID back on the in-memory order_state
        order_state["order_id"] = order.id

    # 4) Commit all changes (inventory + order persistence)
    db.commit()
